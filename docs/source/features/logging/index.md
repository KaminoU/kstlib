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

### Isolated vs registered instances

`LogManager` has two modes controlled by the `register` constructor flag:

```python
# Isolated (default): safe for local use and tests. Does NOT touch
# logging.getLogger("kstlib"), so you can have many LogManager objects
# side by side without interfering with each other.
log = LogManager(preset="dev")

# Registered: bootstraps this instance as the global root of the
# "kstlib" logger hierarchy. logging.getLogger("kstlib") returns the
# same object, and "kstlib.*" child loggers propagate records to it.
log = LogManager(preset="dev", register=True)
```

| Mode | `logging.getLogger("kstlib")` | `.trace` / `.success` on child loggers | Typical use |
| - | - | - | - |
| `register=False` (default) | Standard `logging.Logger` | Not patched | Tests, local scripts, multiple isolated instances |
| `register=True` | This `LogManager` instance | Patched on the base class | Application bootstrap, host-wide logging |

`init_logging()` is a thin backward-compatible alias. These two calls are
equivalent:

```python
from kstlib.logging import LogManager, init_logging

# Preferred: explicit register flag
root = LogManager(preset="dev", register=True)

# Legacy alias (kept for backward compatibility)
root = init_logging(preset="dev")
```

### Internal logging activation

By default, libraries that import kstlib (`kstlib.mail`, `kstlib.rapi`,
`kstlib.auth`, ...) stay silent: no log records are emitted unless the
application explicitly calls `init_logging()`. This is the right default
for libraries - the host app should decide when to turn logging on.

If you embed kstlib inside a larger application and want its internal
logs to appear without writing any Python, flip the opt-in switch in
`kstlib.conf.yml`:

```yaml
kstlib:
  logging:
    enabled: true   # turn on internal kstlib logs
    preset: dev     # dev | prod | debug | trace | <custom preset>
```

The first call to `get_logger()` from any kstlib module reads this
section and triggers `LogManager(preset=..., register=True)`
transparently. Later calls are no-ops - the root logger is a singleton.
The auto-init path is wrapped in a broad `try/except` so a missing,
unreadable, or invalid config file can NEVER break the host application.
At worst you get the default Python logging behavior (silent).

If the requested preset does not exist (typo, custom preset removed,
etc.), kstlib falls back to `prod` and writes a single one-line notice
to `stderr`. The notice is emitted at most once per process even when
`get_logger()` is called many times with the same broken config:

```text
kstlib logging: preset 'foobar' not found, available: ['debug', 'dev', 'prod', 'trace'], falling back to 'prod'.
```

| Configuration state | Behavior |
| - | - |
| Section missing or `enabled: false` | Silent. No auto-init, no stderr output. |
| `enabled: true`, valid preset | Auto-init with the requested preset. |
| `enabled: true`, preset missing | Auto-init with `prod` as the default. |
| `enabled: true`, preset unknown | One-shot stderr notice + fallback to `prod`. |
| Config file unreadable or parse error | Silent fallback. No exception escapes. |

Explicit `LogManager(register=True)` or `init_logging(preset=...)` calls
from application code still take precedence over the config-driven path.

```{tip}
In production, you usually want `enabled: true` + `preset: prod` so
that kstlib's errors and warnings reach your log pipeline. For local
development, `preset: dev` gives you a colorful console with DEBUG
level and full tracebacks.
```

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
      stream: stdout  # stdout (default) | stderr
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

### Console stream: stdout vs stderr

By default the console handler writes to **stdout**. Set `console.stream` to
`stderr` to route log output to standard error instead:

```python
log = LogManager(config={"console": {"stream": "stderr"}})
```

```yaml
logger:
  defaults:
    console:
      stream: stderr  # stdout (default) | stderr
```

**When to use `stderr`.** A CLI that emits machine-readable data on stdout
(JSON, CSV, a raw payload meant to be piped) is corrupted when log lines land
on the same stream. Routing the console to stderr preserves the Unix separation
between **data** (stdout) and **diagnostics** (stderr), so `mycli export | jq .`
stays clean while logs stay visible in the terminal.

The default (`stdout`) is unchanged and backward compatible. An invalid value
raises `ConfigError` at startup rather than silently falling back to stdout,
which would otherwise re-introduce the stream corruption you are trying to avoid.

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
| `LogManager(preset=..., config=..., register=False)` | Main logger class. `register=True` installs it as the global kstlib root. |
| `init_logging(preset=..., config=...)` | Backward-compatible alias of `LogManager(register=True)`. |
| `.trace()`, `.debug()`, `.info()`, etc. | Sync logging methods |
| `.atrace()`, `.adebug()`, `.ainfo()`, etc. | Async logging methods |
| `.success()` | SUCCESS level (25) - between INFO and WARNING |
| `TRACE_LEVEL` | Constant for TRACE level (5) |

## See also

- {doc}`introspection-guide` - 7-level convention, `kstlib.logging.modules`
  cascade, presets, recipes, `HTTPTraceLogger`
- {doc}`../../security/user-responsibility` - which fields users must
  vet themselves before they reach a log line

```{toctree}
:hidden:
:maxdepth: 1

introspection-guide
```
