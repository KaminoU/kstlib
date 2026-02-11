"""Tests for the kstlib.pipeline.runner module."""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import patch

import pytest

from kstlib.pipeline.exceptions import (
    PipelineAbortedError,
    PipelineConfigError,
)
from kstlib.pipeline.models import (
    ErrorPolicy,
    PipelineConfig,
    StepCondition,
    StepConfig,
    StepStatus,
    StepType,
)
from kstlib.pipeline.runner import (
    PipelineRunner,
    _load_pipeline_config,
    _parse_pipeline_config,
)


# ============================================================================
# PipelineRunner tests
# ============================================================================


class TestPipelineRunnerRun:
    """Tests for PipelineRunner.run method."""

    def test_single_step_success(self) -> None:
        """Run a pipeline with one successful step."""
        config = PipelineConfig(
            name="test",
            steps=(StepConfig(name="greet", type=StepType.SHELL, command="echo hello"),),
        )
        runner = PipelineRunner(config)
        result = runner.run()
        assert result.success is True
        assert len(result.results) == 1
        assert result.results[0].status == StepStatus.SUCCESS
        assert result.duration > 0

    def test_multi_step_success(self) -> None:
        """Run a pipeline with multiple successful steps."""
        config = PipelineConfig(
            name="multi",
            steps=(
                StepConfig(name="step1", type=StepType.SHELL, command="echo one"),
                StepConfig(name="step2", type=StepType.SHELL, command="echo two"),
                StepConfig(name="step3", type=StepType.SHELL, command="echo three"),
            ),
        )
        runner = PipelineRunner(config)
        result = runner.run()
        assert result.success is True
        assert len(result.results) == 3

    def test_fail_fast_aborts(self) -> None:
        """Fail fast policy aborts on first failure."""
        cmd_fail = f'{sys.executable} -c "import sys; sys.exit(1)"'
        config = PipelineConfig(
            name="fail-fast",
            steps=(
                StepConfig(name="ok", type=StepType.SHELL, command="echo ok"),
                StepConfig(name="fail", type=StepType.SHELL, command=cmd_fail),
                StepConfig(name="skip", type=StepType.SHELL, command="echo skip"),
            ),
            on_error=ErrorPolicy.FAIL_FAST,
        )
        runner = PipelineRunner(config)
        with pytest.raises(PipelineAbortedError) as exc_info:
            runner.run()
        assert exc_info.value.step_name == "fail"

    def test_continue_policy(self) -> None:
        """Continue policy runs all steps despite failures."""
        cmd_fail = f'{sys.executable} -c "import sys; sys.exit(1)"'
        config = PipelineConfig(
            name="continue",
            steps=(
                StepConfig(name="ok1", type=StepType.SHELL, command="echo ok1"),
                StepConfig(name="fail", type=StepType.SHELL, command=cmd_fail),
                StepConfig(name="ok2", type=StepType.SHELL, command="echo ok2"),
            ),
            on_error=ErrorPolicy.CONTINUE,
        )
        runner = PipelineRunner(config)
        result = runner.run()
        assert result.success is False
        assert len(result.results) == 3
        assert result.results[0].status == StepStatus.SUCCESS
        assert result.results[1].status == StepStatus.FAILED
        assert result.results[2].status == StepStatus.SUCCESS

    def test_dry_run(self) -> None:
        """Dry run skips all steps."""
        config = PipelineConfig(
            name="dry",
            steps=(
                StepConfig(name="step1", type=StepType.SHELL, command="echo hello"),
                StepConfig(name="step2", type=StepType.SHELL, command="echo world"),
            ),
        )
        runner = PipelineRunner(config)
        result = runner.run(dry_run=True)
        assert all(r.status == StepStatus.SKIPPED for r in result.results)

    def test_config_property(self) -> None:
        """Access pipeline configuration via property."""
        config = PipelineConfig(
            name="test",
            steps=(StepConfig(name="step", type=StepType.SHELL, command="echo"),),
        )
        runner = PipelineRunner(config)
        assert runner.config is config


