#!/usr/bin/env python3
"""Send emails via Gmail API using OAuth2 with SOPS-encrypted credentials.

This example demonstrates sending emails through the Gmail API using
OAuth2 authentication with credentials auto-decrypted from SOPS.

Setup:
    1. Run from examples/mail/ directory (where kstlib.conf.yml is)
    2. Ensure your age key can decrypt mail.conf.sops.yml
       (check with: kstlib secrets doctor)
    3. First run will open browser for OAuth consent

Configuration:
    The credentials are stored in mail.conf.sops.yml (encrypted) and
    included via kstlib.conf.yml. See mail.conf.yml for the structure.

Usage:
    cd examples/mail
    python gmail_send.py recipient@example.com

Note:
    - The sender address must match the authenticated Google account
    - First run requires browser-based OAuth consent
    - Token is cached for subsequent runs (see kstlib.auth token storage)
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

# Required OAuth2 scope for sending emails
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"


def get_gmail_provider() -> OAuth2Provider:
    """Load Google OAuth2 provider from configuration (SOPS auto-decrypted).

    Raises:
        SystemExit: If provider is not configured.
    """
    try:
        provider = OAuth2Provider.from_config("google")
    except ProviderNotFoundError:
        print("=" * 60)
        print("ERROR: Google OAuth provider not configured!")
        print("=" * 60)
        print()
        print("Run from examples/mail/ directory where kstlib.conf.yml is located.")
        print("The config should include mail.conf.sops.yml with Google credentials.")
        print()
        print("Check your setup with: kstlib secrets doctor")
        print()
        sys.exit(1)

    return provider


def get_recipient(cli_email: str | None = None) -> str:
    """Get the recipient email address from CLI, environment, or prompt.

    Args:
        cli_email: Email passed via command line argument (highest priority).
    """
    if cli_email:
        return cli_email

    recipient = os.getenv("GMAIL_TEST_RECIPIENT")

    if not recipient:
        print()
        print("Enter recipient email address:")
        recipient = input("> ").strip()

        if not recipient or "@" not in recipient:
            print("Invalid email address")
            sys.exit(1)

    return recipient


async def send_email(transport: GmailTransport, sender: str, recipient: str) -> None:
    """Send a test email via Gmail API."""
    print("-" * 60)
    print("Sending test email")
    print("-" * 60)

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = "Test from kstlib - Gmail API"
    message.set_content(
        "Hello from kstlib!\n\n"
        "This is a test email sent via the Gmail API using OAuth2.\n\n"
        "The kstlib.auth module handled the OAuth flow, and\n"
        "the kstlib.mail module sent this message.\n\n"
        "Cheers!"
    )

    await transport.send(message)

    print("Email sent successfully!")
    print(f"  From: {sender}")
    print(f"  To: {recipient}")
    if transport.last_response:
        print(f"  Message ID: {transport.last_response.id}")
        print(f"  Thread ID: {transport.last_response.thread_id}")
    print()


async def send_html_email(transport: GmailTransport, sender: str, recipient: str) -> None:
    """Send an HTML email via Gmail API."""
    print("-" * 60)
    print("Sending HTML email")
    print("-" * 60)

    html_content = """
    <html>
    <body style="font-family: Arial, sans-serif; padding: 20px;">
        <h1 style="color: #4285f4;">Hello from kstlib!</h1>
        <p>This is an <strong>HTML</strong> email sent via the Gmail API.</p>
        <ul>
            <li>OAuth2 authentication via kstlib.auth</li>
            <li>Email composition via kstlib.mail</li>
            <li>Gmail API transport (async)</li>
        </ul>
        <p style="color: #666; font-size: 12px;">
            Powered by <a href="https://github.com/KaminoU/kstlib">kstlib</a>
        </p>
    </body>
    </html>
    """

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = "Test from kstlib - HTML Email"
    message.set_content("Plain text fallback for clients without HTML support.")
    message.add_alternative(html_content, subtype="html")

    await transport.send(message)

    print("HTML email sent successfully!")
    if transport.last_response:
        print(f"  Message ID: {transport.last_response.id}")
    print()


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Send test emails via Gmail API with SOPS-encrypted credentials.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python gmail_send.py recipient@example.com
  python gmail_send.py --email recipient@example.com
  python gmail_send.py  # prompts for recipient
        """,
    )
    parser.add_argument(
        "email",
        nargs="?",
        help="Recipient email address",
    )
    parser.add_argument(
        "--email",
        "-e",
        dest="email_flag",
        help="Recipient email address (alternative to positional)",
    )
    return parser.parse_args()


