#!/usr/bin/env python3
"""Demonstrate @mail.notify() decorator for job execution notifications.

The notify decorator automatically sends email notifications when a decorated
function completes (success or failure). Perfect for ETL pipelines, scheduled
jobs, or any long-running tasks.

This example uses Ethereal Email (https://ethereal.email) for safe testing.

Setup:
    1. Create a free account at https://ethereal.email
    2. Set environment variables:
       export ETHEREAL_USER="your-user@ethereal.email"
       export ETHEREAL_PASS="your-password"

Usage:
    python examples/mail/notify_decorator.py

Features demonstrated:
    - @mail.notify for sync functions
    - @mail.notify for async functions
    - on_error_only=True (alert only on failures)
    - include_return=True (include return value in email)
    - subject override for custom subjects
    - Error notifications with traceback
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
from pathlib import Path

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from kstlib.mail import MailBuilder
from kstlib.mail.transports.smtp import SMTPCredentials, SMTPSecurity, SMTPTransport


def get_ethereal_transport() -> SMTPTransport:
    """Create SMTP transport for Ethereal Email."""
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

    return SMTPTransport(
        host="smtp.ethereal.email",
        port=587,
        credentials=SMTPCredentials(username=user, password=password),
        security=SMTPSecurity(use_starttls=True),
        timeout=30.0,
    )


def example_basic_notify() -> None:
    """Basic @mail.notify usage - sends email on success or failure."""
    print("-" * 60)
    print("Example 1: Basic @mail.notify")
    print("-" * 60)

    transport = get_ethereal_transport()
    user = os.getenv("ETHEREAL_USER", "")

    mail = MailBuilder(transport=transport).sender(user).to(user).subject("ETL Pipeline")

    @mail.notify
    def extract_data() -> dict[str, int]:
        """Simulate data extraction."""
        print("  Extracting data...")
        return {"rows": 1000, "columns": 15}

    result = extract_data()
    print(f"  Function returned: {result}")
    print("  Notification email sent!")
    print()


def example_on_error_only() -> None:
    """on_error_only=True - only sends email when function fails."""
    print("-" * 60)
    print("Example 2: on_error_only=True")
    print("-" * 60)

    transport = get_ethereal_transport()
    user = os.getenv("ETHEREAL_USER", "")

    mail = MailBuilder(transport=transport).sender(user).to(user).subject("Silent Job")

    @mail.notify(on_error_only=True)
    def quiet_job() -> str:
        """This job succeeds silently - no email sent."""
        print("  Running quiet job...")
        return "success"

    result = quiet_job()
    print(f"  Function returned: {result}")
    print("  No email sent (success with on_error_only=True)")
    print()


def example_with_return_value() -> None:
    """include_return=True - includes return value in email body."""
    print("-" * 60)
    print("Example 3: include_return=True")
    print("-" * 60)

    transport = get_ethereal_transport()
    user = os.getenv("ETHEREAL_USER", "")

    mail = MailBuilder(transport=transport).sender(user).to(user).subject("Data Pipeline")

    @mail.notify(include_return=True)
    def transform_data() -> dict[str, int | float]:
        """Transform data and return statistics."""
        print("  Transforming data...")
        return {
            "input_rows": 1000,
            "output_rows": 950,
            "dropped": 50,
            "success_rate": 95.0,
        }

    result = transform_data()
    print(f"  Function returned: {result}")
    print("  Email includes return value in body!")
    print()


def example_subject_override() -> None:
    """Custom subject per decorated function."""
    print("-" * 60)
    print("Example 4: Subject override")
    print("-" * 60)

    transport = get_ethereal_transport()
    user = os.getenv("ETHEREAL_USER", "")

    mail = MailBuilder(transport=transport).sender(user).to(user).subject("Default Subject")

    @mail.notify(subject="Step 1 - Extract")
    def step1() -> str:
        print("  Running Step 1...")
        return "extracted"

    @mail.notify(subject="Step 2 - Transform")
    def step2() -> str:
        print("  Running Step 2...")
        return "transformed"

    @mail.notify(subject="Step 3 - Load")
    def step3() -> str:
        print("  Running Step 3...")
        return "loaded"

    step1()
    step2()
    step3()
    print("  Each step sent email with custom subject!")
    print()


def example_error_notification() -> None:
    """Error handling - sends email with traceback on failure."""
    print("-" * 60)
    print("Example 5: Error notification with traceback")
    print("-" * 60)

    transport = get_ethereal_transport()
    user = os.getenv("ETHEREAL_USER", "")

    mail = MailBuilder(transport=transport).sender(user).to(user).subject("Flaky Job")

    @mail.notify
    def flaky_operation() -> str:
        """Simulate a flaky operation that sometimes fails."""
        print("  Running flaky operation...")
        if random.random() < 0.8:  # 80% chance of failure for demo
            raise RuntimeError("Connection to database lost!")
        return "success"

    try:
        flaky_operation()
        print("  Operation succeeded!")
    except RuntimeError:
        print("  Operation failed - error notification sent with traceback!")
    print()


async def example_async_notify() -> None:
    """@mail.notify works with async functions too."""
    print("-" * 60)
    print("Example 6: Async function notification")
    print("-" * 60)

    transport = get_ethereal_transport()
    user = os.getenv("ETHEREAL_USER", "")

    mail = MailBuilder(transport=transport).sender(user).to(user).subject("Async Pipeline")

    @mail.notify(include_return=True)
    async def async_fetch() -> dict[str, int]:
        """Simulate async API fetch."""
        print("  Fetching data asynchronously...")
        await asyncio.sleep(0.1)  # Simulate network delay
        return {"records": 500, "pages": 5}

    result = await async_fetch()
    print(f"  Async function returned: {result}")
    print("  Notification email sent!")
    print()


def main() -> None:
    """Run all notify decorator examples."""
    print("=" * 60)
    print("@mail.notify() DECORATOR EXAMPLES")
    print("=" * 60)
    print()
    print("Using Ethereal Email for safe testing.")
    print("View sent emails at: https://ethereal.email/messages")
    print()

    example_basic_notify()
    example_on_error_only()
    example_with_return_value()
    example_subject_override()
    example_error_notification()
    asyncio.run(example_async_notify())

    print("=" * 60)
    print("All examples completed!")
    print()
    print("Check your Ethereal inbox: https://ethereal.email/messages")
    print("=" * 60)


if __name__ == "__main__":  # pragma: no cover - manual example
    main()
