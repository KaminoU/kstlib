"""Tests for the logging manager module.

This module contains comprehensive tests for LogManager class,
including presets, configuration, output modes, and structured logging.
"""

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from box import Box
from pytest import MonkeyPatch

from kstlib.logging import LogManager
from kstlib.logging import manager as logging_manager_module
from kstlib.logging.manager import TRACE_LEVEL


def test_logmanager_default_creation() -> None:
    """Test creating LogManager with default settings."""
    logger = LogManager(name="test_default")

    assert logger.name == "test_default"
    # LogManager inherits from logging.Logger
    assert isinstance(logger, logging.Logger)
    assert logger.level == TRACE_LEVEL  # Logger allows all levels, handlers filter


def test_logmanager_with_preset_dev() -> None:
    """Test LogManager with dev preset."""
    logger = LogManager(name="test_dev", preset="dev")

    assert logger.level == TRACE_LEVEL  # Logger allows all levels, handlers filter
    # Dev preset should have console handler
    assert len(logger.handlers) > 0


def test_logmanager_with_preset_prod() -> None:
    """Test LogManager with prod preset."""
    logger = LogManager(name="test_prod", preset="prod")

    # Logger level is always TRACE (handlers control filtering)
    assert logger.level == TRACE_LEVEL
    # Prod preset should have file handler only
    assert len(logger.handlers) > 0


def test_logmanager_with_preset_debug() -> None:
    """Test LogManager with debug preset."""
    logger = LogManager(name="test_debug", preset="debug")

    assert logger.level == TRACE_LEVEL  # Logger allows all levels, handlers filter
    # Debug preset should have both console and file handlers
    assert len(logger.handlers) >= 1


def test_logmanager_with_custom_config() -> None:
    """Test LogManager with custom configuration."""
    custom_config = {
        "output": "console",
        "console": {"level": "WARNING"},
    }

    logger = LogManager(name="test_custom", config=custom_config)

    # Logger level is always TRACE (handlers control filtering)
    assert logger.level == TRACE_LEVEL
    # Handler should have WARNING level
    assert logger.handlers[0].level == logging.WARNING


def test_logmanager_basic_logging_methods() -> None:
    """Test basic logging methods don't raise errors."""
    logger = LogManager(name="test_methods")

    # These should not raise exceptions
    logger.debug("Debug message")
    logger.info("Info message")
    logger.success("Success message")
    logger.warning("Warning message")
    logger.error("Error message")
    logger.critical("Critical message")


def test_logmanager_structured_logging() -> None:
    """Test structured logging with context kwargs."""
    logger = LogManager(name="test_structured")

    # Should not raise with context
    logger.info("Order placed", symbol="BTCUSDT", quantity=1.5, price=50000.0)
    logger.error("Connection failed", host="localhost", port=5432, retry=3)


def test_logmanager_traceback() -> None:
    """Test traceback logging."""
    logger = LogManager(name="test_traceback")

    try:
        _ = 1 / 0
    except ZeroDivisionError as e:
        # Should not raise
        logger.traceback(e)


def test_logmanager_file_output(tmp_path: Path) -> None:
    """Test logging to file."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    custom_config = {
        "output": "file",
        "file": {
            "log_path": str(tmp_path),
            "log_dir": "logs",
            "log_name": "test.log",
            "level": "INFO",
        },
    }

    logger = LogManager(name="test_file", config=custom_config)
    logger.info("Test message to file")

    # File should be created
    log_file = log_dir / "test.log"
    assert log_file.exists()


def test_logmanager_console_only() -> None:
    """Test console-only output."""
    custom_config = {"output": "console"}

    logger = LogManager(name="test_console", config=custom_config)

    # Should have at least one handler (console)
    assert len(logger.handlers) > 0


def test_logmanager_both_outputs(tmp_path: Path) -> None:
    """Test both console and file output."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    custom_config = {
        "output": "both",
        "file": {
            "log_path": str(tmp_path),
            "log_dir": "logs",
            "log_name": "both.log",
        },
    }

    logger = LogManager(name="test_both", config=custom_config)
    logger.info("Test message")

    # Should have multiple handlers
    assert len(logger.handlers) >= 2
    # File should exist
    log_file = log_dir / "both.log"
    assert log_file.exists()


def test_logmanager_invalid_preset() -> None:
    """Test that invalid preset falls back gracefully."""
    # Should not raise, just use defaults
    logger = LogManager(name="test_invalid", preset="nonexistent")

    assert isinstance(logger, logging.Logger)


def test_logmanager_get_logger_method() -> None:
    """Test that LogManager is itself the logger."""
    logger = LogManager(name="test_get_logger")

    # LogManager inherits from logging.Logger
    assert isinstance(logger, logging.Logger)
    assert logger.name == "test_get_logger"


def test_logmanager_name_attribute() -> None:
    """Test that name attribute is accessible."""
    logger = LogManager(name="test_name_attr")

    assert hasattr(logger, "name")
    assert logger.name == "test_name_attr"


