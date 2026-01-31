"""WebSocket manager with proactive connection control.

This module provides WebSocketManager, an async WebSocket client that offers
proactive control over connections rather than just reactive reconnection.

The key differentiator is the ability to control WHEN to disconnect/reconnect
rather than just reacting to disconnections. This is essential for trading
applications where you want to avoid disconnections during critical operations.

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
    ...         should_disconnect=lambda: next_candle_in() > 30,
    ...         should_reconnect=lambda: next_candle_in() < 60,
    ...     )
    ...     async with ws:
    ...         async for candle in ws.stream():
    ...             process(candle)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from typing_extensions import Self

if TYPE_CHECKING:
    import types

from kstlib.limits import get_websocket_limits
from kstlib.websocket.exceptions import (
    WebSocketClosedError,
    WebSocketConnectionError,
    WebSocketReconnectError,
    WebSocketTimeoutError,
)
from kstlib.websocket.models import (
    ConnectionState,
    DisconnectReason,
    ReconnectStrategy,
    WebSocketStats,
)

try:
    import websockets
    from websockets.asyncio.client import ClientConnection, connect
    from websockets.exceptions import (
        ConnectionClosed,
        ConnectionClosedError,
        ConnectionClosedOK,
        InvalidURI,
        WebSocketException,
    )

    HAS_WEBSOCKETS = True
except ImportError:  # pragma: no cover
    HAS_WEBSOCKETS = False
    websockets = None  # type: ignore[assignment]
    ClientConnection = None  # type: ignore[assignment,misc]
    connect = None  # type: ignore[assignment,misc]
    ConnectionClosed = Exception  # type: ignore[assignment,misc]
    ConnectionClosedError = Exception  # type: ignore[assignment,misc]
    ConnectionClosedOK = Exception  # type: ignore[assignment,misc]
    InvalidURI = Exception  # type: ignore[assignment,misc]
    WebSocketException = Exception  # type: ignore[assignment,misc]

__all__ = ["WebSocketManager"]

log = logging.getLogger(__name__)

# Type aliases for callbacks
ShouldDisconnectCallback = Callable[[], bool]
ShouldReconnectCallback = Callable[[], bool | float]
OnConnectCallback = Callable[[], Awaitable[None] | None]
OnDisconnectCallback = Callable[[DisconnectReason], Awaitable[None] | None]
OnMessageCallback = Callable[[Any], Awaitable[None] | None]
OnAlertCallback = Callable[[str, str, Mapping[str, Any]], Awaitable[None] | None]


def _check_websockets_installed() -> None:
    """Raise ImportError if websockets is not installed."""
    if not HAS_WEBSOCKETS:
        msg = "websockets is required for WebSocketManager. Install it with: pip install kstlib[websocket]"
        raise ImportError(msg)


class WebSocketManager:
    """Async WebSocket manager with proactive connection control.

    This manager provides both reactive (auto-reconnect on failure) and
    proactive (user-controlled disconnect/reconnect) connection management.

    The proactive control feature is the key differentiator: instead of just
    reacting to disconnections, you can control WHEN to disconnect and reconnect.
    This is essential for trading where you want to avoid mid-operation cuts.

    Attributes:
        url: WebSocket server URL.
        state: Current connection state.
        stats: Connection and message statistics.

    Examples:
        Basic streaming:

        >>> async def main():  # doctest: +SKIP
        ...     async with WebSocketManager("wss://example.com/ws") as ws:
        ...         async for msg in ws.stream():
        ...             print(msg)

        Proactive control:

        >>> async def trading():  # doctest: +SKIP
        ...     ws = WebSocketManager(
        ...         url="wss://stream.binance.com/ws",
        ...         should_disconnect=lambda: not is_critical_time(),
        ...         should_reconnect=lambda: is_approaching_candle(),
        ...     )
        ...     async with ws:
        ...         await ws.subscribe("btcusdt@kline_4h")
        ...         async for msg in ws.stream():
        ...             process(msg)
    """

    def __init__(
        self,
        url: str,
        *,
        # Proactive callbacks
        should_disconnect: ShouldDisconnectCallback | None = None,
        should_reconnect: ShouldReconnectCallback | None = None,
        on_connect: OnConnectCallback | None = None,
        on_disconnect: OnDisconnectCallback | None = None,
        on_message: OnMessageCallback | None = None,
        on_alert: OnAlertCallback | None = None,
        # Connection settings
        ping_interval: float | None = None,
        ping_timeout: float | None = None,
        connection_timeout: float | None = None,
        # Reconnection settings
        reconnect_strategy: ReconnectStrategy = ReconnectStrategy.EXPONENTIAL_BACKOFF,
        reconnect_delay: float | None = None,
        max_reconnect_delay: float | None = None,
        max_reconnect_attempts: int | None = None,
        auto_reconnect: bool = True,
        # Proactive control settings
        disconnect_check_interval: float | None = None,
        reconnect_check_interval: float | None = None,
        disconnect_margin: float | None = None,
        # Queue settings
        queue_size: int | None = None,
        # Config
        config: Mapping[str, Any] | None = None,
    ) -> None:
        """Initialize WebSocket manager.

        Args:
            url: WebSocket server URL (wss:// or ws://).
            should_disconnect: Callback returning True when disconnect is desired.
            should_reconnect: Callback returning True or delay (seconds) for reconnect.
            on_connect: Callback invoked after successful connection.
            on_disconnect: Callback invoked after disconnection with reason.
            on_message: Callback invoked for each received message.
            on_alert: Callback for alerting (channel, message, context).
            ping_interval: Seconds between ping frames.
            ping_timeout: Seconds to wait for pong response.
            connection_timeout: Timeout for initial connection.
            reconnect_strategy: Strategy for reconnection delays.
            reconnect_delay: Initial delay between reconnect attempts.
            max_reconnect_delay: Maximum delay for exponential backoff.
            max_reconnect_attempts: Maximum consecutive reconnection attempts.
            auto_reconnect: Whether to auto-reconnect on disconnection.
            disconnect_check_interval: Seconds between should_disconnect checks.
            reconnect_check_interval: Seconds between should_reconnect checks.
            disconnect_margin: Seconds before platform limit to disconnect.
            queue_size: Maximum messages in queue (0 = unlimited).
            config: Optional config mapping for limits resolution.

        Raises:
            ImportError: If websockets package is not installed.
        """
        _check_websockets_installed()

        self._url = url
        self._state = ConnectionState.DISCONNECTED
        self._stats = WebSocketStats()

        # Resolve limits from config with hard limit enforcement
        limits = get_websocket_limits(config)

        # Apply kwargs > config > defaults pattern
        self._ping_interval = ping_interval if ping_interval is not None else limits.ping_interval
        self._ping_timeout = ping_timeout if ping_timeout is not None else limits.ping_timeout
        self._connection_timeout = connection_timeout if connection_timeout is not None else limits.connection_timeout
        self._reconnect_delay = reconnect_delay if reconnect_delay is not None else limits.reconnect_delay
        self._max_reconnect_delay = (
            max_reconnect_delay if max_reconnect_delay is not None else limits.max_reconnect_delay
        )
        self._max_reconnect_attempts = (
            max_reconnect_attempts if max_reconnect_attempts is not None else limits.max_reconnect_attempts
        )
        self._disconnect_check_interval = (
            disconnect_check_interval if disconnect_check_interval is not None else limits.disconnect_check_interval
        )
        self._reconnect_check_interval = (
            reconnect_check_interval if reconnect_check_interval is not None else limits.reconnect_check_interval
        )
        self._disconnect_margin = disconnect_margin if disconnect_margin is not None else limits.disconnect_margin
        self._queue_size = queue_size if queue_size is not None else limits.queue_size

        # Settings
        self._reconnect_strategy = reconnect_strategy
        self._auto_reconnect = auto_reconnect

        # Callbacks
        self._should_disconnect = should_disconnect
        self._should_reconnect = should_reconnect
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._on_message = on_message
        self._on_alert = on_alert

        # Internal state
        self._ws: ClientConnection | None = None
        self._message_queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=max(0, self._queue_size))
        self._subscriptions: set[str] = set()
        self._reconnect_count = 0
        self._connect_time: float = 0.0
        self._scheduled_reconnect_delay: float | None = None

        # Background tasks
        self._disconnect_check_task: asyncio.Task[None] | None = None
        self._reconnect_check_task: asyncio.Task[None] | None = None
        self._receive_task: asyncio.Task[None] | None = None
        self._ping_task: asyncio.Task[None] | None = None

        # Events
        self._connected_event = asyncio.Event()
        self._disconnected_event = asyncio.Event()
        self._closed_event = asyncio.Event()
        self._shutdown_event = asyncio.Event()
        self._disconnected_event.set()  # Start disconnected

    @property
    def url(self) -> str:
        """WebSocket server URL."""
        return self._url

    @property
    def state(self) -> ConnectionState:
        """Current connection state."""
        return self._state

    @property
    def stats(self) -> WebSocketStats:
        """Connection and message statistics."""
        return self._stats

    @property
    def is_connected(self) -> bool:
        """Check if currently connected."""
        return self._state == ConnectionState.CONNECTED

    @property
    def subscriptions(self) -> frozenset[str]:
        """Current active subscriptions."""
        return frozenset(self._subscriptions)

    @property
    def connection_duration(self) -> float:
        """Seconds since last successful connection, or 0 if not connected."""
        if self._connect_time == 0.0:
            return 0.0
        return time.monotonic() - self._connect_time

    async def __aenter__(self) -> Self:
        """Enter async context and connect."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Exit async context and close connection."""
        await self.close()

    async def connect(self) -> None:
        """Establish WebSocket connection.

        Raises:
            WebSocketConnectionError: If connection fails after retries.
            WebSocketTimeoutError: If connection times out.

        Examples:
            >>> async def main():  # doctest: +SKIP
            ...     ws = WebSocketManager("wss://example.com/ws")
            ...     await ws.connect()
            ...     try:
            ...         async for msg in ws.stream():
            ...             print(msg)
            ...     finally:
            ...         await ws.close()
        """
        if not self._state.can_connect():
            log.warning("Cannot connect from state %s", self._state)
            return

        self._state = ConnectionState.CONNECTING
        self._disconnected_event.clear()

        try:
            await self._establish_connection()
        except Exception:
            self._state = ConnectionState.DISCONNECTED
            self._disconnected_event.set()
            raise

    async def _try_connect(self) -> ClientConnection:
        """Attempt a single connection with timeout."""
        return await asyncio.wait_for(
            connect(
                self._url,
                ping_interval=self._ping_interval,
                ping_timeout=self._ping_timeout,
            ),
            timeout=self._connection_timeout,
        )

    async def _establish_connection(self) -> None:
        """Internal connection establishment with timeout."""
        last_error: BaseException | None = None

        for attempt in range(1, self._max_reconnect_attempts + 2):
            try:
                self._ws = await self._try_connect()
                break
            except asyncio.TimeoutError as e:
                last_error = e
                log.warning("Connection timeout (attempt %d/%d)", attempt, self._max_reconnect_attempts + 1)
            except InvalidURI as e:
                raise WebSocketConnectionError(
                    f"Invalid WebSocket URL: {self._url}",
                    url=self._url,
                    attempts=attempt,
                    last_error=e,
                ) from e
            except (OSError, WebSocketException) as e:
                last_error = e
                log.warning("Connection failed (attempt %d/%d): %s", attempt, self._max_reconnect_attempts + 1, e)

            if attempt <= self._max_reconnect_attempts:
                await self._wait_reconnect_delay(attempt)
        else:
            self._raise_connection_failed(last_error, self._max_reconnect_attempts + 1)

        # Connection successful
        await self._finalize_connection()

    def _raise_connection_failed(self, last_error: BaseException | None, attempts: int) -> None:
        """Raise appropriate connection error after all attempts exhausted."""
        if isinstance(last_error, asyncio.TimeoutError):
            raise WebSocketTimeoutError(
                f"Connection timed out after {attempts} attempts",
                operation="connect",
                timeout=self._connection_timeout,
            ) from last_error
        raise WebSocketConnectionError(
            f"Failed to connect after {attempts} attempts",
            url=self._url,
            attempts=attempts,
            last_error=last_error,
        ) from last_error

    async def _finalize_connection(self) -> None:
        """Finalize successful connection setup."""
        self._state = ConnectionState.CONNECTED
        self._connected_event.set()
        self._connect_time = time.monotonic()
        self._reconnect_count = 0
        self._stats.record_connect()

        log.info("WebSocket connected to %s", self._url)

        # Start background tasks
        self._start_background_tasks()

        # Invoke on_connect callback
        if self._on_connect is not None:
            result = self._on_connect()
            if asyncio.iscoroutine(result):
                await result

        # Re-subscribe to channels
        if self._subscriptions:
            await self._resubscribe()

    def _start_background_tasks(self) -> None:
        """Start background monitoring tasks."""
        # Start receive task
        self._receive_task = asyncio.create_task(self._receive_loop(), name="ws_receive_loop")

        # Start proactive disconnect check if callback provided
        if self._should_disconnect is not None:
            self._disconnect_check_task = asyncio.create_task(self._disconnect_check_loop(), name="ws_disconnect_check")

    def _parse_message(self, message: str | bytes) -> Any:
        """Parse incoming message, attempting JSON decode for strings."""
        if isinstance(message, str):
            try:
                return json.loads(message)
            except json.JSONDecodeError:
                return message
        return message

    async def _process_message(self, message: str | bytes) -> None:
        """Process a single received message."""
        data = self._parse_message(message)
        size = len(message) if isinstance(message, str | bytes) else 0
        self._stats.record_message_received(size)

        # Invoke on_message callback
        if self._on_message is not None:
            result = self._on_message(data)
            if asyncio.iscoroutine(result):
                await result

        # Queue message
        try:
            self._message_queue.put_nowait(data)
        except asyncio.QueueFull:
            await self._handle_queue_full()

    async def _handle_queue_full(self) -> None:
        """Handle queue overflow situation."""
        log.warning("Message queue full, dropping message")
        if self._on_alert:
            alert_result = self._on_alert(
                "websocket",
                "Message queue full",
                {"queue_size": self._queue_size},
            )
            if asyncio.iscoroutine(alert_result):
                await alert_result

    async def _receive_loop(self) -> None:
        """Background task to receive messages and queue them."""
        if self._ws is None:
            return

        try:
            async for message in self._ws:
                await self._process_message(message)
        except ConnectionClosedOK:
            log.debug("WebSocket closed normally")
        except ConnectionClosedError as e:
            log.warning("WebSocket closed with error: code=%d reason=%s", e.code, e.reason)
            await self._handle_disconnect(DisconnectReason.SERVER_CLOSED, code=e.code)
        except ConnectionClosed as e:
            log.warning("WebSocket connection closed: %s", e)
            await self._handle_disconnect(DisconnectReason.SERVER_CLOSED)
        except Exception:
            log.exception("Unexpected error in receive loop")
            await self._handle_disconnect(DisconnectReason.PROTOCOL_ERROR)

    async def _disconnect_check_loop(self) -> None:
        """Background task to check should_disconnect callback."""
        while self._state == ConnectionState.CONNECTED and not self._shutdown_event.is_set():
            await asyncio.sleep(self._disconnect_check_interval)

            if self._shutdown_event.is_set():
                break

            if self._should_disconnect is not None and self._state == ConnectionState.CONNECTED:
                try:
                    should_disconnect = self._should_disconnect()
                    if should_disconnect:
                        log.info("should_disconnect callback returned True, disconnecting")
                        await self.request_disconnect(reason=DisconnectReason.CALLBACK_TRIGGERED)
                        break
                except Exception as e:
                    log.warning("Error in should_disconnect callback: %s", e)

    async def _handle_disconnect(
        self,
        reason: DisconnectReason,
        *,
        code: int = 1006,
    ) -> None:
        """Handle disconnection and potentially reconnect."""
        was_connected = self._state == ConnectionState.CONNECTED
        self._state = ConnectionState.RECONNECTING if self._auto_reconnect else ConnectionState.DISCONNECTED
        self._connected_event.clear()

        if was_connected:
            self._stats.record_disconnect(proactive=reason.is_proactive)

        # Cancel background tasks
        await self._cancel_background_tasks()

        # Invoke on_disconnect callback
        if self._on_disconnect is not None:
            result = self._on_disconnect(reason)
            if asyncio.iscoroutine(result):
                await result

        log.info("WebSocket disconnected: %s (code=%d)", reason.name, code)

        # Handle reconnection
        if self._auto_reconnect and not reason.is_proactive:
            # Reactive reconnect for forced disconnections
            await self._attempt_reconnect()
        elif reason.is_proactive and self._scheduled_reconnect_delay is not None:
            # Scheduled reconnect after proactive disconnect
            delay = self._scheduled_reconnect_delay
            self._scheduled_reconnect_delay = None
            await asyncio.sleep(delay)
            await self._attempt_reconnect()
        elif reason.is_proactive and self._should_reconnect is not None:
            # Callback-controlled reconnect
            self._reconnect_check_task = asyncio.create_task(self._reconnect_check_loop(), name="ws_reconnect_check")
        else:
            self._state = ConnectionState.DISCONNECTED
            self._disconnected_event.set()

    async def _reconnect_check_loop(self) -> None:
        """Background task to check should_reconnect callback."""
        while self._state == ConnectionState.RECONNECTING and not self._shutdown_event.is_set():
            await asyncio.sleep(self._reconnect_check_interval)

            if self._shutdown_event.is_set():
                break

            if self._state not in (ConnectionState.RECONNECTING, ConnectionState.DISCONNECTED):
                break

            if self._should_reconnect is not None:
                try:
                    result = self._should_reconnect()
                    if result is True:
                        log.info("should_reconnect callback returned True, reconnecting")
                        await self._attempt_reconnect()
                        break
                    if isinstance(result, int | float) and result > 0:
                        log.info(
                            "should_reconnect callback returned delay=%.1fs, scheduling",
                            result,
                        )
                        await asyncio.sleep(result)
                        await self._attempt_reconnect()
                        break
                except Exception as e:
                    log.warning("Error in should_reconnect callback: %s", e)

    async def _attempt_reconnect(self) -> None:
        """Attempt to reconnect with retry logic."""
        if self._shutdown_event.is_set():
            log.debug("Shutdown requested, skipping reconnect attempt")
            return

        self._reconnect_count += 1

        if self._reconnect_count > self._max_reconnect_attempts:
            log.error(
                "Max reconnection attempts (%d) exceeded",
                self._max_reconnect_attempts,
            )
            self._state = ConnectionState.DISCONNECTED
            self._disconnected_event.set()
            raise WebSocketReconnectError(
                f"Failed to reconnect after {self._reconnect_count} attempts",
                attempts=self._reconnect_count,
            )

        log.info(
            "Attempting reconnection (%d/%d)",
            self._reconnect_count,
            self._max_reconnect_attempts,
        )

        self._state = ConnectionState.CONNECTING
        try:
            await self._establish_connection()
        except WebSocketConnectionError:
            if self._shutdown_event.is_set():
                return
            self._state = ConnectionState.RECONNECTING
            await self._wait_reconnect_delay(self._reconnect_count)
            await self._attempt_reconnect()

    async def _wait_reconnect_delay(self, attempt: int) -> None:
        """Wait before next reconnection attempt based on strategy."""
        if self._reconnect_strategy == ReconnectStrategy.IMMEDIATE:
            return
        if self._reconnect_strategy == ReconnectStrategy.FIXED_DELAY:
            delay = self._reconnect_delay
        elif self._reconnect_strategy == ReconnectStrategy.EXPONENTIAL_BACKOFF:
            delay = min(
                self._reconnect_delay * (2 ** (attempt - 1)),
                self._max_reconnect_delay,
            )
        else:  # CALLBACK_CONTROLLED
            delay = self._reconnect_delay

        log.debug("Waiting %.1fs before reconnection attempt", delay)
        await asyncio.sleep(delay)

    async def _cancel_background_tasks(self) -> None:
        """Cancel all background tasks."""
        tasks = [
            self._receive_task,
            self._disconnect_check_task,
            self._reconnect_check_task,
            self._ping_task,
        ]
        for task in tasks:
            if task is not None and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

        self._receive_task = None
        self._disconnect_check_task = None
        self._reconnect_check_task = None
        self._ping_task = None

    async def _resubscribe(self) -> None:
        """Re-subscribe to all channels after reconnection."""
        if not self._subscriptions:
            return

        log.debug("Re-subscribing to %d channels", len(self._subscriptions))
        for channel in self._subscriptions:
            try:
                await self._send_subscribe(channel)
            except Exception as e:
                log.warning("Failed to re-subscribe to %s: %s", channel, e)

    async def _send_subscribe(self, channel: str) -> None:
        """Send subscription message for a channel."""
        if self._ws is None:
            return

        # Generic subscription format - can be overridden for specific protocols
        message = json.dumps({"type": "subscribe", "channel": channel})
        await self._ws.send(message)

    # =========================================================================
    # PUBLIC PROACTIVE CONTROL METHODS
    # =========================================================================

    async def request_disconnect(
        self,
        *,
        reconnect_after: float | None = None,
        reason: DisconnectReason = DisconnectReason.USER_REQUESTED,
    ) -> None:
        """Request a controlled disconnection.

        This is a proactive method that allows the user to disconnect
        at a time of their choosing rather than waiting for a forced cut.

        Args:
            reconnect_after: Optional delay before auto-reconnect (seconds).
            reason: Reason for the disconnection.

        Examples:
            >>> async def main():  # doctest: +SKIP
            ...     async with WebSocketManager("wss://example.com/ws") as ws:
            ...         # Disconnect now, reconnect in 5 minutes
            ...         await ws.request_disconnect(reconnect_after=300)
        """
        if self._state != ConnectionState.CONNECTED:
            log.warning("Cannot disconnect from state %s", self._state)
            return

        log.info("User requested disconnect (reconnect_after=%s)", reconnect_after)
        self._scheduled_reconnect_delay = reconnect_after

        # Close the connection gracefully
        if self._ws is not None:
            await self._ws.close(1000, "User requested disconnect")

        await self._handle_disconnect(reason)

    async def schedule_reconnect(self, delay: float) -> None:
        """Schedule a reconnection after a delay.

        Use this to programmatically reconnect after a proactive disconnect.

        Args:
            delay: Seconds to wait before reconnecting.

        Examples:
            >>> async def main():  # doctest: +SKIP
            ...     ws = WebSocketManager("wss://example.com/ws")
            ...     await ws.connect()
            ...     await ws.request_disconnect()
            ...     # Reconnect in 5 minutes
            ...     await ws.schedule_reconnect(300)
        """
        if self._state not in (ConnectionState.DISCONNECTED, ConnectionState.RECONNECTING):
            log.warning("Cannot schedule reconnect from state %s", self._state)
            return

        log.info("Scheduling reconnection in %.1f seconds", delay)
        self._state = ConnectionState.RECONNECTING
        await asyncio.sleep(delay)
        await self._attempt_reconnect()

    async def wait_for_reconnect_window(
        self,
        should_reconnect: ShouldReconnectCallback | None = None,
        timeout: float | None = None,
    ) -> bool:
        """Wait until the reconnection condition is met.

        Args:
            should_reconnect: Custom callback (overrides instance callback).
            timeout: Maximum time to wait (seconds).

        Returns:
            True if reconnect condition was met, False if timed out.

        Examples:
            >>> async def main():  # doctest: +SKIP
            ...     ws = WebSocketManager("wss://example.com/ws")
            ...     await ws.connect()
            ...     await ws.request_disconnect()
            ...     # Wait for trading window
            ...     if await ws.wait_for_reconnect_window(
            ...         should_reconnect=lambda: is_trading_time(),
            ...         timeout=3600,
            ...     ):
            ...         await ws.connect()
        """
        callback = should_reconnect or self._should_reconnect
        if callback is None:
            log.warning("No should_reconnect callback provided")
            return False

        start_time = time.monotonic()
        while True:
            elapsed = time.monotonic() - start_time
            if timeout is not None and elapsed >= timeout:
                return False

            try:
                result = callback()
                if result is True:
                    return True
                if isinstance(result, int | float) and result > 0:
                    wait_time = min(
                        result,
                        (timeout - elapsed) if timeout else result,
                    )
                    await asyncio.sleep(wait_time)
                    continue
            except Exception as e:
                log.warning("Error in should_reconnect callback: %s", e)

            await asyncio.sleep(self._reconnect_check_interval)

    async def force_close(self) -> None:
        """Emergency close without reconnection (terminal state).

        This is for emergency situations where you need to stop immediately.
        The WebSocket instance becomes unusable after this call.

        **Key difference from kill() and shutdown():**
        - `kill()`: Reactive. Server kicked us. State=DISCONNECTED. CAN reconnect.
        - `shutdown()`: Proactive graceful. User wants to stop. State=CLOSED. CANNOT reconnect.
        - `force_close()`: Emergency stop. State=CLOSED. CANNOT reconnect.

        Examples:
            >>> async def main():  # doctest: +SKIP
            ...     ws = WebSocketManager("wss://example.com/ws")
            ...     await ws.connect()
            ...     await ws.force_close()
            ...     # Cannot reconnect after force_close
            ...     assert ws.state == ConnectionState.CLOSED
        """
        self._auto_reconnect = False
        self._state = ConnectionState.CLOSING

        await self._cancel_background_tasks()

        if self._ws is not None:
            await self._ws.close(1000, "Force close")
            self._ws = None

        self._state = ConnectionState.CLOSED
        self._closed_event.set()
        self._disconnected_event.set()

        log.info("WebSocket force closed")

    async def kill(self) -> None:
        """Simulate external disconnection (reactive, we are the victim).

        This simulates a scenario where the server (e.g., Binance) forcefully
        disconnects us. The WebSocket "suffers" this disconnection.

        **Key difference from force_close() and shutdown():**
        - `kill()`: Reactive. Server kicked us. State=DISCONNECTED. CAN reconnect.
        - `shutdown()`: Proactive graceful. User wants to stop. State=CLOSED. CANNOT reconnect.
        - `force_close()`: Emergency stop. State=CLOSED. CANNOT reconnect.

        Use this to test heartbeat/watchdog recovery mechanisms.

        Examples:
            >>> async def main():  # doctest: +SKIP
            ...     ws = WebSocketManager("wss://example.com/ws", auto_reconnect=False)
            ...     await ws.connect()
            ...     await ws.kill()  # Simulates Binance kicking us
            ...     assert ws.state == ConnectionState.DISCONNECTED
            ...     # Heartbeat detects is_dead=True and can restart
        """
        if self._state == ConnectionState.CLOSED:
            log.warning("Cannot kill: already closed")
            return

        log.info("Killing WebSocket (simulating external disconnect)")

        # Cancel background tasks first
        await self._cancel_background_tasks()

        # Close the raw connection if open
        if self._ws is not None:
            with suppress(Exception):
                await self._ws.close(1006, "Killed")
            self._ws = None

        # Move to DISCONNECTED (not CLOSED) so reconnection is possible
        self._state = ConnectionState.DISCONNECTED
        self._connected_event.clear()
        self._disconnected_event.set()

        # Record as reactive disconnect (forced)
        self._stats.record_disconnect(proactive=False)

        # Invoke on_disconnect callback with KILLED reason
        if self._on_disconnect is not None:
            result = self._on_disconnect(DisconnectReason.KILLED)
            if asyncio.iscoroutine(result):
                await result

    async def shutdown(self) -> None:
        """Graceful intentional shutdown (proactive, user-initiated).

        This is for clean shutdown scenarios like CTRL+C or service stop.
        The WebSocket proactively decides to close.

        **Key difference from kill() and force_close():**
        - `kill()`: Reactive. Server kicked us. State=DISCONNECTED. CAN reconnect.
        - `shutdown()`: Proactive graceful. User wants to stop. State=CLOSED. CANNOT reconnect.
        - `force_close()`: Emergency stop. State=CLOSED. CANNOT reconnect.

        Sets the shutdown event so external code (heartbeat, watchdog) knows
        we're stopping intentionally and should not try to restart us.

        Examples:
            >>> async def main():  # doctest: +SKIP
            ...     ws = WebSocketManager("wss://example.com/ws")
            ...     await ws.connect()
            ...     # In SIGINT handler:
            ...     await ws.shutdown()
            ...     assert ws.is_shutdown  # Heartbeat knows not to restart
        """
        log.info("WebSocket shutdown requested")
        self._shutdown_event.set()
        await self.force_close()

    @property
    def is_shutdown(self) -> bool:
        """Check if shutdown has been requested."""
        return self._shutdown_event.is_set()

    @property
    def is_dead(self) -> bool:
        """Check if connection is dead (not connected and not reconnecting).

        Useful for heartbeat monitoring to detect if the WebSocket needs restart.

        Returns:
            True if connection is in a dead state requiring manual intervention.

        Examples:
            >>> async def main():  # doctest: +SKIP
            ...     ws = WebSocketManager("wss://example.com/ws")
            ...     if ws.is_dead:
            ...         await ws.connect()  # Restart
        """
        return self._state in (
            ConnectionState.DISCONNECTED,
            ConnectionState.CLOSED,
        )

    async def close(self) -> None:
        """Gracefully close the connection.

        Alias for force_close() when used in context manager.
        """
        await self.force_close()

    # =========================================================================
    # MESSAGING METHODS
    # =========================================================================

    async def send(self, data: Any) -> None:
        """Send a message to the WebSocket server.

        Args:
            data: Data to send (dict/list will be JSON-encoded).

        Raises:
            WebSocketClosedError: If connection is not active.

        Examples:
            >>> async def main():  # doctest: +SKIP
            ...     async with WebSocketManager("wss://example.com/ws") as ws:
            ...         await ws.send({"type": "ping"})
        """
        if self._ws is None or not self._state.can_send():
            raise WebSocketClosedError(
                "Cannot send: connection not active",
                code=1006,
                reason="Not connected",
            )

        message = json.dumps(data) if isinstance(data, dict | list) else str(data)
        await self._ws.send(message)
        self._stats.record_message_sent(len(message))

    async def receive(self, timeout: float | None = None) -> Any:
        """Receive a single message from the queue.

        Args:
            timeout: Maximum time to wait (seconds).

        Returns:
            The received message.

        Raises:
            WebSocketTimeoutError: If timeout expires.
            WebSocketClosedError: If connection is closed.

        Examples:
            >>> async def main():  # doctest: +SKIP
            ...     async with WebSocketManager("wss://example.com/ws") as ws:
            ...         msg = await ws.receive(timeout=10)
        """
        try:
            if timeout is not None:
                return await asyncio.wait_for(self._message_queue.get(), timeout=timeout)
            return await self._message_queue.get()
        except asyncio.TimeoutError as e:
            raise WebSocketTimeoutError(
                "Receive timed out",
                operation="receive",
                timeout=timeout or 0,
            ) from e

    async def stream(self) -> AsyncIterator[Any]:
        """Iterate over received messages.

        This is the main method for consuming WebSocket messages.
        It handles reconnection transparently.

        Yields:
            Received messages (parsed JSON or raw string).

        Examples:
            >>> async def main():  # doctest: +SKIP
            ...     async with WebSocketManager("wss://example.com/ws") as ws:
            ...         async for msg in ws.stream():
            ...             print(msg)
        """
        while self._state not in (ConnectionState.CLOSED, ConnectionState.CLOSING):
            if self._shutdown_event.is_set():
                break

            try:
                # Wait for connection if disconnected
                if not self.is_connected:
                    if self._state == ConnectionState.CLOSED:
                        break
                    await self._connected_event.wait()

                # Get message with timeout to allow state checking
                try:
                    message = await asyncio.wait_for(
                        self._message_queue.get(),
                        timeout=1.0,
                    )
                    yield message
                except asyncio.TimeoutError:
                    continue

            except asyncio.CancelledError:
                break

    # =========================================================================
    # SUBSCRIPTION METHODS
    # =========================================================================

    async def subscribe(self, *channels: str) -> None:
        """Subscribe to one or more channels.

        Subscriptions are automatically restored after reconnection.

        Args:
            channels: Channel names to subscribe to.

        Examples:
            >>> async def main():  # doctest: +SKIP
            ...     async with WebSocketManager("wss://stream.binance.com/ws") as ws:
            ...         await ws.subscribe("btcusdt@trade", "ethusdt@trade")
        """
        for channel in channels:
            if channel not in self._subscriptions:
                self._subscriptions.add(channel)
                if self.is_connected:
                    await self._send_subscribe(channel)

    async def unsubscribe(self, *channels: str) -> None:
        """Unsubscribe from one or more channels.

        Args:
            channels: Channel names to unsubscribe from.

        Examples:
            >>> async def main():  # doctest: +SKIP
            ...     async with WebSocketManager("wss://stream.binance.com/ws") as ws:
            ...         await ws.unsubscribe("btcusdt@trade")
        """
        for channel in channels:
            self._subscriptions.discard(channel)
            if self.is_connected and self._ws is not None:
                message = json.dumps({"type": "unsubscribe", "channel": channel})
                await self._ws.send(message)

    # =========================================================================
    # WAIT METHODS
    # =========================================================================

    async def wait_connected(self, timeout: float | None = None) -> bool:
        """Wait until connected.

        Args:
            timeout: Maximum time to wait (seconds).

        Returns:
            True if connected, False if timed out.
        """
        try:
            if timeout is not None:
                await asyncio.wait_for(self._connected_event.wait(), timeout=timeout)
            else:
                await self._connected_event.wait()
            return True
        except asyncio.TimeoutError:
            return False

    async def wait_disconnected(self, timeout: float | None = None) -> bool:
        """Wait until disconnected.

        Args:
            timeout: Maximum time to wait (seconds).

        Returns:
            True if disconnected, False if timed out.
        """
        try:
            if timeout is not None:
                await asyncio.wait_for(self._disconnected_event.wait(), timeout=timeout)
            else:
                await self._disconnected_event.wait()
            return True
        except asyncio.TimeoutError:
            return False
