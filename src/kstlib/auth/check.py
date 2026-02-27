"""JWT token validation with cryptographic proof.

Validates any RSA-signed JWT whose issuer exposes an OpenID Connect discovery
endpoint (`.well-known/openid-configuration`). This covers both OIDC id_tokens
and OAuth2 access_tokens issued as JWTs by OIDC-capable providers.

Example:
    >>> from kstlib.auth.check import TokenChecker  # doctest: +SKIP
    >>> checker = TokenChecker(http_client)  # doctest: +SKIP
    >>> report = checker.check("eyJhbGci...")  # doctest: +SKIP
    >>> report.valid  # doctest: +SKIP
    True
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Clock skew tolerance for claim validation (seconds)
CLOCK_SKEW_SECONDS = 300

_STEPS = (
    "_decode_structure",
    "_discover_issuer",
    "_fetch_jwks",
    "_extract_public_key",
    "_verify_signature",
    "_validate_claims",
)


@dataclass(frozen=True, slots=True)
class ValidationStep:
    """Result of a single validation step.

    Attributes:
        name: Step identifier (e.g. "decode_structure", "verify_signature").
        passed: Whether the step succeeded.
        message: Human-readable result description.
        details: Optional extra information for verbose output.
    """

    name: str
    passed: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TokenCheckReport:
    """Complete token validation report.

    Attributes:
        token_type: Whether "id_token" or "access_token" was checked.
        valid: Overall result (True only if ALL steps passed).
        steps: Ordered list of validation steps executed.
        header: Decoded JWT header (alg, kid, typ, ...).
        payload: Decoded JWT payload (claims).
        signature_algorithm: Algorithm from JWT header (e.g. "RS256", "RS512").
        key_id: Key ID from JWT header (kid).
        discovery_url: OpenID Connect discovery URL used.
        discovery_data: Relevant fields from discovery document.
        jwks_uri: JWKS endpoint URL.
        public_key_pem: PEM-encoded public key used for verification.
        key_fingerprint: SHA-256 fingerprint of the public key (hex).
        issuer_match: Whether iss claim matches expected issuer.
        audience_match: Whether aud claim matches expected audience.
        error: Error message if validation failed.
    """

    token_type: str = "id_token"
    valid: bool = False
    steps: list[ValidationStep] = field(default_factory=list)
    header: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)
    signature_algorithm: str | None = None
    key_id: str | None = None
    discovery_url: str | None = None
    discovery_data: dict[str, Any] = field(default_factory=dict)
    jwks_uri: str | None = None
    jwks_data: dict[str, Any] = field(default_factory=dict)
    public_key_pem: str | None = None
    key_fingerprint: str | None = None
    key_type: str | None = None
    key_size_bits: int | None = None
    x509_info: dict[str, Any] = field(default_factory=dict)
    issuer_match: bool | None = None
    audience_match: bool | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize report to dictionary for JSON output.

        Returns:
            Dictionary representation of the report.
        """
        return {
            "token_type": self.token_type,
            "valid": self.valid,
            "steps": [
                {
                    "name": s.name,
                    "passed": s.passed,
                    "message": s.message,
                    "details": s.details,
                }
                for s in self.steps
            ],
            "header": self.header,
            "payload": self.payload,
            "signature_algorithm": self.signature_algorithm,
            "key_id": self.key_id,
            "discovery_url": self.discovery_url,
            "discovery_data": self.discovery_data,
            "jwks_uri": self.jwks_uri,
            "public_key_pem": self.public_key_pem,
            "key_fingerprint": self.key_fingerprint,
            "key_type": self.key_type,
            "key_size_bits": self.key_size_bits,
            "x509_info": self.x509_info or None,
            "issuer_match": self.issuer_match,
            "audience_match": self.audience_match,
            "error": self.error,
        }


