"""Show authentication status for a provider."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from rich.panel import Panel
from rich.table import Table

from kstlib.auth.config import get_status_config
from kstlib.cli.common import console

from .common import PROVIDER_ARGUMENT, QUIET_OPTION, get_provider, resolve_provider_name

if TYPE_CHECKING:
    from kstlib.auth.models import Token


@dataclass(frozen=True, slots=True)
class _DisplayContext:
    """Display context for status output."""

    provider_name: str
    status_text: str
    status_style: str
    threshold: int
    refresh_threshold: int
    use_local_tz: bool
    is_expired: bool


def _format_duration(seconds: int) -> str:
    """Format duration in human-readable form.

    Args:
        seconds: Duration in seconds (can be negative for past).

    Returns:
        Formatted duration string.
    """
    abs_seconds = abs(seconds)
    if abs_seconds > 3600:
        return f"{abs_seconds // 3600}h {(abs_seconds % 3600) // 60}m"
    if abs_seconds > 60:
        return f"{abs_seconds // 60}m {abs_seconds % 60}s"
    return f"{abs_seconds}s"


def _format_datetime(dt: datetime, *, use_local: bool) -> str:
    """Format datetime for display.

    Args:
        dt: Datetime to format (should be timezone-aware).
        use_local: If True, convert to local timezone.

    Returns:
        Formatted datetime string.
    """
    if use_local:
        local_dt = dt.astimezone()
        return local_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def _get_refresh_token_expiry(token: Token) -> datetime | None:
    """Extract refresh token expiry from token metadata.

    Args:
        token: Token object with potential refresh token info.

    Returns:
        Refresh token expiry datetime, or None if unknown.
    """
    metadata = token.metadata

    # Check for refresh_expires_at (absolute timestamp)
    if metadata.get("refresh_expires_at"):
        try:
            return datetime.fromisoformat(str(metadata["refresh_expires_at"]))
        except (ValueError, TypeError):
            pass

    # Check refresh_expires_in from token response (relative)
    if metadata.get("refresh_expires_in"):
        try:
            return token.issued_at + timedelta(seconds=int(metadata["refresh_expires_in"]))
        except (ValueError, TypeError):
            pass

    return None


def _determine_status(token: Token, threshold: int) -> tuple[str, str, bool]:
    """Determine token status text and style.

    Args:
        token: Token to check.
        threshold: Expiring soon threshold in seconds.

    Returns:
        Tuple of (status_text, status_style, is_expired).
    """
    expires_in = token.expires_in
    is_expired = token.is_expired

    if is_expired:
        return "[red]Expired[/]", "red", True
    if expires_in is not None and expires_in <= threshold:
        return "[yellow]Expiring soon[/]", "yellow", False
    return "[green]Valid[/]", "green", False


def _build_access_token_rows(table: Table, token: Token, ctx: _DisplayContext) -> None:
    """Add access token rows to the status table.

    Args:
        table: Rich table to add rows to.
        token: Token object.
        ctx: Display context.
    """
    table.add_row("Provider", f"[cyan]{ctx.provider_name}[/]")
    table.add_row("Status", ctx.status_text)
    table.add_row(
        "Token Type",
        token.token_type.value if hasattr(token.token_type, "value") else str(token.token_type),
    )

    if token.issued_at:
        table.add_row("Issued At", _format_datetime(token.issued_at, use_local=ctx.use_local_tz))

    if token.expires_at:
        table.add_row("Expires At", _format_datetime(token.expires_at, use_local=ctx.use_local_tz))

    expires_in = token.expires_in
    if expires_in is not None:
        if ctx.is_expired:
            table.add_row("Expired Since", f"[red]{_format_duration(expires_in)}[/]")
        else:
            table.add_row("Expires In", _format_duration(expires_in))

    if token.scope:
        table.add_row("Scopes", " ".join(token.scope))


def _build_refresh_token_panel(token: Token, ctx: _DisplayContext) -> Panel | None:
    """Build a separate panel for refresh token status.

    Args:
        token: Token object.
        ctx: Display context.

    Returns:
        Panel for refresh token, or None if no refresh token.
    """
    if not token.is_refreshable:
        return None

    table = Table(show_header=False, box=None)
    table.add_column("Field", style="dim")
    table.add_column("Value")

    refresh_expiry = _get_refresh_token_expiry(token)

    if not refresh_expiry:
        table.add_row("Status", "[green]Available[/]")
        table.add_row("Expires At", "[dim]Unknown[/]")
        return Panel(table, title="Refresh Token", style="green")

    now = datetime.now(timezone.utc)
    refresh_expires_in = int((refresh_expiry - now).total_seconds())

    if refresh_expires_in <= 0:
        status_text = "[red]Expired[/]"
        panel_style = "red"
    elif refresh_expires_in <= ctx.refresh_threshold:
        status_text = "[yellow]Expiring soon[/]"
        panel_style = "yellow"
    else:
        status_text = "[green]Valid[/]"
        panel_style = "green"

    table.add_row("Status", status_text)
    table.add_row("Expires At", _format_datetime(refresh_expiry, use_local=ctx.use_local_tz))

    if refresh_expires_in <= 0:
        table.add_row("Expired Since", f"[red]{_format_duration(refresh_expires_in)}[/]")
    else:
        table.add_row("Expires In", _format_duration(refresh_expires_in))

    return Panel(table, title="Refresh Token", style=panel_style)


def _show_not_authenticated(provider_name: str, quiet: bool) -> None:
    """Display not authenticated message.

    Args:
        provider_name: Provider name.
        quiet: Whether to use quiet mode.
    """
    if quiet:
        console.print(f"[yellow]{provider_name}: not authenticated[/]")
    else:
        console.print(
            Panel(
                f"Not authenticated with [cyan]{provider_name}[/].\n"
                f"Run [bold]kstlib auth login {provider_name}[/] to authenticate.",
                title="Auth Status",
                style="yellow",
            )
        )


def _show_quiet_status(provider_name: str, token: Token, status_text: str, is_expired: bool) -> None:
    """Display quiet mode status.

    Args:
        provider_name: Provider name.
        token: Token object.
        status_text: Formatted status text.
        is_expired: Whether token is expired.
    """
    expires_in = token.expires_in
    if expires_in is not None:
        duration = _format_duration(expires_in)
        if is_expired:
            console.print(f"{provider_name}: {status_text} (expired {duration} ago)")
        else:
            console.print(f"{provider_name}: {status_text} (expires in {duration})")
    else:
        console.print(f"{provider_name}: {status_text}")


def _show_verbose_status(token: Token, ctx: _DisplayContext) -> None:
    """Display verbose mode status.

    Args:
        token: Token object.
        ctx: Display context.
    """
    # Access token panel
    table = Table(show_header=False, box=None)
    table.add_column("Field", style="dim")
    table.add_column("Value")
    _build_access_token_rows(table, token, ctx)
    console.print(Panel(table, title="Access Token", style=ctx.status_style))

    # Refresh token panel (separate, with its own status color)
    refresh_panel = _build_refresh_token_panel(token, ctx)
    if refresh_panel:
        console.print(refresh_panel)


def status(
    provider: str | None = PROVIDER_ARGUMENT,
    quiet: bool = QUIET_OPTION,
) -> None:
    """Show authentication status for a provider."""
    provider_name = resolve_provider_name(provider)
    auth_provider = get_provider(provider_name)
    token = auth_provider.get_token(auto_refresh=False)

    if token is None:
        _show_not_authenticated(provider_name, quiet)
        return

    status_cfg = get_status_config()
    threshold = status_cfg["expiring_soon_threshold"]
    refresh_threshold = status_cfg["refresh_expiring_soon_threshold"]
    use_local_tz = status_cfg["display_timezone"] == "local"

    status_text, status_style, is_expired = _determine_status(token, threshold)

    if quiet:
        _show_quiet_status(provider_name, token, status_text, is_expired)
        return

    ctx = _DisplayContext(
        provider_name=provider_name,
        status_text=status_text,
        status_style=status_style,
        threshold=threshold,
        refresh_threshold=refresh_threshold,
        use_local_tz=use_local_tz,
        is_expired=is_expired,
    )
    _show_verbose_status(token, ctx)


__all__ = ["status"]
