"""Specialized exceptions raised by the kstlib.pipeline module.

Exception hierarchy::

    KstlibError
        PipelineError (base for all pipeline errors)
            PipelineConfigError (invalid configuration, also ValueError)
            PipelineAbortedError (fail_fast abort)
            StepError (step execution error)
                StepTimeoutError (step exceeded timeout)
                StepImportError (callable import failure)
"""

from __future__ import annotations

from kstlib.config.exceptions import KstlibError


class PipelineError(KstlibError):
    """Base exception for all pipeline module errors.

    All pipeline-specific exceptions inherit from this class,
    allowing for easy catching of any pipeline error.
    """


class PipelineConfigError(PipelineError, ValueError):
    """Pipeline configuration is invalid.

    Raised when the pipeline or step configuration contains
    invalid values, missing required fields, or constraint
    violations.
    """


class PipelineAbortedError(PipelineError):
    """Pipeline execution was aborted due to fail_fast policy.

    Raised when a step fails and the error policy is ``fail_fast``,
    causing the remaining steps to be skipped.

    Attributes:
        step_name: Name of the step that caused the abort.
        reason: Description of why the step failed.
    """

    def __init__(self, step_name: str, reason: str) -> None:
        """Initialize PipelineAbortedError.

        Args:
            step_name: Name of the step that caused the abort.
            reason: Description of why the step failed.
        """
        super().__init__(f"Pipeline aborted at step '{step_name}': {reason}")
        self.step_name = step_name
        self.reason = reason


class StepError(PipelineError):
    """A pipeline step failed during execution.

    Attributes:
        step_name: Name of the step that failed.
        reason: Description of the failure.
    """

    def __init__(self, step_name: str, reason: str) -> None:
        """Initialize StepError.

        Args:
            step_name: Name of the step that failed.
            reason: Description of the failure.
        """
        super().__init__(f"Step '{step_name}' failed: {reason}")
        self.step_name = step_name
        self.reason = reason


class StepTimeoutError(StepError):
    """A pipeline step exceeded its timeout.

    Attributes:
        step_name: Name of the step that timed out.
        timeout: The timeout value in seconds.
    """

    def __init__(self, step_name: str, timeout: float) -> None:
        """Initialize StepTimeoutError.

        Args:
            step_name: Name of the step that timed out.
            timeout: The timeout value in seconds.
        """
        super().__init__(step_name, f"exceeded timeout of {timeout}s")
        self.timeout = timeout


class StepImportError(StepError):
    """Failed to import a callable target for a step.

    Attributes:
        step_name: Name of the step with the import failure.
        target: The import target string that failed.
    """

    def __init__(self, step_name: str, target: str) -> None:
        """Initialize StepImportError.

        Args:
            step_name: Name of the step with the import failure.
            target: The import target string (e.g. "module.path:function").
        """
        super().__init__(step_name, f"cannot import '{target}'")
        self.target = target


__all__ = [
    "PipelineAbortedError",
    "PipelineConfigError",
    "PipelineError",
    "StepError",
    "StepImportError",
    "StepTimeoutError",
]
