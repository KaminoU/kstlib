"""Shell step executor for pipeline.

Executes shell commands via ``subprocess.run(shell=True)`` with
timeout, environment variable injection, and working directory support.

Multi-line commands are supported natively via YAML folded (``>-``) or
literal (``|``) block scalars. The resulting string is passed as-is to
``subprocess.run(shell=True)``, so loops, pipes, and redirections work.
"""

from __future__ import annotations

import logging

from kstlib.pipeline.models import StepConfig, StepResult, StepStatus
from kstlib.pipeline.steps._base import _run_subprocess

logger = logging.getLogger(__name__)


class ShellStep:
    """Execute a shell command as a pipeline step.

    Uses ``subprocess.run`` with ``shell=True`` to execute the command
    string. Supports environment variable injection, working directory,
    and timeout.

    Examples:
        >>> from kstlib.pipeline.models import StepConfig, StepType
        >>> step = ShellStep()
        >>> config = StepConfig(
        ...     name="greet",
        ...     type=StepType.SHELL,
        ...     command="echo hello",
        ... )
        >>> result = step.execute(config)  # doctest: +SKIP
        >>> result.status  # doctest: +SKIP
        <StepStatus.SUCCESS: 'success'>

    """

    def execute(
        self,
        config: StepConfig,
        *,
        dry_run: bool = False,
    ) -> StepResult:
        """Execute a shell command.

        Args:
            config: Step configuration with command, env, timeout, etc.
            dry_run: If True, log the command without executing it.

        Returns:
            StepResult with captured stdout, stderr, return code, and duration.

        """
        command = config.command or ""
        logger.debug("ShellStep '%s': command=%r", config.name, command)

        if dry_run:
            logger.info("[DRY RUN] ShellStep '%s': %s", config.name, command)
            return StepResult(
                name=config.name,
                status=StepStatus.SKIPPED,
                stdout=f"[dry-run] would execute: {command}",
            )

        return _run_subprocess(command, config, shell=True, log_tag="ShellStep")  # noqa: S604


__all__ = [
    "ShellStep",
]
