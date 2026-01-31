"""Shared CLI utilities for kstlib commands."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, NoReturn

import typer
from rich.console import Console
from rich.panel import Panel
from rich.pretty import Pretty

console = Console()


class CommandStatus(str, Enum):
    """Represents the outcome of a CLI command."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


@dataclass(slots=True)
class CommandResult:
    """Summary payload produced by a command handler."""

    status: CommandStatus
    message: str
    payload: dict[str, Any] | None = None


STYLE_MAP = {
    CommandStatus.OK: "green",
    CommandStatus.WARNING: "yellow",
    CommandStatus.ERROR: "red",
}


def render_result(result: CommandResult) -> None:
    """Render a command result using Rich components."""
    style = STYLE_MAP[result.status]
    console.print(Panel(result.message, title=result.status.value.upper(), style=style, border_style=style))
    if result.payload is not None:
        console.print(Pretty(result.payload))


def emit_result(result: CommandResult, quiet: bool) -> None:
    """Output a command result honoring the quiet flag."""
    if quiet:
        console.print(result.message, style=STYLE_MAP[result.status])
    else:
        render_result(result)


def exit_with_result(
    result: CommandResult,
    quiet: bool,
    exit_code: int,
    *,
    cause: Exception | None = None,
) -> NoReturn:
    """Render ``result`` and raise ``typer.Exit`` with ``exit_code``."""
    emit_result(result, quiet)
    if cause is None:
        raise typer.Exit(code=exit_code)
    raise typer.Exit(code=exit_code) from cause


def exit_error(message: str) -> NoReturn:
    """Render an error result and exit with code 1."""
    render_result(CommandResult(status=CommandStatus.ERROR, message=message))
    raise typer.Exit(code=1)


__all__ = [
    "STYLE_MAP",
    "CommandResult",
    "CommandStatus",
    "console",
    "emit_result",
    "exit_error",
    "exit_with_result",
    "render_result",
]
