"""Circuit breaker pattern for fault tolerance."""

from __future__ import annotations

import functools
import inspect
import threading
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, TypeVar, overload

from typing_extensions import ParamSpec

from kstlib.limits import (
    HARD_MAX_CIRCUIT_FAILURES,
    HARD_MAX_CIRCUIT_RESET_TIMEOUT,
    HARD_MAX_HALF_OPEN_CALLS,
    HARD_MIN_CIRCUIT_FAILURES,
    HARD_MIN_CIRCUIT_RESET_TIMEOUT,
    HARD_MIN_HALF_OPEN_CALLS,
    clamp_with_limits,
    get_resilience_limits,
)
from kstlib.resilience.exceptions import CircuitOpenError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

P = ParamSpec("P")
R = TypeVar("R")


class CircuitState(Enum):
    """State of the circuit breaker.

    States:
        CLOSED: Normal operation, requests pass through.
        OPEN: Circuit tripped, requests fail immediately.
        HALF_OPEN: Testing if service recovered.
    """

    CLOSED = auto()
    OPEN = auto()
    HALF_OPEN = auto()


@dataclass
class CircuitStats:
    """Statistics for circuit breaker monitoring.

    Attributes:
        total_calls: Total number of calls attempted.
        successful_calls: Number of successful calls.
        failed_calls: Number of failed calls.
        rejected_calls: Number of calls rejected due to open circuit.
        state_changes: Number of state transitions.

    Examples:
        >>> stats = CircuitStats()
        >>> stats.record_success()
        >>> stats.record_failure()
        >>> stats.record_rejection()
        >>> (stats.successful_calls, stats.failed_calls, stats.rejected_calls)
        (1, 1, 1)
        >>> stats.total_calls
        3
    """

    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0
    state_changes: int = 0

    def record_success(self) -> None:
        """Record a successful call."""
        self.total_calls += 1
        self.successful_calls += 1

    def record_failure(self) -> None:
        """Record a failed call."""
        self.total_calls += 1
        self.failed_calls += 1

    def record_rejection(self) -> None:
        """Record a rejected call (circuit open)."""
        self.total_calls += 1
        self.rejected_calls += 1

    def record_state_change(self) -> None:
        """Record a state transition."""
        self.state_changes += 1


