"""CLI commands for configuration management."""

from __future__ import annotations

import pathlib
from typing import Annotated

import typer
from rich.panel import Panel

from kstlib.cli.common import console
from kstlib.config.export import (
    ConfigExportError,
    ConfigExportOptions,
    export_configuration,
)

config_app = typer.Typer(help="Configuration utilities.")


@config_app.command("export", help="Export the default configuration file.")
def export_command(
    section: Annotated[
        str | None,
        typer.Option(
            "--section",
            help="Optional dotted path selecting a subtree (e.g. utilities.secure_delete).",
        ),
    ] = None,
    out: Annotated[
        pathlib.Path | None,
        typer.Option(
            "--out",
            help=(
                "Destination file or directory. Defaults to ./kstlib.conf.yml when omitted. "
                "When a directory is provided, the default filename is used."
            ),
        ),
    ] = None,
    stdout: Annotated[
        bool,
        typer.Option(
            "--stdout",
            help="Write configuration to stdout instead of a file.",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Overwrite destination if it already exists.",
        ),
    ] = False,
) -> None:
    """Export default configuration to a file or stdout."""
    resolved_out = out.expanduser() if isinstance(out, pathlib.Path) else out
    options = ConfigExportOptions(section=section, out_path=resolved_out, stdout=stdout, force=force)

    try:
        result = export_configuration(options)
    except ConfigExportError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(code=1) from exc

    if stdout:
        if result.content is None:
            console.print("[bold red]Export failed: empty content.[/bold red]")
            raise typer.Exit(code=1)
        console.print(result.content)
        return

    if result.destination is None:
        console.print("[bold red]Export failed: missing destination file.[/bold red]")
        raise typer.Exit(code=1)
    console.print(
        Panel.fit(
            f"Configuration exported to [bold]{result.destination}[/bold]",
            title="kstlib config export",
            border_style="green",
        )
    )


def register_cli(app: typer.Typer) -> None:
    """Register configuration subcommands on the main CLI application."""
    app.add_typer(config_app, name="config")


__all__ = ["config_app", "register_cli"]
