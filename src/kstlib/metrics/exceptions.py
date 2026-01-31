"""Exceptions for the metrics module."""

__all__ = ["MetricsError"]


class MetricsError(Exception):
    """Base exception for metrics-related errors.

    Examples:
        >>> raise MetricsError("Something went wrong")
        Traceback (most recent call last):
            ...
        kstlib.metrics.exceptions.MetricsError: Something went wrong
    """
