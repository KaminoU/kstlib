# Resilience

Fault tolerance patterns for robust services: circuit breaker, rate limiter, graceful shutdown, heartbeat monitoring, and watchdog.

## TL;DR

```python
import tempfile
from pathlib import Path
from kstlib.resilience import (
    CircuitBreaker, CircuitOpenError,
    RateLimiter, RateLimitExceededError,
    GracefulShutdown, Heartbeat, Watchdog
)

# Circuit breaker - prevent cascading failures
cb = CircuitBreaker(max_failures=3, reset_timeout=30)
try:
    result = cb.call(fetch_data, "BTC/USDT")  # calls fetch_data("BTC/USDT")
except CircuitOpenError:
    result = cached_fallback()  # Circuit open after 3 failures - use fallback

# Rate limiter - control request throughput
limiter = RateLimiter(rate=10, per=1.0)  # 10 requests per second
limiter.acquire()  # Blocks until token available
call_api()

# Graceful shutdown - clean process termination
shutdown = GracefulShutdown()
shutdown.register("database", db.close, priority=10)
shutdown.install()  # Handle SIGTERM/SIGINT

# Heartbeat - process liveness signaling (cross-platform path)
state_file = Path(tempfile.gettempdir()) / "bot.heartbeat"
heartbeat = Heartbeat(state_file=state_file, interval=10)
heartbeat.start()

# Watchdog - detect thread/process freezes
def on_freeze():
    print("Thread appears frozen!")
with Watchdog(timeout=30, on_timeout=on_freeze) as wd:
    while running:
        wd.ping()  # Reset timer periodically
        do_work()
```

## Key Features

- **Circuit Breaker**: Fail-fast pattern to prevent cascading failures
- **Rate Limiter**: Token bucket algorithm for request throttling
- **Graceful Shutdown**: Priority-based callback execution on termination signals
- **Heartbeat**: File-based liveness signaling for external monitors
- **Watchdog**: Detect thread/process freezes and hangs with timeout callbacks
- **Async Support**: All components work with both sync and async code
- **Configuration-driven**: Settings from `kstlib.conf.yml` with per-instance overrides

## Quick Start

### Circuit Breaker

Protect external service calls from cascading failures:

```python
from kstlib.resilience import CircuitBreaker, CircuitOpenError

cb = CircuitBreaker(max_failures=3, reset_timeout=30)

try:
    result = cb.call(api.fetch_data, symbol="BTC/USDT")
except CircuitOpenError:
    # Circuit is open - use fallback
    result = get_cached_data()
```

### Rate Limiter

Control request throughput with token bucket:

```python
from kstlib.resilience import RateLimiter, RateLimitExceededError

# 10 requests per second, allows burst up to 10
limiter = RateLimiter(rate=10, per=1.0)

# Blocking mode (default) - waits for token
limiter.acquire()
call_api()

# Non-blocking mode - returns False if no token
if limiter.try_acquire():
    call_api()
else:
    handle_rate_limit()
```

### Graceful Shutdown

Register cleanup callbacks with priorities:

```python
from kstlib.resilience import GracefulShutdown

shutdown = GracefulShutdown()

# Lower priority = runs first
shutdown.register("save_state", save_state, priority=10)
shutdown.register("close_connections", close_db, priority=20)
shutdown.register("flush_logs", logger.flush, priority=30)

# Install signal handlers (SIGTERM, SIGINT)
shutdown.install()
```

### Heartbeat

Signal process liveness to external monitors:

```python
from kstlib.resilience import Heartbeat

heartbeat = Heartbeat(
    state_file="/tmp/tradingbot.heartbeat",
    interval=10,
    metadata={"version": "1.0.0"}
)
heartbeat.start()

# External monitor can check:
state = Heartbeat.read_state("/tmp/tradingbot.heartbeat")
if state:
    from datetime import datetime, timezone
    ts = datetime.fromisoformat(state.timestamp)
    age = (datetime.now(tz=timezone.utc) - ts).total_seconds()
    if age > 30:
        alert("Process appears dead!")
```

### Watchdog

Detect thread/process freezes and hangs:

```python
from kstlib.resilience import Watchdog

def on_freeze():
    print("Worker thread appears frozen!")

# Start monitoring with 30-second timeout
with Watchdog(timeout=30, on_timeout=on_freeze) as wd:
    for item in work_queue:
        wd.ping()  # Reset timer before each work unit
        process(item)
```

