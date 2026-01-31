"""Custom exceptions for the alerts module."""

from __future__ import annotations

from kstlib.config.exceptions import KstlibError


class AlertError(KstlibError):
    """Base class for all alert-related errors."""


class AlertConfigurationError(AlertError):
    """Raised when alert configuration is invalid or incomplete."""


class AlertDeliveryError(AlertError):
    """Raised when an alert cannot be delivered to a channel.

    Attributes:
        channel: The name of the channel that failed.
        retryable: Whether the error is potentially recoverable with retry.

    Examples:
        >>> err = AlertDeliveryError("Connection failed", channel="slack", retryable=True)
        >>> err.channel
        'slack'
        >>> err.retryable
        True
    """

    def __init__(self, message: str, *, channel: str, retryable: bool = False) -> None:
        """Initialize AlertDeliveryError.

        Args:
            message: Error description.
            channel: Name of the channel that failed.
            retryable: Whether the delivery could succeed on retry.
        """
        super().__init__(message)
        self.channel = channel
        self.retryable = retryable


class AlertThrottledError(AlertError):
    """Raised when an alert is throttled due to rate limiting.

    Attributes:
        retry_after: Seconds until the next alert can be sent.

    Examples:
        >>> err = AlertThrottledError("Rate limit exceeded", retry_after=30.0)
        >>> err.retry_after
        30.0
    """

    def __init__(self, message: str, *, retry_after: float) -> None:
        """Initialize AlertThrottledError.

        Args:
            message: Error description.
            retry_after: Seconds until the rate limit resets.
        """
        super().__init__(message)
        self.retry_after = retry_after


__all__ = [
    "AlertConfigurationError",
    "AlertDeliveryError",
    "AlertError",
    "AlertThrottledError",
]
