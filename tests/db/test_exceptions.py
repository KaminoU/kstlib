"""Tests for database exceptions."""

from __future__ import annotations

import pytest

from kstlib.db.exceptions import (
    DatabaseConnectionError,
    DatabaseError,
    EncryptionError,
    PoolExhaustedError,
    TransactionError,
)


class TestDatabaseError:
    """Tests for DatabaseError base exception."""

    def test_is_exception(self) -> None:
        """DatabaseError inherits from Exception."""
        assert issubclass(DatabaseError, Exception)

    def test_can_be_raised(self) -> None:
        """DatabaseError can be raised and caught."""
        with pytest.raises(DatabaseError, match="test error"):
            raise DatabaseError("test error")


class TestConnectionError:
    """Tests for DatabaseConnectionError."""

    def test_inherits_from_database_error(self) -> None:
        """DatabaseConnectionError inherits from DatabaseError."""
        assert issubclass(DatabaseConnectionError, DatabaseError)

    def test_can_be_caught_as_database_error(self) -> None:
        """DatabaseConnectionError can be caught as DatabaseError."""
        with pytest.raises(DatabaseError):
            raise DatabaseConnectionError("connection failed")


class TestEncryptionError:
    """Tests for EncryptionError."""

    def test_inherits_from_database_error(self) -> None:
        """EncryptionError inherits from DatabaseError."""
        assert issubclass(EncryptionError, DatabaseError)

    def test_message_preserved(self) -> None:
        """EncryptionError preserves message."""
        err = EncryptionError("key not found")
        assert str(err) == "key not found"


class TestPoolExhaustedError:
    """Tests for PoolExhaustedError."""

    def test_inherits_from_database_error(self) -> None:
        """PoolExhaustedError inherits from DatabaseError."""
        assert issubclass(PoolExhaustedError, DatabaseError)


class TestTransactionError:
    """Tests for TransactionError."""

    def test_inherits_from_database_error(self) -> None:
        """TransactionError inherits from DatabaseError."""
        assert issubclass(TransactionError, DatabaseError)
