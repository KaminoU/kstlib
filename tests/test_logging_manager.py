"""Tests for kstlib.logging.manager module."""

from __future__ import annotations

import logging
from collections.abc import Generator
from pathlib import Path

import pytest

from kstlib.logging.manager import (
    FALLBACK_PRESETS,
    LOGGING_LEVEL,
    SUCCESS_LEVEL,
    TRACE_LEVEL,
    LogManager,
)


class TestLogLevels:
    """Tests for custom log levels."""

    def test_trace_level_value(self) -> None:
        """Test TRACE_LEVEL is below DEBUG."""
        assert TRACE_LEVEL == 5
        assert TRACE_LEVEL < logging.DEBUG

    def test_success_level_value(self) -> None:
        """Test SUCCESS_LEVEL is between INFO and WARNING."""
        assert SUCCESS_LEVEL == 25
        assert logging.INFO < SUCCESS_LEVEL < logging.WARNING

    def test_logging_level_namespace_has_trace(self) -> None:
        """Test LOGGING_LEVEL includes TRACE."""
        assert hasattr(LOGGING_LEVEL, "TRACE")
        assert LOGGING_LEVEL.TRACE == TRACE_LEVEL

    def test_logging_level_namespace_order(self) -> None:
        """Test log level ordering is correct."""
        assert LOGGING_LEVEL.TRACE < LOGGING_LEVEL.DEBUG
        assert LOGGING_LEVEL.DEBUG < LOGGING_LEVEL.INFO
        assert LOGGING_LEVEL.INFO < LOGGING_LEVEL.SUCCESS
        assert LOGGING_LEVEL.SUCCESS < LOGGING_LEVEL.WARNING
        assert LOGGING_LEVEL.WARNING < LOGGING_LEVEL.ERROR
        assert LOGGING_LEVEL.ERROR < LOGGING_LEVEL.CRITICAL


class TestLogManagerTrace:
    """Tests for LogManager trace functionality."""

    def test_trace_level_registered(self) -> None:
        """Test that TRACE level is registered with logging module."""
        logger = LogManager(config={"output": "console", "console": {"level": "TRACE"}})
        assert logging.getLevelName(TRACE_LEVEL) == "TRACE"
        assert logging.getLevelName("TRACE") == TRACE_LEVEL
        # Cleanup handlers
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

    def test_trace_method_exists(self) -> None:
        """Test LogManager has trace method."""
        logger = LogManager(config={"output": "console", "console": {"level": "TRACE"}})
        assert hasattr(logger, "trace")
        assert callable(logger.trace)
        # Cleanup handlers
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

    def test_atrace_method_exists(self) -> None:
        """Test LogManager has async atrace method."""
        logger = LogManager(config={"output": "console", "console": {"level": "TRACE"}})
        assert hasattr(logger, "atrace")
        assert callable(logger.atrace)
        # Cleanup handlers
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

    def test_trace_is_enabled_at_trace_level(self) -> None:
        """Test trace messages are enabled when level is TRACE."""
        logger = LogManager(config={"output": "console", "console": {"level": "TRACE"}})
        assert logger.isEnabledFor(TRACE_LEVEL)
        # Cleanup handlers
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

    def test_trace_is_disabled_at_debug_level(self) -> None:
        """Test trace messages are disabled when level is DEBUG."""
        logger = LogManager(config={"output": "console", "console": {"level": "DEBUG"}})
        # Logger level is TRACE but handler level is DEBUG
        # So trace should still be enabled for the logger
        assert logger.isEnabledFor(TRACE_LEVEL)
        # Cleanup handlers
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)


class TestLogManagerTraceOutput:
    """Tests for trace output formatting."""

    @pytest.fixture
    def capture_logger(self) -> Generator[LogManager, None, None]:
        """Create a logger that captures output."""
        logger = LogManager(
            config={
                "output": "console",
                "console": {"level": "TRACE"},
                "icons": {"show": False},
            }
        )
        yield logger
        # Cleanup handlers
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

    def test_trace_with_context(self, capture_logger: LogManager) -> None:
        """Test trace message with structured context."""
        # We can't easily capture Rich output, but we can verify no exception
        capture_logger.trace("HTTP request", method="GET", url="https://example.com")

    def test_trace_without_context(self, capture_logger: LogManager) -> None:
        """Test trace message without context."""
        capture_logger.trace("Simple trace message")


class TestLogManagerTraceAsync:
    """Tests for async trace functionality."""

    @pytest.mark.asyncio
    async def test_atrace_executes(self) -> None:
        """Test atrace method executes without error."""
        logger = LogManager(
            config={
                "output": "console",
                "console": {"level": "TRACE"},
                "icons": {"show": False},
            }
        )
        try:
            await logger.atrace("Async trace message", key="value")
        finally:
            # Cleanup handlers
            for handler in logger.handlers[:]:
                logger.removeHandler(handler)


