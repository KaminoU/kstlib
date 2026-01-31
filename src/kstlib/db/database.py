"""Async database wrapper for SQLite/SQLCipher.

Provides a high-level async interface for database operations with:
- Connection pooling
- Automatic retry on transient failures
- SQLCipher encryption support
- Transaction management
- Query helpers
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from typing_extensions import Self

from kstlib.db.exceptions import TransactionError
from kstlib.db.pool import ConnectionPool, PoolStats

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Sequence
    from pathlib import Path

    import aiosqlite

log = logging.getLogger(__name__)


@dataclass
class AsyncDatabase:
    """Async database interface for SQLite/SQLCipher.

    Provides connection pooling, encryption, and query helpers
    for async database operations.

    Args:
        path: Path to database file (or ":memory:" for in-memory).
        cipher_key: Direct encryption key for SQLCipher.
        cipher_env: Environment variable containing cipher key.
        cipher_sops: Path to SOPS file containing cipher key.
        cipher_sops_key: Key name in SOPS file (default: "db_key").
        pool_min: Minimum pool connections.
        pool_max: Maximum pool connections.
        pool_timeout: Acquire timeout in seconds.
        max_retries: Retry attempts on failure.
        retry_delay: Delay between retries.

    Examples:
        Basic usage:

        >>> db = AsyncDatabase(":memory:")
        >>> db.path
        ':memory:'

        With encryption:

        >>> db = AsyncDatabase("app.db", cipher_key="secret")  # doctest: +SKIP

        With SOPS:

        >>> db = AsyncDatabase("app.db", cipher_sops="secrets.yml")  # doctest: +SKIP
    """

    path: str | Path
    cipher_key: str | None = None
    cipher_env: str | None = None
    cipher_sops: str | Path | None = None
    cipher_sops_key: str = "db_key"
    pool_min: int = 1
    pool_max: int = 10
    pool_timeout: float = 30.0
    max_retries: int = 3
    retry_delay: float = 0.5

    _pool: ConnectionPool | None = field(default=None, repr=False)
    _resolved_key: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Resolve cipher key and apply config defaults with hard limits."""
        from kstlib.limits import get_db_limits

        self.path = str(self.path)

        # Load config defaults for any unset pool/retry params
        limits = get_db_limits()

        # Apply config defaults if using dataclass defaults (sentinel check)
        # Use object.__setattr__ since dataclass fields are set
        if self.pool_min == 1:
            object.__setattr__(self, "pool_min", limits.pool_min_size)
        if self.pool_max == 10:
            object.__setattr__(self, "pool_max", limits.pool_max_size)
        if self.pool_timeout == 30.0:
            object.__setattr__(self, "pool_timeout", limits.pool_acquire_timeout)
        if self.max_retries == 3:
            object.__setattr__(self, "max_retries", limits.max_retries)
        if self.retry_delay == 0.5:
            object.__setattr__(self, "retry_delay", limits.retry_delay)

        # Resolve encryption key if any source provided
        if self.cipher_key or self.cipher_env or self.cipher_sops:
            from kstlib.db.cipher import resolve_cipher_key

            self._resolved_key = resolve_cipher_key(
                passphrase=self.cipher_key,
                env_var=self.cipher_env,
                sops_path=self.cipher_sops,
                sops_key=self.cipher_sops_key,
            )

    def _ensure_pool(self) -> ConnectionPool:
        """Ensure connection pool is initialized."""
        if self._pool is None:
            # path is already converted to str in __post_init__
            db_path = self.path if isinstance(self.path, str) else str(self.path)
            self._pool = ConnectionPool(
                db_path=db_path,
                min_size=self.pool_min,
                max_size=self.pool_max,
                acquire_timeout=self.pool_timeout,
                max_retries=self.max_retries,
                retry_delay=self.retry_delay,
                cipher_key=self._resolved_key,
            )
        return self._pool

    async def connect(self) -> None:
        """Initialize the connection pool.

        Called automatically on first operation, but can be
        called explicitly for eager initialization.
        """
        pool = self._ensure_pool()
        await pool._init_pool()
        log.info("Database connected: %s", self.path)

    async def close(self) -> None:
        """Close all connections and shutdown the pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
        # Scrub resolved key from memory
        self._resolved_key = None
        log.info("Database closed: %s", self.path)

    async def __aenter__(self) -> Self:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Async context manager exit."""
        await self.close()

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """Get a connection from the pool.

        Yields:
            Database connection.

        Examples:
            >>> async with db.connection() as conn:  # doctest: +SKIP
            ...     await conn.execute("SELECT 1")
        """
        pool = self._ensure_pool()
        async with pool.connection() as conn:
            yield conn

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """Execute operations within a transaction.

        Automatically commits on success, rolls back on error.

        Yields:
            Database connection within transaction.

        Raises:
            TransactionError: If transaction fails.

        Examples:
            >>> async with db.transaction() as conn:  # doctest: +SKIP
            ...     await conn.execute("INSERT INTO users VALUES (?)", ("alice",))
            ...     await conn.execute("INSERT INTO users VALUES (?)", ("bob",))
        """
        pool = self._ensure_pool()
        conn = await pool.acquire()
        try:
            await conn.execute("BEGIN")
            yield conn
            await conn.commit()
        except Exception as e:
            try:
                await conn.rollback()
            except Exception:
                # Rollback may fail on closed connection - intentional silent catch
                log.debug("Rollback failed (connection may be closed)", exc_info=True)
            raise TransactionError(f"Transaction failed: {e}") from e
        finally:
            await pool.release(conn)

    async def execute(
        self,
        sql: str,
        parameters: Sequence[Any] | None = None,
    ) -> aiosqlite.Cursor:
        """Execute a single SQL statement.

        Args:
            sql: SQL statement to execute.
            parameters: Query parameters.

        Returns:
            Cursor with results.

        Examples:
            >>> await db.execute("CREATE TABLE test (id INTEGER)")  # doctest: +SKIP
        """
        pool = self._ensure_pool()
        async with pool.connection() as conn:
            if parameters:
                return await conn.execute(sql, parameters)
            return await conn.execute(sql)

    async def executemany(
        self,
        sql: str,
        parameters: Sequence[Sequence[Any]],
    ) -> aiosqlite.Cursor:
        """Execute SQL statement for multiple parameter sets.

        Args:
            sql: SQL statement to execute.
            parameters: Sequence of parameter tuples.

        Returns:
            Cursor with results.

        Examples:
            >>> await db.executemany(  # doctest: +SKIP
            ...     "INSERT INTO test VALUES (?)",
            ...     [(1,), (2,), (3,)]
            ... )
        """
        pool = self._ensure_pool()
        async with pool.connection() as conn:
            return await conn.executemany(sql, parameters)

    async def fetch_one(
        self,
        sql: str,
        parameters: Sequence[Any] | None = None,
    ) -> tuple[Any, ...] | None:
        """Fetch a single row.

        Args:
            sql: SQL query.
            parameters: Query parameters.

        Returns:
            Row tuple or None if no results.

        Examples:
            >>> row = await db.fetch_one("SELECT * FROM test WHERE id=?", (1,))  # doctest: +SKIP
        """
        pool = self._ensure_pool()
        async with pool.connection() as conn:
            if parameters:
                cursor = await conn.execute(sql, parameters)
            else:
                cursor = await conn.execute(sql)
            row = await cursor.fetchone()
            return cast("tuple[Any, ...] | None", row)

    async def fetch_all(
        self,
        sql: str,
        parameters: Sequence[Any] | None = None,
    ) -> list[tuple[Any, ...]]:
        """Fetch all rows.

        Args:
            sql: SQL query.
            parameters: Query parameters.

        Returns:
            List of row tuples.

        Examples:
            >>> rows = await db.fetch_all("SELECT * FROM test")  # doctest: +SKIP
        """
        pool = self._ensure_pool()
        async with pool.connection() as conn:
            if parameters:
                cursor = await conn.execute(sql, parameters)
            else:
                cursor = await conn.execute(sql)
            rows = await cursor.fetchall()
            return cast("list[tuple[Any, ...]]", rows)

    async def fetch_value(
        self,
        sql: str,
        parameters: Sequence[Any] | None = None,
    ) -> Any:
        """Fetch a single value (first column of first row).

        Args:
            sql: SQL query.
            parameters: Query parameters.

        Returns:
            Single value or None.

        Examples:
            >>> count = await db.fetch_value("SELECT count(*) FROM test")  # doctest: +SKIP
        """
        row = await self.fetch_one(sql, parameters)
        return row[0] if row else None

    async def table_exists(self, table_name: str) -> bool:
        """Check if a table exists.

        Args:
            table_name: Name of the table.

        Returns:
            True if table exists.

        Examples:
            >>> await db.table_exists("users")  # doctest: +SKIP
            False
        """
        sql = "SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?"
        count = await self.fetch_value(sql, (table_name,))
        return bool(count)

    @property
    def stats(self) -> PoolStats:
        """Get connection pool statistics."""
        if self._pool:
            return self._pool.stats
        return PoolStats()

    @property
    def is_encrypted(self) -> bool:
        """Whether database is configured for encryption."""
        return self._resolved_key is not None

    @property
    def pool_size(self) -> int:
        """Current number of connections in pool."""
        if self._pool:
            return self._pool.size
        return 0


__all__ = ["AsyncDatabase"]
