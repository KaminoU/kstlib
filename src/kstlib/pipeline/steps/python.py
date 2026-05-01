"""Python module step executor for pipeline.

Executes Python modules via ``subprocess.run([sys.executable, "-m", module])``.
Runs in a subprocess (not ``shell=True``) for isolation and security.
"""

from __future__ import annotations

import logging
import sys

from kstlib.pipeline.models import StepConfig, StepResult, StepStatus
from kstlib.pipeline.steps._base import _run_subprocess
from kstlib.pipeline.steps._helpers import _sanitize_command

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
        # Best-effort redaction for log output; the unredacted argv is
        # still passed verbatim to subprocess for execution.
        safe_cmd_str = _sanitize_command(cmd)
        logger.debug("PythonStep '%s': cmd=%s", config.name, safe_cmd_str)

        if dry_run:
            logger.info("[DRY RUN] PythonStep '%s': %s", config.name, safe_cmd_str)
            return StepResult(
                name=config.name,
                status=StepStatus.SKIPPED,
                stdout=f"[dry-run] would execute: {safe_cmd_str}",
            )

        return _run_subprocess(cmd, config, shell=False, log_tag="PythonStep")


__all__ = [
    "PythonStep",
]
