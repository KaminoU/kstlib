"""Rate limiter using the Token Bucket algorithm.

Provides configurable rate limiting for protecting against request floods
and respecting external API rate limits.

Examples:
    As a decorator:

    >>> @rate_limiter(rate=10, per=1.0)  # 10 requests per second
    ... def call_api():  # doctest: +SKIP
    ...     return requests.get("http://api.example.com")

    Direct usage:

    >>> limiter = RateLimiter(rate=5, per=1.0)
    >>> limiter.acquire()  # Blocks until token available
    True
    >>> limiter.try_acquire()  # Non-blocking, returns immediately
    True

    As context manager:

    >>> with RateLimiter(rate=100, per=60.0):  # doctest: +SKIP
    ...     call_api()
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar, overload

from typing_extensions import ParamSpec, Self

from kstlib.resilience.exceptions import RateLimitExceededError

if TYPE_CHECKING:
    from collections.abc import Callable

P = ParamSpec("P")
R = TypeVar("R")


@dataclass
class RateLimiterStats:
    """Statistics for rate limiter monitoring.

    Attributes:
        total_acquired: Total number of tokens successfully acquired.
        total_rejected: Total number of acquire attempts that were rejected.
        total_waited: Total time spent waiting for tokens (seconds).

    Examples:
        >>> stats = RateLimiterStats()
        >>> stats.record_acquired()
        >>> stats.record_rejected()
        >>> stats.record_wait(0.5)
        >>> (stats.total_acquired, stats.total_rejected)
        (1, 1)
        >>> stats.total_waited
        0.5
    """

    total_acquired: int = 0
    total_rejected: int = 0
    total_waited: float = 0.0

    def record_acquired(self) -> None:
        """Record a successful token acquisition."""
        self.total_acquired += 1

    def record_rejected(self) -> None:
        """Record a rejected acquisition attempt."""
        self.total_rejected += 1

    def record_wait(self, seconds: float) -> None:
        """Record time spent waiting for a token."""
        self.total_waited += seconds


class RateLimiter:
    """Token bucket rate limiter for controlling request throughput.

    Implements the token bucket algorithm where tokens are added at a fixed
    rate and each request consumes one token. Allows bursts up to the
    bucket capacity.

    Args:
        rate: Maximum number of tokens (requests) allowed per period.
        per: Time period in seconds (default 1.0 = per second).
        burst: Initial tokens available. If None, starts full (burst = rate).
        name: Optional name for logging and monitoring.

    Examples:
        Basic usage - 10 requests per second:

        >>> limiter = RateLimiter(rate=10, per=1.0)
        >>> int(limiter.tokens)  # Starts full
        10

        With custom burst capacity:

        >>> limiter = RateLimiter(rate=10, per=1.0, burst=5)
        >>> int(limiter.tokens)  # Starts with 5 tokens
        5

        Rate limiting API calls:

        >>> limiter = RateLimiter(rate=100, per=60.0)  # 100 per minute
        >>> for _ in range(5):
        ...     if limiter.try_acquire():
        ...         pass  # call_api()
        >>> limiter.stats.total_acquired
        5
    """

    def __init__(
        self,
        rate: float,
        per: float = 1.0,
        *,
        burst: float | None = None,
        name: str | None = None,
    ) -> None:
        """Initialize rate limiter.

        Args:
            rate: Maximum tokens (requests) per period.
            per: Period duration in seconds.
            burst: Initial token count. Defaults to rate (full bucket).
            name: Optional name for identification.

        Raises:
            ValueError: If rate or per is not positive.
        """
        if rate <= 0:
            raise ValueError("rate must be positive")
        if per <= 0:
            raise ValueError("per must be positive")

        self._rate = float(rate)
        self._per = float(per)
        self._tokens = float(burst) if burst is not None else self._rate
        self._max_tokens = self._rate
        self._refill_rate = self._rate / self._per  # tokens per second
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()
        self._name = name
        self._stats = RateLimiterStats()

    @property
    def rate(self) -> float:
        """Maximum tokens per period."""
        return self._rate

    @property
    def per(self) -> float:
        """Period duration in seconds."""
        return self._per

    @property
    def tokens(self) -> float:
        """Current available tokens (after refill)."""
        with self._lock:
            self._refill()
            return self._tokens

    @property
    def stats(self) -> RateLimiterStats:
        """Statistics for this rate limiter."""
        return self._stats

    @property
    def name(self) -> str | None:
        """Name of this rate limiter."""
        return self._name

    def _refill(self) -> None:
        """Refill tokens based on elapsed time. Must hold lock."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._max_tokens, self._tokens + elapsed * self._refill_rate)
        self._last_refill = now

    def _time_until_token(self) -> float:
        """Calculate time until at least 1 token is available. Must hold lock."""
        if self._tokens >= 1.0:
            return 0.0
        needed = 1.0 - self._tokens
        return needed / self._refill_rate

    def time_until_token(self) -> float:
        """Calculate time until at least 1 token will be available.

        Returns:
            Seconds until a token is available. Returns 0.0 if token available now.

        Examples:
            >>> limiter = RateLimiter(rate=10, per=1.0)
            >>> limiter.time_until_token()  # Tokens available
            0.0
        """
        with self._lock:
            self._refill()
            return self._time_until_token()

    def acquire(self, *, blocking: bool = True, timeout: float | None = None) -> bool:
        """Acquire a token from the bucket.

        Args:
            blocking: If True, wait until a token is available.
            timeout: Maximum time to wait in seconds (None = wait forever).

        Returns:
            True if token was acquired, False if non-blocking and no token.

        Raises:
            RateLimitExceededError: If timeout exceeded while waiting.

        Examples:
            >>> limiter = RateLimiter(rate=10, per=1.0)
            >>> limiter.acquire()  # Blocks if needed
            True
            >>> limiter.acquire(blocking=False)  # Returns immediately
            True
        """
        start_time = time.monotonic()
        deadline = start_time + timeout if timeout is not None else None

        while True:
            with self._lock:
                self._refill()

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    wait_time = time.monotonic() - start_time
                    if wait_time > 0.001:  # Only record significant waits
                        self._stats.record_wait(wait_time)
                    self._stats.record_acquired()
                    return True

                if not blocking:
                    self._stats.record_rejected()
                    return False

                # Calculate wait time
                wait_time = self._time_until_token()

                # Check timeout
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self._stats.record_rejected()
                        raise RateLimitExceededError(
                            f"Rate limit timeout after {timeout}s",
                            retry_after=wait_time,
                        )
                    wait_time = min(wait_time, remaining)

            # Wait outside the lock
            time.sleep(min(wait_time, 0.1))  # Cap sleep to allow interruption

    def try_acquire(self) -> bool:
        """Try to acquire a token without blocking.

        Returns:
            True if token was acquired, False otherwise.

        Examples:
            >>> limiter = RateLimiter(rate=2, per=1.0)
            >>> limiter.try_acquire()
            True
            >>> limiter.try_acquire()
            True
            >>> limiter.try_acquire()  # No tokens left
            False
        """
        return self.acquire(blocking=False)

    async def acquire_async(self, *, timeout: float | None = None) -> bool:
        """Acquire a token asynchronously.

        Args:
            timeout: Maximum time to wait in seconds.

        Returns:
            True when token is acquired.

        Raises:
            RateLimitExceededError: If timeout exceeded.

        Examples:
            >>> import asyncio
            >>> limiter = RateLimiter(rate=10, per=1.0)
            >>> asyncio.run(limiter.acquire_async())
            True
        """
        start_time = time.monotonic()
        deadline = start_time + timeout if timeout is not None else None

        while True:
            with self._lock:
                self._refill()

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    wait_time = time.monotonic() - start_time
                    if wait_time > 0.001:
                        self._stats.record_wait(wait_time)
                    self._stats.record_acquired()
                    return True

                wait_time = self._time_until_token()

                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self._stats.record_rejected()
                        raise RateLimitExceededError(
                            f"Rate limit timeout after {timeout}s",
                            retry_after=wait_time,
                        )
                    wait_time = min(wait_time, remaining)

            # Async sleep outside the lock
            await asyncio.sleep(min(wait_time, 0.1))

    def reset(self) -> None:
        """Reset the rate limiter to full capacity.

        Examples:
            >>> limiter = RateLimiter(rate=5, per=1.0)
            >>> for _ in range(5):
            ...     limiter.try_acquire()
            True
            True
            True
            True
            True
            >>> limiter.try_acquire()
            False
            >>> limiter.reset()
            >>> limiter.try_acquire()
            True
        """
        with self._lock:
            self._tokens = self._max_tokens
            self._last_refill = time.monotonic()

    def __enter__(self) -> Self:
        """Enter context manager, acquiring a token."""
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Exit context manager."""
        pass

    async def __aenter__(self) -> Self:
        """Enter async context manager, acquiring a token."""
        await self.acquire_async()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Exit async context manager."""
        pass

    def __repr__(self) -> str:
        """Return string representation."""
        name_part = f", name={self._name!r}" if self._name else ""
        return f"RateLimiter(rate={self._rate}, per={self._per}{name_part})"


