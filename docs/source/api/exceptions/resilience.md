# Resilience Exceptions

Exceptions for the resilience module: circuit breaker, graceful shutdown, and heartbeat.

## Exception hierarchy

```
RuntimeError
├── CircuitBreakerError
│   └── CircuitOpenError      # Circuit is open, call blocked
├── HeartbeatError            # Heartbeat file write/read failure
└── ShutdownError             # Shutdown callback failure
```

## Common failure modes

- `CircuitOpenError` is raised when calling through an open circuit. Contains `remaining_seconds` until half-open transition.
- `HeartbeatError` surfaces when the state file cannot be written (permissions, disk full) or read (corrupted JSON).
- `ShutdownError` may be raised if a cleanup callback fails catastrophically (though errors are normally caught).

## Usage patterns

### Handling circuit breaker fast-fail

```python
from kstlib.resilience import CircuitBreaker, CircuitOpenError

cb = CircuitBreaker(max_failures=3, reset_timeout=30)

try:
    result = cb.call(fetch_data, symbol="BTC/USDT")
except CircuitOpenError as e:
    # Circuit is open - use fallback
    logger.warning(f"Circuit open, retry in {e.remaining_seconds:.1f}s")
    result = get_cached_fallback()
```

### Monitoring heartbeat failures

```python
from kstlib.resilience import Heartbeat, HeartbeatError

def on_missed_beat(error: Exception) -> None:
    logger.error(f"Heartbeat write failed: {error}")
    alerting.notify("Heartbeat failure detected")

heartbeat = Heartbeat(
    state_file="/tmp/bot.heartbeat",
    interval=10,
    on_missed_beat=on_missed_beat,
)
```

## API reference

```{eval-rst}
.. automodule:: kstlib.resilience.exceptions
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```
