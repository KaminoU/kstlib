# Performance

Optimization patterns used in kstlib to minimize startup time and memory footprint.

## Lazy Loading

kstlib uses lazy loading to defer expensive imports until they're actually needed.
This significantly reduces startup time when only a subset of features is used.

### PEP 562: Module-Level `__getattr__`

`kstlib/__init__.py` uses PEP 562 lazy loading:

```python
# All symbols loaded on-demand via __getattr__
import kstlib  # ~6ms (was ~280ms)

# Modules loaded only when accessed
kstlib.mail       # Loads mail module
kstlib.ConfigLoader  # Loads config module
```

#### Import time improvement: 280ms → 6ms (98% faster)

**Rich traceback is now opt-in** (saves ~100ms):

```python
# Explicit activation
import kstlib
kstlib.install_rich_traceback()

# Or via environment variable
# KSTLIB_TRACEBACK=1 python script.py
```

### The `@lazy_factory` Decorator

Located in `kstlib.utils.lazy`, this decorator wraps factory functions to defer
class imports until the factory is called:

```python
from kstlib.utils import lazy_factory

@lazy_factory("kstlib.secrets.providers.sops", "SOPSProvider")
def _sops_factory(**kwargs) -> SecretProvider:
    ...  # Body replaced by decorator
```

**How it works:**

1. At module load time, only the decorator is evaluated (no import)
2. When `_sops_factory()` is called, the module is imported via `importlib`
3. The class is instantiated with the provided kwargs
4. Subsequent calls reuse the already-imported module (Python caches imports)

### Metrics: Secret Providers

Before lazy loading, all 4 providers were imported at module load:

| Module | Before | After | Reduction |
| - | - | - | - |
| `secrets.providers` | 109ms | 31ms | **-72%** |
| `providers.keyring` | 83ms | 0ms (lazy) | **-100%** |
| `providers.sops` | 1ms | 0ms (lazy) | **-100%** |
| `providers.environment` | 1ms | 0ms (lazy) | **-100%** |
| `providers.kwargs` | 1ms | 0ms (lazy) | **-100%** |

The `keyring` provider was the main culprit (83ms) due to its heavy dependency chain.

### Current Import Profile

Measured with `python -X importtime -c "import kstlib"`:

| Module | Cumulative (ms) | Notes |
| - | - | - |
| `kstlib.mail` | 93 | Builder imports config chain |
| `kstlib.cli` | 77 | Typer + Rich dependencies |
| `kstlib.config` | 62 | YAML/TOML parsers |
| `kstlib.secrets` | 32 | Lazy-loaded providers |
| `kstlib.logging` | 5 | Lightweight |
| `kstlib.cache` | 4 | Lightweight |

### How to Measure

```bash
# Full import profile (sorted by cumulative time)
python -X importtime -c "import kstlib" 2>&1 | sort -t'|' -k2 -rn | head -20

# Specific module
python -X importtime -c "from kstlib.secrets import resolve_secret" 2>&1 | grep kstlib
```

### Lazy Loading Patterns

kstlib uses three **distinct** patterns for deferring imports. Each solves a different problem:

| Pattern | What it defers | Use case |
| ------- | -------------- | -------- |
| PEP 562 `__getattr__` | Module loading at package level | `kstlib/__init__.py` |
| `@lazy_factory` | Class import + instantiation | Plugin/provider factories |
| Local imports | Import inside function body | Utility functions |
| `TYPE_CHECKING` | Type hints without runtime import | Function signatures |

#### Pattern 1: PEP 562 (Package-level lazy modules)

Used in `kstlib/__init__.py` to defer submodule loading:

```python
# In __init__.py
def __getattr__(name: str) -> Any:
    if name == "mail":
        return importlib.import_module("kstlib.mail")  # Loaded only when accessed
    raise AttributeError(...)
```

```python
import kstlib      # ~6ms - mail not loaded yet
kstlib.mail        # NOW mail is loaded (~93ms)
```

#### Pattern 2: `@lazy_factory` (Class instantiation)

For factory functions that create instances of heavy classes:

```python
from kstlib.utils import lazy_factory

@lazy_factory("kstlib.secrets.providers.sops", "SOPSProvider")
def get_sops_provider(**kwargs) -> SecretProvider:
    ...  # Body is REPLACED by decorator - never executed
```

The decorator handles `importlib.import_module()` + `getattr()` + instantiation.

#### Pattern 3: Local imports (Function-level)

For functions that need a class internally:

```python
from __future__ import annotations

def decrypt_file(path: Path) -> str:
    from kstlib.secrets.providers.sops import SOPSProvider  # Deferred import
    return SOPSProvider().decrypt(path)
```

#### Pattern 4: TYPE_CHECKING (Type hints only)

For type annotations without runtime import:

```python
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from heavy_module import HeavyClass  # Only imported by type checkers

def process(obj: HeavyClass) -> None:  # Works without runtime import
    ...
```

### Guidelines

When adding new modules:

1. **Avoid top-level imports** of heavy dependencies (keyring, cryptography, etc.)
2. **Use PEP 562 `__getattr__`** in `__init__.py` for lazy submodules
3. **Use `@lazy_factory`** for plugin/provider patterns
4. **Use local imports** for one-off heavy class usage in functions
5. **Use `TYPE_CHECKING`** when you only need the type for annotations
6. **Use `from __future__ import annotations`** to enable forward references without quotes
   (becomes default in Python 3.14+, see [PEP 563](https://peps.python.org/pep-0563/))
7. **Measure before/after** with `python -X importtime`
