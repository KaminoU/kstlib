"""Callable step executor for pipeline.

Imports and calls a Python function directly using ``importlib``.
The callable target format is ``module.path:function_name``.

Note:
    Callable steps do not support timeout natively. If timeout control
    is needed, use a shell or python step instead.
"""

from __future__ import annotations

import importlib
import logging
import time

from kstlib.pipeline.exceptions import StepImportError
from kstlib.pipeline.models import StepConfig, StepResult, StepStatus

logger = logging.getLogger(__name__)


class CallableStep:
    """Execute a Python callable as a pipeline step.

    Parses the ``callable`` target as ``module.path:function_name``,
    imports the module, and calls the function. The return value
    is captured in ``StepResult.return_value``.

    Examples:
        >>> from kstlib.pipeline.models import StepConfig, StepType
        >>> step = CallableStep()
        >>> config = StepConfig(
        ...     name="process",
        ...     type=StepType.CALLABLE,
        ...     callable="json:dumps",
        ... )
        >>> result = step.execute(config)  # doctest: +SKIP
    """

    def execute(
        self,
        config: StepConfig,
        *,
        dry_run: bool = False,
    ) -> StepResult:
        """Execute a Python callable.

        Args:
            config: Step configuration with callable target, args, etc.
            dry_run: If True, log the callable without executing it.

        Returns:
            StepResult with return_value, duration, and status.
        """
        target = config.callable or ""
        logger.debug("CallableStep '%s': target=%r", config.name, target)

        if dry_run:
            logger.info(
                "[DRY RUN] CallableStep '%s': %s",
                config.name,
                target,
            )
            return StepResult(
                name=config.name,
                status=StepStatus.SKIPPED,
                stdout=f"[dry-run] would call: {target}",
            )

        # Parse target
        module_path, _, func_name = target.rpartition(":")
        if not module_path or not func_name:
            return StepResult(
                name=config.name,
                status=StepStatus.FAILED,
                error=f"Invalid callable target: {target!r}",
            )

        # Import and resolve function
        try:
            module = importlib.import_module(module_path)
            func = getattr(module, func_name)
        except (ImportError, AttributeError) as exc:
            logger.exception(
                "CallableStep '%s' import error",
                config.name,
            )
            raise StepImportError(config.name, target) from exc

        # Call the function
        start = time.monotonic()
        try:
            return_value = func(*config.args)
            duration = time.monotonic() - start

            logger.debug(
                "CallableStep '%s' completed in %.3fs",
                config.name,
                duration,
            )

            return StepResult(
                name=config.name,
                status=StepStatus.SUCCESS,
                return_value=return_value,
                duration=duration,
            )

        except Exception as exc:
            duration = time.monotonic() - start
            logger.exception(
                "CallableStep '%s' execution error",
                config.name,
            )
            return StepResult(
                name=config.name,
                status=StepStatus.FAILED,
                duration=duration,
                error=str(exc),
            )


__all__ = [
    "CallableStep",
]
