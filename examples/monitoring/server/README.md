# Server Monitoring Example

Config-driven server monitoring with decorator-based collectors.

## Overview

This example demonstrates the simplified `Monitoring` API:

- **Config in YAML**: template, delivery settings
- **Collectors in Python**: `@mon.collector` decorators
- **Simple API**: `mon.run()` to collect, render, deliver

## Files

| File | Description |
|------|-------------|
| `kstlib.conf.yml` | Unified config (includes auth + monitoring) |
| `server.monitor.yml` | Monitoring config (template, delivery) |
| `server.html.j2` | HTML template |
| `run.py` | Main script with collectors |

## Configuration

### server.monitor.yml

```yaml
monitoring:
  name: server-status
  template_file: server.html.j2
  inline_css: true

  delivery:
    type: mail
    sender: me@gmail.com
    recipients: [team@example.com]
```

No collectors in YAML - they're in Python!

### run.py

```python
from kstlib.monitoring import Monitoring, MonitorKV, StatusCell

mon = Monitoring.from_config()

@mon.collector
def system_metrics():
    return MonitorKV(items={"hostname": "srv-01", "cpu": "45%"})

@mon.collector
def services():
    return MonitorTable(headers=["Service", "Status"])

mon.run_sync()  # Collect + render + deliver
```

## Usage

```bash
cd examples/monitoring/server

# Test without sending email
python run.py --no-send

# Save to specific file
python run.py -o report.html

# Send via Gmail (requires OAuth setup)
python run.py
```

## Adding Collectors

Just add a decorated function:

```python
@mon.collector
def my_new_metric():
    return MonitorKV(items={"key": "value"})
```

Then use `{{ my_new_metric | render }}` in the template.

## Render Types

| Type | Usage |
|------|-------|
| `MonitorKV` | Key-value pairs |
| `MonitorTable` | Tables with StatusCell |
| `MonitorList` | Ordered/unordered lists |
| `MonitorMetric` | Big number display |
| `MonitorImage` | Embedded images |
| `StatusCell` | Colored status badges |
