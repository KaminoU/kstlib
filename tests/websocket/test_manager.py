"""Tests for kstlib.websocket.manager module."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kstlib.websocket.models import ConnectionState, DisconnectReason, ReconnectStrategy

# Skip all tests if websockets is not installed
pytestmark = pytest.mark.skipif(
    not pytest.importorskip("websockets", reason="websockets not installed"),
    reason="websockets not installed",
)


class TestWebSocketManagerInit:
    """Tests for WebSocketManager initialization."""

    def test_init_with_url(self) -> None:
        """WebSocketManager initializes with URL."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        assert ws.url == "wss://example.com/ws"
        assert ws.state == ConnectionState.DISCONNECTED

    def test_init_with_custom_ping_interval(self) -> None:
        """WebSocketManager accepts custom ping interval."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws", ping_interval=15.0)
        assert ws._ping_interval == 15.0

    def test_init_with_custom_ping_timeout(self) -> None:
        """WebSocketManager accepts custom ping timeout."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws", ping_timeout=8.0)
        assert ws._ping_timeout == 8.0

    def test_init_with_custom_connection_timeout(self) -> None:
        """WebSocketManager accepts custom connection timeout."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws", connection_timeout=45.0)
        assert ws._connection_timeout == 45.0

    def test_init_with_custom_reconnect_strategy(self) -> None:
        """WebSocketManager accepts custom reconnect strategy."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager(
            "wss://example.com/ws",
            reconnect_strategy=ReconnectStrategy.FIXED_DELAY,
        )
        assert ws._reconnect_strategy == ReconnectStrategy.FIXED_DELAY

    def test_init_with_custom_reconnect_delay(self) -> None:
        """WebSocketManager accepts custom reconnect delay."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws", reconnect_delay=2.0)
        assert ws._reconnect_delay == 2.0

    def test_init_with_custom_max_reconnect_attempts(self) -> None:
        """WebSocketManager accepts custom max reconnect attempts."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws", max_reconnect_attempts=20)
        assert ws._max_reconnect_attempts == 20

    def test_init_with_auto_reconnect_disabled(self) -> None:
        """WebSocketManager can disable auto reconnect."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws", auto_reconnect=False)
        assert ws._auto_reconnect is False

    def test_init_with_queue_size(self) -> None:
        """WebSocketManager accepts custom queue size."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws", queue_size=500)
        assert ws._queue_size == 500

    def test_init_uses_config_limits(self) -> None:
        """WebSocketManager uses config limits when no kwargs provided."""
        from kstlib.websocket import WebSocketManager

        config = {
            "websocket": {
                "ping": {"interval": 25.0},
                "reconnect": {"max_attempts": 15},
            }
        }
        ws = WebSocketManager("wss://example.com/ws", config=config)
        assert ws._ping_interval == 25.0
        assert ws._max_reconnect_attempts == 15

    def test_init_kwargs_override_config(self) -> None:
        """WebSocketManager kwargs override config values."""
        from kstlib.websocket import WebSocketManager

        config = {
            "websocket": {
                "ping": {"interval": 25.0},
            }
        }
        ws = WebSocketManager("wss://example.com/ws", ping_interval=30.0, config=config)
        assert ws._ping_interval == 30.0  # kwargs win


class TestWebSocketManagerProperties:
    """Tests for WebSocketManager properties."""

    def test_is_connected_when_disconnected(self) -> None:
        """is_connected returns False when disconnected."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        assert ws.is_connected is False

    def test_subscriptions_initially_empty(self) -> None:
        """subscriptions is initially empty frozenset."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        assert ws.subscriptions == frozenset()

    def test_connection_duration_when_not_connected(self) -> None:
        """connection_duration returns 0 when not connected."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        assert ws.connection_duration == 0.0

    def test_stats_initially_zero(self) -> None:
        """stats are initially zero."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        assert ws.stats.connects == 0
        assert ws.stats.disconnects == 0
        assert ws.stats.messages_received == 0


