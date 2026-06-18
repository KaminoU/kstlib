"""Shared TRACE-level logging helper (private to kstlib internals).

Consolidates the ``_log_trace`` helper that was previously duplicated across
several sub-packages into a single shared emitter. Modules pass their own
logger so emission stays attributed to the calling module's name.

This module must never import ``kstlib.logging`` at top level: see
:func:`log_trace` for the circular-import rationale.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import logging

__all__ = ["log_trace"]


def log_trace(logger: logging.Logger, msg: str, *args: object) -> None:
    """Emit a TRACE-level (custom level 5) record on the given logger.

    Args:
        logger: Target standard-library logger to emit the record on.
        msg: Log message, optionally containing ``%``-style placeholders.
        *args: Positional arguments interpolated into ``msg`` lazily by the
            logging framework (only when the record is actually emitted).

    Note:
        ``TRACE_LEVEL`` is imported lazily inside the function to avoid the
        circular import chain
        ``kstlib.logging.manager -> kstlib.config -> kstlib.config.sops``.
        Importing ``kstlib.logging`` at module top level would resurrect that
        cycle as soon as a cascade module (e.g. ``kstlib.config.sops``) imports
        this helper.
    """
    from kstlib.logging import TRACE_LEVEL

    logger.log(TRACE_LEVEL, msg, *args)
