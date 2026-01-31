"""Binance WebSocket kline stream with proactive reconnection.

Wraps kstlib.websocket.WebSocketManager for Binance-specific behavior:
- Kline stream subscription
- Proactive disconnect/reconnect on time modulo (e.g., every 30 min)
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from kstlib.logging import LogManager
from kstlib.websocket import WebSocketManager
from kstlib.websocket.models import DisconnectReason

# Placeholder logger - will be replaced by main.py via set_logger()
# Use standard logging to avoid handler duplication from multiple init_logging() calls
import logging as _logging

log: LogManager | _logging.Logger = _logging.getLogger(__name__)

# Global counter for unique stream IDs (debug tracing)
_stream_counter: int = 0


def set_logger(logger: LogManager) -> None:
    """Set the module logger from main.py after init_logging()."""
    global log
    log = logger


@dataclass(frozen=True, slots=True)
class Kline:
    """Represents a candlestick (kline) from Binance.

    Attributes:
        symbol: Trading pair (e.g., BTCUSDT).
        interval: Timeframe (e.g., 15m).
        open_time: Candle open timestamp.
        close_time: Candle close timestamp.
        open: Open price.
        high: High price.
        low: Low price.
        close: Close price.
        volume: Base asset volume.
        is_closed: Whether candle is closed.
    """

    symbol: str
    interval: str
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool

    @classmethod
    def from_message(cls, data: dict[str, Any]) -> Kline:
        """Parse from Binance kline WebSocket message."""
        k = data["k"]
        return cls(
            symbol=k["s"],
            interval=k["i"],
            open_time=datetime.fromtimestamp(k["t"] / 1000, tz=timezone.utc),
            close_time=datetime.fromtimestamp(k["T"] / 1000, tz=timezone.utc),
            open=float(k["o"]),
            high=float(k["h"]),
            low=float(k["l"]),
            close=float(k["c"]),
            volume=float(k["v"]),
            is_closed=k["x"],
        )

    def __str__(self) -> str:
        """Format for display."""
        time_str = self.open_time.strftime("%H:%M:%S")
        return (
            f"{time_str} | O:{self.open:,.2f} H:{self.high:,.2f} "
            f"L:{self.low:,.2f} C:{self.close:,.2f} V:{self.volume:,.2f}"
        )


class BinanceKlineStream:
    """Binance kline WebSocket stream with proactive reconnection.

    Implements proactive disconnect/reconnect based on time modulo.
    For example, with modulo_minutes=30, the stream will disconnect
    at :00 and :30 of each hour, then immediately reconnect.

    This tests the resilience of the WebSocket manager without waiting
    for Binance to force a disconnection (which happens after ~24h).

    Args:
        symbol: Trading pair (e.g., btcusdt).
        timeframe: Candle interval (e.g., 15m).
        ws_url: WebSocket base URL.
        modulo_minutes: Disconnect when minute % modulo == 0.
        margin_seconds: Seconds before modulo to trigger disconnect.
        min_connection_duration: Minimum seconds before allowing disconnect.
        on_connect: Callback when connected.
        on_disconnect: Callback when disconnected.
        on_kline: Callback for each kline message.
        config: Optional config mapping.
    """

    def __init__(
        self,
        symbol: str,
        timeframe: str,
        *,
        ws_url: str = "wss://stream.testnet.binance.vision/ws",
        modulo_minutes: int = 30,
        margin_seconds: int = 5,
        min_connection_duration: int = 60,
        on_connect: Callable[[], Awaitable[None] | None] | None = None,
        on_disconnect: Callable[[DisconnectReason], Awaitable[None] | None] | None = None,
        on_kline: Callable[[Kline], Awaitable[None] | None] | None = None,
        on_alert: Callable[[str, str, Mapping[str, Any]], Awaitable[None] | None] | None = None,
        config: Mapping[str, Any] | None = None,
    ) -> None:
        # Unique stream ID for debug tracing
        global _stream_counter
        _stream_counter += 1
        self._stream_id = _stream_counter

        self._symbol = symbol.lower()
        self._timeframe = timeframe
        self._modulo_minutes = modulo_minutes
        self._margin_seconds = margin_seconds
        self._min_connection_duration = min_connection_duration

        # Callbacks
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._on_kline = on_kline

        # Build WebSocket URL from config
        stream_name = f"{self._symbol}@kline_{self._timeframe}"
        self._url = f"{ws_url}/{stream_name}"

        # Connection tracking
        self._connect_time: float = 0.0
        self._reconnect_count = 0
        self._trigger_disconnect = False  # Controlled by trigger_reconnect()

        log.debug("[Stream#%d] Created for %s", self._stream_id, stream_name)

        # Create WebSocket manager with proactive control
        self._ws = WebSocketManager(
            url=self._url,
            should_disconnect=self._should_disconnect,
            should_reconnect=self._should_reconnect,
            on_connect=self._handle_connect,
            on_disconnect=self._handle_disconnect,
            on_alert=on_alert,
            auto_reconnect=True,
            config=config,
        )

    @property
    def url(self) -> str:
        """Return WebSocket URL."""
        return self._url

    @property
    def reconnect_count(self) -> int:
        """Return number of reconnections."""
        return self._reconnect_count

    @property
    def is_connected(self) -> bool:
        """Return True if currently connected."""
        return str(self._ws.state.name) == "CONNECTED"

    def _should_disconnect(self) -> bool:
        """Check if we should proactively disconnect.

        Now controlled externally via trigger_reconnect() after candle close.
        This callback always returns False - reconnect is triggered by main.py
        when a closed candle's minute is modulo the configured interval.
        """
        return self._trigger_disconnect

    def _should_reconnect(self) -> bool | float:
        """Check if we should reconnect.

        Always returns True immediately after proactive disconnect.
        Returns delay in seconds if we want to wait.
        """
        # Reconnect immediately after proactive disconnect
        return True

    def trigger_reconnect(self) -> None:
        """Trigger a proactive disconnect/reconnect cycle.

        Called by main.py after processing a closed candle whose
        close_time.minute is a modulo of the configured interval.
        """
        self._trigger_disconnect = True

    def reset_trigger(self) -> None:
        """Reset the disconnect trigger after reconnection."""
        self._trigger_disconnect = False

    @property
    def is_dead(self) -> bool:
        """Return True if the stream is dead and needs restart.

        Uses WebSocketManager.is_dead which returns True if state is
        DISCONNECTED or CLOSED (i.e., not connected and not reconnecting).
        """
        return self._ws.is_dead

    @property
    def is_shutdown(self) -> bool:
        """Return True if shutdown was requested (intentional stop)."""
        return self._ws.is_shutdown

    async def kill(self) -> None:
        """Kill the stream (simulates external disconnect like Binance kick).

        Uses WebSocketManager.kill() which sets state to DISCONNECTED.
        Unlike force_close(), the stream CAN be reconnected after kill().
        Used to test heartbeat recovery mechanisms.
        """
        log.info("[Stream#%d] KILL requested (simulating Binance kick)", self._stream_id)
        await self._ws.kill()

    async def shutdown(self) -> None:
        """Graceful intentional shutdown (user-initiated stop).

        Uses WebSocketManager.shutdown() which sets state to CLOSED.
        The stream CANNOT be reconnected after shutdown().
        Heartbeat/watchdog will see is_shutdown=True and know not to restart.
        """
        log.info("[Stream#%d] SHUTDOWN requested (intentional stop)", self._stream_id)
        await self._ws.shutdown()

    @property
    def stream_id(self) -> int:
        """Unique stream ID for debug tracing."""
        return self._stream_id

    async def _handle_connect(self) -> None:
        """Handle connection established."""
        import time

        self._connect_time = time.monotonic()
        self._trigger_disconnect = False  # Reset trigger on reconnect
        log.info("[Stream#%d] CONNECTED to %s", self._stream_id, self._url)

        if self._on_connect:
            result = self._on_connect()
            if result is not None:
                await result

    async def _handle_disconnect(self, reason: DisconnectReason) -> None:
        """Handle disconnection."""
        self._reconnect_count += 1
        log.info("[Stream#%d] DISCONNECTED from %s (reason: %s)", self._stream_id, self._url, reason.name)

        if self._on_disconnect:
            result = self._on_disconnect(reason)
            if result is not None:
                await result

    async def stream(self) -> AsyncIterator[Kline]:
        """Stream klines from Binance.

        Yields:
            Kline objects as they are received.
        """
        async for message in self._ws.stream():
            try:
                # Parse JSON if string
                data = json.loads(message) if isinstance(message, str) else message

                # Skip non-kline messages
                if data.get("e") != "kline":
                    continue

                kline = Kline.from_message(data)

                # Call kline callback if provided
                if self._on_kline:
                    result = self._on_kline(kline)
                    if result is not None:
                        await result

                yield kline

            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                log.warning("Failed to parse message: %s", exc)
                continue

    async def connect(self) -> None:
        """Connect to WebSocket."""
        await self._ws.connect()

    async def disconnect(self) -> None:
        """Disconnect from WebSocket."""
        await self._ws.disconnect()

    async def __aenter__(self) -> BinanceKlineStream:
        """Enter async context manager."""
        await self._ws.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Exit async context manager."""
        await self._ws.__aexit__(exc_type, exc_val, exc_tb)


__all__ = ["BinanceKlineStream", "Kline"]
