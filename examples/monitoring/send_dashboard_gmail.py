#!/usr/bin/env python3
"""Send a monitoring dashboard as an HTML email via Gmail API.

Combines kstlib.monitoring (HTML rendering) with kstlib.mail (Gmail transport)
to send a fully styled service dashboard by email.

Setup:
    1. Run from examples/monitoring/ directory (where kstlib.conf.yml is)
    2. Ensure your age key can decrypt ../mail/mail.conf.sops.yml
       (check with: kstlib secrets doctor)
    3. First run will open browser for OAuth consent

Usage::

    cd examples/monitoring
    python send_dashboard_gmail.py recipient@example.com
    python send_dashboard_gmail.py --sender me@gmail.com recipient@example.com

"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from email.message import EmailMessage
from pathlib import Path

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import webbrowser

from kstlib.auth import OAuth2Provider, ProviderNotFoundError, Token
from kstlib.auth.callback import CallbackServer
from kstlib.mail.transports import GmailTransport
from kstlib.monitoring import (
    MonitorImage,
    MonitorKV,
    MonitorList,
    MonitorMetric,
    MonitorTable,
    StatusCell,
    StatusLevel,
    render_template,
)

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"

# ---------------------------------------------------------------------------
# Dashboard template (email-optimized, inline CSS)
# ---------------------------------------------------------------------------

DASHBOARD_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Service Dashboard</title>
</head>
<body style="font-family:Consolas,Monaco,'Courier New',monospace;margin:20px;\
background:#1a1a2e;color:#e0e0e0;">

  <div style="display:flex;align-items:center;gap:16px;">
    {{ logo | render(inline_css=True) }}
    <h1 style="color:#16A085;margin:0;">Infrastructure Status</h1>
  </div>
  <p>Automated monitoring snapshot sent via kstlib.</p>

  <h2>Service Health</h2>
  {{ table | render(inline_css=True) }}

  <h2>Key Metrics</h2>
  <div style="display:flex;gap:32px;flex-wrap:wrap;">
    {{ uptime | render(inline_css=True) }}
    {{ pnl | render(inline_css=True) }}
    {{ latency | render(inline_css=True) }}
  </div>

  <h2>System Info</h2>
  {{ sysinfo | render(inline_css=True) }}

  <h2>Recent Events</h2>
  {{ events | render(inline_css=True) }}

  <hr style="border:none;border-top:1px solid #333;margin-top:32px;">
  <p style="color:#666;font-size:11px;">
    Sent by kstlib.monitoring + kstlib.mail (Gmail API / OAuth2)
  </p>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# Dashboard data (same as service_dashboard.py)
# ---------------------------------------------------------------------------


def _build_dashboard_context() -> dict[str, object]:
    """Build the full dashboard context with all monitoring widgets."""
    import random

    logo_path = Path(__file__).parent / "kst.png"
    logo = MonitorImage(path=logo_path, alt="kstlib", width=64, height=52)

    table = MonitorTable(headers=["Service", "Region", "Status", "Uptime"])
    services = [
        ("API Gateway", "eu-west-1", StatusLevel.OK, "99.98%"),
        ("WebSocket Feed", "eu-west-1", StatusLevel.OK, "99.95%"),
        ("PostgreSQL Primary", "eu-west-1", StatusLevel.WARNING, "99.80%"),
        ("Redis Cache", "eu-west-1", StatusLevel.OK, "100%"),
        ("Watchdog", "eu-west-1", StatusLevel.ERROR, "97.2%"),
    ]
    for name, region, level, uptime_val in services:
        label = {
            StatusLevel.OK: "UP",
            StatusLevel.WARNING: "DEGRADED",
            StatusLevel.ERROR: "DOWN",
            StatusLevel.CRITICAL: "FAILURE",
        }[level]
        table.add_row([name, region, StatusCell(label, level), uptime_val])

    uptime = MonitorMetric(99.95, label="Overall Uptime", level=StatusLevel.OK, unit="%")
    pnl = MonitorMetric(
        f"+{random.randint(800, 2500)}",
        label="Daily P&L",
        level=StatusLevel.OK,
        unit=" USDT",
    )
    latency = MonitorMetric(42, label="Avg Latency", level=StatusLevel.WARNING, unit=" ms")

    sysinfo = MonitorKV(
        items={
            "Host": "srv-prod-01.eu-west-1",
            "Python": "3.10.16",
            "kstlib": "1.55.2",
            "Uptime": "14d 6h 32m",
            "DB Pool": StatusCell("3/10 active", StatusLevel.OK),
        },
        title="Runtime",
    )

    events = MonitorList(
        items=[
            "14:32:01 - Watchdog restart triggered (timeout 30s exceeded)",
            "14:31:45 - PostgreSQL replica lag > 500ms, switching to WARNING",
            "14:30:00 - Heartbeat OK from all 4 services",
            "14:25:12 - Cache hit ratio: 94.7%",
            "14:20:00 - Daily P&L snapshot saved",
        ],
        ordered=True,
        title="Last 5 Events",
    )

    return {
        "logo": logo,
        "table": table,
        "uptime": uptime,
        "pnl": pnl,
        "latency": latency,
        "sysinfo": sysinfo,
        "events": events,
    }


# ---------------------------------------------------------------------------
# OAuth2 helpers (reused from gmail_send.py)
# ---------------------------------------------------------------------------


def _get_gmail_provider() -> OAuth2Provider:
    """Load Google OAuth2 provider from configuration (SOPS auto-decrypted).

    Raises:
        SystemExit: If provider is not configured.
    """
    try:
        return OAuth2Provider.from_config("google")
    except ProviderNotFoundError:
        print("=" * 60)
        print("ERROR: Google OAuth provider not configured!")
        print("=" * 60)
        print()
        print("Run from examples/monitoring/ directory where kstlib.conf.yml is.")
        print("The config includes ../mail/mail.conf.sops.yml with Google credentials.")
        print()
        print("Check your setup with: kstlib secrets doctor")
        sys.exit(1)


def _authenticate(provider: OAuth2Provider) -> Token:
    """Run OAuth2 authorization code flow with Google.

    Opens browser for user consent on first run, then caches the token.

    Args:
        provider: Configured OAuth2Provider for Google.

    Returns:
        Token object with access_token.

    Raises:
        SystemExit: If authentication fails.
    """
    from urllib.parse import urlparse

    existing_token = provider.get_token()
    if existing_token and not existing_token.is_expired:
        print("Using cached token (still valid)")
        return existing_token

    redirect_uri = provider.config.redirect_uri
    parsed = urlparse(redirect_uri)
    port = parsed.port or 8400
    path = parsed.path or "/callback"

    with CallbackServer(port=port, path=path) as server:
        state = server.generate_state()
        auth_url, _ = provider.get_authorization_url(state=state)

        print("Opening browser for Google OAuth consent...")
        print(f"Callback server listening on: {server.redirect_uri}")
        print()

        webbrowser.open(auth_url)

        print("Waiting for authorization (browser will redirect back)...")
        try:
            result = server.wait_for_callback(timeout=120)
        except Exception as e:
            print(f"ERROR: Authorization failed: {e}")
            sys.exit(1)

        if not result.success or result.code is None:
            print(f"ERROR: Authorization denied: {result.error_description}")
            sys.exit(1)

        print("Exchanging authorization code for token...")
        try:
            token = provider.exchange_code(code=result.code, state=state)
        except Exception as e:
            print(f"ERROR: Token exchange failed: {e}")
            sys.exit(1)

        print("Authentication successful!")
        return token


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Send a monitoring dashboard via Gmail API (OAuth2 + SOPS).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python send_dashboard_gmail.py recipient@example.com
  python send_dashboard_gmail.py --sender me@gmail.com recipient@example.com
  GMAIL_SENDER=me@gmail.com python send_dashboard_gmail.py user@example.com
""",
    )
    parser.add_argument("recipient", help="Recipient email address")
    parser.add_argument(
        "--sender",
        "-s",
        default=None,
        help="Sender Gmail address (or set GMAIL_SENDER env var)",
    )
    return parser.parse_args()


