"""Tests for the kstlib.pipeline.exceptions module."""

from __future__ import annotations

import pytest

from kstlib.config.exceptions import KstlibError
from kstlib.pipeline.exceptions import (
    PipelineAbortedError,
    PipelineConfigError,
    PipelineError,
    StepError,
    StepImportError,
    StepTimeoutError,
)


class TestPipelineErrorHierarchy:
    """Tests for the exception hierarchy."""

    def test_pipeline_error_is_kstlib_error(self) -> None:
        """PipelineError inherits from KstlibError."""
        assert issubclass(PipelineError, KstlibError)

    def test_pipeline_config_error_is_pipeline_error(self) -> None:
        """PipelineConfigError inherits from PipelineError."""
        assert issubclass(PipelineConfigError, PipelineError)

    def test_pipeline_config_error_is_value_error(self) -> None:
        """PipelineConfigError also inherits from ValueError."""
        assert issubclass(PipelineConfigError, ValueError)

    def test_pipeline_aborted_error_is_pipeline_error(self) -> None:
        """PipelineAbortedError inherits from PipelineError."""
        assert issubclass(PipelineAbortedError, PipelineError)

    def test_step_error_is_pipeline_error(self) -> None:
        """StepError inherits from PipelineError."""
        assert issubclass(StepError, PipelineError)

    def test_step_timeout_error_is_step_error(self) -> None:
        """StepTimeoutError inherits from StepError."""
        assert issubclass(StepTimeoutError, StepError)

    def test_step_import_error_is_step_error(self) -> None:
        """StepImportError inherits from StepError."""
        assert issubclass(StepImportError, StepError)


class TestPipelineAbortedError:
    """Tests for PipelineAbortedError."""

    def test_attributes(self) -> None:
        """Store step_name and reason."""
        exc = PipelineAbortedError("build", "exit code 1")
        assert exc.step_name == "build"
        assert exc.reason == "exit code 1"

    def test_message(self) -> None:
        """Format error message with step name and reason."""
        exc = PipelineAbortedError("deploy", "connection refused")
        assert "deploy" in str(exc)
        assert "connection refused" in str(exc)

    def test_catch_as_pipeline_error(self) -> None:
        """Catchable as PipelineError."""
        with pytest.raises(PipelineError):
            raise PipelineAbortedError("step", "reason")


class TestStepError:
    """Tests for StepError."""

    def test_attributes(self) -> None:
        """Store step_name and reason."""
        exc = StepError("lint", "non-zero exit")
        assert exc.step_name == "lint"
        assert exc.reason == "non-zero exit"

    def test_message(self) -> None:
        """Format error message."""
        exc = StepError("test", "assertion failed")
        assert "test" in str(exc)
        assert "assertion failed" in str(exc)


class TestStepTimeoutError:
    """Tests for StepTimeoutError."""

    def test_attributes(self) -> None:
        """Store step_name and timeout."""
        exc = StepTimeoutError("build", 30.0)
        assert exc.step_name == "build"
        assert exc.timeout == 30.0

    def test_message(self) -> None:
        """Format error message with timeout value."""
        exc = StepTimeoutError("deploy", 60.0)
        assert "deploy" in str(exc)
        assert "60.0s" in str(exc)

    def test_reason_set(self) -> None:
        """Reason includes timeout info."""
        exc = StepTimeoutError("step", 10.0)
        assert "timeout" in exc.reason


class TestStepImportError:
    """Tests for StepImportError."""

    def test_attributes(self) -> None:
        """Store step_name and target."""
        exc = StepImportError("process", "my.module:func")
        assert exc.step_name == "process"
        assert exc.target == "my.module:func"

    def test_message(self) -> None:
        """Format error message with import target."""
        exc = StepImportError("run", "bad.module:fn")
        assert "run" in str(exc)
        assert "bad.module:fn" in str(exc)


class TestPipelineConfigError:
    """Tests for PipelineConfigError."""

    def test_is_value_error(self) -> None:
        """Catchable as ValueError for compatibility."""
        with pytest.raises(ValueError):
            raise PipelineConfigError("bad config")

    def test_is_pipeline_error(self) -> None:
        """Catchable as PipelineError."""
        with pytest.raises(PipelineError):
            raise PipelineConfigError("bad config")

    def test_message(self) -> None:
        """Preserve error message."""
        exc = PipelineConfigError("missing field")
        assert str(exc) == "missing field"
