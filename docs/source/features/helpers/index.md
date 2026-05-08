# Helpers

Time-based utilities for periodic operations: detect modulo-aligned boundaries (every 4 hours from midnight, every 15 minutes from the hour, ...) without writing scheduling boilerplate. Designed for trading automation, scheduled restarts, and long-running loops where alignment to wall-clock boundaries matters more than fixed intervals.

```{tip}
For the API reference of the underlying classes (`TimeTrigger`, `TimeTriggerError`, `InvalidModuloError`),
see {doc}`../../api/helpers`.
```

## TL;DR

```python
from kstlib.helpers import TimeTrigger

# Trigger at 4-hour boundaries: 00:00, 04:00, 08:00, 12:00, 16:00, 20:00
trigger = TimeTrigger("4h")

if trigger.is_at_boundary():
    rotate_log_files()

# Margin-based: trigger 60s before the boundary so a long task finishes on time
if trigger.should_trigger(margin=60):
    restart_websocket()
    trigger.record_trigger()  # tracked in stats

# Look-ahead helpers
print(trigger.time_until_next())     # seconds until next 4h boundary
print(trigger.next_boundary_time())  # datetime of next 4h boundary
```

## Key Features

- **Modulo-aligned scheduling**: boundaries are anchored to wall-clock divisions, not to "N seconds from now".
- **Human-readable intervals**: `"4h"`, `"15m"`, `"1d"`, `"30s"`, or a raw integer in seconds.
- **Margin support**: trigger a configurable number of seconds before the boundary (early-fire) for tasks that need lead time.
- **Statistics tracking**: `record_trigger()` accumulates counts and timestamps so you can audit how often a boundary actually fired.
- **Context manager**: `with TimeTrigger("1h") as trigger:` cleans up internal state for short-lived loops.

## Common patterns

### Scheduled WebSocket restart

```python
import asyncio
from kstlib.helpers import TimeTrigger
from kstlib.websocket import WebSocketManager

trigger = TimeTrigger("8h")

async def maybe_restart(ws: WebSocketManager) -> None:
    """Restart WebSocket at 8-hour boundaries for stability."""
    if trigger.should_trigger(margin=30):
        await ws.shutdown()
        await ws.connect()
        trigger.record_trigger()
```

### Trading candle close detection

```python
from kstlib.helpers import TimeTrigger

candle_15m = TimeTrigger("15m")

while running:
    if candle_15m.is_at_boundary():
        process_15m_candle_close()
        candle_15m.record_trigger()
    await asyncio.sleep(1)
```

## Interval formats

| Format | Meaning |
|--------|---------|
| `"30s"` | 30 seconds |
| `"15m"` | 15 minutes |
| `"4h"`  | 4 hours |
| `"1d"`  | 1 day (24 hours) |
| `3600`  | 3600 seconds (raw int) |
