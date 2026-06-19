"""CLI commands for REST API client (rapi)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer
from typer.core import TyperGroup

from kstlib.cli.common import err_console
from kstlib.rapi import load_rapi_config

if TYPE_CHECKING:
    import click

    from kstlib.rapi.config import RapiConfigManager

# Known subcommands that should not be treated as endpoints
_SUBCOMMANDS = {"list", "call", "show", "--help", "-h", "help"}


def _load_config_or_exit() -> RapiConfigManager:
    """Load rapi config or exit the CLI with a friendly error message.

    Shared by ``rapi list``, ``rapi show``, and ``rapi call`` to keep
    a single failure mode for config loading.

    Returns:
        The loaded RapiConfigManager.

    Raises:
        typer.Exit: Exit code 1 if loading fails for any reason.

    """
    try:
        return load_rapi_config()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        err_console.print(f"[red]Failed to load rapi config: {exc}[/]")
        raise typer.Exit(code=1) from exc


# Sub-command imports come AFTER _load_config_or_exit so the callers
# can import it without triggering a circular-import failure.
from .call import _CallCommand, call  # noqa: E402
from .list import list_endpoints  # noqa: E402
from .show import show_endpoint  # noqa: E402


class RapiGroup(TyperGroup):
    """Custom Typer Group that treats unknown commands as endpoint calls."""

    def resolve_command(
        self,
        ctx: click.Context,
        args: list[str],
    ) -> tuple[str | None, click.Command | None, list[str]]:
        """Override command resolution to treat unknown commands as endpoints."""
        # Rewrite BEFORE resolution instead of catching the resolution error:
        # Typer 0.26+ ships a vendored click whose UsageError is a distinct
        # class from click.UsageError, so an except-based fallback never
        # matches there. get_command() returning None for unknown names is
        # the contract that holds across all supported Typer versions.
        if args and args[0] not in _SUBCOMMANDS and "." in args[0] and self.get_command(ctx, args[0]) is None:
            # Treat as implicit call: prepend "call" to args
            args = ["call", *args]
        return super().resolve_command(ctx, args)


rapi_app = typer.Typer(
    help="Config-driven REST API client.",
    cls=RapiGroup,
)

# Register explicit commands
rapi_app.command(name="list")(list_endpoints)
rapi_app.command(name="show")(show_endpoint)
# Keep "call" for explicit usage (shown in help). The custom command class
# gives --show-extracted its optional-value behavior (token normalization).
rapi_app.command(name="call", hidden=False, cls=_CallCommand)(call)


def register_cli(app: typer.Typer) -> None:
    """Register the rapi sub-commands on the root Typer app."""
    app.add_typer(rapi_app, name="rapi")


__all__ = [
    "_load_config_or_exit",
    "call",
    "list_endpoints",
    "rapi_app",
    "register_cli",
    "show_endpoint",
]
