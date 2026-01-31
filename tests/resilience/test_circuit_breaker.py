"""Tests for the CircuitBreaker class and decorator."""

from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import patch

import pytest

from kstlib.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    CircuitStats,
    circuit_breaker,
)
from kstlib.resilience.exceptions import CircuitOpenError


class TestCircuitState:
    """Tests for CircuitState enum."""

    def test_states_exist(self) -> None:
        """Circuit breaker has three states."""
        assert CircuitState.CLOSED
        assert CircuitState.OPEN
        assert CircuitState.HALF_OPEN

    def test_states_are_distinct(self) -> None:
        """Each state has a unique value."""
        states = [CircuitState.CLOSED, CircuitState.OPEN, CircuitState.HALF_OPEN]
        values = [s.value for s in states]
        assert len(values) == len(set(values))


class TestCircuitStats:
    """Tests for CircuitStats dataclass."""

    def test_default_values(self) -> None:
        """Stats start at zero."""
        stats = CircuitStats()
        assert stats.total_calls == 0
        assert stats.successful_calls == 0
        assert stats.failed_calls == 0
        assert stats.rejected_calls == 0
        assert stats.state_changes == 0

    def test_record_success(self) -> None:
        """Record a successful call."""
        stats = CircuitStats()
        stats.record_success()
        assert stats.total_calls == 1
        assert stats.successful_calls == 1

    def test_record_failure(self) -> None:
        """Record a failed call."""
        stats = CircuitStats()
        stats.record_failure()
        assert stats.total_calls == 1
        assert stats.failed_calls == 1

    def test_record_rejection(self) -> None:
        """Record a rejected call."""
        stats = CircuitStats()
        stats.record_rejection()
        assert stats.total_calls == 1
        assert stats.rejected_calls == 1

    def test_record_state_change(self) -> None:
        """Record a state change."""
        stats = CircuitStats()
        stats.record_state_change()
        assert stats.state_changes == 1


class TestCircuitBreakerInit:
    """Tests for CircuitBreaker initialization."""

    def test_default_from_config(self) -> None:
        """Use defaults from config when not specified."""
        cb = CircuitBreaker()
        assert cb._max_failures == 5  # Default from config
        assert cb._reset_timeout == 60  # Default from config
        assert cb._half_open_max_calls == 1  # Default from config

    def test_custom_max_failures(self) -> None:
        """Accept custom max_failures."""
        cb = CircuitBreaker(max_failures=3)
        assert cb._max_failures == 3

    def test_max_failures_clamped_to_minimum(self) -> None:
        """Clamp max_failures to hard minimum."""
        cb = CircuitBreaker(max_failures=0)
        assert cb._max_failures == 1  # Hard minimum

    def test_max_failures_clamped_to_maximum(self) -> None:
        """Clamp max_failures to hard maximum."""
        cb = CircuitBreaker(max_failures=1000)
        assert cb._max_failures == 100  # Hard maximum

    def test_custom_reset_timeout(self) -> None:
        """Accept custom reset_timeout."""
        cb = CircuitBreaker(reset_timeout=30)
        assert cb._reset_timeout == 30

    def test_reset_timeout_clamped_to_minimum(self) -> None:
        """Clamp reset_timeout to hard minimum."""
        cb = CircuitBreaker(reset_timeout=0.1)
        assert cb._reset_timeout == 1  # Hard minimum

    def test_reset_timeout_clamped_to_maximum(self) -> None:
        """Clamp reset_timeout to hard maximum."""
        cb = CircuitBreaker(reset_timeout=10000)
        assert cb._reset_timeout == 3600  # Hard maximum

    def test_custom_half_open_max_calls(self) -> None:
        """Accept custom half_open_max_calls."""
        cb = CircuitBreaker(half_open_max_calls=3)
        assert cb._half_open_max_calls == 3

    def test_half_open_max_calls_clamped(self) -> None:
        """Clamp half_open_max_calls to bounds."""
        cb = CircuitBreaker(half_open_max_calls=0)
        assert cb._half_open_max_calls == 1  # Hard minimum
        cb = CircuitBreaker(half_open_max_calls=100)
        assert cb._half_open_max_calls == 10  # Hard maximum

    def test_excluded_exceptions(self) -> None:
        """Accept excluded exceptions."""
        cb = CircuitBreaker(excluded_exceptions=(ValueError, TypeError))
        assert cb._excluded_exceptions == (ValueError, TypeError)

    def test_name_property(self) -> None:
        """Accept and return name."""
        cb = CircuitBreaker(name="api_breaker")
        assert cb.name == "api_breaker"

    def test_initial_state_is_closed(self) -> None:
        """Initial state is CLOSED."""
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED


