"""Command-line interface for kstlib.

This module provides the CLI commands using Typer and Rich for enhanced terminal output.
Available commands:
- info: Display package information and logo
- version: Show package version
"""

# pylint: disable=redefined-builtin
# Reason: Rich.print is imported to override builtin print for enhanced output

import logging
from typing import Annotated

import typer
from rich import print
from rich.table import Table

from kstlib import meta
from kstlib.cli.commands.auth import register_cli as register_auth_cli
from kstlib.cli.commands.config import register_cli as register_config_cli
from kstlib.cli.commands.ops import register_cli as register_ops_cli
from kstlib.cli.commands.rapi import register_cli as register_rapi_cli
from kstlib.cli.commands.secrets import register_cli as register_secrets_cli
from kstlib.cli.commands.secrets import shred as secrets_shred
from kstlib.cli.common import console
from kstlib.logging import LogManager, get_logger, init_logging

app = typer.Typer(add_completion=False, name=meta.__app_name__)

# Global logger instance (initialized in main callback)
_cli_logger: LogManager | None = None

# Valid log levels
LOG_LEVELS = ["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

# Verbose flag mapping: -v=INFO, -vv=DEBUG, -vvv=TRACE
VERBOSE_LEVELS = {
    0: "WARNING",  # Default
    1: "INFO",  # -v
    2: "DEBUG",  # -vv
    3: "TRACE",  # -vvv
}


def _version_callback(value: bool) -> None:
    """Display version and exit if requested.

    Args:
        value: True if --version flag was passed.

    Raises:
        typer.Exit: Always exits after showing version.
    """
    if value:
        print(f"{meta.__version__}")
        raise typer.Exit()


def get_cli_logger() -> logging.Logger:
    """Get the CLI logger instance.

    Returns:
        The CLI logger. Uses the global kstlib logger if initialized
        via --log-level, otherwise returns a standard logger.
    """
    return get_logger("cli")


@app.callback()
def main(  # pylint: disable=unused-argument
    version: bool | None = typer.Option(
        None,
        "--version",
        help="Show the application's version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
    log_level: Annotated[
        str | None,
        typer.Option(
            "--log-level",
            "-l",
            help="Set logging level (TRACE, DEBUG, INFO, WARNING, ERROR, CRITICAL).",
            case_sensitive=False,
        ),
    ] = None,
    log_file: Annotated[
        bool,
        typer.Option(
            "--log-file",
            help="Enable file logging (writes to ./logs/kstlib.log by default).",
        ),
    ] = False,
    verbose: Annotated[
        int,
        typer.Option(
            "--verbose",
            "-v",
            count=True,
            help="Increase verbosity (-v=INFO, -vv=DEBUG, -vvv=TRACE).",
        ),
    ] = 0,
) -> None:
    """Initialize the root Typer app and handle --version eagerly."""
    global _cli_logger

    # Determine log level (priority: --log-level > -v > default)
    if log_level is not None:
        # Explicit --log-level takes precedence
        level = log_level.upper()
        if level not in LOG_LEVELS:
            console.print(f"[red]Invalid log level: {log_level}[/]")
            console.print(f"[dim]Valid levels: {', '.join(LOG_LEVELS)}[/]")
            raise typer.Exit(1)
    elif verbose > 0:
        # -v/-vv/-vvv flags
        level = VERBOSE_LEVELS.get(min(verbose, 3), "TRACE")
    else:
        level = "WARNING"  # Default: only warnings and errors

    # Determine output mode
    output = "both" if log_file else "console"

    # Always initialize logging so handlers are configured
    _cli_logger = init_logging(
        config={
            "console": {"level": level},
            "file": {"level": level},
            "output": output,
        },
    )

    if log_level is not None or verbose > 0:
        source = "--log-level" if log_level is not None else f"-{'v' * verbose}"
        _cli_logger.debug("CLI logging initialized", level=level, source=source)


@app.command()
def info(
    full: bool = typer.Option(
        False,
        "--full",
        "-f",
        help="Show full information about the application.",
    ),
) -> None:
    """Display package information and logo.

    Args:
        full: If True, show detailed package metadata including author, license, etc.
    """
    print(meta.__logo__)

    if full:
        _data = [
            ("Name", meta.__app_name__),
            ("Version", meta.__version__),
            ("Description", meta.__description__),
            ("Author", meta.__author__),
            ("Email", meta.__email__),
            ("URL", meta.__url__),
            ("Keywords", ", ".join(meta.__keywords__)),
            ("Classifiers", "\n".join(meta.__classifiers__)),
            ("License Type", meta.__license_type__),
            ("License", meta.__license__),
            ("", ""),
        ]

        table = Table(show_header=False, show_lines=False, title=None, box=None)
        table.add_column(justify="right")
        table.add_column(justify="left")

        for row in _data:
            table.add_row(f"[light_salmon1]{row[0]}[/]", row[1])

        console.print(table)

        return

    _version_callback(True)


register_auth_cli(app)
register_ops_cli(app)
register_rapi_cli(app)
register_secrets_cli(app)
register_config_cli(app)

# Expose shred as a top-level command for convenience.
app.command()(secrets_shred)


if __name__ == "__main__":
    app()
