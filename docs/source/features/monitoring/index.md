# Monitoring

Generate HTML dashboards and reports from Python data structures with type-safe
render components, Jinja2 integration, and automated delivery.

## TL;DR

```python
from kstlib.monitoring import Monitoring, MonitorKV, StatusCell, StatusLevel

# Create monitoring with inline template
mon = Monitoring(template="""
<h1>{{ title }}</h1>
{{ metrics | render }}
""")

# Register collectors via decorator
@mon.collector
def title():
    return "Server Status"

@mon.collector
def metrics():
    return MonitorKV(items={
        "API": StatusCell("UP", StatusLevel.OK),
        "DB": StatusCell("DEGRADED", StatusLevel.WARNING),
    })

# Run: collect -> render -> deliver
result = mon.run_sync()
print(result.html)
```

## Key Features

- **Render Types**: Type-safe components (StatusCell, MonitorTable, MonitorKV, MonitorList, MonitorMetric, MonitorImage)
- **Jinja2 Integration**: `| render` filter for seamless template rendering
- **Decorator API**: Register collectors with `@mon.collector`
- **Config-Driven**: Load from `kstlib.conf.yml` or `*.monitor.yml` files
- **Delivery Backends**: Save to file or send via email (Gmail OAuth2)
- **Security**: XSS prevention, SVG sanitization, size limits

## Quick Start

### Option 1: Inline Template

```python
from kstlib.monitoring import Monitoring, MonitorTable, StatusCell, StatusLevel

mon = Monitoring(template="""
<html>
<body>
<h1>{{ title }}</h1>
{{ table | render }}
</body>
</html>
""")

@mon.collector
def title():
    return "Service Status"

@mon.collector
def table():
    t = MonitorTable(headers=["Service", "Status"])
    t.add_row(["API", StatusCell("UP", StatusLevel.OK)])
    t.add_row(["DB", StatusCell("DOWN", StatusLevel.CRITICAL)])
    return t

result = mon.run_sync()
```

### Option 2: Template File

```python
mon = Monitoring(template_file="templates/dashboard.html")

@mon.collector
def metrics():
    return collect_system_metrics()

result = mon.run_sync()
```

### Option 3: Config-Driven

```yaml
# kstlib.conf.yml
monitoring:
  name: server-status
  template_file: templates/dashboard.html
  inline_css: true
  delivery:
    type: mail
    sender: bot@example.com
    recipients:
      - team@example.com
```

```python
mon = Monitoring.from_config()

@mon.collector
def metrics():
    return collect_metrics()

mon.run_sync()  # Renders and sends email
```

## Render Types

### StatusCell

Colored status badges with semantic levels:

```python
from kstlib.monitoring import StatusCell, StatusLevel

# Four status levels
cell = StatusCell("HEALTHY", StatusLevel.OK)        # Green
cell = StatusCell("DEGRADED", StatusLevel.WARNING)  # Yellow
cell = StatusCell("DOWN", StatusLevel.ERROR)        # Orange
cell = StatusCell("FAILURE", StatusLevel.CRITICAL)  # Red

html = cell.render()  # <span class="status-ok">HEALTHY</span>
```

### MonitorTable

Striped HTML tables with typed headers:

```python
from kstlib.monitoring import MonitorTable, StatusCell, StatusLevel

table = MonitorTable(headers=["Service", "Status", "Uptime"])
table.add_row([
    "API Gateway",
    StatusCell("UP", StatusLevel.OK),
    "99.9%"
])
table.add_row([
    "Database",
    StatusCell("DEGRADED", StatusLevel.WARNING),
    "98.5%"
])

html = table.render()
```

### MonitorKV

Key-value stat panels as two-column grids:

```python
from kstlib.monitoring import MonitorKV

kv = MonitorKV()
kv.add("CPU Usage", "75%")
kv.add("Memory", "8.2 GB / 16 GB")
kv.add("Disk", "120 GB free")

# Or from dict
kv = MonitorKV(items={"CPU": "75%", "Memory": "8GB"})

html = kv.render()
```

### MonitorList

Ordered or unordered lists for events and alerts:

```python
from kstlib.monitoring import MonitorList

events = MonitorList(ordered=False)
events.add("2026-01-28 10:30 - Service restarted")
events.add("2026-01-28 09:15 - High CPU alert")

# Or from list
events = MonitorList(items=["Event 1", "Event 2"], ordered=True)

html = events.render()
```

