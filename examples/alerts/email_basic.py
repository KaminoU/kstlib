#!/usr/bin/env python3
"""Basic email alert example.

This example demonstrates sending alerts via email using different
transport backends (SMTP, Gmail, Resend).

Prerequisites:
    - For SMTP: Access to an SMTP server
    - For Gmail: OAuth2 token from kstlib.auth
    - For Resend: API key from resend.com

Usage:
    # SMTP example (using Ethereal for testing)
    python examples/alerts/email_basic.py --smtp

    # Gmail OAuth2 example (requires kstlib auth login)
    python examples/alerts/email_basic.py --gmail

    # Resend API example
    export RESEND_API_KEY="re_xxx"
    python examples/alerts/email_basic.py --resend
"""

from __future__ import annotations

import argparse
import asyncio
import os


async def main_smtp() -> None:
    """Send alerts via SMTP (Ethereal test server)."""
    from kstlib.alerts import AlertLevel, AlertMessage
    from kstlib.alerts.channels import EmailChannel
    from kstlib.mail.transports import SMTPCredentials, SMTPSecurity, SMTPTransport

    # Use Ethereal for testing: https://ethereal.email/
    # Create a test account and use the credentials
    smtp_host = os.environ.get("SMTP_HOST", "smtp.ethereal.email")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")

    if not smtp_user:
        print("Note: No SMTP credentials set. Get test credentials from https://ethereal.email/")
        print("Set SMTP_USER and SMTP_PASS environment variables")
        return

    credentials = SMTPCredentials(username=smtp_user, password=smtp_pass)
    security = SMTPSecurity(use_starttls=True)

    transport = SMTPTransport(
        host=smtp_host,
        port=smtp_port,
        credentials=credentials,
        security=security,
    )

    channel = EmailChannel(
        transport=transport,
        sender=smtp_user,
        recipients=[smtp_user],  # Send to self for testing
        subject_prefix="[TEST ALERT]",
    )

    alert = AlertMessage(
        title="SMTP Test Alert",
        body="This is a test alert sent via SMTP transport.",
        level=AlertLevel.INFO,
    )

    print(f"Sending alert via SMTP to {smtp_host}...")
    result = await channel.send(alert)

    if result.success:
        print("  OK - Check your Ethereal inbox")
    else:
        print(f"  FAILED: {result.error}")


async def main_gmail() -> None:
    """Send alerts via Gmail OAuth2."""
    from kstlib.alerts import AlertLevel, AlertMessage
    from kstlib.alerts.channels import EmailChannel

    # Gmail OAuth2 requires a Token from kstlib.auth
    sender = os.environ.get("GMAIL_SENDER", "")
    recipient = os.environ.get("ALERT_RECIPIENT", sender)

    if not sender:
        print("Error: GMAIL_SENDER environment variable not set")
        return

    try:
        from kstlib.auth import get_token_storage_from_config
        from kstlib.mail.transports import GmailTransport

        # Load token from kstlib.auth storage
        storage = get_token_storage_from_config(provider_name="google")
        token = storage.load("google")

        if not token or not token.access_token:
            print("Error: No valid Gmail token found")
            print("Run 'kstlib auth login google' first to authenticate")
            return

        transport = GmailTransport(token=token)

    except Exception as e:
        print(f"Error loading Gmail credentials: {e}")
        print("Make sure kstlib.auth is configured for Google OAuth2")
        return

    channel = EmailChannel(
        transport=transport,
        sender=sender,
        recipients=[recipient],
        subject_prefix="[ALERT]",
    )

    alert = AlertMessage(
        title="Gmail Test Alert",
        body="This is a test alert sent via Gmail OAuth2 transport.",
        level=AlertLevel.WARNING,
    )

    print(f"Sending alert via Gmail to {recipient}...")
    result = await channel.send(alert)

    if result.success:
        print("  OK")
    else:
        print(f"  FAILED: {result.error}")


async def main_resend() -> None:
    """Send alerts via Resend API."""
    from kstlib.alerts import AlertLevel, AlertMessage
    from kstlib.alerts.channels import EmailChannel
    from kstlib.mail.transports import ResendTransport

    api_key = os.environ.get("RESEND_API_KEY", "")
    sender = os.environ.get("RESEND_SENDER", "alerts@yourdomain.com")
    recipient = os.environ.get("ALERT_RECIPIENT", "test@example.com")

    if not api_key:
        print("Error: RESEND_API_KEY environment variable not set")
        print("Get your API key from https://resend.com/")
        return

    transport = ResendTransport(api_key=api_key)

    channel = EmailChannel(
        transport=transport,
        sender=sender,
        recipients=[recipient],
        subject_prefix="[ALERT]",
    )

    alert = AlertMessage(
        title="Resend API Test",
        body="This is a test alert sent via Resend API.",
        level=AlertLevel.CRITICAL,
    )

    print(f"Sending alert via Resend to {recipient}...")
    result = await channel.send(alert)

    if result.success:
        print("  OK")
    else:
        print(f"  FAILED: {result.error}")


def main() -> None:
    """Parse arguments and run example."""
    parser = argparse.ArgumentParser(description="Email alert example")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--smtp", action="store_true", help="Use SMTP transport")
    group.add_argument("--gmail", action="store_true", help="Use Gmail OAuth2 transport")
    group.add_argument("--resend", action="store_true", help="Use Resend API transport")
    args = parser.parse_args()

    if args.smtp:
        asyncio.run(main_smtp())
    elif args.gmail:
        asyncio.run(main_gmail())
    elif args.resend:
        asyncio.run(main_resend())


if __name__ == "__main__":
    main()