class TestWebSocketManagerCallbacks:
    """Tests for WebSocketManager callback handling."""

    def test_should_disconnect_callback_stored(self) -> None:
        """should_disconnect callback is stored."""
        from kstlib.websocket import WebSocketManager

        def callback() -> bool:
            return True

        ws = WebSocketManager("wss://example.com/ws", should_disconnect=callback)
        assert ws._should_disconnect is callback

    def test_should_reconnect_callback_stored(self) -> None:
        """should_reconnect callback is stored."""
        from kstlib.websocket import WebSocketManager

        def callback() -> bool:
            return True

        ws = WebSocketManager("wss://example.com/ws", should_reconnect=callback)
        assert ws._should_reconnect is callback

    def test_on_connect_callback_stored(self) -> None:
        """on_connect callback is stored."""
        from kstlib.websocket import WebSocketManager

        async def callback() -> None:
            pass

        ws = WebSocketManager("wss://example.com/ws", on_connect=callback)
        assert ws._on_connect is callback

    def test_on_disconnect_callback_stored(self) -> None:
        """on_disconnect callback is stored."""
        from kstlib.websocket import WebSocketManager

        async def callback(reason: DisconnectReason) -> None:
            pass

        ws = WebSocketManager("wss://example.com/ws", on_disconnect=callback)
        assert ws._on_disconnect is callback

    def test_on_message_callback_stored(self) -> None:
        """on_message callback is stored."""
        from kstlib.websocket import WebSocketManager

        async def callback(data: Any) -> None:
            pass

        ws = WebSocketManager("wss://example.com/ws", on_message=callback)
        assert ws._on_message is callback


class TestWebSocketManagerContextManager:
    """Tests for WebSocketManager async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager_connects_and_closes(self) -> None:
        """Context manager connects on enter and closes on exit."""
        from kstlib.websocket import WebSocketManager
        from kstlib.websocket import manager as ws_manager

        mock_ws = MagicMock()
        mock_ws.close = AsyncMock()

        with patch.object(ws_manager, "connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_ws)
            mock_connect.return_value = mock_ws

            # Create mock async iterator
            async def mock_iter() -> None:
                await asyncio.sleep(10)

            mock_ws.__aiter__ = lambda self: mock_iter()

            ws = WebSocketManager("wss://example.com/ws")

            # Mock successful connection
            async def connect_side_effect(*args: Any, **kwargs: Any) -> MagicMock:
                return mock_ws

            mock_connect.side_effect = connect_side_effect

            async with ws:
                assert ws.state == ConnectionState.CONNECTED

            # close() graceful semantic : DISCONNECTED non-terminal, reconnect possible
            assert ws.state == ConnectionState.DISCONNECTED


class TestWebSocketManagerStateMachine:
    """Tests for WebSocketManager state transitions."""

    def test_initial_state_is_disconnected(self) -> None:
        """Initial state is DISCONNECTED."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        assert ws.state == ConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_cannot_connect_from_connected_state(self) -> None:
        """Cannot connect when already connected."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CONNECTED  # Force state

        # Should log warning and return without action
        await ws.connect()
        # State unchanged
        assert ws.state == ConnectionState.CONNECTED


class TestWebSocketManagerUrlRedaction:
    """Verify URL credentials/tokens never leak through the connect log."""

    @pytest.mark.asyncio
    async def test_finalize_connection_redacts_credentials(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """_finalize_connection logs INFO with userinfo masked."""
        import logging

        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://user:supersecret@host.example.com:8443/ws?token=tk_xyz_abc")
        ws._on_connect = None
        ws._subscriptions = {}
        # _start_background_tasks is the only sub-call inside _finalize_connection
        # we need to neutralize. Mocking it avoids the AsyncMock-coroutine-never-awaited
        # warning that would arise from stubbing the underlying async loop.
        ws._start_background_tasks = MagicMock()

        caplog.set_level(logging.INFO, logger="kstlib.websocket.manager")

        await ws._finalize_connection()

        info_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
        assert info_messages, "Expected at least one INFO record from _finalize_connection"
        joined = " ".join(info_messages)
        assert "supersecret" not in joined
        assert "tk_xyz_abc" not in joined
        assert "[REDACTED]@host.example.com" in joined
        assert "token=[REDACTED]" in joined


class TestWebSocketManagerSendReceive:
    """Tests for WebSocketManager send/receive operations."""

    @pytest.mark.asyncio
    async def test_send_raises_when_not_connected(self) -> None:
        """send raises WebSocketClosedError when not connected."""
        from kstlib.websocket import WebSocketManager
        from kstlib.websocket.exceptions import WebSocketClosedError

        ws = WebSocketManager("wss://example.com/ws")

        with pytest.raises(WebSocketClosedError):
            await ws.send({"test": "data"})

    @pytest.mark.asyncio
    async def test_receive_timeout(self) -> None:
        """receive raises WebSocketTimeoutError on timeout."""
        from kstlib.websocket import WebSocketManager
        from kstlib.websocket.exceptions import WebSocketTimeoutError

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CONNECTED

        with pytest.raises(WebSocketTimeoutError):
            await ws.receive(timeout=0.01)


class TestWebSocketManagerSubscriptions:
    """Tests for WebSocketManager subscription management."""

    def test_subscriptions_empty_initially(self) -> None:
        """Subscriptions are empty initially."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        assert len(ws.subscriptions) == 0

    @pytest.mark.asyncio
    async def test_subscribe_adds_to_set(self) -> None:
        """subscribe adds channel to subscriptions set."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        # Not connected, so won't try to send
        await ws.subscribe("btcusdt@trade")
        assert "btcusdt@trade" in ws.subscriptions

    @pytest.mark.asyncio
    async def test_subscribe_multiple_channels(self) -> None:
        """subscribe can add multiple channels."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        await ws.subscribe("btcusdt@trade", "ethusdt@trade")
        assert "btcusdt@trade" in ws.subscriptions
        assert "ethusdt@trade" in ws.subscriptions

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_from_set(self) -> None:
        """unsubscribe removes channel from subscriptions set."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        await ws.subscribe("btcusdt@trade")
        await ws.unsubscribe("btcusdt@trade")
        assert "btcusdt@trade" not in ws.subscriptions

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent_channel_no_error(self) -> None:
        """unsubscribe on non-existent channel does not error."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        # Should not raise
        await ws.unsubscribe("nonexistent@channel")

    @pytest.mark.asyncio
    async def test_subscribe_when_connected_sends_message(self) -> None:
        """subscribe sends subscribe message when connected."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CONNECTED
        ws._send_subscribe = AsyncMock()

        await ws.subscribe("btcusdt@trade")

        assert "btcusdt@trade" in ws._subscriptions
        ws._send_subscribe.assert_called_once_with("btcusdt@trade")

    @pytest.mark.asyncio
    async def test_unsubscribe_when_connected_sends_message(self) -> None:
        """unsubscribe sends unsubscribe message when connected."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CONNECTED
        ws._subscriptions.add("btcusdt@trade")
        ws._ws = MagicMock()
        ws._ws.send = AsyncMock()

        await ws.unsubscribe("btcusdt@trade")

        assert "btcusdt@trade" not in ws._subscriptions
        ws._ws.send.assert_called_once()


