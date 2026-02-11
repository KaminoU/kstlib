"""Tests for the kstlib.pipeline.models module."""

from __future__ import annotations

import pytest

from kstlib.pipeline.exceptions import PipelineConfigError
from kstlib.pipeline.models import (
    ErrorPolicy,
    PipelineConfig,
    PipelineResult,
    StepCondition,
    StepConfig,
    StepResult,
    StepStatus,
    StepType,
)


# ============================================================================
# Enum tests
# ============================================================================


class TestStepType:
    """Tests for StepType enum."""

    def test_values(self) -> None:
        """Verify all step type values."""
        assert StepType.SHELL.value == "shell"
        assert StepType.PYTHON.value == "python"
        assert StepType.CALLABLE.value == "callable"

    def test_from_string(self) -> None:
        """Create StepType from string value."""
        assert StepType("shell") is StepType.SHELL
        assert StepType("python") is StepType.PYTHON
        assert StepType("callable") is StepType.CALLABLE

    def test_invalid_value(self) -> None:
        """Reject invalid step type string."""
        with pytest.raises(ValueError):
            StepType("invalid")


class TestErrorPolicy:
    """Tests for ErrorPolicy enum."""

    def test_values(self) -> None:
        """Verify all error policy values."""
        assert ErrorPolicy.FAIL_FAST.value == "fail_fast"
        assert ErrorPolicy.CONTINUE.value == "continue"

    def test_from_string(self) -> None:
        """Create ErrorPolicy from string value."""
        assert ErrorPolicy("fail_fast") is ErrorPolicy.FAIL_FAST
        assert ErrorPolicy("continue") is ErrorPolicy.CONTINUE


class TestStepCondition:
    """Tests for StepCondition enum."""

    def test_values(self) -> None:
        """Verify all step condition values."""
        assert StepCondition.ALWAYS.value == "always"
        assert StepCondition.ON_SUCCESS.value == "on_success"
        assert StepCondition.ON_FAILURE.value == "on_failure"


class TestStepStatus:
    """Tests for StepStatus enum."""

    def test_values(self) -> None:
        """Verify all step status values."""
        assert StepStatus.SUCCESS.value == "success"
        assert StepStatus.FAILED.value == "failed"
        assert StepStatus.SKIPPED.value == "skipped"
        assert StepStatus.TIMEOUT.value == "timeout"


# ============================================================================
# StepConfig tests
# ============================================================================


