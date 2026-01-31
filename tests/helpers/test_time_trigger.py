"""Tests for kstlib.helpers.time_trigger module."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pendulum
import pytest

from kstlib.helpers import InvalidModuloError, TimeTrigger, TimeTriggerError
from kstlib.helpers.time_trigger import (
    HARD_MAX_MODULO_SECONDS,
    HARD_MIN_MODULO_SECONDS,
    TimeTriggerStats,
    _parse_modulo,
)

if TYPE_CHECKING:
    pass


class TestParseModulo:
    """Tests for _parse_modulo function."""

    def test_parse_minutes(self) -> None:
        """Parse minute-based modulo strings."""
        assert _parse_modulo("30m") == 1800
        assert _parse_modulo("1m") == 60
        assert _parse_modulo("60m") == 3600

    def test_parse_hours(self) -> None:
        """Parse hour-based modulo strings."""
        assert _parse_modulo("1h") == 3600
        assert _parse_modulo("4h") == 14400
        assert _parse_modulo("8h") == 28800
        assert _parse_modulo("24h") == 86400

    def test_parse_days(self) -> None:
        """Parse day-based modulo strings."""
        assert _parse_modulo("1d") == 86400
        assert _parse_modulo("7d") == 604800

    def test_parse_seconds(self) -> None:
        """Parse second-based modulo strings."""
        assert _parse_modulo("60s") == 60
        assert _parse_modulo("120s") == 120

    def test_parse_case_insensitive(self) -> None:
        """Parse is case insensitive."""
        assert _parse_modulo("4H") == 14400
        assert _parse_modulo("30M") == 1800
        assert _parse_modulo("1D") == 86400

    def test_parse_with_whitespace(self) -> None:
        """Parse handles leading/trailing whitespace."""
        assert _parse_modulo("  4h  ") == 14400
        assert _parse_modulo("30m ") == 1800

    def test_parse_invalid_format(self) -> None:
        """Raise error for invalid format."""
        with pytest.raises(InvalidModuloError, match="Invalid modulo format"):
            _parse_modulo("invalid")

        with pytest.raises(InvalidModuloError, match="Invalid modulo format"):
            _parse_modulo("4x")

        with pytest.raises(InvalidModuloError, match="Invalid modulo format"):
            _parse_modulo("")

        with pytest.raises(InvalidModuloError, match="Invalid modulo format"):
            _parse_modulo("h4")

    def test_parse_too_small(self) -> None:
        """Raise error if modulo is below minimum."""
        with pytest.raises(InvalidModuloError, match="Modulo too small"):
            _parse_modulo("30s")  # 30 seconds < 60 minimum

        with pytest.raises(InvalidModuloError, match="Modulo too small"):
            _parse_modulo("1s")

    def test_parse_too_large(self) -> None:
        """Raise error if modulo exceeds maximum."""
        with pytest.raises(InvalidModuloError, match="Modulo too large"):
            _parse_modulo("8d")  # 8 days > 7 days maximum


class TestTimeTriggerStats:
    """Tests for TimeTriggerStats dataclass."""

    def test_initial_values(self) -> None:
        """Stats start at zero."""
        stats = TimeTriggerStats()
        assert stats.triggers_fired == 0
        assert stats.callbacks_invoked == 0
        assert stats.last_trigger_at is None

    def test_record_trigger(self) -> None:
        """Record trigger increments counter and sets timestamp."""
        stats = TimeTriggerStats()
        stats.record_trigger()
        assert stats.triggers_fired == 1
        assert stats.last_trigger_at is not None
        assert "T" in stats.last_trigger_at  # ISO format

    def test_record_callback(self) -> None:
        """Record callback increments counter."""
        stats = TimeTriggerStats()
        stats.record_callback()
        assert stats.callbacks_invoked == 1


class TestTimeTriggerInit:
    """Tests for TimeTrigger initialization."""

    def test_basic_init(self) -> None:
        """Create trigger with basic parameters."""
        trigger = TimeTrigger("4h")
        assert trigger.modulo == "4h"
        assert trigger.modulo_seconds == 14400
        assert trigger.timezone == "UTC"

    def test_init_with_timezone(self) -> None:
        """Create trigger with custom timezone."""
        trigger = TimeTrigger("4h", timezone="Europe/Paris")
        assert trigger.timezone == "Europe/Paris"

    def test_init_invalid_modulo(self) -> None:
        """Raise error for invalid modulo."""
        with pytest.raises(InvalidModuloError):
            TimeTrigger("invalid")

    def test_stats_accessible(self) -> None:
        """Stats property is accessible."""
        trigger = TimeTrigger("4h")
        assert isinstance(trigger.stats, TimeTriggerStats)

    def test_repr(self) -> None:
        """String representation is informative."""
        trigger = TimeTrigger("4h", timezone="UTC")
        assert "TimeTrigger" in repr(trigger)
        assert "4h" in repr(trigger)
        assert "UTC" in repr(trigger)


class TestTimeTriggerBoundaries:
    """Tests for boundary detection methods."""

    def test_time_until_next_at_boundary(self) -> None:
        """Time until next is 0 at exact boundary."""
        # Mock time at exactly 00:00:00 UTC (timestamp divisible by 4h)
        mock_time = pendulum.datetime(2024, 1, 15, 0, 0, 0, tz="UTC")
        with patch.object(pendulum, "now", return_value=mock_time):
            trigger = TimeTrigger("4h")
            assert trigger.time_until_next() == 0.0

    def test_time_until_next_between_boundaries(self) -> None:
        """Time until next is calculated correctly between boundaries."""
        # Mock time at 01:30:00 UTC (5400 seconds into 4h period)
        mock_time = pendulum.datetime(2024, 1, 15, 1, 30, 0, tz="UTC")
        with patch.object(pendulum, "now", return_value=mock_time):
            trigger = TimeTrigger("4h")
            # 4h = 14400s, 1h30m = 5400s, remaining = 14400 - 5400 = 9000s
            assert trigger.time_until_next() == 9000.0

    def test_is_at_boundary_exact(self) -> None:
        """Detect exact boundary."""
        mock_time = pendulum.datetime(2024, 1, 15, 4, 0, 0, tz="UTC")
        with patch.object(pendulum, "now", return_value=mock_time):
            trigger = TimeTrigger("4h")
            assert trigger.is_at_boundary() is True

    def test_is_at_boundary_with_margin(self) -> None:
        """Detect boundary within margin."""
        # 2 seconds before 04:00:00
        mock_time = pendulum.datetime(2024, 1, 15, 3, 59, 58, tz="UTC")
        with patch.object(pendulum, "now", return_value=mock_time):
            trigger = TimeTrigger("4h")
            assert trigger.is_at_boundary(margin=1.0) is False
            assert trigger.is_at_boundary(margin=3.0) is True

    def test_is_at_boundary_just_after(self) -> None:
        """Detect boundary just after it passed."""
        # 0.5 seconds after 04:00:00
        mock_time = pendulum.datetime(2024, 1, 15, 4, 0, 0, tz="UTC").add(microseconds=500000)
        with patch.object(pendulum, "now", return_value=mock_time):
            trigger = TimeTrigger("4h")
            assert trigger.is_at_boundary(margin=1.0) is True

    def test_is_at_boundary_not_at_boundary(self) -> None:
        """Not at boundary in the middle of period."""
        mock_time = pendulum.datetime(2024, 1, 15, 2, 0, 0, tz="UTC")
        with patch.object(pendulum, "now", return_value=mock_time):
            trigger = TimeTrigger("4h")
            assert trigger.is_at_boundary() is False

    def test_should_trigger_approaching(self) -> None:
        """Should trigger when boundary is approaching."""
        # 20 seconds before 04:00:00
        mock_time = pendulum.datetime(2024, 1, 15, 3, 59, 40, tz="UTC")
        with patch.object(pendulum, "now", return_value=mock_time):
            trigger = TimeTrigger("4h")
            assert trigger.should_trigger(margin=30.0) is True
            assert trigger.should_trigger(margin=10.0) is False

    def test_should_trigger_far_from_boundary(self) -> None:
        """Should not trigger far from boundary."""
        mock_time = pendulum.datetime(2024, 1, 15, 2, 0, 0, tz="UTC")
        with patch.object(pendulum, "now", return_value=mock_time):
            trigger = TimeTrigger("4h")
            assert trigger.should_trigger(margin=30.0) is False


class TestTimeTriggerDatetimes:
    """Tests for boundary datetime methods."""

    def test_next_boundary(self) -> None:
        """Get next boundary datetime."""
        mock_time = pendulum.datetime(2024, 1, 15, 1, 30, 0, tz="UTC")
        with patch.object(pendulum, "now", return_value=mock_time):
            trigger = TimeTrigger("4h")
            next_dt = trigger.next_boundary()
            assert next_dt.hour == 4
            assert next_dt.minute == 0
            assert next_dt.second == 0

    def test_previous_boundary(self) -> None:
        """Get previous boundary datetime."""
        mock_time = pendulum.datetime(2024, 1, 15, 5, 30, 0, tz="UTC")
        with patch.object(pendulum, "now", return_value=mock_time):
            trigger = TimeTrigger("4h")
            prev_dt = trigger.previous_boundary()
            assert prev_dt.hour == 4
            assert prev_dt.minute == 0
            assert prev_dt.second == 0

    def test_next_boundary_at_exact_boundary(self) -> None:
        """Next boundary at exact boundary is current time."""
        mock_time = pendulum.datetime(2024, 1, 15, 4, 0, 0, tz="UTC")
        with patch.object(pendulum, "now", return_value=mock_time):
            trigger = TimeTrigger("4h")
            next_dt = trigger.next_boundary()
            # At exact boundary, time_until_next is 0, so next is now
            assert next_dt.hour == 4


class TestTimeTriggerAsync:
    """Tests for async methods."""

    @pytest.mark.asyncio
    async def test_wait_for_boundary(self) -> None:
        """Wait for boundary with mocked sleep."""
        trigger = TimeTrigger("4h")

        # Mock to return 5 seconds until boundary
        with patch.object(trigger, "time_until_next", return_value=5.0):
            with patch("asyncio.sleep", new_callable=MagicMock) as mock_sleep:
                mock_sleep.return_value = asyncio.Future()
                mock_sleep.return_value.set_result(None)

                await trigger.wait_for_boundary()

                mock_sleep.assert_called_once_with(5.0)
                assert trigger.stats.triggers_fired == 1

    @pytest.mark.asyncio
    async def test_wait_for_boundary_with_margin(self) -> None:
        """Wait for boundary minus margin."""
        trigger = TimeTrigger("4h")

        with patch.object(trigger, "time_until_next", return_value=30.0):
            with patch("asyncio.sleep", new_callable=MagicMock) as mock_sleep:
                mock_sleep.return_value = asyncio.Future()
                mock_sleep.return_value.set_result(None)

                await trigger.wait_for_boundary(margin=10.0)

                # Should sleep 30 - 10 = 20 seconds
                mock_sleep.assert_called_once_with(20.0)

    @pytest.mark.asyncio
    async def test_wait_for_boundary_no_wait_needed(self) -> None:
        """No sleep if already at boundary."""
        trigger = TimeTrigger("4h")

        with patch.object(trigger, "time_until_next", return_value=0.0):
            with patch("asyncio.sleep", new_callable=MagicMock) as mock_sleep:
                await trigger.wait_for_boundary()
                mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_on_boundary_with_stop(self) -> None:
        """Run on boundary loop stops when stop() called."""
        trigger = TimeTrigger("4h")
        callback_count = 0

        async def callback() -> None:
            nonlocal callback_count
            callback_count += 1
            # Stop after first callback
            trigger.stop()

        with patch.object(trigger, "time_until_next", return_value=0.001):
            await trigger.run_on_boundary(callback)

        assert callback_count == 1
        assert trigger.stats.callbacks_invoked == 1

    @pytest.mark.asyncio
    async def test_run_on_boundary_run_immediately(self) -> None:
        """Run immediately option invokes callback before first wait."""
        trigger = TimeTrigger("4h")
        callback_count = 0

        def sync_callback() -> None:
            nonlocal callback_count
            callback_count += 1
            if callback_count >= 1:
                trigger.stop()

        with patch.object(trigger, "time_until_next", return_value=0.001):
            await trigger.run_on_boundary(sync_callback, run_immediately=True)

        assert callback_count >= 1

    @pytest.mark.asyncio
    async def test_run_on_boundary_sync_callback(self) -> None:
        """Support synchronous callbacks."""
        trigger = TimeTrigger("4h")
        called = False

        def sync_callback() -> None:
            nonlocal called
            called = True
            trigger.stop()

        with patch.object(trigger, "time_until_next", return_value=0.001):
            await trigger.run_on_boundary(sync_callback)

        assert called

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Async context manager stops on exit."""
        async with TimeTrigger("4h") as trigger:
            assert trigger.modulo == "4h"
        # No assertion needed - just verify no exception