class TestPipelineRunnerConditions:
    """Tests for conditional step execution."""

    def test_on_success_runs_when_no_failure(self) -> None:
        """on_success step runs when all previous steps succeeded."""
        config = PipelineConfig(
            name="success-cond",
            steps=(
                StepConfig(name="ok", type=StepType.SHELL, command="echo ok"),
                StepConfig(
                    name="after-ok",
                    type=StepType.SHELL,
                    command="echo after",
                    when=StepCondition.ON_SUCCESS,
                ),
            ),
            on_error=ErrorPolicy.CONTINUE,
        )
        runner = PipelineRunner(config)
        result = runner.run()
        assert result.results[1].status == StepStatus.SUCCESS

    def test_on_success_skips_after_failure(self) -> None:
        """on_success step skips when a previous step failed."""
        cmd_fail = f'{sys.executable} -c "import sys; sys.exit(1)"'
        config = PipelineConfig(
            name="skip-cond",
            steps=(
                StepConfig(name="fail", type=StepType.SHELL, command=cmd_fail),
                StepConfig(
                    name="after-fail",
                    type=StepType.SHELL,
                    command="echo should-skip",
                    when=StepCondition.ON_SUCCESS,
                ),
            ),
            on_error=ErrorPolicy.CONTINUE,
        )
        runner = PipelineRunner(config)
        result = runner.run()
        assert result.results[1].status == StepStatus.SKIPPED

    def test_on_failure_runs_after_failure(self) -> None:
        """on_failure step runs when a previous step failed."""
        cmd_fail = f'{sys.executable} -c "import sys; sys.exit(1)"'
        config = PipelineConfig(
            name="failure-cond",
            steps=(
                StepConfig(name="fail", type=StepType.SHELL, command=cmd_fail),
                StepConfig(
                    name="cleanup",
                    type=StepType.SHELL,
                    command="echo cleanup",
                    when=StepCondition.ON_FAILURE,
                ),
            ),
            on_error=ErrorPolicy.CONTINUE,
        )
        runner = PipelineRunner(config)
        result = runner.run()
        assert result.results[1].status == StepStatus.SUCCESS

    def test_on_failure_skips_when_no_failure(self) -> None:
        """on_failure step skips when all previous steps succeeded."""
        config = PipelineConfig(
            name="no-failure-cond",
            steps=(
                StepConfig(name="ok", type=StepType.SHELL, command="echo ok"),
                StepConfig(
                    name="cleanup",
                    type=StepType.SHELL,
                    command="echo cleanup",
                    when=StepCondition.ON_FAILURE,
                ),
            ),
            on_error=ErrorPolicy.CONTINUE,
        )
        runner = PipelineRunner(config)
        result = runner.run()
        assert result.results[1].status == StepStatus.SKIPPED

    def test_always_runs_regardless(self) -> None:
        """always step runs regardless of previous results."""
        cmd_fail = f'{sys.executable} -c "import sys; sys.exit(1)"'
        config = PipelineConfig(
            name="always-cond",
            steps=(
                StepConfig(name="fail", type=StepType.SHELL, command=cmd_fail),
                StepConfig(
                    name="always",
                    type=StepType.SHELL,
                    command="echo always",
                    when=StepCondition.ALWAYS,
                ),
            ),
            on_error=ErrorPolicy.CONTINUE,
        )
        runner = PipelineRunner(config)
        result = runner.run()
        assert result.results[1].status == StepStatus.SUCCESS


class TestPipelineRunnerTimeout:
    """Tests for timeout cascade behavior."""

    def test_step_timeout_overrides_default(self) -> None:
        """Step-level timeout takes precedence over pipeline default."""
        config = PipelineConfig(
            name="timeout",
            steps=(
                StepConfig(
                    name="fast",
                    type=StepType.SHELL,
                    command="echo fast",
                    timeout=10.0,
                ),
            ),
            default_timeout=300.0,
        )
        runner = PipelineRunner(config)
        result = runner.run()
        assert result.results[0].status == StepStatus.SUCCESS

    def test_default_timeout_applied(self) -> None:
        """Pipeline default timeout is applied when step has no timeout."""
        config = PipelineConfig(
            name="default-timeout",
            steps=(StepConfig(name="step", type=StepType.SHELL, command="echo ok"),),
            default_timeout=60.0,
        )
        runner = PipelineRunner(config)
        result = runner.run()
        assert result.results[0].status == StepStatus.SUCCESS


class TestPipelineRunnerFailFastCleanup:
    """Tests for fail_fast cleanup step execution."""

    def test_on_failure_steps_run_after_abort(self) -> None:
        """on_failure steps after failed step are executed during abort."""
        cmd_fail = f'{sys.executable} -c "import sys; sys.exit(1)"'
        config = PipelineConfig(
            name="cleanup-test",
            steps=(
                StepConfig(name="fail", type=StepType.SHELL, command=cmd_fail),
                StepConfig(
                    name="cleanup",
                    type=StepType.SHELL,
                    command="echo cleanup-ran",
                    when=StepCondition.ON_FAILURE,
                ),
                StepConfig(
                    name="regular",
                    type=StepType.SHELL,
                    command="echo should-skip",
                ),
            ),
            on_error=ErrorPolicy.FAIL_FAST,
        )
        runner = PipelineRunner(config)
        with pytest.raises(PipelineAbortedError):
            runner.run()


