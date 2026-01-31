"""WebSocket client with proactive connection control.

This module provides WebSocketManager, an async WebSocket client that offers
proactive control over connections rather than just reactive reconnection.

The key differentiator is the ability to control WHEN to disconnect/reconnect
rather than just reacting to disconnections. This is essential for trading
applications where you want to avoid disconnections during critical operations.

Features:
    - **Proactive Control**: User-controlled disconnect/reconnect timing
    - **Auto-Reconnection**: Configurable reconnection strategies
    - **Subscription Management**: Auto-resubscribe on reconnection
    - **Statistics Tracking**: Proactive vs reactive disconnect metrics
    - **Config-Driven**: Integrates with kstlib.conf.yml

Examples:
    Basic usage:

    >>> from kstlib.websocket import WebSocketManager
    >>> async def main():  # doctest: +SKIP
    ...     async with WebSocketManager("wss://example.com/ws") as ws:
    ...         async for message in ws.stream():
    ...             print(message)

    Proactive control for trading:

    >>> def next_candle_in() -> float:  # doctest: +SKIP
    ...     '''Seconds until next 4H candle.'''
    ...     ...
    >>> async def trading():  # doctest: +SKIP
    ...     ws = WebSocketManager(
    ...         url="wss://stream.binance.com/ws/btcusdt@kline_4h",
    ...         # Disconnect when > 30s until next candle
    ...         should_disconnect=lambda: next_candle_in() > 30,
    ...         # Reconnect when < 60s until next candle
    ...         should_reconnect=lambda: next_candle_in() < 60,
    ...         disconnect_check_interval=5.0,
    ...     )
    ...     async with ws:
    ...         async for candle in ws.stream():
    ...             if candle.get("k", {}).get("x"):
    ...                 process_candle(candle)

Note:
    Requires the ``websockets`` package. Install with::

        pip install kstlib[websocket]
"""

from kstlib.websocket.exceptions import (
    WebSocketClosedError,
    WebSocketConnectionError,
    WebSocketError,
    WebSocketProtocolError,
    WebSocketQueueFullError,
    WebSocketReconnectError,
    WebSocketTimeoutError,
)
from kstlib.websocket.models import (
    ConnectionState,
    DisconnectReason,
    ReconnectStrategy,
    WebSocketStats,
)

# Lazy import for WebSocketManager to avoid ImportError if websockets not installed
_websocket_manager = None


def __getattr__(name: str) -> type:
    """Lazy load WebSocketManager to avoid ImportError if websockets not installed."""
    if name == "WebSocketManager":
        global _websocket_manager
        if _websocket_manager is None:
            from kstlib.websocket.manager import WebSocketManager

            _websocket_manager = WebSocketManager
        return _websocket_manager
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


__all__ = [
    "ConnectionState",
    "DisconnectReason",
    "ReconnectStrategy",
    "WebSocketClosedError",
    "WebSocketConnectionError",
    "WebSocketError",
    "WebSocketManager",
    "WebSocketProtocolError",
    "WebSocketQueueFullError",
    "WebSocketReconnectError",
    "WebSocketStats",
    "WebSocketTimeoutError",
]
