# UI Helpers

Declarative wrappers for Rich/Textual components. Build dashboards, status panels, and data tables with configuration-driven layouts.

## TL;DR

```python
from kstlib.ui import PanelManager, TableManager

# Status panel
panel = PanelManager(title="System Status")
panel.update({"cpu": "45%", "memory": "2.1GB", "uptime": "3d 12h"})
panel.render()

# Data table
table = TableManager(columns=["Name", "Status", "Last Updated"])
table.add_row("API", "Online", "2 min ago")
table.render()
```

## Key Features

- **Configuration-driven**: Layout and styling from `kstlib.conf.yml`
- **Rich integration**: Leverages Rich for terminal rendering
- **Consistent styling**: Unified themes across panels and tables
- **Live updates**: Support for dynamic content refresh
- **Spinners**: Animated feedback with multiple styles

## Quick Start

```python
from kstlib.ui import PanelManager, TableManager
from kstlib.ui.spinner import Spinner

# 1. Status panel
panel = PanelManager(title="Server Status")
panel.update({"hostname": "prod-01", "cpu": "23%"})
panel.render()

# 2. Data table
table = TableManager(columns=["Service", "Status"])
table.add_row("API", "OK")
table.add_row("Database", "OK")
table.render()

# 3. Spinner for long operations
with Spinner("Processing..."):
    do_long_operation()
```

## How It Works

### Panels

Key-value status displays with Rich formatting:

```python
from kstlib.ui import PanelManager

panel = PanelManager(title="Server Status")
panel.update({
    "hostname": "prod-01",
    "cpu": "23%",
    "memory": "4.2GB / 16GB",
    "disk": "120GB / 500GB",
})
panel.render()
```

Styled panels:

```python
panel = PanelManager(
    title="Alerts",
    border_style="red",
    title_align="center",
)
```

### Tables

Data tables with column and row styling:

```python
from kstlib.ui import TableManager

table = TableManager(columns=["Service", "Status", "Response Time"])
table.add_row("API Gateway", "OK", "45ms")
table.add_row("Database", "OK", "12ms")
table.add_row("Cache", "WARN", "89ms")
table.render()
```

Styled columns:

```python
table = TableManager(
    columns=[
        {"name": "Service", "style": "cyan"},
        {"name": "Status", "style": "green"},
        {"name": "Latency", "justify": "right"},
    ]
)
```

Row styling:

```python
table.add_row("API", "OK", "45ms", style="green")
table.add_row("DB", "ERROR", "timeout", style="red bold")
```

### Spinners

Animated feedback for CLI operations:

```python
from kstlib.ui.spinner import Spinner

# Basic spinner
with Spinner("Processing..."):
    do_long_operation()

# Different styles
with Spinner("Loading...", style="MOON"):
    time.sleep(2)

# Different animations
with Spinner("Syncing...", animation_type="bounce"):
    time.sleep(2)

with Spinner("Analyzing...", animation_type="color_wave"):
    time.sleep(2)

# From preset
spinner = Spinner.from_preset("fancy", "Processing...")
with spinner:
    time.sleep(2)
```

## Configuration

### In kstlib.conf.yml

```yaml
ui:
  panels:
    default_border_style: "blue"
    default_title_align: "left"
    padding: [0, 1]
  tables:
    show_header: true
    header_style: "bold"
    row_styles: ["", "dim"]  # Alternating
    box: "ROUNDED"
```

## Common Patterns

### Live dashboard

```python
from rich.live import Live
from kstlib.ui import PanelManager

panel = PanelManager(title="Live Metrics")

with Live(panel.renderable, refresh_per_second=1) as live:
    while True:
        metrics = fetch_current_metrics()
        panel.update(metrics)
        live.update(panel.renderable)
```

### Service status table

```python
table = TableManager(columns=["Service", "Status", "Latency"])

for service in services:
    status = check_service(service)
    style = "green" if status.ok else "red"
    table.add_row(service.name, status.state, f"{status.latency}ms", style=style)

table.render()
```

### Progress indicator

```python
from kstlib.ui.spinner import Spinner

with Spinner("Downloading...", style="BLOCKS"):
    download_file(url)

with Spinner("Installing...", animation_type="bounce"):
    install_package()
```

## Troubleshooting

### Panel not rendering

Ensure you call `.render()`:

```python
panel = PanelManager(title="Test")
panel.update({"key": "value"})
panel.render()  # Don't forget this!
```

### Table columns mismatch

Column count must match row data:

```python
# Wrong: 3 columns but 2 values
table = TableManager(columns=["A", "B", "C"])
table.add_row("1", "2")  # Error!

# Correct
table.add_row("1", "2", "3")
```

### Spinner not showing

Ensure terminal supports ANSI escape codes. In some environments:

```python
# Force simple mode if needed
with Spinner("Working...", style="LINE"):
    pass
```

### Colors not appearing

Rich requires a compatible terminal. Check:

```python
from rich.console import Console
console = Console()
console.print("[red]Test[/red]")
```

## Learn More

```{toctree}
:maxdepth: 1
:hidden:

panels
tables
spinners
```

## API Reference

Full autodoc: {doc}`../../api/ui/index`

| Class | Description |
| - | - |
| `PanelManager` | Key-value status panels |
| `TableManager` | Data tables with styling |
| `Spinner` | Animated CLI spinners |