class TestPipelineRunnerMixedSteps:
    """Tests for pipelines with mixed step types."""

    def test_shell_and_callable(self) -> None:
        """Run pipeline mixing shell and callable steps."""
        config = PipelineConfig(
            name="mixed",
            steps=(
                StepConfig(name="shell", type=StepType.SHELL, command="echo hello"),
                StepConfig(
                    name="callable",
                    type=StepType.CALLABLE,
                    callable="platform:system",
                ),
            ),
        )
        runner = PipelineRunner(config)
        result = runner.run()
        assert result.success is True
        assert len(result.results) == 2

    def test_shell_and_python(self) -> None:
        """Run pipeline mixing shell and python steps."""
        config = PipelineConfig(
            name="mixed-py",
            steps=(
                StepConfig(name="shell", type=StepType.SHELL, command="echo hello"),
                StepConfig(name="python", type=StepType.PYTHON, module="platform"),
            ),
        )
        runner = PipelineRunner(config)
        result = runner.run()
        assert result.success is True


# ============================================================================
# from_config tests
# ============================================================================


class TestPipelineRunnerFromConfig:
    """Tests for PipelineRunner.from_config class method."""

    def test_pipeline_not_found(self) -> None:
        """Raise error when pipeline name not in config."""
        with patch(
            "kstlib.pipeline.runner._load_pipeline_config",
            side_effect=PipelineConfigError("Pipeline 'nonexistent' not found in config. Available: (none)"),
        ):
            with pytest.raises(PipelineConfigError, match="not found"):
                PipelineRunner.from_config("nonexistent")

    def test_valid_config(self) -> None:
        """Load pipeline from config successfully."""
        raw_pipeline = {
            "steps": [
                {"name": "step1", "type": "shell", "command": "echo hello"},
            ],
            "on_error": "continue",
            "default_timeout": 60,
        }

        with patch(
            "kstlib.pipeline.runner._load_pipeline_config",
            return_value=raw_pipeline,
        ):
            runner = PipelineRunner.from_config("test-pipeline")
            assert runner.config.name == "test-pipeline"
            assert runner.config.on_error == ErrorPolicy.CONTINUE

    def test_with_overrides(self) -> None:
        """Apply overrides to config-loaded pipeline."""
        raw_pipeline = {
            "steps": [
                {"name": "step1", "type": "shell", "command": "echo hello"},
            ],
            "on_error": "fail_fast",
            "default_timeout": 300,
        }

        with patch(
            "kstlib.pipeline.runner._load_pipeline_config",
            return_value=raw_pipeline,
        ):
            runner = PipelineRunner.from_config("test-pipeline", on_error="continue")
            assert runner.config.on_error == ErrorPolicy.CONTINUE


# ============================================================================
# _load_pipeline_config tests
# ============================================================================


class TestLoadPipelineConfig:
    """Tests for _load_pipeline_config helper."""

    def _mock_get_config(self, config_data: dict) -> Any:  # type: ignore[type-arg]
        """Create a mock that replaces get_config in the import chain."""
        import types

        mock_module = types.ModuleType("kstlib.config")
        mock_module.get_config = lambda: config_data  # type: ignore[attr-defined]
        return mock_module

    def test_pipeline_not_found(self) -> None:
        """Raise error when pipeline name not in config."""
        mock_config: dict[str, Any] = {"pipeline": {"pipelines": {}}}
        mock_mod = self._mock_get_config(mock_config)
        with patch.dict("sys.modules", {"kstlib.config": mock_mod}):
            with pytest.raises(PipelineConfigError, match="not found"):
                _load_pipeline_config("nonexistent")

    def test_pipeline_found(self) -> None:
        """Return pipeline config when found."""
        pipeline_data = {
            "steps": [{"name": "s", "type": "shell", "command": "echo"}],
        }
        mock_config = {"pipeline": {"pipelines": {"test": pipeline_data}}}
        mock_mod = self._mock_get_config(mock_config)
        with patch.dict("sys.modules", {"kstlib.config": mock_mod}):
            result = _load_pipeline_config("test")
            assert result == pipeline_data

    def test_pipeline_not_mapping(self) -> None:
        """Raise error when pipeline value is not a mapping."""
        mock_config = {"pipeline": {"pipelines": {"test": "not-a-dict"}}}
        mock_mod = self._mock_get_config(mock_config)
        with patch.dict("sys.modules", {"kstlib.config": mock_mod}):
            with pytest.raises(PipelineConfigError, match="must be a mapping"):
                _load_pipeline_config("test")

    def test_no_pipeline_section(self) -> None:
        """Handle config without pipeline section."""
        mock_config: dict[str, Any] = {}
        mock_mod = self._mock_get_config(mock_config)
        with patch.dict("sys.modules", {"kstlib.config": mock_mod}):
            with pytest.raises(PipelineConfigError, match="not found"):
                _load_pipeline_config("test")


