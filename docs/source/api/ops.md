# Session Management (Ops)

Unified, config-driven session management for tmux and containers (Docker/Podman).

`kstlib.ops` wraps tmux and Docker/Podman behind a single API to **start, stop, attach,
monitor, and collect logs** from persistent processes. All session definitions live in
`kstlib.conf.yml`, making the config file the single source of truth.

**Container interoperability**: the `list`, `status`, `logs`, `attach`, and `stop` commands
work with **any** container running on the host, not only those created by kstlib.
The `start` command creates new containers from an image definition.

```{tip}
Pair this reference with {doc}`../features/ops/index` for the feature guide.
```

## Quick overview

- `SessionManager` is the main facade for session lifecycle management
- `TmuxRunner` provides direct tmux session control
- `ContainerRunner` provides direct Podman/Docker container control
- `SessionConfig` and `SessionStatus` are the core data models
- Configuration follows the standard priority chain: constructor args > `kstlib.conf.yml` > defaults

## Configuration cascade

The module consults the loaded config for session definitions:

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

    astro-prod:
      backend: container
      image: "astro-bot:latest"
      volumes:
        - "./data:/app/data"
```

Load a session from config:

```python
from kstlib.ops import SessionManager

session = SessionManager.from_config("astro")
```

```{note}
Sessions defined in config are visible in ``kstlib ops list`` with state
``DEFINED`` even before they are started. The ``container_runtime`` field
accepts ``null`` for auto-detection (checks podman first, then docker).
CLI arguments override config values when both are provided.
```

## Usage patterns

### Basic tmux session

```python
from kstlib.ops import SessionManager

session = SessionManager("dev", backend="tmux")
session.start("python app.py")
session.attach()  # Ctrl+B D to detach
session.stop()
```

### Container with volumes

```python
from kstlib.ops import SessionManager

session = SessionManager(
    "prod",
    backend="container",
    image="app:latest",
    volumes=["./data:/app/data"],
    log_volume="./logs:/app/logs",
)
session.start()
```

### Session lifecycle

```python
from kstlib.ops import SessionManager

session = SessionManager.from_config("astro")

# Check state
if session.exists():
    status = session.status()
    print(f"State: {status.state.value}, PID: {status.pid}")

# Logs
logs = session.logs(lines=100)

# Running check
if session.is_running():
    session.stop(graceful=True, timeout=10)
```

### Low-level runner access

```python
from kstlib.ops import TmuxRunner, ContainerRunner, SessionConfig, BackendType

# Direct tmux
tmux = TmuxRunner()
config = SessionConfig(name="test", backend=BackendType.TMUX, command="bash")
tmux.start(config)
tmux.send_keys("test", "echo hello")
tmux.stop("test")

# Direct container
container = ContainerRunner(runtime="podman")
config = SessionConfig(
    name="test",
    backend=BackendType.CONTAINER,
    image="python:3.10-slim",
)
container.start(config)
container.exec("test", "pip list")
container.stop("test")
```

## Module reference

```{eval-rst}
.. automodule:: kstlib.ops
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```

## Exceptions

```{eval-rst}
.. automodule:: kstlib.ops.exceptions
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```

## Models

```{eval-rst}
.. automodule:: kstlib.ops.models
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```

## TmuxRunner

```{eval-rst}
.. automodule:: kstlib.ops.tmux
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```

## ContainerRunner

```{eval-rst}
.. automodule:: kstlib.ops.container
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```

## SessionManager

```{eval-rst}
.. automodule:: kstlib.ops.manager
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```
