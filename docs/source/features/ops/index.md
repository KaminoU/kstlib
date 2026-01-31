# Ops

Unified, config-driven session management for tmux and containers (Docker/Podman).

`kstlib.ops` provides a single API to **start, stop, attach, monitor, and collect logs**
from both tmux sessions and Docker/Podman containers. All session definitions live in
`kstlib.conf.yml`, making the config file the single source of truth.

## What it does

| Capability | tmux | Docker / Podman |
|------------|------|-----------------|
| **Start** a new session | `tmux new-session` | `docker run` / `podman run` |
| **Stop** a session | `tmux kill-session` | `docker stop` / `podman stop` |
| **Attach** (interactive) | `tmux attach` (Ctrl+B D) | `docker attach` (Ctrl+P Ctrl+Q) |
| **Status** | Session state + PID | Container state + image |
| **Logs** | `tmux capture-pane` | `docker logs` / `podman logs` |
| **List** all sessions | All tmux + all containers + config-defined |

**Container interoperability**: `kstlib ops` detects and manages **all** running containers
on the host, not just those created by kstlib. You can `attach`, `logs`, `status`, and `stop`
any existing Docker/Podman container. The `start` command creates new containers from an image.

## TL;DR

```python
from kstlib.ops import SessionManager

# Local dev with tmux
session = SessionManager("dev", backend="tmux")
session.start("python -m app.bot")
session.attach()  # tmux attach-session -t dev (Ctrl+B D to detach)

# Production with Podman/Docker
session = SessionManager(
    "prod",
    backend="container",
    image="bot:latest",
    volumes=["./data:/app/data"],
)
session.start()
session.attach()  # podman attach prod (Ctrl+P Ctrl+Q to detach)

# Config-driven (from kstlib.conf.yml)
session = SessionManager.from_config("astro")
session.start()
```

## Key Features

- **Unified API**: Same interface for tmux sessions and Docker/Podman containers
- **Config-Driven**: Session definitions in `kstlib.conf.yml` with `DEFINED` state visibility
- **Container Interop**: Detects and manages all containers on the host (not just kstlib-created)
- **Pseudo-Terminal Support**: Full TUI/Rich/Textual support with `attach()`
- **Log Persistence**: Container logs available even after crash (via volume mounts)
- **CLI Integration**: `kstlib ops start|stop|attach|status|logs|list`
- **Deep Defense**: All config values validated (session names, commands, images, volumes, ports)

## Quick Start

### Backend Selection

Choose the appropriate backend for your environment:

| Backend | Use Case | Attach/Detach |
|---------|----------|---------------|
| `tmux` | Dev, backtesting | Ctrl+B D |
| `container` | Production | Ctrl+P Ctrl+Q |

### Using tmux Backend (Development)

```python
from kstlib.ops import SessionManager

# Create and start
session = SessionManager("bot", backend="tmux")
session.start("python -m trading.bot")

# Check status
status = session.status()
print(f"{status.name}: {status.state.value}")  # bot: running

# Get logs
logs = session.logs(lines=50)
print(logs)

# Attach (replaces current process)
session.attach()  # Ctrl+B D to detach

# Stop
session.stop()
```

### Using Container Backend (Production)

```python
from kstlib.ops import SessionManager

# Create with container options
session = SessionManager(
    "astro-prod",
    backend="container",
    image="astro-bot:latest",
    volumes=["./data:/app/data"],
    log_volume="./logs:/app/logs",  # Persist logs for post-mortem
    ports=["8081:8080"],  # Prometheus metrics
    env={"ASTRO_ENV": "production"},
)

# Start container
session.start()

# Check status
status = session.status()
print(f"PID: {status.pid}, Image: {status.image}")

# Attach (Ctrl+P Ctrl+Q to detach)
session.attach()

# Stop gracefully (SIGTERM, then SIGKILL after timeout)
session.stop(graceful=True, timeout=10)
```

### Config-Driven Usage

Define sessions in `kstlib.conf.yml`:

```yaml
ops:
  default_backend: tmux
  tmux_binary: tmux
  container_runtime: null  # auto-detect (podman or docker)

  sessions:
    astro:
      backend: tmux
      command: "python -m astro.bot"
      working_dir: "/opt/astro"
      env:
        ASTRO_ENV: "development"

    astro-prod:
      backend: container
      image: "astro-bot:latest"
      volumes:
        - "./data:/app/data"
      log_volume: "./logs/astro:/app/logs"
      env:
        ASTRO_ENV: "production"
```

