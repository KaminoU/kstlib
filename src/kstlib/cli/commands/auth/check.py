"""Validate JWT tokens with cryptographic proof."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any

import typer
from rich.panel import Panel
from rich.table import Table

from kstlib.auth.check import TokenChecker, TokenCheckReport
from kstlib.cli.common import console, exit_error

from .common import PROVIDER_ARGUMENT, get_provider, resolve_provider_name

# ─────────────────────────────────────────────────────────────────────────────
# Rendering
# ─────────────────────────────────────────────────────────────────────────────


def _render_normal(report: TokenCheckReport) -> None:
    """Render compact summary with step results.

    Args:
        report: Completed token validation report.
    """
    style = "green" if report.valid else "red"
    title = "Token VALID" if report.valid else "Token INVALID"

    table = _build_summary_table(report)
    console.print(Panel(table, title=title, style=style))

    # Steps
    console.print()
    for step in report.steps:
        icon = "[green]\u2713[/]" if step.passed else "[red]\u2717[/]"
        console.print(f"  {icon} {step.name}: {step.message}")

    if report.error:
        console.print(f"\n[red]Error:[/] {report.error}")

    if report.x509_info:
        _render_x509_panel(report.x509_info)

    if report.valid and report.discovery_url:
        _render_verification_instructions(report)


def _render_verbose(report: TokenCheckReport) -> None:
    """Render full details including JWT header/payload and PEM key.

    Args:
        report: Completed token validation report.
    """
    _render_normal(report)
    console.print()

    if report.header:
        console.print(Panel(_format_json(report.header), title="JWT Header", style="cyan"))

    if report.payload:
        formatted = _format_payload_timestamps(report.payload)
        console.print(Panel(_format_json(formatted), title="JWT Payload", style="cyan"))

    if report.discovery_data:
        console.print(Panel(_format_json(report.discovery_data), title="Discovery Document", style="cyan"))

    if report.public_key_pem:
        key_title = f"Public Key (SHA256:{report.key_fingerprint or 'unknown'})"
        console.print(Panel(report.public_key_pem.strip(), title=key_title, style="cyan"))

    for step in report.steps:
        if step.details:
            step_style = "green" if step.passed else "red"
            console.print(Panel(_format_json(step.details), title=f"Step: {step.name}", style=step_style))


def _render_json(report: TokenCheckReport) -> None:
    """Render report as JSON to stdout for automation.

    Args:
        report: Completed token validation report.
    """
    sys.stdout.write(json.dumps(report.to_dict(), indent=2, default=str) + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# Rendering helpers
# ─────────────────────────────────────────────────────────────────────────────


def _build_summary_table(report: TokenCheckReport) -> Table:
    """Build the summary table with key fields.

    Args:
        report: Token validation report.

    Returns:
        Rich Table with summary rows.
    """
    table = Table(show_header=False, box=None)
    table.add_column("Field", style="dim")
    table.add_column("Value")

    table.add_row("Token Type", report.token_type)
    table.add_row("Algorithm", report.signature_algorithm or "[dim]unknown[/]")

    # Key metadata
    if report.key_type and report.key_size_bits:
        table.add_row("Key Type", f"{report.key_type} {report.key_size_bits}-bit")
    elif report.key_type:
        table.add_row("Key Type", report.key_type)
    if report.key_id:
        table.add_row("Key ID (kid)", report.key_id)
    if report.key_fingerprint:
        table.add_row("Key Fingerprint", f"SHA256:{report.key_fingerprint[:32]}...")

    _add_claims_rows(table, report.payload)
    _add_expiry_row(table, report.payload)

    return table


def _add_claims_rows(table: Table, payload: dict[str, Any]) -> None:
    """Add issuer/audience/subject rows to table.

    Args:
        table: Rich table to add rows to.
        payload: JWT payload dict.
    """
    if payload.get("iss"):
        table.add_row("Issuer", str(payload["iss"]))
    aud = payload.get("aud")
    if aud:
        table.add_row("Audience", ", ".join(aud) if isinstance(aud, list) else str(aud))
    if payload.get("sub"):
        table.add_row("Subject", str(payload["sub"]))


def _add_expiry_row(table: Table, payload: dict[str, Any]) -> None:
    """Add expiration row to table.

    Args:
        table: Rich table to add row to.
        payload: JWT payload dict.
    """
    exp = payload.get("exp")
    if exp is None:
        return

    exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc)
    now = datetime.now(timezone.utc)
    if exp_dt > now:
        delta = int((exp_dt - now).total_seconds())
        table.add_row("Expires", f"{_format_duration(delta)} remaining")
    else:
        delta = int((now - exp_dt).total_seconds())
        table.add_row("Expires", f"[red]Expired {_format_duration(delta)} ago[/]")


def _render_verification_instructions(report: TokenCheckReport) -> None:
    """Render third-party verification instructions panel.

    Args:
        report: Token validation report.
    """
    console.print()
    console.print(
        Panel(
            "[dim]Third parties can independently verify this token:\n"
            f"1. Fetch discovery: GET {report.discovery_url}\n"
            f"2. Fetch JWKS: GET {report.jwks_uri}\n"
            f"3. Verify signature with kid={report.key_id!r}, alg={report.signature_algorithm}\n"
            "4. Check claims: iss, aud, exp[/]",
            title="Verification Instructions",
            style="dim",
        )
    )


def _render_x509_panel(x509_info: dict[str, Any]) -> None:
    """Render X.509 certificate info panel.

    Args:
        x509_info: Dictionary with certificate details from x5c parsing.
    """
    table = Table(show_header=False, box=None)
    table.add_column("Field", style="dim")
    table.add_column("Value")

    if x509_info.get("subject_cn"):
        table.add_row("Subject (CN)", x509_info["subject_cn"])
    if x509_info.get("issuer_cn"):
        table.add_row("Issuer (CN)", x509_info["issuer_cn"])
    if x509_info.get("serial_number"):
        table.add_row("Serial", x509_info["serial_number"])
    if x509_info.get("not_before"):
        table.add_row("Not Before", x509_info["not_before"])
    if x509_info.get("not_after"):
        table.add_row("Not After", x509_info["not_after"])

    console.print()
    console.print(Panel(table, title="X.509 Certificate (from JWKS x5c)", style="cyan"))


def _format_payload_timestamps(payload: dict[str, Any]) -> dict[str, Any]:
    """Format timestamps in payload for human readability.

    Args:
        payload: JWT payload dict.

    Returns:
        Copy with formatted timestamp values.
    """
    formatted = dict(payload)
    for key in ("exp", "iat", "nbf", "auth_time"):
        if key in formatted and isinstance(formatted[key], int):
            dt = datetime.fromtimestamp(formatted[key], tz=timezone.utc)
            formatted[key] = f"{formatted[key]} ({dt.isoformat()})"
    return formatted


def _format_json(data: Any) -> str:
    """Format data as indented JSON string.

    Args:
        data: Data to format.

    Returns:
        Formatted JSON string.
    """
    return json.dumps(data, indent=2, default=str)


def _format_duration(seconds: int) -> str:
    """Format duration in human-readable form.

    Args:
        seconds: Duration in seconds.

    Returns:
        Formatted duration string.
    """
    if seconds > 3600:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    if seconds > 60:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds}s"


# ─────────────────────────────────────────────────────────────────────────────
# CLI command
# ─────────────────────────────────────────────────────────────────────────────


def check(
    provider: str | None = PROVIDER_ARGUMENT,
    token_str: str | None = typer.Option(
        None,
        "--token",
        help="JWT string to validate (default: cached id_token).",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show full JWT header, payload, PEM key, and step details.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output as JSON for automation.",
    ),
    access_token: bool = typer.Option(
        False,
        "--access-token",
        help="Validate the access token instead of the id_token.",
    ),
) -> None:
    """Validate a JWT token with cryptographic proof.

    Performs full 6-step validation: decode structure, issuer discovery,
    JWKS fetch, public key extraction, signature verification, and
    claims validation. Works with any RSA-signed JWT whose issuer
    exposes an OpenID Connect discovery endpoint.

    Exit codes: 0 (valid), 1 (invalid), 2 (system error).
    """
    jwt_str, token_label, auth_provider = _resolve_token_source(
        provider,
        token_str,
        access_token,
    )

    import httpx

    http_client = httpx.Client()

    try:
        expected_issuer, expected_audience = _resolve_expectations(auth_provider, token_str)

        checker = TokenChecker(http_client, expected_issuer=expected_issuer, expected_audience=expected_audience)
        report = checker.check(jwt_str, token_type=token_label)

        _output_report(report, verbose=verbose, as_json=as_json)

        if not report.valid:
            raise typer.Exit(code=1)

    except typer.Exit:
        raise
    except Exception as exc:
        if as_json:
            sys.stdout.write(json.dumps({"valid": False, "error": str(exc)}) + "\n")
            sys.exit(2)
        else:
            exit_error(f"Unexpected error: {exc}")
    finally:
        http_client.close()


def _resolve_token_source(
    provider: str | None,
    token_str: str | None,
    access_token: bool,
) -> tuple[str, str, Any]:
    """Resolve JWT string and label from CLI arguments.

    Args:
        provider: Provider name argument.
        token_str: Explicit --token value.
        access_token: Whether --access-token was passed.

    Returns:
        Tuple of (jwt_string, token_label, auth_provider_or_None).
    """
    if token_str is not None:
        label = "access_token" if access_token else "id_token"
        return token_str, label, None

    provider_name = resolve_provider_name(provider)
    auth_provider = get_provider(provider_name)
    cached_token = auth_provider.get_token(auto_refresh=False)

    if cached_token is None:
        exit_error(
            f"Not authenticated with {provider_name}.\nRun 'kstlib auth login {provider_name}' first, or use --token."
        )

    if access_token:
        return cached_token.access_token, "access_token", auth_provider

    if cached_token.id_token:
        return cached_token.id_token, "id_token", auth_provider

    return cached_token.access_token, "access_token", auth_provider


def _resolve_expectations(
    auth_provider: Any,
    token_str: str | None,
) -> tuple[str | None, str | None]:
    """Extract expected issuer/audience from provider config.

    Args:
        auth_provider: Auth provider instance (or None for explicit token).
        token_str: Explicit token string (if set, no provider config used).

    Returns:
        Tuple of (expected_issuer, expected_audience).
    """
    if token_str is not None or auth_provider is None:
        return None, None

    try:
        config = auth_provider.config
        return getattr(config, "issuer", None), getattr(config, "client_id", None)
    except AttributeError:
        return None, None


def _output_report(
    report: TokenCheckReport,
    *,
    verbose: bool,
    as_json: bool,
) -> None:
    """Route report to the appropriate renderer.

    Args:
        report: Token validation report.
        verbose: Whether to show verbose output.
        as_json: Whether to output JSON.
    """
    if as_json:
        _render_json(report)
    elif verbose:
        _render_verbose(report)
    else:
        _render_normal(report)


__all__ = ["check"]
