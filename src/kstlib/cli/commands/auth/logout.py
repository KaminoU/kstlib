"""Logout from an OAuth2/OIDC provider."""

from __future__ import annotations

import typer

from kstlib.cli.common import CommandResult, CommandStatus, console, render_result

from .common import PROVIDER_ARGUMENT, QUIET_OPTION, get_provider, resolve_provider_name


def logout(
    provider: str | None = PROVIDER_ARGUMENT,
    quiet: bool = QUIET_OPTION,
    revoke: bool = typer.Option(
        True,
        "--revoke/--no-revoke",
        help="Attempt to revoke token at the authorization server.",
    ),
) -> None:
    """Logout from an OAuth2/OIDC provider.

    Clears the stored token and optionally revokes it at the server.
    """
    provider_name = resolve_provider_name(provider)
    auth_provider = get_provider(provider_name)

    # Check if authenticated
    token = auth_provider.get_token(auto_refresh=False)
    if token is None:
        if quiet:
            console.print(f"[yellow]{provider_name}: not authenticated[/]")
        else:
            render_result(
                CommandResult(
                    status=CommandStatus.WARNING,
                    message=f"Not authenticated with {provider_name}.",
                )
            )
        return

    # Attempt revocation if requested
    revoked = False
    if revoke:
        if not quiet:
            console.print(f"[dim]Revoking token for {provider_name}...[/]")
        try:
            revoked = auth_provider.revoke(token)
        except Exception:  # pylint: disable=broad-exception-caught
            # Best-effort revocation
            if not quiet:
                console.print("[dim]Token revocation not supported or failed.[/]")

    # Clear token from storage
    auth_provider.clear_token()

    # Success message
    if revoked:
        message = f"Logged out from {provider_name} (token revoked)."
    else:
        message = f"Logged out from {provider_name} (token cleared locally)."

    if quiet:
        console.print(f"[green]{message}[/]")
    else:
        render_result(
            CommandResult(
                status=CommandStatus.OK,
                message=message,
            )
        )


__all__ = ["logout"]
