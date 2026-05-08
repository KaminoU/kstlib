"""Shared helpers for subprocess-based pipeline steps.

``ShellStep`` and ``PythonStep`` share the same execution skeleton: build
environment + workdir, call ``subprocess.run`` with matching kwargs,
convert the outcome to :class:`StepResult`, and map ``TimeoutExpired``
and ``OSError`` to ``TIMEOUT``/``FAILED`` statuses.

This module extracts that skeleton into :func:`_run_subprocess` so both
executors delegate to a single implementation and cannot drift.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from typing import TYPE_CHECKING

from kstlib.pipeline.models import StepConfig, StepResult, StepStatus

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


def _run_subprocess(
    cmd: str | Sequence[str],
    config: StepConfig,
    *,
    shell: bool,
    log_tag: str,
) -> StepResult:
    """Run ``cmd`` under ``subprocess.run`` and convert the outcome.

    Args:
        cmd: Command string (``shell=True``) or argv list (``shell=False``).
        config: Originating step configuration. Used for env, working_dir,
            timeout and the name carried in the returned :class:`StepResult`.
        shell: Whether to invoke a shell interpreter.
        log_tag: Prefix used in log messages (e.g. ``"ShellStep"``).

    Returns:
        StepResult with stdout/stderr/return_code/status/duration populated.

    """
    env = {**os.environ, **config.env} if config.env else None
    workdir = os.path.expandvars(config.working_dir) if config.working_dir else None
    if workdir and "\x00" in workdir:
        raise ValueError(f"Null bytes not allowed in working_dir for step '{config.name}'")

    start = time.monotonic()
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            shell=shell,
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
            # Drop stderr from the log: subprocess stderr from arbitrary user
            # commands (curl, psql, sshpass, etc.) routinely contains
            # credentials we cannot generically sanitize. The full stderr is
            # still preserved in StepResult.stderr / StepResult.error for the
            # caller to inspect deliberately.
            logger.warning(
                "%s '%s' failed (rc=%d). See StepResult.stderr for details (not logged for safety).",
                log_tag,
                config.name,
                proc.returncode,
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
            "%s '%s' timed out after %.1fs",
            log_tag,
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
            "%s '%s' OS error",
            log_tag,
            config.name,
        )
        return StepResult(
            name=config.name,
            status=StepStatus.FAILED,
            duration=duration,
            error=str(exc),
        )


__all__ = ["_run_subprocess"]