class CircuitBreaker:
    """Circuit breaker for protecting against cascading failures.

    Implements the circuit breaker pattern to prevent repeated calls
    to a failing service and allow recovery time.

    Args:
        max_failures: Failures before opening circuit (default from config).
        reset_timeout: Seconds before attempting recovery (default from config).
        half_open_max_calls: Calls allowed in half-open state (default from config).
        excluded_exceptions: Exceptions that don't count as failures.
        name: Optional name for the circuit breaker.

    Examples:
        As a decorator:

        >>> @circuit_breaker
        ... def call_api():  # doctest: +SKIP
        ...     return requests.get("http://api.example.com")

        With custom settings:

        >>> @circuit_breaker(max_failures=3, reset_timeout=30)
        ... def risky_call():  # doctest: +SKIP
        ...     pass

        Direct instantiation:

        >>> cb = CircuitBreaker(max_failures=5)
        >>> cb.state
        <CircuitState.CLOSED: 1>
    """

    def __init__(
        self,
        *,
        max_failures: int | None = None,
        reset_timeout: float | None = None,
        half_open_max_calls: int | None = None,
        excluded_exceptions: tuple[type[Exception], ...] = (),
        name: str | None = None,
    ) -> None:
        """Initialize circuit breaker.

        Args:
            max_failures: Failures before opening circuit. Uses config if None.
            reset_timeout: Seconds before attempting recovery. Uses config if None.
            half_open_max_calls: Calls allowed in half-open state. Uses config if None.
            excluded_exceptions: Exceptions that don't count as failures.
            name: Optional name for the circuit breaker.
        """
        limits = get_resilience_limits()

        # Max failures (use config default or clamp provided value)
        self._max_failures = (
            limits.circuit_max_failures
            if max_failures is None
            else int(clamp_with_limits(max_failures, HARD_MIN_CIRCUIT_FAILURES, HARD_MAX_CIRCUIT_FAILURES))
        )

        # Reset timeout (use config default or clamp provided value)
        self._reset_timeout = (
            limits.circuit_reset_timeout
            if reset_timeout is None
            else clamp_with_limits(reset_timeout, HARD_MIN_CIRCUIT_RESET_TIMEOUT, HARD_MAX_CIRCUIT_RESET_TIMEOUT)
        )

        # Half-open max calls (use config default or clamp provided value)
        self._half_open_max_calls = (
            limits.circuit_half_open_calls
            if half_open_max_calls is None
            else int(clamp_with_limits(half_open_max_calls, HARD_MIN_HALF_OPEN_CALLS, HARD_MAX_HALF_OPEN_CALLS))
        )

        self._excluded_exceptions = excluded_exceptions
        self._name = name

        # State
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float | None = None
        self._half_open_calls = 0

        # Thread safety
        self._lock = threading.Lock()

        # Statistics
        self._stats = CircuitStats()

    @property
    def state(self) -> CircuitState:
        """Return the current circuit state."""
        with self._lock:
            self._check_state_transition()
            return self._state

    @property
    def name(self) -> str | None:
        """Return the circuit breaker name."""
        return self._name

    @property
    def stats(self) -> CircuitStats:
        """Return circuit breaker statistics."""
        return self._stats

    @property
    def failure_count(self) -> int:
        """Return current failure count."""
        return self._failure_count

    def _check_state_transition(self) -> None:
        """Check and perform state transition if needed."""
        if self._state == CircuitState.OPEN and self._last_failure_time is not None:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self._reset_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                self._stats.record_state_change()

    def _record_success(self) -> None:
        """Record a successful call and update state."""
        with self._lock:
            self._stats.record_success()
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_calls += 1
                if self._half_open_calls >= self._half_open_max_calls:
                    # Recovery successful, close circuit
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._last_failure_time = None
                    self._stats.record_state_change()
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                self._failure_count = 0

    def _record_failure(self, exc: Exception) -> None:
        """Record a failed call and update state."""
        # Check if exception is excluded
        if isinstance(exc, self._excluded_exceptions):
            return

        with self._lock:
            self._stats.record_failure()
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                # Failed during recovery, reopen circuit
                self._state = CircuitState.OPEN
                self._stats.record_state_change()
            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self._max_failures:
                    self._state = CircuitState.OPEN
                    self._stats.record_state_change()

    def _check_open(self) -> None:
        """Check if circuit is open and raise if so."""
        with self._lock:
            self._check_state_transition()
            if self._state == CircuitState.OPEN:
                remaining = 0.0
                if self._last_failure_time is not None:
                    elapsed = time.monotonic() - self._last_failure_time
                    remaining = max(0.0, self._reset_timeout - elapsed)
                self._stats.record_rejection()
                raise CircuitOpenError(
                    f"Circuit breaker '{self._name or 'unnamed'}' is open",
                    remaining_seconds=remaining,
                )

    def call(self, func: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
        """Execute a function through the circuit breaker.

        Args:
            func: Function to execute.
            *args: Positional arguments for the function.
            **kwargs: Keyword arguments for the function.

        Returns:
            Function result.

        Raises:
            CircuitOpenError: If circuit is open.

        Examples:
            >>> cb = CircuitBreaker()
            >>> result = cb.call(lambda x: x * 2, 5)
            >>> result
            10
        """
        self._check_open()
        try:
            result = func(*args, **kwargs)
            self._record_success()
            return result
        except Exception as exc:
            self._record_failure(exc)
            raise

    async def acall(
        self,
        func: Callable[P, Awaitable[R]],
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> R:
        """Execute an async function through the circuit breaker.

        Args:
            func: Async function to execute.
            *args: Positional arguments for the function.
            **kwargs: Keyword arguments for the function.

        Returns:
            Function result.

        Raises:
            CircuitOpenError: If circuit is open.

        Examples:
            >>> import asyncio
            >>> cb = CircuitBreaker()
            >>> async def double(x): return x * 2
            >>> asyncio.run(cb.acall(double, 5))
            10
        """
        self._check_open()
        try:
            result = await func(*args, **kwargs)
            self._record_success()
            return result
        except Exception as exc:
            self._record_failure(exc)
            raise

    def reset(self) -> None:
        """Manually reset the circuit breaker to closed state.

        Examples:
            >>> cb = CircuitBreaker(max_failures=1)
            >>> try:
            ...     cb.call(lambda: 1/0)
            ... except ZeroDivisionError:
            ...     pass
            >>> cb.state.name
            'OPEN'
            >>> cb.reset()
            >>> cb.state.name
            'CLOSED'
        """
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._last_failure_time = None
            self._half_open_calls = 0

    def __call__(self, func: Callable[P, R]) -> Callable[P, R] | Callable[P, Awaitable[R]]:
        """Use circuit breaker as a decorator.

        Args:
            func: Function to wrap.

        Returns:
            Wrapped function with circuit breaker protection.
        """
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                return await self.acall(func, *args, **kwargs)

            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            return self.call(func, *args, **kwargs)

        return sync_wrapper


# Decorator factory
@overload
def circuit_breaker(func: Callable[P, R]) -> Callable[P, R]: ...


@overload
def circuit_breaker(
    *,
    max_failures: int | None = None,
    reset_timeout: float | None = None,
    half_open_max_calls: int | None = None,
    excluded_exceptions: tuple[type[Exception], ...] = (),
    name: str | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]: ...


def circuit_breaker(
    func: Callable[P, R] | None = None,
    *,
    max_failures: int | None = None,
    reset_timeout: float | None = None,
    half_open_max_calls: int | None = None,
    excluded_exceptions: tuple[type[Exception], ...] = (),
    name: str | None = None,
) -> Callable[P, R] | Callable[[Callable[P, R]], Callable[P, R]]:
    """Circuit breaker decorator for functions.

    Can be used with or without arguments:

    Examples:
        Without arguments (uses config defaults):

        >>> @circuit_breaker
        ... def api_call():  # doctest: +SKIP
        ...     pass

        With arguments:

        >>> @circuit_breaker(max_failures=3, reset_timeout=30)
        ... def api_call():  # doctest: +SKIP
        ...     pass

        Exclude specific exceptions:

        >>> @circuit_breaker(excluded_exceptions=(ValueError,))
        ... def validate():  # doctest: +SKIP
        ...     pass
    """
    cb = CircuitBreaker(
        max_failures=max_failures,
        reset_timeout=reset_timeout,
        half_open_max_calls=half_open_max_calls,
        excluded_exceptions=excluded_exceptions,
        name=name,
    )

    if func is not None:
        # @circuit_breaker without parentheses
        return cb(func)  # type: ignore[return-value]

    # @circuit_breaker(...) with arguments
    return cb  # type: ignore[return-value]


__all__ = ["CircuitBreaker", "CircuitState", "CircuitStats", "circuit_breaker"]
