"""Show or copy the access token."""

from __future__ import annotations

import base64
import json
from typing import Any

import typer

from kstlib.cli.common import console, exit_error
from kstlib.utils.serialization import to_json

from .common import PROVIDER_ARGUMENT, get_provider, resolve_provider_name


def _decode_jwt(token_str: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Decode a JWT and return (header, payload) dicts.

    Returns None if token is not a valid JWT format.
    """
    parts = token_str.split(".")
    if len(parts) != 3:
        return None

    try:
        # Add padding if needed (base64url)
        def decode_part(part: str) -> dict[str, Any]:
            # Add padding
            padding = 4 - len(part) % 4
            if padding != 4:
                part += "=" * padding
            decoded = base64.urlsafe_b64decode(part)
            return json.loads(decoded)  # type: ignore[no-any-return]

        header = decode_part(parts[0])
        payload = decode_part(parts[1])
        return header, payload
    except Exception:  # pylint: disable=broad-exception-caught
        return None


def _format_decoded(
    header: dict[str, Any],
    payload: dict[str, Any],
    *,
    as_json: bool = False,
) -> str:
    """Format decoded JWT for display."""
    if as_json:
        return to_json({"header": header, "payload": payload})

    # YAML-like format (more readable)
    lines = ["[bold cyan]--- JWT Header ---[/]"]
    for key, value in header.items():
        lines.append(f"[dim]{key}:[/] {value}")

    lines.append("")
    lines.append("[bold cyan]--- JWT Payload ---[/]")
    for key, value in payload.items():
        # Special formatting for timestamps
        if key in ("exp", "iat", "auth_time", "nbf") and isinstance(value, int):
            from datetime import datetime, timezone

            dt = datetime.fromtimestamp(value, tz=timezone.utc)
            lines.append(f"[dim]{key}:[/] {value} [dim]({dt.isoformat()})[/]")
        elif isinstance(value, list):
            lines.append(f"[dim]{key}:[/] {', '.join(str(v) for v in value)}")
        else:
            lines.append(f"[dim]{key}:[/] {value}")

    return "\n".join(lines)


def token(
    provider: str | None = PROVIDER_ARGUMENT,
    copy: bool = typer.Option(
        False,
        "--copy",
        "-c",
        help="Copy token to clipboard instead of printing.",
    ),
    refresh: bool = typer.Option(
        False,
        "--refresh",
        "-r",
        help="Force refresh token before displaying.",
    ),
    show_refresh: bool = typer.Option(
        False,
        "--show-refresh",
        help="Show the refresh token instead of access token.",
    ),
    decode: bool = typer.Option(
        False,
        "--decode",
        "-d",
        help="Decode JWT and show header + payload (human-readable).",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output decoded JWT as JSON (requires --decode).",
    ),
    header: bool = typer.Option(
        False,
        "--header",
        "-H",
        help="Output as Authorization header value (access token only).",
    ),
) -> None:
    """Show or copy the current access token.

    By default, prints the raw access token. Use --header to get the
    full Authorization header value (e.g., 'Bearer <token>').

    Use --show-refresh to display the refresh token instead.

    Use --decode to view the JWT header and payload in a readable format.
    """
    provider_name = resolve_provider_name(provider)
    auth_provider = get_provider(provider_name)

    # Force refresh if requested
    if refresh:
        current_token = auth_provider.get_token(auto_refresh=False)
        if current_token is None:
            exit_error(f"Not authenticated with {provider_name}.\nRun 'kstlib auth login {provider_name}' first.")
        if not current_token.is_refreshable:
            exit_error("Token cannot be refreshed (no refresh_token).")
        try:
            current_token = auth_provider.refresh(current_token)
        except Exception as e:  # pylint: disable=broad-exception-caught
            exit_error(f"Token refresh failed: {e}")
    else:
        current_token = auth_provider.get_token(auto_refresh=True)

    if current_token is None:
        exit_error(f"Not authenticated with {provider_name}.\nRun 'kstlib auth login {provider_name}' first.")

    # Validate incompatible options
    if as_json and not decode:
        exit_error("--json requires --decode.")
    if decode and header:
        exit_error("--decode and --header cannot be used together.")
    if decode and copy:
        exit_error("--decode and --copy cannot be used together.")

    # Handle --show-refresh
    if show_refresh:
        if header:
            exit_error("--header cannot be used with --show-refresh (refresh tokens are not used in headers).")
        if not current_token.refresh_token:
            exit_error("No refresh token available for this session.")
        raw_token = current_token.refresh_token
    else:
        raw_token = current_token.access_token

    # Handle --decode
    if decode:
        decoded = _decode_jwt(raw_token)
        if decoded is None:
            exit_error("Token is not a valid JWT format.")
        jwt_header, jwt_payload = decoded
        output = _format_decoded(jwt_header, jwt_payload, as_json=as_json)
        if as_json:
            print(output)
        else:
            console.print(output)
        return

    # Format output for raw token
    if header:
        token_type = (
            current_token.token_type.value
            if hasattr(current_token.token_type, "value")
            else str(current_token.token_type)
        )
        output = f"{token_type} {raw_token}"
    else:
        output = raw_token

    if copy:
        try:
            import pyperclip  # type: ignore[import-untyped]

            pyperclip.copy(output)
            console.print(f"[green]Token copied to clipboard ({provider_name}).[/]")
        except ImportError:
            exit_error("Clipboard support requires pyperclip.\nInstall with: pip install pyperclip")
        except Exception as e:  # pylint: disable=broad-exception-caught
            exit_error(f"Failed to copy to clipboard: {e}")
    else:
        # Print raw token (no Rich formatting for easy piping)
        print(output)


__all__ = ["token"]