class TestLogManagerThemeAndIcons:
    """Tests for trace theme and icons in defaults."""

    def test_trace_in_default_theme(self) -> None:
        """Test trace is in default theme configuration."""
        from kstlib.logging.manager import FALLBACK_DEFAULTS

        theme = FALLBACK_DEFAULTS["theme"]
        assert isinstance(theme, dict)
        assert "trace" in theme
        assert theme["trace"] == "medium_purple4 on dark_olive_green1"

    def test_trace_in_default_icons(self) -> None:
        """Test trace icon is in default icons configuration."""
        from kstlib.logging.manager import FALLBACK_DEFAULTS

        icons = FALLBACK_DEFAULTS["icons"]
        assert isinstance(icons, dict)
        assert "trace" in icons
        assert icons["trace"] == "🔬"


class TestValidateLogFilePath:
    """Tests for _validate_log_file_path function."""

    def test_valid_path_returns_resolved(self, tmp_path: Path) -> None:
        """Test valid path is resolved and returned."""
        from kstlib.logging.manager import _validate_log_file_path

        log_file = tmp_path / "app.log"
        result = _validate_log_file_path(log_file)
        assert result == log_file.resolve()

    def test_valid_path_no_extension(self, tmp_path: Path) -> None:
        """Test path without extension is allowed."""
        from kstlib.logging.manager import _validate_log_file_path

        log_file = tmp_path / "logfile"
        result = _validate_log_file_path(log_file)
        assert result == log_file.resolve()

    def test_valid_path_txt_extension(self, tmp_path: Path) -> None:
        """Test .txt extension is allowed."""
        from kstlib.logging.manager import _validate_log_file_path

        log_file = tmp_path / "debug.txt"
        result = _validate_log_file_path(log_file)
        assert result == log_file.resolve()

    def test_valid_path_json_extension(self, tmp_path: Path) -> None:
        """Test .json extension is allowed."""
        from kstlib.logging.manager import _validate_log_file_path

        log_file = tmp_path / "structured.json"
        result = _validate_log_file_path(log_file)
        assert result == log_file.resolve()

    def test_rejects_path_traversal_dotdot(self, tmp_path: Path) -> None:
        """Test path with .. is rejected (path traversal prevention)."""
        from kstlib.logging.manager import _validate_log_file_path

        log_file = tmp_path / ".." / "escape.log"
        with pytest.raises(ValueError, match="forbidden component"):
            _validate_log_file_path(log_file)

    def test_rejects_path_with_tilde(self) -> None:
        """Test path with ~ is rejected."""
        from kstlib.logging.manager import _validate_log_file_path

        log_file = Path("~") / "logs" / "app.log"
        with pytest.raises(ValueError, match="forbidden component"):
            _validate_log_file_path(log_file)

    def test_rejects_invalid_extension(self, tmp_path: Path) -> None:
        """Test invalid extension is rejected."""
        from kstlib.logging.manager import _validate_log_file_path

        log_file = tmp_path / "malicious.exe"
        with pytest.raises(ValueError, match="not allowed"):
            _validate_log_file_path(log_file)

    def test_rejects_py_extension(self, tmp_path: Path) -> None:
        """Test .py extension is rejected."""
        from kstlib.logging.manager import _validate_log_file_path

        log_file = tmp_path / "inject.py"
        with pytest.raises(ValueError, match="not allowed"):
            _validate_log_file_path(log_file)

    def test_rejects_too_long_filename(self, tmp_path: Path) -> None:
        """Test filename exceeding 255 chars is rejected."""
        from kstlib.logging.manager import _validate_log_file_path

        long_name = "a" * 300 + ".log"
        log_file = tmp_path / long_name
        with pytest.raises(ValueError, match="file name exceeds maximum"):
            _validate_log_file_path(log_file)

    def test_rejects_too_long_path(self) -> None:
        """Test path exceeding 4096 chars is rejected."""
        from kstlib.logging.manager import _validate_log_file_path

        # Create path with many nested directories
        long_path = Path("/") / "/".join(["a" * 100] * 50) / "file.log"
        with pytest.raises(ValueError, match="path exceeds maximum"):
            _validate_log_file_path(long_path)


