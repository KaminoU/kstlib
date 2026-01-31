"""Demonstrate basic Rich panel workflows using ``PanelManager``."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from rich.console import Console
from rich.rule import Rule

from kstlib.ui import TableBuilder
from kstlib.ui.panels import PanelManager


def render_default_examples(console: Console) -> None:
    """Render baseline panels using built-in presets and overrides."""
    manager = PanelManager(console=console)

    console.print(Rule("Default configuration"))
    manager.print_panel(payload="Welcome to kstlib panel examples.")

    manager.print_panel(
        payload={"status": "running", "jobs": 3, "latency_ms": 42},
        content={"sort_keys": True, "key_style": "bold cyan", "value_style": "white"},
    )

    manager.print_panel(kind="info", payload="System is operating within normal parameters.")
    manager.print_panel(kind="success", payload="All monitoring checks passed.")
    manager.print_panel(kind="warning", payload="Disk space running low.")
    manager.print_panel(kind="error", payload="Failed to connect to database.")
    manager.print_panel(
        kind="summary",
        payload={
            "orders_processed": 128,
            "orders_failed": 1,
            "latency_ms_p95": 143,
            "last_success": "2025-11-07 21:42:00",
        },
        panel={"title": "Trading Engine Summary", "width": 128},
        content={"sort_keys": True},
    )

    manager.print_panel(
        payload="[bold yellow]Heads up![/bold yellow] Margin utilization above 70%.",
        panel={"title": "Inline override", "border_style": "orange3"},
        content={"use_markup": True},
    )


def render_configured_examples(console: Console) -> None:
    """Render panels using a custom configuration supplied at construction time."""
    custom_config: dict[str, Any] = {
        "presets": {
            "orders": {
                "panel": {
                    "title": "Order Summary",
                    "border_style": "bright_magenta",
                    "icon": "[trade]",
                },
                "content": {
                    "show_header": True,
                    "key_label": "Field",
                    "value_label": "Value",
                    "key_style": "bold white",
                    "value_style": "bright_white",
                },
            },
            "alerts": {
                "panel": {
                    "title": "Alert Stream",
                    "border_style": "red3",
                    "icon": "[alert]",
                    "padding": [1, 3],
                },
                "content": {
                    "use_markup": True,
                    "use_pretty": False,
                },
            },
        }
    }

    manager = PanelManager(config=custom_config, console=console)

    console.print(Rule("Custom presets"))
    manager.print_panel(
        kind="orders",
        payload=[
            ("Market", "ETH/USDT"),
            ("Side", "Buy"),
            ("Size", "1.5"),
            ("Price", "2,050.00"),
            ("Status", "Filled"),
        ],
    )

    manager.print_panel(
        kind="alerts",
        payload="[bold red]Risk warning:[/] Position exposure at 95% limit.",
    )


def render_panel_with_table(console: Console) -> None:
    """Embed a declarative table payload inside a panel preset."""
    table_builder = TableBuilder()
    panel_manager = PanelManager(console=console)

    columns: Sequence[dict[str, Any]] = (
        {"header": "Component", "key": "component", "style": "bold white"},
        {"header": "Version", "key": "version", "style": "cyan"},
        {"header": "Status", "key": "status", "justify": "center", "style": "bold yellow"},
        {"header": "Owner", "key": "owner", "style": "green"},
    )
    inventory_payload: Sequence[dict[str, Any]] = (
        {"component": "cache", "version": "1.2.3", "status": "ok", "owner": "infra"},
        {"component": "websocket", "version": "0.4.0", "status": "standby", "owner": "edge"},
        {"component": "watchdog", "version": "0.1.0", "status": "pending", "owner": "ops"},
    )

    table = table_builder.render_table(kind="inventory", columns=columns, data=inventory_payload, title="Service Stack")

    panel_manager.print_panel(
        kind="summary",
        payload=table,
        panel={"title": "Runtime Inventory", "border_style": "light_steel_blue1"},
    )


def main() -> None:
    """Run panel usage demonstrations with a shared console."""
    console = Console()
    console.print(Rule("kstlib.ui.panels basics"))

    render_default_examples(console)
    render_configured_examples(console)
    render_panel_with_table(console)

    console.print(Rule("Completed"))


if __name__ == "__main__":
    main()
