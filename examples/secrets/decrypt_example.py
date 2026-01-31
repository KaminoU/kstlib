"""Decrypt a SOPS file using kstlib CLI and print the result.

!!! WARNING - DEMO ONLY !!!
This script demonstrates SOPS decryption but is NOT secure for production.
The secret remains in memory indefinitely (vulnerable to memory dumps).

For production code, use: decrypt_secure_example.py
which uses the `sensitive()` context manager to purge secrets after use.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Paths
EXAMPLE_DIR = Path(__file__).parent
ENCRYPTED_FILE = EXAMPLE_DIR / "secrets.sops.yml"
EXAMPLE_AGE_KEY = EXAMPLE_DIR / "age-key.example.txt"


def main() -> None:
    """Decrypt secrets.sops.yml and print the cleartext output."""
    # Check encrypted file exists
    if not ENCRYPTED_FILE.exists():
        print(f"Error: {ENCRYPTED_FILE} not found", file=sys.stderr)
        print("", file=sys.stderr)
        print("Hint: First run encrypt_example.py to create it.", file=sys.stderr)
        sys.exit(1)

    # Use example age key if available (for demo purposes)
    env = os.environ.copy()
    if EXAMPLE_AGE_KEY.exists():
        env["SOPS_AGE_KEY_FILE"] = str(EXAMPLE_AGE_KEY)
        print(f"Using example age key: {EXAMPLE_AGE_KEY}", file=sys.stderr)

    print(f"Decrypting: {ENCRYPTED_FILE}", file=sys.stderr)
    print("", file=sys.stderr)

    result = subprocess.run(
        ["kstlib", "secrets", "decrypt", str(ENCRYPTED_FILE)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    if result.returncode != 0:
        error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"
        print(f"Decryption failed: {error_msg}", file=sys.stderr)
        print("", file=sys.stderr)
        print("Common causes:", file=sys.stderr)
        print("  - Wrong age key (file encrypted with different key)", file=sys.stderr)
        print("  - Missing age key file", file=sys.stderr)
        print("", file=sys.stderr)
        print("Run 'kstlib secrets doctor' to diagnose.", file=sys.stderr)
        sys.exit(1)

    print("# Decrypted output:")
    print(result.stdout)


if __name__ == "__main__":
    main()
