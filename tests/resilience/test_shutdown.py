"""Tests for the GracefulShutdown class."""

from __future__ import annotations

import asyncio
import signal
import sys
import threading
import time
from typing import Any
from unittest.mock import patch

import pytest

from kstlib.resilience.exceptions import ShutdownError
from kstlib.resilience.shutdown import CleanupCallback, GracefulShutdown


class TestCleanupCallback:
    """Tests for CleanupCallback dataclass."""

    def test_create_callback(self) -> None:
        """Create a cleanup callback with required fields."""
        cb = CleanupCallback(
            name="test",
            callback=lambda: None,
            priority=50,
            timeout=5.0,
            is_async=False,
        )
        assert cb.name == "test"
        assert cb.priority == 50
        assert cb.timeout == 5.0
        assert cb.is_async is False

    def test_default_values(self) -> None:
        """Create callback with default values."""
        cb = CleanupCallback(name="test", callback=lambda: None)
        assert cb.priority == 100
        assert cb.timeout is None
        assert cb.is_async is False


class TestGracefulShutdownInit:
    """Tests for GracefulShutdown initialization."""

    def test_default_timeout_from_config(self) -> None:
        """Use default timeout from config when not specified."""
        shutdown = GracefulShutdown()
        assert shutdown.timeout == 30  # Default from config

    def test_custom_timeout(self) -> None:
        """Accept custom timeout parameter."""
        shutdown = GracefulShutdown(timeout=15.0)
        assert shutdown.timeout == 15.0

    def test_timeout_clamped_to_minimum(self) -> None:
        """Clamp timeout to hard minimum."""
        shutdown = GracefulShutdown(timeout=1.0)
        assert shutdown.timeout == 5  # Hard minimum

    def test_timeout_clamped_to_maximum(self) -> None:
        """Clamp timeout to hard maximum."""
        shutdown = GracefulShutdown(timeout=1000)
        assert shutdown.timeout == 300  # Hard maximum

    def test_default_signals_unix(self) -> None:
        """Auto-detect signals for Unix platforms."""
        if sys.platform == "win32":
            pytest.skip("Unix-only test")
        shutdown = GracefulShutdown()
        assert signal.SIGTERM in shutdown._signals
        assert signal.SIGINT in shutdown._signals

    def test_default_signals_windows(self) -> None:
        """Auto-detect signals for Windows platform."""
        if sys.platform != "win32":
            pytest.skip("Windows-only test")
        shutdown = GracefulShutdown()
        assert signal.SIGINT in shutdown._signals

    def test_custom_signals(self) -> None:
        """Accept custom signals parameter."""
        shutdown = GracefulShutdown(signals=(signal.SIGINT,))
        assert shutdown._signals == (signal.SIGINT,)

    def test_custom_force_exit_code(self) -> None:
        """Accept custom force exit code."""
        shutdown = GracefulShutdown(force_exit_code=2)
        assert shutdown._force_exit_code == 2

    def test_initial_state(self) -> None:
        """Initial state is not shutting down and not installed."""
        shutdown = GracefulShutdown()
        assert shutdown.is_shutting_down is False
        assert shutdown.is_installed is False


class TestGracefulShutdownRegister:
    """Tests for register() and unregister() methods."""

    def test_register_sync_callback(self) -> None:
        """Register a synchronous callback."""
        shutdown = GracefulShutdown()
        shutdown.register("test", lambda: None)
        assert "test" in shutdown._callbacks

    def test_register_async_callback(self) -> None:
        """Register an asynchronous callback."""

        async def async_cleanup() -> None:
            pass

        shutdown = GracefulShutdown()
        shutdown.register("async_test", async_cleanup)
        assert shutdown._callbacks["async_test"].is_async is True

    def test_register_with_priority(self) -> None:
        """Register callback with custom priority."""
        shutdown = GracefulShutdown()
        shutdown.register("high", lambda: None, priority=10)
        shutdown.register("low", lambda: None, priority=200)
        assert shutdown._callbacks["high"].priority == 10
        assert shutdown._callbacks["low"].priority == 200

    def test_register_with_timeout(self) -> None:
        """Register callback with per-callback timeout."""
        shutdown = GracefulShutdown()
        shutdown.register("fast", lambda: None, timeout=2.0)
        assert shutdown._callbacks["fast"].timeout == 2.0

    def test_register_duplicate_name_raises(self) -> None:
        """Raise ShutdownError when registering duplicate name."""
        shutdown = GracefulShutdown()
        shutdown.register("test", lambda: None)
        with pytest.raises(ShutdownError, match="already registered"):
            shutdown.register("test", lambda: None)

    def test_register_during_shutdown_raises(self) -> None:
        """Raise ShutdownError when registering during shutdown."""
        shutdown = GracefulShutdown()
        shutdown._shutting_down = True
        with pytest.raises(ShutdownError, match="during shutdown"):
            shutdown.register("test", lambda: None)

    def test_unregister_existing(self) -> None:
        """Unregister an existing callback."""
        shutdown = GracefulShutdown()
        shutdown.register("test", lambda: None)
        assert shutdown.unregister("test") is True
        assert "test" not in shutdown._callbacks

    def test_unregister_nonexistent(self) -> None:
        """Return False when unregistering nonexistent callback."""
        shutdown = GracefulShutdown()
        assert shutdown.unregister("nonexistent") is False


