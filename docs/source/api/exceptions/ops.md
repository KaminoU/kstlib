# Ops Exceptions

Exception hierarchy for the ops (session management) subsystem.

## Exception Hierarchy

```
KstlibError
└── OpsError
    ├── BackendNotFoundError
    │   ├── TmuxNotFoundError
    │   └── ContainerRuntimeNotFoundError
    └── SessionError
        ├── SessionExistsError
        ├── SessionNotFoundError
        ├── SessionStartError
        ├── SessionAttachError
        ├── SessionStopError
        └── SessionAmbiguousError
```

## Base Exception

```{eval-rst}
.. autoexception:: kstlib.ops.exceptions.OpsError
   :members:
   :show-inheritance:
```

## Backend Not Found Errors

```{eval-rst}
.. autoexception:: kstlib.ops.exceptions.BackendNotFoundError
   :members:
   :show-inheritance:
```

```{eval-rst}
.. autoexception:: kstlib.ops.exceptions.TmuxNotFoundError
   :members:
   :show-inheritance:
```

```{eval-rst}
.. autoexception:: kstlib.ops.exceptions.ContainerRuntimeNotFoundError
   :members:
   :show-inheritance:
```

Raised when the required backend binary is not installed or not in PATH.

## Session Errors

```{eval-rst}
.. autoexception:: kstlib.ops.exceptions.SessionError
   :members:
   :show-inheritance:
```

```{eval-rst}
.. autoexception:: kstlib.ops.exceptions.SessionExistsError
   :members:
   :show-inheritance:
```

```{eval-rst}
.. autoexception:: kstlib.ops.exceptions.SessionNotFoundError
   :members:
   :show-inheritance:
```

```{eval-rst}
.. autoexception:: kstlib.ops.exceptions.SessionStartError
   :members:
   :show-inheritance:
```

```{eval-rst}
.. autoexception:: kstlib.ops.exceptions.SessionAttachError
   :members:
   :show-inheritance:
```

```{eval-rst}
.. autoexception:: kstlib.ops.exceptions.SessionStopError
   :members:
   :show-inheritance:
```

```{eval-rst}
.. autoexception:: kstlib.ops.exceptions.SessionAmbiguousError
   :members:
   :show-inheritance:
```

Raised when auto-detection finds a session in both tmux and container backends.
Use ``--backend`` to disambiguate.

## Usage Examples

```python
from kstlib.ops.exceptions import (
    OpsError,
    SessionExistsError,
    SessionNotFoundError,
    TmuxNotFoundError,
    ContainerRuntimeNotFoundError,
    SessionAmbiguousError,
)

try:
    session.start("python app.py")
except TmuxNotFoundError:
    print("Install tmux: apt install tmux")
except ContainerRuntimeNotFoundError:
    print("Install podman or docker")
except SessionExistsError:
    print("Session already running, stop it first")
except SessionAmbiguousError as e:
    print(f"Found in {e.backends}, use --backend to specify")
except OpsError as e:
    print(f"Ops error: {e}")
```
