"""Async database module for SQLite/SQLCipher.

Provides:
- AsyncDatabase: High-level async interface
- ConnectionPool: Connection pooling with retry
- SQLCipher encryption via SOPS integration

Examples:
    Basic in-memory database:

    >>> from kstlib.db import AsyncDatabase
    >>> db = AsyncDatabase(":memory:")

    Encrypted database with SOPS:

    >>> db = AsyncDatabase(  # doctest: +SKIP
    ...     "app.db",
    ...     cipher_sops="secrets.yml",
    ...     cipher_sops_key="database_key"
    ... )

    Usage as context manager:

    >>> async with AsyncDatabase(":memory:") as db:  # doctest: +SKIP
    ...     await db.execute("CREATE TABLE test (id INTEGER)")
    ...     await db.execute("INSERT INTO test VALUES (?)", (1,))
    ...     row = await db.fetch_one("SELECT * FROM test")
"""

from kstlib.db.aiosqlcipher import is_sqlcipher_available
from kstlib.db.cipher import apply_cipher_key, resolve_cipher_key
from kstlib.db.database import AsyncDatabase
from kstlib.db.exceptions import (
    DatabaseConnectionError,
    DatabaseError,
    EncryptionError,
    PoolExhaustedError,
    TransactionError,
)
from kstlib.db.pool import ConnectionPool, PoolStats

__all__ = [
    "AsyncDatabase",
    "ConnectionPool",
    "DatabaseConnectionError",
    "DatabaseError",
    "EncryptionError",
    "PoolExhaustedError",
    "PoolStats",
    "TransactionError",
    "apply_cipher_key",
    "is_sqlcipher_available",
    "resolve_cipher_key",
]
