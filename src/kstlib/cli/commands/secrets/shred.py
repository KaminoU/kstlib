"""Shred command for secrets subsystem."""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from kstlib.cli.common import (
    CommandResult,
    CommandStatus,
    exit_with_result,
    render_result,
)

from .common import (
    SHRED_CMD_CHUNK_SIZE_OPTION,
    SHRED_CMD_METHOD_OPTION,
    SHRED_CMD_PASSES_OPTION,
    SHRED_CMD_QUIET_OPTION,
    SHRED_CMD_ZERO_LAST_OPTION,
    SHRED_FORCE_OPTION,
    SHRED_TARGET_ARG,
    ShredCommandOptions,
    shred_file,
)

if TYPE_CHECKING:
    from pathlib import Path
else:  # pragma: no cover - runtime alias for Typer conversions
    import pathlib

    Path = pathlib.Path


def _execute_shred(target: Path, options: ShredCommandOptions) -> None:
    """Perform the shredding workflow using the provided options."""
    if not options.force:
        confirmed = typer.confirm(f"Remove '{target}' permanently?", default=False)
        if not confirmed:
            result = CommandResult(
                status=CommandStatus.WARNING,
                message=f"Shred aborted; file '{target}' not removed.",
            )
            exit_with_result(result, options.quiet, exit_code=1)

    report = shred_file(
        target,
        method=options.method,
        passes=options.passes,
        zero_last_pass=options.zero_last_pass,
        chunk_size=options.chunk_size,
    )
    if not report.success:
        result = CommandResult(
            status=CommandStatus.ERROR,
            message=report.message or f"Failed to remove '{target}'. Check permissions and try again.",
        )
        exit_with_result(result, options.quiet, exit_code=1)

    detail = f"{report.method.value} ({report.passes} passes)"
    if report.command:
        detail += f" via {' '.join(report.command)}"
    result = CommandResult(
        status=CommandStatus.OK,
        message=f"Secret file '{target}' removed using {detail}.",
    )
    if options.quiet:
        raise typer.Exit(code=0)
    render_result(result)


# pylint: disable=too-many-arguments,too-many-positional-arguments
def shred(
    target: Path = SHRED_TARGET_ARG,
    *,
    force: bool = SHRED_FORCE_OPTION,
    method: str | None = SHRED_CMD_METHOD_OPTION,
    passes: int | None = SHRED_CMD_PASSES_OPTION,
    zero_last_pass: bool | None = SHRED_CMD_ZERO_LAST_OPTION,
    chunk_size: int | None = SHRED_CMD_CHUNK_SIZE_OPTION,
    quiet: bool = SHRED_CMD_QUIET_OPTION,
) -> None:
    """Remove a secrets file from disk."""
    options = ShredCommandOptions(
        force=force,
        method=method,
        passes=passes,
        zero_last_pass=zero_last_pass,
        chunk_size=chunk_size,
        quiet=quiet,
    )
    _execute_shred(target, options)


__all__ = ["shred"]
