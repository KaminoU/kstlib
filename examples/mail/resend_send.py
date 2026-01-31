#!/usr/bin/env python3
"""Send emails via Resend.com API with SOPS-encrypted secrets.

Resend (https://resend.com) is a modern email API for developers.
The free tier includes 100 emails/day and 3,000 emails/month.

This example demonstrates auto-decryption of SOPS secrets via kstlib config loader.

Setup (Option A - SOPS encrypted config):
    1. Run from examples/mail/ directory (where kstlib.conf.yml is)
    2. Ensure your age key matches the recipient in mail.conf.sops.yml
       (check with: kstlib secrets doctor)
    3. Edit kstlib.conf.yml to set your test_email

Setup (Option B - Environment variables):
    export RESEND_API_KEY="re_your_api_key"
    export RESEND_TEST_EMAIL="you@example.com"

Usage:
    cd examples/mail
    python resend_send.py

Note:
    With sandbox domain, you can only send to your own email.
    Verify a custom domain to send to any recipient.
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

from kstlib.config import load_config
from kstlib.config.exceptions import ConfigFileNotFoundError
from kstlib.mail.transports import ResendTransport


def load_config_with_sops() -> tuple[str | None, str | None, str | None, str | None]:
    """Load config from kstlib.conf.yml with auto-decrypted SOPS secrets.

    Returns:
        Tuple of (api_key, email_from, email_from_name, test_email) or None values.
    """
    try:
        config = load_config()
        mail_config = getattr(config, "mail", None)
        if mail_config and hasattr(mail_config, "resend"):
            resend = mail_config.resend
            return (
                getattr(resend, "api_key", None),
                getattr(resend, "email_from", None),
                getattr(resend, "email_from_name", None),
                getattr(config, "test_email", None),
            )
    except ConfigFileNotFoundError:
        pass
    return None, None, None, None


def get_api_key() -> str:
    """Load Resend API key from config (SOPS) or environment variable.

    Raises:
        SystemExit: If API key is not configured.
    """
    # Try config first (SOPS auto-decrypt)
    api_key, _, _, _ = load_config_with_sops()

    # Fallback to environment variable
    if not api_key:
        api_key = os.getenv("RESEND_API_KEY")

    if not api_key:
        print("=" * 60)
        print("ERROR: Resend API key not configured!")
        print("=" * 60)
        print()
        print("Option A - Use SOPS encrypted config:")
        print("  1. cd examples/mail")
        print("  2. Ensure your age key can decrypt mail.conf.sops.yml")
        print("     (check with: kstlib secrets doctor)")
        print()
        print("Option B - Use environment variable:")
        print('  export RESEND_API_KEY="re_your_api_key"')
        print()
        sys.exit(1)

    return api_key


def get_test_email(cli_email: str | None = None) -> str:
    """Get the test recipient email address from CLI, config, or environment.

    Args:
        cli_email: Email passed via command line argument (highest priority).

    Raises:
        SystemExit: If email is not configured.
    """
    # CLI argument has highest priority
    if cli_email:
        return cli_email

    # Try config
    _, _, _, email = load_config_with_sops()

    # Fallback to environment variable
    if not email or email == "you@example.com":
        email = os.getenv("RESEND_TEST_EMAIL")

    if not email:
        print("=" * 60)
        print("ERROR: Test email not configured!")
        print("=" * 60)
        print()
        print("Option A - Pass as argument:")
        print("  python resend_send.py your-email@example.com")
        print()
        print("Option B - Edit kstlib.conf.yml:")
        print('  test_email: "your-email@example.com"')
        print()
        print("Option C - Use environment variable:")
        print('  export RESEND_TEST_EMAIL="you@example.com"')
        print()
        print("Note: With sandbox domain (onboarding@resend.dev),")
        print("      you can only send to your own verified email.")
        print()
        sys.exit(1)

    return email


def get_sender_info() -> tuple[str, str]:
    """Get sender email and name from config or defaults.

    Returns:
        Tuple of (email_from, email_from_name).
    """
    _, email_from, email_from_name, _ = load_config_with_sops()
    return (
        email_from or "onboarding@resend.dev",
        email_from_name or "kstlib",
    )


async def send_plain_email(transport: ResendTransport, recipient: str, sender: str) -> None:
    """Send a simple plain-text email via Resend."""
    print("-" * 60)
    print("Example 1: Plain text email")
    print("-" * 60)

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = "Test from kstlib - Plain Text"
    message.set_content(
        "Hello from kstlib!\n\n"
        "This is a plain-text test email sent via Resend API.\n\n"
        "Resend free tier: 100 emails/day, 3,000/month.\n\n"
        "This email was sent using SOPS-encrypted API key!"
    )

    await transport.send(message)

    print("Email sent successfully!")
    print(f"  From: {message['From']}")
    print(f"  To: {message['To']}")
    print(f"  Resend ID: {transport.last_response.id if transport.last_response else 'N/A'}")
    print()


async def send_html_email(transport: ResendTransport, recipient: str, sender: str) -> None:
    """Send an HTML email via Resend."""
    print("-" * 60)
    print("Example 2: HTML email")
    print("-" * 60)

    html_content = """
    <html>
    <body style="font-family: Arial, sans-serif; padding: 20px;">
        <h1 style="color: #333;">Hello from kstlib!</h1>
        <p>This is an <strong>HTML</strong> test email sent via Resend API.</p>
        <ul>
            <li>Async transport (httpx)</li>
            <li>Free tier: 100 emails/day</li>
            <li>Simple REST API</li>
        </ul>
        <p style="background: #e8f5e9; padding: 10px; border-radius: 4px;">
            <strong>SOPS Integration:</strong> The API key was auto-decrypted from
            <code>mail.conf.sops.yml</code> by kstlib config loader!
        </p>
        <p style="color: #666; font-size: 12px;">
            Powered by <a href="https://resend.com">Resend</a>
        </p>
    </body>
    </html>
    """

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = "Test from kstlib - HTML (SOPS encrypted)"
    message.set_content("Plain text fallback for email clients without HTML support.")
    message.add_alternative(html_content, subtype="html")

    await transport.send(message)

    print("HTML email sent successfully!")
    print(f"  Resend ID: {transport.last_response.id if transport.last_response else 'N/A'}")
    print()


async def send_email_with_headers(transport: ResendTransport, recipient: str, sender: str) -> None:
    """Send email with CC, BCC, and Reply-To headers."""
    print("-" * 60)
    print("Example 3: Email with extra headers")
    print("-" * 60)

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Reply-To"] = "noreply@example.com"
    message["Subject"] = "Test from kstlib - With Headers"
    message.set_content("This email demonstrates Reply-To header via Resend API.")

    await transport.send(message)

    print("Email with headers sent!")
    print(f"  Reply-To: {message['Reply-To']}")
    print(f"  Resend ID: {transport.last_response.id if transport.last_response else 'N/A'}")
    print()


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Send test emails via Resend API with SOPS-encrypted secrets.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python resend_send.py you@example.com
  python resend_send.py --email you@example.com
  python resend_send.py  # uses config or env var
        """,
    )
    parser.add_argument(
        "email",
        nargs="?",
        help="Recipient email address (overrides config and env var)",
    )
    parser.add_argument(
        "--email",
        "-e",
        dest="email_flag",
        help="Recipient email address (alternative to positional)",
    )
    return parser.parse_args()


