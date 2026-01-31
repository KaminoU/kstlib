"""Tests for resilience module exceptions."""

from __future__ import annotations

import pytest

from kstlib.resilience.exceptions import (
    CircuitBreakerError,
    CircuitOpenError,
    HeartbeatError,
    ShutdownError,
)


class TestHeartbeatError:
    """Tests for HeartbeatError exception."""

    def test_is_runtime_error(self) -> None:
        """HeartbeatError inherits from RuntimeError."""
        assert issubclass(HeartbeatError, RuntimeError)

    def test_can_raise_with_message(self) -> None:
        """HeartbeatError can be raised with a message."""
        with pytest.raises(HeartbeatError, match="test error"):
            raise HeartbeatError("test error")


class TestShutdownError:
    """Tests for ShutdownError exception."""

    def test_is_runtime_error(self) -> None:
        """ShutdownError inherits from RuntimeError."""
        assert issubclass(ShutdownError, RuntimeError)

    def test_can_raise_with_message(self) -> None:
        """ShutdownError can be raised with a message."""
        with pytest.raises(ShutdownError, match="shutdown failed"):
            raise ShutdownError("shutdown failed")


class TestCircuitBreakerError:
    """Tests for CircuitBreakerError base exception."""

    def test_is_runtime_error(self) -> None:
        """CircuitBreakerError inherits from RuntimeError."""
        assert issubclass(CircuitBreakerError, RuntimeError)

    def test_can_raise_with_message(self) -> None:
        """CircuitBreakerError can be raised with a message."""
        with pytest.raises(CircuitBreakerError, match="circuit error"):
            raise CircuitBreakerError("circuit error")


class TestCircuitOpenError:
    """Tests for CircuitOpenError exception."""

    def test_is_circuit_breaker_error(self) -> None:
        """CircuitOpenError inherits from CircuitBreakerError."""
        assert issubclass(CircuitOpenError, CircuitBreakerError)

    def test_stores_remaining_seconds(self) -> None:
        """CircuitOpenError stores remaining_seconds attribute."""
        error = CircuitOpenError("Circuit open", remaining_seconds=15.5)
        assert error.remaining_seconds == 15.5
        assert str(error) == "Circuit open"

    def test_can_raise_and_catch(self) -> None:
        """CircuitOpenError can be raised and caught."""
        with pytest.raises(CircuitOpenError) as exc_info:
            raise CircuitOpenError("Wait before retry", remaining_seconds=30.0)

        assert exc_info.value.remaining_seconds == 30.0
        assert "Wait before retry" in str(exc_info.value)

    def test_zero_remaining_seconds(self) -> None:
        """CircuitOpenError accepts zero remaining seconds."""
        error = CircuitOpenError("About to close", remaining_seconds=0.0)
        assert error.remaining_seconds == 0.0
