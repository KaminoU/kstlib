"""Decrypt command for secrets subsystem."""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from kstlib.cli.common import (
    CommandResult,
    CommandStatus,
    console,
    exit_with_result,
    render_result,
)

from .common import (
    DECRYPT_SOURCE_ARG,
    FORCE_OPTION,
    OUT_OPTION,
    QUIET_OPTION,
    resolve_sops_binary,
    run_sops_command,
)

if TYPE_CHECKING:
    from pathlib import Path
else:  # pragma: no cover - runtime alias for Typer conversions
    import pathlib

    Path = pathlib.Path


def _build_decrypt_args(
    source: Path,
    out: Path | None,
) -> list[str]:
    """Build arguments for ``sops --decrypt``."""
    arguments = ["--decrypt"]
    if out is not None:
        arguments.extend(["--output", str(out)])
    arguments.append(str(source))
    return arguments


def decrypt(
    source: Path = DECRYPT_SOURCE_ARG,
    out: Path | None = OUT_OPTION,
    force: bool = FORCE_OPTION,
    quiet: bool = QUIET_OPTION,
) -> None:
    """Decrypt a SOPS file."""
    binary = resolve_sops_binary()
    if out is not None and out.exists() and not force:
        result = CommandResult(
            status=CommandStatus.ERROR,
            message=f"Refuse to overwrite existing file: {out} (use --force).",
        )
        exit_with_result(result, quiet, exit_code=1)

    try:
        completed = run_sops_command(binary, _build_decrypt_args(source, out))
    except FileNotFoundError as exc:
        result = CommandResult(
            status=CommandStatus.ERROR,
            message=f"SOPS binary '{binary}' not found. Install it or set secrets.sops.binary in the config.",
        )
        exit_with_result(result, quiet, exit_code=1, cause=exc)

    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "sops command failed"
        result = CommandResult(status=CommandStatus.ERROR, message=message)
        exit_with_result(result, quiet, exit_code=1)

    if out is None and completed.stdout and not quiet:
        console.print(completed.stdout.rstrip("\n"))

    target_info = str(out) if out else "stdout"
    result = CommandResult(
        status=CommandStatus.OK,
        message=f"Decrypted secrets written to {target_info}.",
    )
    if quiet:
        raise typer.Exit(code=0)
    render_result(result)


__all__ = ["decrypt"]
