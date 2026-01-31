# Helpers

Time-based utilities for periodic operations, particularly useful for trading automation and scheduled tasks.

```{tip}
The `TimeTrigger` class is designed for modulo-based scheduling (e.g., "every 4 hours aligned to midnight")
rather than interval-based scheduling (e.g., "every 4 hours from now").
```

## Quick overview

- **TimeTrigger**: Detect time boundaries for periodic operations (candle closes, scheduled restarts)
- Supports human-readable intervals: `"4h"`, `"15m"`, `"1d"`
- Configurable margin for early triggering
- Statistics tracking for trigger events

## Usage patterns

### Basic boundary detection

```python
from kstlib.helpers import TimeTrigger

# Trigger at 4-hour boundaries (00:00, 04:00, 08:00, ...)
trigger = TimeTrigger("4h")

if trigger.is_at_boundary():
    print("We are at a 4-hour mark!")

# Check with margin (trigger 60s before boundary)
if trigger.should_trigger(margin=60):
    restart_connection()
```

### Time calculations

```python
from kstlib.helpers import TimeTrigger

trigger = TimeTrigger("15m")

# Seconds until next boundary
wait_time = trigger.time_until_next()
print(f"Next 15-minute mark in {wait_time:.0f} seconds")

# Get the next boundary as datetime
next_boundary = trigger.next_boundary_time()
print(f"Next boundary at {next_boundary}")
```

### WebSocket restart scheduling

```python
from kstlib.helpers import TimeTrigger
from kstlib.websocket import WebSocketManager

trigger = TimeTrigger("8h")

async def maybe_restart(ws: WebSocketManager) -> None:
    """Restart WebSocket at 8-hour boundaries for stability."""
    if trigger.should_trigger(margin=30):
        await ws.shutdown()
        await ws.connect()
        trigger.record_trigger()  # Track for statistics
```

### Context manager for timed operations

```python
from kstlib.helpers import TimeTrigger

with TimeTrigger("1h") as trigger:
    while True:
        if trigger.should_trigger():
            perform_hourly_task()
            trigger.record_trigger()
        await asyncio.sleep(1)
```

## Interval formats

| Format | Meaning |
|--------|---------|
| `"15m"` | 15 minutes |
| `"4h"` | 4 hours |
| `"1d"` | 1 day (24 hours) |
| `"30s"` | 30 seconds |
| `3600` | 3600 seconds (int) |

## Module reference

```{eval-rst}
.. automodule:: kstlib.helpers
    :members:
    :undoc-members:
    :show-inheritance:
    :no-index:
```
