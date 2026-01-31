"""Tests for the Heartbeat class."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from kstlib.resilience.exceptions import HeartbeatError
from kstlib.resilience.heartbeat import Heartbeat, HeartbeatState

if TYPE_CHECKING:
    pass


class TestHeartbeatState:
    """Tests for HeartbeatState dataclass."""

    def test_create_state(self) -> None:
        """Create a heartbeat state with required fields."""
        state = HeartbeatState(
            timestamp="2026-01-12T10:00:00+00:00",
            pid=1234,
            hostname="myhost",
        )
        assert state.timestamp == "2026-01-12T10:00:00+00:00"
        assert state.pid == 1234
        assert state.hostname == "myhost"
        assert state.metadata == {}

    def test_create_state_with_metadata(self) -> None:
        """Create a heartbeat state with custom metadata."""
        state = HeartbeatState(
            timestamp="2026-01-12T10:00:00+00:00",
            pid=1234,
            hostname="myhost",
            metadata={"version": "1.0", "active": True},
        )
        assert state.metadata == {"version": "1.0", "active": True}

    def test_to_dict(self) -> None:
        """Serialize state to dictionary."""
        state = HeartbeatState(
            timestamp="2026-01-12T10:00:00+00:00",
            pid=1234,
            hostname="myhost",
            metadata={"key": "value"},
        )
        result = state.to_dict()
        assert result == {
            "timestamp": "2026-01-12T10:00:00+00:00",
            "pid": 1234,
            "hostname": "myhost",
            "metadata": {"key": "value"},
        }

    def test_from_dict(self) -> None:
        """Deserialize state from dictionary."""
        data = {
            "timestamp": "2026-01-12T10:00:00+00:00",
            "pid": 5678,
            "hostname": "otherhost",
            "metadata": {"status": "ok"},
        }
        state = HeartbeatState.from_dict(data)
        assert state.timestamp == "2026-01-12T10:00:00+00:00"
        assert state.pid == 5678
        assert state.hostname == "otherhost"
        assert state.metadata == {"status": "ok"}

    def test_from_dict_missing_metadata(self) -> None:
        """Deserialize state without optional metadata field."""
        data = {
            "timestamp": "2026-01-12T10:00:00+00:00",
            "pid": 1234,
            "hostname": "myhost",
        }
        state = HeartbeatState.from_dict(data)
        assert state.metadata == {}

    def test_from_dict_missing_required_field(self) -> None:
        """Raise KeyError when required field is missing."""
        data = {"timestamp": "2026-01-12T10:00:00+00:00", "pid": 1234}
        with pytest.raises(KeyError):
            HeartbeatState.from_dict(data)


class TestHeartbeatInit:
    """Tests for Heartbeat initialization."""

    def test_default_interval_from_config(self, heartbeat_file: Path) -> None:
        """Use default interval from config when not specified."""
        hb = Heartbeat(heartbeat_file)
        assert hb.interval == 10  # Default from config

    def test_custom_interval(self, heartbeat_file: Path) -> None:
        """Accept custom interval parameter."""
        hb = Heartbeat(heartbeat_file, interval=5.0)
        assert hb.interval == 5.0

    def test_interval_clamped_to_minimum(self, heartbeat_file: Path) -> None:
        """Clamp interval to hard minimum."""
        hb = Heartbeat(heartbeat_file, interval=0.1)
        assert hb.interval == 1  # Hard minimum

    def test_interval_clamped_to_maximum(self, heartbeat_file: Path) -> None:
        """Clamp interval to hard maximum."""
        hb = Heartbeat(heartbeat_file, interval=1000)
        assert hb.interval == 300  # Hard maximum

    def test_state_file_property(self, heartbeat_file: Path) -> None:
        """Access state file path via property."""
        hb = Heartbeat(heartbeat_file)
        assert hb.state_file == heartbeat_file

    def test_state_file_from_string(self, tmp_path: Path) -> None:
        """Accept state file as string path."""
        path_str = str(tmp_path / "hb.json")
        hb = Heartbeat(path_str)
        assert hb.state_file == Path(path_str)


class TestHeartbeatBeat:
    """Tests for the beat() method."""

    def test_beat_writes_state_file(self, heartbeat_file: Path) -> None:
        """Write valid JSON state file on beat."""
        hb = Heartbeat(heartbeat_file)
        hb.beat()

        assert heartbeat_file.exists()
        data = json.loads(heartbeat_file.read_text())
        assert "timestamp" in data
        assert "pid" in data
        assert "hostname" in data
        assert "metadata" in data

    def test_beat_creates_parent_directory(self, tmp_path: Path) -> None:
        """Create parent directory if it does not exist."""
        nested_file = tmp_path / "subdir" / "deep" / "heartbeat.json"
        hb = Heartbeat(nested_file)
        hb.beat()

        assert nested_file.exists()

    def test_beat_with_metadata(self, heartbeat_file: Path) -> None:
        """Include custom metadata in heartbeat."""
        hb = Heartbeat(heartbeat_file, metadata={"version": "1.0"})
        hb.beat()

        data = json.loads(heartbeat_file.read_text())
        assert data["metadata"] == {"version": "1.0"}

    def test_beat_raises_on_write_error(self, tmp_path: Path) -> None:
        """Raise HeartbeatError when state file cannot be written."""
        # Use a directory as the file path (will fail to write)
        dir_path = tmp_path / "directory"
        dir_path.mkdir()
        hb = Heartbeat(dir_path)

        with pytest.raises(HeartbeatError, match="Failed to write heartbeat"):
            hb.beat()


class TestHeartbeatStartStop:
    """Tests for start() and stop() methods."""

    def test_start_creates_thread(self, heartbeat_file: Path) -> None:
        """Start creates a background thread."""
        hb = Heartbeat(heartbeat_file, interval=1)
        hb.start()
        try:
            assert hb._running is True
            assert hb._thread is not None
            assert hb._thread.is_alive()
        finally:
            hb.stop()

    def test_start_raises_if_already_running(self, heartbeat_file: Path) -> None:
        """Raise HeartbeatError if starting twice."""
        hb = Heartbeat(heartbeat_file, interval=1)
        hb.start()
        try:
            with pytest.raises(HeartbeatError, match="already running"):
                hb.start()
        finally:
            hb.stop()

    def test_stop_halts_thread(self, heartbeat_file: Path) -> None:
        """Stop halts the background thread."""
        hb = Heartbeat(heartbeat_file, interval=1)
        hb.start()
        hb.stop()

        assert hb._running is False
        assert hb._thread is None

    def test_stop_when_not_started(self, heartbeat_file: Path) -> None:
        """Stop is safe to call when not started."""
        hb = Heartbeat(heartbeat_file)
        hb.stop()  # Should not raise
        assert hb._running is False

    def test_stop_multiple_times(self, heartbeat_file: Path) -> None:
        """Stop is safe to call multiple times."""
        hb = Heartbeat(heartbeat_file, interval=1)
        hb.start()
        hb.stop()
        hb.stop()  # Should not raise
        assert hb._running is False


class TestHeartbeatContextManager:
    """Tests for sync context manager."""

    def test_context_manager_starts_and_stops(self, heartbeat_file: Path) -> None:
        """Context manager starts on enter and stops on exit."""
        with Heartbeat(heartbeat_file, interval=1) as hb:
            assert hb._running is True
        assert hb._running is False

    def test_context_manager_stops_on_exception(self, heartbeat_file: Path) -> None:
        """Context manager stops even when exception is raised."""
        try:
            with Heartbeat(heartbeat_file, interval=1) as hb:
                assert hb._running is True
                raise ValueError("Test error")
        except ValueError:
            pass
        assert hb._running is False


class TestHeartbeatOnMissedBeat:
    """Tests for on_missed_beat callback."""

    def test_on_missed_beat_called_on_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Call on_missed_beat when beat fails."""
        callback = MagicMock()
        dir_path = tmp_path / "directory"
        dir_path.mkdir()
        hb = Heartbeat(dir_path, on_missed_beat=callback, interval=1)

        # Simulate one iteration of the loop
        hb._run_loop = lambda: None  # Override to prevent loop
        try:
            hb.beat()
        except HeartbeatError as exc:
            if hb._on_missed_beat:
                hb._on_missed_beat(exc)

        callback.assert_called_once()

    def test_on_missed_beat_exception_ignored(self, tmp_path: Path) -> None:
        """Ignore exceptions raised by on_missed_beat callback."""

        def bad_callback(exc: Exception) -> None:
            raise RuntimeError("Callback error")

        dir_path = tmp_path / "directory"
        dir_path.mkdir()
        hb = Heartbeat(dir_path, on_missed_beat=bad_callback, interval=0.1)

        call_count = 0

        def failing_beat() -> None:
            nonlocal call_count
            call_count += 1
            hb._stop_event.set()  # Stop after first iteration
            raise HeartbeatError("Test")

        # Patch beat to fail and stop after first iteration
        with patch.object(hb, "beat", side_effect=failing_beat):
            hb._run_loop()  # Should not raise despite callback error

        assert call_count == 1


