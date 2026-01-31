#!/usr/bin/env python3
"""Demonstrate SMTP TRACE-level logging for debugging.

This example shows the detailed SMTP session information available
when TRACE logging is enabled. Useful for debugging connection issues,
TLS negotiation, and authentication problems.

Setup:
    1. Go to https://ethereal.email and create a free account
    2. Copy your credentials (user/pass)
    3. Set environment variables:
       export ETHEREAL_USER="your-user@ethereal.email"
       export ETHEREAL_PASS="your-password"

Usage:
    python examples/mail/smtp_trace.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from kstlib.logging import init_logging
from kstlib.mail import MailBuilder
from kstlib.mail.transports.smtp import SMTPCredentials, SMTPSecurity, SMTPTransport

# Ethereal SMTP configuration
ETHEREAL_HOST = "smtp.ethereal.email"
ETHEREAL_PORT = 587


def get_ethereal_credentials() -> SMTPCredentials:
    """Load Ethereal credentials from environment variables."""
    user = os.getenv("ETHEREAL_USER")
    password = os.getenv("ETHEREAL_PASS")

    if not user or not password:
        print("=" * 70)
        print("ERROR: Ethereal credentials not configured!")
        print("=" * 70)
        print()
        print("To use this example:")
        print("  1. Create a free account at https://ethereal.email")
        print("  2. Set environment variables:")
        print('     export ETHEREAL_USER="your-user@ethereal.email"')
        print('     export ETHEREAL_PASS="your-password"')
        print()
        sys.exit(1)

    return SMTPCredentials(username=user, password=password)


def main() -> None:
    """Send email with TRACE logging enabled."""
    print("=" * 70)
    print("SMTP TRACE LOGGING DEMO")
    print("=" * 70)
    print()
    print("This example demonstrates the detailed SMTP session information")
    print("available when TRACE-level logging is enabled.")
    print()
    print(f"SMTP Server: {ETHEREAL_HOST}:{ETHEREAL_PORT}")
    print("-" * 70)
    print()

    # Enable TRACE level logging for detailed SMTP diagnostics
    # init_logging() configures all kstlib.* loggers to TRACE level
    log = init_logging(config={"console": {"level": "TRACE"}})

    log.info("TRACE logging enabled - SMTP session details will be shown")
    print()

    credentials = get_ethereal_credentials()

    transport = SMTPTransport(
        host=ETHEREAL_HOST,
        port=ETHEREAL_PORT,
        credentials=credentials,
        security=SMTPSecurity(use_starttls=True),
        timeout=30.0,
    )

    print("-" * 70)
    print("Sending email... watch for [SMTP] trace logs below:")
    print("-" * 70)
    print()

    message = (
        MailBuilder(transport=transport)
        .sender(credentials.username)
        .to(credentials.username)
        .subject("TRACE logging test from kstlib")
        .message(
            "This email was sent with TRACE-level logging enabled.\n\n"
            "Check the console output above for detailed SMTP session info:\n"
            "- EHLO exchange and server capabilities\n"
            "- STARTTLS negotiation (TLS version, cipher)\n"
            "- Authentication flow\n"
            "- Message envelope (MAIL FROM, RCPT TO)\n",
            content_type="plain",
        )
        .send()
    )

    print()
    print("-" * 70)
    print("Email sent successfully!")
    print("-" * 70)
    print(f"  From: {message['From']}")
    print(f"  To: {message['To']}")
    print(f"  Subject: {message['Subject']}")
    print()
    print("View your email at: https://ethereal.email/messages")
    print("=" * 70)


if __name__ == "__main__":  # pragma: no cover - manual example
    main()