class TestCircuitBreakerCall:
    """Tests for the call() method."""

    def test_successful_call(self) -> None:
        """Successful call passes through."""
        cb = CircuitBreaker()
        result = cb.call(lambda x: x * 2, 5)
        assert result == 10

    def test_failed_call_raises(self) -> None:
        """Failed call re-raises exception."""
        cb = CircuitBreaker()
        with pytest.raises(ValueError, match="test error"):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("test error")))

    def test_failure_increments_count(self) -> None:
        """Failed call increments failure count."""
        cb = CircuitBreaker()
        with contextlib.suppress(ZeroDivisionError):
            cb.call(lambda: 1 / 0)
        assert cb.failure_count == 1

    def test_success_resets_failure_count(self) -> None:
        """Successful call resets failure count in CLOSED state."""
        cb = CircuitBreaker()
        with contextlib.suppress(ZeroDivisionError):
            cb.call(lambda: 1 / 0)
        assert cb.failure_count == 1
        cb.call(lambda: 42)
        assert cb.failure_count == 0


class TestCircuitBreakerAcall:
    """Tests for the acall() async method."""

    @pytest.mark.asyncio
    async def test_successful_async_call(self) -> None:
        """Successful async call passes through."""
        cb = CircuitBreaker()

        async def double(x: int) -> int:
            return x * 2

        result = await cb.acall(double, 5)
        assert result == 10

    @pytest.mark.asyncio
    async def test_failed_async_call_raises(self) -> None:
        """Failed async call re-raises exception."""
        cb = CircuitBreaker()

        async def fail() -> None:
            raise ValueError("async error")

        with pytest.raises(ValueError, match="async error"):
            await cb.acall(fail)

    @pytest.mark.asyncio
    async def test_async_failure_increments_count(self) -> None:
        """Failed async call increments failure count."""
        cb = CircuitBreaker()

        async def fail() -> None:
            raise RuntimeError("fail")

        with contextlib.suppress(RuntimeError):
            await cb.acall(fail)
        assert cb.failure_count == 1


class TestCircuitBreakerStateTransitions:
    """Tests for state transitions."""

    def test_open_after_max_failures(self) -> None:
        """Circuit opens after max_failures consecutive failures."""
        cb = CircuitBreaker(max_failures=3)

        for _ in range(3):
            with contextlib.suppress(ZeroDivisionError):
                cb.call(lambda: 1 / 0)

        assert cb.state == CircuitState.OPEN

    def test_open_circuit_rejects_calls(self) -> None:
        """Open circuit rejects calls with CircuitOpenError."""
        cb = CircuitBreaker(max_failures=1)

        with contextlib.suppress(ZeroDivisionError):
            cb.call(lambda: 1 / 0)

        with pytest.raises(CircuitOpenError) as exc_info:
            cb.call(lambda: 42)

        assert exc_info.value.remaining_seconds >= 0

    def test_transition_to_half_open_after_timeout(self) -> None:
        """Circuit transitions to HALF_OPEN after reset_timeout."""
        cb = CircuitBreaker(max_failures=1, reset_timeout=1)  # Hard minimum

        with contextlib.suppress(ZeroDivisionError):
            cb.call(lambda: 1 / 0)

        assert cb.state == CircuitState.OPEN

        # Mock time to simulate timeout
        original_time = cb._last_failure_time
        with patch("time.monotonic", return_value=original_time + 2):
            assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_closes_on_success(self) -> None:
        """Circuit closes after successful call in HALF_OPEN state."""
        cb = CircuitBreaker(max_failures=1, reset_timeout=1, half_open_max_calls=1)

        with contextlib.suppress(ZeroDivisionError):
            cb.call(lambda: 1 / 0)

        # Force transition to HALF_OPEN by mocking time
        original_time = cb._last_failure_time
        with patch("time.monotonic", return_value=original_time + 2):
            assert cb.state == CircuitState.HALF_OPEN

            cb.call(lambda: 42)
            assert cb.state == CircuitState.CLOSED

    def test_half_open_reopens_on_failure(self) -> None:
        """Circuit reopens after failure in HALF_OPEN state."""
        cb = CircuitBreaker(max_failures=1, reset_timeout=1)

        with contextlib.suppress(ZeroDivisionError):
            cb.call(lambda: 1 / 0)

        # Force transition to HALF_OPEN by mocking time
        original_time = cb._last_failure_time
        with patch("time.monotonic", return_value=original_time + 2):
            assert cb.state == CircuitState.HALF_OPEN

            with contextlib.suppress(ZeroDivisionError):
                cb.call(lambda: 1 / 0)

            assert cb.state == CircuitState.OPEN

    def test_multiple_half_open_successes(self) -> None:
        """Circuit requires multiple successes in HALF_OPEN if configured."""
        cb = CircuitBreaker(max_failures=1, reset_timeout=1, half_open_max_calls=2)

        with contextlib.suppress(ZeroDivisionError):
            cb.call(lambda: 1 / 0)

        # Force transition to HALF_OPEN by mocking time
        original_time = cb._last_failure_time
        with patch("time.monotonic", return_value=original_time + 2):
            assert cb.state == CircuitState.HALF_OPEN

            cb.call(lambda: 42)
            assert cb.state == CircuitState.HALF_OPEN  # Still half-open

            cb.call(lambda: 42)
            assert cb.state == CircuitState.CLOSED  # Now closed


