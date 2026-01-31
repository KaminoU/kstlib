# Panels

Config-driven Rich panels with consistent styling for dashboards and status displays.

## Quick Start

```python
from kstlib.ui.panels import PanelManager

manager = PanelManager()
manager.print_panel(payload={"status": "running", "jobs": 3})
```

## Presets

Built-in presets for common use cases:

```python
manager.print_panel(kind="info", payload="System ready")
manager.print_panel(kind="success", payload="Task completed")
manager.print_panel(kind="warning", payload="Low disk space")
manager.print_panel(kind="error", payload="Connection failed")
manager.print_panel(kind="summary", payload={"total": 100, "processed": 95})
```

## Configuration

```yaml
ui:
  panels:
    defaults:
      panel:
        border_style: "bright_blue"
        box: "ROUNDED"
        padding: [1, 2]
      content:
        box: "SIMPLE"
        show_header: false
        key_style: "bold white"
        value_style: null
        sort_keys: false
    presets:
      summary:
        panel:
          border_style: "light_steel_blue1"
          title: "Execution Summary"
          icon: "..."
        content:
          sort_keys: true
          key_style: "bold orchid2"
```

## Custom Presets

```python
custom_config = {
    "presets": {
        "alerts": {
            "panel": {"title": "Alerts", "border_style": "red3"},
            "content": {"use_markup": True},
        }
    }
}

manager = PanelManager(config=custom_config)
manager.print_panel(kind="alerts", payload="[bold red]Risk warning[/bold red]")
```

## Async Support

```python
import asyncio

async def main():
    manager = PanelManager()
    await manager.print_panel_async(kind="summary", payload={"orders": 128})

asyncio.run(main())
```

## Embedding Tables

```python
from kstlib.ui import TableBuilder, PanelManager

builder = TableBuilder()
manager = PanelManager()

table = builder.render_table(kind="inventory", data=[{"component": "cache", "status": "ok"}])
manager.print_panel(kind="summary", payload=table)
```

## API Reference

-> Full autodoc: {doc}`../../api/ui/panels`