class TokenChecker:
    """Validates JWT tokens with full cryptographic verification.

    Runs a 6-step validation chain:
      1. Decode JWT structure (header + payload)
      2. Discover issuer (OIDC discovery document)
      3. Fetch JWKS (JSON Web Key Set)
      4. Extract public key (JWK to PEM, SHA-256 fingerprint)
      5. Verify signature (cryptographic proof)
      6. Validate claims (iss, aud, exp, iat, nbf)

    Args:
        http_client: httpx.Client for HTTP requests.
        expected_issuer: Expected issuer URL (for claim validation). If None,
            the issuer from the token payload is used.
        expected_audience: Expected audience (client_id). If None, audience
            validation is skipped.

    Example:
        >>> import httpx  # doctest: +SKIP
        >>> client = httpx.Client(verify="/path/to/ca.pem")  # doctest: +SKIP
        >>> checker = TokenChecker(client, expected_audience="my-app")  # doctest: +SKIP
        >>> report = checker.check(token_string)  # doctest: +SKIP
    """

    def __init__(
        self,
        http_client: httpx.Client,
        expected_issuer: str | None = None,
        expected_audience: str | None = None,
    ) -> None:
        self._http = http_client
        self._expected_issuer = expected_issuer
        self._expected_audience = expected_audience
        self._jwks_cache: dict[str, Any] | None = None

    def check(
        self,
        token_str: str,
        *,
        token_type: str = "id_token",  # noqa: S107
    ) -> TokenCheckReport:
        """Run full token validation chain.

        Args:
            token_str: Raw JWT string to validate.
            token_type: Label for the report ("id_token" or "access_token").

        Returns:
            TokenCheckReport with all validation results.
        """
        report = TokenCheckReport(token_type=token_type)
        self._token_str = token_str

        for step_name in _STEPS:
            step_fn = getattr(self, step_name)
            if not step_fn(report):
                return report

        report.valid = True
        return report

    def _decode_structure(self, report: TokenCheckReport) -> bool:
        """Step 1: Split JWT and decode header/payload."""
        try:
            parts = self._token_str.split(".")
            if len(parts) != 3:
                report.steps.append(
                    _fail_step(
                        "decode_structure",
                        f"Invalid JWT format: expected 3 parts, got {len(parts)}",
                    )
                )
                report.error = report.steps[-1].message
                return False

            header = json.loads(_b64url_decode(parts[0]))
            payload = json.loads(_b64url_decode(parts[1]))

            report.header = header
            report.payload = payload
            report.signature_algorithm = header.get("alg")
            report.key_id = header.get("kid")

            report.steps.append(
                ValidationStep(
                    name="decode_structure",
                    passed=True,
                    message=f"JWT decoded: alg={header.get('alg')}, kid={header.get('kid')}",
                    details={
                        "alg": header.get("alg"),
                        "kid": header.get("kid"),
                        "typ": header.get("typ"),
                        "claims": list(payload.keys()),
                    },
                )
            )

        except Exception as exc:
            report.steps.append(_fail_step("decode_structure", f"Failed to decode JWT: {exc}"))
            report.error = report.steps[-1].message
            return False

        return True

    def _discover_issuer(self, report: TokenCheckReport) -> bool:
        """Step 2: Fetch OIDC discovery document from issuer."""
        issuer = report.payload.get("iss")
        if not issuer:
            report.steps.append(_fail_step("discover_issuer", "No 'iss' claim found in token payload"))
            report.error = report.steps[-1].message
            return False

        discovery_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
        report.discovery_url = discovery_url

        try:
            resp = self._http.get(discovery_url, timeout=10)
            resp.raise_for_status()
            discovery = resp.json()

            jwks_uri = discovery.get("jwks_uri")
            supported_algs = discovery.get("id_token_signing_alg_values_supported", [])

            report.discovery_data = {
                "issuer": discovery.get("issuer"),
                "jwks_uri": jwks_uri,
                "id_token_signing_alg_values_supported": supported_algs,
                "authorization_endpoint": discovery.get("authorization_endpoint"),
                "token_endpoint": discovery.get("token_endpoint"),
            }
            report.jwks_uri = jwks_uri

            report.steps.append(
                ValidationStep(
                    name="discover_issuer",
                    passed=True,
                    message=f"Discovery OK: {discovery_url}",
                    details={"issuer": discovery.get("issuer"), "supported_algs": supported_algs, "jwks_uri": jwks_uri},
                )
            )

        except httpx.HTTPStatusError as exc:
            return _record_http_error(
                report, "discover_issuer", f"Discovery failed: HTTP {exc.response.status_code} from {discovery_url}"
            )
        except httpx.RequestError as exc:
            return _record_http_error(report, "discover_issuer", f"Discovery failed: {exc}")

        return True

    def _fetch_jwks(self, report: TokenCheckReport) -> bool:
        """Step 3: Fetch JSON Web Key Set from jwks_uri."""
        jwks_uri = report.jwks_uri
        if not jwks_uri:
            report.steps.append(_fail_step("fetch_jwks", "No jwks_uri found in discovery document"))
            report.error = report.steps[-1].message
            return False

        # Use cache if available
        if self._jwks_cache is not None:
            report.jwks_data = self._jwks_cache
            report.steps.append(
                ValidationStep(
                    name="fetch_jwks",
                    passed=True,
                    message="JWKS loaded from cache",
                    details={"key_count": len(self._jwks_cache.get("keys", []))},
                )
            )
            return True

        try:
            resp = self._http.get(jwks_uri, timeout=10)
            resp.raise_for_status()
            jwks = resp.json()

            self._jwks_cache = jwks
            report.jwks_data = jwks
            key_count = len(jwks.get("keys", []))

            report.steps.append(
                ValidationStep(
                    name="fetch_jwks",
                    passed=True,
                    message=f"JWKS fetched: {key_count} key(s) from {jwks_uri}",
                    details={"key_count": key_count, "key_ids": [k.get("kid", "no-kid") for k in jwks.get("keys", [])]},
                )
            )

        except httpx.HTTPStatusError as exc:
            return _record_http_error(
                report, "fetch_jwks", f"JWKS fetch failed: HTTP {exc.response.status_code} from {jwks_uri}"
            )
        except httpx.RequestError as exc:
            return _record_http_error(report, "fetch_jwks", f"JWKS fetch failed: {exc}")

        return True

    def _extract_public_key(self, report: TokenCheckReport) -> bool:
        """Step 4: Match key by kid and convert JWK to PEM."""
        kid = report.key_id
        keys = report.jwks_data.get("keys", [])

        if not keys:
            report.steps.append(_fail_step("extract_public_key", "JWKS contains no keys"))
            report.error = report.steps[-1].message
            return False

        matching_key = _find_matching_key(keys, kid)

        if matching_key is None:
            available_kids = [k.get("kid", "no-kid") for k in keys]
            report.steps.append(_fail_step("extract_public_key", f"Key not found: kid={kid!r} not in {available_kids}"))
            report.error = report.steps[-1].message
            return False

        try:
            pem_str, fingerprint, key_size = _jwk_to_pem(matching_key)

            report.public_key_pem = pem_str
            report.key_fingerprint = fingerprint
            report.key_type = matching_key.get("kty", "unknown")
            report.key_size_bits = key_size

            # Extract X.509 certificate info if x5c is present
            x5c = matching_key.get("x5c")
            if x5c:
                report.x509_info = _parse_x509_info(x5c[0])

            kty = report.key_type
            size_label = f" {key_size}-bit" if key_size else ""
            msg = f"Public key extracted: {kty}{size_label}, kid={kid}, fingerprint={fingerprint[:16]}..."

            report.steps.append(
                ValidationStep(
                    name="extract_public_key",
                    passed=True,
                    message=msg,
                    details={
                        "kid": kid,
                        "kty": kty,
                        "key_size_bits": key_size,
                        "alg": matching_key.get("alg"),
                        "fingerprint_sha256": fingerprint,
                        "has_x509": bool(x5c),
                    },
                )
            )

        except ImportError:
            report.steps.append(
                _fail_step("extract_public_key", "authlib is required for key extraction (pip install authlib)")
            )
            report.error = report.steps[-1].message
            return False
        except Exception as exc:
            report.steps.append(_fail_step("extract_public_key", f"Failed to extract public key: {exc}"))
            report.error = report.steps[-1].message
            return False

        return True

    def _verify_signature(self, report: TokenCheckReport) -> bool:
        """Step 5: Verify JWT signature using JWKS."""
        try:
            from authlib.jose import jwt
            from authlib.jose.errors import JoseError

            jwt.decode(
                self._token_str,
                report.jwks_data,
            )

            report.steps.append(
                ValidationStep(
                    name="verify_signature",
                    passed=True,
                    message=f"Signature valid ({report.signature_algorithm})",
                    details={"algorithm": report.signature_algorithm},
                )
            )

        except ImportError:
            report.steps.append(_fail_step("verify_signature", "authlib is required for signature verification"))
            report.error = report.steps[-1].message
            return False
        except JoseError as exc:
            report.steps.append(_fail_step("verify_signature", f"Signature verification failed: {exc}"))
            report.error = report.steps[-1].message
            return False

        return True

    def _validate_claims(self, report: TokenCheckReport) -> bool:
        """Step 6: Validate standard JWT claims."""
        payload = report.payload
        now = time.time()

        issues = _check_issuer(payload, self._expected_issuer, report)
        issues += _check_audience(payload, self._expected_audience, report)
        issues += _check_temporal_claims(payload, now)

        if issues:
            report.steps.append(
                ValidationStep(
                    name="validate_claims",
                    passed=False,
                    message="; ".join(issues),
                    details=_claims_details(payload, report),
                )
            )
            report.error = report.steps[-1].message
            return False

        report.steps.append(
            ValidationStep(
                name="validate_claims",
                passed=True,
                message="All claims valid",
                details=_claims_details(payload, report),
            )
        )
        return True