class TestWebSocketManagerWaitMethods:
    """Tests for WebSocketManager wait methods."""

    @pytest.mark.asyncio
    async def test_wait_connected_times_out(self) -> None:
        """wait_connected returns False on timeout."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        result = await ws.wait_connected(timeout=0.01)
        assert result is False

    @pytest.mark.asyncio
    async def test_wait_connected_returns_true_when_signaled(self) -> None:
        """wait_connected returns True when connected event is set."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")

        async def set_event() -> None:
            await asyncio.sleep(0.01)
            ws._connected_event.set()

        asyncio.create_task(set_event())
        result = await ws.wait_connected(timeout=1.0)
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_disconnected_returns_immediately_when_disconnected(self) -> None:
        """wait_disconnected returns immediately when already disconnected."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        result = await ws.wait_disconnected(timeout=0.01)
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_disconnected_returns_true_when_signaled(self) -> None:
        """wait_disconnected returns True when disconnected event is set."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._connected_event.set()  # Simulate connected
        ws._disconnected_event.clear()

        async def set_event() -> None:
            await asyncio.sleep(0.01)
            ws._disconnected_event.set()

        asyncio.create_task(set_event())
        result = await ws.wait_disconnected(timeout=1.0)
        assert result is True


class TestWebSocketManagerForceClose:
    """Tests for WebSocketManager force_close method."""

    @pytest.mark.asyncio
    async def test_force_close_sets_closed_state(self) -> None:
        """force_close sets state to CLOSED."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        await ws.force_close()
        assert ws.state == ConnectionState.CLOSED

    @pytest.mark.asyncio
    async def test_force_close_disables_auto_reconnect(self) -> None:
        """force_close disables auto_reconnect."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws", auto_reconnect=True)
        await ws.force_close()
        assert ws._auto_reconnect is False

    @pytest.mark.asyncio
    async def test_force_close_sets_shutdown_event(self) -> None:
        """force_close sets is_shutdown (intentional emergency marker)."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        assert ws.is_shutdown is False
        await ws.force_close()
        assert ws.is_shutdown is True


class TestCloseMethodGraceful:
    """Tests for WebSocketManager.close() graceful semantic (non-terminal, reconnect possible)."""

    @pytest.mark.asyncio
    async def test_close_sets_state_disconnected_graceful(self) -> None:
        """close() sets DISCONNECTED non-terminal (graceful semantic, reconnect possible)."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CONNECTED
        await ws.close()
        assert ws.state == ConnectionState.DISCONNECTED
        assert ws.state.is_terminal() is False

    @pytest.mark.asyncio
    async def test_close_preserves_auto_reconnect(self) -> None:
        """close() does NOT touch _auto_reconnect (graceful preserves config)."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws", auto_reconnect=True)
        ws._state = ConnectionState.CONNECTED
        await ws.close()
        assert ws._auto_reconnect is True

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self) -> None:
        """close() is idempotent (no-op if state already CLOSED or DISCONNECTED)."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        # Initial state DISCONNECTED : close() is a no-op
        await ws.close()
        assert ws.state == ConnectionState.DISCONNECTED

        # State CLOSED : close() is a no-op (no exception, no transition)
        ws._state = ConnectionState.CLOSED
        await ws.close()
        assert ws.state == ConnectionState.CLOSED