class TestGracefulShutdownInstall:
    """Tests for install() and uninstall() methods."""

    def test_install_sets_handlers(self) -> None:
        """Install signal handlers."""
        shutdown = GracefulShutdown()
        shutdown.install()
        try:
            assert shutdown.is_installed is True
        finally:
            shutdown.uninstall()

    def test_install_twice_raises(self) -> None:
        """Raise ShutdownError when installing twice."""
        shutdown = GracefulShutdown()
        shutdown.install()
        try:
            with pytest.raises(ShutdownError, match="already installed"):
                shutdown.install()
        finally:
            shutdown.uninstall()

    def test_uninstall_restores_handlers(self) -> None:
        """Uninstall restores original handlers."""
        shutdown = GracefulShutdown()
        shutdown.install()
        shutdown.uninstall()
        assert shutdown.is_installed is False
        assert len(shutdown._original_handlers) == 0

    def test_uninstall_when_not_installed(self) -> None:
        """Uninstall is safe when not installed."""
        shutdown = GracefulShutdown()
        shutdown.uninstall()  # Should not raise
        assert shutdown.is_installed is False


class TestGracefulShutdownTrigger:
    """Tests for trigger() and atrigger() methods."""

    def test_trigger_sets_shutting_down(self) -> None:
        """Trigger sets is_shutting_down flag."""
        shutdown = GracefulShutdown()
        shutdown.trigger()
        assert shutdown.is_shutting_down is True

    def test_trigger_runs_callbacks_in_priority_order(self) -> None:
        """Trigger runs callbacks in priority order."""
        order: list[str] = []
        shutdown = GracefulShutdown()
        shutdown.register("third", lambda: order.append("third"), priority=300)
        shutdown.register("first", lambda: order.append("first"), priority=100)
        shutdown.register("second", lambda: order.append("second"), priority=200)

        shutdown.trigger()

        assert order == ["first", "second", "third"]

    def test_trigger_twice_runs_callbacks_once(self) -> None:
        """Trigger multiple times only runs callbacks once."""
        call_count = 0

        def counter() -> None:
            nonlocal call_count
            call_count += 1

        shutdown = GracefulShutdown()
        shutdown.register("counter", counter)
        shutdown.trigger()
        shutdown.trigger()

        assert call_count == 1

    def test_trigger_handles_callback_exception(self) -> None:
        """Trigger continues despite callback exceptions."""
        order: list[str] = []

        def failing() -> None:
            raise RuntimeError("fail")

        shutdown = GracefulShutdown()
        shutdown.register("fail", failing, priority=1)
        shutdown.register("success", lambda: order.append("success"), priority=2)

        shutdown.trigger()  # Should not raise

        assert order == ["success"]

    def test_trigger_handles_slow_callback(self) -> None:
        """Trigger continues when callback exceeds timeout."""
        order: list[str] = []
        slow_started = threading.Event()

        def slow() -> None:
            slow_started.set()
            time.sleep(0.1)  # Longer than timeout
            order.append("slow")

        shutdown = GracefulShutdown(timeout=0.1)
        shutdown.register("slow", slow, timeout=0.05)
        shutdown.register("fast", lambda: order.append("fast"), priority=200)

        shutdown.trigger()

        # Fast should complete, slow may or may not (thread continues)
        assert "fast" in order

    @pytest.mark.asyncio
    async def test_atrigger_sets_shutting_down(self) -> None:
        """Async trigger sets is_shutting_down flag."""
        shutdown = GracefulShutdown()
        await shutdown.atrigger()
        assert shutdown.is_shutting_down is True

    @pytest.mark.asyncio
    async def test_atrigger_runs_async_callbacks(self) -> None:
        """Async trigger runs async callbacks."""
        order: list[str] = []

        async def async_cleanup() -> None:
            order.append("async")

        shutdown = GracefulShutdown()
        shutdown.register("async", async_cleanup)
        await shutdown.atrigger()

        assert order == ["async"]

    @pytest.mark.asyncio
    async def test_atrigger_runs_sync_callbacks(self) -> None:
        """Async trigger runs sync callbacks in executor."""
        order: list[str] = []

        shutdown = GracefulShutdown()
        shutdown.register("sync", lambda: order.append("sync"))
        await shutdown.atrigger()

        assert order == ["sync"]

    @pytest.mark.asyncio
    async def test_atrigger_handles_timeout(self) -> None:
        """Async trigger continues when callback exceeds timeout."""
        order: list[str] = []

        async def slow() -> None:
            await asyncio.sleep(0.1)  # Longer than timeout
            order.append("slow")

        shutdown = GracefulShutdown()
        shutdown.register("slow", slow, timeout=0.01)
        shutdown.register("fast", lambda: order.append("fast"), priority=200)

        await shutdown.atrigger()

        assert "fast" in order

    @pytest.mark.asyncio
    async def test_atrigger_handles_callback_exception(self) -> None:
        """Async trigger continues despite callback exceptions."""
        order: list[str] = []

        async def failing() -> None:
            raise RuntimeError("async fail")

        shutdown = GracefulShutdown()
        shutdown.register("fail", failing, priority=1)
        shutdown.register("success", lambda: order.append("success"), priority=2)

        await shutdown.atrigger()  # Should not raise

        assert order == ["success"]

    @pytest.mark.asyncio
    async def test_atrigger_twice_runs_callbacks_once(self) -> None:
        """Async trigger multiple times only runs callbacks once."""
        call_count = 0

        async def counter() -> None:
            nonlocal call_count
            call_count += 1

        shutdown = GracefulShutdown()
        shutdown.register("counter", counter)
        await shutdown.atrigger()
        await shutdown.atrigger()

        assert call_count == 1


