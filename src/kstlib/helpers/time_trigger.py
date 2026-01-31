"""Time-based trigger for periodic operations.

This module provides a TimeTrigger class for detecting time boundaries
and scheduling periodic operations based on modulo intervals.

Typical use cases:
- Restart WebSocket connections at market boundaries (4h, 8h candles)
- Execute periodic tasks at fixed intervals aligned to clock time
- Coordinate operations with exchange candlestick closes

Examples:
    Basic boundary detection:

    >>> from kstlib.helpers import TimeTrigger
    >>> trigger = TimeTrigger("4h")
    >>> trigger.time_until_next()  # doctest: +SKIP
    3542.5

    With callback for async operations:

    >>> import asyncio
    >>> async def restart_ws():  # doctest: +SKIP
    ...     print("Restarting WebSocket...")
    >>> trigger = TimeTrigger("8h")
    >>> await trigger.wait_for_boundary()  # doctest: +SKIP
    >>> await restart_ws()  # doctest: +SKIP
"""

from __future__ import annotations

import asyncio
import re
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pendulum
from typing_extensions import Self

from kstlib.helpers.exceptions import InvalidModuloError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

__all__ = ["TimeTrigger", "TimeTriggerStats"]

# Regex for parsing modulo strings like "30m", "4h", "1d"
MODULO_PATTERN = re.compile(r"^(\d+)\s*(s|m|h|d)$", re.IGNORECASE)

# Unit multipliers to seconds
UNIT_SECONDS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
}

# Hard limits for modulo (deep defense)
HARD_MIN_MODULO_SECONDS = 60  # Minimum 1 minute
HARD_MAX_MODULO_SECONDS = 86400 * 7  # Maximum 1 week


def _parse_modulo(modulo: str) -> int:
    """Parse modulo string to seconds.

    Args:
        modulo: Duration string like "30m", "4h", "1d".

    Returns:
        Duration in seconds.

    Raises:
        InvalidModuloError: If format is invalid or out of bounds.
    """
    match = MODULO_PATTERN.match(modulo.strip())
    if not match:
        msg = (
            f"Invalid modulo format: '{modulo}'. "
            "Expected format: <number><unit> where unit is s, m, h, or d. "
            "Examples: '30m', '4h', '1d'"
        )
        raise InvalidModuloError(msg)

    value = int(match.group(1))
    unit = match.group(2).lower()
    seconds = value * UNIT_SECONDS[unit]

    if seconds < HARD_MIN_MODULO_SECONDS:
        msg = f"Modulo too small: {seconds}s < {HARD_MIN_MODULO_SECONDS}s minimum"
        raise InvalidModuloError(msg)

    if seconds > HARD_MAX_MODULO_SECONDS:
        msg = f"Modulo too large: {seconds}s > {HARD_MAX_MODULO_SECONDS}s maximum"
        raise InvalidModuloError(msg)

    return seconds


@dataclass
class TimeTriggerStats:
    """Statistics for TimeTrigger operations.

    Attributes:
        triggers_fired: Number of times boundary was triggered.
        callbacks_invoked: Number of callback invocations.
        last_trigger_at: ISO timestamp of last trigger.
    """

    triggers_fired: int = 0
    callbacks_invoked: int = 0
    last_trigger_at: str | None = None

    def record_trigger(self) -> None:
        """Record a trigger event."""
        self.triggers_fired += 1
        self.last_trigger_at = pendulum.now("UTC").to_iso8601_string()

    def record_callback(self) -> None:
        """Record a callback invocation."""
        self.callbacks_invoked += 1


