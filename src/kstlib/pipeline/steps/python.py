"""Python module step executor for pipeline.

Executes Python modules via ``subprocess.run([sys.executable, "-m", module])``.
Runs in a subprocess (not ``shell=True``) for isolation and security.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time

from kstlib.pipeline.models import StepConfig, StepResult, StepStatus

logger = logging.getLogger(__name__)


class PythonStep:
    """Execute a Python module as a pipeline step.

    Uses ``subprocess.run`` with ``[sys.executable, "-m", module, *args]``
    to run a Python module in a subprocess. Does not use ``shell=True``.

    Examples:
        >>> from kstlib.pipeline.models import StepConfig, StepType
        >>> step = PythonStep()
        >>> config = StepConfig(
        ...     name="lint",
        ...     type=StepType.PYTHON,
        ...     module="ruff",
        ...     args=("check", "src/"),
        ... )
        >>> result = step.execute(config)  # doctest: +SKIP
    """

    def execute(
        self,
        config: StepConfig,
        *,
        dry_run: bool = False,
    ) -> StepResult:
        """Execute a Python module via subprocess.

        Args:
            config: Step configuration with module, args, env, timeout, etc.
            dry_run: If True, log the command without executing it.

        Returns:
            StepResult with captured stdout, stderr, return code, and duration.
        """
        module = config.module or ""
        cmd = [sys.executable, "-m", module, *config.args]
        logger.debug("PythonStep '%s': cmd=%s", config.name, cmd)

        if dry_run:
            cmd_str = " ".join(cmd)
            logger.info("[DRY RUN] PythonStep '%s': %s", config.name, cmd_str)
            return StepResult(
                name=config.name,
                status=StepStatus.SKIPPED,
                stdout=f"[dry-run] would execute: {cmd_str}",
            )

        # Build environment
        env = {**os.environ, **config.env} if config.env else None

        # Resolve working directory
        workdir = os.path.expandvars(config.working_dir) if config.working_dir else None

        start = time.monotonic()
        try:
            proc = subprocess.run(  # noqa: S603
                cmd,
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
                    "PythonStep '%s' failed (rc=%d): %s",
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
                "PythonStep '%s' timed out after %.1fs",
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
                "PythonStep '%s' OS error",
                config.name,
            )
            return StepResult(
                name=config.name,
                status=StepStatus.FAILED,
                duration=duration,
                error=str(exc),
            )


__all__ = [
    "PythonStep",
]