class TestWebSocketManagerConnectionDuration:
    """Tests for connection_duration property."""

    def test_connection_duration_zero_when_not_connected(self) -> None:
        """connection_duration returns 0 when never connected."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        assert ws.connection_duration == 0.0

    def test_connection_duration_positive_when_connected(self) -> None:
        """connection_duration returns positive value when connected."""
        import time

        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._connect_time = time.monotonic() - 1.0  # Simulate 1 second ago
        assert ws.connection_duration >= 0.9
        assert ws.connection_duration < 2.0


class TestWebSocketManagerStream:
    """Tests for stream() async generator."""

    @pytest.mark.asyncio
    async def test_stream_yields_messages_from_queue(self) -> None:
        """stream yields messages from the internal queue."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CONNECTED
        ws._connected_event.set()

        # Add messages to queue
        await ws._message_queue.put({"type": "test", "data": 1})
        await ws._message_queue.put({"type": "test", "data": 2})

        messages: list[Any] = []
        async for msg in ws.stream():
            messages.append(msg)
            if len(messages) >= 2:
                await ws.force_close()

        assert len(messages) == 2
        assert messages[0] == {"type": "test", "data": 1}
        assert messages[1] == {"type": "test", "data": 2}

    @pytest.mark.asyncio
    async def test_stream_exits_on_closed_state(self) -> None:
        """stream exits when state is CLOSED."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CLOSED

        messages: list[Any] = []
        async for msg in ws.stream():
            messages.append(msg)

        assert len(messages) == 0

    @pytest.mark.asyncio
    async def test_stream_waits_for_connection(self) -> None:
        """stream waits for connection when disconnected."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")

        async def connect_later() -> None:
            await asyncio.sleep(0.02)
            ws._state = ConnectionState.CONNECTED
            ws._connected_event.set()
            await ws._message_queue.put({"msg": "connected"})
            await asyncio.sleep(0.02)
            await ws.force_close()

        asyncio.create_task(connect_later())

        messages: list[Any] = []
        async for msg in ws.stream():
            messages.append(msg)

        assert len(messages) == 1
        assert messages[0] == {"msg": "connected"}


