"""Logging module for kstlib with Rich console output and async helpers.

This module provides a flexible logging system with:
- Rich console output (colored, traceback with locals)
- File rotation (TimedRotatingFileHandler)
- Async-friendly wrappers (executed via thread pool)
- Structured logging (context key=value)
- Configurable presets (dev, prod, debug, + custom via config)
- Multiple instances support

Example:
    Basic usage with preset::

        from kstlib.logging import LogManager

        logger = LogManager(preset="dev")
        logger.info("Server started", host="localhost", port=8080)

    Async logging::

        async def main():
            logger = LogManager(preset="prod")
            await logger.ainfo("Order placed", symbol="BTCUSDT", qty=0.5)

    Custom config::

        config = {
            "output": "both",
            "console": {"level": "DEBUG"},
            "file": {"log_name": "myapp.log"}
        }
        logger = LogManager(config=config)

"""

import asyncio
import logging
import re
import shutil
from functools import partial
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from box import Box
from rich.console import Console
from rich.logging import RichHandler
from rich.theme import Theme
from rich.traceback import Traceback

from kstlib.config import get_config

# =============================================================================
# HARDCODED LIMITS (Deep Defense)
# =============================================================================
# These limits are enforced regardless of user configuration to prevent abuse.

# Pre-compiled patterns for log sanitization (hot path)
_ANSI_CSI_PATTERN = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
_ANSI_OSC_PATTERN = re.compile(r"\x1b\][^\x07]*\x07")
_CONTROL_CHAR_PATTERN = re.compile(r"[\r\n\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Maximum log file path length (prevents filesystem issues)
HARD_MAX_FILE_PATH_LENGTH: int = 4096

# Maximum log file name length (prevents filesystem issues on some OS)
HARD_MAX_FILE_NAME_LENGTH: int = 255

# Forbidden path components (security: prevent path traversal)
FORBIDDEN_PATH_COMPONENTS: frozenset[str] = frozenset({"..", "~"})

# Allowed file extensions for log files
ALLOWED_LOG_EXTENSIONS: frozenset[str] = frozenset({".log", ".txt", ".json", ""})


# TODO: Add aiofiles for true async file I/O
# try:
#     import aiofiles
#     import aiofiles.os
#     HAS_ASYNC = True
# except ImportError:
#     HAS_ASYNC = False
HAS_ASYNC = False

__all__ = [
    "HAS_ASYNC",
    "LOGGING_LEVEL",
    "SUCCESS_LEVEL",
    "TRACE_LEVEL",
    "LogManager",
    "list_available_presets",
]

# Custom log levels
TRACE_LEVEL = 5  # Below DEBUG (10) - for HTTP traces, detailed diagnostics
SUCCESS_LEVEL = 25  # Between INFO (20) and WARNING (30)

LOGGING_LEVEL = SimpleNamespace(
    TRACE=TRACE_LEVEL,
    DEBUG=logging.DEBUG,
    INFO=logging.INFO,
    SUCCESS=SUCCESS_LEVEL,
    WARNING=logging.WARNING,
    ERROR=logging.ERROR,
    CRITICAL=logging.CRITICAL,
)

# Levels accepted in kstlib.logging.modules entries (case-insensitive). Any
# value outside this set is rejected with a WARNING and the entry is skipped.
_VALID_LEVEL_NAMES: frozenset[str] = frozenset(
    {"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"},
)

# Module names accepted in kstlib.logging.modules entries must start with this
# prefix to prevent users from configuring loggers outside the kstlib
# hierarchy by accident (or maliciously).
_KSTLIB_LOGGER_PREFIX = "kstlib."

# Internal logger for LogManager bootstrap diagnostics. Uses native Python
# logging with a name OUTSIDE the kstlib hierarchy so it is never captured by
# LogManager itself when register=True (prevents recursion). Activate via:
#   logging.getLogger("kstlib_logging_internal").setLevel(logging.DEBUG)
_internal_log = logging.getLogger("kstlib_logging_internal")

# Preset fallbacks used when configuration file does not define any
FALLBACK_PRESETS: dict[str, dict[str, Any]] = {
    "dev": {
        "output": "console",
        "console": {"level": "DEBUG", "show_path": True},
        "icons": {"show": True},
        "file": {"level": "DEBUG"},
    },
    "prod": {
        "output": "file",
        "console": {"level": "WARNING", "show_path": False, "tracebacks_show_locals": False},
        "file": {"level": "INFO"},
        "icons": {"show": False},
    },
    "debug": {
        "output": "both",
        "console": {"level": "TRACE", "show_path": True, "tracebacks_show_locals": True},
        "file": {"level": "TRACE"},
        "icons": {"show": True},
    },
}


def list_available_presets() -> list[str]:
    """Return the list of logging preset names available to ``LogManager``.

    Merges the built-in fallback presets (``dev``, ``prod``, ``debug``) with
    the presets declared under ``logger.presets`` in ``kstlib.conf.yml``.
    User-defined presets override built-ins with the same name.

    Returns:
        Sorted list of unique preset names. Falls back to the built-in
        names when the configuration cannot be read (silent on all errors).

    Examples:
        >>> names = list_available_presets()
        >>> "prod" in names
        True

    """
    names: set[str] = set(FALLBACK_PRESETS.keys())
    try:
        config = get_config()
        logger_section = config.get("logger", {})  # type: ignore[no-untyped-call]
        config_presets = logger_section.get("presets") if logger_section else None
        if config_presets:
            names.update(config_presets.keys())
    except Exception as exc:
        # Silent by design: fall back to built-in presets. Raising here
        # would break the host application through a helper function.
        # Exception type surfaces on the internal logger (default off) so
        # operators activating it for diagnostics see the cause.
        _internal_log.debug(
            "[INIT] list_available_presets fell back to built-ins: %s",
            type(exc).__name__,
        )
    return sorted(names)


def _validate_log_file_path(file_path: Path) -> Path:
    """Validate and sanitize log file path.

    Applies hardcoded security limits regardless of user configuration.

    Args:
        file_path: The log file path to validate.

    Returns:
        The validated and resolved path.

    Raises:
        ValueError: If path violates security constraints.

    """
    # Convert to string for length checks
    path_str = str(file_path)

    # Check total path length
    if len(path_str) > HARD_MAX_FILE_PATH_LENGTH:
        raise ValueError(f"Log file path exceeds maximum length of {HARD_MAX_FILE_PATH_LENGTH} characters")

    # Check file name length
    if len(file_path.name) > HARD_MAX_FILE_NAME_LENGTH:
        raise ValueError(f"Log file name exceeds maximum length of {HARD_MAX_FILE_NAME_LENGTH} characters")

    # Check for forbidden path components (path traversal prevention)
    for part in file_path.parts:
        if part in FORBIDDEN_PATH_COMPONENTS:
            raise ValueError(f"Log file path contains forbidden component: {part!r}")

    # Check file extension
    suffix = file_path.suffix.lower()
    if suffix not in ALLOWED_LOG_EXTENSIONS:
        raise ValueError(
            f"Log file extension {suffix!r} not allowed. "
            f"Allowed: {', '.join(sorted(ALLOWED_LOG_EXTENSIONS)) or '(no extension)'}"
        )

    return file_path.resolve()


# Default configuration fallback when config file is missing or incomplete
FALLBACK_DEFAULTS = {
    "output": "both",  # console | file | both
    "theme": {
        "trace": "medium_purple4 on dark_olive_green1",
        "debug": "black on deep_sky_blue1",
        "info": "sky_blue1",
        "success": "black on sea_green3",
        "warning": "bold white on salmon1",
        "error": "bold white on deep_pink2",
        "critical": "blink bold white on red3",
    },
    "icons": {
        "show": True,
        "trace": "🔬",
        "debug": "🔎",
        "info": "📄",
        "success": "✅",
        "warning": "🚨",
        "error": "❌",
        "critical": "💀",
    },
    "console": {
        "level": "DEBUG",
        "datefmt": "%Y-%m-%d %H:%M:%S",
        "format": "::: PID %(process)d / TID %(thread)d ::: %(message)s",
        "show_path": True,
        "tracebacks_show_locals": False,
    },
    "file": {
        "level": "DEBUG",
        "datefmt": "%Y-%m-%d %H:%M:%S",
        "format": "[%(asctime)s | %(levelname)-8s] ::: PID %(process)d / TID %(thread)d ::: %(message)s",
        "log_path": "./",
        "log_dir": "logs",
        "log_name": "kstlib.log",
        "log_dir_auto_create": True,
    },
    "rotation": {
        "when": "midnight",
        "interval": 1,
        "backup_count": 7,
    },
}


class LogManager(logging.Logger):
    """Rich-based logger with async-friendly wrappers and flexible configuration.

    Supports multiple configuration sources with priority order (lowest to highest):
    1. Built-in defaults (module fallback)
    2. Built-in presets
    3. ``logger.defaults`` from configuration file
    4. ``logger.presets[<name>]`` from configuration file
    5. Remaining ``logger`` keys from configuration file (global overrides)
    6. Explicit ``config`` parameter (constructor argument)

    Args:
        name: Logger name (default: "kstlib")
        config: Explicit configuration dict/Box
        preset: Preset name ("dev", "prod", "debug", or custom from config)
        register: When ``True``, register this instance as the global root
            of the ``"kstlib"`` logger hierarchy. The instance is injected
            into ``logging.Logger.manager.loggerDict`` so ``logging.getLogger("kstlib")``
            returns the same object, ``.trace()`` and ``.success()`` are
            installed on the base ``logging.Logger`` class (so child loggers
            returned by ``logging.getLogger("kstlib.foo")`` also support them),
            and the ``TRACE_LEVEL`` is propagated to all pre-existing
            ``"kstlib.*"`` child loggers. Defaults to ``False``, which produces
            an isolated instance suitable for local use and tests.

    Example:
        >>> logger = LogManager(preset="dev")  # doctest: +SKIP
        >>> logger.info("Server started", host="localhost", port=8080)  # doctest: +SKIP
        >>> logger.success("Connection established")  # doctest: +SKIP

        Global bootstrap used by ``init_logging()``::

            LogManager(preset="dev", register=True)  # doctest: +SKIP

    """

    def __init__(
        self,
        name: str = "kstlib",
        config: Box | dict[str, Any] | None = None,
        preset: str | None = None,
        register: bool = False,
    ) -> None:
        """Initialize LogManager with configuration priority chain.

        Args:
            name: Logger name (default: "kstlib").
            config: Explicit configuration dict/Box.
            preset: Preset name ("dev", "prod", "debug", or custom from config).
            register: When ``True``, register this instance as the global
                kstlib root logger (see class docstring for details). When
                ``False`` (default), the instance stays isolated and does not
                affect ``logging.getLogger("kstlib")``.

        """
        super().__init__(name)
        logging.addLevelName(TRACE_LEVEL, "TRACE")
        logging.addLevelName(SUCCESS_LEVEL, "SUCCESS")

        # Load configuration with priority chain
        self._config = self._load_config(config, preset)

        # Resolve per-module level overrides (kstlib.logging.modules cascade).
        # Stored separately from _config so the YAML structure stays clean.
        self._module_levels: dict[str, str] = self._resolve_module_levels(config, preset)

        # Setup console and theme
        self.width = shutil.get_terminal_size(fallback=(120, 30)).columns
        theme = self._create_theme()
        self.console = Console(theme=theme, width=self.width)

        # Setup handlers
        self._setup_handlers()

        # Optional global bootstrap
        if register:
            self._register_as_root()
            self._apply_module_levels()

    def _register_as_root(self) -> None:
        """Inject this instance as the ``"kstlib"`` root in Python logging.

        Performs three steps in order:

        1. Patch the ``logging.Logger`` class with ``.trace()`` and ``.success()``
           methods (only once per process) so that child loggers returned by
           ``logging.getLogger("kstlib.foo")`` also support them.
        2. Register this instance under ``logging.Logger.manager.loggerDict``
           at the ``"kstlib"`` name, set ``parent`` to the root logger and
           bind the manager. ``propagate`` stays at ``True`` (Python default)
           so host applications can aggregate records at the root level and
           pytest's caplog fixture keeps working.
        3. Propagate ``TRACE_LEVEL`` to all pre-existing ``"kstlib.*"`` child
           loggers so modules already imported before the bootstrap get the
           correct level. New children inherit correctly via the hierarchy.
        """
        # 1. Patch logging.Logger class (once per process)
        if not hasattr(logging.Logger, "trace"):

            def _trace(self: logging.Logger, msg: object, *args: object, **kwargs: Any) -> None:
                if self.isEnabledFor(TRACE_LEVEL):
                    self._log(TRACE_LEVEL, msg, args, **kwargs)

            logging.Logger.trace = _trace  # type: ignore[attr-defined]

        if not hasattr(logging.Logger, "success"):

            def _success(self: logging.Logger, msg: object, *args: object, **kwargs: Any) -> None:
                if self.isEnabledFor(SUCCESS_LEVEL):
                    self._log(SUCCESS_LEVEL, msg, args, **kwargs)

            logging.Logger.success = _success  # type: ignore[attr-defined]

        # 2. Register in Python's logging manager
        self.parent = logging.root
        self.propagate = True
        self.manager = logging.Logger.manager
        logging.Logger.manager.loggerDict[self.name] = self

        # 3. Propagate level to pre-existing children
        prefix = f"{self.name}."
        for logger_name in list(logging.Logger.manager.loggerDict):
            if logger_name.startswith(prefix):
                child_logger = logging.getLogger(logger_name)
                child_logger.setLevel(TRACE_LEVEL)

    @staticmethod
    def _resolve_module_levels(
        config: Box | dict[str, Any] | None,
        preset: str | None,
    ) -> dict[str, str]:
        """Resolve the effective per-module log-level mapping.

        Cascade (lowest to highest priority):
            1. ``kstlib.logging.modules`` from the global config file
            2. ``logger.presets.<active>.modules`` from the global config file
            3. ``modules`` key in the explicit ``config`` argument

        Step 3 ECHOes a CLI override and, when present, replaces all earlier
        layers (no merge). Steps 1 and 2 are merged key-by-key with step 2
        winning on shared keys.

        Args:
            config: Explicit configuration dict/Box passed to the constructor.
            preset: Active preset name (used to resolve step 2).

        Returns:
            A flat mapping of logger name (e.g. ``"kstlib.rapi.config"``) to
            level name (e.g. ``"WARNING"``). Empty when no source is set.

        """
        if config is not None and "modules" in config:
            explicit = config["modules"]
            if explicit is None:
                return {}
            return {str(k): str(v) for k, v in dict(explicit).items()}

        merged: dict[str, str] = {}
        try:
            global_config = get_config()
        except (FileNotFoundError, KeyError):
            return merged

        kstlib_section = global_config.get("kstlib")  # type: ignore[no-untyped-call]
        logging_section = kstlib_section.get("logging") if kstlib_section else None
        global_modules = logging_section.get("modules") if logging_section else None
        if global_modules:
            merged.update({str(k): str(v) for k, v in dict(global_modules).items()})

        if preset:
            logger_section = global_config.get("logger")  # type: ignore[no-untyped-call]
            presets = logger_section.get("presets") if logger_section else None
            preset_section = presets.get(preset) if presets else None
            preset_modules = preset_section.get("modules") if preset_section else None
            if preset_modules:
                merged.update({str(k): str(v) for k, v in dict(preset_modules).items()})

        return merged

    def _apply_module_levels(self) -> None:
        """Apply per-module level overrides resolved by :meth:`_resolve_module_levels`.

        Each entry is validated:

        - The logger name must start with ``"kstlib."`` (otherwise the entry
          is skipped with a ``WARNING [SECURITY]`` log so users notice when
          they try to configure their own application loggers through the
          kstlib YAML).
        - The level must be one of the seven supported names (TRACE, DEBUG,
          INFO, SUCCESS, WARNING, ERROR, CRITICAL).

        Invalid entries never abort the bootstrap: they are reported and
        skipped, so a typo in one entry does not break the whole logger.
        """
        if not self._module_levels:
            return

        for logger_name, level_name in self._module_levels.items():
            if not logger_name.startswith(_KSTLIB_LOGGER_PREFIX):
                _internal_log.warning(
                    "[SECURITY] Invalid logger name %r in kstlib.logging.modules: must start with %r, skipped",
                    logger_name,
                    _KSTLIB_LOGGER_PREFIX,
                )
                continue

            level_upper = level_name.upper()
            if level_upper not in _VALID_LEVEL_NAMES:
                _internal_log.warning(
                    "Invalid level %r for logger %r in kstlib.logging.modules: expected one of %s, skipped",
                    level_name,
                    logger_name,
                    sorted(_VALID_LEVEL_NAMES),
                )
                continue

            level_value = getattr(LOGGING_LEVEL, level_upper)
            logging.getLogger(logger_name).setLevel(level_value)
            _internal_log.debug(
                "[INIT] Applied module override: %s=%s",
                logger_name,
                level_upper,
            )

    def _load_config(self, config: Box | dict[str, Any] | None, preset: str | None) -> Box:
        """Load configuration with priority chain.

        Priority (lowest to highest):
            1. Built-in defaults (module fallback)
            2. Built-in presets
            3. ``logger.defaults`` from configuration file
            4. ``logger.presets[<name>]`` from configuration file
            5. Remaining ``logger`` keys from configuration file (global overrides)
            6. Explicit ``config`` parameter

        Args:
            config: Explicit configuration
            preset: Preset name

        Returns:
            Merged configuration as Box

        """
        merged = Box(FALLBACK_DEFAULTS, default_box=True)

        # Apply fallback preset if requested
        preset_config = self._resolve_preset(preset, FALLBACK_PRESETS)
        if preset_config is not None:
            merged.merge_update(preset_config)

        # Load from kstlib.conf.yml
        try:
            global_config = get_config()
        except (FileNotFoundError, KeyError):
            global_config = None

        if global_config and "logger" in global_config:
            logger_config = global_config.logger

            defaults = logger_config.get("defaults")
            config_presets = logger_config.get("presets")
            overrides = {key: value for key, value in logger_config.items() if key not in {"defaults", "presets"}}

            if defaults is not None:
                merged.merge_update(Box(defaults, default_box=True))

            preset_from_config = self._resolve_preset(preset, config_presets)
            if preset_from_config is not None:
                merged.merge_update(preset_from_config)

            if overrides:
                merged.merge_update(Box(overrides, default_box=True))

        # Apply explicit config (highest priority)
        if config:
            if isinstance(config, dict):
                config = Box(config, default_box=True)
            merged.merge_update(config)

        return merged

    @staticmethod
    def _resolve_preset(
        preset: str | None,
        presets: dict[str, Any] | Box | None,
    ) -> Box | None:
        """Return the preset configuration if available.

        Args:
            preset: Requested preset name.
            presets: Mapping of preset names to configuration dictionaries.

        Returns:
            Box with preset configuration, or ``None`` if not found.

        """
        if not preset or not presets:
            return None

        candidate = presets.get(preset)
        if candidate is None:
            return None
        return candidate if isinstance(candidate, Box) else Box(candidate, default_box=True)

    def _create_theme(self) -> Theme:
        """Create Rich theme from config.

        Returns:
            Rich Theme with logging level colors

        """
        theme_config = self._config.theme
        return Theme(
            {
                "logging.level.trace": theme_config.trace,
                "logging.level.debug": theme_config.debug,
                "logging.level.info": theme_config.info,
                "logging.level.success": theme_config.success,
                "logging.level.warning": theme_config.warning,
                "logging.level.error": theme_config.error,
                "logging.level.critical": theme_config.critical,
            }
        )

    def _setup_handlers(self) -> None:
        """Set up console and/or file handlers based on config."""
        # Clear existing handlers to prevent duplication on re-initialization
        # (Python loggers are singletons by name, so handlers accumulate)
        self.handlers.clear()

        self.setLevel(TRACE_LEVEL)  # Allow all levels, handlers filter
        output = self._config.output.lower()

        # Console handler
        if output in ("console", "both"):
            self._setup_console_handler()

        # File handler
        if output in ("file", "both"):
            self._setup_file_handler()

    def _setup_console_handler(self) -> None:
        """Set up the Rich console handler."""
        console_config = self._config.console
        rich_handler = RichHandler(
            console=self.console,
            show_path=console_config.get("show_path", True),
            markup=True,
            tracebacks_show_locals=console_config.get("tracebacks_show_locals", False),
        )
        rich_handler.setFormatter(logging.Formatter(console_config.format, datefmt=console_config.datefmt))
        level = console_config.level.upper()
        rich_handler.setLevel(getattr(LOGGING_LEVEL, level, logging.DEBUG))
        self.addHandler(rich_handler)

    def _setup_file_handler(self) -> None:
        """Set up the file handler with rotation.

        Supports two configuration styles:
            - New style: ``file.file_path`` (single path, recommended)
            - Legacy style: ``file.log_path`` + ``file.log_dir`` + ``file.log_name``

        The new style takes priority if ``file_path`` is defined.
        """
        file_config = self._config.file
        rotation_config = self._config.rotation

        # Build log file path (new style takes priority)
        file_path_value = file_config.get("file_path")
        if file_path_value:
            # New style: single file_path
            log_file = Path(file_path_value)
        else:
            # Legacy style: log_path / log_dir / log_name
            log_path = Path(file_config.get("log_path", "./"))
            log_dir = file_config.get("log_dir", "logs")
            log_name = file_config.get("log_name", "kstlib.log")
            log_file = log_path / log_dir / log_name

        # Validate path (deep defense - hardcoded limits)
        log_file = _validate_log_file_path(log_file)

        # Determine auto_create setting (support both new and legacy names)
        auto_create = file_config.get(
            "auto_create_dir",
            file_config.get("log_dir_auto_create", True),
        )

        # Create directory if needed with proper permissions
        if auto_create:
            log_file.parent.mkdir(parents=True, exist_ok=True, mode=0o755)

        # Create file handler with rotation
        file_handler = TimedRotatingFileHandler(
            log_file,
            when=rotation_config.when,
            interval=rotation_config.interval,
            backupCount=rotation_config.backup_count,
            encoding="utf-8",
            delay=False,  # Create file immediately for better debugging
        )
        file_handler.setFormatter(logging.Formatter(file_config.format, datefmt=file_config.datefmt))
        level = file_config.level.upper()
        file_handler.setLevel(getattr(LOGGING_LEVEL, level, logging.DEBUG))
        self.addHandler(file_handler)

    def _format_with_icon(self, level: str, msg: str) -> str:
        """Add icon to message if enabled.

        Args:
            level: Log level name (debug, info, success, etc.)
            msg: Log message

        Returns:
            Formatted message with icon

        """
        icons = self._config.icons
        if not icons.show:
            return msg
        icon = icons.get(level, "")
        return f"{icon}  {msg}" if icon else msg

    @staticmethod
    def _sanitize_log_value(value: Any) -> str:
        """Strip control characters from log values to prevent log injection.

        Removes CRLF sequences and ANSI escape codes that could be used
        to forge log entries or manipulate terminal output.

        Args:
            value: Value to sanitize.

        Returns:
            Sanitized string representation.

        """
        text = str(value)
        # Strip ANSI escape sequences (CSI and OSC)
        text = _ANSI_CSI_PATTERN.sub("", text)
        text = _ANSI_OSC_PATTERN.sub("", text)
        # Replace control characters (CR, LF, tab, etc.) with space
        text = _CONTROL_CHAR_PATTERN.sub(" ", text)
        return text

    def _format_structured(self, msg: str, **context: Any) -> str:
        """Format message with structured context.

        Args:
            msg: Base message
            **context: Key-value context pairs

        Returns:
            Formatted message with context

        """
        if not context:
            return msg
        ctx_str = " | ".join(f"{k}={self._sanitize_log_value(v)}" for k, v in context.items())
        return f"{self._sanitize_log_value(msg)} | {ctx_str}"

    @staticmethod
    def _split_log_kwargs(kwargs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """Separate structured context from logging kwargs.

        Args:
            kwargs: Keyword arguments received by the public logging method.

        Returns:
            A tuple containing the structured context dictionary and the kwargs
            that should be forwarded to the underlying logging call.

        """
        reserved = {"exc_info", "stack_info", "stacklevel", "extra"}
        context: dict[str, Any] = {}
        log_kwargs: dict[str, Any] = {}
        for key, value in kwargs.items():
            if key in reserved:
                log_kwargs[key] = value
            else:
                context[key] = value
        return context, log_kwargs

    def _prepare_message(self, level: str, msg: object, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Return formatted message and logging kwargs for emission."""
        msg_str = str(msg)
        context, log_kwargs = self._split_log_kwargs(kwargs)
        formatted = self._format_structured(msg_str, **context)
        formatted = self._format_with_icon(level, formatted)
        return formatted, log_kwargs

    # Synchronous logging methods

    def trace(self, msg: object, *args: object, **kwargs: Any) -> None:
        """Log trace message (custom level 5, below DEBUG).

        Use for detailed HTTP traces, protocol dumps, and low-level diagnostics.

        Args:
            msg: Log message
            *args: Format args
            **kwargs: Context key=value pairs

        """
        if self.isEnabledFor(TRACE_LEVEL):
            formatted, log_kwargs = self._prepare_message("trace", msg, kwargs)
            log_kwargs.setdefault("stacklevel", 2)
            self._log(TRACE_LEVEL, formatted, args, **log_kwargs)

    def debug(self, msg: object, *args: object, **kwargs: Any) -> None:
        """Log debug message.

        Args:
            msg: Log message
            *args: Format args
            **kwargs: Context key=value pairs

        """
        formatted, log_kwargs = self._prepare_message("debug", msg, kwargs)
        log_kwargs.setdefault("stacklevel", 2)
        super().debug(formatted, *args, **log_kwargs)

    def info(self, msg: object, *args: object, **kwargs: Any) -> None:
        """Log info message.

        Args:
            msg: Log message
            *args: Format args
            **kwargs: Context key=value pairs

        """
        formatted, log_kwargs = self._prepare_message("info", msg, kwargs)
        log_kwargs.setdefault("stacklevel", 2)
        super().info(formatted, *args, **log_kwargs)

    def success(self, msg: object, *args: object, **kwargs: Any) -> None:
        """Log success message (custom level 25).

        Args:
            msg: Log message
            *args: Format args
            **kwargs: Context key=value pairs

        """
        if self.isEnabledFor(SUCCESS_LEVEL):
            formatted, log_kwargs = self._prepare_message("success", msg, kwargs)
            log_kwargs.setdefault("stacklevel", 2)
            self._log(SUCCESS_LEVEL, formatted, args, **log_kwargs)

    def warning(self, msg: object, *args: object, **kwargs: Any) -> None:
        """Log warning message.

        Args:
            msg: Log message
            *args: Format args
            **kwargs: Context key=value pairs

        """
        formatted, log_kwargs = self._prepare_message("warning", msg, kwargs)
        log_kwargs.setdefault("stacklevel", 2)
        super().warning(formatted, *args, **log_kwargs)

    def error(self, msg: object, *args: object, **kwargs: Any) -> None:
        """Log error message.

        Args:
            msg: Log message
            *args: Format args
            **kwargs: Context key=value pairs

        """
        formatted, log_kwargs = self._prepare_message("error", msg, kwargs)
        log_kwargs.setdefault("stacklevel", 2)
        super().error(formatted, *args, **log_kwargs)

    def critical(self, msg: object, *args: object, **kwargs: Any) -> None:
        """Log critical message.

        Args:
            msg: Log message
            *args: Format args
            **kwargs: Context key=value pairs

        """
        formatted, log_kwargs = self._prepare_message("critical", msg, kwargs)
        log_kwargs.setdefault("stacklevel", 2)
        super().critical(formatted, *args, **log_kwargs)

    def traceback(self, exc: BaseException) -> None:
        """Print Rich traceback, respecting the configured show_locals setting.

        Args:
            exc: Exception to display

        """
        show_locals = self._config.console.get("tracebacks_show_locals", False)
        self.console.print(
            Traceback.from_exception(
                type(exc),
                exc,
                exc.__traceback__,
                show_locals=show_locals,
                width=self.width,
                extra_lines=13,
            )
        )

    @property
    def has_native_async_support(self) -> bool:
        """Return whether native async logs are available."""
        return HAS_ASYNC

    # Async logging methods (TODO: implement with aiofiles)

    async def atrace(self, msg: str, **context: Any) -> None:
        """Async trace wrapper executed via thread pool."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, partial(self.trace, msg, **context))

    async def adebug(self, msg: str, **context: Any) -> None:
        """Async debug wrapper executed via thread pool."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, partial(self.debug, msg, **context))

    async def ainfo(self, msg: str, **context: Any) -> None:
        """Async info wrapper executed via thread pool."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, partial(self.info, msg, **context))

    async def asuccess(self, msg: str, **context: Any) -> None:
        """Async success wrapper executed via thread pool."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, partial(self.success, msg, **context))

    async def awarning(self, msg: str, **context: Any) -> None:
        """Async warning wrapper executed via thread pool."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, partial(self.warning, msg, **context))

    async def aerror(self, msg: str, **context: Any) -> None:
        """Async error wrapper executed via thread pool."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, partial(self.error, msg, **context))

    async def acritical(self, msg: str, **context: Any) -> None:
        """Async critical wrapper executed via thread pool."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, partial(self.critical, msg, **context))
