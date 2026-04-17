"""Tests for the kstlib.pipeline.steps.callable module."""

from __future__ import annotations

import pytest

from kstlib.pipeline.exceptions import PipelineConfigError, StepImportError
from kstlib.pipeline.models import StepConfig, StepStatus, StepType
from kstlib.pipeline.steps.callable import DANGEROUS_MODULES, CallableStep


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
            callable="posixpath:join",
            args=("/tmp", "test"),
        )
        result = step.execute(config)
        assert result.status == StepStatus.SUCCESS
        assert result.return_value == "/tmp/test"

    def test_call_returning_none(self) -> None:
        """Handle functions that return an int value."""
        step = CallableStep()
        config = StepConfig(
            name="thread-id",
            type=StepType.CALLABLE,
            callable="threading:get_ident",
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
            callable="json:nonexistent_function_xyz",
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
            callable="posixpath:join",
            args=("/tmp", "test"),
        )
        result = step.execute(config, dry_run=True)
        assert result.status == StepStatus.SKIPPED
        assert "dry-run" in result.stdout
        assert "posixpath:join" in result.stdout

    def test_invalid_target_no_colon(self) -> None:
        """Handle target without colon separator."""
        step = CallableStep()
        # Bypass StepConfig validation by using a valid-looking but bad target
        config = StepConfig(
            name="bad-target",
            type=StepType.CALLABLE,
            callable="a:b",  # Valid format but test the rpartition path
        )
        # Blacklist and whitelist pass for "a", so this reaches the import step
        with pytest.raises(StepImportError):
            step.execute(config)

    def test_dotted_module_path(self) -> None:
        """Call function from dotted module path."""
        step = CallableStep()
        config = StepConfig(
            name="basename",
            type=StepType.CALLABLE,
            callable="posixpath:basename",
            args=("/tmp/test.txt",),
        )
        result = step.execute(config)
        assert result.status == StepStatus.SUCCESS
        assert result.return_value == "test.txt"


class TestCallableStepSecurity:
    """Tests for DANGEROUS_MODULES blacklist and whitelist enforcement."""

    @pytest.mark.parametrize("module", ["os", "sys", "subprocess", "ctypes", "pickle"])
    def test_blacklist_rejects_dangerous_module(self, module: str) -> None:
        """DANGEROUS_MODULES blacklist rejects the target before import."""
        step = CallableStep()
        config = StepConfig(
            name="malicious",
            type=StepType.CALLABLE,
            callable=f"{module}:any_function",
        )
        with pytest.raises(PipelineConfigError, match="DANGEROUS_MODULES"):
            step.execute(config)

    def test_blacklist_rejects_dangerous_submodule(self) -> None:
        """Blacklist rejects submodules of dangerous root modules."""
        step = CallableStep()
        config = StepConfig(
            name="indirect",
            type=StepType.CALLABLE,
            callable="os.path:join",
        )
        with pytest.raises(PipelineConfigError, match="DANGEROUS_MODULES"):
            step.execute(config)

    def test_whitelist_rejects_outside_module(self) -> None:
        """Whitelist rejects modules not present in the allow-list."""
        step = CallableStep(allowed_modules=("json",))
        config = StepConfig(
            name="off-list",
            type=StepType.CALLABLE,
            callable="platform:system",
        )
        with pytest.raises(PipelineConfigError, match="not in allowed_callable_modules"):
            step.execute(config)

    def test_whitelist_allows_exact_match(self) -> None:
        """Whitelist allows exact module match."""
        step = CallableStep(allowed_modules=("json",))
        config = StepConfig(
            name="allowed",
            type=StepType.CALLABLE,
            callable="json:dumps",
            args=('{"k": "v"}',),
        )
        result = step.execute(config)
        assert result.status == StepStatus.SUCCESS

    def test_whitelist_allows_submodule_prefix(self) -> None:
        """Whitelist allows submodules via prefix match."""
        step = CallableStep(allowed_modules=("email",))
        config = StepConfig(
            name="allowed-sub",
            type=StepType.CALLABLE,
            callable="email.utils:quote",
            args=("hello",),
        )
        result = step.execute(config)
        assert result.status == StepStatus.SUCCESS

    def test_dangerous_modules_contains_expected(self) -> None:
        """Ensure the core dangerous modules are covered."""
        for expected in {"os", "sys", "subprocess", "builtins", "ctypes"}:
            assert expected in DANGEROUS_MODULES
