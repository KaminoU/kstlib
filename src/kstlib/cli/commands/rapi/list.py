"""List available API endpoints."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from kstlib.cli.common import console
from kstlib.rapi import load_rapi_config


def list_endpoints(
    api: Annotated[
        str | None,
        typer.Argument(help="Filter by API name (optional)."),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Show additional details (method, auth, headers).",
        ),
    ] = False,
) -> None:
    """List all configured API endpoints.

    Examples:
        # List all endpoints
        kstlib rapi list

        # List endpoints for specific API
        kstlib rapi list github

        # Verbose output with methods and auth
        kstlib rapi list -v
    """
    try:
        config_manager = load_rapi_config()
    except Exception as e:  # pylint: disable=broad-exception-caught
        console.print(f"[red]Failed to load rapi config: {e}[/]")
        raise typer.Exit(code=1) from e

    apis = config_manager.apis

    if not apis:
        console.print("[yellow]No APIs configured in kstlib.conf.yml[/]")
        console.print("[dim]Add APIs under 'rapi.api' section.[/]")
        raise typer.Exit(code=0)

    # Filter by API name if specified
    if api:
        if api not in apis:
            console.print(f"[red]API '{api}' not found.[/]")
            console.print(f"[dim]Available APIs: {', '.join(apis.keys())}[/]")
            raise typer.Exit(code=1)
        apis = {api: apis[api]}

    # Build table
    if verbose:
        table = Table(title="Available Endpoints", show_lines=True)
        table.add_column("Reference", style="cyan")
        table.add_column("Method", style="green")
        table.add_column("Path")
        table.add_column("Query", style="yellow")
    else:
        table = Table(title="Available Endpoints")
        table.add_column("Reference", style="cyan")
        table.add_column("Path")

    for api_name, api_config in sorted(apis.items()):
        for ep_name, ep_config in sorted(api_config.endpoints.items()):
            ref = f"{api_name}.{ep_name}"

            # Build path display with query param indicator
            path_display = f"[dim]{ep_config.path}[/]"
            if ep_config.query:
                path_display += f" [yellow]({len(ep_config.query)})[/]"

            if verbose:
                method = ep_config.method.upper()
                # Show query param keys or "-"
                query_info = ", ".join(ep_config.query.keys()) if ep_config.query else "-"

                table.add_row(ref, method, path_display, query_info)
            else:
                table.add_row(ref, path_display)

    console.print(table)

    # Summary
    total_apis = len(apis)
    total_endpoints = sum(len(api.endpoints) for api in apis.values())
    console.print(f"\n[dim]{total_endpoints} endpoints across {total_apis} API(s)[/]")


__all__ = ["list_endpoints"]