class TestWebSocketManagerReceive:
    """Tests for receive() method."""

    @pytest.mark.asyncio
    async def test_receive_returns_message_from_queue(self) -> None:
        """receive returns message from queue."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CONNECTED

        # Add message to queue
        await ws._message_queue.put({"test": "data"})

        result = await ws.receive(timeout=1.0)
        assert result == {"test": "data"}

    @pytest.mark.asyncio
    async def test_receive_raises_timeout_when_no_message(self) -> None:
        """receive raises WebSocketTimeoutError when queue is empty."""
        from kstlib.websocket import WebSocketManager
        from kstlib.websocket.exceptions import WebSocketTimeoutError

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CONNECTED

        with pytest.raises(WebSocketTimeoutError):
            await ws.receive(timeout=0.01)


class TestWebSocketManagerSend:
    """Tests for send() method."""

    @pytest.mark.asyncio
    async def test_send_string_message(self) -> None:
        """send handles string messages."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CONNECTED
        ws._ws = MagicMock()
        ws._ws.send = AsyncMock()

        await ws.send("test message")
        ws._ws.send.assert_called_once_with("test message")

    @pytest.mark.asyncio
    async def test_send_dict_message(self) -> None:
        """send serializes dict to JSON."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CONNECTED
        ws._ws = MagicMock()
        ws._ws.send = AsyncMock()

        await ws.send({"key": "value"})
        ws._ws.send.assert_called_once_with('{"key": "value"}')


class TestWebSocketManagerIsConnected:
    """Tests for is_connected property."""

    def test_is_connected_true_when_connected(self) -> None:
        """is_connected returns True when state is CONNECTED."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CONNECTED
        assert ws.is_connected is True

    def test_is_connected_false_when_disconnected(self) -> None:
        """is_connected returns False when state is DISCONNECTED."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        assert ws.is_connected is False

    def test_is_connected_false_when_reconnecting(self) -> None:
        """is_connected returns False when state is RECONNECTING."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.RECONNECTING
        assert ws.is_connected is False


class TestWebSocketManagerConfigFromDict:
    """Tests for config dict loading."""

    def test_config_overrides_defaults(self) -> None:
        """Config dict overrides default values."""
        from kstlib.websocket import WebSocketManager

        config = {
            "websocket": {
                "ping": {"interval": 25.0, "timeout": 12.0},
                "reconnect": {"delay": 2.0, "max_attempts": 15},
            }
        }

        ws = WebSocketManager("wss://example.com/ws", config=config)
        assert ws._ping_interval == 25.0
        assert ws._ping_timeout == 12.0
        assert ws._reconnect_delay == 2.0
        assert ws._max_reconnect_attempts == 15


class TestWebSocketManagerStatsObject:
    """Tests for stats property and WebSocketStats reset."""

    def test_stats_returns_websocket_stats(self) -> None:
        """stats property returns a WebSocketStats object."""
        from kstlib.websocket import WebSocketManager
        from kstlib.websocket.models import WebSocketStats

        ws = WebSocketManager("wss://example.com/ws")
        assert isinstance(ws.stats, WebSocketStats)

    def test_stats_records_operations(self) -> None:
        """stats object correctly records operations."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")

        # Record some operations
        ws._stats.record_connect()
        ws._stats.record_message_received(100)
        ws._stats.record_message_sent(50)
        ws._stats.record_disconnect(proactive=True)

        assert ws.stats.connects == 1
        assert ws.stats.messages_received == 1
        assert ws.stats.bytes_received == 100
        assert ws.stats.messages_sent == 1
        assert ws.stats.bytes_sent == 50
        assert ws.stats.disconnects == 1
        assert ws.stats.proactive_disconnects == 1

    def test_stats_reset_clears_counters(self) -> None:
        """WebSocketStats.reset() clears all counters."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")

        ws._stats.record_connect()
        ws._stats.record_message_received(100)

        assert ws.stats.connects > 0

        ws._stats.reset()

        assert ws.stats.connects == 0
        assert ws.stats.messages_received == 0


