#!/usr/bin/env python3
"""Multi-channel alert example with AlertManager.

This example demonstrates using AlertManager to send alerts to multiple
channels with level-based filtering and rate limiting.

Prerequisites:
    - Slack webhook URL
    - SMTP credentials (or Resend API key)

Usage:
    # Set environment variables
    export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/T.../B.../xxx"
    export SMTP_HOST="smtp.ethereal.email"
    export SMTP_USER="your@ethereal.email"
    export SMTP_PASS="yourpassword"

    # Run the example (env mode)
    python examples/alerts/multi_channel.py

    # Or with config file (requires kstlib.conf.yml with alerts section)
    cd examples/alerts
    python multi_channel.py --config

Config file (examples/alerts/kstlib.conf.yml):
    alerts:
      throttle:
        rate: 10
        per: 60

      channels:
        slack_ops:
          type: slack
          credentials: slack_webhook
          username: "kstlib-alerts"
          min_level: warning

    credentials:
      slack_webhook:
        type: sops
        path: "secrets/slack.sops.yaml"
        key_field: "sops_webhook_url"

Note:
    Run from examples/alerts/ directory for kstlib.conf.yml auto-discovery
    when using --config mode.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from typing import Any


async def main_env() -> None:
    """Send alerts using environment variables."""
    from kstlib.alerts import AlertLevel, AlertManager, AlertMessage, AlertThrottle
    from kstlib.alerts.channels import EmailChannel, SlackChannel
    from kstlib.mail.transports import SMTPCredentials, SMTPSecurity, SMTPTransport

    # Get configuration from environment
    slack_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    smtp_host = os.environ.get("SMTP_HOST", "smtp.ethereal.email")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")

    # Build alert manager
    manager = AlertManager()

    # Add Slack channel for WARNING and above
    if slack_url:
        slack_channel = SlackChannel(
            webhook_url=slack_url,
            username="kstlib-alerts",
        )
        # Rate limit: 10 alerts per minute
        slack_throttle = AlertThrottle(rate=10, per=60.0)
        manager.add_channel(
            slack_channel,
            min_level=AlertLevel.WARNING,
            throttle=slack_throttle,
        )
        print("  Slack channel configured (min_level=WARNING)")
    else:
        print("  Slack channel skipped (no SLACK_WEBHOOK_URL)")

    # Add Email channel for CRITICAL only
    if smtp_user:
        credentials = SMTPCredentials(username=smtp_user, password=smtp_pass)
        security = SMTPSecurity(use_starttls=True)
        smtp_transport = SMTPTransport(
            host=smtp_host,
            port=smtp_port,
            credentials=credentials,
            security=security,
        )
        email_channel = EmailChannel(
            transport=smtp_transport,
            sender=smtp_user,
            recipients=[smtp_user],
            subject_prefix="[CRITICAL]",
        )
        manager.add_channel(
            email_channel,
            min_level=AlertLevel.CRITICAL,
        )
        print("  Email channel configured (min_level=CRITICAL)")
    else:
        print("  Email channel skipped (no SMTP_USER)")

    if manager.channel_count == 0:
        print("\nNo channels configured. Set environment variables and try again.")
        return

    print(f"\nAlertManager ready with {manager.channel_count} channel(s)")
    print("-" * 50)

    # Send alerts of different levels
    alerts = [
        AlertMessage(
            title="Deployment Started",
            body="Starting deployment of version 2.1.0",
            level=AlertLevel.INFO,
        ),
        AlertMessage(
            title="High Memory Usage",
            body="Server api-1 memory at 90%",
            level=AlertLevel.WARNING,
        ),
        AlertMessage(
            title="Database Connection Lost",
            body="Primary database connection failed",
            level=AlertLevel.CRITICAL,
        ),
    ]

    for alert in alerts:
        print(f"\n[{alert.level.name}] {alert.title}")
        results = await manager.send(alert)

        if not results:
            print("  -> No channels matched (level too low)")
        else:
            for result in results:
                status = "OK" if result.success else f"FAILED: {result.error}"
                print(f"  -> {result.channel}: {status}")

    # Show statistics
    print("\n" + "=" * 50)
    print("Statistics:")
    print(f"  Total sent: {manager.stats.total_sent}")
    print(f"  Total failed: {manager.stats.total_failed}")
    print(f"  Total throttled: {manager.stats.total_throttled}")


async def main_config() -> None:
    """Send alerts using configuration file."""
    from pathlib import Path

    from kstlib.alerts import AlertLevel, AlertManager, AlertMessage
    from kstlib.config import load_config
    from kstlib.rapi.credentials import CredentialResolver

    # Change to script directory for config auto-discovery
    script_dir = Path(__file__).parent
    os.chdir(script_dir)

    # Load configuration
    try:
        raw_config = load_config()
        # Cast to dict for type checking (Box is dict-like)
        config: dict[str, Any] = dict(raw_config)
    except Exception as e:
        print(f"Error loading config: {e}")
        print("Make sure kstlib.conf.yml exists with alerts section")
        return

    alerts_config = dict(config.get("alerts", {}))
    credentials_config = config.get("credentials", {})

    if not alerts_config.get("channels"):
        print("No alert channels configured in kstlib.conf.yml")
        return

    # Filter channels: only keep dict entries (exclude timeout, max_retries defaults)
    raw_channels = alerts_config.get("channels", {})
    actual_channels = {k: dict(v) for k, v in raw_channels.items() if isinstance(v, dict)}
    alerts_config["channels"] = actual_channels

    # Create credential resolver and alert manager
    resolver = CredentialResolver(credentials_config)
    manager = AlertManager.from_config(alerts_config, resolver)

    print(f"AlertManager loaded with {manager.channel_count} channel(s) from config")
    print("-" * 50)

    # Send test alerts
    alerts = [
        AlertMessage(
            title="Config Test - INFO",
            body="Testing INFO level alert from config",
            level=AlertLevel.INFO,
        ),
        AlertMessage(
            title="Config Test - WARNING",
            body="Testing WARNING level alert from config",
            level=AlertLevel.WARNING,
        ),
        AlertMessage(
            title="Config Test - CRITICAL",
            body="Testing CRITICAL level alert from config",
            level=AlertLevel.CRITICAL,
        ),
    ]

    for alert in alerts:
        print(f"\n[{alert.level.name}] {alert.title}")
        results = await manager.send(alert)

        if not results:
            print("  -> No channels matched")
        else:
            for result in results:
                status = "OK" if result.success else f"FAILED: {result.error}"
                print(f"  -> {result.channel}: {status}")


def main() -> None:
    """Parse arguments and run example."""
    parser = argparse.ArgumentParser(description="Multi-channel alert example")
    parser.add_argument(
        "--config",
        action="store_true",
        help="Use kstlib.conf.yml instead of environment variables",
    )
    args = parser.parse_args()

    print("Multi-Channel Alert Example")
    print("=" * 50)

    if args.config:
        asyncio.run(main_config())
    else:
        asyncio.run(main_env())


if __name__ == "__main__":
    main()