class TestCircuitBreakerExcludedExceptions:
    """Tests for excluded exceptions."""

    def test_excluded_exception_not_counted(self) -> None:
        """Excluded exceptions don't count as failures."""
        cb = CircuitBreaker(max_failures=1, excluded_exceptions=(ValueError,))

        with contextlib.suppress(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("excluded")))

        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED

    def test_non_excluded_exception_counted(self) -> None:
        """Non-excluded exceptions count as failures."""
        cb = CircuitBreaker(max_failures=1, excluded_exceptions=(ValueError,))

        with contextlib.suppress(ZeroDivisionError):
            cb.call(lambda: 1 / 0)

        assert cb.failure_count == 1
        assert cb.state == CircuitState.OPEN


class TestCircuitBreakerReset:
    """Tests for manual reset."""

    def test_reset_closes_circuit(self) -> None:
        """Manual reset closes the circuit."""
        cb = CircuitBreaker(max_failures=1)

        with contextlib.suppress(ZeroDivisionError):
            cb.call(lambda: 1 / 0)

        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED

    def test_reset_clears_failure_count(self) -> None:
        """Manual reset clears failure count."""
        cb = CircuitBreaker(max_failures=5)

        for _ in range(3):
            with contextlib.suppress(ZeroDivisionError):
                cb.call(lambda: 1 / 0)

        assert cb.failure_count == 3
        cb.reset()
        assert cb.failure_count == 0


class TestCircuitBreakerStats:
    """Tests for statistics tracking."""

    def test_stats_track_success(self) -> None:
        """Stats track successful calls."""
        cb = CircuitBreaker()
        cb.call(lambda: 42)

        assert cb.stats.total_calls == 1
        assert cb.stats.successful_calls == 1

    def test_stats_track_failure(self) -> None:
        """Stats track failed calls."""
        cb = CircuitBreaker()

        with contextlib.suppress(ZeroDivisionError):
            cb.call(lambda: 1 / 0)

        assert cb.stats.total_calls == 1
        assert cb.stats.failed_calls == 1

    def test_stats_track_rejection(self) -> None:
        """Stats track rejected calls."""
        cb = CircuitBreaker(max_failures=1)

        with contextlib.suppress(ZeroDivisionError):
            cb.call(lambda: 1 / 0)

        with contextlib.suppress(CircuitOpenError):
            cb.call(lambda: 42)

        assert cb.stats.rejected_calls == 1

    def test_stats_track_state_changes(self) -> None:
        """Stats track state changes."""
        cb = CircuitBreaker(max_failures=1, reset_timeout=1)

        with contextlib.suppress(ZeroDivisionError):
            cb.call(lambda: 1 / 0)

        # First state change: CLOSED -> OPEN
        assert cb.stats.state_changes == 1

        # Force transition to HALF_OPEN by mocking time
        original_time = cb._last_failure_time
        with patch("time.monotonic", return_value=original_time + 2):
            _ = cb.state  # Trigger transition check
            # Second state change: OPEN -> HALF_OPEN
            assert cb.stats.state_changes == 2


