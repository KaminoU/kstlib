"""CLI commands for REST API client (rapi)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import click
import typer
from typer.core import TyperGroup

from kstlib.cli.common import console
from kstlib.rapi import load_rapi_config

if TYPE_CHECKING:
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
        console.print(f"[red]Failed to load rapi config: {exc}[/]")
        raise typer.Exit(code=1) from exc


# Sub-command imports come AFTER _load_config_or_exit so the callers
# can import it without triggering a circular-import failure.
from .call import call  # noqa: E402
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
        # Try normal resolution first
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError:
            # If command not found and looks like an endpoint, redirect to call
            if args and args[0] not in _SUBCOMMANDS and "." in args[0]:
                # Treat as implicit call: prepend "call" to args
                return super().resolve_command(ctx, ["call", *args])
            raise


rapi_app = typer.Typer(
    help="Config-driven REST API client.",
    cls=RapiGroup,
)

# Register explicit commands
rapi_app.command(name="list")(list_endpoints)
rapi_app.command(name="show")(show_endpoint)
# Keep "call" for explicit usage (shown in help)
rapi_app.command(name="call", hidden=False)(call)


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
