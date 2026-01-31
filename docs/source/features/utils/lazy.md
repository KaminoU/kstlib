# Lazy Loading

The `@lazy_factory` decorator defers module imports until the decorated function is called, reducing startup time.

## Problem

Heavy dependencies slow down `import kstlib`:

```python
# Without lazy loading: keyring imported immediately (83ms)
from kstlib.secrets.providers.keyring import KeyringProvider

provider = KeyringProvider()  # Only needed here
```

## Solution

```python
from kstlib.utils import lazy_factory

@lazy_factory("kstlib.secrets.providers.keyring", "KeyringProvider")
def get_keyring_provider(**kwargs):
    ...  # Body replaced by decorator

# Module not imported yet (0ms)
provider = get_keyring_provider()  # Import happens here
```

## How It Works

1. At module load time, only the decorator is evaluated (no import)
2. When the factory is called, the module is imported via `importlib`
3. The class is instantiated with the provided kwargs
4. Subsequent calls reuse the already-imported module (Python caches imports)

## Usage

```python
from kstlib.utils import lazy_factory
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from heavy_module import HeavyClass

@lazy_factory("heavy_module", "HeavyClass")
def create_heavy_instance(**kwargs) -> "HeavyClass":
    ...  # Body is replaced by decorator

# Later, when needed:
instance = create_heavy_instance(param="value")
```

## Performance Impact

Before/after lazy loading for secret providers:

| Module | Before | After | Reduction |
| - | - | - | - |
| `secrets.providers` | 109ms | 31ms | **-72%** |
| `providers.keyring` | 83ms | 0ms (lazy) | **-100%** |
| `providers.sops` | 1ms | 0ms (lazy) | **-100%** |

## Measuring Import Time

```bash
# Full import profile
python -X importtime -c "import kstlib" 2>&1 | sort -t'|' -k2 -rn | head -20

# Specific module
python -X importtime -c "from kstlib.secrets import resolve_secret" 2>&1 | grep kstlib
```

## Best Practices

1. **Use for heavy dependencies**: keyring, cryptography, large frameworks
2. **Combine with TYPE_CHECKING**: Get type hints without runtime imports
3. **Measure before/after**: Verify the improvement with `python -X importtime`

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from heavy_module import HeavyClass  # Only for type checkers

@lazy_factory("heavy_module", "HeavyClass")
def get_heavy(**kwargs) -> "HeavyClass":
    ...
```

## API Reference

```python
def lazy_factory(module_path: str, class_name: str) -> Callable:
    """
    Decorator that defers class import until the factory is called.

    Args:
        module_path: Full module path (e.g., "kstlib.secrets.providers.sops")
        class_name: Class name to import from the module

    Returns:
        Decorated factory function that imports on first call
    """
```