class TestCircuitBreakerDecorator:
    """Tests for CircuitBreaker as decorator."""

    def test_decorator_wraps_sync_function(self) -> None:
        """Decorator wraps synchronous function."""
        cb = CircuitBreaker()

        @cb
        def double(x: int) -> int:
            return x * 2

        assert double(5) == 10

    def test_decorator_wraps_async_function(self) -> None:
        """Decorator wraps async function."""
        cb = CircuitBreaker()

        @cb
        async def double(x: int) -> int:
            return x * 2

        assert asyncio.run(double(5)) == 10

    def test_decorator_preserves_function_name(self) -> None:
        """Decorator preserves function metadata."""
        cb = CircuitBreaker()

        @cb
        def my_function() -> None:
            """My docstring."""
            pass

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring."


class TestCircuitBreakerDecoratorFactory:
    """Tests for circuit_breaker decorator factory."""

    def test_without_arguments(self) -> None:
        """Use decorator without arguments."""

        @circuit_breaker
        def api_call() -> str:
            return "success"

        assert api_call() == "success"

    def test_with_arguments(self) -> None:
        """Use decorator with arguments."""

        @circuit_breaker(max_failures=2)
        def api_call() -> str:
            return "success"

        assert api_call() == "success"

    def test_async_without_arguments(self) -> None:
        """Async decorator without arguments."""

        @circuit_breaker
        async def api_call() -> str:
            return "async success"

        assert asyncio.run(api_call()) == "async success"

    def test_async_with_arguments(self) -> None:
        """Async decorator with arguments."""

        @circuit_breaker(max_failures=2, reset_timeout=10)
        async def api_call() -> str:
            return "async success"

        assert asyncio.run(api_call()) == "async success"

    def test_decorator_with_excluded_exceptions(self) -> None:
        """Decorator with excluded exceptions."""

        @circuit_breaker(max_failures=1, excluded_exceptions=(ValueError,))
        def validate(x: int) -> int:
            if x < 0:
                raise ValueError("negative")
            return x

        # ValueError should not trip the circuit
        with pytest.raises(ValueError):
            validate(-1)

        # Should still work
        assert validate(5) == 5

    def test_decorator_with_name(self) -> None:
        """Decorator with custom name appears in error."""

        @circuit_breaker(max_failures=1, name="test_api")
        def api_call() -> None:
            raise RuntimeError("fail")

        with contextlib.suppress(RuntimeError):
            api_call()

        with pytest.raises(CircuitOpenError, match="test_api"):
            api_call()


class TestCircuitBreakerConcurrency:
    """Tests for thread safety."""

    def test_concurrent_calls(self) -> None:
        """Circuit breaker is thread-safe."""
        import threading

        cb = CircuitBreaker(max_failures=100)
        results: list[int] = []
        errors: list[Exception] = []

        def worker(n: int) -> None:
            try:
                result = cb.call(lambda x: x * 2, n)
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 50
        assert len(errors) == 0


class TestCircuitBreakerOpenError:
    """Tests for CircuitOpenError details."""

    def test_error_includes_remaining_time(self) -> None:
        """CircuitOpenError includes remaining time."""
        cb = CircuitBreaker(max_failures=1, reset_timeout=10)

        with contextlib.suppress(ZeroDivisionError):
            cb.call(lambda: 1 / 0)

        with pytest.raises(CircuitOpenError) as exc_info:
            cb.call(lambda: 42)

        # Should have roughly 10 seconds remaining
        assert exc_info.value.remaining_seconds > 9
        assert exc_info.value.remaining_seconds <= 10

    def test_error_message_includes_name(self) -> None:
        """CircuitOpenError message includes circuit name."""
        cb = CircuitBreaker(max_failures=1, name="my_circuit")

        with contextlib.suppress(ZeroDivisionError):
            cb.call(lambda: 1 / 0)

        with pytest.raises(CircuitOpenError, match="my_circuit"):
            cb.call(lambda: 42)

    def test_error_message_unnamed_circuit(self) -> None:
        """CircuitOpenError message handles unnamed circuit."""
        cb = CircuitBreaker(max_failures=1)

        with contextlib.suppress(ZeroDivisionError):
            cb.call(lambda: 1 / 0)

        with pytest.raises(CircuitOpenError, match="unnamed"):
            cb.call(lambda: 42)
