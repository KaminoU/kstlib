# WebSocket

Async WebSocket client with proactive connection control for trading applications.

## TL;DR

```python
import asyncio
from kstlib.websocket import WebSocketManager

async def main():
    async with WebSocketManager("wss://stream.example.com/ws") as ws:
        async for message in ws.stream():
            print(message)

asyncio.run(main())
```

## Key Features

- **Proactive Control**: User-controlled disconnect/reconnect timing
- **Auto-Reconnection**: Configurable reconnection strategies
- **Subscription Management**: Auto-resubscribe on reconnection
- **Statistics Tracking**: Proactive vs reactive disconnect metrics
- **Config-Driven**: Integrates with `kstlib.conf.yml`

## The Problem

Traditional WebSocket clients are **reactive**: they only handle disconnections after they occur. For trading applications, this is problematic:

- Binance disconnects WebSockets every 24 hours
- Disconnections during critical moments (order placement, candle close) cause data loss
- No control over WHEN disconnections happen

## The Solution: Proactive Control

`WebSocketManager` lets you control WHEN to disconnect and reconnect:

```python
def next_candle_in() -> float:
    """Seconds until next 4H candle."""
    ...

ws = WebSocketManager(
    url="wss://stream.binance.com/ws/btcusdt@kline_4h",
    # Disconnect when > 30s until next candle (safe window)
    should_disconnect=lambda: next_candle_in() > 30,
    # Reconnect when < 60s until next candle (prepare for data)
    should_reconnect=lambda: next_candle_in() < 60,
    disconnect_check_interval=5.0,
)
```

This ensures you're always connected during critical moments and disconnected during safe windows.

## Quick Start

### Basic Usage

```python
from kstlib.websocket import WebSocketManager

async with WebSocketManager("wss://example.com/ws") as ws:
    async for message in ws.stream():
        print(message)
```

### With Auto-Reconnection

```python
from kstlib.websocket import WebSocketManager, ReconnectStrategy

ws = WebSocketManager(
    url="wss://example.com/ws",
    reconnect_strategy=ReconnectStrategy.EXPONENTIAL_BACKOFF,
    max_reconnect_attempts=5,
    reconnect_delay=1.0,
    reconnect_delay_max=60.0,
)
```

### With Subscriptions

```python
ws = WebSocketManager(
    url="wss://stream.binance.com/ws",
    subscriptions=[
        {"method": "SUBSCRIBE", "params": ["btcusdt@kline_1m"]},
        {"method": "SUBSCRIBE", "params": ["ethusdt@kline_1m"]},
    ],
)

# Subscriptions are automatically restored on reconnection
```

### Manual Control

```python
ws = WebSocketManager(url="wss://example.com/ws")

await ws.connect()

# Request graceful disconnect (waits for safe moment)
ws.request_disconnect()

# Force immediate disconnect
await ws.disconnect()

# Schedule reconnection
ws.schedule_reconnect(delay=30.0)

# Check state
print(ws.state)  # ConnectionState.CONNECTED
print(ws.stats)  # WebSocketStats(...)
```

## Connection States

```python
from kstlib.websocket import ConnectionState

ConnectionState.DISCONNECTED  # Initial state
ConnectionState.CONNECTING    # Connection in progress
ConnectionState.CONNECTED     # Active connection
ConnectionState.RECONNECTING  # Restoring lost connection
ConnectionState.CLOSING       # Graceful shutdown
ConnectionState.CLOSED        # Terminal state
```

State transitions:
```
DISCONNECTED -> CONNECTING -> CONNECTED
CONNECTED -> RECONNECTING -> CONNECTED (success)
CONNECTED -> RECONNECTING -> DISCONNECTED (failure)
CONNECTED -> CLOSING -> CLOSED
```

## Disconnect Reasons

Track why disconnections happened:

