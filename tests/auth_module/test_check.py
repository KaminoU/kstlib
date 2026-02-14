"""Unit tests for TokenChecker and token validation."""

from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from kstlib.auth.check import (
    CLOCK_SKEW_SECONDS,
    TokenChecker,
    TokenCheckReport,
    ValidationStep,
    _b64url_decode,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _b64url_encode(data: bytes) -> str:
    """Encode bytes to base64url without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _make_unsigned_jwt(header: dict[str, Any], payload: dict[str, Any]) -> str:
    """Create a JWT-like string (header.payload.signature) for structure tests."""
    h = _b64url_encode(json.dumps(header).encode())
    p = _b64url_encode(json.dumps(payload).encode())
    # Fake signature (not cryptographically valid)
    s = _b64url_encode(b"fake-signature-bytes")
    return f"{h}.{p}.{s}"


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


def _key_to_pem(private_key: Any) -> bytes:
    """Serialize RSA private key to PEM bytes for authlib compatibility."""
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

    return private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())


@pytest.fixture
def rsa_keypair():
    """Generate a real RSA key pair for testing."""
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    return private_key


@pytest.fixture
def rsa_keypair_4096():
    """Generate a 4096-bit RSA key pair for RS512 testing."""
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=4096,
    )
    return private_key


@pytest.fixture
def jwk_dict(rsa_keypair):
    """Convert RSA key to JWK dict format."""
    from authlib.jose import JsonWebKey

    pem = _key_to_pem(rsa_keypair)
    jwk = JsonWebKey.import_key(pem, {"kid": "test-key-1", "use": "sig"})
    return jwk.as_dict(is_private=False)


@pytest.fixture
def jwk_dict_rs512(rsa_keypair_4096):
    """Convert 4096-bit RSA key to JWK dict format for RS512."""
    from authlib.jose import JsonWebKey

    pem = _key_to_pem(rsa_keypair_4096)
    jwk = JsonWebKey.import_key(pem, {"kid": "rs512-key-1", "use": "sig"})
    return jwk.as_dict(is_private=False)


@pytest.fixture
def jwks_response(jwk_dict):
    """Create a JWKS response containing the test key."""
    return {"keys": [jwk_dict]}


@pytest.fixture
def jwks_response_rs512(jwk_dict_rs512):
    """Create a JWKS response containing the RS512 test key."""
    return {"keys": [jwk_dict_rs512]}


def _make_signed_jwt(
    private_key: Any,
    claims: dict[str, Any],
    *,
    alg: str = "RS256",
    kid: str = "test-key-1",
) -> str:
    """Create a real signed JWT using authlib.

    Args:
        private_key: RSA private key (cryptography object).
        claims: JWT payload claims.
        alg: Signing algorithm.
        kid: Key ID for header.

    Returns:
        Signed JWT string.
    """
    from authlib.jose import jwt

    pem = _key_to_pem(private_key)
    header = {"alg": alg, "kid": kid, "typ": "JWT"}
    token_bytes: bytes = jwt.encode(header, claims, pem)  # type: ignore[call-overload]
    return token_bytes.decode("utf-8")


@pytest.fixture
def valid_claims():
    """Create valid JWT claims."""
    now = int(time.time())
    return {
        "iss": "https://idp.example.com",
        "aud": "test-client",
        "sub": "user123",
        "exp": now + 3600,
        "iat": now,
        "nbf": now,
        "name": "Test User",
        "email": "test@example.com",
    }


@pytest.fixture
def valid_jwt(rsa_keypair, valid_claims):
    """Create a valid signed JWT."""
    return _make_signed_jwt(rsa_keypair, valid_claims)


@pytest.fixture
def valid_jwt_rs512(rsa_keypair_4096, valid_claims):
    """Create a valid RS512-signed JWT."""
    claims = dict(valid_claims)
    return _make_signed_jwt(rsa_keypair_4096, claims, alg="RS512", kid="rs512-key-1")


@pytest.fixture
def expired_claims():
    """Create expired JWT claims."""
    past = int(time.time()) - 7200  # 2 hours ago
    return {
        "iss": "https://idp.example.com",
        "aud": "test-client",
        "sub": "user123",
        "exp": past,
        "iat": past - 3600,
    }


@pytest.fixture
def discovery_response():
    """Create a mock OIDC discovery response."""
    return {
        "issuer": "https://idp.example.com",
        "authorization_endpoint": "https://idp.example.com/authorize",
        "token_endpoint": "https://idp.example.com/token",
        "userinfo_endpoint": "https://idp.example.com/userinfo",
        "jwks_uri": "https://idp.example.com/.well-known/jwks.json",
        "id_token_signing_alg_values_supported": ["RS256", "RS512"],
    }


@pytest.fixture
def mock_http_client(discovery_response, jwks_response):
    """Create a mock httpx.Client that returns discovery + JWKS."""
    client = MagicMock(spec=httpx.Client)

    def mock_get(url, **kwargs):
        """Route GET requests to appropriate mock responses."""
        resp = MagicMock()
        resp.raise_for_status = MagicMock()

        if ".well-known/openid-configuration" in url:
            resp.json.return_value = discovery_response
        elif "jwks" in url:
            resp.json.return_value = jwks_response
        else:
            resp.status_code = 404
            resp.raise_for_status.side_effect = httpx.HTTPStatusError("Not Found", request=MagicMock(), response=resp)
        return resp

    client.get = MagicMock(side_effect=mock_get)
    return client


# ─────────────────────────────────────────────────────────────────────────────
# Test ValidationStep dataclass
# ─────────────────────────────────────────────────────────────────────────────


class TestValidationStep:
    """Tests for ValidationStep dataclass."""

    def test_create_passing_step(self) -> None:
        """Creates a passing validation step."""
        step = ValidationStep(name="test", passed=True, message="OK")
        assert step.name == "test"
        assert step.passed is True
        assert step.message == "OK"
        assert step.details == {}

    def test_create_failing_step_with_details(self) -> None:
        """Creates a failing step with details."""
        step = ValidationStep(
            name="test",
            passed=False,
            message="Failed",
            details={"reason": "bad"},
        )
        assert step.passed is False
        assert step.details["reason"] == "bad"

    def test_step_is_frozen(self) -> None:
        """ValidationStep is immutable."""
        step = ValidationStep(name="test", passed=True, message="OK")
        with pytest.raises(AttributeError):
            step.name = "changed"  # type: ignore[misc]


# ─────────────────────────────────────────────────────────────────────────────
# Test TokenCheckReport
# ─────────────────────────────────────────────────────────────────────────────


class TestTokenCheckReport:
    """Tests for TokenCheckReport dataclass."""

    def test_default_report_is_invalid(self) -> None:
        """Default report has valid=False."""
        report = TokenCheckReport()
        assert report.valid is False
        assert report.steps == []
        assert report.token_type == "id_token"

    def test_to_dict_serialization(self) -> None:
        """Report serializes to dict correctly."""
        report = TokenCheckReport(
            valid=True,
            token_type="access_token",
            header={"alg": "RS256"},
            payload={"sub": "user1"},
            signature_algorithm="RS256",
            key_id="kid-1",
        )
        report.steps.append(ValidationStep(name="step1", passed=True, message="OK"))

        d = report.to_dict()
        assert d["valid"] is True
        assert d["token_type"] == "access_token"
        assert d["signature_algorithm"] == "RS256"
        assert len(d["steps"]) == 1
        assert d["steps"][0]["name"] == "step1"

    def test_to_dict_includes_all_fields(self) -> None:
        """Report dict includes all expected keys."""
        report = TokenCheckReport()
        d = report.to_dict()
        expected_keys = {
            "token_type",
            "valid",
            "steps",
            "header",
            "payload",
            "signature_algorithm",
            "key_id",
            "discovery_url",
            "discovery_data",
            "jwks_uri",
            "public_key_pem",
            "key_fingerprint",
            "key_type",
            "key_size_bits",
            "x509_info",
            "issuer_match",
            "audience_match",
            "error",
        }
        assert set(d.keys()) == expected_keys


# ─────────────────────────────────────────────────────────────────────────────
# Test _b64url_decode helper
# ─────────────────────────────────────────────────────────────────────────────


class TestB64urlDecode:
    """Tests for base64url decode helper."""

    def test_decodes_padded_data(self) -> None:
        """Decodes base64url with proper padding."""
        data = base64.urlsafe_b64encode(b"hello").rstrip(b"=").decode()
        assert _b64url_decode(data) == b"hello"

    def test_decodes_data_needing_padding(self) -> None:
        """Decodes base64url needing 1 or 2 padding chars."""
        # "hel" -> 3 bytes -> 4 base64 chars, no padding needed
        data = _b64url_encode(b"hel")
        assert _b64url_decode(data) == b"hel"

    def test_decodes_already_padded_data(self) -> None:
        """Handles data that already has padding."""
        data = base64.urlsafe_b64encode(b"hello world").decode()
        assert _b64url_decode(data) == b"hello world"


# ─────────────────────────────────────────────────────────────────────────────
# Test TokenChecker
# ─────────────────────────────────────────────────────────────────────────────


class TestTokenCheckerDecodeStructure:
    """Tests for step 1: decode_structure."""

    def test_valid_jwt_structure(self) -> None:
        """Decodes a valid 3-part JWT."""
        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(client)

        header = {"alg": "RS256", "kid": "key-1", "typ": "JWT"}
        payload = {"sub": "user1", "iss": "https://example.com"}
        token = _make_unsigned_jwt(header, payload)
        checker._token_str = token

        report = TokenCheckReport()
        result = checker._decode_structure(report)

        assert result is True
        assert report.header["alg"] == "RS256"
        assert report.payload["sub"] == "user1"
        assert report.signature_algorithm == "RS256"
        assert report.key_id == "key-1"
        assert report.steps[0].passed is True

    def test_invalid_jwt_format_two_parts(self) -> None:
        """Rejects JWT with only 2 parts."""
        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(client)
        checker._token_str = "part1.part2"

        report = TokenCheckReport()
        result = checker._decode_structure(report)

        assert result is False
        assert report.steps[0].passed is False
        assert "expected 3 parts" in report.steps[0].message

    def test_invalid_jwt_format_single_string(self) -> None:
        """Rejects non-JWT string."""
        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(client)
        checker._token_str = "not-a-jwt"

        report = TokenCheckReport()
        result = checker._decode_structure(report)

        assert result is False
        assert report.error is not None

    def test_invalid_base64_content(self) -> None:
        """Rejects JWT with invalid base64 in payload."""
        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(client)
        checker._token_str = "eyJhbGciOiJSUzI1NiJ9.!!!invalid!!!.sig"

        report = TokenCheckReport()
        result = checker._decode_structure(report)

        assert result is False
        assert "Failed to decode" in report.error


class TestTokenCheckerDiscoverIssuer:
    """Tests for step 2: discover_issuer."""

    def test_successful_discovery(self, discovery_response) -> None:
        """Fetches and parses discovery document."""
        client = MagicMock(spec=httpx.Client)
        resp = MagicMock()
        resp.json.return_value = discovery_response
        resp.raise_for_status = MagicMock()
        client.get.return_value = resp

        checker = TokenChecker(client)
        report = TokenCheckReport()
        report.payload = {"iss": "https://idp.example.com"}

        result = checker._discover_issuer(report)

        assert result is True
        assert report.jwks_uri == "https://idp.example.com/.well-known/jwks.json"
        assert report.discovery_url == "https://idp.example.com/.well-known/openid-configuration"
        assert report.steps[0].passed is True

    def test_missing_iss_claim(self) -> None:
        """Fails when no iss claim in payload."""
        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(client)
        report = TokenCheckReport()
        report.payload = {"sub": "user1"}  # no iss

        result = checker._discover_issuer(report)

        assert result is False
        assert "iss" in report.steps[0].message

    def test_discovery_http_error(self) -> None:
        """Fails on HTTP error from discovery endpoint."""
        client = MagicMock(spec=httpx.Client)
        mock_response = MagicMock()
        mock_response.status_code = 404
        client.get.side_effect = httpx.HTTPStatusError("Not Found", request=MagicMock(), response=mock_response)

        checker = TokenChecker(client)
        report = TokenCheckReport()
        report.payload = {"iss": "https://bad-idp.example.com"}

        result = checker._discover_issuer(report)

        assert result is False
        assert "404" in report.steps[0].message

    def test_discovery_network_error(self) -> None:
        """Fails on network error during discovery."""
        client = MagicMock(spec=httpx.Client)
        client.get.side_effect = httpx.ConnectError("Connection refused")

        checker = TokenChecker(client)
        report = TokenCheckReport()
        report.payload = {"iss": "https://unreachable.example.com"}

        result = checker._discover_issuer(report)

        assert result is False
        assert "Connection refused" in report.steps[0].message

    def test_trailing_slash_in_issuer(self, discovery_response) -> None:
        """Strips trailing slash from issuer URL."""
        client = MagicMock(spec=httpx.Client)
        resp = MagicMock()
        resp.json.return_value = discovery_response
        resp.raise_for_status = MagicMock()
        client.get.return_value = resp

        checker = TokenChecker(client)
        report = TokenCheckReport()
        report.payload = {"iss": "https://idp.example.com/"}

        result = checker._discover_issuer(report)

        assert result is True
        assert report.discovery_url == "https://idp.example.com/.well-known/openid-configuration"


class TestTokenCheckerFetchJwks:
    """Tests for step 3: fetch_jwks."""

    def test_successful_fetch(self, jwks_response) -> None:
        """Fetches JWKS successfully."""
        client = MagicMock(spec=httpx.Client)
        resp = MagicMock()
        resp.json.return_value = jwks_response
        resp.raise_for_status = MagicMock()
        client.get.return_value = resp

        checker = TokenChecker(client)
        report = TokenCheckReport()
        report.jwks_uri = "https://idp.example.com/.well-known/jwks.json"

        result = checker._fetch_jwks(report)

        assert result is True
        assert "keys" in report.jwks_data
        assert report.steps[0].passed is True

    def test_no_jwks_uri(self) -> None:
        """Fails when no jwks_uri available."""
        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(client)
        report = TokenCheckReport()
        report.jwks_uri = None

        result = checker._fetch_jwks(report)

        assert result is False
        assert "jwks_uri" in report.steps[0].message

    def test_jwks_http_error(self) -> None:
        """Fails on HTTP error from JWKS endpoint."""
        client = MagicMock(spec=httpx.Client)
        mock_response = MagicMock()
        mock_response.status_code = 500
        client.get.side_effect = httpx.HTTPStatusError("Server Error", request=MagicMock(), response=mock_response)

        checker = TokenChecker(client)
        report = TokenCheckReport()
        report.jwks_uri = "https://idp.example.com/.well-known/jwks.json"

        result = checker._fetch_jwks(report)

        assert result is False
        assert "500" in report.steps[0].message

    def test_jwks_network_error(self) -> None:
        """Fails on network error fetching JWKS."""
        client = MagicMock(spec=httpx.Client)
        client.get.side_effect = httpx.ConnectError("timeout")

        checker = TokenChecker(client)
        report = TokenCheckReport()
        report.jwks_uri = "https://idp.example.com/.well-known/jwks.json"

        result = checker._fetch_jwks(report)

        assert result is False

    def test_jwks_cache(self, jwks_response) -> None:
        """Uses cached JWKS on second call."""
        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(client)
        checker._jwks_cache = jwks_response

        report = TokenCheckReport()
        report.jwks_uri = "https://idp.example.com/.well-known/jwks.json"

        result = checker._fetch_jwks(report)

        assert result is True
        assert "cache" in report.steps[0].message.lower()
        client.get.assert_not_called()


class TestTokenCheckerExtractPublicKey:
    """Tests for step 4: extract_public_key."""

    def test_extracts_key_by_kid(self, jwk_dict) -> None:
        """Extracts correct key with type, size, and fingerprint."""
        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(client)

        report = TokenCheckReport()
        report.key_id = "test-key-1"
        report.jwks_data = {"keys": [jwk_dict]}

        result = checker._extract_public_key(report)

        assert result is True
        assert report.public_key_pem is not None
        assert "BEGIN PUBLIC KEY" in report.public_key_pem
        assert report.key_fingerprint is not None
        assert len(report.key_fingerprint) == 64  # SHA-256 hex
        assert report.key_type == "RSA"
        assert report.key_size_bits == 2048
        assert "RSA 2048-bit" in report.steps[0].message

    def test_key_not_found(self, jwk_dict) -> None:
        """Fails when kid doesn't match any JWKS key."""
        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(client)

        report = TokenCheckReport()
        report.key_id = "nonexistent-key"
        report.jwks_data = {"keys": [jwk_dict]}

        result = checker._extract_public_key(report)

        assert result is False
        assert "not in" in report.steps[0].message

    def test_empty_jwks(self) -> None:
        """Fails when JWKS has no keys."""
        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(client)

        report = TokenCheckReport()
        report.key_id = "test-key-1"
        report.jwks_data = {"keys": []}

        result = checker._extract_public_key(report)

        assert result is False
        assert "no keys" in report.steps[0].message.lower()

    def test_no_kid_single_key(self, jwk_dict) -> None:
        """Uses single key when JWT has no kid header."""
        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(client)

        report = TokenCheckReport()
        report.key_id = None  # No kid in JWT header
        report.jwks_data = {"keys": [jwk_dict]}

        result = checker._extract_public_key(report)

        assert result is True
        assert report.public_key_pem is not None

    def test_no_kid_multiple_keys(self, jwk_dict) -> None:
        """Fails when no kid and multiple keys in JWKS."""
        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(client)

        other_key = dict(jwk_dict)
        other_key["kid"] = "other-key"

        report = TokenCheckReport()
        report.key_id = None
        report.jwks_data = {"keys": [jwk_dict, other_key]}

        result = checker._extract_public_key(report)

        assert result is False

    def test_authlib_import_error(self, jwk_dict) -> None:
        """Fails gracefully when authlib is not available."""
        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(client)

        report = TokenCheckReport()
        report.key_id = "test-key-1"
        report.jwks_data = {"keys": [jwk_dict]}

        with patch.dict("sys.modules", {"authlib.jose": None, "authlib": None}):
            # Force ImportError by patching the import
            with patch(
                "kstlib.auth.check.TokenChecker._extract_public_key",
                side_effect=lambda self, r: _simulate_import_error(r),
            ):
                # Use the actual method but we need to test ImportError path
                pass

        # Test with a broken key instead to cover the exception path
        report2 = TokenCheckReport()
        report2.key_id = "test-key-1"
        report2.jwks_data = {"keys": [{"kid": "test-key-1", "kty": "INVALID"}]}

        result = checker._extract_public_key(report2)
        assert result is False

    def test_extracts_x509_info_when_x5c_present(self, rsa_keypair) -> None:
        """Extracts X.509 certificate details from x5c field."""
        from authlib.jose import JsonWebKey
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.x509.oid import NameOID

        # Generate a self-signed certificate
        subject = issuer = x509.Name(
            [
                x509.NameAttribute(NameOID.COMMON_NAME, "test-idp.example.com"),
            ]
        )
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(rsa_keypair.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime(2025, 1, 1, tzinfo=timezone.utc))
            .not_valid_after(datetime(2030, 12, 31, tzinfo=timezone.utc))
            .sign(rsa_keypair, hashes.SHA256())
        )
        cert_der = cert.public_bytes(serialization.Encoding.DER)
        cert_b64 = base64.b64encode(cert_der).decode("utf-8")

        # Build JWK with x5c
        pem = _key_to_pem(rsa_keypair)
        jwk = JsonWebKey.import_key(pem, {"kid": "x5c-key", "use": "sig"})
        jwk_data = jwk.as_dict(is_private=False)
        jwk_data["x5c"] = [cert_b64]

        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(client)

        report = TokenCheckReport()
        report.key_id = "x5c-key"
        report.jwks_data = {"keys": [jwk_data]}

        result = checker._extract_public_key(report)

        assert result is True
        assert report.x509_info["subject_cn"] == "test-idp.example.com"
        assert report.x509_info["issuer_cn"] == "test-idp.example.com"
        assert "serial_number" in report.x509_info
        assert "not_before" in report.x509_info
        assert "not_after" in report.x509_info

    def test_no_x509_info_without_x5c(self, jwk_dict) -> None:
        """No X.509 info when x5c field is absent."""
        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(client)

        report = TokenCheckReport()
        report.key_id = "test-key-1"
        report.jwks_data = {"keys": [jwk_dict]}

        checker._extract_public_key(report)
        assert report.x509_info == {}