class TestWebSocketManagerKill:
    """Tests for WebSocketManager kill method."""

    @pytest.mark.asyncio
    async def test_kill_sets_disconnected_state(self) -> None:
        """kill sets state to DISCONNECTED (not CLOSED)."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CONNECTED
        await ws.kill()
        assert ws.state == ConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_kill_does_not_set_closed_state(self) -> None:
        """kill allows reconnection (unlike force_close)."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CONNECTED
        await ws.kill()
        assert ws.state != ConnectionState.CLOSED

    @pytest.mark.asyncio
    async def test_kill_from_closed_state_logs_warning(self) -> None:
        """kill from CLOSED state logs warning and returns early."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CLOSED
        await ws.kill()
        assert ws.state == ConnectionState.CLOSED

    @pytest.mark.asyncio
    async def test_kill_invokes_on_disconnect_callback(self) -> None:
        """kill invokes on_disconnect callback with KILLED reason."""
        from kstlib.websocket import WebSocketManager

        callback_called = False
        callback_reason = None

        def on_disconnect(reason: DisconnectReason) -> None:
            nonlocal callback_called, callback_reason
            callback_called = True
            callback_reason = reason

        ws = WebSocketManager("wss://example.com/ws", on_disconnect=on_disconnect)
        ws._state = ConnectionState.CONNECTED
        await ws.kill()

        assert callback_called
        assert callback_reason == DisconnectReason.KILLED

    @pytest.mark.asyncio
    async def test_kill_records_reactive_disconnect(self) -> None:
        """kill records disconnect as reactive (not proactive)."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CONNECTED
        await ws.kill()

        assert ws.stats.disconnects == 1
        assert ws.stats.proactive_disconnects == 0

    @pytest.mark.asyncio
    async def test_kill_does_not_set_shutdown_event(self) -> None:
        """kill() (reactive server kick) does NOT mark is_shutdown."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws", auto_reconnect=False)
        ws._state = ConnectionState.CONNECTED
        await ws.kill()
        assert ws.is_shutdown is False
        assert ws.state == ConnectionState.DISCONNECTED


class TestWebSocketManagerShutdown:
    """Tests for WebSocketManager shutdown method."""

    @pytest.mark.asyncio
    async def test_shutdown_sets_shutdown_event(self) -> None:
        """shutdown sets the shutdown event."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        assert not ws.is_shutdown
        await ws.shutdown()
        assert ws.is_shutdown

    @pytest.mark.asyncio
    async def test_shutdown_closes_connection(self) -> None:
        """shutdown closes the connection."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        await ws.shutdown()
        assert ws.state == ConnectionState.CLOSED


class TestWebSocketManagerIsDead:
    """Tests for WebSocketManager is_dead property."""

    def test_is_dead_true_when_disconnected(self) -> None:
        """is_dead returns True when DISCONNECTED."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.DISCONNECTED
        assert ws.is_dead is True

    def test_is_dead_true_when_closed(self) -> None:
        """is_dead returns True when CLOSED."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CLOSED
        assert ws.is_dead is True

    def test_is_dead_false_when_connected(self) -> None:
        """is_dead returns False when CONNECTED."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CONNECTED
        assert ws.is_dead is False

    def test_is_dead_false_when_reconnecting(self) -> None:
        """is_dead returns False when RECONNECTING."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.RECONNECTING
        assert ws.is_dead is False

    def test_is_dead_false_when_connecting(self) -> None:
        """is_dead returns False when CONNECTING."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CONNECTING
        assert ws.is_dead is False


