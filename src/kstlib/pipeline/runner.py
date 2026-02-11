"""Pipeline runner for sequential step execution.

Provides the ``PipelineRunner`` class that executes a sequence of steps
with support for conditional execution, error policies, dry-run mode,
and config-driven pipeline definitions.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from kstlib.pipeline.exceptions import (
    PipelineAbortedError,
    PipelineConfigError,
)
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
from kstlib.pipeline.steps.callable import CallableStep
from kstlib.pipeline.steps.python import PythonStep
from kstlib.pipeline.steps.shell import ShellStep

if TYPE_CHECKING:
    from kstlib.pipeline.base import AbstractStep

logger = logging.getLogger(__name__)

# Step type to executor mapping
_STEP_EXECUTORS: dict[StepType, AbstractStep] = {
    StepType.SHELL: ShellStep(),
    StepType.PYTHON: PythonStep(),
    StepType.CALLABLE: CallableStep(),
}


class PipelineRunner:
    """Execute a pipeline of sequential steps.

    Supports conditional execution (``when``), error policies
    (``fail_fast`` / ``continue``), timeout cascading, and dry-run mode.

    Args:
        config: Pipeline configuration.

    Examples:
        Build a pipeline programmatically:

        >>> from kstlib.pipeline.models import (
        ...     PipelineConfig, StepConfig, StepType,
        ... )
        >>> config = PipelineConfig(
        ...     name="demo",
        ...     steps=(
        ...         StepConfig(name="greet", type=StepType.SHELL, command="echo hello"),
        ...     ),
        ... )
        >>> runner = PipelineRunner(config)
        >>> result = runner.run()  # doctest: +SKIP

        Load from ``kstlib.conf.yml``:

        >>> runner = PipelineRunner.from_config("morning")  # doctest: +SKIP
        >>> result = runner.run()  # doctest: +SKIP
    """

    def __init__(self, config: PipelineConfig) -> None:
        """Initialize PipelineRunner.

        Args:
            config: Pipeline configuration with steps and policies.
        """
        self._config = config

    @property
    def config(self) -> PipelineConfig:
        """Return the pipeline configuration."""
        return self._config

    @classmethod
    def from_config(
        cls,
        name: str,
        **overrides: Any,
    ) -> PipelineRunner:
        """Create a PipelineRunner from ``kstlib.conf.yml``.

        Loads the pipeline definition from ``pipeline.pipelines.<name>``
        in the global configuration.

        Args:
            name: Pipeline name as defined in config.
            **overrides: Override pipeline-level settings (e.g. ``on_error``).

        Returns:
            Configured PipelineRunner instance.

        Raises:
            PipelineConfigError: If the pipeline is not found or invalid.

        Examples:
            >>> runner = PipelineRunner.from_config("morning")  # doctest: +SKIP
        """
        config_data = _load_pipeline_config(name)

        # Apply overrides
        if overrides:
            config_data = {**config_data, **overrides}

        pipeline_config = _parse_pipeline_config(name, config_data)
        return cls(pipeline_config)

    def run(self, *, dry_run: bool = False) -> PipelineResult:
        """Execute the pipeline.

        Runs each step sequentially, respecting conditions and error policies.

        Args:
            dry_run: If True, simulate execution without side effects.

        Returns:
            PipelineResult with all step results and aggregate status.

        Raises:
            PipelineAbortedError: If a step fails with ``fail_fast`` policy.
        """
        pipeline_result = PipelineResult(name=self._config.name)
        has_failure = False
        start = time.monotonic()

        logger.info(
            "Pipeline '%s' started (%d steps, on_error=%s%s)",
            self._config.name,
            len(self._config.steps),
            self._config.on_error.value,
            ", dry_run=True" if dry_run else "",
        )

        for step_config in self._config.steps:
            # Check condition
            if not self._should_execute(step_config, has_failure):
                logger.info(
                    "Step '%s' skipped (when=%s, has_failure=%s)",
                    step_config.name,
                    step_config.when.value,
                    has_failure,
                )
                pipeline_result.results.append(StepResult(name=step_config.name, status=StepStatus.SKIPPED))
                continue

            # Resolve timeout cascade: step timeout > pipeline default
            effective_config = step_config
            if step_config.timeout is None:
                # Apply pipeline default timeout via a new StepConfig
                effective_config = _with_timeout(step_config, self._config.default_timeout)

            # Execute step
            executor = _STEP_EXECUTORS[step_config.type]
            result = executor.execute(effective_config, dry_run=dry_run)
            pipeline_result.results.append(result)

            logger.info(
                "Step '%s' -> %s (%.3fs)",
                result.name,
                result.status.value,
                result.duration,
            )

            # Handle failure
            if result.status in (StepStatus.FAILED, StepStatus.TIMEOUT):
                has_failure = True
                if self._config.on_error == ErrorPolicy.FAIL_FAST:
                    # Execute remaining on_failure steps before aborting
                    self._execute_on_failure_steps(step_config, pipeline_result, dry_run)
                    pipeline_result.duration = time.monotonic() - start
                    raise PipelineAbortedError(
                        result.name,
                        result.error or result.status.value,
                    )

        pipeline_result.duration = time.monotonic() - start
        logger.info(
            "Pipeline '%s' completed in %.3fs (success=%s)",
            self._config.name,
            pipeline_result.duration,
            pipeline_result.success,
        )
        return pipeline_result

    def _should_execute(
        self,
        step: StepConfig,
        has_failure: bool,
    ) -> bool:
        """Determine if a step should execute based on its condition.

        Args:
            step: Step configuration with ``when`` condition.
            has_failure: Whether any previous step has failed.

        Returns:
            True if the step should execute.
        """
        if step.when == StepCondition.ON_SUCCESS:
            return not has_failure
        if step.when == StepCondition.ON_FAILURE:
            return has_failure
        # StepCondition.ALWAYS (default)
        return True

    def _execute_on_failure_steps(
        self,
        failed_step: StepConfig,
        pipeline_result: PipelineResult,
        dry_run: bool,
    ) -> None:
        """Execute remaining steps that have ``when: on_failure``.

        Called during fail_fast abort to allow cleanup steps to run.

        Args:
            failed_step: The step that caused the abort.
            pipeline_result: Pipeline result to append step results to.
            dry_run: Whether to simulate execution.
        """
        found = False
        for step_config in self._config.steps:
            if step_config.name == failed_step.name:
                found = True
                continue
            if not found:
                continue
            if step_config.when == StepCondition.ON_FAILURE:
                effective_config = step_config
                if step_config.timeout is None:
                    effective_config = _with_timeout(step_config, self._config.default_timeout)
                executor = _STEP_EXECUTORS[step_config.type]
                result = executor.execute(effective_config, dry_run=dry_run)
                pipeline_result.results.append(result)
                logger.info(
                    "Cleanup step '%s' -> %s (%.3fs)",
                    result.name,
                    result.status.value,
                    result.duration,
                )
            else:
                pipeline_result.results.append(StepResult(name=step_config.name, status=StepStatus.SKIPPED))


# ============================================================================
# Config helpers
# ============================================================================


def _load_pipeline_config(name: str) -> dict[str, Any]:
    """Load a pipeline definition from global config.

    Args:
        name: Pipeline name.

    Returns:
        Raw config dict for the pipeline.

    Raises:
        PipelineConfigError: If the pipeline is not found.
    """
    # Lazy imports to avoid circular dependencies
    try:
        from kstlib.config import get_config  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise PipelineConfigError("kstlib.config is required for config-driven pipelines") from exc

    raw_config: Mapping[str, Any] = get_config()
    pipeline_section: Mapping[str, Any] = raw_config.get("pipeline", {})
    pipelines: Mapping[str, Any] = pipeline_section.get("pipelines", {})

    if name not in pipelines:
        available = ", ".join(sorted(pipelines.keys())) or "(none)"
        raise PipelineConfigError(f"Pipeline '{name}' not found in config. Available: {available}")

    raw = pipelines[name]
    if not isinstance(raw, Mapping):
        raise PipelineConfigError(f"Pipeline '{name}' must be a mapping, got {type(raw).__name__}")
    return dict(raw)


def _parse_pipeline_config(
    name: str,
    data: dict[str, Any],
) -> PipelineConfig:
    """Parse raw config data into a PipelineConfig.

    Args:
        name: Pipeline name.
        data: Raw config dict.

    Returns:
        Validated PipelineConfig.

    Raises:
        PipelineConfigError: If config is invalid.
    """
    raw_steps = data.get("steps", [])
    if not isinstance(raw_steps, list):
        raise PipelineConfigError(f"Pipeline '{name}': 'steps' must be a list")

    steps: list[StepConfig] = []
    for i, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, Mapping):
            raise PipelineConfigError(f"Pipeline '{name}': step {i} must be a mapping")
        steps.append(_parse_step_config(name, i, dict(raw_step)))

    on_error_str = data.get("on_error", "fail_fast")
    try:
        on_error = ErrorPolicy(on_error_str)
    except ValueError:
        raise PipelineConfigError(f"Pipeline '{name}': invalid on_error {on_error_str!r}") from None

    default_timeout = data.get("default_timeout", 300.0)
    try:
        default_timeout = float(default_timeout)
    except (TypeError, ValueError):
        raise PipelineConfigError(f"Pipeline '{name}': invalid default_timeout {default_timeout!r}") from None

    return PipelineConfig(
        name=name,
        steps=tuple(steps),
        on_error=on_error,
        default_timeout=default_timeout,
    )


def _parse_step_config(
    pipeline_name: str,
    index: int,
    data: dict[str, Any],
) -> StepConfig:
    """Parse raw step config data into a StepConfig.

    Args:
        pipeline_name: Parent pipeline name (for error messages).
        index: Step index (for error messages).
        data: Raw step config dict.

    Returns:
        Validated StepConfig.

    Raises:
        PipelineConfigError: If step config is invalid.
    """
    step_name = data.get("name")
    if not step_name:
        raise PipelineConfigError(f"Pipeline '{pipeline_name}': step {index} missing 'name'")

    raw_type = data.get("type", "shell")
    try:
        step_type = StepType(raw_type)
    except ValueError:
        raise PipelineConfigError(f"Pipeline '{pipeline_name}': step '{step_name}' invalid type {raw_type!r}") from None

    raw_when = data.get("when", "always")
    try:
        when = StepCondition(raw_when)
    except ValueError:
        raise PipelineConfigError(f"Pipeline '{pipeline_name}': step '{step_name}' invalid when {raw_when!r}") from None

    # Parse args as tuple
    raw_args = data.get("args", [])
    if isinstance(raw_args, str):
        raw_args = [raw_args]
    args = tuple(str(a) for a in raw_args)

    # Parse timeout
    timeout = data.get("timeout")
    if timeout is not None:
        try:
            timeout = float(timeout)
        except (TypeError, ValueError):
            raise PipelineConfigError(
                f"Pipeline '{pipeline_name}': step '{step_name}' invalid timeout {timeout!r}"
            ) from None

    return StepConfig(
        name=step_name,
        type=step_type,
        command=data.get("command"),
        module=data.get("module"),
        callable=data.get("callable"),
        args=args,
        env=data.get("env", {}),
        working_dir=data.get("working_dir"),
        timeout=timeout,
        when=when,
    )


def _with_timeout(config: StepConfig, timeout: float) -> StepConfig:
    """Create a copy of a StepConfig with a different timeout.

    Uses ``object.__setattr__`` since StepConfig is frozen.

    Args:
        config: Original step config.
        timeout: New timeout value.

    Returns:
        New StepConfig with the specified timeout.
    """
    new = StepConfig(
        name=config.name,
        type=config.type,
        command=config.command,
        module=config.module,
        callable=config.callable,
        args=config.args,
        env=config.env,
        working_dir=config.working_dir,
        timeout=timeout,
        when=config.when,
    )
    return new


__all__ = [
    "PipelineRunner",
]