Then use:

```python
from kstlib.ops import SessionManager

# Backend and options loaded from config
session = SessionManager.from_config("astro")
session.start()
```

### Session Lifecycle (DEFINED State)

Sessions defined in `kstlib.conf.yml` are **always visible** in `kstlib ops list`,
even before they are started. This makes the config file the single source of truth:

```
  kstlib.conf.yml        kstlib ops start       kstlib ops stop
  ┌──────────┐           ┌──────────┐           ┌──────────┐
  │ DEFINED  │  ──────►  │ RUNNING  │  ──────►  │ DEFINED  │
  │ (config) │           │ (active) │           │ (config) │
  └──────────┘           └──────────┘           └──────────┘
```

The `defined` state means "exists in config but not yet started". It appears dimmed
in the CLI output to distinguish from active sessions:

```bash
$ kstlib ops list
  Name          Backend    State      PID
  astro         tmux       defined    -
  astro-prod    container  defined    -

$ kstlib ops start astro
$ kstlib ops list
  Name          Backend    State      PID
  astro         tmux       running    12345
  astro-prod    container  defined    -
```

The `kstlib ops status` command also supports the `defined` state for config-only
sessions, showing the configured backend and image without requiring a running process.

### Runtime Auto-Detect

Set `container_runtime: null` (or omit the key) to let kstlib auto-detect
the container runtime:

1. Checks for `podman` in PATH
2. Falls back to `docker` in PATH
3. Raises `ContainerRuntimeNotFoundError` if neither is found

```yaml
ops:
  container_runtime: null  # auto-detect
```

This ensures configs are portable across machines with different runtimes installed.

### CLI Overrides on Config Sessions

Config values serve as defaults. CLI arguments override them when needed:

```bash
# Start with all options from config
kstlib ops start astro-prod

# Override the image
kstlib ops start astro-prod --image astro-bot:v2

# Override the backend (turns a tmux session into a container)
kstlib ops start astro --backend container --image astro-bot
```

The override priority chain is: **CLI arguments > kstlib.conf.yml > defaults**.

## CLI Commands

```bash
# Start a session
kstlib ops start dev --backend tmux --command "python app.py"
kstlib ops start prod --backend container --image app:latest

# Session from config (recommended)
kstlib ops start astro

# Stop
kstlib ops stop dev
kstlib ops stop prod --force

# Attach
kstlib ops attach dev

# Status (works for running and config-defined sessions)
kstlib ops status dev
kstlib ops status prod --json

# Logs
kstlib ops logs dev --lines 50

# List all sessions (running + config-defined)
kstlib ops list
kstlib ops list --backend container --json
```

## Exception Handling

```python
from kstlib.ops import SessionManager
from kstlib.ops.exceptions import (
    SessionExistsError,
    SessionNotFoundError,
    TmuxNotFoundError,
    ContainerRuntimeNotFoundError,
)

try:
    session = SessionManager("bot", backend="tmux")
    session.start("python app.py")
except TmuxNotFoundError:
    print("tmux not installed - install with: apt install tmux")
except SessionExistsError:
    print("Session already exists - use stop first")
except SessionNotFoundError:
    print("Session not found")
```

## Low-Level Runners

For direct backend access without SessionManager:

```python
from kstlib.ops import TmuxRunner, ContainerRunner, SessionConfig, BackendType

# Direct tmux usage
tmux = TmuxRunner()
config = SessionConfig(
    name="direct-test",
    backend=BackendType.TMUX,
    command="python app.py",
)
status = tmux.start(config)
sessions = tmux.list_sessions()
tmux.stop("direct-test")

# Direct container usage
container = ContainerRunner(runtime="podman")
config = SessionConfig(
    name="container-test",
    backend=BackendType.CONTAINER,
    image="python:3.10-slim",
    command="python -c 'import time; time.sleep(3600)'",
)
status = container.start(config)
container.stop("container-test")
```

## See Also

- [API Reference](../../api/ops.md) for complete API documentation
- [Configuration](../config/index.md) for configuration loading
