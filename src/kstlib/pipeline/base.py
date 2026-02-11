"""Abstract base protocol for pipeline steps.

This module defines the protocol that all pipeline step implementations
must satisfy, enabling consistent execution across shell, python,
and callable step types.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from kstlib.pipeline.models import StepConfig, StepResult


@runtime_checkable
class AbstractStep(Protocol):
    """Protocol defining the interface for pipeline step executors.

    All step implementations (ShellStep, PythonStep, CallableStep) must
    implement this protocol to ensure consistent behavior across step types.

    Examples:
        >>> def run_step(step: AbstractStep, config: StepConfig) -> StepResult:
        ...     return step.execute(config)
    """

    def execute(
        self,
        config: StepConfig,
        *,
        dry_run: bool = False,
    ) -> StepResult:
        """Execute a pipeline step.

        Args:
            config: Step configuration with command, env, timeout, etc.
            dry_run: If True, simulate execution without side effects.

        Returns:
            StepResult with status, stdout, stderr, duration, etc.
        """
        ...


__all__ = [
    "AbstractStep",
]
