"""Heartbeat mechanism for process liveness signaling."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import socket
import threading
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from typing_extensions import Self

from kstlib.limits import (
    HARD_MAX_HEARTBEAT_INTERVAL,
    HARD_MIN_HEARTBEAT_INTERVAL,
    clamp_with_limits,
    get_resilience_limits,
)
from kstlib.resilience.exceptions import HeartbeatError

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    import types

# Type aliases for callbacks
OnAlertCallback = Callable[[str, str, Mapping[str, Any]], Awaitable[None] | None]


@runtime_checkable
class HeartbeatTarget(Protocol):
    """Protocol for objects that can be monitored by Heartbeat.

    Any object implementing `is_dead` property can be used as a target.
    This allows Heartbeat to detect when a monitored component has failed.

    Examples:
        >>> class MyWebSocket:  # doctest: +SKIP
        ...     @property
        ...     def is_dead(self) -> bool:
        ...         return not self.connected
    """

    @property
    def is_dead(self) -> bool:
        """Check if the target is dead and needs restart."""
        ...


@dataclass(frozen=True, slots=True)
class HeartbeatState:
    """Represents the state written to the heartbeat file.

    Attributes:
        timestamp: Last heartbeat time (ISO 8601 UTC).
        pid: Process ID.
        hostname: Machine hostname.
        metadata: Optional application-specific data.

    Examples:
        >>> state = HeartbeatState(
        ...     timestamp="2026-01-12T10:00:00+00:00",
        ...     pid=1234,
        ...     hostname="myhost",
        ... )
        >>> state.pid
        1234
    """

    timestamp: str
    pid: int
    hostname: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dictionary.

        Returns:
            Dictionary representation of the heartbeat state.
        """
        return {
            "timestamp": self.timestamp,
            "pid": self.pid,
            "hostname": self.hostname,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HeartbeatState:
        """Deserialize from dictionary.

        Args:
            data: Dictionary with heartbeat state fields.

        Returns:
            HeartbeatState instance.

        Raises:
            KeyError: If required fields are missing.
        """
        return cls(
            timestamp=data["timestamp"],
            pid=data["pid"],
            hostname=data["hostname"],
            metadata=data.get("metadata", {}),
        )


class Heartbeat:
    """Periodic signal to indicate the process is alive.

    Writes timestamp to a JSON state file at configurable intervals.
    Supports both sync and async context managers.

    Args:
        state_file: Path to the heartbeat state file. If None, no file is written
            (useful when using on_beat callback for state management).
        interval: Seconds between heartbeats (default from config or 10s).
        on_missed_beat: Callback invoked when a beat write fails.
        on_alert: Callback for alerting (channel, message, context).
        target: Optional object with `is_dead` property to monitor.
        on_target_dead: Callback invoked when target is detected as dead.
        on_beat: Callback invoked after each successful beat. Can be sync or async.
            Use this to delegate state writing to an external component.
        metadata: Optional dict included in each heartbeat.

    Examples:
        Sync context manager:

        >>> with Heartbeat("/tmp/bot.heartbeat") as hb:  # doctest: +SKIP
        ...     do_work()

        Async context manager:

        >>> async with Heartbeat("/tmp/bot.heartbeat") as hb:  # doctest: +SKIP
        ...     await do_async_work()

        Check if a process is alive:

        >>> Heartbeat.is_alive("/tmp/bot.heartbeat", max_age_seconds=30)  # doctest: +SKIP
        True

        Monitor a WebSocket:

        >>> hb = Heartbeat(  # doctest: +SKIP
        ...     "/tmp/bot.heartbeat",
        ...     target=ws_manager,
        ...     on_target_dead=lambda: restart_ws(),
        ... )
    """

    def __init__(
        self,
        state_file: str | Path | None = None,
        *,
        interval: float | None = None,
        on_missed_beat: Callable[[Exception], None] | None = None,
        on_alert: OnAlertCallback | None = None,
        target: HeartbeatTarget | None = None,
        on_target_dead: Callable[[], Awaitable[None] | None] | None = None,
        on_beat: Callable[[], Awaitable[None] | None] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Initialize heartbeat.

        Args:
            state_file: Path to the heartbeat state file. If None, no file is written.
            interval: Seconds between heartbeats. Uses config default if None.
            on_missed_beat: Callback invoked when a beat write fails.
            on_alert: Callback for alerting (channel, message, context).
            target: Optional object with `is_dead` property to monitor.
            on_target_dead: Callback invoked when target is detected as dead.
            on_beat: Callback invoked after each successful beat.
            metadata: Optional dict included in each heartbeat.
        """
        self._state_file = Path(state_file) if state_file else None
        self._on_missed_beat = on_missed_beat
        self._on_alert = on_alert
        self._target = target
        self._on_target_dead = on_target_dead
        self._on_beat = on_beat
        self._metadata = metadata or {}

        # Load interval from config if not provided, or clamp user value
        limits = get_resilience_limits()
        self._interval = (
            limits.heartbeat_interval
            if interval is None
            else clamp_with_limits(interval, HARD_MIN_HEARTBEAT_INTERVAL, HARD_MAX_HEARTBEAT_INTERVAL)
        )

        # Threading state
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._shutdown_requested = False

        # Async state
        self._async_task: asyncio.Task[None] | None = None

    @property
    def interval(self) -> float:
        """Return the heartbeat interval in seconds."""
        return self._interval

    @property
    def state_file(self) -> Path | None:
        """Return the path to the state file, or None if not configured."""
        return self._state_file

    @property
    def is_shutdown(self) -> bool:
        """Check if shutdown has been requested."""
        return self._shutdown_requested

    @property
    def target(self) -> HeartbeatTarget | None:
        """Return the monitored target, if any."""
        return self._target

    def shutdown(self) -> None:
        """Signal shutdown and stop gracefully.

        Sets the shutdown flag which can be checked by external code
        to know that we're shutting down intentionally.
        """
        log.info("Heartbeat shutdown requested")
        self._shutdown_requested = True
        self.stop()

    async def ashutdown(self) -> None:
        """Signal shutdown and stop gracefully (async version)."""
        log.info("Heartbeat shutdown requested")
        self._shutdown_requested = True
        await self.astop()

    def start(self) -> None:
        """Start the heartbeat background thread.

        Raises:
            HeartbeatError: If heartbeat is already running.
        """
        with self._lock:
            if self._running:
                raise HeartbeatError("Heartbeat is already running")
            self._running = True
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Stop the heartbeat and clean up.

        Safe to call multiple times or if not started.
        """
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._stop_event.set()

        if self._thread is not None:
            self._thread.join(timeout=self._interval + 1.0)
            self._thread = None

    def beat(self) -> None:
        """Write a heartbeat immediately (manual trigger).

        If state_file is configured, writes to file.
        If on_beat callback is configured, it will be invoked by the loop (not here).

        Raises:
            HeartbeatError: If state file is configured and cannot be written.
        """
        # Skip file write if no state_file configured
        if self._state_file is None:
            return

        state = HeartbeatState(
            timestamp=datetime.now(timezone.utc).isoformat(),
            pid=os.getpid(),
            hostname=socket.gethostname(),
            metadata=self._metadata,
        )
        try:
            # Ensure parent directory exists with proper permissions
            self._state_file.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            # Write atomically using temp file
            temp_file = self._state_file.with_suffix(".tmp")
            temp_file.write_text(json.dumps(state.to_dict(), indent=2))
            temp_file.replace(self._state_file)
        except OSError as exc:
            raise HeartbeatError(f"Failed to write heartbeat: {exc}") from exc

    def _run_loop(self) -> None:
        """Background thread loop that writes heartbeats and checks target."""
        while not self._stop_event.wait(timeout=self._interval):
            if self._shutdown_requested:
                break
            try:
                self.beat()
                # Invoke on_beat callback after successful beat
                if self._on_beat is not None:
                    with contextlib.suppress(Exception):
                        result = self._on_beat()
                        # Note: Cannot await in sync thread, result is ignored if coroutine
                        if asyncio.iscoroutine(result):
                            result.close()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                if self._on_missed_beat is not None:
                    with contextlib.suppress(Exception):
                        self._on_missed_beat(exc)

            # Check target if provided (sync version cannot use async callbacks)
            if self._target is not None and self._target.is_dead and self._on_target_dead is not None:
                with contextlib.suppress(Exception):
                    result = self._on_target_dead()
                    # Note: Cannot await in sync thread, result is ignored if coroutine
                    if asyncio.iscoroutine(result):
                        # Close the coroutine to avoid warning
                        result.close()

    async def astart(self) -> None:
        """Start the heartbeat using asyncio (async version).

        Raises:
            HeartbeatError: If heartbeat is already running.
        """
        with self._lock:
            if self._running:
                raise HeartbeatError("Heartbeat is already running")
            self._running = True

        self._async_task = asyncio.create_task(self._async_loop())

    async def astop(self) -> None:
        """Stop the heartbeat (async version).

        Safe to call multiple times or if not started.
        """
        with self._lock:
            if not self._running:
                return
            self._running = False

        if self._async_task is not None:
            self._async_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._async_task
            self._async_task = None

    async def _invoke_callback_async(
        self,
        callback: Callable[[], Awaitable[None] | None] | None,
    ) -> None:
        """Invoke a callback that may be sync or async."""
        if callback is not None:
            try:
                result = callback()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                log.warning("Callback failed: %s", exc)

    async def _check_target_async(self) -> None:
        """Check target health and invoke callbacks if dead."""
        if self._target is None or not self._target.is_dead:
            return

        # Send alert if callback provided
        if self._on_alert is not None:
            with contextlib.suppress(Exception):
                alert_result = self._on_alert(
                    "heartbeat",
                    "Target is dead, triggering recovery",
                    {"target": str(type(self._target).__name__)},
                )
                if asyncio.iscoroutine(alert_result):
                    await alert_result

        # Invoke on_target_dead callback
        await self._invoke_callback_async(self._on_target_dead)

    async def _async_loop(self) -> None:
        """Async loop that writes heartbeats and monitors target."""
        log.debug("Heartbeat async loop started (interval=%.1fs)", self._interval)
        while self._running and not self._shutdown_requested:
            try:
                # Run beat in executor to avoid blocking
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self.beat)
                # Invoke on_beat callback after successful beat
                if self._on_beat is not None:
                    log.debug("Invoking on_beat callback")
                await self._invoke_callback_async(self._on_beat)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                log.warning("Heartbeat beat failed: %s", exc)
                if self._on_missed_beat is not None:
                    with contextlib.suppress(Exception):
                        self._on_missed_beat(exc)

            await self._check_target_async()
            await asyncio.sleep(self._interval)

    @staticmethod
    def read_state(state_file: str | Path) -> HeartbeatState | None:
        """Read and parse an existing heartbeat state file.

        Args:
            state_file: Path to heartbeat file.

        Returns:
            HeartbeatState if file exists and is valid, None otherwise.

        Examples:
            >>> state = Heartbeat.read_state("/tmp/bot.heartbeat")  # doctest: +SKIP
            >>> if state:  # doctest: +SKIP
            ...     print(f"Last beat: {state.timestamp}")
        """
        path = Path(state_file)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return HeartbeatState.from_dict(data)
        except (json.JSONDecodeError, KeyError, OSError):
            return None

    @staticmethod
    def is_alive(state_file: str | Path, max_age_seconds: float = 30.0) -> bool:
        """Check if a process is alive based on its heartbeat.

        Args:
            state_file: Path to heartbeat file.
            max_age_seconds: Maximum age before considering process dead.

        Returns:
            True if heartbeat exists and is recent enough.

        Examples:
            >>> Heartbeat.is_alive("/tmp/bot.heartbeat", max_age_seconds=30)  # doctest: +SKIP
            True
        """
        state = Heartbeat.read_state(state_file)
        if state is None:
            return False
        try:
            beat_time = datetime.fromisoformat(state.timestamp)
            age = (datetime.now(timezone.utc) - beat_time).total_seconds()
            return age <= max_age_seconds
        except (ValueError, TypeError):
            return False

    def __enter__(self) -> Self:
        """Enter sync context manager."""
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Exit sync context manager."""
        self.stop()

    async def __aenter__(self) -> Self:
        """Enter async context manager."""
        await self.astart()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Exit async context manager."""
        await self.astop()


__all__ = ["Heartbeat", "HeartbeatState", "HeartbeatTarget", "OnAlertCallback"]
