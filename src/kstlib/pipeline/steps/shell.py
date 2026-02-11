"""Shell step executor for pipeline.

Executes shell commands via ``subprocess.run(shell=True)`` with
timeout, environment variable injection, and working directory support.

Multi-line commands are supported natively via YAML folded (``>-``) or
literal (``|``) block scalars. The resulting string is passed as-is to
``subprocess.run(shell=True)``, so loops, pipes, and redirections work.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time

from kstlib.pipeline.models import StepConfig, StepResult, StepStatus

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

        # Build environment
        env = {**os.environ, **config.env} if config.env else None

        # Resolve working directory
        workdir = os.path.expandvars(config.working_dir) if config.working_dir else None

        start = time.monotonic()
        try:
            proc = subprocess.run(  # noqa: S602
                command,
                shell=True,
                capture_output=True,
                text=True,
                check=False,
                timeout=config.timeout,
                env=env,
                cwd=workdir,
            )
            duration = time.monotonic() - start

            status = StepStatus.SUCCESS if proc.returncode == 0 else StepStatus.FAILED
            error = proc.stderr.strip() if proc.returncode != 0 else None

            if status == StepStatus.FAILED:
                logger.warning(
                    "ShellStep '%s' failed (rc=%d): %s",
                    config.name,
                    proc.returncode,
                    error or "(no stderr)",
                )

            return StepResult(
                name=config.name,
                status=status,
                stdout=proc.stdout,
                stderr=proc.stderr,
                return_code=proc.returncode,
                duration=duration,
                error=error,
            )

        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start
            logger.warning(
                "ShellStep '%s' timed out after %.1fs",
                config.name,
                config.timeout,
            )
            return StepResult(
                name=config.name,
                status=StepStatus.TIMEOUT,
                duration=duration,
                error=f"Timed out after {config.timeout}s",
            )

        except OSError as exc:
            duration = time.monotonic() - start
            logger.exception(
                "ShellStep '%s' OS error",
                config.name,
            )
            return StepResult(
                name=config.name,
                status=StepStatus.FAILED,
                duration=duration,
                error=str(exc),
            )


__all__ = [
    "ShellStep",
]