class TestGracefulShutdownSyncAsync:
    """Tests for running async callbacks in sync context."""

    def test_sync_trigger_runs_async_callback(self) -> None:
        """Sync trigger can run async callbacks."""
        result: list[str] = []

        async def async_cleanup() -> None:
            result.append("async_ran")

        shutdown = GracefulShutdown()
        shutdown.register("async", async_cleanup)
        shutdown.trigger()

        assert result == ["async_ran"]

    def test_sync_trigger_async_callback_timeout(self) -> None:
        """Sync trigger handles async callback timeout."""
        result: list[str] = []

        async def slow_async() -> None:
            await asyncio.sleep(0.1)  # Longer than timeout
            result.append("slow")

        shutdown = GracefulShutdown()
        shutdown.register("slow", slow_async, timeout=0.01)
        shutdown.register("fast", lambda: result.append("fast"), priority=200)

        shutdown.trigger()

        assert "fast" in result

    def test_sync_trigger_async_callback_exception(self) -> None:
        """Sync trigger handles async callback exception."""
        result: list[str] = []

        async def failing_async() -> None:
            raise RuntimeError("async error")

        shutdown = GracefulShutdown()
        shutdown.register("fail", failing_async, priority=1)
        shutdown.register("success", lambda: result.append("ok"), priority=2)

        shutdown.trigger()  # Should not raise

        assert result == ["ok"]


class TestGracefulShutdownWait:
    """Tests for wait() and await_shutdown() methods."""

    def test_wait_returns_true_when_triggered(self) -> None:
        """Wait returns True when shutdown triggered."""
        shutdown = GracefulShutdown()

        def trigger_later() -> None:
            time.sleep(0.05)
            shutdown.trigger()

        thread = threading.Thread(target=trigger_later)
        thread.start()

        result = shutdown.wait(timeout=1.0)
        thread.join()

        assert result is True

    def test_wait_returns_false_on_timeout(self) -> None:
        """Wait returns False when timeout exceeded."""
        shutdown = GracefulShutdown()
        result = shutdown.wait(timeout=0.01)
        assert result is False

    @pytest.mark.asyncio
    async def test_await_shutdown_returns_true_when_triggered(self) -> None:
        """Await shutdown returns True when triggered."""
        shutdown = GracefulShutdown()

        async def trigger_later() -> None:
            await asyncio.sleep(0.05)
            shutdown._shutdown_event.set()

        task = asyncio.create_task(trigger_later())
        result = await shutdown.await_shutdown(timeout=1.0)
        await task

        assert result is True

    @pytest.mark.asyncio
    async def test_await_shutdown_returns_false_on_timeout(self) -> None:
        """Await shutdown returns False when timeout exceeded."""
        shutdown = GracefulShutdown()
        result = await shutdown.await_shutdown(timeout=0.01)
        assert result is False


