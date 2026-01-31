"""Graceful shutdown handler with prioritized cleanup callbacks."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import signal
import sys
import threading
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from typing_extensions import Self

from kstlib.limits import (
    HARD_MAX_SHUTDOWN_TIMEOUT,
    HARD_MIN_SHUTDOWN_TIMEOUT,
    get_resilience_limits,
)
from kstlib.resilience.exceptions import ShutdownError

if TYPE_CHECKING:
    import types

log = logging.getLogger(__name__)

# Type aliases for callbacks
SyncCallback = Callable[[], None]
AsyncCallback = Callable[[], Coroutine[Any, Any, None]]
Callback = SyncCallback | AsyncCallback


@dataclass(frozen=True, slots=True)
class CleanupCallback:
    """Registered cleanup callback with metadata.

    Attributes:
        name: Unique identifier for the callback.
        callback: The cleanup function (sync or async).
        priority: Execution order (lower runs first, default 100).
        timeout: Per-callback timeout in seconds (None = use global).
        is_async: Whether the callback is async.

    Examples:
        >>> cb = CleanupCallback(
        ...     name="db_close",
        ...     callback=lambda: None,
        ...     priority=50,
        ...     timeout=5.0,
        ...     is_async=False,
        ... )
        >>> (cb.name, cb.priority, cb.timeout)
        ('db_close', 50, 5.0)
    """

    name: str
    callback: Callback
    priority: int = 100
    timeout: float | None = None
    is_async: bool = False


class GracefulShutdown:
    """Graceful shutdown handler with prioritized cleanup callbacks.

    Manages orderly shutdown on SIGTERM/SIGINT with timeout enforcement.
    Callbacks execute in priority order (lower = first).

    Args:
        timeout: Total timeout for all callbacks (default from config).
        signals: Signals to handle (default: SIGTERM, SIGINT).
        force_exit_code: Exit code when timeout exceeded (default: 1).

    Examples:
        Register callbacks with priority ordering:

        >>> shutdown = GracefulShutdown(timeout=30)
        >>> shutdown.register("cache", lambda: None, priority=20)
        >>> shutdown.register("db", lambda: None, priority=10)
        >>> [cb.name for cb in shutdown._get_sorted_callbacks()]
        ['db', 'cache']

        Context manager usage (with signals):

        >>> with GracefulShutdown() as shutdown:  # doctest: +SKIP
        ...     shutdown.register("cleanup", close_resources)
        ...     run_application()
    """

    # Signals not available on Windows
    _UNIX_SIGNALS: tuple[signal.Signals, ...] = (signal.SIGTERM, signal.SIGINT)
    _WINDOWS_SIGNALS: tuple[signal.Signals, ...] = (signal.SIGINT,)

    def __init__(
        self,
        *,
        timeout: float | None = None,
        signals: tuple[signal.Signals, ...] | None = None,
        force_exit_code: int = 1,
    ) -> None:
        """Initialize graceful shutdown handler.

        Args:
            timeout: Total timeout for all callbacks. Uses config if None.
            signals: Signals to handle. Auto-detects platform if None.
            force_exit_code: Exit code when timeout exceeded.
        """
        # Load timeout from config if not provided
        if timeout is None:
            limits = get_resilience_limits()
            self._timeout = limits.shutdown_timeout
        else:
            # Clamp to hard limits
            self._timeout = max(
                HARD_MIN_SHUTDOWN_TIMEOUT,
                min(timeout, HARD_MAX_SHUTDOWN_TIMEOUT),
            )

        # Auto-detect signals based on platform
        if signals is None:
            self._signals = self._WINDOWS_SIGNALS if sys.platform == "win32" else self._UNIX_SIGNALS
        else:
            self._signals = signals

        self._force_exit_code = force_exit_code

        # Callback registry
        self._callbacks: dict[str, CleanupCallback] = {}
        self._lock = threading.Lock()

        # Shutdown state
        self._shutting_down = False
        self._shutdown_event = threading.Event()

        # Original signal handlers (for restoration)
        self._original_handlers: dict[signal.Signals, Any] = {}
        self._installed = False

    @property
    def timeout(self) -> float:
        """Return the total shutdown timeout in seconds."""
        return self._timeout

    @property
    def is_shutting_down(self) -> bool:
        """Return True if shutdown is in progress."""
        return self._shutting_down

    @property
    def is_installed(self) -> bool:
        """Return True if signal handlers are installed."""
        return self._installed

    def register(
        self,
        name: str,
        callback: Callback,
        *,
        priority: int = 100,
        timeout: float | None = None,
    ) -> None:
        """Register a cleanup callback.

        Args:
            name: Unique identifier for the callback.
            callback: Cleanup function (sync or async).
            priority: Execution order (lower runs first, default 100).
            timeout: Per-callback timeout (None = use global).

        Raises:
            ShutdownError: If name already registered or shutdown in progress.

        Examples:
            >>> shutdown = GracefulShutdown()
            >>> shutdown.register("db", lambda: print("closing db"), priority=10)
            >>> "db" in [cb.name for cb in shutdown._callbacks.values()]
            True
        """
        with self._lock:
            if self._shutting_down:
                raise ShutdownError("Cannot register callback during shutdown")
            if name in self._callbacks:
                raise ShutdownError(f"Callback '{name}' already registered")

            is_async = inspect.iscoroutinefunction(callback)
            self._callbacks[name] = CleanupCallback(
                name=name,
                callback=callback,
                priority=priority,
                timeout=timeout,
                is_async=is_async,
            )

    def unregister(self, name: str) -> bool:
        """Unregister a cleanup callback.

        Args:
            name: Identifier of callback to remove.

        Returns:
            True if callback was removed, False if not found.

        Examples:
            >>> shutdown = GracefulShutdown()
            >>> shutdown.register("test", lambda: None)
            >>> shutdown.unregister("test")
            True
            >>> shutdown.unregister("nonexistent")
            False
        """
        with self._lock:
            if name in self._callbacks:
                del self._callbacks[name]
                return True
            return False

    def install(self) -> None:
        """Install signal handlers.

        Raises:
            ShutdownError: If handlers already installed.
        """
        with self._lock:
            if self._installed:
                raise ShutdownError("Signal handlers already installed")

            for sig in self._signals:
                with contextlib.suppress(OSError, ValueError):
                    self._original_handlers[sig] = signal.signal(sig, self._signal_handler)

            self._installed = True

    def uninstall(self) -> None:
        """Restore original signal handlers."""
        with self._lock:
            if not self._installed:
                return

            for sig, handler in self._original_handlers.items():
                with contextlib.suppress(OSError, ValueError):
                    signal.signal(sig, handler)

            self._original_handlers.clear()
            self._installed = False

    def _signal_handler(self, _signum: int, _frame: types.FrameType | None) -> None:
        """Handle incoming signal."""
        self.trigger()

    def trigger(self) -> None:
        """Trigger shutdown programmatically.

        Useful for testing or triggering shutdown from code.
        Runs callbacks synchronously in priority order.
        """
        with self._lock:
            if self._shutting_down:
                return
            self._shutting_down = True

        log.info("Shutdown requested")
        self._shutdown_event.set()
        self._run_callbacks_sync()

    async def atrigger(self) -> None:
        """Trigger shutdown programmatically (async version).

        Runs callbacks asynchronously in priority order.
        """
        with self._lock:
            if self._shutting_down:
                return
            self._shutting_down = True

        log.info("Shutdown requested")
        self._shutdown_event.set()
        await self._run_callbacks_async()

    def _get_sorted_callbacks(self) -> list[CleanupCallback]:
        """Return callbacks sorted by priority (ascending)."""
        with self._lock:
            return sorted(self._callbacks.values(), key=lambda cb: cb.priority)

    def _run_callbacks_sync(self) -> None:
        """Run all callbacks synchronously with timeout."""
        callbacks = self._get_sorted_callbacks()

        for cb in callbacks:
            cb_timeout = cb.timeout if cb.timeout is not None else self._timeout

            if cb.is_async:
                # Run async callback in new event loop
                async_callback = cast("AsyncCallback", cb.callback)
                try:
                    loop = asyncio.new_event_loop()
                    try:
                        loop.run_until_complete(asyncio.wait_for(async_callback(), timeout=cb_timeout))
                    finally:
                        loop.close()
                except asyncio.TimeoutError:
                    log.warning("Shutdown callback '%s' timed out", cb.name)
                except Exception:  # pylint: disable=broad-exception-caught
                    # Intentional: shutdown must continue even if callback fails
                    log.warning("Shutdown callback '%s' failed", cb.name, exc_info=True)
            else:
                # Run sync callback with timeout via thread
                # Wrap in suppress to prevent unhandled thread exceptions
                def safe_callback(fn: SyncCallback) -> None:
                    with contextlib.suppress(Exception):
                        fn()

                sync_callback = cast("SyncCallback", cb.callback)
                thread = threading.Thread(target=safe_callback, args=(sync_callback,))
                thread.start()
                thread.join(timeout=cb_timeout)
                # If thread still running after timeout, we continue anyway

    async def _run_callbacks_async(self) -> None:
        """Run all callbacks asynchronously with timeout."""
        callbacks = self._get_sorted_callbacks()

        for cb in callbacks:
            cb_timeout = cb.timeout if cb.timeout is not None else self._timeout

            try:
                if cb.is_async:
                    async_cb = cast("AsyncCallback", cb.callback)
                    await asyncio.wait_for(async_cb(), timeout=cb_timeout)
                else:
                    # Run sync callback in executor
                    loop = asyncio.get_running_loop()
                    await asyncio.wait_for(
                        loop.run_in_executor(None, cb.callback),
                        timeout=cb_timeout,
                    )
            except asyncio.TimeoutError:
                log.warning("Shutdown callback '%s' timed out", cb.name)
            except Exception:  # pylint: disable=broad-exception-caught
                # Intentional: shutdown must continue even if callback fails
                log.warning("Shutdown callback '%s' failed", cb.name, exc_info=True)

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for shutdown signal.

        Args:
            timeout: Maximum time to wait (None = wait forever).

        Returns:
            True if shutdown was triggered, False if timeout.
        """
        return self._shutdown_event.wait(timeout=timeout)

    async def await_shutdown(self, timeout: float | None = None) -> bool:
        """Wait for shutdown signal (async version).

        Args:
            timeout: Maximum time to wait (None = wait forever).

        Returns:
            True if shutdown was triggered, False if timeout.
        """
        # Use polling to avoid executor thread cleanup issues
        # Note: We poll a threading.Event, not asyncio.Event, hence the loop
        # The threading.Event is used to support both sync and async contexts
        poll_interval = 0.05  # 50ms polling
        if timeout is None:
            # Wait forever (poll threading.Event from async context)
            while not self._shutdown_event.is_set():
                await asyncio.sleep(poll_interval)
            return True

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not self._shutdown_event.is_set():
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False
            await asyncio.sleep(min(poll_interval, remaining))
        return True

    def __enter__(self) -> Self:
        """Enter sync context manager."""
        self.install()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Exit sync context manager."""
        self.uninstall()
        if not self._shutting_down:
            self.trigger()

    async def __aenter__(self) -> Self:
        """Enter async context manager."""
        self.install()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Exit async context manager."""
        self.uninstall()
        if not self._shutting_down:
            await self.atrigger()


__all__ = ["CleanupCallback", "GracefulShutdown"]
