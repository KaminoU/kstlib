"""Watchdog for detecting thread/process freezes and hangs.

Provides configurable timeout monitoring for long-running operations,
with automatic callback invocation when activity stops.

Examples:
    Basic usage with callback:

    >>> def on_freeze():  # doctest: +SKIP
    ...     print("Thread frozen!")
    >>> watchdog = Watchdog(timeout=30, on_timeout=on_freeze)  # doctest: +SKIP
    >>> watchdog.start()  # doctest: +SKIP
    >>> while running:  # doctest: +SKIP
    ...     watchdog.ping()  # Reset timer
    ...     do_work()
    >>> watchdog.stop()  # doctest: +SKIP

    As context manager:

    >>> with Watchdog(timeout=30) as wd:  # doctest: +SKIP
    ...     for item in items:
    ...         wd.ping()
    ...         process(item)
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from typing_extensions import Self

from kstlib.limits import (
    DEFAULT_WATCHDOG_TIMEOUT,
    HARD_MAX_WATCHDOG_TIMEOUT,
    HARD_MIN_WATCHDOG_TIMEOUT,
    clamp_with_limits,
    get_resilience_limits,
)
from kstlib.resilience.exceptions import WatchdogTimeoutError

log = logging.getLogger(__name__)

# Type alias for alert callback
OnAlertCallback = Callable[[str, str, Mapping[str, Any]], Awaitable[None] | None]


@dataclass
class WatchdogStats:
    """Statistics for watchdog monitoring.

    Attributes:
        pings_total: Total number of ping calls.
        timeouts_triggered: Number of timeout events detected.
        last_ping_time: Timestamp of last activity (monotonic).
        start_time: Timestamp when watchdog started (monotonic).

    Examples:
        >>> stats = WatchdogStats()
        >>> stats.record_ping()
        >>> stats.pings_total
        1
    """

    pings_total: int = 0
    timeouts_triggered: int = 0
    last_ping_time: float | None = None
    start_time: float | None = None

    def record_ping(self) -> None:
        """Record a ping event."""
        self.pings_total += 1
        self.last_ping_time = time.monotonic()

    def record_timeout(self) -> None:
        """Record a timeout event."""
        self.timeouts_triggered += 1

    def record_start(self) -> None:
        """Record watchdog start."""
        self.start_time = time.monotonic()
        self.last_ping_time = time.monotonic()

    @property
    def uptime(self) -> float:
        """Return seconds since watchdog started."""
        if self.start_time is None:
            return 0.0
        return time.monotonic() - self.start_time


class Watchdog:
    """Monitor thread/process health and detect freezes or hangs.

    Implements a watchdog timer that must be periodically "pinged" to
    prevent timeout. If no ping is received within the timeout period,
    the on_timeout callback is invoked.

    Args:
        timeout: Seconds of inactivity before triggering timeout.
            If None, uses config default (30s).
        on_timeout: Callback invoked when timeout is detected.
            Can be sync or async function.
        name: Optional identifier for logging and monitoring.

    Examples:
        Basic usage:

        >>> watchdog = Watchdog(timeout=30)
        >>> watchdog.timeout
        30

        With callback:

        >>> def alert():
        ...     print("Watchdog triggered!")
        >>> wd = Watchdog(timeout=10, on_timeout=alert, name="worker")
        >>> wd.name
        'worker'

        As context manager:

        >>> with Watchdog(timeout=30) as wd:  # doctest: +SKIP
        ...     wd.ping()
        ...     do_work()
    """

    def __init__(
        self,
        *,
        timeout: float | None = None,
        on_timeout: Callable[[], None] | Callable[[], Awaitable[None]] | None = None,
        on_alert: OnAlertCallback | None = None,
        name: str | None = None,
    ) -> None:
        """Initialize watchdog.

        Args:
            timeout: Seconds before timeout triggers. Clamped to [1, 3600].
            on_timeout: Callback for timeout events (sync or async).
            on_alert: Callback for alerting (channel, message, context).
            name: Optional identifier.
        """
        # Load config defaults if needed
        if timeout is None:
            try:
                limits = get_resilience_limits()
                timeout = limits.watchdog_timeout
            except Exception:
                timeout = DEFAULT_WATCHDOG_TIMEOUT

        self._timeout = clamp_with_limits(timeout, HARD_MIN_WATCHDOG_TIMEOUT, HARD_MAX_WATCHDOG_TIMEOUT)
        self._on_timeout = on_timeout
        self._on_alert = on_alert
        self._name = name
        self._stats = WatchdogStats()

        # State
        self._last_ping = time.monotonic()
        self._running = False
        self._triggered = False
        self._shutdown_requested = False
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._async_task: asyncio.Task[None] | None = None
        self._callback_task: asyncio.Task[None] | None = None

        # State file monitoring (when using from_state_file)
        self._state_file: Path | None = None
        self._max_age: float = 30.0

    @property
    def timeout(self) -> float:
        """Timeout duration in seconds."""
        return self._timeout

    @property
    def name(self) -> str | None:
        """Watchdog identifier."""
        return self._name

    @property
    def stats(self) -> WatchdogStats:
        """Statistics for this watchdog."""
        return self._stats

    @property
    def is_running(self) -> bool:
        """Return True if watchdog is actively monitoring."""
        return self._running

    @property
    def is_triggered(self) -> bool:
        """Return True if timeout has been triggered."""
        return self._triggered

    @property
    def seconds_since_ping(self) -> float:
        """Return seconds since last ping."""
        with self._lock:
            return time.monotonic() - self._last_ping

    @property
    def is_shutdown(self) -> bool:
        """Check if shutdown has been requested."""
        return self._shutdown_requested

    @property
    def state_file(self) -> Path | None:
        """Return the state file path if monitoring a heartbeat file."""
        return self._state_file

    @classmethod
    def from_state_file(
        cls,
        state_file: str | Path,
        *,
        check_interval: float | None = None,
        max_age: float = 30.0,
        on_timeout: Callable[[], None] | Callable[[], Awaitable[None]] | None = None,
        on_alert: OnAlertCallback | None = None,
        name: str | None = None,
    ) -> Self:
        """Create a watchdog that monitors a heartbeat state file.

        Instead of requiring periodic ping() calls, this watchdog checks
        if a heartbeat state file is being updated regularly.

        Args:
            state_file: Path to the heartbeat JSON state file.
            check_interval: Seconds between file checks (defaults to max_age/2).
            max_age: Maximum age in seconds before triggering timeout (default: 30s).
            on_timeout: Callback for timeout events.
            on_alert: Callback for alerting (channel, message, context).
            name: Optional identifier.

        Returns:
            Configured Watchdog instance.

        Examples:
            >>> wd = Watchdog.from_state_file(  # doctest: +SKIP
            ...     "/tmp/bot.heartbeat",
            ...     max_age=30.0,  # Trigger if no heartbeat for 30 seconds
            ...     on_timeout=restart_bot,
            ... )
            >>> await wd.astart()  # doctest: +SKIP
        """
        interval = check_interval if check_interval is not None else max_age / 2
        instance = cls(
            timeout=interval,
            on_timeout=on_timeout,
            on_alert=on_alert,
            name=name or f"state_file_watcher:{state_file}",
        )
        instance._state_file = Path(state_file)
        instance._max_age = max_age
        return instance

    def shutdown(self) -> None:
        """Signal shutdown and stop gracefully."""
        log.info("Watchdog shutdown requested")
        self._shutdown_requested = True
        self.stop()

    async def ashutdown(self) -> None:
        """Signal shutdown and stop gracefully (async version)."""
        log.info("Watchdog shutdown requested")
        self._shutdown_requested = True
        await self.astop()

    def ping(self) -> None:
        """Reset the watchdog timer.

        Call this periodically to indicate the monitored code is still alive.
        Must be called more frequently than the timeout interval.

        Examples:
            >>> watchdog = Watchdog(timeout=30)
            >>> watchdog.ping()  # Reset timer
        """
        with self._lock:
            self._last_ping = time.monotonic()
            self._stats.record_ping()

    async def aping(self) -> None:
        """Async version of ping().

        Examples:
            >>> import asyncio
            >>> async def example():
            ...     watchdog = Watchdog(timeout=30)
            ...     await watchdog.aping()
            >>> asyncio.run(example())
        """
        self.ping()

    def start(self) -> None:
        """Start watchdog monitoring in a background thread.

        Raises:
            RuntimeError: If watchdog is already running.

        Examples:
            >>> watchdog = Watchdog(timeout=30)
            >>> watchdog.start()
            >>> watchdog.is_running
            True
            >>> watchdog.stop()
        """
        with self._lock:
            if self._running:
                raise RuntimeError("Watchdog is already running")

            self._running = True
            self._triggered = False
            self._stop_event.clear()
            self._last_ping = time.monotonic()
            self._stats.record_start()

        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop watchdog monitoring.

        Safe to call multiple times or when not running.

        Examples:
            >>> watchdog = Watchdog(timeout=30)
            >>> watchdog.start()
            >>> watchdog.stop()
            >>> watchdog.is_running
            False
        """
        with self._lock:
            if not self._running:
                return
            self._running = False

        self._stop_event.set()

        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    async def astart(self) -> None:
        """Start watchdog monitoring asynchronously.

        Raises:
            RuntimeError: If watchdog is already running.
        """
        with self._lock:
            if self._running:
                raise RuntimeError("Watchdog is already running")

            self._running = True
            self._triggered = False
            self._stop_event.clear()
            self._last_ping = time.monotonic()
            self._stats.record_start()

        self._async_task = asyncio.create_task(self._async_monitor_loop())

    async def astop(self) -> None:
        """Stop watchdog monitoring asynchronously.

        Safe to call multiple times or when not running.
        """
        with self._lock:
            if not self._running:
                return
            self._running = False

        self._stop_event.set()

        if self._async_task is not None:
            self._async_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._async_task
            self._async_task = None

    def reset(self) -> None:
        """Reset watchdog state without stopping.

        Clears triggered flag and resets timer.
        """
        with self._lock:
            self._last_ping = time.monotonic()
            self._triggered = False

    def _monitor_loop(self) -> None:
        """Background thread monitoring loop."""
        check_interval = min(1.0, self._timeout / 4)

        while not self._stop_event.wait(timeout=check_interval):
            if self._shutdown_requested:
                break
            self._check_timeout()

    async def _async_monitor_loop(self) -> None:
        """Async monitoring loop."""
        check_interval = min(1.0, self._timeout / 4)

        while self._running and not self._shutdown_requested:
            await asyncio.sleep(check_interval)
            await self._async_check_timeout()

    def _check_timeout(self) -> None:
        """Check for timeout and invoke callback if needed."""
        # If monitoring a state file, check that instead of ping time
        if self._state_file is not None:
            self._check_state_file_sync()
            return

        with self._lock:
            if self._triggered:
                return

            elapsed = time.monotonic() - self._last_ping
            if elapsed < self._timeout:
                return

            self._triggered = True
            self._stats.record_timeout()

        # Invoke callback outside lock - suppress errors to prevent watchdog crash
        if self._on_timeout is not None:
            with contextlib.suppress(Exception):
                result = self._on_timeout()
                # Handle async callback in sync context
                if inspect.iscoroutine(result):
                    # Run async callback in new event loop
                    try:
                        loop = asyncio.get_running_loop()
                        self._callback_task = loop.create_task(result)
                    except RuntimeError:
                        asyncio.run(result)

    def _check_state_file_sync(self) -> None:
        """Check heartbeat state file (sync version)."""
        if self._state_file is None:
            return

        is_alive = self._is_state_file_alive()

        with self._lock:
            if is_alive:
                # Reset triggered state if heartbeat is back
                self._triggered = False
                return

            if self._triggered:
                return

            self._triggered = True
            self._stats.record_timeout()

        # Invoke callbacks outside lock
        if self._on_timeout is not None:
            with contextlib.suppress(Exception):
                result = self._on_timeout()
                if inspect.iscoroutine(result):
                    result.close()  # Cannot await in sync context

    def _is_state_file_alive(self) -> bool:
        """Check if heartbeat state file is recent enough."""
        if self._state_file is None or not self._state_file.exists():
            return False
        try:
            data = json.loads(self._state_file.read_text())
            timestamp = data.get("timestamp")
            if not timestamp:
                return False
            beat_time = datetime.fromisoformat(timestamp)
            age = (datetime.now(timezone.utc) - beat_time).total_seconds()
            return age <= self._max_age
        except (json.JSONDecodeError, KeyError, OSError, ValueError, TypeError):
            return False

    async def _async_check_timeout(self) -> None:
        """Async version of timeout check."""
        # If monitoring a state file, check that instead of ping time
        if self._state_file is not None:
            await self._check_state_file_async()
            return

        with self._lock:
            if self._triggered:
                return

            elapsed = time.monotonic() - self._last_ping
            if elapsed < self._timeout:
                return

            self._triggered = True
            self._stats.record_timeout()

        # Invoke callback outside lock - suppress errors to prevent watchdog crash
        if self._on_timeout is not None:
            with contextlib.suppress(Exception):
                result = self._on_timeout()
                if inspect.iscoroutine(result):
                    await result

    async def _check_state_file_async(self) -> None:
        """Check heartbeat state file (async version)."""
        if self._state_file is None:
            return

        # Run file check in executor to avoid blocking
        loop = asyncio.get_running_loop()
        is_alive = await loop.run_in_executor(None, self._is_state_file_alive)

        with self._lock:
            if is_alive:
                # Reset triggered state if heartbeat is back
                self._triggered = False
                return

            if self._triggered:
                return

            self._triggered = True
            self._stats.record_timeout()

        # Send alert if callback provided
        if self._on_alert is not None:
            with contextlib.suppress(Exception):
                alert_result = self._on_alert(
                    "watchdog",
                    f"Heartbeat state file is stale: {self._state_file}",
                    {"state_file": str(self._state_file), "max_age": self._max_age},
                )
                if asyncio.iscoroutine(alert_result):
                    await alert_result

        # Invoke timeout callback outside lock
        if self._on_timeout is not None:
            with contextlib.suppress(Exception):
                result = self._on_timeout()
                if inspect.iscoroutine(result):
                    await result

    def __enter__(self) -> Self:
        """Enter context manager, starting watchdog."""
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Exit context manager, stopping watchdog."""
        self.stop()

    async def __aenter__(self) -> Self:
        """Enter async context manager, starting watchdog."""
        await self.astart()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Exit async context manager, stopping watchdog."""
        await self.astop()

    def __repr__(self) -> str:
        """Return string representation."""
        name_part = f", name={self._name!r}" if self._name else ""
        status = "running" if self._running else "stopped"
        return f"Watchdog(timeout={self._timeout}, status={status}{name_part})"


