"""Tests for the RateLimiter class and decorator."""

from __future__ import annotations

import threading
import time

import pytest

from kstlib.resilience.exceptions import RateLimitExceededError
from kstlib.resilience.rate_limiter import (
    RateLimiter,
    RateLimiterStats,
    rate_limiter,
)


class TestRateLimiterStats:
    """Tests for RateLimiterStats dataclass."""

    def test_default_values(self) -> None:
        """Stats start at zero."""
        stats = RateLimiterStats()
        assert stats.total_acquired == 0
        assert stats.total_rejected == 0
        assert stats.total_waited == 0.0

    def test_record_acquired(self) -> None:
        """Record a successful acquisition."""
        stats = RateLimiterStats()
        stats.record_acquired()
        assert stats.total_acquired == 1

    def test_record_rejected(self) -> None:
        """Record a rejected acquisition."""
        stats = RateLimiterStats()
        stats.record_rejected()
        assert stats.total_rejected == 1

    def test_record_wait(self) -> None:
        """Record wait time."""
        stats = RateLimiterStats()
        stats.record_wait(0.5)
        stats.record_wait(0.3)
        assert stats.total_waited == pytest.approx(0.8, abs=0.01)


class TestRateLimiterInit:
    """Tests for RateLimiter initialization."""

    def test_basic_init(self) -> None:
        """Basic initialization with rate and per."""
        limiter = RateLimiter(rate=10, per=1.0)
        assert limiter.rate == 10.0
        assert limiter.per == 1.0
        assert limiter.tokens == pytest.approx(10.0, abs=0.1)  # Starts full

    def test_custom_burst(self) -> None:
        """Initialize with custom burst capacity."""
        limiter = RateLimiter(rate=10, per=1.0, burst=5)
        assert limiter.tokens == pytest.approx(5.0, abs=0.1)

    def test_named_limiter(self) -> None:
        """Initialize with a name."""
        limiter = RateLimiter(rate=10, per=1.0, name="api-limiter")
        assert limiter.name == "api-limiter"

    def test_repr(self) -> None:
        """String representation."""
        limiter = RateLimiter(rate=10, per=1.0)
        assert "RateLimiter" in repr(limiter)
        assert "rate=10" in repr(limiter)

    def test_repr_with_name(self) -> None:
        """String representation with name."""
        limiter = RateLimiter(rate=10, per=1.0, name="test")
        assert "name='test'" in repr(limiter)

    def test_invalid_rate_raises(self) -> None:
        """Invalid rate raises ValueError."""
        with pytest.raises(ValueError, match="rate must be positive"):
            RateLimiter(rate=0, per=1.0)

        with pytest.raises(ValueError, match="rate must be positive"):
            RateLimiter(rate=-1, per=1.0)

    def test_invalid_per_raises(self) -> None:
        """Invalid per raises ValueError."""
        with pytest.raises(ValueError, match="per must be positive"):
            RateLimiter(rate=10, per=0)

        with pytest.raises(ValueError, match="per must be positive"):
            RateLimiter(rate=10, per=-1)


