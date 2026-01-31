"""Service monitoring dashboard rendered as HTML via Jinja2.

Simulates a trading infrastructure status page with:
- Service status table (API, WebSocket, Database, Cache, Watchdog)
- KPI hero metrics (uptime, P&L, latency)
- Key-value system info panel
- Recent event log

Generates two HTML files:
- ``dashboard_browser.html`` -- CSS class-based (for browsers)
- ``dashboard_email.html``   -- inline CSS (for email clients)

Usage::

    python examples/monitoring/service_dashboard.py

"""

from __future__ import annotations

import random
from pathlib import Path

from kstlib.monitoring import (
    MonitorImage,
    MonitorKV,
    MonitorList,
    MonitorMetric,
    MonitorTable,
    StatusCell,
    StatusLevel,
    render_template,
)

# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------

DASHBOARD_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Service Dashboard</title>
</head>
<body style="font-family:Consolas,Monaco,'Courier New',monospace;margin:20px;background:#1a1a2e;color:#e0e0e0;">

  <div style="display:flex;align-items:center;gap:16px;">
    {{ logo | render }}
    <h1 style="color:#16A085;margin:0;">Infrastructure Status</h1>
  </div>
  <p>Generated snapshot for demonstration purposes.</p>

  <h2>Service Health</h2>
  {{ table | render(inline_css=inline) }}

  <h2>Key Metrics</h2>
  <div style="display:flex;gap:32px;flex-wrap:wrap;">
    {{ uptime | render(inline_css=inline) }}
    {{ pnl | render(inline_css=inline) }}
    {{ latency | render(inline_css=inline) }}
  </div>

  <h2>System Info</h2>
  {{ sysinfo | render(inline_css=inline) }}

  <h2>Recent Events</h2>
  {{ events | render(inline_css=inline) }}

</body>
</html>
"""

# ---------------------------------------------------------------------------
# Data simulation
# ---------------------------------------------------------------------------


def _build_service_table() -> MonitorTable:
    """Build a status table for five infrastructure services."""
    table = MonitorTable(headers=["Service", "Region", "Status", "Uptime"])

    services = [
        ("API Gateway", "eu-west-1", StatusLevel.OK, "99.98%"),
        ("WebSocket Feed", "eu-west-1", StatusLevel.OK, "99.95%"),
        ("PostgreSQL Primary", "eu-west-1", StatusLevel.WARNING, "99.80%"),
        ("Redis Cache", "eu-west-1", StatusLevel.OK, "100%"),
        ("Watchdog", "eu-west-1", StatusLevel.ERROR, "97.2%"),
    ]

    for name, region, level, uptime in services:
        label = {
            StatusLevel.OK: "UP",
            StatusLevel.WARNING: "DEGRADED",
            StatusLevel.ERROR: "DOWN",
            StatusLevel.CRITICAL: "FAILURE",
        }[level]
        table.add_row([name, region, StatusCell(label, level), uptime])

    return table


def _build_metrics() -> tuple[MonitorMetric, MonitorMetric, MonitorMetric]:
    """Build three KPI hero metrics."""
    uptime = MonitorMetric(99.95, label="Overall Uptime", level=StatusLevel.OK, unit="%")
    pnl = MonitorMetric(
        f"+{random.randint(800, 2500)}",
        label="Daily P&L",
        level=StatusLevel.OK,
        unit=" USDT",
    )
    latency = MonitorMetric(42, label="Avg Latency", level=StatusLevel.WARNING, unit=" ms")
    return uptime, pnl, latency


def _build_sysinfo() -> MonitorKV:
    """Build a system info key-value panel."""
    return MonitorKV(
        items={
            "Host": "srv-prod-01.eu-west-1",
            "Python": "3.10.16",
            "kstlib": "1.54.0",
            "Uptime": "14d 6h 32m",
            "DB Pool": StatusCell("3/10 active", StatusLevel.OK),
        },
        title="Runtime",
    )


def _build_events() -> MonitorList:
    """Build a recent events log."""
    return MonitorList(
        items=[
            "14:32:01 - Watchdog restart triggered (timeout 30s exceeded)",
            "14:31:45 - PostgreSQL replica lag > 500ms, switching to WARNING",
            "14:30:00 - Heartbeat OK from all 4 services",
            "14:25:12 - Cache hit ratio: 94.7%",
            "14:20:00 - Daily P&L snapshot saved",
        ],
        ordered=True,
        title="Last 5 Events",
    )


# ---------------------------------------------------------------------------
# Render & write
# ---------------------------------------------------------------------------


def generate_dashboard() -> None:
    """Generate browser and email versions of the dashboard."""
    logo_path = Path(__file__).parent / "kst.png"
    logo = MonitorImage(path=logo_path, alt="kstlib", width=64, height=52)

    table = _build_service_table()
    uptime, pnl, latency = _build_metrics()
    sysinfo = _build_sysinfo()
    events = _build_events()

    base_context = {
        "logo": logo,
        "table": table,
        "uptime": uptime,
        "pnl": pnl,
        "latency": latency,
        "sysinfo": sysinfo,
        "events": events,
    }

    out_dir = Path(__file__).parent

    # Browser version (CSS classes + <style> block)
    browser_ctx = {**base_context, "inline": False}
    browser_html = render_template(DASHBOARD_TEMPLATE, browser_ctx, inline_css=False)
    browser_path = out_dir / "dashboard_browser.html"
    browser_path.write_text(browser_html, encoding="utf-8")
    print(f"Browser dashboard -> {browser_path}")

    # Email version (inline CSS, no <style> block)
    email_ctx = {**base_context, "inline": True}
    email_html = render_template(DASHBOARD_TEMPLATE, email_ctx, inline_css=True)
    email_path = out_dir / "dashboard_email.html"
    email_path.write_text(email_html, encoding="utf-8")
    print(f"Email dashboard   -> {email_path}")

    print("\nOpen either file in a browser to preview.")


if __name__ == "__main__":  # pragma: no cover - manual example
    generate_dashboard()