class TestStepConfig:
    """Tests for StepConfig dataclass."""

    def test_shell_step(self) -> None:
        """Create a valid shell step configuration."""
        config = StepConfig(
            name="build",
            type=StepType.SHELL,
            command="echo hello",
        )
        assert config.name == "build"
        assert config.type == StepType.SHELL
        assert config.command == "echo hello"

    def test_python_step(self) -> None:
        """Create a valid python step configuration."""
        config = StepConfig(
            name="lint",
            type=StepType.PYTHON,
            module="ruff",
            args=("check", "src/"),
        )
        assert config.name == "lint"
        assert config.module == "ruff"
        assert config.args == ("check", "src/")

    def test_callable_step(self) -> None:
        """Create a valid callable step configuration."""
        config = StepConfig(
            name="process",
            type=StepType.CALLABLE,
            callable="mymod:func",
        )
        assert config.name == "process"
        assert config.callable == "mymod:func"

    def test_defaults(self) -> None:
        """Verify default values."""
        config = StepConfig(
            name="step",
            type=StepType.SHELL,
            command="echo",
        )
        assert config.args == ()
        assert config.env == {}
        assert config.working_dir is None
        assert config.timeout is None
        assert config.when == StepCondition.ALWAYS

    def test_frozen(self) -> None:
        """StepConfig is immutable."""
        config = StepConfig(
            name="step",
            type=StepType.SHELL,
            command="echo",
        )
        with pytest.raises(AttributeError):
            config.name = "other"  # type: ignore[misc]

    def test_shell_missing_command(self) -> None:
        """Reject shell step without command."""
        with pytest.raises(PipelineConfigError, match="requires a 'command'"):
            StepConfig(name="build", type=StepType.SHELL)

    def test_python_missing_module(self) -> None:
        """Reject python step without module."""
        with pytest.raises(PipelineConfigError, match="requires a 'module'"):
            StepConfig(name="lint", type=StepType.PYTHON)

    def test_callable_missing_target(self) -> None:
        """Reject callable step without target."""
        with pytest.raises(PipelineConfigError, match="requires a 'callable'"):
            StepConfig(name="proc", type=StepType.CALLABLE)

    def test_negative_timeout(self) -> None:
        """Reject negative timeout."""
        with pytest.raises(PipelineConfigError, match="must be positive"):
            StepConfig(
                name="step",
                type=StepType.SHELL,
                command="echo",
                timeout=-1,
            )

    def test_zero_timeout(self) -> None:
        """Reject zero timeout."""
        with pytest.raises(PipelineConfigError, match="must be positive"):
            StepConfig(
                name="step",
                type=StepType.SHELL,
                command="echo",
                timeout=0,
            )

    def test_invalid_name(self) -> None:
        """Reject invalid step name."""
        with pytest.raises(PipelineConfigError):
            StepConfig(name="", type=StepType.SHELL, command="echo")

    def test_env_validated(self) -> None:
        """Validate environment variables."""
        with pytest.raises(ValueError, match="Invalid env key"):
            StepConfig(
                name="step",
                type=StepType.SHELL,
                command="echo",
                env={"invalid key": "value"},
            )

    def test_with_all_options(self) -> None:
        """Create step with all optional fields."""
        config = StepConfig(
            name="deploy",
            type=StepType.SHELL,
            command="deploy.sh",
            args=("--prod",),
            env={"ENV": "prod"},
            working_dir="/app",
            timeout=60.0,
            when=StepCondition.ON_SUCCESS,
        )
        assert config.args == ("--prod",)
        assert config.env == {"ENV": "prod"}
        assert config.working_dir == "/app"
        assert config.timeout == 60.0
        assert config.when == StepCondition.ON_SUCCESS


# ============================================================================
# PipelineConfig tests
# ============================================================================


class TestPipelineConfig:
    """Tests for PipelineConfig dataclass."""

    def test_basic_pipeline(self) -> None:
        """Create a basic pipeline configuration."""
        config = PipelineConfig(
            name="deploy",
            steps=(
                StepConfig(name="build", type=StepType.SHELL, command="make"),
                StepConfig(name="test", type=StepType.SHELL, command="make test"),
            ),
        )
        assert config.name == "deploy"
        assert len(config.steps) == 2

    def test_defaults(self) -> None:
        """Verify default values."""
        config = PipelineConfig(
            name="pipeline",
            steps=(StepConfig(name="step", type=StepType.SHELL, command="echo"),),
        )
        assert config.on_error == ErrorPolicy.FAIL_FAST
        assert config.default_timeout == 300.0

    def test_frozen(self) -> None:
        """PipelineConfig is immutable."""
        config = PipelineConfig(
            name="pipeline",
            steps=(StepConfig(name="step", type=StepType.SHELL, command="echo"),),
        )
        with pytest.raises(AttributeError):
            config.name = "other"  # type: ignore[misc]

    def test_no_steps(self) -> None:
        """Reject pipeline with no steps."""
        with pytest.raises(PipelineConfigError, match="at least one step"):
            PipelineConfig(name="empty", steps=())

    def test_duplicate_step_names(self) -> None:
        """Reject pipeline with duplicate step names."""
        with pytest.raises(PipelineConfigError, match="Duplicate step name"):
            PipelineConfig(
                name="pipeline",
                steps=(
                    StepConfig(name="step", type=StepType.SHELL, command="echo"),
                    StepConfig(name="step", type=StepType.SHELL, command="echo 2"),
                ),
            )

    def test_negative_default_timeout(self) -> None:
        """Reject negative default timeout."""
        with pytest.raises(PipelineConfigError, match="must be positive"):
            PipelineConfig(
                name="pipeline",
                steps=(StepConfig(name="step", type=StepType.SHELL, command="echo"),),
                default_timeout=-1,
            )


