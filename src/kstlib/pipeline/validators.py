"""Input validation for kstlib.pipeline module.

This module provides validation functions for pipeline configuration,
implementing deep defense against malformed or malicious input.

Reuses security validators from ``kstlib.ops.validators`` for command
and environment variable validation.
"""

from __future__ import annotations

import re

from kstlib.ops.validators import (
    DANGEROUS_PATTERNS,
    validate_command,
    validate_env,
)
from kstlib.pipeline.exceptions import PipelineConfigError

# ============================================================================
# Constants - Hard Limits
# ============================================================================

#: Maximum step name length.
MAX_STEP_NAME_LENGTH = 64

#: Pattern for valid step names (same rules as session names).
STEP_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")

#: Maximum number of steps in a single pipeline.
MAX_PIPELINE_STEPS = 50

#: Maximum number of arguments for a step.
MAX_STEP_ARGS = 50

#: Maximum length of a callable target string.
MAX_CALLABLE_TARGET_LENGTH = 256

#: Pattern for valid callable targets (module.path:function_name).
CALLABLE_TARGET_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.]*:[a-zA-Z_][a-zA-Z0-9_]*$")

#: Pattern for valid Python module names.
MODULE_NAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.]*$")

#: Maximum length of a module name.
MAX_MODULE_NAME_LENGTH = 256


# ============================================================================
# Validation Functions
# ============================================================================


def validate_step_name(name: str) -> str:
    """Validate and return a step name.

    Rules:
    - Cannot be empty
    - Max 64 characters (hard limit)
    - Must start with a letter
    - Only alphanumeric, underscore, hyphen allowed

    Args:
        name: Step name to validate.

    Returns:
        The validated step name (unchanged).

    Raises:
        PipelineConfigError: If name is invalid.

    Examples:
        >>> validate_step_name("build_logs")
        'build_logs'
        >>> validate_step_name("step-01")
        'step-01'
        >>> validate_step_name("")
        Traceback (most recent call last):
            ...
        kstlib.pipeline.exceptions.PipelineConfigError: Step name cannot be empty
    """
    if not name:
        raise PipelineConfigError("Step name cannot be empty")
    if len(name) > MAX_STEP_NAME_LENGTH:
        raise PipelineConfigError(f"Step name too long (max {MAX_STEP_NAME_LENGTH} chars)")
    if not STEP_NAME_PATTERN.match(name):
        raise PipelineConfigError(
            "Step name must start with a letter and contain only alphanumeric, underscore, or hyphen characters"
        )
    return name


def validate_callable_target(target: str) -> str:
    """Validate a callable target string.

    Expected format: ``module.path:function_name``

    Args:
        target: Callable target string to validate.

    Returns:
        The validated target (unchanged).

    Raises:
        PipelineConfigError: If target is invalid.

    Examples:
        >>> validate_callable_target("mymodule:run")
        'mymodule:run'
        >>> validate_callable_target("my.pkg.module:do_work")
        'my.pkg.module:do_work'
    """
    if not target:
        raise PipelineConfigError("Callable target cannot be empty")
    if len(target) > MAX_CALLABLE_TARGET_LENGTH:
        raise PipelineConfigError(f"Callable target too long (max {MAX_CALLABLE_TARGET_LENGTH} chars)")
    if not CALLABLE_TARGET_PATTERN.match(target):
        raise PipelineConfigError(f"Invalid callable target format: {target!r} (expected 'module.path:function_name')")
    return target


def validate_module_name(module: str) -> str:
    """Validate a Python module name.

    Args:
        module: Module name to validate (e.g. ``my.package.module``).

    Returns:
        The validated module name (unchanged).

    Raises:
        PipelineConfigError: If module name is invalid.

    Examples:
        >>> validate_module_name("mymodule")
        'mymodule'
        >>> validate_module_name("my.package.module")
        'my.package.module'
    """
    if not module:
        raise PipelineConfigError("Module name cannot be empty")
    if len(module) > MAX_MODULE_NAME_LENGTH:
        raise PipelineConfigError(f"Module name too long (max {MAX_MODULE_NAME_LENGTH} chars)")
    if not MODULE_NAME_PATTERN.match(module):
        raise PipelineConfigError(f"Invalid module name format: {module!r}")
    return module


def validate_step_config(  # noqa: PLR0913
    *,
    name: str,
    step_type: str,
    command: str | None = None,
    module: str | None = None,
    callable_target: str | None = None,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> None:
    """Validate a step configuration.

    Checks that the step has the required fields for its type and
    that all values pass validation.

    Args:
        name: Step name.
        step_type: Step type (shell, python, callable).
        command: Shell command (required for shell type).
        module: Python module (required for python type).
        callable_target: Import target (required for callable type).
        args: Arguments list.
        env: Environment variables.

    Raises:
        PipelineConfigError: If configuration is invalid.
    """
    validate_step_name(name)

    if step_type == "shell":
        if not command:
            raise PipelineConfigError(f"Step '{name}': shell step requires a 'command'")
        validate_command(command)
    elif step_type == "python":
        if not module:
            raise PipelineConfigError(f"Step '{name}': python step requires a 'module'")
        validate_module_name(module)
    elif step_type == "callable":
        if not callable_target:
            raise PipelineConfigError(f"Step '{name}': callable step requires a 'callable' target")
        validate_callable_target(callable_target)
    else:
        raise PipelineConfigError(
            f"Step '{name}': unknown step type {step_type!r} (expected 'shell', 'python', or 'callable')"
        )

    if args is not None and len(args) > MAX_STEP_ARGS:
        raise PipelineConfigError(f"Step '{name}': too many arguments (max {MAX_STEP_ARGS})")

    if env is not None:
        validate_env(env)


def validate_pipeline_config(
    *,
    step_count: int,
    on_error: str,
) -> None:
    """Validate pipeline-level configuration.

    Args:
        step_count: Number of steps in the pipeline.
        on_error: Error policy string.

    Raises:
        PipelineConfigError: If configuration is invalid.
    """
    if step_count == 0:
        raise PipelineConfigError("Pipeline must have at least one step")
    if step_count > MAX_PIPELINE_STEPS:
        raise PipelineConfigError(f"Too many steps (max {MAX_PIPELINE_STEPS})")
    if on_error not in ("fail_fast", "continue"):
        raise PipelineConfigError(f"Invalid error policy {on_error!r} (expected 'fail_fast' or 'continue')")


__all__ = [
    "CALLABLE_TARGET_PATTERN",
    "DANGEROUS_PATTERNS",
    "MAX_CALLABLE_TARGET_LENGTH",
    "MAX_MODULE_NAME_LENGTH",
    "MAX_PIPELINE_STEPS",
    "MAX_STEP_ARGS",
    "MAX_STEP_NAME_LENGTH",
    "MODULE_NAME_PATTERN",
    "STEP_NAME_PATTERN",
    "validate_callable_target",
    "validate_command",
    "validate_env",
    "validate_module_name",
    "validate_pipeline_config",
    "validate_step_config",
    "validate_step_name",
]
