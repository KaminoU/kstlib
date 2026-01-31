"""Specialized exceptions raised by the kstlib.monitoring module.

Exception hierarchy::

    KstlibError
        MonitoringError (base)
            CollectorError
            RenderError
            MonitoringConfigError
"""

from __future__ import annotations

from kstlib.config.exceptions import KstlibError


class MonitoringError(KstlibError):
    """Base exception for all monitoring errors."""


class CollectorError(MonitoringError):
    """Error during data collection.

    Raised when a collector callable fails during MonitoringService.collect().

    Attributes:
        collector_name: Name of the failed collector.
        cause: The underlying exception that caused the failure.
    """

    def __init__(self, collector_name: str, cause: Exception) -> None:
        """Initialize with collector name and underlying cause.

        Args:
            collector_name: Name of the failed collector.
            cause: The exception that caused the failure.
        """
        self.collector_name = collector_name
        self.cause = cause
        super().__init__(f"Collector '{collector_name}' failed: {cause}")


class RenderError(MonitoringError, ValueError):
    """HTML rendering failed.

    Raised when a renderable object cannot produce valid HTML output,
    for example due to inconsistent data dimensions or template errors.
    """


class MonitoringConfigError(MonitoringError):
    """Base exception for monitoring configuration errors.

    Raised when a monitoring configuration file cannot be loaded or parsed.
    """


__all__ = [
    "CollectorError",
    "MonitoringConfigError",
    "MonitoringError",
    "RenderError",
]