class TestIsRecoverable:
    """Tests for is_recoverable property (helper for watchdog consumers)."""

    @pytest.mark.asyncio
    async def test_is_recoverable_true_after_close_graceful(self) -> None:
        """close() graceful -> is_recoverable True (reconnect possible)."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CONNECTED
        await ws.close()
        assert ws.is_dead is True
        assert ws.is_shutdown is False
        assert ws.is_recoverable is True

    @pytest.mark.asyncio
    async def test_is_recoverable_true_after_kill(self) -> None:
        """kill() reactive -> is_recoverable True (auto_reconnect via watchdog)."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws", auto_reconnect=False)
        ws._state = ConnectionState.CONNECTED
        await ws.kill()
        assert ws.is_dead is True
        assert ws.is_shutdown is False
        assert ws.is_recoverable is True

    @pytest.mark.asyncio
    async def test_is_recoverable_false_after_force_close(self) -> None:
        """force_close() emergency -> is_recoverable False (intentional terminal)."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CONNECTED
        await ws.force_close()
        assert ws.is_dead is True
        assert ws.is_shutdown is True
        assert ws.is_recoverable is False

    @pytest.mark.asyncio
    async def test_is_recoverable_false_after_shutdown(self) -> None:
        """shutdown() intentional -> is_recoverable False (do not restart)."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CONNECTED
        await ws.shutdown()
        assert ws.is_dead is True
        assert ws.is_shutdown is True
        assert ws.is_recoverable is False

    def test_is_recoverable_false_when_connected(self) -> None:
        """state CONNECTED -> is_recoverable False (is_dead=False)."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CONNECTED
        assert ws.is_dead is False
        assert ws.is_recoverable is False


class TestWebSocketManagerCloseMethods:
    """Tests comparing kill(), shutdown(), and force_close() behaviors."""

    @pytest.mark.asyncio
    async def test_kill_vs_shutdown_vs_force_close_states(self) -> None:
        """Compare final states: kill=DISCONNECTED reactive, shutdown/force_close=CLOSED intentional."""
        from kstlib.websocket import WebSocketManager

        # kill() -> DISCONNECTED (reactive, can reconnect, NOT is_shutdown)
        ws1 = WebSocketManager("wss://example.com/ws")
        ws1._state = ConnectionState.CONNECTED
        await ws1.kill()
        assert ws1.state == ConnectionState.DISCONNECTED
        assert ws1.state.can_connect()  # CAN reconnect
        assert not ws1.is_shutdown  # Reactive, flag is NOT set

        # shutdown() -> CLOSED (intentional, cannot reconnect, is_shutdown=True)
        ws2 = WebSocketManager("wss://example.com/ws")
        ws2._state = ConnectionState.CONNECTED
        await ws2.shutdown()
        assert ws2.state == ConnectionState.CLOSED
        assert not ws2.state.can_connect()  # CANNOT reconnect
        assert ws2.is_shutdown  # Intentional, flag IS set

        # force_close() -> CLOSED (intentional emergency, cannot reconnect, is_shutdown=True)
        ws3 = WebSocketManager("wss://example.com/ws")
        ws3._state = ConnectionState.CONNECTED
        await ws3.force_close()
        assert ws3.state == ConnectionState.CLOSED
        assert not ws3.state.can_connect()  # CANNOT reconnect
        assert ws3.is_shutdown  # Intentional emergency, flag IS set

    @pytest.mark.asyncio
    async def test_kill_records_reactive_disconnect(self) -> None:
        """kill records as reactive (forced) disconnect in stats."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CONNECTED
        await ws.kill()

        assert ws.stats.disconnects == 1
        assert ws.stats.proactive_disconnects == 0  # NOT proactive


