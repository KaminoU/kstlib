#!/usr/bin/env python3
"""OAuth2 with Google using kstlib.auth - production-ready approach.

This example demonstrates the same OAuth2 flow as oauth2_manual_google.py,
but using kstlib.auth abstractions. Much cleaner code, with TRACE logging
available to see HTTP details when needed.

Compare with oauth2_manual_google.py to see:
    - Manual: ~400 lines, explicit HTTP calls, verbose output
    - kstlib: ~60 lines, clean API, structured logging

Setup:
    Same as oauth2_manual_google.py - credentials in SOPS config.

Usage:
    cd examples/auth
    python oauth2_google.py your-email@gmail.com

    # With TRACE logging to see HTTP details:
    python oauth2_google.py your-email@gmail.com --trace

Educational value:
    - See how kstlib.auth simplifies OAuth2
    - Use TRACE logging instead of print() debugging
    - Token storage handled automatically (SOPS)
"""

from __future__ import annotations

import argparse
import base64
import sys
import webbrowser
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import httpx

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from kstlib.auth import OAuth2Provider, ProviderNotFoundError
from kstlib.auth.callback import CallbackServer
from kstlib.logging import get_logger, init_logging
from kstlib.utils.http_trace import HTTPTraceLogger

log = get_logger(__name__)
http_tracer: HTTPTraceLogger | None = None


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="OAuth2 with Google using kstlib.auth",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python oauth2_google.py your-email@gmail.com
    python oauth2_google.py your-email@gmail.com --trace
        """,
    )
    parser.add_argument(
        "email",
        help="Your Gmail address (sender and recipient for test)",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Enable TRACE logging to see HTTP details",
    )
    return parser.parse_args()


def get_provider() -> OAuth2Provider:
    """Load Google OAuth2 provider from config."""
    try:
        return OAuth2Provider.from_config("google")
    except ProviderNotFoundError:
        log.error("Google OAuth provider not configured in kstlib.conf.yml")
        sys.exit(1)


def authenticate(provider: OAuth2Provider) -> str:
    """Authenticate and return access token.

    Handles:
        - Cached token (SOPS-encrypted)
        - Token refresh if expired
        - Full browser flow if needed
    """
    # Check for existing valid token
    token = provider.get_token()
    if token and not token.is_expired:
        log.info("Using cached token (still valid)")
        return token.access_token

    # Need to authenticate
    log.info("Starting OAuth2 flow...")

    # Extract port from redirect_uri
    from urllib.parse import urlparse

    redirect_uri = provider.config.redirect_uri
    parsed = urlparse(redirect_uri)
    port = parsed.port or 8400
    path = parsed.path or "/callback"

    with CallbackServer(port=port, path=path) as server:
        state = server.generate_state()
        auth_url, _ = provider.get_authorization_url(state=state)

        log.info("Opening browser for consent...")
        webbrowser.open(auth_url)

        log.info("Waiting for callback...")
        result = server.wait_for_callback(timeout=120)

        if not result.success or result.code is None:
            log.error("Authorization failed: %s", result.error_description)
            sys.exit(1)

        token = provider.exchange_code(code=result.code, state=state)
        log.info("Authentication successful!")

        return token.access_token


def send_test_email(access_token: str, sender: str, recipient: str) -> None:
    """Send a test email via Gmail API."""
    log.info("Sending test email via Gmail API...")

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = "Test from kstlib - OAuth2 with kstlib.auth"
    message.set_content(
        "Hello!\n\n"
        "This email was sent using kstlib.auth OAuth2 flow.\n\n"
        "Compare with oauth2_manual_google.py to see the difference:\n"
        "  - Manual: ~400 lines of explicit HTTP code\n"
        "  - kstlib: ~60 lines with clean abstractions\n\n"
        "Use --trace flag to see HTTP details via structured logging."
    )

    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    raw_message = raw_message.rstrip("=")

    # Use HTTP tracer if enabled
    event_hooks: dict[str, list[Any]] = {}
    if http_tracer:
        event_hooks = {
            "request": [http_tracer.on_request],
            "response": [http_tracer.on_response],
        }

    with httpx.Client(event_hooks=event_hooks) as client:
        response = client.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            json={"raw": raw_message},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )

    if response.status_code == 200:
        data = response.json()
        log.info("Email sent! Message ID: %s", data.get("id"))
    else:
        log.error("Gmail API failed: %s", response.text)
        sys.exit(1)


def main() -> None:
    """Run OAuth2 flow with kstlib.auth."""
    global http_tracer
    args = parse_args()

    # Configure logging (trace preset enables TRACE level)
    preset = "my_trace" if args.trace else "dev"
    init_logging(preset=preset)

    # Enable HTTP tracing if requested
    if args.trace:
        http_tracer = HTTPTraceLogger(log)

    log.info("OAuth2 with Google (kstlib.auth)")
    log.info("=" * 50)

    provider = get_provider()
    access_token = authenticate(provider)
    send_test_email(access_token, args.email, args.email)

    log.info("=" * 50)
    log.info("Done! Check your inbox.")


if __name__ == "__main__":
    main()
