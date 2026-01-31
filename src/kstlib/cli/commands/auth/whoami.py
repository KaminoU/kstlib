"""Show user info from OIDC userinfo endpoint."""

# pylint: disable=too-many-locals,too-many-branches
# Justification: OIDC userinfo renderer with 3 output modes (raw/quiet/verbose) and
# claim mapping for 12 standard OIDC claims. Variables are mostly display labels and
# formatted values - extracting helpers would fragment the linear rendering logic.

from __future__ import annotations

import typer
from rich.panel import Panel
from rich.table import Table

from kstlib.cli.common import console, exit_error
from kstlib.utils.formatting import format_timestamp
from kstlib.utils.serialization import to_json

from .common import PROVIDER_ARGUMENT, QUIET_OPTION, get_provider, resolve_provider_name


def whoami(
    provider: str | None = PROVIDER_ARGUMENT,
    quiet: bool = QUIET_OPTION,
    raw: bool = typer.Option(
        False,
        "--raw",
        help="Output raw JSON response.",
    ),
) -> None:
    """Show user info from the OIDC userinfo endpoint.

    Only works with OIDC providers that expose a userinfo endpoint.
    """
    provider_name = resolve_provider_name(provider)
    auth_provider = get_provider(provider_name)

    # Check if authenticated
    token = auth_provider.get_token(auto_refresh=True)
    if token is None:
        exit_error(f"Not authenticated with {provider_name}.\nRun 'kstlib auth login {provider_name}' first.")

    # Check if provider supports userinfo (OIDC)
    if not hasattr(auth_provider, "get_userinfo"):
        exit_error(
            f"Provider '{provider_name}' does not support userinfo.\nUserinfo is only available for OIDC providers."
        )

    try:
        userinfo = auth_provider.get_userinfo()
    except Exception as e:  # pylint: disable=broad-exception-caught
        exit_error(f"Failed to fetch userinfo: {e}")

    if raw:
        print(to_json(userinfo))
        return

    if quiet:
        # Show just the essential info
        name = userinfo.get("name") or userinfo.get("preferred_username") or userinfo.get("sub", "unknown")
        email = userinfo.get("email", "")
        if email:
            console.print(f"{name} <{email}>")
        else:
            console.print(name)
        return

    # Verbose output
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Field", style="dim")
    table.add_column("Value")

    # Standard OIDC claims in preferred order
    claim_labels = {
        "sub": "Subject",
        "name": "Name",
        "preferred_username": "Username",
        "email": "Email",
        "email_verified": "Email Verified",
        "given_name": "Given Name",
        "family_name": "Family Name",
        "nickname": "Nickname",
        "picture": "Picture",
        "locale": "Locale",
        "zoneinfo": "Timezone",
        "updated_at": "Updated At",
    }

    # Show known claims first
    for claim, label in claim_labels.items():
        if claim in userinfo:
            value = userinfo[claim]
            if isinstance(value, bool):
                value = "[green]Yes[/]" if value else "[red]No[/]"
            elif claim == "updated_at" and isinstance(value, int):
                value = format_timestamp(value)
            table.add_row(label, str(value))

    # Show any additional claims
    for claim, value in userinfo.items():
        if claim not in claim_labels:
            table.add_row(claim, str(value))

    console.print(Panel(table, title=f"User Info ({provider_name})", style="cyan"))


__all__ = ["whoami"]