class TestHeartbeatReadState:
    """Tests for read_state() static method."""

    def test_read_existing_state(self, heartbeat_file: Path) -> None:
        """Read valid heartbeat state file."""
        hb = Heartbeat(heartbeat_file)
        hb.beat()

        state = Heartbeat.read_state(heartbeat_file)
        assert state is not None
        assert isinstance(state, HeartbeatState)
        assert state.pid > 0

    def test_read_nonexistent_file(self, tmp_path: Path) -> None:
        """Return None for nonexistent file."""
        state = Heartbeat.read_state(tmp_path / "nonexistent.json")
        assert state is None

    def test_read_invalid_json(self, heartbeat_file: Path) -> None:
        """Return None for invalid JSON."""
        heartbeat_file.write_text("not valid json")
        state = Heartbeat.read_state(heartbeat_file)
        assert state is None

    def test_read_missing_fields(self, heartbeat_file: Path) -> None:
        """Return None for JSON with missing required fields."""
        heartbeat_file.write_text('{"timestamp": "2026-01-12T10:00:00+00:00"}')
        state = Heartbeat.read_state(heartbeat_file)
        assert state is None


class TestHeartbeatIsAlive:
    """Tests for is_alive() static method."""

    def test_is_alive_recent_heartbeat(self, heartbeat_file: Path) -> None:
        """Return True for recent heartbeat."""
        hb = Heartbeat(heartbeat_file)
        hb.beat()

        assert Heartbeat.is_alive(heartbeat_file, max_age_seconds=30) is True

    def test_is_alive_stale_heartbeat(self, heartbeat_file: Path) -> None:
        """Return False for stale heartbeat."""
        # Write a heartbeat with old timestamp
        old_time = datetime(2020, 1, 1, tzinfo=timezone.utc)
        state = HeartbeatState(
            timestamp=old_time.isoformat(),
            pid=1234,
            hostname="myhost",
        )
        heartbeat_file.write_text(json.dumps(state.to_dict()))

        assert Heartbeat.is_alive(heartbeat_file, max_age_seconds=30) is False

    def test_is_alive_nonexistent_file(self, tmp_path: Path) -> None:
        """Return False for nonexistent file."""
        assert Heartbeat.is_alive(tmp_path / "missing.json") is False

    def test_is_alive_invalid_timestamp(self, heartbeat_file: Path) -> None:
        """Return False for invalid timestamp format."""
        heartbeat_file.write_text('{"timestamp": "not-a-date", "pid": 1234, "hostname": "test"}')
        assert Heartbeat.is_alive(heartbeat_file) is False


