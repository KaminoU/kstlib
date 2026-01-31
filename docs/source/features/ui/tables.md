# Tables

Declarative Rich tables with presets and runtime column configuration.

## Quick Start

```python
from kstlib.ui.tables import TableBuilder

builder = TableBuilder()
builder.print_table(data=[
    {"key": "status", "value": "running"},
    {"key": "jobs", "value": 3},
])
```

## Presets

### Inventory preset

```python
inventory = [
    {"component": "cache", "version": "1.2.3", "status": "ok"},
    {"component": "watchdog", "version": "0.1.0", "status": "pending"},
]
TableBuilder().print_table(kind="inventory", data=inventory)
```

### Metrics preset

```python
metrics = [
    {"key": "latency", "value": "43ms"},
    {"key": "throughput", "value": "1.2k/s"},
]
TableBuilder().print_table(kind="metrics", data=metrics)
```

## Configuration

```yaml
ui:
  tables:
    defaults:
      table:
        box: "SIMPLE"
        show_header: true
        header_style: "bold cyan"
      columns:
        - header: "Key"
          key: "key"
          style: "bold white"
        - header: "Value"
          key: "value"
    presets:
      inventory:
        table:
          title: "Inventory"
          box: "SIMPLE_HEAVY"
          show_lines: true
        columns:
          - header: "Component"
            key: "component"
            style: "bold"
          - header: "Version"
            key: "version"
            style: "cyan"
          - header: "Status"
            key: "status"
            justify: "center"
```

## Runtime Column Overrides

```python
columns = (
    {"header": "Service", "key": "name", "style": "bold white"},
    {"header": "Region", "key": "metadata.region", "style": "cyan"},
)
services = (
    {"name": "matcher", "metadata": {"region": "eu-west-1"}},
    {"name": "notifier", "metadata": {"region": "us-east-2"}},
)
TableBuilder().print_table(columns=columns, data=services, table={"title": "Service Map"})
```

## Nested Keys

Access nested data with dot notation:

```python
columns = [
    {"header": "Name", "key": "name"},
    {"header": "Region", "key": "metadata.region"},
    {"header": "Status", "key": "health.status"},
]
```

## Embedding in Panels

```python
from kstlib.ui import PanelManager, TableBuilder

builder = TableBuilder()
panel_manager = PanelManager()

table = builder.render_table(kind="metrics", data=[{"key": "latency", "value": "43ms"}])
panel_manager.print_panel(kind="summary", payload=table)
```

## Async Support

```python
import asyncio

async def main():
    builder = TableBuilder()
    await builder.print_table_async(data=[{"key": "status", "value": "ok"}])

asyncio.run(main())
```

## API Reference

-> Full autodoc: {doc}`../../api/ui/tables`
