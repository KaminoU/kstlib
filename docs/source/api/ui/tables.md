# UI Tables

Declarative table builder that formats Rich tables from defaults, presets, and runtime overrides.
`TableBuilder` uses the standard config cascade so dashboards can swap layouts without touching
application code.

```{tip}
See {doc}`../../features/ui/tables` for the feature guide.
```

## Quick overview

- Defaults emit a two-column key/value table with `SIMPLE` box and cyan headers.
- Presets such as `inventory` and `metrics` tweak titles, line styles, and header colors; extend via
  `ui.tables.presets`.
- Data can be provided as sequences of mappings (`data=[...]`) or explicit `rows=` sequences.
- Column definitions support dotted keys (`metadata.region`), width hints, justification, and custom
  styles. Runtime `columns=` overrides replace everything configured in presets.
- `print_table_async` mirrors the panel API for asyncio contexts.

## Configuration snippet

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

## Usage patterns

### Default key/value table

```python
from kstlib.ui.tables import TableBuilder

builder = TableBuilder()
table = builder.render_table(data=[{"key": "status", "value": "running"}])
builder.print_table(data=[{"key": "retries", "value": 2}])
```

### Inventory preset

```python
inventory = [
    {"component": "cache", "version": "1.2.3", "status": "ok"},
    {"component": "watchdog", "version": "0.1.0", "status": "pending"},
]
TableBuilder().print_table(kind="inventory", data=inventory)
```

### Runtime column overrides

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

### Embedding in panels

```python
from kstlib.ui import PanelManager, TableBuilder

builder = TableBuilder()
panel_manager = PanelManager()
payload = builder.render_table(kind="metrics", data=[{"key": "latency", "value": "43ms"}])
panel_manager.print_panel(kind="summary", payload=payload)
```

## Module reference

```{eval-rst}
.. automodule:: kstlib.ui.tables
		:members:
		:undoc-members:
		:show-inheritance:
		:noindex:
```
