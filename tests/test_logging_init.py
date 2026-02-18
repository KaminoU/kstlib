"""Tests for kstlib.logging module initialization."""

from __future__ import annotations

import logging
import logging.handlers
from collections.abc import Generator

import pytest

import kstlib.logging as kstlib_logging
from kstlib.logging import LogManager, get_logger, init_logging
from kstlib.logging.manager import TRACE_LEVEL, SUCCESS_LEVEL


class TestInitLogging:
    """Tests for init_logging function."""

    def test_init_logging_creates_root_logger(self) -> None:
        """Test that init_logging creates and returns a LogManager."""
        # Reset global state
        kstlib_logging._root_logger = None

        logger = init_logging(preset="dev")

        assert logger is not None
        assert isinstance(logger, LogManager)
        assert kstlib_logging._root_logger is logger

    def test_init_logging_configures_standard_logger(self) -> None:
        """Test that init_logging configures the standard kstlib logger."""
        # Reset global state
        kstlib_logging._root_logger = None

        log_manager = init_logging(preset="dev")

        # Check standard logger is configured
        std_logger = logging.getLogger("kstlib")
        from kstlib.logging import TRACE_LEVEL

        assert std_logger.level == TRACE_LEVEL

        # Handlers should be copied from LogManager
        for handler in log_manager.handlers:
            assert handler in std_logger.handlers

    def test_init_logging_with_config(self) -> None:
        """Test init_logging with explicit config dict."""
        # Reset global state
        kstlib_logging._root_logger = None

        config = {
            "console": {"enabled": True, "level": "WARNING"},
            "file": {"enabled": False},
        }
        logger = init_logging(config=config)

        assert logger is not None
        assert isinstance(logger, LogManager)


class TestGetLogger:
    """Tests for get_logger function."""

    def test_get_logger_returns_child_logger(self) -> None:
        """Test that get_logger returns a logger under kstlib namespace."""
        logger = get_logger("mymodule")

        assert logger.name == "kstlib.mymodule"

    def test_get_logger_with_kstlib_prefix(self) -> None:
        """Test that get_logger preserves kstlib prefix if present."""
        logger = get_logger("kstlib.auth.providers")

        assert logger.name == "kstlib.auth.providers"

    def test_get_logger_none_returns_root_logger_if_initialized(self) -> None:
        """Test that get_logger(None) returns root LogManager if initialized."""
        # Reset and initialize
        kstlib_logging._root_logger = None
        root = init_logging(preset="dev")

        logger = get_logger(None)

        assert logger is root

    def test_get_logger_none_returns_standard_logger_if_not_initialized(self) -> None:
        """Test that get_logger(None) returns standard logger if not initialized."""
        # Reset global state
        kstlib_logging._root_logger = None

        logger = get_logger(None)

        assert logger.name == "kstlib"
        assert isinstance(logger, logging.Logger)


@pytest.fixture()
def _clean_logger_patch() -> Generator[None, None, None]:
    """Remove class-level .trace()/.success() patches after the test."""
    yield
    for attr in ("trace", "success"):
        # Only remove if it was injected by init_logging (not from LogManager)
        if attr in logging.Logger.__dict__:
            delattr(logging.Logger, attr)


class TestLoggerTracePatch:
    """Tests for .trace() and .success() class-level patch on logging.Logger."""

    def test_trace_before_init_raises(self, _clean_logger_patch: None) -> None:
        """Test that .trace() is not available before init_logging()."""
        # Ensure patch is removed for this test
        for attr in ("trace", "success"):
            if attr in logging.Logger.__dict__:
                delattr(logging.Logger, attr)

        logger = logging.getLogger("kstlib.test_no_patch")
        assert not hasattr(logging.Logger, "trace")
        with pytest.raises(AttributeError):
            logger.trace("should fail")  # type: ignore[attr-defined]

    def test_trace_after_init_works(self, _clean_logger_patch: None) -> None:
        """Test that get_logger().trace() works after init_logging()."""
        kstlib_logging._root_logger = None
        init_logging(preset="dev")

        logger = get_logger("test_trace_works")
        # Should not raise
        logger.trace("hello from child logger")  # type: ignore[attr-defined]

    def test_success_after_init_works(self, _clean_logger_patch: None) -> None:
        """Test that get_logger().success() works after init_logging()."""
        kstlib_logging._root_logger = None
        init_logging(preset="dev")

        logger = get_logger("test_success_works")
        # Should not raise
        logger.success("operation completed")  # type: ignore[attr-defined]

    def test_trace_captures_message(self, _clean_logger_patch: None) -> None:
        """Test that trace messages are captured by handlers at TRACE level."""
        kstlib_logging._root_logger = None
        init_logging(preset="dev")

        logger = get_logger("test_trace_capture")
        logger.setLevel(TRACE_LEVEL)

        handler = logging.handlers.MemoryHandler(capacity=100)
        handler.setLevel(TRACE_LEVEL)
        logger.addHandler(handler)

        logger.trace("trace payload")  # type: ignore[attr-defined]

        assert len(handler.buffer) == 1
        assert handler.buffer[0].getMessage() == "trace payload"
        assert handler.buffer[0].levelno == TRACE_LEVEL

        logger.removeHandler(handler)

    def test_multiple_init_no_duplicate_patch(self, _clean_logger_patch: None) -> None:
        """Test that calling init_logging() twice does not duplicate the patch."""
        kstlib_logging._root_logger = None
        init_logging(preset="dev")
        first_trace = logging.Logger.__dict__["trace"]

        kstlib_logging._root_logger = None
        init_logging(preset="dev")
        second_trace = logging.Logger.__dict__["trace"]

        assert first_trace is second_trace


class TestModuleExports:
    """Tests for module exports."""

    def test_has_async_exported(self) -> None:
        """Test that HAS_ASYNC is exported."""
        from kstlib.logging import HAS_ASYNC

        assert isinstance(HAS_ASYNC, bool)

    def test_all_exports(self) -> None:
        """Test __all__ contains expected exports."""
        assert "LogManager" in kstlib_logging.__all__
        assert "get_logger" in kstlib_logging.__all__
        assert "init_logging" in kstlib_logging.__all__
        assert "HAS_ASYNC" in kstlib_logging.__all__
        assert "TRACE_LEVEL" in kstlib_logging.__all__
