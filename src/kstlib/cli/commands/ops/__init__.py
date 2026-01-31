"""CLI commands for session management (tmux/container)."""

from __future__ import annotations

import typer

from .attach import attach
from .list_sessions import list_sessions
from .logs import logs
from .start import start
from .status import status
from .stop import stop

ops_app = typer.Typer(help="Manage sessions (tmux/container).")

# Register commands on the ops_app
ops_app.command()(start)
ops_app.command()(stop)
ops_app.command()(attach)
ops_app.command()(status)
ops_app.command()(logs)
ops_app.command(name="list")(list_sessions)


def register_cli(app: typer.Typer) -> None:
    """Register the ops sub-commands on the root Typer app."""
    app.add_typer(ops_app, name="ops")


__all__ = [
    "attach",
    "list_sessions",
    "logs",
    "ops_app",
    "register_cli",
    "start",
    "status",
    "stop",
]
