#!/usr/bin/env python3
"""Server monitoring with decorator-based collectors.

This example demonstrates the simplified Monitoring API:
- Config in YAML (template, delivery)
- Collectors in Python (@mon.collector)
- Simple mon.run() to collect, render, deliver

Usage:
    cd examples/monitoring/server
    python run.py
    python run.py --no-send
"""

from __future__ import annotations

import argparse
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add src and project root to path for development
_project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(_project_root / "src"))
sys.path.insert(0, str(_project_root))

from kstlib.monitoring import (  # noqa: E402
    Monitoring,
    MonitorImage,
    MonitorKV,
    MonitorList,
    MonitorTable,
    StatusCell,
    StatusLevel,
)


# =============================================================================
# Collectors - Pure Python, no YAML config needed
# =============================================================================


def create_monitoring() -> Monitoring:
    """Create and configure monitoring instance with collectors."""
    # Work from script directory
    base_dir = Path(__file__).parent
    original_cwd = Path.cwd()
    os.chdir(base_dir)

    try:
        mon = Monitoring.from_config(base_dir=base_dir)
    finally:
        os.chdir(original_cwd)

    # Register collectors via decorator
    @mon.collector
    def generated_at() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    @mon.collector
    def title() -> str:
        return "Server Status Report"

    @mon.collector
    def environment() -> str:
        return os.getenv("ENVIRONMENT", "development")

    @mon.collector
    def version() -> str:
        return os.getenv("APP_VERSION", "1.55.9")

    @mon.collector
    def logo() -> MonitorImage:
        logo_path = base_dir.parent / "kst.png"
        return MonitorImage(path=logo_path, alt="kstlib", width=128, height=104)

    @mon.collector
    def system_metrics() -> MonitorKV:
        items: dict[str, str | StatusCell] = {
            "Hostname": platform.node(),
            "OS": f"{platform.system()} {platform.release()}",
            "Python": platform.python_version(),
            "Architecture": platform.machine(),
        }

        try:
            import psutil

            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory().percent
            disk = psutil.disk_usage("/" if platform.system() != "Windows" else "C:\\")

            items["CPU Usage"] = StatusCell(f"{cpu}%", _level(cpu, 75, 90))
            items["Memory Usage"] = StatusCell(f"{mem}%", _level(mem, 85, 95))
            items["Disk Usage"] = StatusCell(f"{disk.percent}%", _level(disk.percent, 80, 95))
        except ImportError:
            items["CPU Usage"] = "N/A (psutil not installed)"
            items["Memory Usage"] = "N/A"
            items["Disk Usage"] = "N/A"

        return MonitorKV(items=items, title="System Information")

    @mon.collector
    def services_table() -> MonitorTable:
        table = MonitorTable(headers=["Service", "Status", "Response Time", "Uptime"])

        # Example services (replace with real checks)
        services = [
            ("API Gateway", StatusLevel.OK, "45ms", "99.98%"),
            ("Database", StatusLevel.OK, "12ms", "99.95%"),
            ("Redis Cache", StatusLevel.WARNING, "150ms", "99.80%"),
            ("Message Queue", StatusLevel.OK, "8ms", "100%"),
            ("Scheduler", StatusLevel.OK, "5ms", "99.99%"),
        ]

        for name, level, latency, uptime in services:
            status_text = {
                StatusLevel.OK: "UP",
                StatusLevel.WARNING: "DEGRADED",
                StatusLevel.ERROR: "DOWN",
                StatusLevel.CRITICAL: "FAILURE",
            }[level]
            table.add_row([name, StatusCell(status_text, level), latency, uptime])

        return table

    @mon.collector
    def alerts() -> MonitorList | None:
        # Return None if no alerts (template uses {% if alerts %})
        alert_items: list[str] = []
        # Uncomment to test:
        # alert_items = ["WARNING: Redis latency above threshold"]
        if not alert_items:
            return None
        return MonitorList(items=alert_items, ordered=False, title="Active Alerts")

    return mon


def _level(value: float, warn: float, crit: float) -> StatusLevel:
    """Determine status level based on thresholds."""
    if value >= crit:
        return StatusLevel.CRITICAL
    if value >= warn:
        return StatusLevel.WARNING
    return StatusLevel.OK


# =============================================================================
# Main
# =============================================================================


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Server monitoring dashboard")
    parser.add_argument("--no-send", action="store_true", help="Don't send email")
    parser.add_argument("--output", "-o", help="Save HTML to file")
    return parser.parse_args()


def main() -> None:
    """Run monitoring."""
    args = parse_args()

    print("=" * 60)
    print("SERVER MONITORING - Simplified API")
    print("=" * 60)
    print()

    # Create monitoring with collectors
    mon = create_monitoring()
    print(f"Dashboard: {mon.name}")
    print(f"Collectors: {mon.collector_names}")
    print()

    # Run (collect + render + deliver)
    print("Running collectors...")
    result = mon.run_sync(deliver=not args.no_send and not args.output)

    print(f"Success: {result.success}")
    print(f"HTML size: {len(result.html):,} bytes")

    if args.output:
        Path(args.output).write_text(result.html, encoding="utf-8")
        print(f"Saved to: {args.output}")
    elif args.no_send:
        output = Path(__file__).parent / "server_report.html"
        output.write_text(result.html, encoding="utf-8")
        print(f"Saved to: {output}")
        print("(--no-send: email not sent)")
    else:
        print("Email sent!")

    print()
    print("Done!")


if __name__ == "__main__":
    main()
