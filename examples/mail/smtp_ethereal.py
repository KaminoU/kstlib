#!/usr/bin/env python3
"""Send test emails via Ethereal Email fake SMTP service.

Ethereal Email (https://ethereal.email) is a free fake SMTP service
for testing email sending without delivering to real mailboxes.

Setup:
    1. Go to https://ethereal.email and create a free account
    2. Copy your credentials (user/pass)
    3. Set environment variables:
       export ETHEREAL_USER="your-user@ethereal.email"
       export ETHEREAL_PASS="your-password"

Usage:
    python examples/mail/smtp_ethereal.py

After running, check your Ethereal inbox to see the captured email:
    https://ethereal.email/messages
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from kstlib.mail import MailBuilder
from kstlib.mail.transports.smtp import SMTPCredentials, SMTPSecurity, SMTPTransport

# Ethereal SMTP configuration
ETHEREAL_HOST = "smtp.ethereal.email"
ETHEREAL_PORT = 587


def get_ethereal_credentials() -> SMTPCredentials:
    """Load Ethereal credentials from environment variables.

    Raises:
        SystemExit: If credentials are not configured.
    """
    user = os.getenv("ETHEREAL_USER")
    password = os.getenv("ETHEREAL_PASS")

    if not user or not password:
        print("=" * 60)
        print("ERROR: Ethereal credentials not configured!")
        print("=" * 60)
        print()
        print("To use this example:")
        print("  1. Create a free account at https://ethereal.email")
        print("  2. Set environment variables:")
        print('     export ETHEREAL_USER="your-user@ethereal.email"')
        print('     export ETHEREAL_PASS="your-password"')
        print()
        sys.exit(1)

    return SMTPCredentials(username=user, password=password)


def create_ethereal_transport() -> SMTPTransport:
    """Create SMTP transport configured for Ethereal Email."""
    return SMTPTransport(
        host=ETHEREAL_HOST,
        port=ETHEREAL_PORT,
        credentials=get_ethereal_credentials(),
        security=SMTPSecurity(use_starttls=True),
        timeout=30.0,
    )


def send_plain_email() -> None:
    """Send a simple plain-text email via Ethereal."""
    print("-" * 60)
    print("Example 1: Plain text email")
    print("-" * 60)

    transport = create_ethereal_transport()
    credentials = get_ethereal_credentials()

    message = (
        MailBuilder(transport=transport)
        .sender(credentials.username)
        .to(credentials.username)  # Send to ourselves
        .subject("Test from kstlib - Plain Text")
        .message(
            "Hello from kstlib!\n\n"
            "This is a plain-text test email sent via Ethereal SMTP.\n\n"
            "Check your Ethereal inbox: https://ethereal.email/messages",
            content_type="plain",
        )
        .send()
    )

    print("Email sent successfully!")
    print(f"  From: {message['From']}")
    print(f"  To: {message['To']}")
    print(f"  Subject: {message['Subject']}")
    print()


def send_html_email() -> None:
    """Send an HTML email via Ethereal."""
    print("-" * 60)
    print("Example 2: HTML email")
    print("-" * 60)

    transport = create_ethereal_transport()
    credentials = get_ethereal_credentials()

    html_content = """
    <html>
    <body style="font-family: Arial, sans-serif; padding: 20px;">
        <h1 style="color: #333;">Hello from kstlib!</h1>
        <p>This is an <strong>HTML</strong> test email sent via Ethereal SMTP.</p>
        <ul>
            <li>Feature 1: Config-driven design</li>
            <li>Feature 2: Multiple transport backends</li>
            <li>Feature 3: Template support with Jinja2</li>
        </ul>
        <p style="color: #666; font-size: 12px;">
            Check your inbox: <a href="https://ethereal.email/messages">Ethereal Messages</a>
        </p>
    </body>
    </html>
    """

    message = (
        MailBuilder(transport=transport)
        .sender(credentials.username)
        .to(credentials.username)
        .subject("Test from kstlib - HTML")
        .message(html_content, content_type="html")
        .send()
    )

    print("HTML email sent successfully!")
    print(f"  Subject: {message['Subject']}")
    print()


def send_email_with_headers() -> None:
    """Send email with CC, BCC, and Reply-To headers."""
    print("-" * 60)
    print("Example 3: Email with extra headers")
    print("-" * 60)

    transport = create_ethereal_transport()
    credentials = get_ethereal_credentials()

    message = (
        MailBuilder(transport=transport)
        .sender(credentials.username)
        .to(credentials.username)
        .cc(credentials.username)  # CC to ourselves
        .reply_to("noreply@example.com")
        .subject("Test from kstlib - With Headers")
        .message(
            "This email demonstrates CC, BCC, and Reply-To headers.",
            content_type="plain",
        )
        .send()
    )

    print("Email with headers sent!")
    print(f"  Reply-To: {message['Reply-To']}")
    print(f"  Cc: {message['Cc']}")
    print()


def main() -> None:
    """Run all Ethereal SMTP examples."""
    print("=" * 60)
    print("ETHEREAL EMAIL SMTP EXAMPLES")
    print("=" * 60)
    print()
    print(f"SMTP Server: {ETHEREAL_HOST}:{ETHEREAL_PORT}")
    print()

    send_plain_email()
    send_html_email()
    send_email_with_headers()

    print("=" * 60)
    print("All examples completed!")
    print()
    print("View your emails at: https://ethereal.email/messages")
    print("=" * 60)


if __name__ == "__main__":  # pragma: no cover - manual example
    main()
