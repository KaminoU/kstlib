"""Exceptions for the metrics module."""

from kstlib.config.exceptions import KstlibError

__all__ = ["MetricsError"]


class MetricsError(KstlibError):
    """Base exception for metrics-related errors.

    Examples:
        >>> raise MetricsError("Something went wrong")
        Traceback (most recent call last):
            ...
        kstlib.metrics.exceptions.MetricsError: Something went wrong

    """