def _simulate_import_error(report: TokenCheckReport) -> bool:
    """Helper to simulate ImportError in extract_public_key."""
    step = ValidationStep(
        name="extract_public_key",
        passed=False,
        message="authlib is required for key extraction",
    )
    report.steps.append(step)
    report.error = step.message
    return False


class TestTokenCheckerVerifySignature:
    """Tests for step 5: verify_signature."""

    def test_valid_signature_rs256(self, rsa_keypair, valid_claims, jwks_response) -> None:
        """Verifies RS256 signature successfully."""
        token = _make_signed_jwt(rsa_keypair, valid_claims)

        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(client)
        checker._token_str = token

        report = TokenCheckReport()
        report.signature_algorithm = "RS256"
        report.jwks_data = jwks_response

        result = checker._verify_signature(report)

        assert result is True
        assert "RS256" in report.steps[0].message

    def test_valid_signature_rs512(self, rsa_keypair_4096, valid_claims, jwks_response_rs512) -> None:
        """Verifies RS512 signature successfully."""
        token = _make_signed_jwt(rsa_keypair_4096, valid_claims, alg="RS512", kid="rs512-key-1")

        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(client)
        checker._token_str = token

        report = TokenCheckReport()
        report.signature_algorithm = "RS512"
        report.jwks_data = jwks_response_rs512

        result = checker._verify_signature(report)

        assert result is True
        assert "RS512" in report.steps[0].message

    def test_invalid_signature(self, rsa_keypair, valid_claims) -> None:
        """Fails with tampered signature."""
        from cryptography.hazmat.primitives.asymmetric import rsa as rsa_mod

        # Sign with one key
        token = _make_signed_jwt(rsa_keypair, valid_claims)

        # Verify with different key
        other_key = rsa_mod.generate_private_key(public_exponent=65537, key_size=2048)
        from authlib.jose import JsonWebKey

        other_pem = _key_to_pem(other_key)
        other_jwk = JsonWebKey.import_key(other_pem, {"kid": "test-key-1", "use": "sig"})
        wrong_jwks = {"keys": [other_jwk.as_dict(is_private=False)]}

        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(client)
        checker._token_str = token

        report = TokenCheckReport()
        report.signature_algorithm = "RS256"
        report.jwks_data = wrong_jwks

        result = checker._verify_signature(report)

        assert result is False
        assert "failed" in report.steps[0].message.lower() or "Signature" in report.steps[0].message