class TestRateLimiterAcquire:
    """Tests for token acquisition."""

    def test_acquire_success(self) -> None:
        """Acquire token successfully."""
        limiter = RateLimiter(rate=5, per=1.0)
        assert limiter.acquire() is True
        assert limiter.stats.total_acquired == 1

    def test_acquire_consumes_token(self) -> None:
        """Acquire consumes one token."""
        limiter = RateLimiter(rate=5, per=1.0)
        initial = limiter.tokens
        limiter.acquire()
        assert limiter.tokens == pytest.approx(initial - 1, abs=0.1)

    def test_try_acquire_success(self) -> None:
        """try_acquire returns True when tokens available."""
        limiter = RateLimiter(rate=5, per=1.0)
        assert limiter.try_acquire() is True

    def test_try_acquire_failure(self) -> None:
        """try_acquire returns False when no tokens."""
        limiter = RateLimiter(rate=2, per=1.0)
        assert limiter.try_acquire() is True
        assert limiter.try_acquire() is True
        assert limiter.try_acquire() is False
        assert limiter.stats.total_rejected == 1

    def test_acquire_non_blocking_failure(self) -> None:
        """Non-blocking acquire returns False when no tokens."""
        limiter = RateLimiter(rate=1, per=1.0)
        limiter.acquire()
        assert limiter.acquire(blocking=False) is False

    def test_acquire_blocking_waits(self) -> None:
        """Blocking acquire waits for token."""
        limiter = RateLimiter(rate=10, per=1.0, burst=0)  # Start empty
        start = time.monotonic()

        # Should wait for token refill
        limiter.acquire()

        elapsed = time.monotonic() - start
        assert elapsed >= 0.05  # At least some wait time
        assert limiter.stats.total_acquired == 1

    def test_acquire_timeout_raises(self) -> None:
        """Acquire with timeout raises when exceeded."""
        limiter = RateLimiter(rate=1, per=10.0, burst=0)  # Very slow refill

        with pytest.raises(RateLimitExceededError) as exc_info:
            limiter.acquire(timeout=0.1)

        assert exc_info.value.retry_after > 0
        assert limiter.stats.total_rejected == 1


class TestRateLimiterRefill:
    """Tests for token refill behavior."""

    def test_tokens_refill_over_time(self) -> None:
        """Tokens refill based on elapsed time."""
        limiter = RateLimiter(rate=10, per=1.0)

        # Consume all tokens
        for _ in range(10):
            limiter.try_acquire()

        assert limiter.tokens < 1.0

        # Wait for refill
        time.sleep(0.2)  # Should refill ~2 tokens

        assert limiter.tokens >= 1.0

    def test_tokens_capped_at_max(self) -> None:
        """Tokens don't exceed maximum."""
        limiter = RateLimiter(rate=5, per=1.0)

        # Wait extra time
        time.sleep(0.1)

        # Should still be capped at max
        assert limiter.tokens <= 5.0

    def test_reset_restores_full_capacity(self) -> None:
        """Reset restores full token capacity."""
        limiter = RateLimiter(rate=5, per=1.0)

        # Consume tokens
        for _ in range(5):
            limiter.try_acquire()

        assert limiter.tokens < 1.0

        limiter.reset()

        assert limiter.tokens == pytest.approx(5.0, abs=0.1)


class TestRateLimiterAsync:
    """Tests for async token acquisition."""

    @pytest.mark.asyncio
    async def test_acquire_async_success(self) -> None:
        """Async acquire succeeds with available token."""
        limiter = RateLimiter(rate=5, per=1.0)
        result = await limiter.acquire_async()
        assert result is True
        assert limiter.stats.total_acquired == 1

    @pytest.mark.asyncio
    async def test_acquire_async_waits(self) -> None:
        """Async acquire waits for token."""
        limiter = RateLimiter(rate=10, per=1.0, burst=0)
        start = time.monotonic()

        await limiter.acquire_async()

        elapsed = time.monotonic() - start
        assert elapsed >= 0.05

    @pytest.mark.asyncio
    async def test_acquire_async_timeout_raises(self) -> None:
        """Async acquire with timeout raises when exceeded."""
        limiter = RateLimiter(rate=1, per=10.0, burst=0)

        with pytest.raises(RateLimitExceededError):
            await limiter.acquire_async(timeout=0.1)


class TestRateLimiterContextManager:
    """Tests for context manager usage."""

    def test_sync_context_manager(self) -> None:
        """Sync context manager acquires token."""
        limiter = RateLimiter(rate=5, per=1.0)

        with limiter:
            pass

        assert limiter.stats.total_acquired == 1

    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        """Async context manager acquires token."""
        limiter = RateLimiter(rate=5, per=1.0)

        async with limiter:
            pass

        assert limiter.stats.total_acquired == 1


