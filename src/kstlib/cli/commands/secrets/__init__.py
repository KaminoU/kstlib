"""CLI commands for secrets management."""

from __future__ import annotations

import typer

from .decrypt import decrypt
from .doctor import doctor, init
from .encrypt import encrypt
from .shred import shred

secrets_app = typer.Typer(help="Manage encrypted secrets and diagnostics.")

# Register commands on the secrets_app
secrets_app.command()(doctor)
secrets_app.command()(init)
secrets_app.command()(encrypt)
secrets_app.command()(decrypt)
secrets_app.command()(shred)


def register_cli(app: typer.Typer) -> None:
    """Register the secrets sub-commands on the root Typer app."""
    app.add_typer(secrets_app, name="secrets")


__all__ = [
    "decrypt",
    "doctor",
    "encrypt",
    "init",
    "register_cli",
    "secrets_app",
    "shred",
]