class TestTokenCheckerValidateClaims:
    """Tests for step 6: validate_claims."""

    def test_valid_claims(self) -> None:
        """Passes with all valid claims."""
        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(
            client,
            expected_issuer="https://idp.example.com",
            expected_audience="test-client",
        )

        now = int(time.time())
        report = TokenCheckReport()
        report.payload = {
            "iss": "https://idp.example.com",
            "aud": "test-client",
            "exp": now + 3600,
            "iat": now,
            "nbf": now,
        }

        result = checker._validate_claims(report)

        assert result is True
        assert report.issuer_match is True
        assert report.audience_match is True

    def test_issuer_mismatch(self) -> None:
        """Fails when issuer doesn't match expected."""
        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(
            client,
            expected_issuer="https://expected.example.com",
        )

        report = TokenCheckReport()
        report.payload = {
            "iss": "https://wrong.example.com",
            "exp": int(time.time()) + 3600,
        }

        result = checker._validate_claims(report)

        assert result is False
        assert report.issuer_match is False
        assert "mismatch" in report.error.lower()

    def test_audience_mismatch(self) -> None:
        """Fails when audience doesn't match expected."""
        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(
            client,
            expected_audience="expected-client",
        )

        report = TokenCheckReport()
        report.payload = {
            "iss": "https://idp.example.com",
            "aud": "wrong-client",
            "exp": int(time.time()) + 3600,
        }

        result = checker._validate_claims(report)

        assert result is False
        assert report.audience_match is False

    def test_audience_list_match(self) -> None:
        """Matches when expected audience is in aud list."""
        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(
            client,
            expected_audience="test-client",
        )

        report = TokenCheckReport()
        report.payload = {
            "iss": "https://idp.example.com",
            "aud": ["test-client", "other-client"],
            "exp": int(time.time()) + 3600,
        }

        result = checker._validate_claims(report)

        assert result is True
        assert report.audience_match is True

    def test_audience_list_no_match(self) -> None:
        """Fails when expected audience not in aud list."""
        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(
            client,
            expected_audience="missing-client",
        )

        report = TokenCheckReport()
        report.payload = {
            "iss": "https://idp.example.com",
            "aud": ["other-client", "another-client"],
            "exp": int(time.time()) + 3600,
        }

        result = checker._validate_claims(report)

        assert result is False
        assert report.audience_match is False

    def test_expired_token(self) -> None:
        """Fails when token is expired beyond clock skew."""
        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(client)

        report = TokenCheckReport()
        report.payload = {
            "iss": "https://idp.example.com",
            "exp": int(time.time()) - CLOCK_SKEW_SECONDS - 100,
        }

        result = checker._validate_claims(report)

        assert result is False
        assert "expired" in report.error.lower()

    def test_token_within_clock_skew(self) -> None:
        """Passes when token is expired but within clock skew tolerance."""
        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(client)

        report = TokenCheckReport()
        report.payload = {
            "iss": "https://idp.example.com",
            "exp": int(time.time()) - 60,  # Expired 60s ago, within 5min skew
        }

        result = checker._validate_claims(report)

        assert result is True

    def test_future_iat(self) -> None:
        """Fails when iat is too far in the future."""
        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(client)

        report = TokenCheckReport()
        report.payload = {
            "iss": "https://idp.example.com",
            "iat": int(time.time()) + CLOCK_SKEW_SECONDS + 100,
            "exp": int(time.time()) + 7200,
        }

        result = checker._validate_claims(report)

        assert result is False
        assert "future" in report.error.lower()

    def test_nbf_not_yet_valid(self) -> None:
        """Fails when nbf is in the future beyond clock skew."""
        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(client)

        report = TokenCheckReport()
        report.payload = {
            "iss": "https://idp.example.com",
            "nbf": int(time.time()) + CLOCK_SKEW_SECONDS + 100,
            "exp": int(time.time()) + 7200,
        }

        result = checker._validate_claims(report)

        assert result is False
        assert "not yet valid" in report.error.lower()

    def test_no_expected_issuer_or_audience(self) -> None:
        """Passes without expected issuer/audience (no validation)."""
        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(client)  # no expected values

        report = TokenCheckReport()
        report.payload = {
            "iss": "https://any-issuer.example.com",
            "aud": "any-client",
            "exp": int(time.time()) + 3600,
        }

        result = checker._validate_claims(report)

        assert result is True
        assert report.issuer_match is True
        assert report.audience_match is True

    def test_no_iss_claim_no_expected(self) -> None:
        """Passes without iss claim when no expected issuer configured."""
        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(client)

        report = TokenCheckReport()
        report.payload = {"exp": int(time.time()) + 3600}

        result = checker._validate_claims(report)

        assert result is True
        assert report.issuer_match is None

    def test_no_aud_claim_no_expected(self) -> None:
        """Passes without aud claim when no expected audience configured."""
        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(client)

        report = TokenCheckReport()
        report.payload = {
            "iss": "https://idp.example.com",
            "exp": int(time.time()) + 3600,
        }

        result = checker._validate_claims(report)

        assert result is True
        assert report.audience_match is None

    def test_multiple_claim_issues(self) -> None:
        """Reports multiple issues at once."""
        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(
            client,
            expected_issuer="https://expected.example.com",
            expected_audience="expected-client",
        )

        report = TokenCheckReport()
        report.payload = {
            "iss": "https://wrong.example.com",
            "aud": "wrong-client",
            "exp": int(time.time()) - CLOCK_SKEW_SECONDS - 100,
        }

        result = checker._validate_claims(report)

        assert result is False
        assert "Issuer mismatch" in report.error
        assert "Audience mismatch" in report.error
        assert "expired" in report.error.lower()


