"""Specialized exceptions raised by the kstlib.resilience module."""

from __future__ import annotations


class HeartbeatError(RuntimeError):
    """Raised when the heartbeat encounters an error.

    Examples include state file write failure or invalid state file path.
    """


class ShutdownError(RuntimeError):
    """Raised when graceful shutdown encounters an error.

    Examples include cleanup callback failure or timeout exceeded.
    """


class CircuitBreakerError(RuntimeError):
    """Base exception for circuit breaker errors."""


class CircuitOpenError(CircuitBreakerError):
    """Raised when a call is attempted while the circuit is open.

    Attributes:
        remaining_seconds: Time until the circuit may transition to half-open.
    """

    def __init__(self, message: str, remaining_seconds: float) -> None:
        """Initialize CircuitOpenError.

        Args:
            message: Human-readable error message.
            remaining_seconds: Seconds until circuit may transition to half-open.
        """
        super().__init__(message)
        self.remaining_seconds = remaining_seconds


class RateLimitError(RuntimeError):
    """Base exception for rate limiter errors."""


class RateLimitExceededError(RateLimitError):
    """Raised when rate limit is exceeded and blocking is disabled.

    Attributes:
        retry_after: Seconds until a token will be available.
    """

    def __init__(self, message: str, retry_after: float) -> None:
        """Initialize RateLimitExceededError.

        Args:
            message: Human-readable error message.
            retry_after: Seconds until a token will be available.
        """
        super().__init__(message)
        self.retry_after = retry_after


class WatchdogError(RuntimeError):
    """Base exception for watchdog errors."""


class WatchdogTimeoutError(WatchdogError):
    """Raised when watchdog detects inactivity timeout.

    Attributes:
        seconds_inactive: Time since last ping/activity.
    """

    def __init__(self, message: str, seconds_inactive: float) -> None:
        """Initialize WatchdogTimeoutError.

        Args:
            message: Human-readable error message.
            seconds_inactive: Seconds since last activity.
        """
        super().__init__(message)
        self.seconds_inactive = seconds_inactive


__all__ = [
    "CircuitBreakerError",
    "CircuitOpenError",
    "HeartbeatError",
    "RateLimitError",
    "RateLimitExceededError",
    "ShutdownError",
    "WatchdogError",
    "WatchdogTimeoutError",
]