# ─────────────────────────────────────────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────────────────────────────────────────


def _fail_step(name: str, message: str) -> ValidationStep:
    """Create a failing validation step."""
    return ValidationStep(name=name, passed=False, message=message)


def _record_http_error(report: TokenCheckReport, step_name: str, message: str) -> bool:
    """Record an HTTP error as a failed step and return False."""
    report.steps.append(_fail_step(step_name, message))
    report.error = message
    return False


def _find_matching_key(keys: list[dict[str, Any]], kid: str | None) -> dict[str, Any] | None:
    """Find a JWK matching the given kid.

    Args:
        keys: List of JWK dicts from the JWKS.
        kid: Key ID to match, or None.

    Returns:
        Matching key dict, or None.
    """
    if kid:
        for key in keys:
            if key.get("kid") == kid:
                return key
        return None

    # No kid in header, use first key if only one available
    if len(keys) == 1:
        return keys[0]
    return None


def _jwk_to_pem(jwk_data: dict[str, Any]) -> tuple[str, str, int | None]:
    """Convert a JWK dict to PEM string, SHA-256 fingerprint, and key size.

    Args:
        jwk_data: JWK dict from JWKS.

    Returns:
        Tuple of (pem_string, sha256_hex_fingerprint, key_size_bits).

    Raises:
        ImportError: If authlib is not installed.
    """
    from authlib.jose import JsonWebKey
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    jwk_obj = JsonWebKey.import_key(jwk_data)
    public_key = jwk_obj.get_public_key()

    pem_bytes = public_key.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    der_bytes = public_key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    fingerprint = hashlib.sha256(der_bytes).hexdigest()

    key_size: int | None = None
    if isinstance(public_key, RSAPublicKey):
        key_size = public_key.key_size

    return pem_bytes.decode("utf-8"), fingerprint, key_size