## How It Works

### Circuit Breaker State Machine

The circuit breaker implements a finite state machine:

```text
         ┌────────┐      N failures    ┌────────┐
   ●───► │ CLOSED │ ─────────────────► │  OPEN  │◄─────┐
   start └────────┘                    └────────┘      │
              ▲                            │           │
              │                            │ timeout   │
              │ success                    ▼           │ failure
              │                       ┌──────────┐     │
              └────────────────────── │HALF-OPEN │─────┘
                                      └──────────┘
```

| State | Behavior |
| - | - |
| **CLOSED** | Circuit closed = current flows = requests pass through |
| **OPEN** | Circuit open = current cut = requests blocked (fast-fail) |
| **HALF-OPEN** | Test mode: 1 request allowed to check if service recovered |

### Rate Limiter Token Bucket

The rate limiter implements the token bucket algorithm:

```text
    Tokens refill at rate/per
           │
           ▼
    ┌─────────────┐
    │   BUCKET    │  max capacity = rate
    │  ○ ○ ○ ○ ○  │  (or custom burst)
    └──────┬──────┘
           │
           ▼ acquire() consumes 1 token
    ┌─────────────┐
    │   REQUEST   │  Allowed if token available
    └─────────────┘
```

| Parameter | Description |
| - | - |
| **rate** | Maximum tokens per period (e.g., 10 requests) |
| **per** | Period duration in seconds (e.g., 1.0 = per second) |
| **burst** | Initial/max tokens (defaults to rate) |

### Graceful Shutdown Flow

1. Signal received (SIGTERM/SIGINT) or `trigger()` called
2. Callbacks execute in priority order (lowest first)
3. Each callback has optional timeout
4. Errors are caught - all callbacks still run

### Heartbeat Mechanism

- Background thread writes JSON state file periodically
- State includes: timestamp, PID, hostname, custom metadata
- External monitors check file age for liveness

### Watchdog Mechanism

The watchdog monitors thread/process health by requiring periodic "pings":

```text
    Thread must call ping()
    before timeout expires
           │
           ▼
    ┌─────────────┐
    │  WATCHING   │ ◄──── ping() resets timer
    │   ○ ○ ○ ○   │
    └──────┬──────┘
           │ timeout expired
           ▼
    ┌─────────────┐
    │  TRIGGERED  │ ──── on_timeout callback invoked
    └─────────────┘
```

| Property | Description |
| - | - |
| **timeout** | Seconds of inactivity before triggering (clamped: 1-3600s) |
| **ping()** | Reset the watchdog timer (call periodically) |
| **on_timeout** | Callback invoked when timeout occurs (sync or async) |

## Configuration

### In kstlib.conf.yml

```yaml
resilience:
  circuit_breaker:
    max_failures: 5
    reset_timeout: 60
    half_open_max_calls: 3
  rate_limiter:
    default_rate: 10
    default_per: 1.0
  shutdown:
    default_timeout: 30
  heartbeat:
    interval: 10
  watchdog:
    timeout: 30
```

### Per-instance overrides

```python
# Override config values
cb = CircuitBreaker(
    max_failures=3,      # Override default
    reset_timeout=10,    # Override default
    name="payment-api"   # Optional identifier
)
```

## Common Patterns

### Trading bot with full resilience

```python
import tempfile
from pathlib import Path
from kstlib.resilience import CircuitBreaker, GracefulShutdown, Heartbeat

class TradingBot:
    def __init__(self):
        state_file = Path(tempfile.gettempdir()) / "tradingbot.heartbeat"

        # Heartbeat for liveness monitoring
        self.heartbeat = Heartbeat(
            state_file=state_file,
            interval=10,
            metadata={"version": "1.0.0"}
        )

        # Circuit breaker for exchange API
        self.exchange_cb = CircuitBreaker(
            max_failures=3,
            reset_timeout=30,
            name="exchange-api"
        )

        # Graceful shutdown with priority-ordered callbacks
        self.shutdown = GracefulShutdown()
        self.shutdown.register("positions", self.close_positions, priority=10)   # First: close positions
        self.shutdown.register("connections", self.cleanup, priority=50)         # Then: cleanup
        self.shutdown.register("heartbeat", self.heartbeat.stop, priority=100)   # Last: stop heartbeat

    def close_positions(self):
        """Close all open trading positions."""
        ...

    def cleanup(self):
        """Close database and API connections."""
        ...

    async def process_trades(self):
        """Main trading loop iteration."""
        ...

    async def run(self):
        self.heartbeat.start()
        self.shutdown.install()

        try:
            while not self.shutdown.is_shutting_down:
                await self.process_trades()
        finally:
            self.shutdown.trigger()
```