class TestHeartbeatAsync:
    """Tests for async context manager and methods."""

    @pytest.mark.asyncio
    async def test_async_context_manager(self, heartbeat_file: Path) -> None:
        """Async context manager starts and stops heartbeat."""
        async with Heartbeat(heartbeat_file, interval=1) as hb:
            assert hb._running is True
            assert hb._async_task is not None
        assert hb._running is False
        assert hb._async_task is None

    @pytest.mark.asyncio
    async def test_astart_raises_if_already_running(self, heartbeat_file: Path) -> None:
        """Raise HeartbeatError if astart called twice."""
        hb = Heartbeat(heartbeat_file, interval=1)
        await hb.astart()
        try:
            with pytest.raises(HeartbeatError, match="already running"):
                await hb.astart()
        finally:
            await hb.astop()

    @pytest.mark.asyncio
    async def test_astop_when_not_started(self, heartbeat_file: Path) -> None:
        """astop is safe to call when not started."""
        hb = Heartbeat(heartbeat_file)
        await hb.astop()  # Should not raise

    @pytest.mark.asyncio
    async def test_async_writes_heartbeat(self, heartbeat_file: Path) -> None:
        """Async heartbeat writes state file."""
        async with Heartbeat(heartbeat_file, interval=0.1):
            # Wait a bit for at least one beat
            await asyncio.sleep(0.2)

        assert heartbeat_file.exists()

    @pytest.mark.asyncio
    async def test_async_on_missed_beat(self, tmp_path: Path) -> None:
        """Call on_missed_beat in async mode."""
        callback = MagicMock()
        dir_path = tmp_path / "directory"
        dir_path.mkdir()

        hb = Heartbeat(dir_path, on_missed_beat=callback, interval=0.1)
        await hb.astart()
        await asyncio.sleep(0.2)  # Let it try to beat
        await hb.astop()

        # Callback should have been called due to write error
        assert callback.call_count >= 1

    @pytest.mark.asyncio
    async def test_async_on_missed_beat_exception_ignored(self, tmp_path: Path) -> None:
        """Ignore exceptions from on_missed_beat in async mode."""

        def bad_callback(exc: Exception) -> None:
            raise RuntimeError("Callback error")

        dir_path = tmp_path / "directory"
        dir_path.mkdir()

        hb = Heartbeat(dir_path, on_missed_beat=bad_callback, interval=0.1)
        await hb.astart()
        await asyncio.sleep(0.2)
        await hb.astop()  # Should not raise