# ============================================================================
# _parse_pipeline_config tests
# ============================================================================


class TestParsePipelineConfig:
    """Tests for _parse_pipeline_config helper."""

    def test_basic_config(self) -> None:
        """Parse basic pipeline configuration."""
        data = {
            "steps": [
                {"name": "build", "type": "shell", "command": "make build"},
            ],
        }
        config = _parse_pipeline_config("test", data)
        assert config.name == "test"
        assert len(config.steps) == 1
        assert config.steps[0].name == "build"

    def test_steps_not_list(self) -> None:
        """Reject non-list steps."""
        with pytest.raises(PipelineConfigError, match="must be a list"):
            _parse_pipeline_config("test", {"steps": "invalid"})

    def test_step_not_mapping(self) -> None:
        """Reject non-mapping step entries."""
        with pytest.raises(PipelineConfigError, match="must be a mapping"):
            _parse_pipeline_config("test", {"steps": ["invalid"]})

    def test_step_missing_name(self) -> None:
        """Reject steps without a name."""
        with pytest.raises(PipelineConfigError, match="missing 'name'"):
            _parse_pipeline_config("test", {"steps": [{"type": "shell", "command": "echo"}]})

    def test_invalid_step_type(self) -> None:
        """Reject invalid step type."""
        with pytest.raises(PipelineConfigError, match="invalid type"):
            _parse_pipeline_config(
                "test",
                {
                    "steps": [{"name": "step", "type": "bad", "command": "echo"}],
                },
            )

    def test_invalid_when(self) -> None:
        """Reject invalid when condition."""
        with pytest.raises(PipelineConfigError, match="invalid when"):
            _parse_pipeline_config(
                "test",
                {
                    "steps": [{"name": "step", "type": "shell", "command": "echo", "when": "bad"}],
                },
            )

    def test_invalid_on_error(self) -> None:
        """Reject invalid error policy."""
        with pytest.raises(PipelineConfigError, match="invalid on_error"):
            _parse_pipeline_config(
                "test",
                {
                    "steps": [{"name": "step", "type": "shell", "command": "echo"}],
                    "on_error": "ignore",
                },
            )

    def test_invalid_timeout(self) -> None:
        """Reject invalid timeout value."""
        with pytest.raises(PipelineConfigError, match="invalid timeout"):
            _parse_pipeline_config(
                "test",
                {
                    "steps": [{"name": "step", "type": "shell", "command": "echo", "timeout": "abc"}],
                },
            )

    def test_invalid_default_timeout(self) -> None:
        """Reject invalid default timeout value."""
        with pytest.raises(PipelineConfigError, match="invalid default_timeout"):
            _parse_pipeline_config(
                "test",
                {
                    "steps": [{"name": "step", "type": "shell", "command": "echo"}],
                    "default_timeout": "abc",
                },
            )

    def test_string_args_converted_to_list(self) -> None:
        """Convert string args to single-element list."""
        data = {
            "steps": [
                {"name": "step", "type": "python", "module": "ruff", "args": "check"},
            ],
        }
        config = _parse_pipeline_config("test", data)
        assert config.steps[0].args == ("check",)

    def test_with_env(self) -> None:
        """Parse step with environment variables."""
        data = {
            "steps": [
                {
                    "name": "step",
                    "type": "shell",
                    "command": "echo",
                    "env": {"VAR": "value"},
                },
            ],
        }
        config = _parse_pipeline_config("test", data)
        assert config.steps[0].env == {"VAR": "value"}

    def test_with_working_dir(self) -> None:
        """Parse step with working directory."""
        data = {
            "steps": [
                {
                    "name": "step",
                    "type": "shell",
                    "command": "echo",
                    "working_dir": "/app",
                },
            ],
        }
        config = _parse_pipeline_config("test", data)
        assert config.steps[0].working_dir == "/app"

    def test_callable_step(self) -> None:
        """Parse callable step configuration."""
        data = {
            "steps": [
                {
                    "name": "process",
                    "type": "callable",
                    "callable": "mymod:func",
                },
            ],
        }
        config = _parse_pipeline_config("test", data)
        assert config.steps[0].type == StepType.CALLABLE
        assert config.steps[0].callable == "mymod:func"

    def test_python_step(self) -> None:
        """Parse python step configuration."""
        data = {
            "steps": [
                {
                    "name": "lint",
                    "type": "python",
                    "module": "ruff",
                    "args": ["check", "src/"],
                },
            ],
        }
        config = _parse_pipeline_config("test", data)
        assert config.steps[0].type == StepType.PYTHON
        assert config.steps[0].module == "ruff"
        assert config.steps[0].args == ("check", "src/")
