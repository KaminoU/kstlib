"""Secure secret access pattern using the sensitive() context manager.

This is the RECOMMENDED way to access secrets in production code.
The secret is decrypted on-demand and purged from memory after use.

Compare with decrypt_example.py which is INSECURE (secret stays in memory).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from kstlib.secrets import (
    SecretDecryptionError,
    SecretNotFoundError,
    resolve_secret,
    sensitive,
)

# Set up example age key for demo (in real code, this would be configured elsewhere)
EXAMPLE_DIR = Path(__file__).parent
EXAMPLE_AGE_KEY = EXAMPLE_DIR / "age-key.example.txt"
SOPS_FILE = EXAMPLE_DIR / "secrets.sops.yml"


def send_email(password: str) -> None:
    """Simulate sending an email (placeholder for real SMTP logic)."""
    # In real code: smtp.login(username, password)
    print(f"[DEMO] Would authenticate with password length: {len(password)} chars ({password[0:3]}...{password[-3:]})")


def main() -> None:
    """Demonstrate secure secret access pattern."""
    # Set up environment for demo
    if EXAMPLE_AGE_KEY.exists():
        os.environ["SOPS_AGE_KEY_FILE"] = str(EXAMPLE_AGE_KEY)
        print(f"Using example age key: {EXAMPLE_AGE_KEY}", file=sys.stderr)

    if not SOPS_FILE.exists():
        print(f"Error: {SOPS_FILE} not found", file=sys.stderr)
        print("Run encrypt_example.py first to create it.", file=sys.stderr)
        sys.exit(1)

    print("Secure secret access example", file=sys.stderr)
    print("=" * 40, file=sys.stderr)
    print(file=sys.stderr)

    try:
        # Step 1: Resolve the secret (returns a SecretRecord)
        # We pass config to tell the resolver where to find the SOPS file
        record = resolve_secret(
            "mail.smtp.password",
            config={"sops": {"path": str(SOPS_FILE)}},
            required=True,
        )

        # Step 2: SECURE PATTERN - use sensitive() context manager
        # The secret only exists in memory during the with block
        with sensitive(record) as secret_value:
            print(f"Secret source: {record.source.value}", file=sys.stderr)
            print(file=sys.stderr)

            # Use the secret for its intended purpose
            send_email(str(secret_value))

            print(file=sys.stderr)
            print("Secret is available HERE, inside the with block.", file=sys.stderr)

        # After exiting the with block:
        # - record.value is set to None
        # - The secret is scrubbed from memory
        print(file=sys.stderr)
        print(f"record.value after with block: {record.value}", file=sys.stderr)
        print("Secret has been PURGED from memory.", file=sys.stderr)
        print("This is the secure pattern for production code.", file=sys.stderr)

    except SecretNotFoundError:
        print("Error: Secret 'mail.smtp.password' not found.", file=sys.stderr)
        print("Make sure secrets.sops.yml contains this key.", file=sys.stderr)
        sys.exit(1)

    except SecretDecryptionError as e:
        print(f"Error: Failed to decrypt: {e}", file=sys.stderr)
        print("Check that the age key matches.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
