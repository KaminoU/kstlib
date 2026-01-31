"""CLI commands for REST API client (rapi)."""

from __future__ import annotations

import click
import typer
from typer.core import TyperGroup

from .call import call
from .list import list_endpoints
from .show import show_endpoint

# Known subcommands that should not be treated as endpoints
_SUBCOMMANDS = {"list", "call", "show", "--help", "-h", "help"}


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
    "call",
    "list_endpoints",
    "rapi_app",
    "register_cli",
    "show_endpoint",
]