def authenticate_with_google(provider: OAuth2Provider) -> Token:
    """Run OAuth2 authorization code flow with Google.

    Opens browser for user consent, waits for callback, exchanges code for token.

    Args:
        provider: Configured OAuth2Provider for Google.

    Returns:
        Token object with access_token.

    Raises:
        SystemExit: If authentication fails.
    """
    from urllib.parse import urlparse

    # Check for existing valid token
    existing_token = provider.get_token()
    if existing_token and not existing_token.is_expired:
        print("Using cached token (still valid)")
        return existing_token

    # Extract port from redirect_uri (normalized to string in build_provider_config)
    redirect_uri = provider.config.redirect_uri
    parsed = urlparse(redirect_uri)
    port = parsed.port or 8400
    path = parsed.path or "/callback"

    # Start callback server
    with CallbackServer(port=port, path=path) as server:
        # Generate state and auth URL
        state = server.generate_state()
        auth_url, _ = provider.get_authorization_url(state=state)

        print("Opening browser for Google OAuth consent...")
        print(f"Callback server listening on: {server.redirect_uri}")
        print()

        # Open browser
        webbrowser.open(auth_url)

        # Wait for callback
        print("Waiting for authorization (browser will redirect back)...")
        try:
            result = server.wait_for_callback(timeout=120)
        except Exception as e:
            print(f"ERROR: Authorization failed: {e}")
            sys.exit(1)

        if not result.success or result.code is None:
            print(f"ERROR: Authorization denied: {result.error_description}")
            sys.exit(1)

        # Exchange code for token
        print("Exchanging authorization code for token...")
        try:
            token = provider.exchange_code(code=result.code, state=state)
        except Exception as e:
            print(f"ERROR: Token exchange failed: {e}")
            sys.exit(1)

        print("Authentication successful!")
        return token


async def main(cli_email: str | None = None) -> None:
    """Run Gmail send examples."""
    print("=" * 60)
    print("GMAIL API EXAMPLES (with SOPS auto-decrypt)")
    print("=" * 60)
    print()

    # Get OAuth provider (credentials auto-decrypted from SOPS)
    provider = get_gmail_provider()
    print("Config source: kstlib.conf.yml (SOPS auto-decrypted)")

    # Check scopes include gmail.send
    config = provider.config
    if GMAIL_SEND_SCOPE not in config.scopes:
        print(f"WARNING: Scope '{GMAIL_SEND_SCOPE}' not in provider config.")
        print("Email sending may fail.")
    print()

    # Authenticate (opens browser on first run)
    print("Authenticating with Google...")
    print("(Browser may open for OAuth consent on first run)")
    print()

    token = authenticate_with_google(provider)

    # Get sender email
    # The sender must be the authenticated user's email
    sender = os.getenv("GMAIL_SENDER")
    if not sender:
        print("Enter your Gmail address (sender):")
        sender = input("> ").strip()

    print(f"Sender: {sender}")
    print()

    # Get recipient
    recipient = get_recipient(cli_email)
    print(f"Recipient: {recipient}")
    print()

    # Create transport with the Token object
    transport = GmailTransport(token=token)

    # Send emails
    await send_email(transport, sender, recipient)
    await send_html_email(transport, sender, recipient)

    print("=" * 60)
    print("All examples completed!")
    print("=" * 60)


if __name__ == "__main__":  # pragma: no cover - manual example
    args = parse_args()
    email = args.email_flag or args.email
    asyncio.run(main(email))
