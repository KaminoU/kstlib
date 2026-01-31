"""Tests for kstlib.alerts.exceptions module."""

import pytest

from kstlib.alerts.exceptions import (
    AlertConfigurationError,
    AlertDeliveryError,
    AlertError,
    AlertThrottledError,
)


class TestAlertError:
    """Tests for base AlertError."""

    def test_alert_error_is_exception(self) -> None:
        """AlertError should be a subclass of Exception."""
        assert issubclass(AlertError, Exception)

    def test_alert_error_message(self) -> None:
        """AlertError should store message."""
        err = AlertError("test message")
        assert str(err) == "test message"


class TestAlertConfigurationError:
    """Tests for AlertConfigurationError."""

    def test_is_alert_error_subclass(self) -> None:
        """AlertConfigurationError should be a subclass of AlertError."""
        assert issubclass(AlertConfigurationError, AlertError)

    def test_message(self) -> None:
        """AlertConfigurationError should store message."""
        err = AlertConfigurationError("invalid config")
        assert str(err) == "invalid config"


class TestAlertDeliveryError:
    """Tests for AlertDeliveryError."""

    def test_is_alert_error_subclass(self) -> None:
        """AlertDeliveryError should be a subclass of AlertError."""
        assert issubclass(AlertDeliveryError, AlertError)

    def test_channel_attribute(self) -> None:
        """AlertDeliveryError should store channel name."""
        err = AlertDeliveryError("failed", channel="slack")
        assert err.channel == "slack"

    def test_retryable_default_false(self) -> None:
        """AlertDeliveryError retryable should default to False."""
        err = AlertDeliveryError("failed", channel="email")
        assert err.retryable is False

    def test_retryable_true(self) -> None:
        """AlertDeliveryError should accept retryable=True."""
        err = AlertDeliveryError("timeout", channel="slack", retryable=True)
        assert err.retryable is True

    def test_message(self) -> None:
        """AlertDeliveryError should store message."""
        err = AlertDeliveryError("connection failed", channel="slack")
        assert str(err) == "connection failed"


class TestAlertThrottledError:
    """Tests for AlertThrottledError."""

    def test_is_alert_error_subclass(self) -> None:
        """AlertThrottledError should be a subclass of AlertError."""
        assert issubclass(AlertThrottledError, AlertError)

    def test_retry_after_attribute(self) -> None:
        """AlertThrottledError should store retry_after."""
        err = AlertThrottledError("rate limited", retry_after=30.0)
        assert err.retry_after == 30.0

    def test_message(self) -> None:
        """AlertThrottledError should store message."""
        err = AlertThrottledError("rate limited", retry_after=10.5)
        assert str(err) == "rate limited"

    def test_retry_after_float(self) -> None:
        """AlertThrottledError retry_after should be a float."""
        err = AlertThrottledError("limited", retry_after=45.5)
        assert isinstance(err.retry_after, float)
        assert err.retry_after == 45.5


class TestExceptionRaising:
    """Tests for raising exceptions in context."""

    def test_raise_delivery_error(self) -> None:
        """Should be able to raise and catch AlertDeliveryError."""
        with pytest.raises(AlertDeliveryError) as exc_info:
            raise AlertDeliveryError("webhook failed", channel="slack", retryable=True)

        assert exc_info.value.channel == "slack"
        assert exc_info.value.retryable is True

    def test_raise_throttled_error(self) -> None:
        """Should be able to raise and catch AlertThrottledError."""
        with pytest.raises(AlertThrottledError) as exc_info:
            raise AlertThrottledError("too many requests", retry_after=60.0)

        assert exc_info.value.retry_after == 60.0

    def test_catch_as_alert_error(self) -> None:
        """All alert exceptions should be catchable as AlertError."""
        exceptions = [
            AlertConfigurationError("bad config"),
            AlertDeliveryError("failed", channel="test"),
            AlertThrottledError("limited", retry_after=10.0),
        ]

        for exc in exceptions:
            with pytest.raises(AlertError):
                raise exc
