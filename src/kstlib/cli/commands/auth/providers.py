"""List configured auth providers."""

from __future__ import annotations

import typer
from rich.table import Table

from kstlib.auth.config import (
    get_default_provider_name,
    get_provider_config,
    list_configured_providers,
)
from kstlib.cli.common import console


def providers(
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed provider configuration.",
    ),
) -> None:
    """List configured authentication providers."""
    configured = list_configured_providers()
    default = get_default_provider_name()

    if not configured:
        console.print("[yellow]No auth providers configured.[/]")
        console.print("Configure providers in kstlib.conf.yml under 'auth.providers'.")
        raise typer.Exit(0)

    table = Table(title="Configured Auth Providers")
    table.add_column("Provider", style="cyan")
    table.add_column("Type", style="green")
    if verbose:
        table.add_column("Issuer / Endpoints", style="dim")
    table.add_column("Default", style="yellow", justify="center")

    for name in configured:
        cfg = get_provider_config(name) or {}
        provider_type = cfg.get("type", "oidc").upper()
        is_default = "[bold]✓[/]" if name == default else ""

        if verbose:
            # Show issuer or authorization endpoint
            issuer = cfg.get("issuer", "")
            auth_endpoint = cfg.get("authorization_endpoint", cfg.get("authorize_url", ""))
            endpoint_info = issuer or auth_endpoint or "[dim]not configured[/]"
            table.add_row(name, provider_type, endpoint_info, is_default)
        else:
            table.add_row(name, provider_type, is_default)

    console.print(table)


__all__ = ["providers"]