### MonitorMetric

Hero-number display for KPIs:

```python
from kstlib.monitoring import MonitorMetric

pnl = MonitorMetric(
    value="+$1,234.56",
    label="Today's P&L",
    color="#00cc00"
)

html = pnl.render()  # Large styled number with label
```

### MonitorImage

Embedded images as Base64 data URIs (no external dependencies):

```python
from kstlib.monitoring import MonitorImage

# From file (auto-detects format via magic bytes)
logo = MonitorImage.from_file("logo.png")

# From bytes
icon = MonitorImage.from_bytes(png_data, "image/png")

# With sizing
logo = MonitorImage(path="logo.png", width=128, height=64, alt="Logo")

html = logo.render()  # <img src="data:image/png;base64,..." />
```

Supported formats: PNG, JPEG, GIF, WebP, SVG (sanitized), ICO.

## Jinja2 Integration

### The `| render` Filter

All render types work seamlessly with Jinja2 via the `| render` filter:

```python
from kstlib.monitoring import create_environment

env = create_environment()
template = env.from_string("""
<div class="dashboard">
  <h1>Status Dashboard</h1>
  {{ table | render }}
  <h2>Stats</h2>
  {{ kv | render }}
</div>
""")
```

### Inline CSS Mode

For email clients that strip `<style>` tags:

```python
from kstlib.monitoring import render_template

# Styles embedded in each element
html = render_template(source, context, inline_css=True)
```

### Custom Environment

Configure Jinja2 with your own loader:

```python
from jinja2 import FileSystemLoader
from kstlib.monitoring import create_environment

env = create_environment(
    loader=FileSystemLoader("templates/"),
    trim_blocks=True,
    lstrip_blocks=True,
)
```

## Delivery Backends

### FileDelivery

Save HTML reports to local files with automatic rotation:

```python
from kstlib.monitoring import Monitoring, FileDelivery

mon = Monitoring(
    template_file="dashboard.html",
    delivery=FileDelivery(
        output_dir="./reports",
        max_files=7,  # Keep last 7 reports
    ),
)

@mon.collector
def data():
    return collect_data()

mon.run_sync()  # Saves to ./reports/monitoring_YYYYMMDD_HHMMSS.html
```

### MailDelivery

Send reports via email using kstlib.mail transports:

```yaml
# kstlib.conf.yml
monitoring:
  template_file: dashboard.html
  inline_css: true  # Required for email!
  delivery:
    type: mail
    sender: bot@example.com
    recipients:
      - team@example.com
    subject_template: "Daily Report: {name}"
```

```python
mon = Monitoring.from_config()

@mon.collector
def metrics():
    return collect_metrics()

mon.run_sync()  # Sends email via Gmail OAuth2
```

```{note}
Mail delivery requires a valid Gmail OAuth2 token. Run `kstlib auth login google` first.
```

## Configuration

### In kstlib.conf.yml

```yaml
monitoring:
  # Dashboard name (used in delivery subject)
  name: server-status

  # Template (mutually exclusive)
  template: "<p>{{ msg }}</p>"      # Inline
  template_file: dashboard.html     # Or file path

  # Rendering options
  inline_css: true     # Embed styles (required for email)
  fail_fast: false     # Continue on collector errors

  # Delivery backend
  delivery:
    type: file         # or "mail"
    output_dir: ./reports
    max_files: 100
```

### Per-call Overrides

```python
# Override at instantiation
mon = Monitoring(
    template_file="dashboard.html",
    inline_css=False,  # Override default
    fail_fast=True,
)

# Control delivery at runtime
result = mon.run_sync(deliver=False)  # Skip delivery
```

## Common Patterns

### Server Monitoring Dashboard

```python
import platform
from kstlib.monitoring import (
    Monitoring, MonitorKV, MonitorTable,
    StatusCell, StatusLevel, MonitorImage
)

mon = Monitoring(template_file="server.html")

@mon.collector
def system_info():
    return MonitorKV(items={
        "Hostname": platform.node(),
        "OS": f"{platform.system()} {platform.release()}",
        "Python": platform.python_version(),
    })

@mon.collector
def services():
    import psutil
    cpu = psutil.cpu_percent()

    table = MonitorTable(headers=["Metric", "Value", "Status"])
    level = StatusLevel.OK if cpu < 80 else StatusLevel.WARNING
    table.add_row(["CPU", f"{cpu}%", StatusCell("OK" if cpu < 80 else "HIGH", level)])
    return table

@mon.collector
def logo():
    return MonitorImage(path="logo.png", width=100)

mon.run_sync()
```