class TestFilePathConfig:
    """Tests for file_path configuration style."""

    def test_new_style_file_path_creates_file(self, tmp_path: Path) -> None:
        """Test new style file_path creates log file in specified location."""
        log_file = tmp_path / "custom" / "myapp.log"
        logger = LogManager(
            config={
                "output": "file",
                "file": {
                    "level": "DEBUG",
                    "file_path": str(log_file),
                    "auto_create_dir": True,
                },
            }
        )
        try:
            logger.info("Test message")
            assert log_file.exists()
        finally:
            for handler in logger.handlers[:]:
                handler.close()
                logger.removeHandler(handler)

    def test_legacy_style_still_works(self, tmp_path: Path) -> None:
        """Test legacy log_path/log_dir/log_name style still works."""
        logger = LogManager(
            config={
                "output": "file",
                "file": {
                    "level": "DEBUG",
                    "log_path": str(tmp_path),
                    "log_dir": "oldstyle",
                    "log_name": "legacy.log",
                    "log_dir_auto_create": True,
                },
            }
        )
        try:
            logger.info("Legacy test")
            expected_file = tmp_path / "oldstyle" / "legacy.log"
            assert expected_file.exists()
        finally:
            for handler in logger.handlers[:]:
                handler.close()
                logger.removeHandler(handler)

    def test_file_path_takes_priority_over_legacy(self, tmp_path: Path) -> None:
        """Test file_path takes priority when both styles are specified."""
        new_file = tmp_path / "new" / "priority.log"
        logger = LogManager(
            config={
                "output": "file",
                "file": {
                    "level": "DEBUG",
                    "file_path": str(new_file),
                    "auto_create_dir": True,
                    # Legacy settings should be ignored
                    "log_path": str(tmp_path),
                    "log_dir": "ignored",
                    "log_name": "ignored.log",
                },
            }
        )
        try:
            logger.info("Priority test")
            assert new_file.exists()
            # Legacy path should NOT exist
            legacy_file = tmp_path / "ignored" / "ignored.log"
            assert not legacy_file.exists()
        finally:
            for handler in logger.handlers[:]:
                handler.close()
                logger.removeHandler(handler)

    def test_auto_create_dir_new_style(self, tmp_path: Path) -> None:
        """Test auto_create_dir works with new style."""
        log_file = tmp_path / "deep" / "nested" / "dirs" / "app.log"
        logger = LogManager(
            config={
                "output": "file",
                "file": {
                    "level": "DEBUG",
                    "file_path": str(log_file),
                    "auto_create_dir": True,
                },
            }
        )
        try:
            logger.info("Nested dirs test")
            assert log_file.exists()
        finally:
            for handler in logger.handlers[:]:
                handler.close()
                logger.removeHandler(handler)

    def test_rejects_invalid_path_in_config(self, tmp_path: Path) -> None:
        """Test invalid path in config raises ValueError."""
        with pytest.raises(ValueError, match="forbidden component"):
            LogManager(
                config={
                    "output": "file",
                    "file": {
                        "level": "DEBUG",
                        "file_path": str(tmp_path / ".." / "escape.log"),
                    },
                }
            )


class TestFallbackPresetsTracebacks:
    """Tests for tracebacks_show_locals in FALLBACK_PRESETS."""

    def test_prod_preset_hides_locals(self) -> None:
        """Prod preset should disable tracebacks_show_locals."""
        prod_console: dict[str, object] = FALLBACK_PRESETS["prod"]["console"]  # type: ignore[assignment]
        assert prod_console["tracebacks_show_locals"] is False

    def test_debug_preset_shows_locals(self) -> None:
        """Debug preset should enable tracebacks_show_locals."""
        debug_console: dict[str, object] = FALLBACK_PRESETS["debug"]["console"]  # type: ignore[assignment]
        assert debug_console["tracebacks_show_locals"] is True

    def test_dev_preset_inherits_secure_default(self) -> None:
        """Dev preset should not set tracebacks_show_locals (inherits False default)."""
        dev_console: dict[str, object] = FALLBACK_PRESETS["dev"]["console"]  # type: ignore[assignment]
        assert "tracebacks_show_locals" not in dev_console

    def test_prod_preset_rich_handler(self) -> None:
        """Prod preset should produce RichHandler with show_locals=False."""
        logger = LogManager(preset="prod")
        from rich.logging import RichHandler

        rich_handlers = [h for h in logger.handlers if isinstance(h, RichHandler)]
        for handler in rich_handlers:
            assert handler.tracebacks_show_locals is False

    def test_debug_preset_rich_handler(self) -> None:
        """Debug preset should produce RichHandler with show_locals=True."""
        logger = LogManager(preset="debug")
        from rich.logging import RichHandler

        rich_handlers = [h for h in logger.handlers if isinstance(h, RichHandler)]
        assert len(rich_handlers) >= 1
        for handler in rich_handlers:
            assert handler.tracebacks_show_locals is True


class TestHardcodedLimits:
    """Tests for hardcoded security limits."""

    def test_limits_are_exported(self) -> None:
        """Test hardcoded limits are defined."""
        from kstlib.logging.manager import (
            ALLOWED_LOG_EXTENSIONS,
            FORBIDDEN_PATH_COMPONENTS,
            HARD_MAX_FILE_NAME_LENGTH,
            HARD_MAX_FILE_PATH_LENGTH,
        )

        assert HARD_MAX_FILE_PATH_LENGTH == 4096
        assert HARD_MAX_FILE_NAME_LENGTH == 255
        assert ".." in FORBIDDEN_PATH_COMPONENTS
        assert "~" in FORBIDDEN_PATH_COMPONENTS
        assert ".log" in ALLOWED_LOG_EXTENSIONS
        assert ".txt" in ALLOWED_LOG_EXTENSIONS
        assert ".json" in ALLOWED_LOG_EXTENSIONS
        assert "" in ALLOWED_LOG_EXTENSIONS  # No extension allowed
