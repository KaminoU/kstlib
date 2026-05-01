"""Command-line interface for kstlib.

This module provides the CLI commands using Typer and Rich for enhanced terminal output.
Available commands:
- info: Display package information and logo
- version: Show package version
"""

# pylint: disable=redefined-builtin
# Reason: Rich.print is imported to override builtin print for enhanced output

import logging
import re
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

# --- --log-module factorized parser -----------------------------------------

# Levels accepted on the --log-module flag (case-insensitive). Mirrors
# kstlib.logging.manager._VALID_LEVEL_NAMES (kept in sync manually to avoid
# importing a private symbol across sub-packages).
_LOG_MODULE_VALID_LEVELS: frozenset[str] = frozenset(
    {"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"},
)

# Logger name shape after the optional kstlib. auto-prepend. Forbids empty
# components, double dots, leading dot, and any character outside [A-Za-z0-9_].
_VALID_LOGGER_NAME = re.compile(r"^kstlib\.[a-zA-Z_]\w*(\.[a-zA-Z_]\w*)*$")

# Warnings from the parser go to the same internal logger LogManager uses for
# its own bootstrap diagnostics. Activate with:
#   logging.getLogger("kstlib_logging_internal").setLevel(logging.WARNING)
_log_module_parser_log = logging.getLogger("kstlib_logging_internal")


def _record_module_pair(raw_name: str, level: str, sink: dict[str, str]) -> None:
    """Auto-prepend ``kstlib.`` if missing, validate, and record.

    Pathological names (after prepend) are rejected with a
    ``WARNING [SECURITY]`` and dropped. Later entries overwrite earlier
    ones for the same fully-qualified logger.
    """
    name = raw_name if raw_name.startswith("kstlib.") else f"kstlib.{raw_name}"
    if not _VALID_LOGGER_NAME.match(name):
        _log_module_parser_log.warning(
            "[SECURITY] Invalid logger name %r from --log-module: must match "
            "kstlib.<component>[.<component>...] (alphanumeric + underscore), "
            "skipped",
            raw_name,
        )
        return
    sink[name] = level


def _parse_log_module_entries(entries: list[str]) -> dict[str, str]:
    """Parse ``--log-module`` raw entries into a ``{logger_name: level}`` mapping.

    Supported syntaxes (per entry, repeatable on the CLI):

    - ``kstlib.rapi.config=TRACE`` : classic, fully-qualified
    - ``rapi.config=TRACE``        : classic, ``kstlib.`` auto-prepended
    - ``DEBUG=foo.bar,baz.qux``    : inverse, level groups a module list

    Mode is decided on the LEFT side : a known level token (case-insensitive)
    triggers inverse mode ; anything else is treated as a module name.

    Pathological cases (no ``=``, empty side, unknown level, malformed
    logger name, empty inverse list) emit a ``WARNING`` on the
    ``kstlib_logging_internal`` logger and the offending occurrence is
    skipped. The parser never raises ; the program continues normally with
    whatever valid entries remain.
    """
    resolved: dict[str, str] = {}
    for entry in entries:
        left, sep, right = entry.partition("=")
        left = left.strip()
        right = right.strip()
        if not sep or not left or not right:
            _log_module_parser_log.warning(
                "Invalid --log-module format %r: expected name=level or level=name1,name2,..., skipped",
                entry,
            )
            continue

        if left.upper() in _LOG_MODULE_VALID_LEVELS:
            # Inverse mode : LEVEL=name1,name2,...
            level = left.upper()
            modules = [m.strip() for m in right.split(",") if m.strip()]
            if not modules:
                _log_module_parser_log.warning(
                    "Invalid --log-module format %r: expected name=level or level=name1,name2,..., skipped",
                    entry,
                )
                continue
            for raw_name in modules:
                _record_module_pair(raw_name, level, resolved)
        else:
            # Classic mode : name=LEVEL
            level_upper = right.upper()
            if level_upper not in _LOG_MODULE_VALID_LEVELS:
                _log_module_parser_log.warning(
                    "Invalid level %r for logger %r from --log-module: expected one of %s, skipped",
                    right,
                    left,
                    sorted(_LOG_MODULE_VALID_LEVELS),
                )
                continue
            _record_module_pair(left, level_upper, resolved)
    return resolved


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
    log_module: Annotated[
        list[str] | None,
        typer.Option(
            "--log-module",
            help=(
                "Per-logger level override, repeatable. Three syntaxes : "
                "(1) kstlib.rapi.config=TRACE (fully-qualified), "
                "(2) rapi.config=TRACE (kstlib. auto-prepended), "
                "(3) DEBUG=foo.bar,baz.qux (level groups module list). "
                "Levels case-insensitive. When at least one --log-module is "
                "supplied, it REPLACES the kstlib.logging.modules cascade. "
                "Invalid entries warn on the kstlib_logging_internal logger "
                "and are skipped without aborting the command."
            ),
        ),
    ] = None,
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

    # Parse --log-module entries (name=level pairs, total override of YAML)
    init_config: dict[str, object] = {
        "console": {"level": level},
        "file": {"level": level},
        "output": output,
    }
    if log_module:
        # Pathological entries warn on kstlib_logging_internal and are
        # dropped silently from the perspective of the business command.
        # Only fully-qualified, validated pairs reach the manager.
        init_config["modules"] = _parse_log_module_entries(list(log_module))
    # Verbosity flags (-v/-vv/-vvv or --log-level) only adjust the root
    # handler level; they do NOT reset the YAML modules cascade. Default
    # mutes for verbose modules (kstlib.rapi.config, kstlib.config.loader)
    # stay in effect under -vvv so noisy modules cannot drown the output
    # the user actually wants. Bypass a specific mute via --log-module.

    # Always initialize logging so handlers are configured
    _cli_logger = init_logging(config=init_config)

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