def _parse_x509_info(cert_b64: str) -> dict[str, Any]:
    """Parse X.509 certificate info from base64-encoded DER (x5c field).

    Args:
        cert_b64: Base64-encoded DER certificate from x5c array.

    Returns:
        Dictionary with CN, serial, not_before, not_after.
        Empty dict if parsing fails.
    """
    try:
        from cryptography import x509

        cert_der = base64.b64decode(cert_b64)
        cert = x509.load_der_x509_certificate(cert_der)

        subject_cn = ""
        try:
            cn_attrs = cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
            if cn_attrs:
                subject_cn = str(cn_attrs[0].value)
        except Exception:
            subject_cn = cert.subject.rfc4514_string()

        issuer_cn = ""
        try:
            cn_attrs = cert.issuer.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
            if cn_attrs:
                issuer_cn = str(cn_attrs[0].value)
        except Exception:
            issuer_cn = cert.issuer.rfc4514_string()

        return {
            "subject_cn": subject_cn,
            "issuer_cn": issuer_cn,
            "serial_number": format(cert.serial_number, "x"),
            "not_before": cert.not_valid_before_utc.isoformat(),
            "not_after": cert.not_valid_after_utc.isoformat(),
        }
    except Exception:
        logger.debug("Failed to parse x5c certificate", exc_info=True)
        return {}


