# Resilience Utilities

Public API for fault tolerance patterns: circuit breaker, rate limiter, graceful shutdown, heartbeat monitoring, and watchdog.
These components help build robust services that handle failures gracefully and support clean termination.

```{tip}
Pair this reference with {doc}`../features/resilience/index` for the feature guide.
```

## Quick overview

- `CircuitBreaker` implements the circuit breaker pattern to prevent cascading failures
- `RateLimiter` provides token bucket rate limiting for request throttling
- `GracefulShutdown` manages prioritized cleanup callbacks on process termination
- `Heartbeat` provides file-based liveness signaling for external monitoring
- `Watchdog` detects thread/process freezes with configurable timeout callbacks
- All components support both sync and async usage patterns
- Configuration follows the standard priority chain: constructor args > `kstlib.conf.yml` > defaults

## Configuration cascade

The module consults the loaded config for default values. A minimal config block:

```yaml
resilience:
  circuit_breaker:
    max_failures: 5
    reset_timeout: 60
  shutdown:
    default_timeout: 30
  heartbeat:
    interval: 10
  watchdog:
    timeout: 30
```

Override any of these per instance:

```python
from kstlib.resilience import CircuitBreaker

cb = CircuitBreaker(max_failures=3, reset_timeout=10)
```

## Usage patterns

### Circuit breaker for external APIs

```python
from kstlib.resilience import CircuitBreaker, CircuitOpenError

cb = CircuitBreaker(max_failures=3, reset_timeout=30)

try:
    result = cb.call(api.fetch, endpoint="/data")
except CircuitOpenError:
    result = fallback_value
```

### Async circuit breaker

```python
result = await cb.acall(async_api.fetch, symbol="BTC/USDT")
```

### Rate limiter for API throttling

```python
from kstlib.resilience import RateLimiter, rate_limiter

# Direct usage
limiter = RateLimiter(rate=10, per=1.0)
limiter.acquire()  # Blocks until token available
call_api()

# As decorator
@rate_limiter(rate=100, per=60.0)  # 100 per minute
def call_service(data: dict) -> dict:
    return api.post(data)
```

### Decorator syntax

```python
from kstlib.resilience import circuit_breaker

@circuit_breaker(max_failures=3)
def call_service(data: dict) -> dict:
    return external_api.post(data)
```

### Graceful shutdown with priorities

```python
from kstlib.resilience import GracefulShutdown

shutdown = GracefulShutdown()
shutdown.register("save", save_state, priority=10)
shutdown.register("close", close_db, priority=20)
shutdown.install()  # Handle SIGTERM/SIGINT
```

### Heartbeat monitoring

```python
from kstlib.resilience import Heartbeat

heartbeat = Heartbeat(
    state_file="/tmp/app.heartbeat",
    interval=10,
    metadata={"version": "1.0"}
)
heartbeat.start()
```

### Watchdog for freeze detection

```python
from kstlib.resilience import Watchdog

def on_freeze():
    print("Thread appears frozen!")

with Watchdog(timeout=30, on_timeout=on_freeze) as wd:
    for item in work_queue:
        wd.ping()  # Must call before timeout
        process(item)
```

## Module reference

```{eval-rst}
.. automodule:: kstlib.resilience
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```

## Exceptions

```{eval-rst}
.. automodule:: kstlib.resilience.exceptions
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```
