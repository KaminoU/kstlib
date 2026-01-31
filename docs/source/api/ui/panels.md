# UI Panels

Config-driven helpers that create Rich panels with consistent styling. `PanelManager` merges defaults,
presets, and runtime overrides so dashboards keep coherent framing without hand-writing Rich code.

```{tip}
See {doc}`../../features/ui/panels` for the feature guide.
```

## Quick overview

- Defaults provide a neutral box (`ROUNDED`), bright blue border, and key/value table layout for
  mapping payloads.
- Presets (`info`, `success`, `warning`, `error`, `summary`) modify titles, icons, and content
  styles; you can extend them via `ui.panels.presets` in `kstlib.conf.yml`.
- Payloads accept strings, Rich renderables, mappings, sequences of `(key, value)`, or `None`.
- `print_panel_async` delegates to `asyncio.to_thread` so event loops stay responsive.

## Configuration snippet

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
                    icon: "📝"
                content:
                    sort_keys: true
                    key_style: "bold orchid2"
                    value_style: "dim white"
```

## Usage patterns

### Basic rendering

```python
from kstlib.ui.panels import PanelManager

manager = PanelManager()
manager.print_panel(payload={"status": "running", "jobs": 3})
manager.print_panel(kind="info", payload="System ready")
```

### Custom presets

```python
custom_config = {
    "presets": {
        "alerts": {
            "panel": {"title": "Alerts", "border_style": "red3", "icon": "[alert]"},
            "content": {"use_markup": True},
        }
    }
}

manager = PanelManager(config=custom_config)
manager.print_panel(kind="alerts", payload="[bold red]Risk warning[/bold red]")
```

### Async-friendly printing

```python
import asyncio
from kstlib.ui.panels import PanelManager

async def main() -> None:
    manager = PanelManager()
    await manager.print_panel_async(kind="summary", payload={"orders": 128, "errors": 1})

asyncio.run(main())
```

### Embedding Rich tables

```python
from kstlib.ui import TableBuilder
from kstlib.ui.panels import PanelManager

builder = TableBuilder()
manager = PanelManager()
payload = builder.render_table(kind="inventory", data=[{"component": "cache", "status": "ok"}])
manager.print_panel(kind="summary", payload=payload)
```

## Module reference

```{eval-rst}
.. automodule:: kstlib.ui.panels
	:members:
	:undoc-members:
	:show-inheritance:
	:noindex:
```
