"""Show detailed information for a specific API endpoint."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Annotated

import typer
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from kstlib.cli.common import console
from kstlib.limits import HARD_MAX_DISPLAY_VALUE_LENGTH, HARD_MAX_ENDPOINT_REF_LENGTH
from kstlib.rapi import EndpointNotFoundError, load_rapi_config
from kstlib.rapi.config import _PATH_PARAM_PATTERN

if TYPE_CHECKING:
    from kstlib.rapi.config import ApiConfig, EndpointConfig

# Allowed characters for endpoint reference: alphanum + underscore + dot + hyphen
_ENDPOINT_REF_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]+$")


def _truncate(value: str, max_length: int = HARD_MAX_DISPLAY_VALUE_LENGTH) -> str:
    """Truncate a string and append ellipsis if too long."""
    if len(value) <= max_length:
        return value
    return value[: max_length - 3] + "..."


def _validate_endpoint_ref(endpoint_ref: str) -> None:
    """Validate endpoint reference for security (deep defense)."""
    if len(endpoint_ref) > HARD_MAX_ENDPOINT_REF_LENGTH:
        console.print(f"[red]Endpoint reference too long: {len(endpoint_ref)} > {HARD_MAX_ENDPOINT_REF_LENGTH}[/]")
        raise typer.Exit(code=1)

    if not _ENDPOINT_REF_PATTERN.match(endpoint_ref):
        console.print("[red]Endpoint reference contains invalid characters.[/]")
        console.print("[dim]Allowed: alphanumeric, underscore, dot, hyphen[/]")
        raise typer.Exit(code=1)


def _print_basic_info(api_config: ApiConfig, ep_config: EndpointConfig) -> None:
    """Print basic endpoint information table."""
    info_table = Table(show_header=False, box=None, padding=(0, 2))
    info_table.add_column("Label", style="dim")
    info_table.add_column("Value")

    info_table.add_row("Path:", f"[green]{escape(ep_config.path)}[/]")
    info_table.add_row("Method:", f"[yellow]{ep_config.method}[/]")
    info_table.add_row("API:", api_config.name)
    info_table.add_row("Base URL:", escape(api_config.base_url))

    console.print(info_table)
    console.print()


def _print_path_params(path_params: list[str]) -> None:
    """Print path parameters section."""
    console.print("[bold]Path Parameters:[/]")
    if path_params:
        for param in path_params:
            suffix = " [dim](positional)[/]" if param.isdigit() else ""
            console.print(f"  [cyan]{{{param}}}[/]{suffix}")
    else:
        console.print("  [dim](none)[/]")
    console.print()


def _print_query_params(ep_config: EndpointConfig) -> None:
    """Print default query parameters section."""
    console.print("[bold]Default Query Parameters:[/]")
    if ep_config.query:
        for key, value in ep_config.query.items():
            safe_value = escape(_truncate(str(value)))
            console.print(f"  [cyan]{escape(key)}[/] = {safe_value}")
    else:
        console.print("  [dim](none)[/]")
    console.print()


def _print_headers(api_config: ApiConfig, ep_config: EndpointConfig) -> None:
    """Print headers section."""
    console.print("[bold]Headers:[/]")
    service_headers = len(api_config.headers) if api_config.headers else 0
    ep_headers = len(ep_config.headers) if ep_config.headers else 0
    console.print(f"  Service: [dim]{service_headers} header(s)[/]")
    console.print(f"  Endpoint: [dim]{ep_headers} header(s)[/]")
    console.print()


def _print_auth(api_config: ApiConfig, ep_config: EndpointConfig) -> None:
    """Print authentication section."""
    console.print("[bold]Authentication:[/]")
    if api_config.auth_type:
        console.print("  Required: [yellow]Yes[/]")
        console.print(f"  Type: [cyan]{api_config.auth_type}[/]")
        if ep_config.auth is False:
            console.print("  [dim]Note: Auth disabled for this endpoint[/]")
    else:
        console.print("  Required: [green]No[/]")
    console.print()


def _print_body_template(ep_config: EndpointConfig) -> None:
    """Print body template section."""
    console.print("[bold]Body Template:[/]")
    if ep_config.body_template:
        body_str = json.dumps(ep_config.body_template, indent=2)
        safe_body = escape(_truncate(body_str))
        console.print(f"  {safe_body}")
    elif ep_config.method in ("POST", "PUT", "PATCH"):
        console.print("  [dim](none - provide via --body)[/]")
    else:
        console.print(f"  [dim](none - {ep_config.method} request)[/]")
    console.print()


def _print_examples(ep_config: EndpointConfig, path_params: list[str]) -> None:
    """Print usage examples section."""
    console.print("[bold]Examples:[/]")
    base_cmd = f"kstlib rapi {ep_config.full_ref}"

    # Build path params string (required in ALL examples)
    # Use escape() to prevent Rich from interpreting <param> as markup tags
    path_args = ""
    if path_params:
        named_args = " ".join(escape(f"<{p}>") for p in path_params if not p.isdigit())
        positional_args = " ".join(escape(f"<arg{p}>") for p in path_params if p.isdigit())
        path_args = " ".join(filter(None, [named_args, positional_args]))

    # Basic example with required path params
    if path_args:
        console.print(f"  [dim]{base_cmd} {path_args}[/]")
    else:
        console.print(f"  [dim]{base_cmd}[/]")

    # Example with query param (path params are REQUIRED, query is optional)
    if ep_config.query:
        first_key = escape(next(iter(ep_config.query)))
        if path_args:
            console.print(f"  [dim]{base_cmd} {path_args} {first_key}={escape('<value>')}[/]")
        else:
            console.print(f"  [dim]{base_cmd} {first_key}={escape('<value>')}[/]")

    # Example with body (path params are REQUIRED)
    if ep_config.method in ("POST", "PUT", "PATCH"):
        if path_args:
            console.print(f'  [dim]{base_cmd} {path_args} --body \'{{"key": "value"}}\'[/]')
        else:
            console.print(f'  [dim]{base_cmd} --body \'{{"key": "value"}}\'[/]')

    console.print()


def show_endpoint(
    endpoint_ref: Annotated[
        str,
        typer.Argument(help="Endpoint reference (api.endpoint or short form)."),
    ],
) -> None:
    """Show detailed information for an API endpoint.

    Displays full configuration including path parameters, query parameters,
    headers, authentication requirements, and usage examples.

    Examples:
        # Show endpoint details
        kstlib rapi show httpbin.get_ip

        # Short form (if unique)
        kstlib rapi show get_ip
    """
    _validate_endpoint_ref(endpoint_ref)

    try:
        config_manager = load_rapi_config()
    except Exception as e:  # pylint: disable=broad-exception-caught
        console.print(f"[red]Failed to load rapi config: {e}[/]")
        raise typer.Exit(code=1) from e

    try:
        api_config, ep_config = config_manager.resolve(endpoint_ref)
    except EndpointNotFoundError as e:
        console.print(f"[red]Endpoint not found: {endpoint_ref}[/]")
        console.print(f"[dim]Available APIs: {', '.join(e.searched_apis)}[/]")
        raise typer.Exit(code=1) from e

    path_params = _PATH_PARAM_PATTERN.findall(ep_config.path)

    console.print()
    console.print(Panel(f"[bold cyan]{ep_config.full_ref}[/]", expand=False))
    console.print()

    _print_basic_info(api_config, ep_config)
    _print_path_params(path_params)
    _print_query_params(ep_config)
    _print_headers(api_config, ep_config)
    _print_auth(api_config, ep_config)
    _print_body_template(ep_config)
    _print_examples(ep_config, path_params)


__all__ = ["show_endpoint"]
