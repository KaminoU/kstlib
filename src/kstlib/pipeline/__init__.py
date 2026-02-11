"""Declarative pipeline execution for kstlib.

This module provides config-driven pipeline execution for sequential
workflows combining shell commands, Python modules, and callable functions.

Pipelines can be defined programmatically or declared in ``kstlib.conf.yml``
and executed with error handling, conditional steps, and dry-run support.

Examples:
    Programmatic pipeline:

    >>> from kstlib.pipeline import PipelineRunner, PipelineConfig, StepConfig, StepType
    >>> config = PipelineConfig(
    ...     name="demo",
    ...     steps=(
    ...         StepConfig(name="greet", type=StepType.SHELL, command="echo hello"),
    ...     ),
    ... )
    >>> runner = PipelineRunner(config)
    >>> result = runner.run()  # doctest: +SKIP

    Config-driven pipeline:

    >>> runner = PipelineRunner.from_config("morning")  # doctest: +SKIP
    >>> result = runner.run()  # doctest: +SKIP
"""

from kstlib.pipeline.base import AbstractStep
from kstlib.pipeline.exceptions import (
    PipelineAbortedError,
    PipelineConfigError,
    PipelineError,
    StepError,
    StepImportError,
    StepTimeoutError,
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
from kstlib.pipeline.runner import PipelineRunner
from kstlib.pipeline.steps import CallableStep, PythonStep, ShellStep

__all__ = [
    "AbstractStep",
    "CallableStep",
    "ErrorPolicy",
    "PipelineAbortedError",
    "PipelineConfig",
    "PipelineConfigError",
    "PipelineError",
    "PipelineResult",
    "PipelineRunner",
    "PythonStep",
    "ShellStep",
    "StepCondition",
    "StepConfig",
    "StepError",
    "StepImportError",
    "StepResult",
    "StepStatus",
    "StepTimeoutError",
    "StepType",
]
