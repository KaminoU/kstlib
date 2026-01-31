# WebSocket Subsystem

Async WebSocket client with proactive connection control and auto-reconnection.

```{tip}
Pair this reference with {doc}`../features/websocket/index` for the feature guide.
```

## Quick Overview

- `WebSocketManager` provides proactive control over connection lifecycle.
- `ConnectionState` tracks the connection state machine.
- `DisconnectReason` categorizes proactive vs reactive disconnections.
- `ReconnectStrategy` defines reconnection behavior.
- `WebSocketStats` tracks connection and message statistics.

---

## Core Components

### WebSocketManager

```{eval-rst}
.. autoclass:: kstlib.websocket.manager.WebSocketManager
   :members:
   :show-inheritance:
   :noindex:
```

---

## Models

### ConnectionState

```{eval-rst}
.. autoclass:: kstlib.websocket.models.ConnectionState
   :members:
   :show-inheritance:
   :noindex:
```

### DisconnectReason

```{eval-rst}
.. autoclass:: kstlib.websocket.models.DisconnectReason
   :members:
   :show-inheritance:
   :noindex:
```

### ReconnectStrategy

```{eval-rst}
.. autoclass:: kstlib.websocket.models.ReconnectStrategy
   :members:
   :show-inheritance:
   :noindex:
```

### WebSocketStats

```{eval-rst}
.. autoclass:: kstlib.websocket.models.WebSocketStats
   :members:
   :show-inheritance:
   :noindex:
```

---

## Configuration Limits

### WebSocketLimits

```{eval-rst}
.. autoclass:: kstlib.limits.WebSocketLimits
   :members:
   :show-inheritance:
   :noindex:
```

### get_websocket_limits

```{eval-rst}
.. autofunction:: kstlib.limits.get_websocket_limits
   :noindex:
```
