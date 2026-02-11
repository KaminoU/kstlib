"""Tests for the kstlib.pipeline.validators module."""

from __future__ import annotations

import pytest

from kstlib.pipeline.exceptions import PipelineConfigError
from kstlib.pipeline.validators import (
    MAX_CALLABLE_TARGET_LENGTH,
    MAX_MODULE_NAME_LENGTH,
    MAX_PIPELINE_STEPS,
    MAX_STEP_ARGS,
    MAX_STEP_NAME_LENGTH,
    validate_callable_target,
    validate_module_name,
    validate_pipeline_config,
    validate_step_config,
    validate_step_name,
)


# ============================================================================
# validate_step_name tests
# ============================================================================


class TestValidateStepName:
    """Tests for validate_step_name function."""

    def test_valid_simple_name(self) -> None:
        """Accept simple alphanumeric names."""
        assert validate_step_name("build") == "build"
        assert validate_step_name("Build") == "Build"

    def test_valid_with_underscore(self) -> None:
        """Accept names with underscores."""
        assert validate_step_name("build_logs") == "build_logs"

    def test_valid_with_hyphen(self) -> None:
        """Accept names with hyphens."""
        assert validate_step_name("step-01") == "step-01"

    def test_valid_with_numbers(self) -> None:
        """Accept names with numbers (not at start)."""
        assert validate_step_name("step1") == "step1"

    def test_empty_name(self) -> None:
        """Reject empty names."""
        with pytest.raises(PipelineConfigError, match="cannot be empty"):
            validate_step_name("")

    def test_too_long(self) -> None:
        """Reject names exceeding max length."""
        long_name = "a" * (MAX_STEP_NAME_LENGTH + 1)
        with pytest.raises(PipelineConfigError, match="too long"):
            validate_step_name(long_name)

    def test_max_length_accepted(self) -> None:
        """Accept names at exactly max length."""
        name = "a" * MAX_STEP_NAME_LENGTH
        assert validate_step_name(name) == name

    def test_starts_with_number(self) -> None:
        """Reject names starting with a number."""
        with pytest.raises(PipelineConfigError, match="must start with a letter"):
            validate_step_name("1step")

    def test_starts_with_underscore(self) -> None:
        """Reject names starting with underscore."""
        with pytest.raises(PipelineConfigError, match="must start with a letter"):
            validate_step_name("_step")

    def test_invalid_characters(self) -> None:
        """Reject names with shell metacharacters."""
        for name in ["my step", "my.step", "my@step", "my$step"]:
            with pytest.raises(PipelineConfigError):
                validate_step_name(name)


# ============================================================================
# validate_callable_target tests
# ============================================================================


class TestValidateCallableTarget:
    """Tests for validate_callable_target function."""

    def test_valid_simple_target(self) -> None:
        """Accept module:function format."""
        assert validate_callable_target("mymodule:run") == "mymodule:run"

    def test_valid_dotted_module(self) -> None:
        """Accept dotted module paths."""
        assert validate_callable_target("my.pkg.module:do_work") == "my.pkg.module:do_work"

    def test_empty_target(self) -> None:
        """Reject empty targets."""
        with pytest.raises(PipelineConfigError, match="cannot be empty"):
            validate_callable_target("")

    def test_too_long(self) -> None:
        """Reject targets exceeding max length."""
        long_target = "a" * MAX_CALLABLE_TARGET_LENGTH + ":f"
        with pytest.raises(PipelineConfigError, match="too long"):
            validate_callable_target(long_target)

    def test_missing_colon(self) -> None:
        """Reject targets without colon separator."""
        with pytest.raises(PipelineConfigError, match="Invalid callable target"):
            validate_callable_target("mymodule.func")

    def test_invalid_module_chars(self) -> None:
        """Reject targets with invalid characters."""
        with pytest.raises(PipelineConfigError, match="Invalid callable target"):
            validate_callable_target("my-module:func")

    def test_invalid_function_start(self) -> None:
        """Reject targets where function starts with number."""
        with pytest.raises(PipelineConfigError, match="Invalid callable target"):
            validate_callable_target("mymodule:1func")


# ============================================================================
# validate_module_name tests
# ============================================================================


