"""Logging module with Rich console output and async-friendly wrappers.

This module provides a LogManager class for structured logging with:

- Rich console output (colored, emoji icons, traceback with locals)
- File logging with rotation
- Preset configurations (dev, prod, debug)
- Async wrappers executed via thread pool
- Structured logging with context key=value pairs
- Opt-in lazy auto-init driven by the config file

Two ways to use LogManager:

- ``LogManager(preset="dev")`` returns an isolated instance. ``logging.getLogger("kstlib")``
  is untouched, so this form is safe for local use and tests.
- ``LogManager(preset="dev", register=True)`` (or the ``init_logging()`` alias)
  registers the instance as the global root of the ``"kstlib"`` logger hierarchy
  so that ``logging.getLogger("kstlib.foo")`` child loggers propagate records
  back to it.

Consumers who never call ``init_logging()`` can still activate internal
kstlib logs by flipping ``kstlib.logging.enabled`` in ``kstlib.conf.yml``.
The first call to ``get_logger()`` from any kstlib module then triggers
``LogManager(preset=..., register=True)`` transparently. Any error on that
cascade is swallowed silently so the library never breaks the host
application.

Example:
    >>> from kstlib.logging import get_logger
    >>> logger = get_logger(__name__)
    >>> logger.info("Server started")  # doctest: +SKIP

"""

from __future__ import annotations

import logging
import sys
from typing import Any

from kstlib.logging.manager import (
    HAS_ASYNC,
    LOGGING_LEVEL,
    SUCCESS_LEVEL,
    TRACE_LEVEL,
    LogManager,
    list_available_presets,
)

# Singleton root logger for kstlib
_root_logger: LogManager | None = None

# Default preset used when ``kstlib.logging.preset`` is missing or invalid
_DEFAULT_AUTO_INIT_PRESET = "prod"

# One-shot flag so the invalid-preset stderr notice is printed at most once
# per process even if get_logger() is called many times with the same broken
# config. Module-level so tests can reset it between runs.
_preset_warning_emitted: bool = False


def init_logging(
    *,
    preset: str | None = None,
    config: dict[str, Any] | None = None,
) -> LogManager:
    """Initialize the kstlib root logger (alias of ``LogManager(register=True)``).

    This is a thin backward-compatible wrapper around
    ``LogManager(name="kstlib", preset=..., config=..., register=True)``. The
    heavy lifting (logger-dict injection, ``.trace``/``.success`` monkey-patch,
    level propagation to pre-existing children) happens inside
    ``LogManager.__init__`` when ``register=True``.

    Call this function early in the application startup to configure logging.
    If it is never called explicitly, ``get_logger()`` may still trigger a
    silent auto-init based on ``kstlib.logging.enabled`` in ``kstlib.conf.yml``.

    Args:
        preset: Logging preset ("dev", "prod", "debug", or custom from config).
        config: Explicit configuration dict.

    Returns:
        The root LogManager instance (same as ``logging.getLogger("kstlib")``).

    Example:
        >>> from kstlib.logging import init_logging
        >>> logger = init_logging(preset="dev")  # doctest: +SKIP

    """
    global _root_logger
    _root_logger = LogManager(name="kstlib", preset=preset, config=config, register=True)
    return _root_logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Get a logger for the given module name.

    Returns a child logger under the 'kstlib' namespace. When the root
    logger is initialized via ``init_logging()`` or CLI ``--log-level``,
    child loggers inherit its handlers and configuration.

    On first call, if no explicit ``init_logging()`` has been made, this
    function reads ``kstlib.logging.enabled`` from ``kstlib.conf.yml`` and
    triggers a silent auto-init when the flag is true. Config errors are
    swallowed: the cascade simply falls back to Python's default logging.

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
    global _root_logger, _preset_warning_emitted

    # Lazy opt-in auto-init: harmless no-op if already initialized or disabled.
    if _root_logger is None:
        try:
            from kstlib.config import get_config

            cfg = get_config()
            kstlib_section = cfg.get("kstlib") if hasattr(cfg, "get") else None  # type: ignore[no-untyped-call]
            log_section = kstlib_section.get("logging") if kstlib_section and hasattr(kstlib_section, "get") else None
            if log_section and bool(log_section.get("enabled", False)):
                requested = log_section.get("preset") or _DEFAULT_AUTO_INIT_PRESET
                available = list_available_presets()
                if requested not in available:
                    if not _preset_warning_emitted:
                        sys.stderr.write(
                            f"kstlib logging: preset '{requested}' not found, "
                            f"available: {available}, "
                            f"falling back to '{_DEFAULT_AUTO_INIT_PRESET}'.\n"
                        )
                        _preset_warning_emitted = True
                    requested = _DEFAULT_AUTO_INIT_PRESET
                _root_logger = LogManager(name="kstlib", preset=requested, register=True)
        except Exception:
            # Silent by design: auto-init MUST NEVER raise. kstlib cannot
            # break the host application through the logging cascade.
            pass

    if name is None:
        # Return root logger (create if needed)
        if _root_logger is not None:
            return _root_logger
        return logging.getLogger("kstlib")

    # Ensure logger is under kstlib namespace for proper propagation
    logger_name = name if name.startswith("kstlib.") else f"kstlib.{name}"
    return logging.getLogger(logger_name)


__all__ = [
    "HAS_ASYNC",
    "LOGGING_LEVEL",
    "SUCCESS_LEVEL",
    "TRACE_LEVEL",
    "LogManager",
    "get_logger",
    "init_logging",
    "list_available_presets",
]