class TestHeartbeatShutdown:
    """Tests for Heartbeat shutdown functionality."""

    def test_shutdown_sets_flag(self, heartbeat_file: Path) -> None:
        """shutdown sets the shutdown flag."""
        hb = Heartbeat(heartbeat_file)
        assert not hb.is_shutdown
        hb.shutdown()
        assert hb.is_shutdown

    def test_shutdown_stops_heartbeat(self, heartbeat_file: Path) -> None:
        """shutdown stops the heartbeat."""
        hb = Heartbeat(heartbeat_file, interval=0.1)
        hb.start()
        assert hb._running
        hb.shutdown()
        assert not hb._running

    @pytest.mark.asyncio
    async def test_ashutdown_sets_flag(self, heartbeat_file: Path) -> None:
        """ashutdown sets the shutdown flag."""
        hb = Heartbeat(heartbeat_file)
        assert not hb.is_shutdown
        await hb.ashutdown()
        assert hb.is_shutdown


class TestHeartbeatTarget:
    """Tests for Heartbeat target monitoring."""

    def test_target_property_returns_target(self, heartbeat_file: Path) -> None:
        """target property returns the monitored target."""

        class MockTarget:
            @property
            def is_dead(self) -> bool:
                return False

        target = MockTarget()
        hb = Heartbeat(heartbeat_file, target=target)
        assert hb.target is target

    def test_target_property_returns_none_when_not_set(self, heartbeat_file: Path) -> None:
        """target property returns None when not set."""
        hb = Heartbeat(heartbeat_file)
        assert hb.target is None

    @pytest.mark.asyncio
    async def test_on_target_dead_called_when_target_dead(self, heartbeat_file: Path) -> None:
        """on_target_dead callback is invoked when target is dead."""

        class DeadTarget:
            @property
            def is_dead(self) -> bool:
                return True

        callback_called = False

        async def on_dead() -> None:
            nonlocal callback_called
            callback_called = True

        hb = Heartbeat(
            heartbeat_file,
            interval=0.1,
            target=DeadTarget(),
            on_target_dead=on_dead,
        )
        await hb.astart()
        await asyncio.sleep(0.2)  # Let it detect dead target
        await hb.astop()

        assert callback_called

    @pytest.mark.asyncio
    async def test_on_target_dead_not_called_when_target_alive(self, heartbeat_file: Path) -> None:
        """on_target_dead callback is NOT invoked when target is alive."""

        class AliveTarget:
            @property
            def is_dead(self) -> bool:
                return False

        callback_called = False

        async def on_dead() -> None:
            nonlocal callback_called
            callback_called = True

        hb = Heartbeat(
            heartbeat_file,
            interval=0.1,
            target=AliveTarget(),
            on_target_dead=on_dead,
        )
        await hb.astart()
        await asyncio.sleep(0.2)
        await hb.astop()

        assert not callback_called


