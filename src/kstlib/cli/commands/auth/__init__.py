"""CLI commands for OAuth2/OIDC authentication."""

from __future__ import annotations

import typer

from .login import login
from .logout import logout
from .providers import providers
from .status import status
from .token import token
from .whoami import whoami

auth_app = typer.Typer(help="Manage OAuth2/OIDC authentication.")

# Register commands on the auth_app
auth_app.command()(login)
auth_app.command()(logout)
auth_app.command()(status)
auth_app.command()(token)
auth_app.command()(whoami)
auth_app.command()(providers)


def register_cli(app: typer.Typer) -> None:
    """Register the auth sub-commands on the root Typer app."""
    app.add_typer(auth_app, name="auth")


__all__ = [
    "auth_app",
    "login",
    "logout",
    "providers",
    "register_cli",
    "status",
    "token",
    "whoami",
]