def watchdog_context(
    timeout: float | None = None,
    on_timeout: Callable[[], None] | Callable[[], Awaitable[None]] | None = None,
    *,
    raise_on_timeout: bool = False,
    name: str | None = None,
) -> Watchdog:
    """Create a watchdog context for monitoring code blocks.

    This is a convenience function that creates a Watchdog instance.
    Use with 'with' statement for automatic start/stop.

    Args:
        timeout: Seconds before timeout triggers.
        on_timeout: Optional callback for timeout events.
        raise_on_timeout: If True, raise WatchdogTimeoutError on timeout.
        name: Optional identifier.

    Returns:
        Watchdog instance for use as context manager.

    Examples:
        >>> with watchdog_context(timeout=30) as wd:  # doctest: +SKIP
        ...     for item in items:
        ...         wd.ping()
        ...         process(item)
    """
    callback = on_timeout

    if raise_on_timeout and on_timeout is None:

        def raise_timeout() -> None:
            raise WatchdogTimeoutError(
                f"Watchdog timeout after {timeout}s",
                seconds_inactive=timeout or DEFAULT_WATCHDOG_TIMEOUT,
            )

        callback = raise_timeout

    return Watchdog(timeout=timeout, on_timeout=callback, name=name)


__all__ = [
    "OnAlertCallback",
    "Watchdog",
    "WatchdogStats",
    "watchdog_context",
]
