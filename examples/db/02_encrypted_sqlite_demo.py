#!/usr/bin/env python3
"""Demonstrate SQLCipher encrypted database.

This example shows how to create an encrypted SQLite database using SQLCipher.
The database file is unreadable without the correct passphrase.

Requirements:
    pip install kstlib[db-crypto]  # Installs sqlcipher3

    On Debian/Ubuntu, you also need:
    sudo apt-get install libsqlcipher-dev

    On macOS:
    brew install sqlcipher

    On Windows:
    Use pre-built wheels from: https://github.com/nickmccullum/pysqlcipher3-windows
    Or build from source with vcpkg

Usage:
    python examples/db/02_encrypted_sqlite_demo.py

What this demonstrates:
    1. Create an encrypted database with a passphrase
    2. Insert some data
    3. Close the connection
    4. Try to read with standard sqlite3 (should fail with "not a database")
    5. Re-open with correct passphrase (should work)

Note on key management:
    In production, NEVER hardcode passphrases. Use one of:
    - Environment variable: KSTLIB_DB_KEY
    - SOPS encrypted file: see kstlib.secrets for SOPS integration
    - Hardware security module (HSM) or cloud KMS
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

# Check if sqlcipher3 is available
try:
    import sqlcipher3

    HAS_SQLCIPHER = True
except ImportError:
    HAS_SQLCIPHER = False


def create_encrypted_db(db_path: Path, passphrase: str) -> None:
    """Create an encrypted SQLite database with sample data.

    Args:
        db_path: Path to the database file.
        passphrase: Encryption passphrase.
    """
    print(f"\n[1] Creating encrypted database: {db_path}")

    # Connect using sqlcipher3 (NOT standard sqlite3)
    conn = sqlcipher3.connect(str(db_path))

    # Set the encryption key (MUST be done before any other operation)
    # Escape single quotes to prevent SQL injection
    escaped_key = passphrase.replace("'", "''")
    conn.execute(f"PRAGMA key = '{escaped_key}'")

    # Verify encryption is working
    conn.execute("SELECT count(*) FROM sqlite_master")

    # Create table and insert data
    conn.execute("""
        CREATE TABLE IF NOT EXISTS secrets (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            value TEXT NOT NULL
        )
    """)

    # Insert some "secret" data
    secrets = [
        ("api_key", "sk-super-secret-12345"),
        ("db_password", "hunter2"),
        ("jwt_secret", "my-jwt-signing-key-very-long"),
    ]

    conn.executemany("INSERT INTO secrets (name, value) VALUES (?, ?)", secrets)
    conn.commit()

    # Verify data was inserted
    cursor = conn.execute("SELECT count(*) FROM secrets")
    count = cursor.fetchone()[0]
    print(f"    Inserted {count} secret entries")

    conn.close()
    print("    Database created and closed")


def try_read_with_sqlite3(db_path: Path) -> bool:
    """Try to read the encrypted database with standard sqlite3.

    Args:
        db_path: Path to the database file.

    Returns:
        True if read succeeded (NOT encrypted), False if failed (encrypted).
    """
    print("\n[2] Attempting to read with standard sqlite3...")

    try:
        conn = sqlite3.connect(str(db_path))
        # This should fail on an encrypted database
        conn.execute("SELECT count(*) FROM sqlite_master")
        conn.close()
        print("    WARNING: Database is NOT encrypted (sqlite3 could read it)")
        return True
    except sqlite3.DatabaseError as e:
        print("    SUCCESS: sqlite3 cannot read the file")
        print(f"    Error: {e}")
        return False


def read_with_correct_passphrase(db_path: Path, passphrase: str) -> bool:
    """Read the encrypted database with the correct passphrase.

    Args:
        db_path: Path to the database file.
        passphrase: Encryption passphrase.

    Returns:
        True if read succeeded.
    """
    print("\n[3] Reading with correct passphrase using sqlcipher3...")

    try:
        conn = sqlcipher3.connect(str(db_path))
        escaped_key = passphrase.replace("'", "''")
        conn.execute(f"PRAGMA key = '{escaped_key}'")

        # Read the secrets
        cursor = conn.execute("SELECT name, value FROM secrets")
        rows = cursor.fetchall()

        print("    Decrypted secrets:")
        for name, value in rows:
            # Mask the value for display
            masked = value[:3] + "*" * (len(value) - 6) + value[-3:] if len(value) > 6 else "***"
            print(f"      - {name}: {masked}")

        conn.close()
        return True
    except Exception as e:
        print(f"    ERROR: Failed to read with passphrase: {e}")
        return False


def read_with_wrong_passphrase(db_path: Path) -> bool:
    """Try to read with wrong passphrase.

    Args:
        db_path: Path to the database file.

    Returns:
        True if read succeeded (should NOT happen).
    """
    print("\n[4] Attempting to read with WRONG passphrase...")

    try:
        conn = sqlcipher3.connect(str(db_path))
        conn.execute("PRAGMA key = 'wrong-password-123'")

        # This should fail
        conn.execute("SELECT count(*) FROM sqlite_master")
        conn.close()
        print("    WARNING: Read succeeded with wrong passphrase (encryption broken?)")
        return True
    except Exception as e:
        print("    SUCCESS: Wrong passphrase rejected")
        print(f"    Error: {e}")
        return False


def main() -> int:
    """Run the encrypted database demo."""
    print("=" * 70)
    print("SQLCIPHER ENCRYPTED DATABASE DEMO")
    print("=" * 70)

    if not HAS_SQLCIPHER:
        print("\n[ERROR] sqlcipher3 is not installed.")
        print("\nTo install:")
        print("  pip install kstlib[db-crypto]")
        print("\nSystem dependencies:")
        print("  Debian/Ubuntu: sudo apt-get install libsqlcipher-dev")
        print("  macOS:         brew install sqlcipher")
        print("  Windows:       See https://github.com/nickmccullum/pysqlcipher3-windows")
        return 1

    # Demo passphrase (in production, use env var or SOPS)
    passphrase = "my-super-secret-passphrase-2024"
    print(f"\nPassphrase: {passphrase[:10]}... (demo only, use SOPS in production)")

    # Create temp directory for demo
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "encrypted_secrets.db"

        # Step 1: Create encrypted database
        create_encrypted_db(db_path, passphrase)

        # Show file exists and has content
        file_size = db_path.stat().st_size
        print(f"\n    File size: {file_size:,} bytes")

        # Step 2: Try to read with standard sqlite3 (should fail)
        sqlite3_failed = not try_read_with_sqlite3(db_path)

        # Step 3: Read with correct passphrase (should work)
        correct_pass_worked = read_with_correct_passphrase(db_path, passphrase)

        # Step 4: Try wrong passphrase (should fail)
        wrong_pass_failed = not read_with_wrong_passphrase(db_path)

        # Summary
        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)

        all_passed = sqlite3_failed and correct_pass_worked and wrong_pass_failed

        print(f"\n  sqlite3 rejected (encrypted):  {'PASS' if sqlite3_failed else 'FAIL'}")
        print(f"  Correct passphrase works:      {'PASS' if correct_pass_worked else 'FAIL'}")
        print(f"  Wrong passphrase rejected:     {'PASS' if wrong_pass_failed else 'FAIL'}")
        print(f"\n  Overall: {'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")

        if all_passed:
            print("\n  The database is properly encrypted with AES-256.")
            print("  Without the passphrase, the data is completely unreadable.")

        # Note about kstlib integration
        print("\n" + "-" * 70)
        print("INTEGRATION WITH KSTLIB")
        print("-" * 70)
        print("""
  Current status: cipher.py provides key resolution utilities but
  AsyncDatabase uses aiosqlite which wraps standard sqlite3.

  For full SQLCipher support, use sqlcipher3 directly (sync) or
  wait for async SQLCipher integration in a future release.

  Key resolution options (kstlib.db.cipher.resolve_cipher_key):
    - passphrase: Direct string (demo only)
    - env_var: Environment variable name
    - sops_path: SOPS-encrypted file path

  Example with SOPS:
    from kstlib.db.cipher import resolve_cipher_key
    key = resolve_cipher_key(sops_path="secrets.yml", sops_key="db_key")
        """)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