class TimeTrigger:
    """Time-based trigger for detecting modulo boundaries.

    Detects when current time aligns with periodic intervals (boundaries).
    Useful for coordinating operations with market candle closes or
    scheduling periodic restarts.

    Attributes:
        modulo: Original modulo string (e.g., "4h").
        modulo_seconds: Modulo duration in seconds.
        stats: Trigger statistics.

    Args:
        modulo: Duration string for the interval (e.g., "30m", "4h", "8h", "1d").
        timezone: Timezone for calculations (default: UTC).

    Raises:
        InvalidModuloError: If modulo format is invalid or out of bounds.

    Examples:
        Create a 4-hour trigger:

        >>> trigger = TimeTrigger("4h")
        >>> trigger.modulo_seconds
        14400

        Check boundary status:

        >>> trigger.is_at_boundary()  # doctest: +SKIP
        False
        >>> trigger.time_until_next()  # doctest: +SKIP
        1234.5

        Create with different timezone:

        >>> trigger = TimeTrigger("1d", timezone="Europe/Paris")
        >>> trigger.timezone
        'Europe/Paris'
    """

    def __init__(
        self,
        modulo: str,
        *,
        timezone: str = "UTC",
    ) -> None:
        """Initialize TimeTrigger.

        Args:
            modulo: Duration string (e.g., "30m", "4h", "1d").
            timezone: Timezone for boundary calculations.
        """
        self._modulo_str = modulo
        self._modulo_seconds = _parse_modulo(modulo)
        self._timezone = timezone
        self._stats = TimeTriggerStats()

        # Async loop state
        self._running = False
        self._stop_event = threading.Event()
        self._async_task: asyncio.Task[None] | None = None

    @property
    def modulo(self) -> str:
        """Return the original modulo string."""
        return self._modulo_str

    @property
    def modulo_seconds(self) -> int:
        """Return the modulo duration in seconds."""
        return self._modulo_seconds

    @property
    def timezone(self) -> str:
        """Return the timezone used for calculations."""
        return self._timezone

    @property
    def stats(self) -> TimeTriggerStats:
        """Return trigger statistics."""
        return self._stats

    def _get_current_timestamp(self) -> float:
        """Get current Unix timestamp."""
        return pendulum.now(self._timezone).timestamp()

    def _seconds_into_period(self) -> float:
        """Get seconds elapsed since last boundary."""
        return self._get_current_timestamp() % self._modulo_seconds

    def time_until_next(self) -> float:
        """Calculate seconds until next boundary.

        Returns:
            Seconds remaining until the next modulo boundary.

        Examples:
            >>> trigger = TimeTrigger("4h")
            >>> remaining = trigger.time_until_next()  # doctest: +SKIP
            >>> 0 <= remaining <= 14400  # doctest: +SKIP
            True
        """
        elapsed = self._seconds_into_period()
        if elapsed == 0:
            return 0.0
        return self._modulo_seconds - elapsed

    def is_at_boundary(self, margin: float = 1.0) -> bool:
        """Check if current time is at a boundary.

        A boundary is when the timestamp is divisible by the modulo.
        The margin allows for slight timing imprecision.

        Args:
            margin: Tolerance in seconds around the boundary (default: 1.0).

        Returns:
            True if within margin seconds of a boundary.

        Examples:
            >>> trigger = TimeTrigger("4h")
            >>> trigger.is_at_boundary()  # doctest: +SKIP
            True  # If time is 00:00:00, 04:00:00, etc.
            >>> trigger.is_at_boundary(margin=5.0)  # doctest: +SKIP
            True  # If time is within 5 seconds of boundary
        """
        elapsed = self._seconds_into_period()
        # Check if we're near 0 (just passed) or near modulo (about to hit)
        return elapsed <= margin or (self._modulo_seconds - elapsed) <= margin

    def should_trigger(self, margin: float = 30.0) -> bool:
        """Check if trigger should fire (boundary approaching).

        Use this to prepare for an upcoming boundary (e.g., start shutdown
        sequence before the boundary hits).

        Args:
            margin: Seconds before boundary to trigger (default: 30.0).

        Returns:
            True if boundary is within margin seconds.

        Examples:
            >>> trigger = TimeTrigger("4h")
            >>> if trigger.should_trigger(margin=60):  # doctest: +SKIP
            ...     print("Boundary in less than 60 seconds!")
        """
        remaining = self.time_until_next()
        return remaining <= margin

    def next_boundary(self) -> pendulum.DateTime:
        """Get the datetime of the next boundary.

        Returns:
            Pendulum DateTime of the next boundary.

        Examples:
            >>> trigger = TimeTrigger("4h")
            >>> next_time = trigger.next_boundary()  # doctest: +SKIP
            >>> print(next_time.to_iso8601_string())  # doctest: +SKIP
            '2024-01-15T08:00:00+00:00'
        """
        now = pendulum.now(self._timezone)
        seconds_until = self.time_until_next()
        return now.add(seconds=seconds_until)

    def previous_boundary(self) -> pendulum.DateTime:
        """Get the datetime of the previous boundary.

        Returns:
            Pendulum DateTime of the previous boundary.

        Examples:
            >>> trigger = TimeTrigger("4h")
            >>> prev_time = trigger.previous_boundary()  # doctest: +SKIP
            >>> print(prev_time.to_iso8601_string())  # doctest: +SKIP
            '2024-01-15T04:00:00+00:00'
        """
        now = pendulum.now(self._timezone)
        elapsed = self._seconds_into_period()
        return now.subtract(seconds=elapsed)

    async def wait_for_boundary(self, margin: float = 0.0) -> None:
        """Wait until the next boundary (async).

        Sleeps until the next boundary minus the margin.

        Args:
            margin: Seconds before boundary to wake up (default: 0.0).

        Examples:
            >>> import asyncio
            >>> trigger = TimeTrigger("30m")
            >>> await trigger.wait_for_boundary()  # doctest: +SKIP
            >>> print("Boundary reached!")  # doctest: +SKIP
        """
        remaining = self.time_until_next() - margin
        if remaining > 0:
            await asyncio.sleep(remaining)
        self._stats.record_trigger()

    async def run_on_boundary(
        self,
        callback: Callable[[], None] | Callable[[], Awaitable[None]],
        *,
        margin: float = 0.0,
        run_immediately: bool = False,
    ) -> None:
        """Run callback at each boundary (async loop).

        Continuously waits for boundaries and invokes the callback.
        Call stop() to terminate the loop.

        Args:
            callback: Function to call at each boundary (sync or async).
            margin: Seconds before boundary to invoke callback.
            run_immediately: If True, run callback immediately before first wait.

        Examples:
            >>> import asyncio
            >>> async def restart():  # doctest: +SKIP
            ...     print("Restarting...")
            >>> trigger = TimeTrigger("4h")
            >>> task = asyncio.create_task(  # doctest: +SKIP
            ...     trigger.run_on_boundary(restart, margin=30)
            ... )
            >>> # Later: trigger.stop()
        """
        self._running = True
        self._stop_event.clear()

        if run_immediately:
            await self._invoke_callback(callback)

        while self._running:
            await self.wait_for_boundary(margin=margin)
            # Re-check after await since stop() may have been called concurrently
            if self._stop_event.is_set():
                break
            await self._invoke_callback(callback)

    async def _invoke_callback(
        self,
        callback: Callable[[], None] | Callable[[], Awaitable[None]],
    ) -> None:
        """Invoke callback (sync or async)."""
        self._stats.record_callback()
        result = callback()
        if asyncio.iscoroutine(result):
            await result

    def stop(self) -> None:
        """Stop the boundary loop."""
        self._running = False
        self._stop_event.set()
        if self._async_task is not None and not self._async_task.done():
            self._async_task.cancel()

    def __repr__(self) -> str:
        """Return string representation."""
        return f"TimeTrigger(modulo={self._modulo_str!r}, timezone={self._timezone!r})"

    async def __aenter__(self) -> Self:
        """Async context manager entry."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Async context manager exit."""
        self.stop()