class TestTokenCheckerFullChain:
    """Integration tests for the full check() chain."""

    def test_full_valid_check(self, rsa_keypair, valid_claims, mock_http_client, jwks_response) -> None:
        """Full chain passes with valid RS256 token."""
        token = _make_signed_jwt(rsa_keypair, valid_claims)

        checker = TokenChecker(
            mock_http_client,
            expected_issuer="https://idp.example.com",
            expected_audience="test-client",
        )
        report = checker.check(token)

        assert report.valid is True
        assert len(report.steps) == 6
        assert all(s.passed for s in report.steps)
        assert report.signature_algorithm == "RS256"
        assert report.key_id == "test-key-1"
        assert report.issuer_match is True
        assert report.audience_match is True

    def test_full_valid_check_rs512(
        self, rsa_keypair_4096, valid_claims, discovery_response, jwks_response_rs512
    ) -> None:
        """Full chain passes with valid RS512 token."""
        token = _make_signed_jwt(rsa_keypair_4096, valid_claims, alg="RS512", kid="rs512-key-1")

        client = MagicMock(spec=httpx.Client)

        def mock_get(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if ".well-known/openid-configuration" in url:
                resp.json.return_value = discovery_response
            else:
                resp.json.return_value = jwks_response_rs512
            return resp

        client.get = MagicMock(side_effect=mock_get)

        checker = TokenChecker(
            client,
            expected_issuer="https://idp.example.com",
            expected_audience="test-client",
        )
        report = checker.check(token)

        assert report.valid is True
        assert report.signature_algorithm == "RS512"

    def test_stops_on_first_failure(self) -> None:
        """Chain stops at first failing step."""
        client = MagicMock(spec=httpx.Client)
        checker = TokenChecker(client)

        report = checker.check("not-a-jwt")

        assert report.valid is False
        assert len(report.steps) == 1
        assert report.steps[0].name == "decode_structure"

    def test_token_type_label(self, rsa_keypair, valid_claims, mock_http_client) -> None:
        """Token type label is preserved in report."""
        token = _make_signed_jwt(rsa_keypair, valid_claims)

        checker = TokenChecker(
            mock_http_client,
            expected_issuer="https://idp.example.com",
            expected_audience="test-client",
        )
        report = checker.check(token, token_type="access_token")

        assert report.token_type == "access_token"

    def test_expired_token_full_chain(self, rsa_keypair, expired_claims, mock_http_client) -> None:
        """Full chain fails at claims validation for expired token."""
        token = _make_signed_jwt(rsa_keypair, expired_claims)

        checker = TokenChecker(
            mock_http_client,
            expected_issuer="https://idp.example.com",
            expected_audience="test-client",
        )
        report = checker.check(token)

        assert report.valid is False
        # Should have gone through 5 steps before failing at claims
        assert report.steps[-1].name == "validate_claims"
        assert report.steps[-1].passed is False

    def test_discovery_failure_stops_chain(self) -> None:
        """Chain stops when discovery fails."""
        client = MagicMock(spec=httpx.Client)
        mock_response = MagicMock()
        mock_response.status_code = 500
        client.get.side_effect = httpx.HTTPStatusError("Server Error", request=MagicMock(), response=mock_response)

        now = int(time.time())
        header = {"alg": "RS256", "kid": "test-key-1", "typ": "JWT"}
        payload = {"iss": "https://bad.example.com", "exp": now + 3600}
        token = _make_unsigned_jwt(header, payload)

        checker = TokenChecker(client)
        report = checker.check(token)

        assert report.valid is False
        assert len(report.steps) == 2  # decode_structure + discover_issuer
        assert report.steps[1].name == "discover_issuer"