class TestHeartbeatOnAlert:
    """Tests for Heartbeat on_alert callback."""

    @pytest.mark.asyncio
    async def test_on_alert_called_when_target_dead(self, heartbeat_file: Path) -> None:
        """on_alert is invoked when target is detected as dead."""

        class DeadTarget:
            @property
            def is_dead(self) -> bool:
                return True

        alert_channel = None
        alert_message = None

        async def on_alert(channel: str, message: str, context: dict) -> None:
            nonlocal alert_channel, alert_message
            alert_channel = channel
            alert_message = message

        hb = Heartbeat(
            heartbeat_file,
            interval=0.1,
            target=DeadTarget(),
            on_alert=on_alert,
        )
        await hb.astart()
        await asyncio.sleep(0.2)
        await hb.astop()

        assert alert_channel == "heartbeat"
        assert "dead" in alert_message.lower()


class TestHeartbeatOnBeat:
    """Tests for on_beat callback."""

    @pytest.mark.asyncio
    async def test_on_beat_called_after_beat(self, heartbeat_file: Path) -> None:
        """on_beat callback is invoked after each successful beat."""
        beat_count = 0

        def on_beat() -> None:
            nonlocal beat_count
            beat_count += 1

        hb = Heartbeat(heartbeat_file, interval=0.1, on_beat=on_beat)
        await hb.astart()
        await asyncio.sleep(0.15)  # Let at least one beat happen
        await hb.astop()

        assert beat_count >= 1

    @pytest.mark.asyncio
    async def test_on_beat_async_callback(self, heartbeat_file: Path) -> None:
        """on_beat works with async callbacks."""
        beat_count = 0

        async def on_beat_async() -> None:
            nonlocal beat_count
            beat_count += 1

        hb = Heartbeat(heartbeat_file, interval=0.1, on_beat=on_beat_async)
        await hb.astart()
        await asyncio.sleep(0.15)
        await hb.astop()

        assert beat_count >= 1

    @pytest.mark.asyncio
    async def test_on_beat_exception_ignored(self, heartbeat_file: Path) -> None:
        """Exceptions from on_beat callback are suppressed."""

        def bad_on_beat() -> None:
            raise RuntimeError("on_beat error")

        hb = Heartbeat(heartbeat_file, interval=0.1, on_beat=bad_on_beat)
        await hb.astart()
        await asyncio.sleep(0.2)
        await hb.astop()  # Should not raise


class TestHeartbeatNoStateFile:
    """Tests for Heartbeat without state_file (using on_beat callback only)."""

    def test_state_file_none_allowed(self) -> None:
        """Heartbeat can be created without state_file."""
        hb = Heartbeat(state_file=None, interval=1.0)
        assert hb.state_file is None

    def test_beat_skips_file_write_when_no_state_file(self) -> None:
        """beat() does nothing when state_file is None."""
        hb = Heartbeat(state_file=None, interval=1.0)
        hb.beat()  # Should not raise

    @pytest.mark.asyncio
    async def test_heartbeat_works_with_on_beat_only(self) -> None:
        """Heartbeat works with on_beat callback and no state_file."""
        beat_count = 0

        def on_beat() -> None:
            nonlocal beat_count
            beat_count += 1

        hb = Heartbeat(state_file=None, interval=0.1, on_beat=on_beat)
        await hb.astart()
        await asyncio.sleep(0.15)
        await hb.astop()

        assert beat_count >= 1
