"""Resilience utilities for fault-tolerant applications.

This module provides core components for building resilient systems:

- **Heartbeat**: Periodic liveness signaling via state files
- **GracefulShutdown**: Orderly shutdown with prioritized callbacks
- **CircuitBreaker**: Protect against cascading failures
- **RateLimiter**: Token bucket rate limiting for request throttling
- **Watchdog**: Detect thread/process freezes and hangs

Examples:
    Heartbeat for process monitoring:

    >>> from kstlib.resilience import Heartbeat
    >>> with Heartbeat("/tmp/app.heartbeat") as hb:  # doctest: +SKIP
    ...     run_application()
    >>> Heartbeat.is_alive("/tmp/app.heartbeat")  # doctest: +SKIP
    True

    Graceful shutdown with cleanup:

    >>> from kstlib.resilience import GracefulShutdown
    >>> with GracefulShutdown() as shutdown:  # doctest: +SKIP
    ...     shutdown.register("db", close_database, priority=10)
    ...     shutdown.register("cache", flush_cache, priority=20)
    ...     run_application()

    Circuit breaker for external calls:

    >>> from kstlib.resilience import circuit_breaker
    >>> @circuit_breaker(max_failures=3, reset_timeout=30)
    ... def call_external_api():  # doctest: +SKIP
    ...     return requests.get("http://api.example.com")

    Rate limiting API calls:

    >>> from kstlib.resilience import rate_limiter, RateLimiter
    >>> @rate_limiter(rate=10, per=1.0)  # 10 requests per second
    ... def call_api():  # doctest: +SKIP
    ...     return requests.get("http://api.example.com")

    >>> limiter = RateLimiter(rate=100, per=60.0)  # 100 per minute
    >>> limiter.acquire()  # doctest: +SKIP
    True

    Watchdog for freeze detection:

    >>> from kstlib.resilience import Watchdog
    >>> def on_freeze():  # doctest: +SKIP
    ...     print("Thread frozen!")
    >>> with Watchdog(timeout=30, on_timeout=on_freeze) as wd:  # doctest: +SKIP
    ...     while running:
    ...         wd.ping()
    ...         do_work()
"""

from kstlib.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    CircuitStats,
    circuit_breaker,
)
from kstlib.resilience.exceptions import (
    CircuitBreakerError,
    CircuitOpenError,
    HeartbeatError,
    RateLimitError,
    RateLimitExceededError,
    ShutdownError,
    WatchdogError,
    WatchdogTimeoutError,
)
from kstlib.resilience.heartbeat import Heartbeat, HeartbeatState
from kstlib.resilience.rate_limiter import RateLimiter, RateLimiterStats, rate_limiter
from kstlib.resilience.shutdown import CleanupCallback, GracefulShutdown
from kstlib.resilience.watchdog import Watchdog, WatchdogStats, watchdog_context

__all__ = [
    "CircuitBreaker",
    "CircuitBreakerError",
    "CircuitOpenError",
    "CircuitState",
    "CircuitStats",
    "CleanupCallback",
    "GracefulShutdown",
    "Heartbeat",
    "HeartbeatError",
    "HeartbeatState",
    "RateLimitError",
    "RateLimitExceededError",
    "RateLimiter",
    "RateLimiterStats",
    "ShutdownError",
    "Watchdog",
    "WatchdogError",
    "WatchdogStats",
    "WatchdogTimeoutError",
    "circuit_breaker",
    "rate_limiter",
    "watchdog_context",
]
