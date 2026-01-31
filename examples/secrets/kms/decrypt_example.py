#!/usr/bin/env python3
"""Example: Decrypt SOPS-encrypted secrets using AWS KMS.

This example demonstrates decrypting secrets that were encrypted with a
real AWS KMS key. The KMS key must be accessible via your AWS credentials
(environment variables, ~/.aws/credentials, or IAM role).

Prerequisites:
    - AWS credentials configured (aws configure or environment variables)
    - Access to the KMS key used for encryption
    - sops CLI installed (for encryption)

Usage:
    # First, encrypt your secrets (one-time setup):
    cd examples/secrets/kms
    cp secrets.example.yml secrets.sops.yml
    # Edit secrets.sops.yml with real values
    sops -e -i secrets.sops.yml

    # Then run this script:
    python decrypt_example.py
"""

from __future__ import annotations

from pathlib import Path

import yaml

from kstlib.config.sops import get_decryptor


def main() -> None:
    """Decrypt and display secrets from KMS-encrypted SOPS file."""
    secrets_path = Path(__file__).parent / "secrets.sops.yml"

    if not secrets_path.exists():
        print("secrets.sops.yml not found!")
        print("Create it by copying secrets.example.yml and encrypting with sops:")
        print("  cp secrets.example.yml secrets.sops.yml")
        print("  sops -e -i secrets.sops.yml")
        return

    # Decrypt using kstlib (auto-detects KMS from sops metadata)
    decryptor = get_decryptor()
    decrypted_content = decryptor.decrypt_file(secrets_path)
    secrets = yaml.safe_load(decrypted_content)

    print("Decrypted secrets:")
    print("-" * 40)

    # Access nested values safely
    if "binance" in secrets:
        api_key = secrets["binance"].get("api_key", "N/A")
        print(f"Binance API Key: {api_key[:10]}..." if len(api_key) > 10 else f"Binance API Key: {api_key}")

    if "kraken" in secrets:
        api_key = secrets["kraken"].get("api_key", "N/A")
        print(f"Kraken API Key: {api_key[:10]}..." if len(api_key) > 10 else f"Kraken API Key: {api_key}")

    # Non-encrypted fields are returned as-is
    print(f"Bot Name: {secrets.get('bot_name', 'N/A')}")
    print(f"Environment: {secrets.get('environment', 'N/A')}")


if __name__ == "__main__":
    main()