async def main(cli_email: str | None = None) -> None:
    """Run all Resend examples."""
    print("=" * 60)
    print("RESEND API EXAMPLES (with SOPS auto-decrypt)")
    print("=" * 60)
    print()

    api_key = get_api_key()
    recipient = get_test_email(cli_email)
    email_from, email_from_name = get_sender_info()

    # Format sender as "Name <email>" if name is provided
    sender = f"{email_from_name} <{email_from}>" if email_from_name else email_from

    # Show config source
    config_api_key, _, _, _ = load_config_with_sops()
    if config_api_key:
        print("Config source: kstlib.conf.yml (SOPS auto-decrypted)")
    else:
        print("Config source: environment variables")
    print(f"Sender: {sender}")
    print(f"Recipient: {recipient}")
    print()

    transport = ResendTransport(api_key=api_key)

    await send_plain_email(transport, recipient, sender)
    await send_html_email(transport, recipient, sender)
    await send_email_with_headers(transport, recipient, sender)

    print("=" * 60)
    print("All examples completed!")
    print()
    print("Check your inbox for the test emails.")
    print("=" * 60)


if __name__ == "__main__":  # pragma: no cover - manual example
    args = parse_args()
    # Use flag if provided, else positional
    email = args.email_flag or args.email
    asyncio.run(main(email))
