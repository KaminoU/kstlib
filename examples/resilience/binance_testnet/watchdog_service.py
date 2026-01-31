#!/usr/bin/env python3
"""External Watchdog Service for Binance Resilience Demo.

This is a SEPARATE process that monitors the main application's health
by checking the heartbeat state file using kstlib's Watchdog.from_state_file().

Design rationale:
    The watchdog runs independently so it can detect when the main
    process has completely crashed (not just hung). If both were in
    the same process, a crash would take down both.

Usage:
    # Run in a separate terminal
    python watchdog_service.py

    # Or as a systemd service (see README.md for setup)

Configuration:
    Uses kstlib.conf.yml for:
    - resilience.watchdog.cycle_interval: seconds between checks (default: 300)
    - resilience.watchdog.max_heartbeat_age: max age before alert (default: 30)
    - Slack webhook from config/slack.sops.yml
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import signal
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

# kstlib imports
from kstlib.alerts import AlertLevel, AlertManager, AlertMessage
from kstlib.alerts.channels import SlackChannel
from kstlib.logging import LogManager, init_logging
from kstlib.resilience import GracefulShutdown, Watchdog

# Placeholder logger - will be replaced by LogManager in main()
# Use standard logging to avoid handler duplication from multiple init_logging() calls
import logging as _logging

log: LogManager | _logging.Logger = _logging.getLogger(__name__)


def create_alert_manager(config: Mapping[str, Any]) -> AlertManager:
    """Create AlertManager from config with Slack channels.

    Args:
        config: Configuration with credentials.sops_* webhook URLs.

    Returns:
        Configured AlertManager.
    """
    credentials = config.get("credentials", {})
    manager = AlertManager()

    # Add watchdog channel if webhook configured
    webhook_url = credentials.get("sops_wd")
    if webhook_url:
        channel = SlackChannel(
            webhook_url=webhook_url,
            username="kstlib-watchdog",
            icon_emoji=":dog:",
        )
        manager.add_channel(channel, key="watchdog")
        log.debug("Added Slack channel: watchdog")

    return manager


async def send_alert(
    manager: AlertManager,
    channel: str,
    message: str,
    context: Mapping[str, Any],
    *,
    level: AlertLevel = AlertLevel.CRITICAL,  # Watchdog alerts = serious by default
) -> None:
    """Send alert via AlertManager (on_alert callback compatible).

    Args:
        manager: AlertManager instance.
        channel: Target channel name.
        message: Alert message.
        context: Additional context data.
        level: Alert severity (default CRITICAL for watchdog).
    """
    try:
        alert = AlertMessage(
            title="[WATCHDOG] kstlib-resilience",
            body=f"{message}\n\nContext: {context}",
            level=level,
            timestamp=True,
        )
        await manager.send(alert, channel=channel)
    except Exception as exc:
        log.warning("Failed to send alert: %s", exc)


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load configuration from kstlib.conf.yml."""
    from kstlib.config import load_config as kstlib_load_config

    script_dir = Path(__file__).parent
    original_cwd = os.getcwd()

    try:
        os.chdir(script_dir)
        config = kstlib_load_config(filename=str(config_path)) if config_path else kstlib_load_config()
        return dict(config)
    finally:
        os.chdir(original_cwd)


async def run_watchdog(
    state_file: Path,
    check_interval: float,
    max_age: float,
    alert_manager: AlertManager,
    shutdown_event: asyncio.Event,
) -> None:
    """Run the watchdog service loop.

    Args:
        state_file: Path to heartbeat state file.
        check_interval: Seconds between checks.
        max_age: Max seconds before state is considered stale.
        alert_manager: AlertManager for Slack notifications.
        shutdown_event: Event to signal shutdown (set from signal handler).
    """
    log.info("Watchdog service started")
    log.info("State file: %s", state_file)
    log.info("Check interval: %s seconds", check_interval)
    log.info("Max age: %s seconds", max_age)

    async def on_alert(channel: str, message: str, context: Mapping[str, Any]) -> None:
        await send_alert(alert_manager, channel, message, context)

    def on_timeout() -> None:
        log.warning("TIMEOUT: Heartbeat state file is stale!")

    # Create watchdog using factory method
    watchdog = Watchdog.from_state_file(
        state_file=state_file,
        check_interval=check_interval,
        max_age=max_age,
        on_timeout=on_timeout,
        on_alert=on_alert,
        name="binance-resilience-watchdog",
    )

    # Run until shutdown
    async with watchdog:
        # Setup signal handlers (Unix only, Windows uses thread-safe approach in main)
        if sys.platform != "win32":
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, shutdown_event.set)

        await shutdown_event.wait()

    log.info("Watchdog service stopped")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="External Watchdog Service",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to kstlib.conf.yml",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=None,
        help="Override state file path",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Override check interval (seconds)",
    )
    parser.add_argument(
        "--max-age",
        type=float,
        default=None,
        help="Override max heartbeat age (seconds)",
    )
    args = parser.parse_args()

    # Load config
    try:
        config = load_config(args.config)
    except Exception as exc:
        print(f"Warning: Could not load config: {exc} (using defaults)", file=sys.stderr)
        config = {}

    # Extract settings from config
    resilience_config = config.get("resilience", {})
    watchdog_config = resilience_config.get("watchdog", {})
    hb_config = resilience_config.get("heartbeat", {})

    # Resolve state file path (CLI > watchdog config > heartbeat config > default)
    if args.state_file:
        state_file = args.state_file
    else:
        state_path = watchdog_config.get(
            "state_file",
            hb_config.get("state_file", "state/heartbeat.state.json"),
        )
        state_file = Path(__file__).parent / state_path

    # Resolve settings (CLI args > config > defaults)
    check_interval = args.interval or watchdog_config.get("cycle_interval", 300.0)
    max_age = args.max_age or watchdog_config.get("max_heartbeat_age", 30.0)

    # Initialize logging from config
    global log
    logger_config = config.get("logger", {})
    if logger_config.get("preset"):
        log = init_logging(preset=logger_config["preset"])

    # Create AlertManager
    alert_manager = create_alert_manager(config)

    # Create shutdown event (shared between GracefulShutdown and async code)
    shutdown_event = asyncio.Event()

    # Setup graceful shutdown with kstlib.resilience.GracefulShutdown
    shutdown = GracefulShutdown(timeout=30)
    shutdown.register("watchdog", shutdown_event.set, priority=10)
    shutdown.install()

    try:
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(run_watchdog(state_file, check_interval, max_age, alert_manager, shutdown_event))
    finally:
        shutdown.uninstall()


if __name__ == "__main__":
    main()