async def main() -> None:
    """Render the dashboard and send it as an HTML email via Gmail."""
    args = parse_args()

    sender = args.sender or os.getenv("GMAIL_SENDER")
    if not sender:
        print("Enter your Gmail address (sender):")
        sender = input("> ").strip()
        if not sender or "@" not in sender:
            print("Invalid email address")
            sys.exit(1)

    recipient: str = args.recipient

    print("=" * 60)
    print("MONITORING DASHBOARD - Gmail Send")
    print("=" * 60)
    print()

    # 1. Authenticate with Google
    provider = _get_gmail_provider()
    print("Config source: kstlib.conf.yml (SOPS auto-decrypted)")

    config = provider.config
    if GMAIL_SEND_SCOPE not in config.scopes:
        print(f"WARNING: Scope '{GMAIL_SEND_SCOPE}' not in provider config.")
        print("Email sending may fail.")
    print()

    print("Authenticating with Google...")
    token = _authenticate(provider)
    print()

    # 2. Render the dashboard HTML (inline CSS for email clients)
    print("Rendering dashboard (inline CSS for email)...")
    context = _build_dashboard_context()
    html = render_template(DASHBOARD_TEMPLATE, context, inline_css=True)
    print(f"  HTML size: {len(html):,} bytes")
    print()

    # 3. Build email message
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = "kstlib - Infrastructure Dashboard"
    message.set_content("This email contains an HTML dashboard.\nPlease view it in an HTML-capable email client.")
    message.add_alternative(html, subtype="html")

    # 4. Send via Gmail API
    print(f"Sending to {recipient}...")
    transport = GmailTransport(token=token)
    await transport.send(message)

    print("Email sent successfully!")
    print(f"  From: {sender}")
    print(f"  To: {recipient}")
    if transport.last_response:
        print(f"  Message ID: {transport.last_response.id}")
        print(f"  Thread ID: {transport.last_response.thread_id}")
    print()
    print("=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":  # pragma: no cover - manual example
    asyncio.run(main())
