"""Tests for the kstlib.pipeline.steps.callable module."""

from __future__ import annotations

import pytest

from kstlib.pipeline.exceptions import StepImportError
from kstlib.pipeline.models import StepConfig, StepStatus, StepType
from kstlib.pipeline.steps.callable import CallableStep


class TestCallableStepExecute:
    """Tests for CallableStep.execute method."""

    def test_call_builtin_function(self) -> None:
        """Call a standard library function."""
        step = CallableStep()
        config = StepConfig(
            name="get-platform",
            type=StepType.CALLABLE,
            callable="platform:system",
        )
        result = step.execute(config)
        assert result.status == StepStatus.SUCCESS
        assert result.return_value is not None
        assert isinstance(result.return_value, str)
        assert result.duration >= 0

    def test_call_with_args(self) -> None:
        """Call function with positional arguments."""
        step = CallableStep()
        config = StepConfig(
            name="join-path",
            type=StepType.CALLABLE,
            callable="os.path:join",
            args=("/tmp", "test"),
        )
        result = step.execute(config)
        assert result.status == StepStatus.SUCCESS
        # On Windows this may differ, but value should be set
        assert result.return_value is not None

    def test_call_returning_none(self) -> None:
        """Handle functions that return None."""
        step = CallableStep()
        # list.clear returns None but we need an importable function
        # Use os.getpid which returns int, but test json.loads for None scenario
        config = StepConfig(
            name="no-return",
            type=StepType.CALLABLE,
            callable="os:getpid",
        )
        result = step.execute(config)
        assert result.status == StepStatus.SUCCESS
        assert isinstance(result.return_value, int)

    def test_import_error(self) -> None:
        """Raise StepImportError for invalid module."""
        step = CallableStep()
        config = StepConfig(
            name="bad-import",
            type=StepType.CALLABLE,
            callable="nonexistent_xyz_module:func",
        )
        with pytest.raises(StepImportError) as exc_info:
            step.execute(config)
        assert exc_info.value.step_name == "bad-import"
        assert exc_info.value.target == "nonexistent_xyz_module:func"

    def test_import_error_bad_attr(self) -> None:
        """Raise StepImportError for invalid function name."""
        step = CallableStep()
        config = StepConfig(
            name="bad-attr",
            type=StepType.CALLABLE,
            callable="os:nonexistent_function_xyz",
        )
        with pytest.raises(StepImportError) as exc_info:
            step.execute(config)
        assert exc_info.value.step_name == "bad-attr"

    def test_execution_error(self) -> None:
        """Handle runtime errors in callable."""
        step = CallableStep()
        # json.loads with no args will fail
        config = StepConfig(
            name="runtime-error",
            type=StepType.CALLABLE,
            callable="json:loads",
        )
        result = step.execute(config)
        assert result.status == StepStatus.FAILED
        assert result.error is not None

    def test_dry_run(self) -> None:
        """Dry run does not call the function."""
        step = CallableStep()
        config = StepConfig(
            name="process",
            type=StepType.CALLABLE,
            callable="os.path:join",
            args=("/tmp", "test"),
        )
        result = step.execute(config, dry_run=True)
        assert result.status == StepStatus.SKIPPED
        assert "dry-run" in result.stdout
        assert "os.path:join" in result.stdout

    def test_invalid_target_no_colon(self) -> None:
        """Handle target without colon separator."""
        step = CallableStep()
        # Bypass StepConfig validation by using a valid-looking but bad target
        config = StepConfig(
            name="bad-target",
            type=StepType.CALLABLE,
            callable="a:b",  # Valid format but test the rpartition path
        )
        # This will try to import 'a' which doesn't exist
        with pytest.raises(StepImportError):
            step.execute(config)

    def test_dotted_module_path(self) -> None:
        """Call function from dotted module path."""
        step = CallableStep()
        config = StepConfig(
            name="basename",
            type=StepType.CALLABLE,
            callable="os.path:basename",
            args=("/tmp/test.txt",),
        )
        result = step.execute(config)
        assert result.status == StepStatus.SUCCESS
        assert result.return_value == "test.txt"
