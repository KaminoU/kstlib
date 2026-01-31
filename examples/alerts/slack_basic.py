#!/usr/bin/env python3
"""Slack alert example with channel targeting and batch sending.

This example demonstrates:
    - Multi-channel Slack alerting
    - Channel targeting by key or alias
    - Level-based broadcast filtering
    - Batch sending (list of AlertMessage)
    - Timestamp prefix (timestamp=True)

Prerequisites:
    1. Create a Slack App: https://api.slack.com/apps
    2. Add Incoming Webhooks feature
    3. Create webhook URLs for your channels

Usage:
    # Single channel via environment variable
    export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/T.../B.../xxx"
    python slack_basic.py

    # Multi-channel with SOPS credentials (config-driven)
    cd examples/alerts
    python slack_basic.py --sops

Config file (examples/alerts/kstlib.conf.yml):
    credentials:
      slack_hb:
        type: sops
        path: "secrets/slack.sops.yml"
        key_field: "sops_hb"
      slack_wd:
        type: sops
        path: "secrets/slack.sops.yml"
        key_field: "sops_wd"

    alerts:
      channels:
        hb:                          # <- config key
          type: slack
          name: "heartbeat"          # <- optional alias
          credentials: slack_hb
          min_level: info
        wd:
          type: slack
          name: "watchdog"
          credentials: slack_wd
          min_level: warning

Channel targeting:
    # By config key
    await manager.send(alert, channel="hb")

    # By alias
    await manager.send(alert, channel="heartbeat")

    # Broadcast (level-based filtering)
    await manager.send(alert)  # goes to all matching channels

Note:
    Run from examples/alerts/ directory for kstlib.conf.yml auto-discovery.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys


async def main_env() -> None:
    """Send alerts using webhook URL from environment."""
    from kstlib.alerts import AlertLevel, AlertMessage
    from kstlib.alerts.channels import SlackChannel

    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print("Error: SLACK_WEBHOOK_URL environment variable not set")
        sys.exit(1)

    # Create Slack channel
    channel = SlackChannel(
        webhook_url=webhook_url,
        username="kstlib-example",
        icon_emoji=":robot_face:",
    )

    # Send alerts of different levels
    alerts = [
        AlertMessage(
            title="Deployment Started",
            body="Starting deployment of version 2.1.0 to production",
            level=AlertLevel.INFO,
        ),
        AlertMessage(
            title="High Memory Usage",
            body="Server api-1 memory at 85%. Consider scaling up.",
            level=AlertLevel.WARNING,
        ),
        AlertMessage(
            title="Database Connection Lost",
            body="Primary database connection failed. Failover in progress.",
            level=AlertLevel.CRITICAL,
        ),
    ]

    print("Sending alerts to Slack...")
    for alert in alerts:
        result = await channel.send(alert)
        status = "OK" if result.success else f"FAILED: {result.error}"
        print(f"  [{alert.level.name}] {alert.title}: {status}")


async def main_sops() -> None:
    """Send alerts using SOPS-encrypted credentials from kstlib.conf.yml."""
    from pathlib import Path

    from kstlib.alerts import AlertLevel, AlertManager, AlertMessage
    from kstlib.config import load_config
    from kstlib.rapi.credentials import CredentialResolver

    # Change to script directory for config auto-discovery
    script_dir = Path(__file__).parent
    os.chdir(script_dir)

    # Load config from kstlib.conf.yml (with SOPS auto-decrypt)
    config = dict(load_config())

    # Get config sections
    credentials_config = config.get("credentials", {})
    alerts_config = dict(config.get("alerts", {}))

    if not credentials_config:
        print("Error: No 'credentials' section in kstlib.conf.yml")
        sys.exit(1)

    if not alerts_config.get("channels"):
        print("Error: No 'alerts.channels' section in kstlib.conf.yml")
        sys.exit(1)

    # Filter channels: only keep dict entries (exclude timeout, max_retries defaults)
    raw_channels = alerts_config.get("channels", {})
    actual_channels = {k: dict(v) for k, v in raw_channels.items() if isinstance(v, dict)}
    alerts_config["channels"] = actual_channels

    # Create alert manager from config (100% config-driven)
    resolver = CredentialResolver(credentials_config)
    manager = AlertManager.from_config(alerts_config, resolver)

    print("Config source: kstlib.conf.yml (SOPS auto-decrypted)")
    print(f"Channels: {list(alerts_config.get('channels', {}).keys())}")
    print()

    # Demo 1: Targeted sending (by key or alias)
    print("=" * 50)
    print("Demo 1: Targeted channel sending")
    print("=" * 50)

    # Send to heartbeat only (by key "hb") with timestamp prefix
    alert_hb = AlertMessage(
        title="Heartbeat Check",
        body="Targeted to 'hb' channel only",
        level=AlertLevel.INFO,
        timestamp=True,  # Adds "YYYY-MM-DD HH:MM:SS ::: " prefix
    )
    print(f"\n[{alert_hb.level.name}] {alert_hb.formatted_title} -> channel='hb'")
    results = await manager.send(alert_hb, channel="hb")
    for result in results:
        status = "OK" if result.success else f"FAILED: {result.error}"
        print(f"  -> {result.channel}: {status}")

    # Send multiple alerts to watchdog (by alias "watchdog") with timestamps
    alerts_wd = [
        AlertMessage(
            title="Watchdog Alert 1",
            body="Targeted to 'watchdog' alias - first message",
            level=AlertLevel.WARNING,
            timestamp=True,
        ),
        AlertMessage(
            title="Watchdog Alert 2",
            body="Targeted to 'watchdog' alias - second message",
            level=AlertLevel.WARNING,
            timestamp=True,
        ),
    ]
    print(f"\nSending {len(alerts_wd)} alerts -> channel='watchdog'")
    results = await manager.send(alerts_wd, channel="watchdog")
    for result in results:
        status = "OK" if result.success else f"FAILED: {result.error}"
        print(f"  -> {result.channel}: {status}")

    # Demo 2: Broadcast (level-based filtering)
    print()
    print("=" * 50)
    print("Demo 2: Broadcast (level-based filtering)")
    print("=" * 50)

    alert_broadcast = AlertMessage(
        title="Critical System Alert",
        body="Broadcast to all channels matching WARNING+",
        level=AlertLevel.WARNING,
        timestamp=True,
    )
    print(f"\n[{alert_broadcast.level.name}] {alert_broadcast.title} -> broadcast")
    results = await manager.send(alert_broadcast)  # No channel = broadcast
    for result in results:
        status = "OK" if result.success else f"FAILED: {result.error}"
        print(f"  -> {result.channel}: {status}")
    print()


def main() -> None:
    """Parse arguments and run example."""
    parser = argparse.ArgumentParser(description="Slack alert example")
    parser.add_argument(
        "--sops",
        action="store_true",
        help="Use SOPS-encrypted credentials instead of environment variable",
    )
    args = parser.parse_args()

    if args.sops:
        asyncio.run(main_sops())
    else:
        asyncio.run(main_env())


if __name__ == "__main__":
    main()
