"""Showcase declarative TableBuilder usage."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from rich.console import Console

from kstlib.ui import PanelManager, TableBuilder

Row = Mapping[str, Any]
ColumnConfig = Mapping[str, Any]


def demo_default_table(builder: TableBuilder, console: Console) -> None:
    """Render the default key/value layout."""
    metrics_data: Sequence[Row] = (
        {"key": "status", "value": "running"},
        {"key": "retries", "value": 2},
        {"key": "uptime", "value": "48h"},
    )
    table = builder.render_table(data=metrics_data)
    console.print("\n[bold]Default layout[/bold]")
    console.print(table)


def demo_configured_inventory(builder: TableBuilder, console: Console) -> None:
    """Render the inventory preset defined in configuration."""
    inventory_data: Sequence[Row] = (
        {"component": "cache", "version": "1.2.3", "status": "ok"},
        {"component": "websocket", "version": "0.4.0", "status": "standby"},
        {"component": "watchdog", "version": "0.1.0", "status": "pending"},
    )
    table = builder.render_table(kind="inventory", data=inventory_data)
    console.print("\n[bold]Inventory preset[/bold]")
    console.print(table)


def demo_runtime_columns(builder: TableBuilder, console: Console) -> None:
    """Override columns at runtime with dotted key resolution and styling."""
    columns: Sequence[ColumnConfig] = (
        {"header": "Service", "key": "name", "style": "bold white", "width": 14},
        {"header": "Region", "key": "metadata.region", "style": "cyan", "min_width": 12},
        {
            "header": "Failover",
            "key": "metadata.failover",
            "justify": "center",
            "style": "yellow",
            "max_width": 12,
        },
    )
    services: Sequence[Row] = (
        {"name": "matcher", "metadata": {"region": "eu-west-1", "failover": "active"}},
        {"name": "notifier", "metadata": {"region": "us-east-2", "failover": "standby"}},
    )
    table = builder.render_table(columns=columns, data=services, title="Service Map", box="SIMPLE_HEAD")
    console.print("\n[bold]Runtime columns[/bold]")
    console.print(table)


def demo_table_in_panel(builder: TableBuilder, console: Console) -> None:
    """Render a table payload inside a panel preset."""
    panel_manager = PanelManager(console=console)
    payload: Sequence[Row] = (
        {"component": "cache", "version": "1.2.3", "status": "ok"},
        {"component": "websocket", "version": "0.4.0", "status": "standby"},
        {"component": "watchdog", "version": "0.1.0", "status": "pending"},
    )
    table = builder.render_table(kind="inventory", data=payload)
    console.print("\n[bold]Table embedded in panel[/bold]")
    panel_manager.print_panel(kind="summary", payload=table, panel={"title": "Stack Overview"})


def main() -> None:
    """Run table examples."""
    console = Console()
    builder = TableBuilder()
    demo_default_table(builder, console)
    demo_configured_inventory(builder, console)
    demo_runtime_columns(builder, console)
    demo_table_in_panel(builder, console)


if __name__ == "__main__":
    main()