class _RaisingAsyncIter:
    """Async iterator that raises an exception on first __anext__ call."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def __aiter__(self) -> _RaisingAsyncIter:
        return self

    async def __anext__(self) -> Any:
        raise self._exc


class TestReceiveLoopCleanClose:
    """Tests for _receive_loop handling of ConnectionClosedOK."""

    @pytest.mark.asyncio
    async def test_connection_closed_ok_calls_handle_disconnect(self) -> None:
        """ConnectionClosedOK triggers _handle_disconnect with SERVER_CLOSED."""
        from websockets.exceptions import ConnectionClosedOK
        from websockets.frames import Close

        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws", auto_reconnect=True)
        ws._state = ConnectionState.CONNECTED

        exc = ConnectionClosedOK(Close(1000, "normal closure"), None)
        ws._ws = _RaisingAsyncIter(exc)

        ws._handle_disconnect = AsyncMock()
        await ws._receive_loop()

        ws._handle_disconnect.assert_called_once_with(
            DisconnectReason.SERVER_CLOSED,
            code=1000,
        )

    @pytest.mark.asyncio
    async def test_connection_closed_ok_passes_close_code(self) -> None:
        """ConnectionClosedOK passes the close code to _handle_disconnect."""
        from websockets.exceptions import ConnectionClosedOK
        from websockets.frames import Close

        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CONNECTED

        exc = ConnectionClosedOK(Close(1001, "going away"), None)
        ws._ws = _RaisingAsyncIter(exc)

        ws._handle_disconnect = AsyncMock()
        await ws._receive_loop()

        call_kwargs = ws._handle_disconnect.call_args
        assert call_kwargs[1]["code"] == 1001

    @pytest.mark.asyncio
    async def test_connection_closed_ok_triggers_reconnect(self) -> None:
        """ConnectionClosedOK triggers _attempt_reconnect when auto_reconnect=True."""
        from websockets.exceptions import ConnectionClosedOK
        from websockets.frames import Close

        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws", auto_reconnect=True)
        ws._state = ConnectionState.CONNECTED

        exc = ConnectionClosedOK(Close(1000, "normal closure"), None)
        ws._ws = _RaisingAsyncIter(exc)

        ws._attempt_reconnect = AsyncMock()
        await ws._receive_loop()

        ws._attempt_reconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_connection_closed_ok_no_reconnect_when_disabled(self) -> None:
        """ConnectionClosedOK does not reconnect when auto_reconnect=False."""
        from websockets.exceptions import ConnectionClosedOK
        from websockets.frames import Close

        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws", auto_reconnect=False)
        ws._state = ConnectionState.CONNECTED

        exc = ConnectionClosedOK(Close(1000, "normal closure"), None)
        ws._ws = _RaisingAsyncIter(exc)

        ws._attempt_reconnect = AsyncMock()
        await ws._receive_loop()

        ws._attempt_reconnect.assert_not_called()
        assert ws.state == ConnectionState.DISCONNECTED


class TestIntegrationAsyncWithPatterns:
    """Integration tests for the async with + stream pattern (validates close graceful fix)."""

    @pytest.mark.asyncio
    async def test_async_with_long_running_voluntary_exit_allows_reconnect(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """async with + voluntary break exits gracefully, then reconnect possible.

        Validates the primary fix : pre-C2 the async with exit triggered
        close() == force_close() == CLOSED terminal, preventing any
        reconnect. Post-C2 close() is graceful (DISCONNECTED non-terminal)
        and reconnect via explicit connect() works.
        """
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")

        async def fake_connect() -> None:
            ws._state = ConnectionState.CONNECTED
            ws._connected_event.set()

        monkeypatch.setattr(ws, "connect", fake_connect)

        for i in range(3):
            await ws._message_queue.put({"msg": i})

        received: list[Any] = []
        async with ws:
            async for msg in ws.stream():
                received.append(msg)
                if len(received) >= 3:
                    break

        # close() graceful : DISCONNECTED non-terminal, is_recoverable True
        assert ws.state == ConnectionState.DISCONNECTED
        assert ws.state.is_terminal() is False
        assert ws.is_recoverable is True
        assert len(received) == 3

        # Semantic guard permits reconnect
        assert ws.state.can_connect() is True

        # Reconnect works
        await ws.connect()
        assert ws.state == ConnectionState.CONNECTED

    @pytest.mark.asyncio
    async def test_force_close_terminal_blocks_reconnect(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """force_close() emergency keeps CLOSED terminal + blocks reconnect (semantic guard)."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")

        async def fake_connect() -> None:
            ws._state = ConnectionState.CONNECTED
            ws._connected_event.set()

        monkeypatch.setattr(ws, "connect", fake_connect)
        await ws.connect()
        await ws.force_close()

        assert ws.state == ConnectionState.CLOSED
        assert ws.state.is_terminal() is True
        assert ws.is_shutdown is True
        assert ws.is_recoverable is False
        # Semantic guard : CLOSED is not in can_connect()
        assert ws.state.can_connect() is False

    @pytest.mark.asyncio
    async def test_kill_reactive_reconnect_possible(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """kill() reactive (simulated server disconnect) allows reconnect."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws", auto_reconnect=False)

        async def fake_connect() -> None:
            ws._state = ConnectionState.CONNECTED
            ws._connected_event.set()

        monkeypatch.setattr(ws, "connect", fake_connect)
        await ws.connect()
        await ws.kill()

        assert ws.state == ConnectionState.DISCONNECTED
        assert ws.is_shutdown is False
        assert ws.is_recoverable is True
        assert ws.state.can_connect() is True

        # Reconnect works
        await ws.connect()
        assert ws.state == ConnectionState.CONNECTED

    @pytest.mark.asyncio
    async def test_async_with_exception_propagation_graceful_close(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Exception in async with body propagates, but close() stays graceful.

        Validates the symmetric case to voluntary exit : when an exception
        bubbles out of the async with body, __aexit__ still calls close()
        graceful (not force_close). State ends DISCONNECTED non-terminal
        so the caller can recover via reconnect.
        """
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")

        async def fake_connect() -> None:
            ws._state = ConnectionState.CONNECTED
            ws._connected_event.set()

        monkeypatch.setattr(ws, "connect", fake_connect)

        with pytest.raises(ValueError, match="simulated downstream exception"):
            async with ws:
                raise ValueError("simulated downstream exception")

        # Exception propagated, but close graceful
        assert ws.state == ConnectionState.DISCONNECTED
        assert ws.is_shutdown is False
        assert ws.is_recoverable is True
        assert ws.state.can_connect() is True
