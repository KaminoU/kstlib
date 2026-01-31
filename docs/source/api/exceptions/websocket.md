# WebSocket Exceptions

Exception hierarchy for the websocket subsystem.

## Exception Hierarchy

```
KstlibError
└── WebSocketError
    ├── WebSocketConnectionError
    ├── WebSocketClosedError
    ├── WebSocketTimeoutError
    ├── WebSocketReconnectError
    ├── WebSocketProtocolError
    └── WebSocketQueueFullError
```

## Base Exception

```{eval-rst}
.. autoexception:: kstlib.websocket.exceptions.WebSocketError
   :members:
   :show-inheritance:
```

## Connection Errors

```{eval-rst}
.. autoexception:: kstlib.websocket.exceptions.WebSocketConnectionError
   :members:
   :show-inheritance:
```

Raised when connection fails:
- Initial connection failure
- All retry attempts exhausted
- DNS resolution failure

Attributes:
- `url`: The WebSocket URL that failed
- `attempts`: Number of connection attempts made
- `last_error`: The underlying error from the last attempt

## Closed Errors

```{eval-rst}
.. autoexception:: kstlib.websocket.exceptions.WebSocketClosedError
   :members:
   :show-inheritance:
```

Raised when connection is closed unexpectedly:
- Server initiated close
- Protocol error close
- Network disconnection

Attributes:
- `code`: WebSocket close code (1000-4999)
- `reason`: Human-readable close reason

## Timeout Errors

```{eval-rst}
.. autoexception:: kstlib.websocket.exceptions.WebSocketTimeoutError
   :members:
   :show-inheritance:
```

Raised when operations time out:
- Connection timeout
- Ping/pong timeout
- Receive timeout

Attributes:
- `operation`: The operation that timed out
- `timeout`: The timeout value in seconds

## Reconnect Errors

```{eval-rst}
.. autoexception:: kstlib.websocket.exceptions.WebSocketReconnectError
   :members:
   :show-inheritance:
```

Raised when reconnection fails:
- All reconnection attempts exhausted
- Reconnection disabled

Attributes:
- `attempts`: Total reconnection attempts made
- `last_error`: The underlying error from the last attempt

## Protocol Errors

```{eval-rst}
.. autoexception:: kstlib.websocket.exceptions.WebSocketProtocolError
   :members:
   :show-inheritance:
```

Raised on protocol violations:
- Malformed frames
- Invalid data format
- Protocol state violations

Attributes:
- `protocol_error`: Description of the protocol violation

## Queue Errors

```{eval-rst}
.. autoexception:: kstlib.websocket.exceptions.WebSocketQueueFullError
   :members:
   :show-inheritance:
```

Raised when message queue is full:
- Consumer too slow
- Burst of messages

Attributes:
- `queue_size`: Maximum queue size exceeded
- `dropped_count`: Number of messages dropped

## Usage Examples

```python
from kstlib.websocket import (
    WebSocketError,
    WebSocketConnectionError,
    WebSocketClosedError,
    WebSocketTimeoutError,
    WebSocketReconnectError,
)

try:
    async with WebSocketManager(url) as ws:
        async for message in ws.stream():
            process(message)
except WebSocketConnectionError as e:
    log.error(f"Failed to connect to {e.url} after {e.attempts} attempts")
except WebSocketClosedError as e:
    log.warning(f"Connection closed: {e.code} - {e.reason}")
except WebSocketTimeoutError as e:
    log.warning(f"Timeout during {e.operation}: {e.timeout}s")
except WebSocketReconnectError as e:
    log.error(f"Reconnection failed after {e.attempts} attempts")
except WebSocketError as e:
    log.error(f"WebSocket error: {e}")
```