class TestValidateModuleName:
    """Tests for validate_module_name function."""

    def test_valid_simple_module(self) -> None:
        """Accept simple module names."""
        assert validate_module_name("mymodule") == "mymodule"

    def test_valid_dotted_module(self) -> None:
        """Accept dotted module names."""
        assert validate_module_name("my.package.module") == "my.package.module"

    def test_valid_with_underscore(self) -> None:
        """Accept module names with underscores."""
        assert validate_module_name("my_module") == "my_module"

    def test_empty_module(self) -> None:
        """Reject empty module names."""
        with pytest.raises(PipelineConfigError, match="cannot be empty"):
            validate_module_name("")

    def test_too_long(self) -> None:
        """Reject module names exceeding max length."""
        long_module = "a" * (MAX_MODULE_NAME_LENGTH + 1)
        with pytest.raises(PipelineConfigError, match="too long"):
            validate_module_name(long_module)

    def test_invalid_start(self) -> None:
        """Reject module names starting with a number."""
        with pytest.raises(PipelineConfigError, match="Invalid module name"):
            validate_module_name("1module")

    def test_invalid_characters(self) -> None:
        """Reject module names with invalid characters."""
        with pytest.raises(PipelineConfigError, match="Invalid module name"):
            validate_module_name("my-module")


# ============================================================================
# validate_step_config tests
# ============================================================================


class TestValidateStepConfig:
    """Tests for validate_step_config function."""

    def test_valid_shell_step(self) -> None:
        """Accept valid shell step configuration."""
        validate_step_config(name="build", step_type="shell", command="echo hello")

    def test_valid_python_step(self) -> None:
        """Accept valid python step configuration."""
        validate_step_config(name="lint", step_type="python", module="ruff")

    def test_valid_callable_step(self) -> None:
        """Accept valid callable step configuration."""
        validate_step_config(
            name="process",
            step_type="callable",
            callable_target="mymod:func",
        )

    def test_shell_missing_command(self) -> None:
        """Reject shell step without command."""
        with pytest.raises(PipelineConfigError, match="requires a 'command'"):
            validate_step_config(name="build", step_type="shell")

    def test_python_missing_module(self) -> None:
        """Reject python step without module."""
        with pytest.raises(PipelineConfigError, match="requires a 'module'"):
            validate_step_config(name="lint", step_type="python")

    def test_callable_missing_target(self) -> None:
        """Reject callable step without target."""
        with pytest.raises(PipelineConfigError, match="requires a 'callable'"):
            validate_step_config(name="proc", step_type="callable")

    def test_unknown_type(self) -> None:
        """Reject unknown step types."""
        with pytest.raises(PipelineConfigError, match="unknown step type"):
            validate_step_config(name="step", step_type="unknown")

    def test_too_many_args(self) -> None:
        """Reject steps with too many arguments."""
        args = [f"arg{i}" for i in range(MAX_STEP_ARGS + 1)]
        with pytest.raises(PipelineConfigError, match="too many arguments"):
            validate_step_config(
                name="build",
                step_type="shell",
                command="echo",
                args=args,
            )

    def test_dangerous_command_blocked(self) -> None:
        """Reject dangerous command patterns."""
        with pytest.raises(ValueError, match="dangerous"):
            validate_step_config(
                name="bad",
                step_type="shell",
                command="echo hello; rm -rf /",
            )


# ============================================================================
# validate_pipeline_config tests
# ============================================================================


class TestValidatePipelineConfig:
    """Tests for validate_pipeline_config function."""

    def test_valid_config(self) -> None:
        """Accept valid pipeline configuration."""
        validate_pipeline_config(step_count=3, on_error="fail_fast")
        validate_pipeline_config(step_count=1, on_error="continue")

    def test_zero_steps(self) -> None:
        """Reject pipeline with no steps."""
        with pytest.raises(PipelineConfigError, match="at least one step"):
            validate_pipeline_config(step_count=0, on_error="fail_fast")

    def test_too_many_steps(self) -> None:
        """Reject pipeline with too many steps."""
        with pytest.raises(PipelineConfigError, match="Too many steps"):
            validate_pipeline_config(
                step_count=MAX_PIPELINE_STEPS + 1,
                on_error="fail_fast",
            )

    def test_max_steps_accepted(self) -> None:
        """Accept pipeline at exactly max steps."""
        validate_pipeline_config(step_count=MAX_PIPELINE_STEPS, on_error="fail_fast")

    def test_invalid_on_error(self) -> None:
        """Reject invalid error policy."""
        with pytest.raises(PipelineConfigError, match="Invalid error policy"):
            validate_pipeline_config(step_count=1, on_error="ignore")
