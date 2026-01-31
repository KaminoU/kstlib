# Helpers Exceptions

The helpers module provides time-based utilities for periodic operations like candle close detection and scheduled restarts.
These exceptions indicate invalid interval specifications passed to `TimeTrigger`.

## Exception hierarchy

```
TimeTriggerError (base)
└── InvalidModuloError
```

## Common failure modes

- `InvalidModuloError` is raised when a modulo string like `"4h"` or `"15m"` is malformed or out of valid bounds.
- Typical causes: typos in interval units (`"4hours"` instead of `"4h"`), zero intervals (`"0m"`), or negative values.

## Usage patterns

### Validating interval strings

```python
from kstlib.helpers import TimeTrigger
from kstlib.helpers.exceptions import InvalidModuloError

try:
    trigger = TimeTrigger("4h")
except InvalidModuloError as error:
    raise ValueError(f"Invalid interval: {error}") from error
```

### Safe trigger initialization

```python
from kstlib.helpers import TimeTrigger
from kstlib.helpers.exceptions import TimeTriggerError

def create_restart_trigger(interval: str) -> TimeTrigger:
    """Create a trigger with validation."""
    try:
        return TimeTrigger(interval)
    except TimeTriggerError:
        # Fall back to safe default
        return TimeTrigger("1h")
```

## Module reference

```{eval-rst}
.. automodule:: kstlib.helpers.exceptions
    :members:
    :undoc-members:
    :show-inheritance:
```
