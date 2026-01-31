"""Async SQLCipher wrapper built on top of aiosqlite.

Provides async database connections with SQLCipher AES-256 encryption.
This module wraps aiosqlite to use sqlcipher3 instead of standard sqlite3.

Requirements:
    pip install kstlib[db-crypto]  # Installs sqlcipher3

Examples:
    Basic encrypted connection::

        import asyncio
        from kstlib.db.aiosqlcipher import connect

        async def main():
            async with connect(":memory:", cipher_key="secret") as db:
                await db.execute("CREATE TABLE test (id INTEGER)")

        asyncio.run(main())
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from kstlib.db.exceptions import EncryptionError

if TYPE_CHECKING:
    from aiosqlite import Connection

__all__ = ["connect", "is_sqlcipher_available"]

log = logging.getLogger(__name__)


def is_sqlcipher_available() -> bool:
    """Check if sqlcipher3 is installed and available.

    Returns:
        True if sqlcipher3 can be imported.

    Examples:
        >>> is_sqlcipher_available()  # doctest: +SKIP
        True
    """
    try:
        import sqlcipher3  # noqa: F401

        return True
    except ImportError:
        return False


def connect(
    database: str | Path,
    *,
    cipher_key: str,
    iter_chunk_size: int = 64,
    **kwargs: Any,
) -> Connection:
    """Create an async connection to an encrypted SQLite database.

    This function is a drop-in replacement for aiosqlite.connect() that
    uses SQLCipher for AES-256 encryption. The cipher key is applied
    immediately after connection using PRAGMA key.

    Args:
        database: Path to database file or ":memory:" for in-memory.
        cipher_key: Encryption key for SQLCipher (required).
        iter_chunk_size: Rows to fetch per iteration (default: 64).
        **kwargs: Additional arguments passed to sqlcipher3.connect().

    Returns:
        Async Connection object (same interface as aiosqlite.Connection).

    Raises:
        EncryptionError: If sqlcipher3 is not installed or key is empty.
        sqlite3.DatabaseError: If database exists but key is wrong.

    Examples:
        >>> async with connect("app.db", cipher_key="secret") as db:  # doctest: +SKIP
        ...     await db.execute("CREATE TABLE users (id INTEGER)")

        >>> # With SOPS key resolution:
        >>> from kstlib.db.cipher import resolve_cipher_key
        >>> key = resolve_cipher_key(sops_path="secrets.yml")  # doctest: +SKIP
        >>> async with connect("app.db", cipher_key=key) as db:  # doctest: +SKIP
        ...     pass
    """
    if not cipher_key:
        raise EncryptionError("cipher_key is required for encrypted connections")

    # Import sqlcipher3 (fail early if not installed)
    try:
        import sqlcipher3
    except ImportError as e:
        raise EncryptionError("sqlcipher3 is not installed. Install with: pip install kstlib[db-crypto]") from e

    # Import aiosqlite Connection class (we reuse its async machinery)
    from aiosqlite.core import Connection

    # Resolve path
    db_path = str(database) if isinstance(database, Path) else database

    def connector() -> sqlcipher3.Connection:
        """Create encrypted connection with key already applied.

        This runs in a worker thread (via aiosqlite).
        """
        # Enable autocommit by default (isolation_level=None)
        # This ensures data is persisted immediately without explicit commit
        # User can override by passing isolation_level in kwargs
        connect_kwargs = {"isolation_level": None, **kwargs}

        # Connect using sqlcipher3 (NOT standard sqlite3)
        conn = sqlcipher3.connect(db_path, **connect_kwargs)

        # Apply encryption key (MUST be first operation)
        # Escape single quotes to prevent SQL injection
        escaped_key = cipher_key.replace("'", "''")
        conn.execute(f"PRAGMA key = '{escaped_key}'")

        # Verify key works by reading schema
        # This will raise DatabaseError if key is wrong
        try:
            conn.execute("SELECT count(*) FROM sqlite_master")
        except Exception as e:
            conn.close()
            raise EncryptionError(f"Invalid cipher key or corrupted database: {e}") from e

        log.debug("SQLCipher connection established: %s", db_path)
        return conn

    # Return aiosqlite Connection with our custom connector
    return Connection(connector, iter_chunk_size)
