"""Tests for kstlib.alerts.throttle module."""

import pytest

from kstlib.alerts.exceptions import AlertThrottledError
from kstlib.alerts.throttle import AlertThrottle
from kstlib.limits import (
    HARD_MAX_THROTTLE_PER,
    HARD_MAX_THROTTLE_RATE,
    HARD_MIN_THROTTLE_PER,
    HARD_MIN_THROTTLE_RATE,
)


class TestAlertThrottleInit:
    """Tests for AlertThrottle initialization."""

    def test_basic_init(self) -> None:
        """AlertThrottle should initialize with rate and per."""
        throttle = AlertThrottle(rate=10, per=60.0)
        assert throttle.rate == 10.0
        assert throttle.per == 60.0

    def test_default_from_config(self) -> None:
        """AlertThrottle should use config defaults when no args provided."""
        throttle = AlertThrottle()
        # Default from config is rate=10, per=60.0
        assert throttle.rate == 10.0
        assert throttle.per == 60.0

    def test_burst(self) -> None:
        """AlertThrottle should accept burst parameter."""
        throttle = AlertThrottle(rate=10, per=60.0, burst=5)
        # Use approx due to token refill timing between creation and read
        assert throttle.available == pytest.approx(5.0, abs=0.01)

    def test_rate_clamped_to_minimum(self) -> None:
        """AlertThrottle should clamp rate to hard minimum."""
        throttle = AlertThrottle(rate=0, per=60.0)
        assert throttle.rate == HARD_MIN_THROTTLE_RATE

        throttle = AlertThrottle(rate=-10, per=60.0)
        assert throttle.rate == HARD_MIN_THROTTLE_RATE

    def test_rate_clamped_to_maximum(self) -> None:
        """AlertThrottle should clamp rate to hard maximum."""
        throttle = AlertThrottle(rate=9999, per=60.0)
        assert throttle.rate == HARD_MAX_THROTTLE_RATE

    def test_per_clamped_to_minimum(self) -> None:
        """AlertThrottle should clamp per to hard minimum."""
        throttle = AlertThrottle(rate=10, per=0.1)
        assert throttle.per == HARD_MIN_THROTTLE_PER

        throttle = AlertThrottle(rate=10, per=-5)
        assert throttle.per == HARD_MIN_THROTTLE_PER

    def test_per_clamped_to_maximum(self) -> None:
        """AlertThrottle should clamp per to hard maximum."""
        throttle = AlertThrottle(rate=10, per=999999)
        assert throttle.per == HARD_MAX_THROTTLE_PER

    def test_burst_clamped_to_rate(self) -> None:
        """AlertThrottle should clamp burst to rate value."""
        throttle = AlertThrottle(rate=5, per=60.0, burst=100)
        # Burst clamped to rate (5)
        assert throttle.available == pytest.approx(5.0, abs=0.01)

    def test_burst_clamped_to_minimum(self) -> None:
        """AlertThrottle should clamp burst to minimum of 1."""
        throttle = AlertThrottle(rate=10, per=60.0, burst=0)
        assert throttle.available == pytest.approx(1.0, abs=0.01)

    def test_repr(self) -> None:
        """AlertThrottle should have meaningful repr."""
        throttle = AlertThrottle(rate=10, per=60.0)
        assert repr(throttle) == "AlertThrottle(rate=10.0, per=60.0)"


class TestAlertThrottleTryAcquire:
    """Tests for AlertThrottle.try_acquire()."""

    def test_try_acquire_success(self) -> None:
        """try_acquire should return True when tokens available."""
        throttle = AlertThrottle(rate=2, per=1.0)
        assert throttle.try_acquire() is True
        assert throttle.try_acquire() is True

    def test_try_acquire_exhausted(self) -> None:
        """try_acquire should return False when tokens exhausted."""
        throttle = AlertThrottle(rate=2, per=1.0)
        assert throttle.try_acquire() is True
        assert throttle.try_acquire() is True
        assert throttle.try_acquire() is False

    def test_available_decreases(self) -> None:
        """Available tokens should decrease on acquire."""
        throttle = AlertThrottle(rate=5, per=1.0)
        initial = throttle.available
        throttle.try_acquire()
        assert throttle.available < initial


class TestAlertThrottleAcquire:
    """Tests for AlertThrottle.acquire()."""

    def test_acquire_immediate(self) -> None:
        """acquire should return immediately when tokens available."""
        throttle = AlertThrottle(rate=10, per=1.0)
        throttle.acquire()  # Should not block

    def test_acquire_timeout_error(self) -> None:
        """acquire should raise AlertThrottledError on timeout."""
        throttle = AlertThrottle(rate=1, per=60.0)
        throttle.try_acquire()  # Exhaust token

        with pytest.raises(AlertThrottledError) as exc_info:
            throttle.acquire(timeout=0.01)

        assert exc_info.value.retry_after > 0


class TestAlertThrottleAcquireAsync:
    """Tests for AlertThrottle.acquire_async()."""

    @pytest.mark.asyncio
    async def test_acquire_async_immediate(self) -> None:
        """acquire_async should return immediately when tokens available."""
        throttle = AlertThrottle(rate=10, per=1.0)
        await throttle.acquire_async()  # Should not block

    @pytest.mark.asyncio
    async def test_acquire_async_timeout_error(self) -> None:
        """acquire_async should raise AlertThrottledError on timeout."""
        throttle = AlertThrottle(rate=1, per=60.0)
        throttle.try_acquire()  # Exhaust token

        with pytest.raises(AlertThrottledError) as exc_info:
            await throttle.acquire_async(timeout=0.01)

        assert exc_info.value.retry_after > 0


class TestAlertThrottleReset:
    """Tests for AlertThrottle.reset()."""

    def test_reset(self) -> None:
        """reset should restore full capacity."""
        throttle = AlertThrottle(rate=3, per=60.0)
        throttle.try_acquire()
        throttle.try_acquire()
        throttle.try_acquire()
        assert throttle.try_acquire() is False

        throttle.reset()
        assert throttle.try_acquire() is True


class TestAlertThrottleContextManager:
    """Tests for AlertThrottle context manager."""

    def test_sync_context_manager(self) -> None:
        """AlertThrottle should work as sync context manager."""
        throttle = AlertThrottle(rate=10, per=1.0)
        with throttle:
            pass  # Should acquire token

    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        """AlertThrottle should work as async context manager."""
        throttle = AlertThrottle(rate=10, per=1.0)
        async with throttle:
            pass  # Should acquire token


class TestAlertThrottleTimeUntilAvailable:
    """Tests for AlertThrottle.time_until_available."""

    def test_time_until_available_immediate(self) -> None:
        """time_until_available should be 0 when tokens available."""
        throttle = AlertThrottle(rate=10, per=1.0)
        assert throttle.time_until_available == 0.0

    def test_time_until_available_exhausted(self) -> None:
        """time_until_available should be positive when exhausted."""
        throttle = AlertThrottle(rate=1, per=60.0)
        throttle.try_acquire()  # Exhaust token
        assert throttle.time_until_available > 0