```python
from kstlib.websocket import DisconnectReason

# Proactive (user-controlled)
DisconnectReason.USER_REQUESTED      # Manual disconnect
DisconnectReason.SCHEDULED           # Scheduled reconnect
DisconnectReason.CALLBACK_TRIGGERED  # should_disconnect() returned True
DisconnectReason.CONNECTION_LIMIT    # Preemptive (before platform limit)

# Reactive (forced)
DisconnectReason.SERVER_CLOSED   # Server closed connection
DisconnectReason.NETWORK_ERROR   # Network issue
DisconnectReason.PING_TIMEOUT    # No pong response
DisconnectReason.PROTOCOL_ERROR  # Protocol violation

# Check type
reason.is_proactive  # True for user-controlled
reason.is_reactive   # True for forced
```

## Statistics

Monitor connection health:

```python
stats = ws.stats

print(f"Connects: {stats.connects}")
print(f"Disconnects: {stats.disconnects}")
print(f"  Proactive: {stats.proactive_disconnects}")
print(f"  Reactive: {stats.reactive_disconnects}")
print(f"Messages: {stats.messages_received} rx, {stats.messages_sent} tx")
print(f"Bytes: {stats.bytes_received} rx, {stats.bytes_sent} tx")
print(f"Uptime: {stats.uptime:.1f}s")
print(f"Connection time: {stats.connection_time:.1f}s")
```

## Configuration

Settings from `kstlib.conf.yml`:

```yaml
websocket:
  # Connection settings
  connect_timeout: 10.0
  ping_interval: 30.0
  ping_timeout: 10.0

  # Reconnection settings
  reconnect_delay: 1.0
  reconnect_delay_max: 60.0
  max_reconnect_attempts: 10

  # Queue settings
  queue_size: 1000

  # Proactive control
  disconnect_check_interval: 5.0
```

## Error Handling

```python
from kstlib.websocket import (
    WebSocketError,
    WebSocketConnectionError,
    WebSocketClosedError,
    WebSocketTimeoutError,
)

try:
    async with WebSocketManager(url) as ws:
        async for message in ws.stream():
            process(message)
except WebSocketConnectionError as e:
    log.error(f"Connection failed: {e.url}, attempts: {e.attempts}")
except WebSocketClosedError as e:
    log.warning(f"Closed: {e.code} - {e.reason}")
except WebSocketTimeoutError as e:
    log.warning(f"Timeout: {e.operation}")
except WebSocketError as e:
    log.error(f"WebSocket error: {e}")
```

## Trading Example

Complete example for Binance kline streaming:

```python
import asyncio
from datetime import datetime
from kstlib.websocket import WebSocketManager, ReconnectStrategy

def seconds_until_candle_close(interval_minutes: int = 240) -> float:
    """Calculate seconds until next candle close."""
    now = datetime.utcnow()
    minutes = now.hour * 60 + now.minute
    next_close = ((minutes // interval_minutes) + 1) * interval_minutes
    seconds_to_close = (next_close - minutes) * 60 - now.second
    return max(0, seconds_to_close)

async def main():
    ws = WebSocketManager(
        url="wss://stream.binance.com:9443/ws/btcusdt@kline_4h",
        reconnect_strategy=ReconnectStrategy.EXPONENTIAL_BACKOFF,
        # Disconnect when > 5 min until candle close
        should_disconnect=lambda: seconds_until_candle_close() > 300,
        # Reconnect when < 2 min until candle close
        should_reconnect=lambda: seconds_until_candle_close() < 120,
        disconnect_check_interval=10.0,
    )

    async with ws:
        async for message in ws.stream():
            kline = message.get("k", {})
            if kline.get("x"):  # Candle closed
                print(f"Candle closed: {kline['c']}")

asyncio.run(main())
```

## See Also

- {doc}`/api/websocket` - API Reference
- {doc}`/api/exceptions/websocket` - Exception Catalog
- {doc}`/features/resilience/index` - Resilience patterns (CircuitBreaker, Watchdog)

