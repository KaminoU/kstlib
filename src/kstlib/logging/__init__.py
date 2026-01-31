"""Logging module with Rich console output and async-friendly wrappers.

This module provides a LogManager class for structured logging with:
- Rich console output (colored, emoji icons, traceback with locals)
- File logging with rotation
- Preset configurations (dev, prod, debug)
- Async wrappers executed via thread pool
- Structured logging with context key=value pairs

Example:
    >>> from kstlib.logging import get_logger
    >>> logger = get_logger(__name__)
    >>> logger.info("Server started")  # doctest: +SKIP
"""

from __future__ import annotations

import logging
from typing import Any

from kstlib.logging.manager import HAS_ASYNC, TRACE_LEVEL, LogManager

# Singleton root logger for kstlib
_root_logger: LogManager | None = None


def init_logging(
    *,
    preset: str | None = None,
    config: dict[str, Any] | None = None,
) -> LogManager:
    """Initialize the kstlib root logger.

    This function should be called early in the application startup to
    configure logging. If not called, loggers will use Python's default
    configuration.

    This also configures the standard "kstlib" logger in Python's logging
    hierarchy so that child loggers (e.g., "kstlib.auth.providers.base")
    properly propagate their messages to the LogManager's handlers.

    Args:
        preset: Logging preset ("dev", "prod", "debug", or custom from config).
        config: Explicit configuration dict.

    Returns:
        The root LogManager instance.

    Example:
        >>> from kstlib.logging import init_logging
        >>> logger = init_logging(preset="dev")  # doctest: +SKIP
    """
    global _root_logger
    _root_logger = LogManager(name="kstlib", preset=preset, config=config)

    # Also configure the standard "kstlib" logger so child loggers
    # (created via logging.getLogger("kstlib.xxx")) propagate correctly
    std_logger = logging.getLogger("kstlib")
    std_logger.setLevel(TRACE_LEVEL)  # Let handlers filter

    # Clear existing handlers to prevent duplication on multiple init_logging() calls
    std_logger.handlers.clear()

    # Copy handlers from LogManager to standard logger
    for handler in _root_logger.handlers:
        std_logger.addHandler(handler)

    # Propagate level to ALL existing child loggers under "kstlib.*"
    # This ensures modules loaded before init_logging() also get the correct level
    for logger_name in list(logging.Logger.manager.loggerDict):
        if logger_name.startswith("kstlib."):
            child_logger = logging.getLogger(logger_name)
            child_logger.setLevel(TRACE_LEVEL)

    return _root_logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Get a logger for the given module name.

    Returns a child logger under the 'kstlib' namespace. When the root
    logger is initialized via ``init_logging()`` or CLI ``--log-level``,
    child loggers inherit its handlers and configuration.

    Args:
        name: Module name (typically ``__name__``). If None, returns
            the root kstlib logger.

    Returns:
        A logger instance.

    Example:
        >>> from kstlib.logging import get_logger
        >>> logger = get_logger(__name__)
        >>> logger.debug("Processing item", extra={"item_id": 123})  # doctest: +SKIP
    """
    if name is None:
        # Return root logger (create if needed)
        if _root_logger is not None:
            return _root_logger
        return logging.getLogger("kstlib")

    # Ensure logger is under kstlib namespace for proper propagation
    logger_name = name if name.startswith("kstlib.") else f"kstlib.{name}"
    return logging.getLogger(logger_name)


__all__ = ["HAS_ASYNC", "TRACE_LEVEL", "LogManager", "get_logger", "init_logging"]
