"""Database module exceptions."""

from __future__ import annotations

from kstlib.config.exceptions import KstlibError


class DatabaseError(KstlibError):
    """Base exception for database operations."""


class DatabaseConnectionError(DatabaseError):
    """Failed to establish database connection."""


class EncryptionError(DatabaseError):
    """Failed to decrypt or access encrypted database."""


class PoolExhaustedError(DatabaseError):
    """Connection pool exhausted, no connections available."""


class TransactionError(DatabaseError):
    """Transaction operation failed."""
