"""Tests for the Watchdog class."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from kstlib.resilience.exceptions import WatchdogError, WatchdogTimeoutError
from kstlib.resilience.watchdog import Watchdog, WatchdogStats, watchdog_context


class TestWatchdogStats:
    """Tests for WatchdogStats dataclass."""

    def test_default_values(self) -> None:
        """Stats start at zero."""
        stats = WatchdogStats()
        assert stats.pings_total == 0
        assert stats.timeouts_triggered == 0
        assert stats.last_ping_time is None
        assert stats.start_time is None

    def test_record_ping(self) -> None:
        """Record a ping event."""
        stats = WatchdogStats()
        stats.record_ping()
        assert stats.pings_total == 1
        assert stats.last_ping_time is not None

    def test_record_timeout(self) -> None:
        """Record a timeout event."""
        stats = WatchdogStats()
        stats.record_timeout()
        assert stats.timeouts_triggered == 1

    def test_record_start(self) -> None:
        """Record watchdog start."""
        stats = WatchdogStats()
        stats.record_start()
        assert stats.start_time is not None
        assert stats.last_ping_time is not None

    def test_uptime_not_started(self) -> None:
        """Uptime is zero when not started."""
        stats = WatchdogStats()
        assert stats.uptime == 0.0

    def test_uptime_after_start(self) -> None:
        """Uptime increases after start."""
        stats = WatchdogStats()
        stats.record_start()
        time.sleep(0.05)
        assert stats.uptime >= 0.04


class TestWatchdogInit:
    """Tests for Watchdog initialization."""

    def test_default_timeout(self) -> None:
        """Default timeout from config or default."""
        watchdog = Watchdog()
        assert watchdog.timeout >= 1.0
        assert watchdog.timeout <= 3600.0

    def test_custom_timeout(self) -> None:
        """Custom timeout value."""
        watchdog = Watchdog(timeout=60)
        assert watchdog.timeout == 60.0

    def test_timeout_clamped_to_minimum(self) -> None:
        """Timeout clamped to minimum."""
        watchdog = Watchdog(timeout=0.1)
        assert watchdog.timeout == 1.0

    def test_timeout_clamped_to_maximum(self) -> None:
        """Timeout clamped to maximum."""
        watchdog = Watchdog(timeout=10000)
        assert watchdog.timeout == 3600.0

    def test_named_watchdog(self) -> None:
        """Initialize with a name."""
        watchdog = Watchdog(timeout=30, name="worker")
        assert watchdog.name == "worker"

    def test_repr(self) -> None:
        """String representation."""
        watchdog = Watchdog(timeout=30)
        assert "Watchdog" in repr(watchdog)
        assert "timeout=30" in repr(watchdog)
        assert "stopped" in repr(watchdog)

    def test_repr_with_name(self) -> None:
        """String representation with name."""
        watchdog = Watchdog(timeout=30, name="test")
        assert "name='test'" in repr(watchdog)

    def test_initial_state(self) -> None:
        """Initial state is stopped and not triggered."""
        watchdog = Watchdog(timeout=30)
        assert not watchdog.is_running
        assert not watchdog.is_triggered


class TestWatchdogPing:
    """Tests for ping functionality."""

    def test_ping_resets_timer(self) -> None:
        """Ping resets the activity timer."""
        watchdog = Watchdog(timeout=30)
        time.sleep(0.05)
        assert watchdog.seconds_since_ping >= 0.04
        watchdog.ping()
        assert watchdog.seconds_since_ping < 0.02

    def test_ping_records_stats(self) -> None:
        """Ping increments stats."""
        watchdog = Watchdog(timeout=30)
        watchdog.ping()
        watchdog.ping()
        watchdog.ping()
        assert watchdog.stats.pings_total == 3

    @pytest.mark.asyncio
    async def test_aping(self) -> None:
        """Async ping works."""
        watchdog = Watchdog(timeout=30)
        await watchdog.aping()
        assert watchdog.stats.pings_total == 1


class TestWatchdogStartStop:
    """Tests for start/stop functionality."""

    def test_start_sets_running(self) -> None:
        """Start sets running state."""
        watchdog = Watchdog(timeout=30)
        watchdog.start()
        try:
            assert watchdog.is_running
        finally:
            watchdog.stop()

    def test_start_raises_if_already_running(self) -> None:
        """Start raises if already running."""
        watchdog = Watchdog(timeout=30)
        watchdog.start()
        try:
            with pytest.raises(RuntimeError, match="already running"):
                watchdog.start()
        finally:
            watchdog.stop()

    def test_stop_clears_running(self) -> None:
        """Stop clears running state."""
        watchdog = Watchdog(timeout=30)
        watchdog.start()
        watchdog.stop()
        assert not watchdog.is_running

    def test_stop_when_not_running(self) -> None:
        """Stop is safe when not running."""
        watchdog = Watchdog(timeout=30)
        watchdog.stop()  # Should not raise
        assert not watchdog.is_running

    def test_stop_multiple_times(self) -> None:
        """Stop can be called multiple times."""
        watchdog = Watchdog(timeout=30)
        watchdog.start()
        watchdog.stop()
        watchdog.stop()
        watchdog.stop()
        assert not watchdog.is_running


class TestWatchdogTimeout:
    """Tests for timeout detection."""

    def test_timeout_triggers_callback(self) -> None:
        """Callback is invoked on timeout."""
        triggered = threading.Event()

        def on_timeout() -> None:
            triggered.set()

        watchdog = Watchdog(timeout=1, on_timeout=on_timeout)
        watchdog.start()
        try:
            # Wait for timeout + check interval
            assert triggered.wait(timeout=3.0)
            assert watchdog.is_triggered
            assert watchdog.stats.timeouts_triggered == 1
        finally:
            watchdog.stop()

    def test_ping_prevents_timeout(self) -> None:
        """Pinging prevents timeout."""
        triggered = threading.Event()

        def on_timeout() -> None:
            triggered.set()

        watchdog = Watchdog(timeout=1, on_timeout=on_timeout)
        watchdog.start()
        try:
            # Keep pinging to prevent timeout
            for _ in range(5):
                watchdog.ping()
                time.sleep(0.3)

            assert not triggered.is_set()
            assert not watchdog.is_triggered
        finally:
            watchdog.stop()

    def test_reset_clears_triggered(self) -> None:
        """Reset clears triggered state."""
        watchdog = Watchdog(timeout=1)  # Hard min is 1s
        watchdog.start()
        try:
            time.sleep(1.2)  # Let it timeout
            if watchdog.is_triggered:
                watchdog.reset()
                assert not watchdog.is_triggered
        finally:
            watchdog.stop()


class TestWatchdogAsync:
    """Tests for async functionality."""

    @pytest.mark.asyncio
    async def test_astart_astop(self) -> None:
        """Async start/stop works."""
        watchdog = Watchdog(timeout=30)
        await watchdog.astart()
        try:
            assert watchdog.is_running
        finally:
            await watchdog.astop()
        assert not watchdog.is_running

    @pytest.mark.asyncio
    async def test_astart_raises_if_running(self) -> None:
        """Astart raises if already running."""
        watchdog = Watchdog(timeout=30)
        await watchdog.astart()
        try:
            with pytest.raises(RuntimeError, match="already running"):
                await watchdog.astart()
        finally:
            await watchdog.astop()

    @pytest.mark.asyncio
    async def test_astop_when_not_running(self) -> None:
        """Astop is safe when not running."""
        watchdog = Watchdog(timeout=30)
        await watchdog.astop()  # Should not raise

    @pytest.mark.asyncio
    async def test_async_timeout_callback(self) -> None:
        """Async callback is invoked on timeout."""
        triggered = asyncio.Event()

        async def on_timeout() -> None:
            triggered.set()

        watchdog = Watchdog(timeout=1, on_timeout=on_timeout)
        await watchdog.astart()
        try:
            await asyncio.wait_for(triggered.wait(), timeout=3.0)
            assert watchdog.is_triggered
        finally:
            await watchdog.astop()


class TestWatchdogContextManager:
    """Tests for context manager usage."""

    def test_sync_context_manager(self) -> None:
        """Sync context manager starts and stops."""
        with Watchdog(timeout=30) as wd:
            assert wd.is_running
            wd.ping()
        assert not wd.is_running

    def test_sync_context_manager_stops_on_exception(self) -> None:
        """Context manager stops on exception."""
        watchdog = Watchdog(timeout=30)
        with pytest.raises(ValueError), watchdog:
            raise ValueError("test")
        assert not watchdog.is_running

    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        """Async context manager starts and stops."""
        async with Watchdog(timeout=30) as wd:
            assert wd.is_running
            await wd.aping()
        assert not wd.is_running

    @pytest.mark.asyncio
    async def test_async_context_manager_stops_on_exception(self) -> None:
        """Async context manager stops on exception."""
        watchdog = Watchdog(timeout=30)
        with pytest.raises(ValueError):
            async with watchdog:
                raise ValueError("test")
        assert not watchdog.is_running


class TestWatchdogContext:
    """Tests for watchdog_context function."""

    def test_creates_watchdog(self) -> None:
        """Creates a watchdog instance."""
        wd = watchdog_context(timeout=30)
        assert isinstance(wd, Watchdog)
        assert wd.timeout == 30.0

    def test_with_callback(self) -> None:
        """Creates watchdog with callback."""
        called = []

        def cb() -> None:
            called.append(True)

        wd = watchdog_context(timeout=30, on_timeout=cb)
        assert wd._on_timeout is cb

    def test_raise_on_timeout(self) -> None:
        """Creates watchdog that raises on timeout."""
        wd = watchdog_context(timeout=1, raise_on_timeout=True)  # Hard min is 1s
        wd.start()
        try:
            time.sleep(1.2)
            # The callback should raise, but it's caught internally
            assert wd.is_triggered
        finally:
            wd.stop()


class TestWatchdogExceptions:
    """Tests for watchdog exceptions."""

    def test_watchdog_error_base(self) -> None:
        """WatchdogError is RuntimeError."""
        exc = WatchdogError("test")
        assert isinstance(exc, RuntimeError)
        assert str(exc) == "test"

    def test_watchdog_timeout_error(self) -> None:
        """WatchdogTimeoutError has seconds_inactive."""
        exc = WatchdogTimeoutError("Timeout!", seconds_inactive=30.5)
        assert str(exc) == "Timeout!"
        assert exc.seconds_inactive == 30.5
        assert isinstance(exc, WatchdogError)


class TestWatchdogThreadSafety:
    """Tests for thread safety."""

    def test_concurrent_pings(self) -> None:
        """Concurrent pings are thread-safe."""
        watchdog = Watchdog(timeout=30)
        errors: list[Exception] = []

        def worker() -> None:
            try:
                for _ in range(100):
                    watchdog.ping()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert watchdog.stats.pings_total == 1000


class TestWatchdogShutdown:
    """Tests for Watchdog shutdown functionality."""

    def test_shutdown_sets_flag(self) -> None:
        """shutdown sets the shutdown flag."""
        watchdog = Watchdog(timeout=30)
        assert not watchdog.is_shutdown
        watchdog.shutdown()
        assert watchdog.is_shutdown

    def test_shutdown_stops_watchdog(self) -> None:
        """shutdown stops the watchdog."""
        watchdog = Watchdog(timeout=30)
        watchdog.start()
        assert watchdog.is_running
        watchdog.shutdown()
        assert not watchdog.is_running

    @pytest.mark.asyncio
    async def test_ashutdown_sets_flag(self) -> None:
        """ashutdown sets the shutdown flag."""
        watchdog = Watchdog(timeout=30)
        assert not watchdog.is_shutdown
        await watchdog.ashutdown()
        assert watchdog.is_shutdown


class TestWatchdogFromStateFile:
    """Tests for Watchdog.from_state_file factory method."""

    def test_from_state_file_creates_watchdog(self, tmp_path: Path) -> None:
        """from_state_file creates a configured watchdog."""
        state_file = tmp_path / "heartbeat.json"
        wd = Watchdog.from_state_file(state_file, max_age=30.0)
        assert wd.state_file == state_file
        assert wd.name == f"state_file_watcher:{state_file}"

    def test_from_state_file_with_custom_name(self, tmp_path: Path) -> None:
        """from_state_file accepts custom name."""
        state_file = tmp_path / "heartbeat.json"
        wd = Watchdog.from_state_file(state_file, name="my-watcher")
        assert wd.name == "my-watcher"

    def test_from_state_file_default_interval(self, tmp_path: Path) -> None:
        """from_state_file uses max_age/2 as check interval by default."""
        state_file = tmp_path / "heartbeat.json"
        wd = Watchdog.from_state_file(state_file, max_age=30.0)
        assert wd.timeout == 15.0  # 30 / 2

    def test_from_state_file_custom_interval(self, tmp_path: Path) -> None:
        """from_state_file accepts custom check interval."""
        state_file = tmp_path / "heartbeat.json"
        wd = Watchdog.from_state_file(state_file, check_interval=10.0, max_age=30.0)
        assert wd.timeout == 10.0

    @pytest.mark.asyncio
    async def test_state_file_triggers_timeout_when_missing(self, tmp_path: Path) -> None:
        """Watchdog triggers timeout when state file is missing."""
        state_file = tmp_path / "nonexistent.json"
        callback_called = False

        def on_timeout() -> None:
            nonlocal callback_called
            callback_called = True

        wd = Watchdog.from_state_file(
            state_file,
            check_interval=0.1,
            max_age=0.5,
            on_timeout=on_timeout,
        )
        await wd.astart()
        await asyncio.sleep(0.3)  # Let it check
        await wd.astop()

        assert callback_called

    @pytest.mark.asyncio
    async def test_state_file_no_timeout_when_fresh(self, tmp_path: Path) -> None:
        """Watchdog does not trigger timeout when state file is fresh."""
        import json as json_module
        from datetime import datetime as dt
        from datetime import timezone as tz

        state_file = tmp_path / "heartbeat.json"
        # Write a fresh heartbeat
        state_file.write_text(
            json_module.dumps(
                {
                    "timestamp": dt.now(tz.utc).isoformat(),
                    "pid": 1234,
                    "hostname": "test",
                }
            )
        )

        callback_called = False

        def on_timeout() -> None:
            nonlocal callback_called
            callback_called = True

        wd = Watchdog.from_state_file(
            state_file,
            check_interval=0.1,
            max_age=10.0,
            on_timeout=on_timeout,
        )
        await wd.astart()
        await asyncio.sleep(0.3)
        await wd.astop()

        assert not callback_called


class TestWatchdogStateFileSync:
    """Tests for sync state file monitoring."""

    def test_sync_state_file_triggers_timeout(self, tmp_path: Path) -> None:
        """Sync watchdog triggers timeout when state file is missing."""
        state_file = tmp_path / "nonexistent.json"
        callback_called = False

        def on_timeout() -> None:
            nonlocal callback_called
            callback_called = True

        wd = Watchdog.from_state_file(
            state_file,
            check_interval=0.1,
            max_age=0.5,
            on_timeout=on_timeout,
        )
        wd.start()
        time.sleep(0.3)
        wd.stop()

        assert callback_called

    def test_sync_state_file_resets_on_fresh_file(self, tmp_path: Path) -> None:
        """Sync watchdog resets triggered state when file becomes fresh."""
        import json as json_module
        from datetime import datetime as dt
        from datetime import timezone as tz

        state_file = tmp_path / "heartbeat.json"
        timeout_count = 0

        def on_timeout() -> None:
            nonlocal timeout_count
            timeout_count += 1

        wd = Watchdog.from_state_file(
            state_file,
            check_interval=0.1,
            max_age=0.5,
            on_timeout=on_timeout,
        )
        wd.start()
        time.sleep(0.3)  # Should trigger timeout (file missing)

        # Now write a fresh heartbeat
        state_file.write_text(
            json_module.dumps(
                {
                    "timestamp": dt.now(tz.utc).isoformat(),
                    "pid": 1234,
                    "hostname": "test",
                }
            )
        )
        time.sleep(0.3)  # Should reset
        wd.stop()

        # Should have triggered once
        assert timeout_count == 1

    def test_sync_state_file_with_stale_file(self, tmp_path: Path) -> None:
        """Sync watchdog triggers timeout when state file is stale."""
        import json as json_module
        from datetime import datetime as dt
        from datetime import timedelta
        from datetime import timezone as tz

        state_file = tmp_path / "heartbeat.json"
        # Write a stale heartbeat (1 hour old)
        state_file.write_text(
            json_module.dumps(
                {
                    "timestamp": (dt.now(tz.utc) - timedelta(hours=1)).isoformat(),
                    "pid": 1234,
                    "hostname": "test",
                }
            )
        )

        callback_called = False

        def on_timeout() -> None:
            nonlocal callback_called
            callback_called = True

        wd = Watchdog.from_state_file(
            state_file,
            check_interval=0.1,
            max_age=0.5,
            on_timeout=on_timeout,
        )
        wd.start()
        time.sleep(0.3)
        wd.stop()

        assert callback_called


class TestWatchdogAsyncCallback:
    """Tests for async callback handling in watchdog."""

    @pytest.mark.asyncio
    async def test_async_callback_in_async_context(self, tmp_path: Path) -> None:
        """Async callback is awaited in async context."""
        state_file = tmp_path / "nonexistent.json"
        callback_called = False

        async def async_on_timeout() -> None:
            nonlocal callback_called
            await asyncio.sleep(0.01)
            callback_called = True

        wd = Watchdog.from_state_file(
            state_file,
            check_interval=0.1,
            max_age=0.5,
            on_timeout=async_on_timeout,
        )
        await wd.astart()
        await asyncio.sleep(0.3)
        await wd.astop()

        assert callback_called


class TestWatchdogConfigFallback:
    """Tests for config fallback behavior."""

    def test_fallback_when_config_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Use default timeout when config raises exception."""
        import kstlib.resilience.watchdog as watchdog_module

        def raise_error() -> None:
            raise RuntimeError("Config not available")

        monkeypatch.setattr(watchdog_module, "get_resilience_limits", raise_error)

        # Should not raise, should use default
        wd = Watchdog(timeout=None)
        assert wd.timeout == watchdog_module.DEFAULT_WATCHDOG_TIMEOUT


