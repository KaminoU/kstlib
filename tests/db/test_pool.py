"""Tests for connection pool."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from kstlib.db.exceptions import DatabaseConnectionError, PoolExhaustedError
from kstlib.db.pool import ConnectionPool, PoolStats

if TYPE_CHECKING:
    from pathlib import Path


class TestPoolStats:
    """Tests for PoolStats dataclass."""

    def test_default_values(self) -> None:
        """Stats have zero defaults."""
        stats = PoolStats()
        assert stats.total_connections == 0
        assert stats.active_connections == 0
        assert stats.idle_connections == 0
        assert stats.total_acquired == 0
        assert stats.total_released == 0
        assert stats.total_timeouts == 0
        assert stats.total_errors == 0


class TestConnectionPool:
    """Tests for ConnectionPool."""

    def test_pool_creation(self) -> None:
        """Pool can be created with configuration."""
        pool = ConnectionPool(":memory:", min_size=2, max_size=10)
        assert pool.db_path == ":memory:"
        assert pool.min_size == 2
        assert pool.max_size == 10
        assert pool.size == 0  # Not initialized yet

    @pytest.mark.asyncio
    async def test_acquire_creates_connection(self) -> None:
        """Acquire creates connection on first call."""
        pool = ConnectionPool(":memory:", min_size=1, max_size=5)
        try:
            conn = await pool.acquire()
            assert conn is not None
            assert pool.stats.total_connections >= 1
            assert pool.stats.total_acquired == 1
            await pool.release(conn)
        finally:
            await pool.close()

    @pytest.mark.asyncio
    async def test_release_returns_to_pool(self) -> None:
        """Released connection is returned to pool."""
        pool = ConnectionPool(":memory:", min_size=1, max_size=5)
        try:
            conn = await pool.acquire()
            await pool.release(conn)
            assert pool.stats.total_released == 1
            assert pool.stats.active_connections == 0
        finally:
            await pool.close()

    @pytest.mark.asyncio
    async def test_connection_context_manager(self) -> None:
        """Connection context manager acquires and releases."""
        pool = ConnectionPool(":memory:", min_size=1, max_size=5)
        try:
            async with pool.connection() as conn:
                await conn.execute("SELECT 1")
                assert pool.stats.active_connections == 1
            assert pool.stats.active_connections == 0
            assert pool.stats.total_released == 1
        finally:
            await pool.close()

    @pytest.mark.asyncio
    async def test_pool_reuses_connections(self) -> None:
        """Released connections are reused."""
        pool = ConnectionPool(":memory:", min_size=1, max_size=2)
        try:
            # Acquire and release
            conn1 = await pool.acquire()
            await pool.release(conn1)

            # Acquire again - should reuse
            conn2 = await pool.acquire()
            await pool.release(conn2)

            # Only min_size connections created
            assert pool.stats.total_connections == 1
            assert pool.stats.total_acquired == 2
        finally:
            await pool.close()

    @pytest.mark.asyncio
    async def test_pool_grows_to_max(self) -> None:
        """Pool grows when connections are needed."""
        pool = ConnectionPool(":memory:", min_size=1, max_size=3, acquire_timeout=1.0)
        try:
            # Acquire all connections
            conns = []
            for _ in range(3):
                conn = await pool.acquire()
                conns.append(conn)

            assert pool.stats.total_connections == 3

            # Release all
            for conn in conns:
                await pool.release(conn)
        finally:
            await pool.close()

    @pytest.mark.asyncio
    async def test_pool_exhausted_raises(self) -> None:
        """Pool exhaustion raises PoolExhaustedError."""
        pool = ConnectionPool(":memory:", min_size=1, max_size=1, acquire_timeout=0.1)
        try:
            # Hold the only connection
            conn = await pool.acquire()

            # Try to acquire another
            with pytest.raises(PoolExhaustedError, match="Pool exhausted"):
                await pool.acquire()

            await pool.release(conn)
        finally:
            await pool.close()

    @pytest.mark.asyncio
    async def test_close_shuts_down_pool(self) -> None:
        """Close shuts down all connections."""
        pool = ConnectionPool(":memory:", min_size=2, max_size=5)
        async with pool.connection():
            pass  # Initialize pool

        await pool.close()
        assert pool.is_closed
        assert pool.stats.active_connections == 0
        assert pool.stats.idle_connections == 0

    @pytest.mark.asyncio
    async def test_acquire_after_close_raises(self) -> None:
        """Acquire after close raises DatabaseConnectionError."""
        pool = ConnectionPool(":memory:", min_size=1, max_size=5)
        await pool.close()

        with pytest.raises(DatabaseConnectionError, match="Pool is closed"):
            await pool.acquire()

    @pytest.mark.asyncio
    async def test_wal_mode_enabled(self, temp_db_path: Path) -> None:
        """WAL journal mode is enabled for file databases."""
        # WAL mode only works for file databases, not :memory:
        pool = ConnectionPool(str(temp_db_path), min_size=1, max_size=5)
        try:
            async with pool.connection() as conn:
                cursor = await conn.execute("PRAGMA journal_mode")
                row = await cursor.fetchone()
                assert row is not None
                assert row[0].lower() == "wal"
        finally:
            await pool.close()

    @pytest.mark.asyncio
    async def test_foreign_keys_enabled(self) -> None:
        """Foreign key enforcement is enabled."""
        pool = ConnectionPool(":memory:", min_size=1, max_size=5)
        try:
            async with pool.connection() as conn:
                cursor = await conn.execute("PRAGMA foreign_keys")
                row = await cursor.fetchone()
                assert row is not None
                assert row[0] == 1
        finally:
            await pool.close()

    @pytest.mark.asyncio
    async def test_on_connect_callback(self) -> None:
        """on_connect callback is called for new connections."""
        callback_count = 0

        async def on_connect(conn: object) -> None:
            nonlocal callback_count
            callback_count += 1

        pool = ConnectionPool(":memory:", min_size=1, max_size=5, on_connect=on_connect)
        try:
            async with pool.connection():
                pass
            assert callback_count >= 1
        finally:
            await pool.close()

    @pytest.mark.asyncio
    async def test_concurrent_acquires(self) -> None:
        """Multiple concurrent acquires work correctly."""
        pool = ConnectionPool(":memory:", min_size=1, max_size=5)
        try:

            async def worker(worker_id: int) -> int:
                async with pool.connection() as conn:
                    cursor = await conn.execute(f"SELECT {worker_id}")
                    row = await cursor.fetchone()
                    return row[0] if row else 0

            results = await asyncio.gather(*[worker(i) for i in range(5)])
            assert results == [0, 1, 2, 3, 4]
        finally:
            await pool.close()

    @pytest.mark.asyncio
    async def test_file_database(self, temp_db_path: Path) -> None:
        """Pool works with file-based database."""
        pool = ConnectionPool(str(temp_db_path), min_size=1, max_size=3)
        try:
            async with pool.connection() as conn:
                await conn.execute("CREATE TABLE test (id INTEGER)")
                await conn.execute("INSERT INTO test VALUES (1)")
                await conn.commit()

            # New connection sees data
            async with pool.connection() as conn:
                cursor = await conn.execute("SELECT * FROM test")
                row = await cursor.fetchone()
                assert row == (1,)
        finally:
            await pool.close()

    @pytest.mark.asyncio
    async def test_release_after_close(self) -> None:
        """Release after close closes the connection."""
        pool = ConnectionPool(":memory:", min_size=1, max_size=5)
        conn = await pool.acquire()
        await pool.close()

        # Release should close connection, not raise
        await pool.release(conn)

    @pytest.mark.asyncio
    async def test_close_with_already_closed_connection(self) -> None:
        """Close handles already-closed connections gracefully."""
        pool = ConnectionPool(":memory:", min_size=1, max_size=5)
        conn = await pool.acquire()
        await pool.release(conn)

        # Close the connection manually before pool close
        await conn.close()

        # Pool close should not raise even with closed connection
        await pool.close()

    @pytest.mark.asyncio
    async def test_dead_connection_is_replaced(self) -> None:
        """Dead connections are detected and replaced."""
        pool = ConnectionPool(":memory:", min_size=1, max_size=5, acquire_timeout=0.1)
        try:
            conn = await pool.acquire()
            await pool.release(conn)

            # Simulate dead connection by closing it after release
            await conn.close()

            # Next acquire should detect dead and get new connection
            conn2 = await pool.acquire()
            # Should work despite previous connection being dead
            cursor = await conn2.execute("SELECT 1")
            row = await cursor.fetchone()
            assert row == (1,)
            await pool.release(conn2)
        finally:
            await pool.close()

    @pytest.mark.asyncio
    async def test_connection_retry_on_failure(self) -> None:
        """Connection retries on transient failures."""
        import aiosqlite

        call_count = 0
        original_connect = aiosqlite.connect

        async def flaky_connect(*args: object, **kwargs: object) -> object:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RuntimeError("Transient connection failure")
            return await original_connect(":memory:")

        pool = ConnectionPool(":memory:", min_size=0, max_size=5, max_retries=3, retry_delay=0.1, acquire_timeout=0.1)
        try:
            with patch.object(aiosqlite, "connect", side_effect=flaky_connect):
                conn = await pool.acquire()
                await pool.release(conn)

            assert call_count >= 2
            assert pool.stats.total_errors >= 1
        finally:
            await pool.close()

    @pytest.mark.asyncio
    async def test_connection_fails_after_max_retries(self) -> None:
        """Connection raises after exhausting retries."""
        import aiosqlite

        async def always_fail(*args: object, **kwargs: object) -> None:
            raise RuntimeError("Connection failure")

        pool = ConnectionPool(":memory:", min_size=0, max_size=5, max_retries=2, retry_delay=0.1, acquire_timeout=0.1)
        try:
            with (
                patch.object(aiosqlite, "connect", side_effect=always_fail),
                pytest.raises(DatabaseConnectionError, match="Failed to acquire connection"),
            ):
                await pool.acquire()

            assert pool.stats.total_errors >= 2
        finally:
            await pool.close()

    def test_cipher_key_stored(self) -> None:
        """Cipher key is stored in pool configuration."""
        pool = ConnectionPool(":memory:", min_size=1, max_size=5, cipher_key="secret")
        assert pool.cipher_key == "secret"

    def test_no_cipher_key_by_default(self) -> None:
        """No cipher key by default."""
        pool = ConnectionPool(":memory:", min_size=1, max_size=5)
        assert pool.cipher_key is None

    @pytest.mark.asyncio
    async def test_auto_vacuum_incremental_on_new_db(self, temp_db_path: Path) -> None:
        """New file database gets auto_vacuum set to INCREMENTAL."""
        pool = ConnectionPool(str(temp_db_path), min_size=1, max_size=2)
        try:
            async with pool.connection() as conn:
                cursor = await conn.execute("PRAGMA auto_vacuum")
                row = await cursor.fetchone()
                assert row is not None
                assert row[0] == 2  # INCREMENTAL
        finally:
            await pool.close()

    @pytest.mark.asyncio
    async def test_auto_vacuum_unchanged_on_existing_db(self, temp_db_path: Path) -> None:
        """Existing database with tables keeps its auto_vacuum mode."""
        import aiosqlite

        # Pre-populate the database with a table (auto_vacuum defaults to NONE=0)
        async with aiosqlite.connect(str(temp_db_path)) as conn:
            await conn.execute("CREATE TABLE setup (id INTEGER)")
            await conn.commit()

        pool = ConnectionPool(str(temp_db_path), min_size=1, max_size=2)
        try:
            async with pool.connection() as conn:
                cursor = await conn.execute("PRAGMA auto_vacuum")
                row = await cursor.fetchone()
                assert row is not None
                assert row[0] == 0  # NONE (unchanged)
        finally:
            await pool.close()

    @pytest.mark.asyncio
    async def test_optimize_on_close(self) -> None:
        """PRAGMA optimize is executed on each connection at close."""
        pool = ConnectionPool(":memory:", min_size=1, max_size=2)
        async with pool.connection() as conn:
            await conn.execute("SELECT 1")

        # Track execute calls via wrapper
        executed_statements: list[str] = []
        for conn in pool._connections:
            original_execute = conn.execute

            async def tracking_execute(
                sql: str, *args: object, _orig: object = original_execute, **kwargs: object
            ) -> object:
                executed_statements.append(str(sql))
                return await _orig(sql, *args, **kwargs)  # type: ignore[operator]

            conn.execute = tracking_execute  # type: ignore[assignment]

        await pool.close()
        assert any("optimize" in s for s in executed_statements), "PRAGMA optimize not called"

    @pytest.mark.asyncio
    async def test_auto_vacuum_skipped_for_memory_db(self) -> None:
        """Memory databases skip auto_vacuum setup."""
        pool = ConnectionPool(":memory:", min_size=1, max_size=2)
        try:
            async with pool.connection() as conn:
                cursor = await conn.execute("PRAGMA auto_vacuum")
                row = await cursor.fetchone()
                assert row is not None
                assert row[0] == 0  # NONE (default for :memory:)
        finally:
            await pool.close()

    @pytest.mark.asyncio
    async def test_plain_sqlite_persists_after_close(self, temp_db_path: Path) -> None:
        """Plain SQLite path uses autocommit so data survives connection close."""
        pool = ConnectionPool(str(temp_db_path), min_size=1, max_size=1)
        try:
            async with pool.connection() as conn:
                await conn.execute("CREATE TABLE candles (id INTEGER PRIMARY KEY)")
                await conn.executemany(
                    "INSERT INTO candles (id) VALUES (?)",
                    [(i,) for i in range(100)],
                )
        finally:
            await pool.close()

        # Reopen with a fresh pool and verify rows persisted
        pool2 = ConnectionPool(str(temp_db_path), min_size=1, max_size=1)
        try:
            async with pool2.connection() as conn:
                cursor = await conn.execute("SELECT count(*) FROM candles")
                row = await cursor.fetchone()
                assert row is not None
                assert row[0] == 100
        finally:
            await pool2.close()