class TestRateLimiterThreadSafety:
    """Tests for thread safety."""

    def test_concurrent_acquires(self) -> None:
        """Concurrent acquires are thread-safe."""
        limiter = RateLimiter(rate=100, per=1.0)
        results: list[bool] = []
        errors: list[Exception] = []

        def worker() -> None:
            try:
                for _ in range(10):
                    result = limiter.try_acquire()
                    results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 100
        # All 100 tokens should be acquired (some may fail)
        assert results.count(True) == 100  # All should succeed with rate=100


class TestRateLimiterDecorator:
    """Tests for rate_limiter decorator."""

    def test_decorator_without_args(self) -> None:
        """Decorator works without arguments."""

        @rate_limiter
        def func() -> str:
            return "ok"

        assert func() == "ok"
        assert hasattr(func, "_rate_limiter")

    def test_decorator_with_args(self) -> None:
        """Decorator works with arguments."""

        @rate_limiter(rate=5, per=1.0)
        def func() -> str:
            return "ok"

        assert func() == "ok"

    def test_decorator_respects_rate(self) -> None:
        """Decorator enforces rate limit."""
        call_count = 0

        @rate_limiter(rate=2, per=1.0, blocking=False)
        def func() -> None:
            nonlocal call_count
            call_count += 1

        func()
        func()

        with pytest.raises(RateLimitExceededError):
            func()

        assert call_count == 2

    def test_decorator_blocking_waits(self) -> None:
        """Decorator waits when blocking=True."""

        @rate_limiter(rate=10, per=1.0)
        def func() -> str:
            return "ok"

        # Should always succeed (waits if needed)
        for _ in range(3):
            assert func() == "ok"

    def test_decorator_non_blocking_raises(self) -> None:
        """Decorator raises when blocking=False and limit hit."""

        @rate_limiter(rate=1, per=1.0, blocking=False)
        def func() -> str:
            return "ok"

        func()  # First call succeeds

        with pytest.raises(RateLimitExceededError) as exc_info:
            func()  # Second call fails

        assert exc_info.value.retry_after > 0

    def test_decorator_preserves_metadata(self) -> None:
        """Decorator preserves function metadata."""

        @rate_limiter(rate=10, per=1.0)
        def my_function() -> str:
            """My docstring."""
            return "ok"

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring."

    def test_decorator_with_timeout(self) -> None:
        """Decorator respects timeout."""

        @rate_limiter(rate=1, per=10.0, timeout=0.1, burst=0)
        def slow_func() -> str:
            return "ok"

        with pytest.raises(RateLimitExceededError):
            slow_func()

    @pytest.mark.asyncio
    async def test_decorator_async_function(self) -> None:
        """Decorator works with async functions."""

        @rate_limiter(rate=5, per=1.0)
        async def async_func() -> str:
            return "ok"

        result = await async_func()
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_decorator_async_respects_rate(self) -> None:
        """Async decorator enforces rate limit."""
        call_count = 0

        @rate_limiter(rate=2, per=1.0, blocking=False)
        async def async_func() -> None:
            nonlocal call_count
            call_count += 1

        await async_func()
        await async_func()

        with pytest.raises(RateLimitExceededError):
            await async_func()

        assert call_count == 2


class TestRateLimitExceededError:
    """Tests for RateLimitExceededError exception."""

    def test_exception_attributes(self) -> None:
        """Exception has required attributes."""
        exc = RateLimitExceededError("Rate limit hit", retry_after=1.5)
        assert str(exc) == "Rate limit hit"
        assert exc.retry_after == 1.5

    def test_exception_inheritance(self) -> None:
        """Exception inherits from correct base."""
        from kstlib.resilience.exceptions import RateLimitError

        exc = RateLimitExceededError("test", retry_after=1.0)
        assert isinstance(exc, RateLimitError)
        assert isinstance(exc, RuntimeError)
