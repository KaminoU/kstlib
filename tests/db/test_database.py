"""Tests for AsyncDatabase."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from kstlib.db.database import AsyncDatabase
from kstlib.db.exceptions import EncryptionError, TransactionError
from kstlib.db.pool import PoolStats

if TYPE_CHECKING:
    from pathlib import Path


class TestAsyncDatabaseInit:
    """Tests for AsyncDatabase initialization."""

    def test_basic_init(self) -> None:
        """Basic initialization with path."""
        db = AsyncDatabase(":memory:")
        assert db.path == ":memory:"
        assert db.pool_min == 1
        assert db.pool_max == 10

    def test_path_converted_to_string(self, temp_db_path: Path) -> None:
        """Path object is converted to string."""
        db = AsyncDatabase(temp_db_path)
        assert isinstance(db.path, str)

    def test_custom_pool_settings(self) -> None:
        """Custom pool settings are applied."""
        db = AsyncDatabase(
            ":memory:",
            pool_min=2,
            pool_max=20,
            pool_timeout=60.0,
            max_retries=5,
        )
        assert db.pool_min == 2
        assert db.pool_max == 20
        assert db.pool_timeout == 60.0
        assert db.max_retries == 5

    def test_cipher_key_resolved(self) -> None:
        """Direct cipher key is resolved."""
        db = AsyncDatabase(":memory:", cipher_key="my-secret")
        assert db.is_encrypted
        assert db._resolved_key == "my-secret"

    def test_cipher_env_resolved(self) -> None:
        """Cipher key from env var is resolved."""
        with patch.dict(os.environ, {"DB_SECRET": "env-secret"}):
            db = AsyncDatabase(":memory:", cipher_env="DB_SECRET")
            assert db.is_encrypted
            assert db._resolved_key == "env-secret"

    def test_cipher_env_missing_raises(self) -> None:
        """Missing cipher env var raises EncryptionError."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MISSING_VAR", None)
            with pytest.raises(EncryptionError):
                AsyncDatabase(":memory:", cipher_env="MISSING_VAR")

    def test_no_encryption_by_default(self) -> None:
        """Database is not encrypted by default."""
        db = AsyncDatabase(":memory:")
        assert not db.is_encrypted
        assert db._resolved_key is None


