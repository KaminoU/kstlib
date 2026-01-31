"""Connection pool with retry support for async SQLite.

Provides connection pooling with:
- Configurable pool size
- Connection health checks
- Automatic retry on transient failures
- Graceful shutdown
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from kstlib.db.exceptions import DatabaseConnectionError, PoolExhaustedError
from kstlib.limits import (
    HARD_MAX_DB_MAX_RETRIES,
    HARD_MAX_DB_RETRY_DELAY,
    HARD_MAX_POOL_ACQUIRE_TIMEOUT,
    HARD_MAX_POOL_MAX_SIZE,
    HARD_MAX_POOL_MIN_SIZE,
    HARD_MIN_DB_MAX_RETRIES,
    HARD_MIN_DB_RETRY_DELAY,
    HARD_MIN_POOL_ACQUIRE_TIMEOUT,
    HARD_MIN_POOL_MAX_SIZE,
    HARD_MIN_POOL_MIN_SIZE,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    import aiosqlite

log = logging.getLogger(__name__)


@dataclass
class PoolStats:
    """Statistics for connection pool monitoring.

    Attributes:
        total_connections: Total connections created.
        active_connections: Currently in-use connections.
        idle_connections: Available connections in pool.
        total_acquired: Total acquire operations.
        total_released: Total release operations.
        total_timeouts: Acquire operations that timed out.
        total_errors: Connection errors encountered.

    Examples:
        >>> stats = PoolStats()
        >>> stats.total_connections
        0
    """

    total_connections: int = 0
    active_connections: int = 0
    idle_connections: int = 0
    total_acquired: int = 0
    total_released: int = 0
    total_timeouts: int = 0
    total_errors: int = 0


@dataclass
class ConnectionPool:
    """Async connection pool for SQLite/SQLCipher databases.

    Manages a pool of database connections with health checks
    and automatic retry on failures.

    Args:
        db_path: Path to database file.
        min_size: Minimum connections to maintain.
        max_size: Maximum connections allowed.
        acquire_timeout: Timeout for acquiring connection.
        max_retries: Retry attempts on failure.
        retry_delay: Delay between retries.
        cipher_key: Optional encryption key for SQLCipher.
        on_connect: Callback after connection established.

    Examples:
        >>> pool = ConnectionPool(":memory:", min_size=1, max_size=5)
        >>> pool.max_size
        5
    """

    db_path: str
    min_size: int = 1
    max_size: int = 10
    acquire_timeout: float = 30.0
    max_retries: int = 3
    retry_delay: float = 0.5
    cipher_key: str | None = None
    on_connect: Any | None = None  # Callable[[aiosqlite.Connection], Awaitable[None]]

    _pool: asyncio.Queue[aiosqlite.Connection] = field(default_factory=lambda: asyncio.Queue(), repr=False)
    _connections: set[aiosqlite.Connection] = field(default_factory=set, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _closed: bool = field(default=False, repr=False)
    _stats: PoolStats = field(default_factory=PoolStats, repr=False)

    def __post_init__(self) -> None:
        """Validate and clamp configuration values to hard limits."""
        # Clamp pool sizes
        self.min_size = max(HARD_MIN_POOL_MIN_SIZE, min(HARD_MAX_POOL_MIN_SIZE, self.min_size))
        self.max_size = max(HARD_MIN_POOL_MAX_SIZE, min(HARD_MAX_POOL_MAX_SIZE, self.max_size))

        # Ensure min_size <= max_size
        self.min_size = min(self.min_size, self.max_size)

        # Clamp timeouts and delays
        self.acquire_timeout = max(
            HARD_MIN_POOL_ACQUIRE_TIMEOUT, min(HARD_MAX_POOL_ACQUIRE_TIMEOUT, self.acquire_timeout)
        )
        self.max_retries = max(HARD_MIN_DB_MAX_RETRIES, min(HARD_MAX_DB_MAX_RETRIES, self.max_retries))
        self.retry_delay = max(HARD_MIN_DB_RETRY_DELAY, min(HARD_MAX_DB_RETRY_DELAY, self.retry_delay))

    async def _create_connection(self) -> aiosqlite.Connection:
        """Create a new database connection.

        Uses aiosqlcipher for encrypted connections (when cipher_key is set),
        or standard aiosqlite for unencrypted connections.
        """
        if self.cipher_key:
            # Use SQLCipher for encrypted database
            from kstlib.db.aiosqlcipher import connect as aiosqlcipher_connect

            conn = await aiosqlcipher_connect(self.db_path, cipher_key=self.cipher_key)
        else:
            # Use standard sqlite3 for unencrypted database
            import aiosqlite

            conn = await aiosqlite.connect(self.db_path)

        # Enable WAL mode for better concurrency (works with both)
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA foreign_keys=ON")

        # Call custom on_connect handler
        if self.on_connect:
            await self.on_connect(conn)

        self._stats.total_connections += 1
        log.debug("Created new database connection (total: %d)", self._stats.total_connections)
        return conn

    async def _init_pool(self) -> None:
        """Initialize the connection pool with min_size connections."""
        async with self._lock:
            for _ in range(self.min_size):
                conn = await self._create_connection()
                self._connections.add(conn)
                await self._pool.put(conn)
            self._stats.idle_connections = self.min_size

    async def acquire(self) -> aiosqlite.Connection:
        """Acquire a connection from the pool.

        Returns:
            Database connection.

        Raises:
            PoolExhaustedError: If no connection available within timeout.
            DatabaseConnectionError: If connection creation fails after retries.
        """
        if self._closed:
            raise DatabaseConnectionError("Pool is closed")

        # Initialize pool on first acquire
        if not self._connections:
            await self._init_pool()

        for attempt in range(self.max_retries):
            try:
                # Try to get from pool with timeout
                try:
                    conn = await asyncio.wait_for(self._pool.get(), timeout=self.acquire_timeout)
                    self._stats.idle_connections -= 1
                except asyncio.TimeoutError:
                    # Pool empty, try to create new if under max
                    async with self._lock:
                        if len(self._connections) < self.max_size:
                            conn = await self._create_connection()
                            self._connections.add(conn)
                        else:
                            self._stats.total_timeouts += 1
                            raise PoolExhaustedError(
                                f"Pool exhausted (max={self.max_size}), timeout after {self.acquire_timeout}s"
                            ) from None

                # Verify connection is alive
                try:
                    await conn.execute("SELECT 1")
                except Exception:
                    # Connection dead, remove and retry
                    self._connections.discard(conn)
                    await conn.close()
                    self._stats.total_errors += 1
                    continue

                self._stats.active_connections += 1
                self._stats.total_acquired += 1
                return conn

            except PoolExhaustedError:
                raise
            except Exception as e:
                self._stats.total_errors += 1
                if attempt < self.max_retries - 1:
                    log.warning(
                        "Connection attempt %d failed: %s, retrying...",
                        attempt + 1,
                        e,
                    )
                    await asyncio.sleep(self.retry_delay)
                else:
                    raise DatabaseConnectionError(
                        f"Failed to acquire connection after {self.max_retries} attempts"
                    ) from e

        raise DatabaseConnectionError("Failed to acquire connection")

    async def release(self, conn: aiosqlite.Connection) -> None:
        """Release a connection back to the pool.

        Args:
            conn: Connection to release.
        """
        if self._closed:
            await conn.close()
            return

        self._stats.active_connections -= 1
        self._stats.total_released += 1

        # Return to pool
        await self._pool.put(conn)
        self._stats.idle_connections += 1

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """Context manager for acquiring and releasing connections.

        Yields:
            Database connection.

        Examples:
            >>> async with pool.connection() as conn:  # doctest: +SKIP
            ...     await conn.execute("SELECT 1")
        """
        conn = await self.acquire()
        try:
            yield conn
        finally:
            await self.release(conn)

    async def close(self) -> None:
        """Close all connections and shutdown the pool."""
        self._closed = True

        async with self._lock:
            # Close all connections
            for conn in self._connections:
                try:
                    await conn.close()
                except Exception:
                    # Connection may be already closed - intentional silent catch
                    log.debug("Failed to close connection (may be already closed)", exc_info=True)
            self._connections.clear()

            # Empty the queue
            while not self._pool.empty():
                try:
                    self._pool.get_nowait()
                except asyncio.QueueEmpty:
                    break

        self._stats.active_connections = 0
        self._stats.idle_connections = 0
        log.debug("Connection pool closed")

    @property
    def stats(self) -> PoolStats:
        """Get pool statistics."""
        return self._stats

    @property
    def size(self) -> int:
        """Current number of connections in pool."""
        return len(self._connections)

    @property
    def is_closed(self) -> bool:
        """Whether the pool is closed."""
        return self._closed


__all__ = ["ConnectionPool", "PoolStats"]