# Type overloads for the decorator
@overload
def rate_limiter(fn: Callable[P, R]) -> Callable[P, R]: ...


@overload
def rate_limiter(
    fn: None = None,
    *,
    rate: float = 10.0,
    per: float = 1.0,
    burst: float | None = None,
    blocking: bool = True,
    timeout: float | None = None,
    name: str | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]: ...


def rate_limiter(
    fn: Callable[P, R] | None = None,
    *,
    rate: float = 10.0,
    per: float = 1.0,
    burst: float | None = None,
    blocking: bool = True,
    timeout: float | None = None,
    name: str | None = None,
) -> Callable[P, R] | Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator to rate limit function calls.

    Can be used with or without arguments:

    - ``@rate_limiter`` - Uses defaults (10 requests/second)
    - ``@rate_limiter(rate=5, per=1.0)`` - 5 requests per second

    Args:
        fn: Function to decorate (when used without parentheses).
        rate: Maximum calls per period (default 10).
        per: Period in seconds (default 1.0).
        burst: Initial capacity (default = rate).
        blocking: If True, wait for token. If False, raise on limit.
        timeout: Maximum wait time in seconds.
        name: Name for the rate limiter.

    Returns:
        Decorated function that respects rate limits.

    Raises:
        RateLimitExceededError: If blocking=False and rate limit exceeded.

    Examples:
        Default rate limiting (10/sec):

        >>> @rate_limiter
        ... def call_api():  # doctest: +SKIP
        ...     pass

        Custom rate:

        >>> @rate_limiter(rate=100, per=60.0)  # 100 per minute
        ... def call_api():  # doctest: +SKIP
        ...     pass

        Non-blocking mode:

        >>> @rate_limiter(rate=5, blocking=False)
        ... def fast_api():  # doctest: +SKIP
        ...     pass  # Raises RateLimitExceededError if limit hit
    """
    # Create the limiter instance (shared across all calls)
    limiter = RateLimiter(rate=rate, per=per, burst=burst, name=name)

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        # Check if function is async
        is_async = inspect.iscoroutinefunction(fn)

        if is_async:

            @functools.wraps(fn)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                if blocking:
                    await limiter.acquire_async(timeout=timeout)
                elif not limiter.try_acquire():
                    raise RateLimitExceededError(
                        f"Rate limit exceeded for {fn.__name__}",
                        retry_after=limiter.time_until_token(),
                    )
                return await fn(*args, **kwargs)  # type: ignore[no-any-return, misc]

            # Attach limiter for inspection
            async_wrapper._rate_limiter = limiter  # type: ignore[attr-defined]
            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            if blocking:
                limiter.acquire(timeout=timeout)
            elif not limiter.try_acquire():
                raise RateLimitExceededError(
                    f"Rate limit exceeded for {fn.__name__}",
                    retry_after=limiter.time_until_token(),
                )
            return fn(*args, **kwargs)

        # Attach limiter for inspection
        sync_wrapper._rate_limiter = limiter  # type: ignore[attr-defined]
        return sync_wrapper

    # Handle @rate_limiter vs @rate_limiter()
    if fn is not None:
        return decorator(fn)
    return decorator


__all__ = [
    "RateLimiter",
    "RateLimiterStats",
    "rate_limiter",
]