### Trading Bot P&L Report

```python
from kstlib.monitoring import Monitoring, MonitorMetric, MonitorTable, StatusCell, StatusLevel

mon = Monitoring(template_file="pnl.html")

@mon.collector
def daily_pnl():
    pnl = calculate_pnl()
    color = "#00cc00" if pnl >= 0 else "#cc0000"
    return MonitorMetric(
        value=f"${pnl:+,.2f}",
        label="Today's P&L",
        color=color,
    )

@mon.collector
def positions():
    table = MonitorTable(headers=["Symbol", "Side", "P&L", "Status"])
    for pos in get_positions():
        level = StatusLevel.OK if pos.pnl >= 0 else StatusLevel.ERROR
        table.add_row([
            pos.symbol,
            pos.side,
            f"${pos.pnl:+.2f}",
            StatusCell("PROFIT" if pos.pnl >= 0 else "LOSS", level),
        ])
    return table

mon.run_sync()
```

### Conditional Sections

```html
<!-- dashboard.html -->
<h1>{{ title }}</h1>

{{ metrics | render }}

{% if alerts %}
<div class="alerts">
  <h2>Active Alerts</h2>
  {{ alerts | render }}
</div>
{% endif %}
```

```python
@mon.collector
def alerts():
    items = get_active_alerts()
    if not items:
        return None  # Section won't render
    return MonitorList(items=items)
```

## MonitoringService (Advanced)

For more control, use `MonitoringService` directly:

```python
from kstlib.monitoring import MonitoringService, MonitorKV

service = MonitoringService(
    template="<p>{{ data | render }}</p>",
    collectors={
        "data": lambda: MonitorKV(items={"key": "value"}),
    },
    inline_css=True,
    fail_fast=False,
)

# Async
result = await service.run()

# Sync
result = service.run_sync()

print(result.html)
print(result.success)
print(result.errors)  # Dict of collector errors
```

## Config Loader (Advanced)

Load monitoring configs from `*.monitor.yml` files:

```yaml
# dashboard.monitor.yml
name: daily-report
template: |
  <h1>{{ title }}</h1>
  <p>Version: {{ version }}</p>
collectors:
  title: "Daily Report"
  version:
    type: env
    env_var: APP_VERSION
    default: "1.0.0"
```

```python
from kstlib.monitoring import load_monitoring_config, discover_monitoring_configs

# Load single config
config = load_monitoring_config("dashboard.monitor.yml")
service = config.to_service()
result = service.run_sync()

# Discover all configs in directory
configs = discover_monitoring_configs("./monitoring", recursive=True)
for name, config in configs.items():
    service = config.to_service()
    service.run_sync()
```

## Security

The monitoring module includes defense-in-depth protections:

| Feature | Protection |
|---------|------------|
| XSS Prevention | All non-Renderable values are HTML-escaped |
| SVG Sanitization | Scripts and dangerous elements removed |
| Image Validation | Magic bytes verification, format whitelist |
| Size Limits | 512KB max per image, 50MB max output |
| Module Blocklist | Dangerous modules blocked in config loaders |
| Path Traversal | Output paths validated against base directory |
| Autoescape | Enabled by default in Jinja2 environment |

## Troubleshooting

**Template not found**
: Ensure `template_file` path is relative to `base_dir` (defaults to cwd).

**Email not sending**
: Run `kstlib auth login google` to get OAuth2 token. Check `inline_css: true`.

**Collector errors**
: Check `result.errors` dict. Set `fail_fast=True` to raise on first error.

**Images not displaying in email**
: Gmail may block external images. Use `MonitorImage` for Base64 embedding.

**CSS not applied in email**
: Always use `inline_css=True` for email delivery.

## API Reference

See {doc}`../../api/monitoring` for complete API documentation.

See {doc}`../../api/exceptions/monitoring` for exception handling patterns.