def _check_issuer(
    payload: dict[str, Any],
    expected: str | None,
    report: TokenCheckReport,
) -> list[str]:
    """Validate issuer claim."""
    iss = payload.get("iss")
    issues: list[str] = []

    if expected:
        report.issuer_match = iss == expected
        if not report.issuer_match:
            issues.append(f"Issuer mismatch: got {iss!r}, expected {expected!r}")
    else:
        report.issuer_match = True if iss else None

    return issues


def _check_audience(
    payload: dict[str, Any],
    expected: str | None,
    report: TokenCheckReport,
) -> list[str]:
    """Validate audience claim."""
    aud = payload.get("aud")
    issues: list[str] = []

    if expected:
        report.audience_match = expected in aud if isinstance(aud, list) else aud == expected
        if not report.audience_match:
            issues.append(f"Audience mismatch: got {aud!r}, expected {expected!r}")
    else:
        report.audience_match = True if aud else None

    return issues


def _check_temporal_claims(payload: dict[str, Any], now: float) -> list[str]:
    """Validate exp, iat, nbf claims with clock skew tolerance."""
    issues: list[str] = []

    exp = payload.get("exp")
    if exp is not None and now > exp + CLOCK_SKEW_SECONDS:
        exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc).isoformat()
        issues.append(f"Token expired at {exp_dt}")

    iat = payload.get("iat")
    if iat is not None and iat > now + CLOCK_SKEW_SECONDS:
        issues.append(f"Token issued in the future: iat={iat}")

    nbf = payload.get("nbf")
    if nbf is not None and now < nbf - CLOCK_SKEW_SECONDS:
        issues.append(f"Token not yet valid: nbf={nbf}")

    return issues


def _claims_details(payload: dict[str, Any], report: TokenCheckReport) -> dict[str, Any]:
    """Build details dict for claims validation step."""
    return {
        "iss": payload.get("iss"),
        "aud": payload.get("aud"),
        "exp": payload.get("exp"),
        "iat": payload.get("iat"),
        "issuer_match": report.issuer_match,
        "audience_match": report.audience_match,
    }


def _b64url_decode(data: str) -> bytes:
    """Decode base64url-encoded data with padding fix.

    Args:
        data: Base64url-encoded string.

    Returns:
        Decoded bytes.
    """
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data)


__all__ = [
    "CLOCK_SKEW_SECONDS",
    "TokenCheckReport",
    "TokenChecker",
    "ValidationStep",
]
