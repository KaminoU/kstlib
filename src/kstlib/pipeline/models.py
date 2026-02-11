"""Data models for the kstlib.pipeline module.

This module defines the core data structures used by the pipeline module:

- StepType: Enum for step execution mode (shell, python, callable)
- ErrorPolicy: Enum for pipeline error handling (fail_fast, continue)
- StepCondition: Enum for conditional step execution (always, on_success, on_failure)
- StepStatus: Enum for step result status (success, failed, skipped, timeout)
- StepConfig: Frozen configuration for a single pipeline step
- PipelineConfig: Frozen configuration for an entire pipeline
- StepResult: Mutable result of a single step execution
- PipelineResult: Mutable aggregate result of a pipeline execution
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from kstlib.pipeline.exceptions import PipelineConfigError
from kstlib.pipeline.validators import (
    validate_callable_target,
    validate_command,
    validate_env,
    validate_module_name,
    validate_pipeline_config,
    validate_step_name,
)


class StepType(str, Enum):
    """Execution mode for a pipeline step.

    Attributes:
        SHELL: Execute a shell command via ``subprocess.run(shell=True)``.
        PYTHON: Execute a Python module via ``python -m module``.
        CALLABLE: Import and call a Python function directly.
    """

    SHELL = "shell"
    PYTHON = "python"
    CALLABLE = "callable"


class ErrorPolicy(str, Enum):
    """Error handling policy for a pipeline.

    Attributes:
        FAIL_FAST: Abort pipeline on first step failure.
        CONTINUE: Continue executing remaining steps after a failure.
    """

    FAIL_FAST = "fail_fast"
    CONTINUE = "continue"


class StepCondition(str, Enum):
    """Condition for executing a pipeline step.

    Attributes:
        ALWAYS: Execute the step regardless of previous results.
        ON_SUCCESS: Execute only if all previous steps succeeded.
        ON_FAILURE: Execute only if at least one previous step failed.
    """

    ALWAYS = "always"
    ON_SUCCESS = "on_success"
    ON_FAILURE = "on_failure"


class StepStatus(str, Enum):
    """Result status of a pipeline step.

    Attributes:
        SUCCESS: Step completed successfully (exit code 0).
        FAILED: Step failed (non-zero exit code or exception).
        SKIPPED: Step was skipped due to condition or abort.
        TIMEOUT: Step exceeded its timeout limit.
    """

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class StepConfig:
    """Configuration for a single pipeline step.

    Attributes:
        name: Unique step name within the pipeline.
        type: Execution mode (shell, python, callable).
        command: Shell command string (required for shell type).
        module: Python module to execute (required for python type).
        callable: Import target ``module.path:function`` (required for callable type).
        args: Arguments passed to the step.
        env: Environment variables to set for the step.
        working_dir: Working directory for the step.
        timeout: Step timeout in seconds (None uses pipeline default).
        when: Condition for executing this step.

    Examples:
        >>> config = StepConfig(
        ...     name="build",
        ...     type=StepType.SHELL,
        ...     command="echo hello",
        ... )
        >>> config.name
        'build'

        >>> config = StepConfig(
        ...     name="process",
        ...     type=StepType.PYTHON,
        ...     module="my.module",
        ...     args=["--verbose"],
        ... )
    """

    name: str
    type: StepType
    command: str | None = None
    module: str | None = None
    callable: str | None = None
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    working_dir: str | None = None
    timeout: float | None = None
    when: StepCondition = StepCondition.ALWAYS

    def __post_init__(self) -> None:
        """Validate step configuration values.

        Raises:
            PipelineConfigError: If any configuration value is invalid.
        """
        validate_step_name(self.name)

        if self.type == StepType.SHELL:
            if not self.command:
                raise PipelineConfigError(f"Step '{self.name}': shell step requires a 'command'")
            validate_command(self.command)
        elif self.type == StepType.PYTHON:
            if not self.module:
                raise PipelineConfigError(f"Step '{self.name}': python step requires a 'module'")
            validate_module_name(self.module)
        elif self.type == StepType.CALLABLE:
            if not self.callable:
                raise PipelineConfigError(f"Step '{self.name}': callable step requires a 'callable' target")
            validate_callable_target(self.callable)

        if self.env:
            validate_env(self.env)

        if self.timeout is not None and self.timeout <= 0:
            raise PipelineConfigError(f"Step '{self.name}': timeout must be positive, got {self.timeout}")


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    """Configuration for a complete pipeline.

    Attributes:
        name: Pipeline name.
        steps: Ordered tuple of step configurations.
        on_error: Error handling policy.
        default_timeout: Default timeout for steps without explicit timeout.

    Examples:
        >>> config = PipelineConfig(
        ...     name="deploy",
        ...     steps=(
        ...         StepConfig(name="build", type=StepType.SHELL, command="make build"),
        ...         StepConfig(name="test", type=StepType.SHELL, command="make test"),
        ...     ),
        ... )
        >>> len(config.steps)
        2
    """

    name: str
    steps: tuple[StepConfig, ...]
    on_error: ErrorPolicy = ErrorPolicy.FAIL_FAST
    default_timeout: float = 300.0

    def __post_init__(self) -> None:
        """Validate pipeline configuration values.

        Raises:
            PipelineConfigError: If configuration is invalid.
        """
        validate_pipeline_config(
            step_count=len(self.steps),
            on_error=self.on_error.value,
        )

        if self.default_timeout <= 0:
            raise PipelineConfigError(f"Pipeline default_timeout must be positive, got {self.default_timeout}")

        # Check for duplicate step names
        seen: set[str] = set()
        for step in self.steps:
            if step.name in seen:
                raise PipelineConfigError(f"Duplicate step name: {step.name!r}")
            seen.add(step.name)


@dataclass(slots=True)
class StepResult:
    """Result of a single pipeline step execution.

    Attributes:
        name: Step name.
        status: Execution result status.
        stdout: Standard output captured from the step.
        stderr: Standard error captured from the step.
        return_code: Process exit code (shell/python steps).
        return_value: Return value (callable steps).
        duration: Execution duration in seconds.
        error: Error message if the step failed.

    Examples:
        >>> result = StepResult(name="build", status=StepStatus.SUCCESS)
        >>> result.status
        <StepStatus.SUCCESS: 'success'>
    """

    name: str
    status: StepStatus
    stdout: str = ""
    stderr: str = ""
    return_code: int | None = None
    return_value: object = None
    duration: float = 0.0
    error: str | None = None


@dataclass(slots=True)
class PipelineResult:
    """Aggregate result of a pipeline execution.

    Attributes:
        name: Pipeline name.
        results: Ordered list of step results.
        duration: Total pipeline execution duration in seconds.

    Examples:
        >>> result = PipelineResult(name="deploy")
        >>> result.success
        True
    """

    name: str
    results: list[StepResult] = field(default_factory=list)
    duration: float = 0.0

    @property
    def success(self) -> bool:
        """Whether all executed steps succeeded.

        Returns:
            True if no step has FAILED or TIMEOUT status.
        """
        return all(r.status not in (StepStatus.FAILED, StepStatus.TIMEOUT) for r in self.results)

    @property
    def failed_steps(self) -> list[StepResult]:
        """Steps that failed or timed out.

        Returns:
            List of StepResult with FAILED or TIMEOUT status.
        """
        return [r for r in self.results if r.status in (StepStatus.FAILED, StepStatus.TIMEOUT)]

    @property
    def skipped_steps(self) -> list[StepResult]:
        """Steps that were skipped.

        Returns:
            List of StepResult with SKIPPED status.
        """
        return [r for r in self.results if r.status == StepStatus.SKIPPED]


__all__ = [
    "ErrorPolicy",
    "PipelineConfig",
    "PipelineResult",
    "StepCondition",
    "StepConfig",
    "StepResult",
    "StepStatus",
    "StepType",
]
