"""List available API endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

import typer
from rich.table import Table

from kstlib.cli.common import console
from kstlib.rapi import load_rapi_config

if TYPE_CHECKING:
    from kstlib.rapi.config import ApiConfig, EndpointConfig


def _matches_filter(
    filter_terms: list[str],
    ref: str,
    method: str,
    path: str,
    description: str | None,
) -> bool:
    """Check if endpoint matches all filter terms (AND logic).

    Args:
        filter_terms: List of lowercase search terms.
        ref: Endpoint reference (e.g., "github.repos").
        method: HTTP method (e.g., "GET").
        path: Endpoint path.
        description: Optional endpoint description.

    Returns:
        True if all terms match any field.
    """
    searchable = f"{ref} {method} {path} {description or ''}".lower()
    return all(term in searchable for term in filter_terms)


def _build_query_body_display(
    ep_config: EndpointConfig,
    method: str,
) -> tuple[str, str]:
    """Build query and body column displays.

    Args:
        ep_config: Endpoint configuration.
        method: HTTP method.

    Returns:
        Tuple of (query_display, body_display).
    """
    query_display = f"[yellow]{len(ep_config.query)}[/]" if ep_config.query else "-"
    body_display = "-"
    if ep_config.body_template and method in ("POST", "PUT", "PATCH"):
        body_display = f"[green]{len(ep_config.body_template)}[/]"
    return query_display, body_display


def _build_compact_indicator(ep_config: EndpointConfig, method: str) -> str:
    """Build compact param indicator for non-verbose mode.

    Args:
        ep_config: Endpoint configuration.
        method: HTTP method.

    Returns:
        Formatted indicator string (e.g., " (4) (2)").
    """
    indicator = ""
    if ep_config.query:
        indicator += f" [yellow]({len(ep_config.query)})[/]"
    if ep_config.body_template and method in ("POST", "PUT", "PATCH"):
        indicator += f" [green]({len(ep_config.body_template)})[/]"
    return indicator


def _add_endpoint_row(
    table: Table,
    ep_config: EndpointConfig,
    api_name: str,
    verbose: bool,
    *,
    short_desc: bool = False,
) -> None:
    """Add a single endpoint row to the table.

    Args:
        table: Rich table to add row to.
        ep_config: Endpoint configuration.
        api_name: Parent API name.
        verbose: Whether to show verbose columns.
        short_desc: Whether to truncate description (verbose mode only).
    """
    ref = f"{api_name}.{ep_config.name}"
    method = ep_config.method.upper()
    path_display = f"[dim]{ep_config.path}[/]"

    if verbose:
        query_display, body_display = _build_query_body_display(ep_config, method)
        description = ep_config.description or ""
        desc_display = (description[:40] + "...") if short_desc and len(description) > 43 else description
        table.add_row(ref, method, path_display, query_display, body_display, desc_display)
    else:
        indicator = _build_compact_indicator(ep_config, method)
        table.add_row(ref, method, path_display + indicator)


def _create_table(verbose: bool) -> Table:
    """Create the endpoints table with appropriate columns.

    Args:
        verbose: Whether to include verbose columns.

    Returns:
        Configured Rich table.
    """
    table = Table(title="Available Endpoints", show_lines=False)
    table.add_column("Reference", style="cyan")
    table.add_column("Method", style="green", justify="center")
    table.add_column("Path")

    if verbose:
        table.add_column("Query", justify="center")
        table.add_column("Body", justify="center")
        table.add_column("Description", style="dim")

    return table


def _collect_matching_endpoints(
    apis: dict[str, ApiConfig],
    filter_terms: list[str],
) -> list[tuple[str, EndpointConfig]]:
    """Collect endpoints matching the filter.

    Args:
        apis: Dictionary of API configurations.
        filter_terms: List of lowercase filter terms.

    Returns:
        List of (api_name, endpoint_config) tuples.
    """
    results = []
    for api_name, api_config in sorted(apis.items()):
        for ep_name, ep_config in sorted(api_config.endpoints.items()):
            ref = f"{api_name}.{ep_name}"
            method = ep_config.method.upper()
            description = ep_config.description or ""

            if filter_terms and not _matches_filter(filter_terms, ref, method, ep_config.path, description):
                continue

            results.append((api_name, ep_config))
    return results


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
            help="Show additional details (method, description, query params).",
        ),
    ] = False,
    filter_str: Annotated[
        str | None,
        typer.Option(
            "--filter",
            "-f",
            help="Filter endpoints by keyword(s). Searches in ref, method, path, description.",
        ),
    ] = None,
    short_desc: Annotated[
        bool,
        typer.Option(
            "--short-desc",
            help="Truncate descriptions to 40 chars (verbose mode only).",
        ),
    ] = False,
) -> None:
    """List all configured API endpoints.

    Examples:
        # List all endpoints
        kstlib rapi list

        # List endpoints for specific API
        kstlib rapi list github

        # Filter by keyword (searches everywhere)
        kstlib rapi list --filter "delete"

        # Multiple keywords (AND logic)
        kstlib rapi list --filter "annotation GET"

        # Combine API filter with keyword filter
        kstlib rapi list annotations --filter "member"

        # Verbose output with method, description, query params
        kstlib rapi list -v

        # Show details for specific endpoint (use 'rapi show')
        kstlib rapi show annotations.create
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

    # Parse filter terms
    filter_terms = filter_str.lower().split() if filter_str else []

    # Collect matching endpoints
    matches = _collect_matching_endpoints(apis, filter_terms)

    if not matches:
        if filter_terms:
            console.print(f"[yellow]No endpoints matching '{filter_str}'[/]")
        else:
            console.print("[yellow]No endpoints found.[/]")
        raise typer.Exit(code=0)

    # Build and populate table
    table = _create_table(verbose)
    for api_name, ep_config in matches:
        _add_endpoint_row(table, ep_config, api_name, verbose, short_desc=short_desc)

    console.print(table)

    # Summary
    total_apis = len(apis)
    total_endpoints = sum(len(a.endpoints) for a in apis.values())
    if filter_terms:
        console.print(f"\n[dim]{len(matches)} matching / {total_endpoints} total endpoints[/]")
    else:
        console.print(f"\n[dim]{total_endpoints} endpoints across {total_apis} API(s)[/]")


__all__ = ["list_endpoints"]
