# Logging

Rich-enabled logging with presets, rotation, and async helpers.

## TL;DR

```python
from kstlib.logging import LogManager

log = LogManager()
log.info("Application started")
log.success("Task completed", task_id=123)
log.error("Something failed", error="details")
```

## Key Features

- **Rich rendering**: Color themes, icons, and traceback formatting
- **Presets**: `dev`, `prod`, `debug` for common scenarios
- **Dual output**: Console and/or file with independent levels
- **File rotation**: Timed rotation with configurable retention
- **Async helpers**: Non-blocking logging for event loops
- **Structured context**: Key-value pairs in log messages
- **TRACE level**: Ultra-verbose logging for HTTP traces and protocol debugging

## Quick Start

```python
from kstlib.logging import LogManager

# 1. Basic logging
log = LogManager()
log.info("Application started")
log.warning("Something to watch")
log.error("An error occurred")

# 2. With preset
log = LogManager(preset="dev")  # Verbose console, no file

# 3. Structured context
log.info("User action", user_id=42, action="login", ip="192.168.1.1")
```

## How It Works

### Log Levels

kstlib provides 7 log levels, including 2 custom levels:

| Level | Value | Use Case |
| - | - | - |
| `TRACE` | 5 | HTTP traces, protocol dumps, detailed diagnostics |
| `DEBUG` | 10 | General debugging information |
| `INFO` | 20 | Normal operational messages |
| `SUCCESS` | 25 | Operation completed successfully |
| `WARNING` | 30 | Something unexpected but handled |
| `ERROR` | 40 | Error occurred, operation failed |
| `CRITICAL` | 50 | System failure, immediate attention needed |

### Presets

Use presets for common configurations:

```python
log = LogManager(preset="dev")    # Development
log = LogManager(preset="prod")   # Production
log = LogManager(preset="debug")  # Debug level (use TRACE for max verbosity)
```

| Preset | Console | File | Icons |
| - | - | - | - |
| `dev` | DEBUG | OFF | Yes |
| `prod` | OFF | INFO | No |
| `debug` | DEBUG | OFF | Yes |
| `trace` | TRACE | TRACE | Yes |

### Output Modes

```python
log = LogManager(config={"output": "console"})  # Console only
log = LogManager(config={"output": "file"})     # File only
log = LogManager(config={"output": "both"})     # Both (default)
```

### File Rotation

Logs are automatically rotated based on configuration:

```yaml
logger:
  rotation:
    when: midnight    # midnight | H | D | W0-W6
    interval: 1
    backup_count: 7   # Keep 7 days of logs
```

## Configuration

### In kstlib.conf.yml

```yaml
logger:
  defaults:
    output: both
    theme:
      trace: "dim cyan"
      debug: "dim"
      info: "sky_blue1"
      success: "green"
      warning: "yellow"
      error: "red"
      critical: "bold red"
    icons:
      show: true
    console:
      level: DEBUG
      show_path: true
      tracebacks_show_locals: true
    file:
      level: DEBUG
      log_path: "./"
      log_dir: "logs"
      log_name: "kstlib.log"
```

### Runtime override

```python
log = LogManager(config={
    "output": "console",
    "console": {"level": "INFO"},
    "icons": {"show": False},
})
```

### Theme customization

Customize colors using Rich style strings:

```python
log = LogManager(config={
    "theme": {
        "info": "bold blue",
        "error": "bold white on red",
        "success": "green",
    }
})
```

## Common Patterns

### HTTP trace debugging

```python
log = LogManager(config={"console": {"level": "TRACE"}})

# Log HTTP request/response details
log.trace("POST /api/token", headers={"Content-Type": "application/json"})
log.trace("Response 200", body={"access_token": "***"})
```

### Async logging

```python
import asyncio
from kstlib.logging import LogManager

log = LogManager()

async def main():
    await log.ainfo("Async operation started")
    await log.asuccess("Async operation completed")
    await log.aerror("Async operation failed")

asyncio.run(main())
```

### Structured logging for trading

```python
log.info("Order placed",
    symbol="BTC/USDT",
    side="buy",
    amount=0.5,
    price=42000.00
)

log.success("Order filled",
    order_id="abc123",
    fill_price=41999.50,
    slippage_bps=1.2
)
```

### Production setup

```python
# Minimal console output, detailed file logs
log = LogManager(preset="prod")

# Or explicit configuration
log = LogManager(config={
    "output": "both",
    "console": {"level": "WARNING"},
    "file": {"level": "DEBUG", "log_dir": "/var/log/myapp"},
})
```

## Troubleshooting

### Logs not appearing

**Console level too high**: Default prod preset shows only WARNING+.

```python
# Fix: Use dev preset or lower console level
log = LogManager(preset="dev")
# or
log = LogManager(config={"console": {"level": "DEBUG"}})
```

### TRACE logs not showing

TRACE is below DEBUG. Ensure the level is explicitly set:

```python
log = LogManager(config={"console": {"level": "TRACE"}})
```

### File logs not created

Check output mode and file configuration:

```python
log = LogManager(config={
    "output": "both",  # or "file"
    "file": {
        "log_path": "./",
        "log_dir": "logs",
        "log_name": "app.log",
    }
})
```

### Icons not rendering

Terminal may not support Unicode. Disable icons:

```python
log = LogManager(config={"icons": {"show": False}})
```

### Async methods deadlocking

Use `ainfo()`, `aerror()`, etc. in async contexts:

```python
# Wrong - may block event loop
async def handler():
    log.info("Blocking call")  # Sync method in async context

# Correct
async def handler():
    await log.ainfo("Non-blocking call")
```

## API Reference

Full autodoc: {doc}`../../api/logging`

| Class/Method | Description |
| - | - |
| `LogManager(preset=..., config=...)` | Main logger class |
| `.trace()`, `.debug()`, `.info()`, etc. | Sync logging methods |
| `.atrace()`, `.adebug()`, `.ainfo()`, etc. | Async logging methods |
| `.success()` | SUCCESS level (25) - between INFO and WARNING |
| `TRACE_LEVEL` | Constant for TRACE level (5) |