class TestWatchdogStateFileEdgeCases:
    """Tests for state file edge cases."""

    def test_state_file_invalid_json(self, tmp_path: Path) -> None:
        """Handle invalid JSON in state file."""
        state_file = tmp_path / "heartbeat.json"
        state_file.write_text("not valid json")

        callback_called = False

        def on_timeout() -> None:
            nonlocal callback_called
            callback_called = True

        wd = Watchdog.from_state_file(
            state_file,
            check_interval=0.1,
            max_age=0.5,
            on_timeout=on_timeout,
        )
        wd.start()
        time.sleep(0.3)
        wd.stop()

        # Should trigger timeout (invalid file = not alive)
        assert callback_called

    def test_state_file_missing_timestamp(self, tmp_path: Path) -> None:
        """Handle missing timestamp in state file."""
        import json as json_module

        state_file = tmp_path / "heartbeat.json"
        state_file.write_text(json_module.dumps({"pid": 1234}))

        callback_called = False

        def on_timeout() -> None:
            nonlocal callback_called
            callback_called = True

        wd = Watchdog.from_state_file(
            state_file,
            check_interval=0.1,
            max_age=0.5,
            on_timeout=on_timeout,
        )
        wd.start()
        time.sleep(0.3)
        wd.stop()

        # Should trigger timeout (no timestamp = not alive)
        assert callback_called


# Import Path for type hints in tests
from pathlib import Path