class TestTimeTriggerStop:
    """Tests for stop functionality."""

    def test_stop_sets_flags(self) -> None:
        """Stop sets running flag to False."""
        trigger = TimeTrigger("4h")
        trigger._running = True
        trigger.stop()
        assert trigger._running is False

    def test_stop_cancels_task(self) -> None:
        """Stop cancels async task if running."""
        trigger = TimeTrigger("4h")
        mock_task = MagicMock()
        mock_task.done.return_value = False
        trigger._async_task = mock_task

        trigger.stop()

        mock_task.cancel.assert_called_once()


class TestExceptionHierarchy:
    """Tests for exception hierarchy."""

    def test_invalid_modulo_is_time_trigger_error(self) -> None:
        """InvalidModuloError inherits from TimeTriggerError."""
        assert issubclass(InvalidModuloError, TimeTriggerError)

    def test_time_trigger_error_is_exception(self) -> None:
        """TimeTriggerError inherits from Exception."""
        assert issubclass(TimeTriggerError, Exception)


class TestHardLimits:
    """Tests for hard limit constants."""

    def test_min_modulo_is_one_minute(self) -> None:
        """Minimum modulo is 60 seconds."""
        assert HARD_MIN_MODULO_SECONDS == 60

    def test_max_modulo_is_one_week(self) -> None:
        """Maximum modulo is 7 days."""
        assert HARD_MAX_MODULO_SECONDS == 86400 * 7