class TestAsyncDatabaseOperations:
    """Tests for AsyncDatabase operations."""

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Database works as async context manager."""
        async with AsyncDatabase(":memory:") as db:
            assert db.pool_size >= 1
        assert db.pool_size == 0

    @pytest.mark.asyncio
    async def test_connect_initializes_pool(self) -> None:
        """Connect initializes the connection pool."""
        db = AsyncDatabase(":memory:")
        await db.connect()
        try:
            assert db.pool_size >= 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_close_shuts_down_pool(self) -> None:
        """Close shuts down the pool."""
        db = AsyncDatabase(":memory:")
        await db.connect()
        await db.close()
        assert db.pool_size == 0

    @pytest.mark.asyncio
    async def test_execute(self) -> None:
        """Execute runs SQL statement."""
        async with AsyncDatabase(":memory:") as db:
            await db.execute("CREATE TABLE test (id INTEGER)")
            await db.execute("INSERT INTO test VALUES (?)", (1,))

            row = await db.fetch_one("SELECT * FROM test")
            assert row == (1,)

    @pytest.mark.asyncio
    async def test_executemany(self) -> None:
        """Executemany runs multiple inserts."""
        async with AsyncDatabase(":memory:") as db:
            await db.execute("CREATE TABLE test (id INTEGER)")
            await db.executemany(
                "INSERT INTO test VALUES (?)",
                [(1,), (2,), (3,)],
            )

            rows = await db.fetch_all("SELECT * FROM test ORDER BY id")
            assert rows == [(1,), (2,), (3,)]

    @pytest.mark.asyncio
    async def test_fetch_one(self) -> None:
        """Fetch_one returns single row."""
        async with AsyncDatabase(":memory:") as db:
            await db.execute("CREATE TABLE test (id INTEGER, name TEXT)")
            await db.execute("INSERT INTO test VALUES (?, ?)", (1, "alice"))

            row = await db.fetch_one("SELECT * FROM test WHERE id=?", (1,))
            assert row == (1, "alice")

    @pytest.mark.asyncio
    async def test_fetch_one_no_results(self) -> None:
        """Fetch_one returns None when no results."""
        async with AsyncDatabase(":memory:") as db:
            await db.execute("CREATE TABLE test (id INTEGER)")

            row = await db.fetch_one("SELECT * FROM test")
            assert row is None

    @pytest.mark.asyncio
    async def test_fetch_all(self) -> None:
        """Fetch_all returns all rows."""
        async with AsyncDatabase(":memory:") as db:
            await db.execute("CREATE TABLE test (id INTEGER)")
            await db.executemany("INSERT INTO test VALUES (?)", [(1,), (2,), (3,)])

            rows = await db.fetch_all("SELECT * FROM test ORDER BY id")
            assert rows == [(1,), (2,), (3,)]

    @pytest.mark.asyncio
    async def test_fetch_all_empty(self) -> None:
        """Fetch_all returns empty list when no results."""
        async with AsyncDatabase(":memory:") as db:
            await db.execute("CREATE TABLE test (id INTEGER)")

            rows = await db.fetch_all("SELECT * FROM test")
            assert rows == []

    @pytest.mark.asyncio
    async def test_fetch_value(self) -> None:
        """Fetch_value returns single value."""
        async with AsyncDatabase(":memory:") as db:
            await db.execute("CREATE TABLE test (id INTEGER)")
            await db.executemany("INSERT INTO test VALUES (?)", [(1,), (2,), (3,)])

            count = await db.fetch_value("SELECT count(*) FROM test")
            assert count == 3

    @pytest.mark.asyncio
    async def test_fetch_value_none(self) -> None:
        """Fetch_value returns None when no results."""
        async with AsyncDatabase(":memory:") as db:
            await db.execute("CREATE TABLE test (id INTEGER)")

            value = await db.fetch_value("SELECT id FROM test LIMIT 1")
            assert value is None

    @pytest.mark.asyncio
    async def test_table_exists_true(self) -> None:
        """Table_exists returns True for existing table."""
        async with AsyncDatabase(":memory:") as db:
            await db.execute("CREATE TABLE users (id INTEGER)")

            assert await db.table_exists("users") is True

    @pytest.mark.asyncio
    async def test_table_exists_false(self) -> None:
        """Table_exists returns False for non-existent table."""
        async with AsyncDatabase(":memory:") as db:
            assert await db.table_exists("nonexistent") is False


class TestAsyncDatabaseTransaction:
    """Tests for transaction support."""

    @pytest.mark.asyncio
    async def test_transaction_commits_on_success(self) -> None:
        """Successful transaction commits changes."""
        async with AsyncDatabase(":memory:") as db:
            await db.execute("CREATE TABLE test (id INTEGER)")

            async with db.transaction() as conn:
                await conn.execute("INSERT INTO test VALUES (1)")
                await conn.execute("INSERT INTO test VALUES (2)")

            rows = await db.fetch_all("SELECT * FROM test ORDER BY id")
            assert rows == [(1,), (2,)]

    @pytest.mark.asyncio
    async def test_transaction_rollback_on_error(self) -> None:
        """Failed transaction rolls back changes."""
        async with AsyncDatabase(":memory:") as db:
            # Setup with committed data
            async with db.transaction() as conn:
                await conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")
                await conn.execute("INSERT INTO test VALUES (1)")

            with pytest.raises(TransactionError):
                async with db.transaction() as conn:
                    await conn.execute("INSERT INTO test VALUES (2)")
                    # This will fail - duplicate key
                    await conn.execute("INSERT INTO test VALUES (1)")

            # Only original row remains
            rows = await db.fetch_all("SELECT * FROM test")
            assert rows == [(1,)]

    @pytest.mark.asyncio
    async def test_nested_connection_calls(self, temp_db_path: Path) -> None:
        """Multiple connection calls work independently."""
        # Use file database for multi-connection test
        async with AsyncDatabase(temp_db_path, pool_min=2, pool_max=5) as db:
            # Setup table in transaction
            async with db.transaction() as conn:
                await conn.execute("CREATE TABLE test (id INTEGER)")

            async with db.connection() as conn1:
                await conn1.execute("INSERT INTO test VALUES (1)")
                await conn1.commit()

                async with db.connection() as conn2:
                    cursor = await conn2.execute("SELECT count(*) FROM test")
                    row = await cursor.fetchone()
                    assert row is not None
                    assert row[0] == 1


class TestAsyncDatabaseStats:
    """Tests for statistics."""

    @pytest.mark.asyncio
    async def test_stats_type(self) -> None:
        """Stats returns PoolStats object."""
        async with AsyncDatabase(":memory:") as db:
            assert isinstance(db.stats, PoolStats)

    @pytest.mark.asyncio
    async def test_stats_before_connect(self) -> None:
        """Stats returns empty before connect."""
        db = AsyncDatabase(":memory:")
        stats = db.stats
        assert stats.total_connections == 0

    @pytest.mark.asyncio
    async def test_stats_after_operations(self) -> None:
        """Stats track operations."""
        async with AsyncDatabase(":memory:") as db:
            await db.execute("SELECT 1")
            await db.execute("SELECT 2")

            stats = db.stats
            assert stats.total_acquired >= 2


class TestAsyncDatabaseFileBased:
    """Tests for file-based databases."""

    @pytest.mark.asyncio
    async def test_file_database_persistence(self, temp_db_path: Path) -> None:
        """Data persists across connections."""
        # Write data with transaction (ensures commit)
        async with AsyncDatabase(temp_db_path) as db, db.transaction() as conn:
            await conn.execute("CREATE TABLE test (id INTEGER)")
            await conn.execute("INSERT INTO test VALUES (42)")

        # Read data in new connection
        async with AsyncDatabase(temp_db_path) as db:
            value = await db.fetch_value("SELECT id FROM test")
            assert value == 42

    @pytest.mark.asyncio
    async def test_connection_helper(self) -> None:
        """Connection context manager works."""
        async with AsyncDatabase(":memory:") as db, db.connection() as conn:
            cursor = await conn.execute("SELECT 1")
            row = await cursor.fetchone()
            assert row == (1,)
