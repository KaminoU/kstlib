"""SQLCipher integration with SOPS secret resolution.

Provides secure key management for encrypted SQLite databases.
Keys can be loaded from:
- Direct passphrase
- Environment variable
- SOPS-encrypted file via kstlib.secrets
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from kstlib.db.exceptions import EncryptionError

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

log = logging.getLogger(__name__)


def resolve_cipher_key(
    *,
    passphrase: str | None = None,
    env_var: str | None = None,
    sops_path: str | Path | None = None,
    sops_key: str = "db_key",
) -> str:
    """Resolve encryption key from various sources.

    Priority: passphrase > env_var > sops_path

    Args:
        passphrase: Direct passphrase string.
        env_var: Environment variable name containing the key.
        sops_path: Path to SOPS-encrypted file.
        sops_key: Key name within SOPS file (default: "db_key").

    Returns:
        Resolved encryption key.

    Raises:
        EncryptionError: If no key source provided or resolution fails.

    Examples:
        >>> key = resolve_cipher_key(passphrase="my-secret-key")
        >>> len(key) > 0
        True
    """
    # Direct passphrase (highest priority)
    if passphrase:
        return passphrase

    # Environment variable
    if env_var:
        import os

        key = os.environ.get(env_var)
        if key:
            log.debug("Resolved cipher key from env var: %s", env_var)
            return key
        raise EncryptionError(f"Environment variable '{env_var}' not set or empty")

    # SOPS file
    if sops_path:
        try:
            from kstlib.secrets.models import SecretRequest
            from kstlib.secrets.providers.sops import SOPSProvider

            provider = SOPSProvider(path=sops_path)
            request = SecretRequest(name=sops_key, required=True)
            record = provider.resolve(request)
            if record is None or record.value is None:
                raise EncryptionError(f"Key '{sops_key}' not found in SOPS file")
            log.debug("Resolved cipher key from SOPS: %s", sops_path)
            return str(record.value)
        except ImportError as e:
            raise EncryptionError("kstlib.secrets required for SOPS support") from e
        except Exception as e:
            raise EncryptionError(f"Failed to resolve SOPS key: {e}") from e

    raise EncryptionError("No encryption key source provided. Specify passphrase, env_var, or sops_path.")


def apply_cipher_key(conn: sqlite3.Connection, key: str) -> None:
    """Apply SQLCipher key to a connection.

    Args:
        conn: SQLite connection object.
        key: Encryption key to apply.

    Raises:
        EncryptionError: If key application fails.
    """
    try:
        # SQLCipher PRAGMA to set key
        # Escape single quotes to prevent SQL injection
        escaped_key = key.replace("'", "''")
        cursor = conn.execute(f"PRAGMA key = '{escaped_key}'")
        cursor.close()
        # Verify key works by reading schema
        cursor = conn.execute("SELECT count(*) FROM sqlite_master")
        cursor.fetchone()
        cursor.close()
        log.debug("SQLCipher key applied successfully")
    except Exception as e:
        raise EncryptionError(f"Failed to apply cipher key: {e}") from e


__all__ = ["apply_cipher_key", "resolve_cipher_key"]
