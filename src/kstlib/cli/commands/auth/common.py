"""Shared utilities for auth CLI commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from kstlib.auth.config import get_default_provider_name, list_configured_providers
from kstlib.auth.errors import AuthError, ConfigurationError
from kstlib.cli.common import exit_error

if TYPE_CHECKING:
    from kstlib.auth.providers.base import AbstractAuthProvider

# Common CLI options
PROVIDER_ARGUMENT = typer.Argument(
    None,
    help="Provider name (uses default if not specified).",
    show_default=False,
)

QUIET_OPTION = typer.Option(
    False,
    "--quiet",
    "-q",
    help="Suppress verbose output.",
)

TIMEOUT_OPTION = typer.Option(
    120,
    "--timeout",
    "-t",
    help="Timeout in seconds for browser authentication.",
)


def resolve_provider_name(provider: str | None) -> str:
    """Resolve provider name from argument or default.

    Args:
        provider: Explicit provider name or None.

    Returns:
        Resolved provider name.

    Raises:
        typer.Exit: If no provider specified and no default configured.
    """
    if provider:
        return provider

    default = get_default_provider_name()
    if default:
        return default

    configured = list_configured_providers()
    if not configured:
        return exit_error(
            "No auth providers configured.\nConfigure providers in kstlib.conf.yml under 'auth.providers'."
        )

    if len(configured) == 1:
        return configured[0]

    return exit_error(
        f"Multiple providers configured: {', '.join(configured)}\n"
        "Specify a provider name or set 'auth.default_provider' in config."
    )


def get_provider(provider_name: str) -> AbstractAuthProvider:
    """Get a configured auth provider by name.

    Args:
        provider_name: Name of the provider.

    Returns:
        Configured provider instance.

    Raises:
        typer.Exit: If provider not found or misconfigured.
    """
    from kstlib.auth.config import get_provider_config

    provider_cfg = get_provider_config(provider_name)
    if provider_cfg is None:
        configured = list_configured_providers()
        if configured:
            exit_error(f"Provider '{provider_name}' not found.\nAvailable providers: {', '.join(configured)}")
        else:
            exit_error(f"Provider '{provider_name}' not found.\nNo providers configured in kstlib.conf.yml.")

    # Determine provider type and instantiate
    provider_type = provider_cfg.get("type", "oidc").lower()

    try:
        if provider_type in ("oidc", "openid", "openidconnect"):
            from kstlib.auth.providers.oidc import OIDCProvider

            return OIDCProvider.from_config(provider_name)

        if provider_type in ("oauth2", "oauth"):
            from kstlib.auth.providers.oauth2 import OAuth2Provider

            return OAuth2Provider.from_config(provider_name)

        exit_error(f"Unknown provider type '{provider_type}' for '{provider_name}'.")

    except ConfigurationError as e:
        exit_error(f"Configuration error for '{provider_name}': {e}")
    except AuthError as e:
        exit_error(f"Auth error for '{provider_name}': {e}")


__all__ = [
    "PROVIDER_ARGUMENT",
    "QUIET_OPTION",
    "TIMEOUT_OPTION",
    "get_provider",
    "resolve_provider_name",
]