def test_logmanager_success_level_exists() -> None:
    """Test that SUCCESS custom level is registered."""
    _ = LogManager(name="test_success_level")

    # SUCCESS level should be registered in logging module
    success_level = logging.getLevelName("SUCCESS")
    assert isinstance(success_level, int)
    # Should be between INFO and WARNING
    assert logging.INFO < success_level < logging.WARNING


def test_logmanager_multiple_instances() -> None:
    """Test creating multiple LogManager instances."""
    logger1 = LogManager(name="test_multi_1")
    logger2 = LogManager(name="test_multi_2")

    assert logger1.name != logger2.name
    assert logger1 is not logger2


def test_logmanager_uses_global_config(monkeypatch: MonkeyPatch) -> None:
    """Ensure logger section from global config is merged."""

    fake_global = Box({"logger": {"defaults": {"output": "console"}, "icons": {"show": False}}}, default_box=True)
    monkeypatch.setattr(logging_manager_module, "get_config", lambda: fake_global)

    logger = LogManager(name="test_global_config")

    # Test that config is properly applied by checking behavior
    # Icons disabled should mean no icon formatting occurs
    logger.info("global config message")

    # Verify the configuration was applied by testing the format behavior
    formatted = logger._format_with_icon("INFO", "test message")  # pylint: disable=protected-access
    assert formatted == "test message"  # No icon should be prepended


def test_format_with_icon_missing_level() -> None:
    """Formatter should return message unchanged when icon missing."""

    logger = LogManager(name="test_missing_icon")
    assert logger._format_with_icon("nonexistent", "plain message") == "plain message"  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_async_logging_methods(monkeypatch: MonkeyPatch) -> None:
    """Async logging helpers should proxy to sync counterparts."""

    class DummyLoop:
        """Asyncio loop stub that runs tasks synchronously for tests."""

        async def run_in_executor(self, _executor: Any, func: Callable[..., Any], *args: Any) -> Any:
            """Execute the provided callable without offloading to threads."""
            return func(*args)

    dummy_loop = DummyLoop()
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: dummy_loop)

    logger = LogManager(name="test_async_methods", config={"output": "console"})

    await logger.adebug("async debug", user="alice")
    await logger.ainfo("async info", request_id="abc")
    await logger.asuccess("async success")
    await logger.awarning("async warning", retry=1)
    await logger.aerror("async error")
    await logger.acritical("async critical")


def test_logmanager_config_defaults(monkeypatch: MonkeyPatch) -> None:
    """Defaults from configuration file should override built-in fallback."""

    fake_global = Box(
        {
            "logger": {
                "defaults": {
                    "output": "console",
                    "console": {"level": "INFO", "show_path": False},
                }
            }
        },
        default_box=True,
    )
    monkeypatch.setattr(logging_manager_module, "get_config", lambda: fake_global)

    logger = LogManager(name="test_defaults")

    assert logger._config.output == "console"  # pylint: disable=protected-access
    assert logger._config.console.level == "INFO"  # pylint: disable=protected-access
    assert logger._config.console.show_path is False  # pylint: disable=protected-access


def test_logmanager_config_presets(monkeypatch: MonkeyPatch) -> None:
    """Presets defined in configuration file should override fallback presets."""

    fake_global = Box(
        {
            "logger": {
                "defaults": {"output": "file"},
                "presets": {
                    "dev": {"output": "console", "console": {"level": "DEBUG"}},
                },
            }
        },
        default_box=True,
    )
    monkeypatch.setattr(logging_manager_module, "get_config", lambda: fake_global)

    logger = LogManager(name="test_config_preset", preset="dev")

    assert logger._config.output == "console"  # pylint: disable=protected-access
    assert logger._config.console.level == "DEBUG"  # pylint: disable=protected-access


def test_logmanager_handles_missing_global_config(monkeypatch: MonkeyPatch) -> None:
    """If the global config lookup fails, LogManager should fall back gracefully."""

    def raise_not_found() -> Box:
        raise FileNotFoundError("config missing for test")

    monkeypatch.setattr(logging_manager_module, "get_config", raise_not_found)

    logger = LogManager(name="test_missing_global_config")

    assert logger._config.output == logging_manager_module.FALLBACK_DEFAULTS["output"]  # pylint: disable=protected-access


def test_logmanager_reserved_kwargs_passthrough() -> None:
    """Reserved logging kwargs should bypass structured context formatting."""

    logger = LogManager(name="test_reserved", config={"output": "console"})
    # exc_info is a reserved kwarg and should not appear in structured context
    logger.info("reserved kwargs handled", exc_info=True)


def test_logmanager_has_native_async_support_property() -> None:
    """Expose the HAS_ASYNC flag via property for coverage."""

    logger = LogManager(name="test_async_flag")
    assert logger.has_native_async_support is False
