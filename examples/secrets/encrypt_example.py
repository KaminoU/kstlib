"""Encrypt a secrets file using kstlib CLI and print the result."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Paths
EXAMPLE_DIR = Path(__file__).parent
SECRETS_FILE = EXAMPLE_DIR / "secrets.example.yml"
OUTPUT_FILE = EXAMPLE_DIR / "secrets.sops.yml"
EXAMPLE_AGE_KEY = EXAMPLE_DIR / "age-key.example.txt"

# Possible SOPS config locations
SOPS_CONFIG_LOCATIONS = [
    EXAMPLE_DIR / ".sops.yaml",  # Local to examples/secrets/
    EXAMPLE_DIR.parent.parent / ".sops.yaml",  # Project root
    Path.home() / ".sops.yaml",  # User home
]


def find_sops_config() -> Path | None:
    """Find the first existing .sops.yaml config file."""
    for path in SOPS_CONFIG_LOCATIONS:
        if path.exists():
            return path
    return None


def main() -> None:
    """Encrypt secrets.example.yml and write to secrets.sops.yml."""
    # Check secrets file exists
    if not SECRETS_FILE.exists():
        print(f"Error: {SECRETS_FILE} not found", file=sys.stderr)
        sys.exit(1)

    # Check SOPS config exists
    sops_config = find_sops_config()
    if sops_config is None:
        print("Error: No .sops.yaml config found.", file=sys.stderr)
        print("", file=sys.stderr)
        print("Hint: Copy .sops.example.yml to .sops.yaml:", file=sys.stderr)
        print(f"  cp {EXAMPLE_DIR / '.sops.example.yml'} {EXAMPLE_DIR / '.sops.yaml'}", file=sys.stderr)
        sys.exit(1)

    # Use example age key if available (for demo purposes)
    env = os.environ.copy()
    if EXAMPLE_AGE_KEY.exists():
        env["SOPS_AGE_KEY_FILE"] = str(EXAMPLE_AGE_KEY)
        print(f"Using example age key: {EXAMPLE_AGE_KEY}", file=sys.stderr)

    print(f"Using SOPS config: {sops_config}", file=sys.stderr)
    print(f"Encrypting: {SECRETS_FILE}", file=sys.stderr)
    print(f"Output: {OUTPUT_FILE}", file=sys.stderr)
    print("", file=sys.stderr)

    result = subprocess.run(
        [
            "kstlib",
            "secrets",
            "encrypt",
            str(SECRETS_FILE),
            "--out",
            str(OUTPUT_FILE),
            "--config",
            str(sops_config),
            "--force",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    if result.returncode != 0:
        error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"
        print(f"Encryption failed: {error_msg}", file=sys.stderr)
        sys.exit(1)

    print("Encryption successful!", file=sys.stderr)
    print("", file=sys.stderr)
    print(f"Encrypted file: {OUTPUT_FILE}", file=sys.stderr)
    print("Run decrypt_example.py to decrypt it.", file=sys.stderr)


if __name__ == "__main__":
    main()