### Async circuit breaker

```python
from kstlib.resilience import CircuitBreaker

cb = CircuitBreaker(max_failures=2)

async def fetch_data(symbol: str) -> dict:
    return await exchange.get_ticker(symbol)

# Use acall for async functions
result = await cb.acall(fetch_data, "BTC/USDT")
```

### Rate limiter decorator

```python
from kstlib.resilience import rate_limiter, RateLimitExceededError

# Blocking mode - waits for token
@rate_limiter(rate=100, per=60.0)  # 100 requests per minute
def call_api(endpoint: str) -> dict:
    return requests.get(endpoint).json()

# Non-blocking mode - raises if limit exceeded
@rate_limiter(rate=10, per=1.0, blocking=False)
def fast_api(data: dict) -> dict:
    return api.post(data)

try:
    fast_api({"key": "value"})
except RateLimitExceededError as e:
    print(f"Rate limited, retry after {e.retry_after:.2f}s")
```

### Rate limiter with timeout

```python
from kstlib.resilience import RateLimiter, RateLimitExceededError

limiter = RateLimiter(rate=5, per=1.0)

try:
    # Wait up to 2 seconds for a token
    limiter.acquire(timeout=2.0)
    call_api()
except RateLimitExceededError as e:
    print(f"Timeout! Retry after {e.retry_after:.2f}s")
```

### Async rate limiter

```python
from kstlib.resilience import RateLimiter

limiter = RateLimiter(rate=10, per=1.0)

async def fetch_data():
    await limiter.acquire_async()  # Async wait for token
    return await api.get_data()

# Or use as async context manager
async with limiter:
    await api.get_data()
```

### Decorator usage

```python
from kstlib.resilience import circuit_breaker

@circuit_breaker(max_failures=3, reset_timeout=30)
def call_external_api(endpoint: str) -> dict:
    return requests.get(endpoint).json()
```

### Excluded exceptions

Some exceptions should not trip the circuit (e.g., validation errors):

```python
cb = CircuitBreaker(
    max_failures=3,
    excluded_exceptions=(ValueError, KeyError),  # Won't count as failures
)
```

### Multi-process heartbeat monitoring

```python
import tempfile
from pathlib import Path
from kstlib.resilience import Heartbeat

def check_services():
    temp_dir = Path(tempfile.gettempdir())
    services = ["api-server", "worker-1", "worker-2"]

    for service in services:
        state = Heartbeat.read_state(temp_dir / f"{service}.heartbeat")
        if state:
            from datetime import datetime, timezone
            ts = datetime.fromisoformat(state.timestamp)
            age = (datetime.now(tz=timezone.utc) - ts).total_seconds()
            status = "DEAD" if age > 30 else "ALIVE"
        else:
            status = "UNKNOWN"
        print(f"{service}: {status}")
```

### Async graceful shutdown

```python
shutdown = GracefulShutdown()

async def async_cleanup():
    await db.close()
    await cache.flush()

shutdown.register("cleanup", async_cleanup, priority=10)

# Use atrigger() for async context
await shutdown.atrigger()
```

### Watchdog for worker threads

```python
from kstlib.resilience import Watchdog
import threading

def on_worker_frozen():
    print("Worker thread appears frozen - consider restart")

def worker():
    with Watchdog(timeout=60, on_timeout=on_worker_frozen, name="worker") as wd:
        while True:
            wd.ping()  # Must call before each long operation
            process_next_item()

thread = threading.Thread(target=worker, daemon=True)
thread.start()
```

### Async watchdog

```python
from kstlib.resilience import Watchdog

async def monitored_task():
    async with Watchdog(timeout=30) as wd:
        while running:
            await wd.aping()  # Async ping
            await do_async_work()
```

### Watchdog with raise on timeout

```python
from kstlib.resilience import watchdog_context, WatchdogTimeoutError

# Raise exception instead of calling callback
wd = watchdog_context(timeout=10, raise_on_timeout=True)

try:
    with wd:
        while True:
            wd.ping()
            slow_operation()
except WatchdogTimeoutError as e:
    print(f"Timeout after {e.seconds_inactive:.1f}s of inactivity")
```

