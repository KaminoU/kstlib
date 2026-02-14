#!/usr/bin/env python3
"""JWT token validation with cryptographic proof - two approaches.

Demonstrates token validation using both kstlib and manual verification.
Uses the local Keycloak instance as identity provider.

This example shows:
    - kstlib approach: TokenChecker with 6-step validation chain
    - Manual approach: step-by-step verification with httpx + cryptography
    - Both produce the same result (cryptographic proof)

Prerequisites:
    1. Start Keycloak: cd infra && docker compose up -d keycloak
    2. Login first: cd examples/auth && kstlib auth login oidc-keycloak-dev

Usage:
    cd examples/auth

    # Validate cached token (kstlib approach)
    python token_check.py

    # Validate with manual step-by-step verification
    python token_check.py --manual

    # Validate an explicit JWT string
    python token_check.py --token "eyJhbGci..."

    # Show full details (header, payload, PEM key)
    python token_check.py --verbose

Test credentials:
    Username: testuser
    Password: testpass123
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import httpx

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _b64url_decode(data: str) -> bytes:
    """Decode base64url without padding."""
    padding = 4 - len(data) % 4
    return base64.urlsafe_b64decode(data + "=" * padding)


def _print_json(label: str, data: Any) -> None:
    """Print formatted JSON with a label."""
    print(f"\n--- {label} ---")
    print(json.dumps(data, indent=2, default=str))


def _get_token(token_str: str | None) -> str:
    """Resolve token from argument or cached provider."""
    if token_str:
        return token_str

    from kstlib.auth import OIDCProvider

    try:
        provider = OIDCProvider.from_config("oidc-keycloak-dev")
    except Exception as exc:
        print(f"Error loading provider: {exc}")
        print("Run 'kstlib auth login oidc-keycloak-dev' first.")
        sys.exit(1)

    cached = provider.get_token(auto_refresh=False)
    if cached is None:
        print("Not authenticated. Run 'kstlib auth login oidc-keycloak-dev' first.")
        sys.exit(1)

    jwt_str = cached.id_token or cached.access_token
    print(f"Using cached {'id_token' if cached.id_token else 'access_token'}")
    return jwt_str


# ---------------------------------------------------------------------------
# Approach 1: kstlib TokenChecker
# ---------------------------------------------------------------------------


def check_with_kstlib(token_str: str, *, verbose: bool = False) -> bool:
    """Validate token using kstlib TokenChecker.

    This is the production approach: one class, one method call,
    complete validation report.

    Args:
        token_str: JWT string to validate.
        verbose: Show full details.

    Returns:
        True if token is valid.
    """
    from kstlib.auth.check import TokenChecker

    print("=" * 60)
    print("APPROACH 1: kstlib TokenChecker")
    print("=" * 60)

    with httpx.Client() as client:
        checker = TokenChecker(client)
        report = checker.check(token_str)

    # Summary
    status = "VALID" if report.valid else "INVALID"
    print(f"\nResult: {status}")
    print(f"Algorithm: {report.signature_algorithm}")
    print(f"Key ID: {report.key_id}")

    if report.key_fingerprint:
        print(f"Key Fingerprint: SHA256:{report.key_fingerprint[:32]}...")

    # Steps
    print("\nValidation steps:")
    for step in report.steps:
        icon = "+" if step.passed else "X"
        print(f"  [{icon}] {step.name}: {step.message}")

    if report.error:
        print(f"\nError: {report.error}")

    # Verbose output
    if verbose:
        if report.header:
            _print_json("JWT Header", report.header)
        if report.payload:
            _print_json("JWT Payload", report.payload)
        if report.discovery_data:
            _print_json("Discovery Document", report.discovery_data)
        if report.public_key_pem:
            print(f"\n--- Public Key (SHA256:{report.key_fingerprint or 'unknown'}) ---")
            print(report.public_key_pem.strip())

    return report.valid


# ---------------------------------------------------------------------------
# Approach 2: Manual step-by-step verification
# ---------------------------------------------------------------------------


def check_manually(token_str: str, *, verbose: bool = False) -> bool:
    """Validate token manually with httpx + cryptography.

    This is the educational approach: every step is explicit,
    showing exactly what happens under the hood.

    Args:
        token_str: JWT string to validate.
        verbose: Show full details.

    Returns:
        True if token is valid.
    """
    print("=" * 60)
    print("APPROACH 2: Manual verification (httpx + cryptography)")
    print("=" * 60)

    # --- Step 1: Decode JWT structure ---
    print("\n[Step 1] Decode JWT structure")

    parts = token_str.split(".")
    if len(parts) != 3:
        print(f"  FAIL: Expected 3 parts, got {len(parts)}")
        return False

    header = json.loads(_b64url_decode(parts[0]))
    payload = json.loads(_b64url_decode(parts[1]))

    alg = header.get("alg", "unknown")
    kid = header.get("kid", "unknown")
    issuer = payload.get("iss", "")

    print(f"  OK: alg={alg}, kid={kid}")
    print(f"  Issuer: {issuer}")

    if verbose:
        _print_json("Header", header)
        _print_json("Payload", payload)

    # --- Step 2: Fetch OIDC discovery ---
    print("\n[Step 2] Fetch discovery document")

    discovery_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    print(f"  GET {discovery_url}")

    with httpx.Client() as client:
        resp = client.get(discovery_url, timeout=10)
        resp.raise_for_status()
        discovery = resp.json()

    jwks_uri = discovery.get("jwks_uri", "")
    supported_algs = discovery.get("id_token_signing_alg_values_supported", [])
    print(f"  OK: jwks_uri={jwks_uri}")
    print(f"  Supported algorithms: {supported_algs}")

    if verbose:
        _print_json(
            "Discovery",
            {
                "issuer": discovery.get("issuer"),
                "jwks_uri": jwks_uri,
                "supported_algs": supported_algs,
            },
        )

    # --- Step 3: Fetch JWKS ---
    print("\n[Step 3] Fetch JWKS (public keys)")
    print(f"  GET {jwks_uri}")

    with httpx.Client() as client:
        resp = client.get(jwks_uri, timeout=10)
        resp.raise_for_status()
        jwks = resp.json()

    keys = jwks.get("keys", [])
    print(f"  OK: {len(keys)} key(s) available")

    # --- Step 4: Find matching key ---
    print(f"\n[Step 4] Match key by kid={kid!r}")

    matching_key = None
    for key in keys:
        if key.get("kid") == kid:
            matching_key = key
            break

    if matching_key is None:
        available = [k.get("kid") for k in keys]
        print(f"  FAIL: kid={kid!r} not found. Available: {available}")
        return False

    # Convert JWK to PEM using authlib
    from authlib.jose import JsonWebKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    jwk_obj = JsonWebKey.import_key(matching_key)
    public_key = jwk_obj.get_public_key()
    pem_bytes = public_key.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    der_bytes = public_key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    fingerprint = hashlib.sha256(der_bytes).hexdigest()

    print(f"  OK: Key found, fingerprint SHA256:{fingerprint[:32]}...")

    if verbose:
        print(f"\n--- Public Key ---\n{pem_bytes.decode().strip()}")

    # --- Step 5: Verify signature ---
    print(f"\n[Step 5] Verify signature ({alg})")

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    # The signed data is the first two parts as-is (base64url encoded)
    signed_data = f"{parts[0]}.{parts[1]}".encode("ascii")
    signature = _b64url_decode(parts[2])

    # Select hash algorithm based on JWT alg header
    hash_algorithms: dict[str, hashes.HashAlgorithm] = {
        "RS256": hashes.SHA256(),
        "RS384": hashes.SHA384(),
        "RS512": hashes.SHA512(),
    }

    hash_alg = hash_algorithms.get(alg)
    if hash_alg is None:
        print(f"  FAIL: Unsupported algorithm {alg!r}")
        return False

    try:
        public_key.verify(
            signature,
            signed_data,
            padding.PKCS1v15(),
            hash_alg,
        )
        print(f"  OK: Signature valid ({alg})")
    except Exception as exc:
        print(f"  FAIL: Signature invalid: {exc}")
        return False

    # --- Step 6: Validate claims ---
    print("\n[Step 6] Validate claims")

    import time

    now = time.time()
    skew = 300  # 5 minutes tolerance
    issues = []

    exp = payload.get("exp")
    if exp is not None and exp + skew < now:
        issues.append(f"Token expired ({int(now - exp)}s ago)")
    elif exp is not None:
        remaining = int(exp - now)
        print(f"  Expires in: {remaining // 60}m {remaining % 60}s")

    iat = payload.get("iat")
    if iat is not None and iat - skew > now:
        issues.append(f"Token issued in the future (iat={iat})")

    if payload.get("iss"):
        print(f"  Issuer: {payload['iss']}")
    if payload.get("aud"):
        print(f"  Audience: {payload['aud']}")
    if payload.get("sub"):
        print(f"  Subject: {payload['sub']}")

    if issues:
        for issue in issues:
            print(f"  FAIL: {issue}")
        return False

    print("  OK: All claims valid")

    # --- Summary ---
    print("\n" + "=" * 60)
    print("RESULT: TOKEN IS VALID")
    print("=" * 60)
    print(f"  Algorithm:   {alg}")
    print(f"  Key ID:      {kid}")
    print(f"  Fingerprint: SHA256:{fingerprint[:32]}...")
    print(f"  Issuer:      {payload.get('iss')}")
    print(f"  Subject:     {payload.get('sub')}")
    print()
    print("This is a mathematical fact verified against the issuer's own public key.")
    print("Any third party can reproduce this verification independently.")

    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="JWT token validation with cryptographic proof",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python token_check.py                      # kstlib approach (cached token)
    python token_check.py --manual             # Manual step-by-step
    python token_check.py --token "eyJ..."     # Explicit token
    python token_check.py --verbose            # Full details
    python token_check.py --manual --verbose   # Manual + full details
        """,
    )
    parser.add_argument(
        "--token",
        help="JWT string to validate (default: cached token from oidc-keycloak-dev)",
    )
    parser.add_argument(
        "--manual",
        action="store_true",
        help="Use manual step-by-step verification instead of kstlib",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show full JWT header, payload, PEM key",
    )
    return parser.parse_args()


def main() -> None:
    """Run token validation."""
    args = parse_args()
    jwt_str = _get_token(args.token)

    if args.manual:
        valid = check_manually(jwt_str, verbose=args.verbose)
    else:
        valid = check_with_kstlib(jwt_str, verbose=args.verbose)

    sys.exit(0 if valid else 1)


if __name__ == "__main__":
    main()