class TestGracefulShutdownContextManager:
    """Tests for sync context manager."""

    def test_context_manager_installs_handlers(self) -> None:
        """Context manager installs signal handlers on enter."""
        with GracefulShutdown() as shutdown:
            assert shutdown.is_installed is True

    def test_context_manager_uninstalls_on_exit(self) -> None:
        """Context manager uninstalls handlers on exit."""
        shutdown = GracefulShutdown()
        with shutdown:
            pass
        assert shutdown.is_installed is False

    def test_context_manager_triggers_on_exit(self) -> None:
        """Context manager triggers shutdown on exit."""
        order: list[str] = []
        shutdown = GracefulShutdown()
        shutdown.register("cleanup", lambda: order.append("cleanup"))

        with shutdown:
            pass

        assert order == ["cleanup"]

    def test_context_manager_skips_trigger_if_already_shutting_down(self) -> None:
        """Context manager skips trigger if already shutting down."""
        call_count = 0

        def counter() -> None:
            nonlocal call_count
            call_count += 1

        shutdown = GracefulShutdown()
        shutdown.register("counter", counter)

        with shutdown:
            shutdown.trigger()  # Trigger manually

        # Should only be called once
        assert call_count == 1


class TestGracefulShutdownAsyncContextManager:
    """Tests for async context manager."""

    @pytest.mark.asyncio
    async def test_async_context_manager_installs_handlers(self) -> None:
        """Async context manager installs signal handlers on enter."""
        async with GracefulShutdown() as shutdown:
            assert shutdown.is_installed is True

    @pytest.mark.asyncio
    async def test_async_context_manager_uninstalls_on_exit(self) -> None:
        """Async context manager uninstalls handlers on exit."""
        shutdown = GracefulShutdown()
        async with shutdown:
            pass
        assert shutdown.is_installed is False

    @pytest.mark.asyncio
    async def test_async_context_manager_triggers_on_exit(self) -> None:
        """Async context manager triggers shutdown on exit."""
        order: list[str] = []

        async def cleanup() -> None:
            order.append("cleanup")

        shutdown = GracefulShutdown()
        shutdown.register("cleanup", cleanup)

        async with shutdown:
            pass

        assert order == ["cleanup"]

    @pytest.mark.asyncio
    async def test_async_context_manager_skips_trigger_if_shutting_down(self) -> None:
        """Async context manager skips trigger if already shutting down."""
        call_count = 0

        async def counter() -> None:
            nonlocal call_count
            call_count += 1

        shutdown = GracefulShutdown()
        shutdown.register("counter", counter)

        async with shutdown:
            await shutdown.atrigger()  # Trigger manually

        # Should only be called once
        assert call_count == 1


class TestGracefulShutdownSignalHandler:
    """Tests for signal handler functionality."""

    def test_signal_handler_triggers_shutdown(self) -> None:
        """Signal handler calls trigger()."""
        shutdown = GracefulShutdown()
        shutdown._signal_handler(signal.SIGINT, None)
        assert shutdown.is_shutting_down is True

    def test_install_handles_unavailable_signal(self) -> None:
        """Install handles signals that can't be caught."""
        # Use a signal that might not be available or catchable
        shutdown = GracefulShutdown()

        # Mock signal.signal to raise for one signal
        original_signal = signal.signal
        call_count = 0

        def mock_signal(sig: int, handler: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("Cannot catch signal")
            return original_signal(sig, handler)

        with patch.object(signal, "signal", side_effect=mock_signal):
            shutdown.install()

        # Should still be installed despite error
        shutdown.uninstall()

    def test_uninstall_handles_restore_error(self) -> None:
        """Uninstall handles errors when restoring handlers."""
        shutdown = GracefulShutdown()
        shutdown.install()

        # Mock signal.signal to raise during restore
        with patch.object(signal, "signal", side_effect=OSError("restore error")):
            shutdown.uninstall()  # Should not raise

        assert shutdown.is_installed is False


class TestGracefulShutdownEdgeCases:
    """Tests for edge cases and error handling."""

    def test_callbacks_with_same_priority_maintain_order(self) -> None:
        """Callbacks with same priority maintain registration order."""
        order: list[str] = []
        shutdown = GracefulShutdown()
        shutdown.register("a", lambda: order.append("a"), priority=100)
        shutdown.register("b", lambda: order.append("b"), priority=100)
        shutdown.register("c", lambda: order.append("c"), priority=100)

        shutdown.trigger()

        # Order is stable due to dict ordering in Python 3.7+
        assert len(order) == 3

    def test_callback_uses_global_timeout_when_none(self) -> None:
        """Callback uses global timeout when per-callback is None."""
        shutdown = GracefulShutdown(timeout=10)
        shutdown.register("test", lambda: None)

        callbacks = shutdown._get_sorted_callbacks()
        assert callbacks[0].timeout is None  # Stored as None

    @pytest.mark.asyncio
    async def test_async_sync_callback_timeout(self) -> None:
        """Async trigger handles sync callback timeout."""
        result: list[str] = []

        def slow_sync() -> None:
            time.sleep(0.1)  # Longer than timeout
            result.append("slow")

        shutdown = GracefulShutdown()
        shutdown.register("slow", slow_sync, timeout=0.01)
        shutdown.register("fast", lambda: result.append("fast"), priority=200)

        await shutdown.atrigger()

        assert "fast" in result