```{seealso}
For a complete real-world example integrating all resilience components (Heartbeat, Watchdog, TimeTrigger, AlertManager, WebSocketManager), see the resilience section in the {doc}`../../examples` Gallery.
```

## Troubleshooting

### Circuit stays open too long

**Cause**: `reset_timeout` too high or service still failing.

**Solution**: Reduce `reset_timeout` or check service health:

```python
cb = CircuitBreaker(max_failures=3, reset_timeout=10)  # 10s instead of 60s
```

### Shutdown callbacks not running

**Cause**: Signal handlers not installed or already triggered.

**Solution**: Call `install()` before the main loop:

```python
shutdown = GracefulShutdown()
shutdown.register("cleanup", cleanup_fn)
shutdown.install()  # Must call this!

# Main loop here...
```

### Heartbeat file not created

**Cause**: Permission issues or directory does not exist.

**Solution**: Use temp directory or ensure path exists:

```python
import tempfile
from pathlib import Path

state_file = Path(tempfile.gettempdir()) / "myapp.heartbeat"
heartbeat = Heartbeat(state_file=state_file)
```

### Async context issues

**Cause**: Using sync methods in async context or vice versa.

**Solution**: Use the correct method variant:

```python
# Sync context
cb.call(sync_function, arg)
shutdown.trigger()

# Async context
await cb.acall(async_function, arg)
await shutdown.atrigger()
```

### Watchdog triggers unexpectedly

**Cause**: Long-running operation without ping calls.

**Solution**: Call `ping()` before each potentially slow operation:

```python
with Watchdog(timeout=30) as wd:
    for item in large_dataset:
        wd.ping()  # Reset timer before processing
        slow_process(item)  # May take 5+ seconds
```

### Watchdog callback not called

**Cause**: Watchdog not started or already stopped.

**Solution**: Use context manager or call `start()`:

```python
# Wrong - watchdog not started
wd = Watchdog(timeout=30, on_timeout=callback)
# ... callback never called

# Correct - use context manager
with Watchdog(timeout=30, on_timeout=callback) as wd:
    ...

# Or explicitly start
wd = Watchdog(timeout=30, on_timeout=callback)
wd.start()
try:
    ...
finally:
    wd.stop()
```

### Rate limit always exceeded

**Cause**: Rate too low or burst capacity exhausted.

**Solution**: Increase rate or use blocking mode:

```python
# Option 1: Increase rate
limiter = RateLimiter(rate=100, per=1.0)  # 100/s instead of 10/s

# Option 2: Use blocking mode (default)
limiter.acquire()  # Waits for token instead of failing

# Option 3: Add burst capacity
limiter = RateLimiter(rate=10, per=1.0, burst=50)  # Allow bursts up to 50
```

### Rate limiter not throttling

**Cause**: Each decorator call creates a new limiter instance.

**Solution**: Share the limiter instance:

```python
# Wrong - each call creates new limiter
@rate_limiter(rate=10)
def call_a(): ...

@rate_limiter(rate=10)
def call_b(): ...  # Separate limiter!

# Correct - share limiter
shared_limiter = RateLimiter(rate=10, per=1.0)

def call_a():
    shared_limiter.acquire()
    ...

def call_b():
    shared_limiter.acquire()
    ...
```

## API Reference

Full autodoc: {doc}`../../api/resilience`

| Class | Description |
| - | - |
| `CircuitBreaker` | Fault tolerance for external calls |
| `CircuitState` | Circuit breaker state enum |
| `CircuitStats` | Circuit breaker statistics |
| `GracefulShutdown` | Priority-based shutdown callbacks |
| `Heartbeat` | Process liveness signaling |
| `HeartbeatState` | Heartbeat state data container |
| `RateLimiter` | Token bucket rate limiting |
| `RateLimiterStats` | Rate limiter statistics |
| `Watchdog` | Thread/process freeze detection |
| `WatchdogStats` | Watchdog statistics |

| Exception | Description |
| - | - |
| `CircuitOpenError` | Raised when circuit is open |
| `HeartbeatError` | Heartbeat write/read failures |
| `RateLimitExceededError` | Raised when rate limit exceeded |
| `WatchdogError` | Watchdog base exception |
| `WatchdogTimeoutError` | Raised when watchdog timeout occurs |