# ============================================================================
# StepResult tests
# ============================================================================


class TestStepResult:
    """Tests for StepResult dataclass."""

    def test_basic_result(self) -> None:
        """Create a basic step result."""
        result = StepResult(name="build", status=StepStatus.SUCCESS)
        assert result.name == "build"
        assert result.status == StepStatus.SUCCESS

    def test_defaults(self) -> None:
        """Verify default values."""
        result = StepResult(name="step", status=StepStatus.SUCCESS)
        assert result.stdout == ""
        assert result.stderr == ""
        assert result.return_code is None
        assert result.return_value is None
        assert result.duration == 0.0
        assert result.error is None

    def test_mutable(self) -> None:
        """StepResult is mutable."""
        result = StepResult(name="step", status=StepStatus.SUCCESS)
        result.status = StepStatus.FAILED
        assert result.status == StepStatus.FAILED

    def test_with_output(self) -> None:
        """Create result with captured output."""
        result = StepResult(
            name="build",
            status=StepStatus.SUCCESS,
            stdout="output\n",
            stderr="",
            return_code=0,
            duration=1.23,
        )
        assert result.stdout == "output\n"
        assert result.return_code == 0
        assert result.duration == 1.23

    def test_with_return_value(self) -> None:
        """Create result with callable return value."""
        result = StepResult(
            name="process",
            status=StepStatus.SUCCESS,
            return_value={"key": "value"},
        )
        assert result.return_value == {"key": "value"}


# ============================================================================
# PipelineResult tests
# ============================================================================


class TestPipelineResult:
    """Tests for PipelineResult dataclass."""

    def test_empty_result(self) -> None:
        """Empty pipeline result is successful."""
        result = PipelineResult(name="pipeline")
        assert result.success is True
        assert result.failed_steps == []
        assert result.skipped_steps == []
        assert result.results == []

    def test_all_success(self) -> None:
        """Pipeline with all successful steps."""
        result = PipelineResult(
            name="pipeline",
            results=[
                StepResult(name="a", status=StepStatus.SUCCESS),
                StepResult(name="b", status=StepStatus.SUCCESS),
            ],
        )
        assert result.success is True
        assert result.failed_steps == []

    def test_with_failure(self) -> None:
        """Pipeline with a failed step."""
        result = PipelineResult(
            name="pipeline",
            results=[
                StepResult(name="a", status=StepStatus.SUCCESS),
                StepResult(name="b", status=StepStatus.FAILED),
            ],
        )
        assert result.success is False
        assert len(result.failed_steps) == 1
        assert result.failed_steps[0].name == "b"

    def test_with_timeout(self) -> None:
        """Pipeline with a timed out step counts as failure."""
        result = PipelineResult(
            name="pipeline",
            results=[
                StepResult(name="a", status=StepStatus.TIMEOUT),
            ],
        )
        assert result.success is False
        assert len(result.failed_steps) == 1

    def test_skipped_steps(self) -> None:
        """Track skipped steps separately."""
        result = PipelineResult(
            name="pipeline",
            results=[
                StepResult(name="a", status=StepStatus.SUCCESS),
                StepResult(name="b", status=StepStatus.SKIPPED),
                StepResult(name="c", status=StepStatus.SKIPPED),
            ],
        )
        assert result.success is True
        assert len(result.skipped_steps) == 2

    def test_mutable(self) -> None:
        """PipelineResult is mutable."""
        result = PipelineResult(name="pipeline")
        result.results.append(StepResult(name="a", status=StepStatus.SUCCESS))
        result.duration = 1.5
        assert len(result.results) == 1
        assert result.duration == 1.5
