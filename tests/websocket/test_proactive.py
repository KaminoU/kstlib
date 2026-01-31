"""Tests for WebSocketManager proactive control features."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from kstlib.websocket.models import ConnectionState, DisconnectReason

# Skip all tests if websockets is not installed
pytestmark = pytest.mark.skipif(
    not pytest.importorskip("websockets", reason="websockets not installed"),
    reason="websockets not installed",
)


class TestRequestDisconnect:
    """Tests for WebSocketManager.request_disconnect method."""

    @pytest.mark.asyncio
    async def test_request_disconnect_from_disconnected_state(self) -> None:
        """request_disconnect does nothing when already disconnected."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        assert ws.state == ConnectionState.DISCONNECTED

        # Should return without error
        await ws.request_disconnect()
        assert ws.state == ConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_request_disconnect_stores_reconnect_after(self) -> None:
        """request_disconnect stores reconnect_after delay."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CONNECTED
        ws._ws = MagicMock()
        ws._ws.close = AsyncMock()

        # Mock _handle_disconnect to prevent actual disconnect logic
        ws._handle_disconnect = AsyncMock()

        await ws.request_disconnect(reconnect_after=300.0)
        assert ws._scheduled_reconnect_delay == 300.0

    @pytest.mark.asyncio
    async def test_request_disconnect_with_custom_reason(self) -> None:
        """request_disconnect accepts custom reason."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CONNECTED
        ws._ws = MagicMock()
        ws._ws.close = AsyncMock()
        ws._handle_disconnect = AsyncMock()

        await ws.request_disconnect(reason=DisconnectReason.CONNECTION_LIMIT)
        ws._handle_disconnect.assert_called_once_with(DisconnectReason.CONNECTION_LIMIT)


class TestScheduleReconnect:
    """Tests for WebSocketManager.schedule_reconnect method."""

    @pytest.mark.asyncio
    async def test_schedule_reconnect_from_connected_state(self) -> None:
        """schedule_reconnect does nothing when connected."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CONNECTED

        # Should return without action
        await ws.schedule_reconnect(10.0)
        assert ws.state == ConnectionState.CONNECTED

    @pytest.mark.asyncio
    async def test_schedule_reconnect_sets_reconnecting_state(self) -> None:
        """schedule_reconnect sets state to RECONNECTING."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        assert ws.state == ConnectionState.DISCONNECTED

        # Mock _attempt_reconnect to prevent actual reconnection
        ws._attempt_reconnect = AsyncMock()

        # Use a short delay for testing
        task = asyncio.create_task(ws.schedule_reconnect(0.01))
        await asyncio.sleep(0.001)  # Let it start
        assert ws.state == ConnectionState.RECONNECTING
        await task


class TestWaitForReconnectWindow:
    """Tests for WebSocketManager.wait_for_reconnect_window method."""

    @pytest.mark.asyncio
    async def test_wait_for_reconnect_window_no_callback(self) -> None:
        """wait_for_reconnect_window returns False when no callback."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")

        result = await ws.wait_for_reconnect_window(timeout=0.01)
        assert result is False

    @pytest.mark.asyncio
    async def test_wait_for_reconnect_window_callback_returns_true(self) -> None:
        """wait_for_reconnect_window returns True when callback returns True."""
        from kstlib.websocket import WebSocketManager

        def should_reconnect() -> bool:
            return True

        ws = WebSocketManager("wss://example.com/ws", should_reconnect=should_reconnect)

        result = await ws.wait_for_reconnect_window(timeout=1.0)
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_for_reconnect_window_custom_callback(self) -> None:
        """wait_for_reconnect_window uses custom callback over instance callback."""
        from kstlib.websocket import WebSocketManager

        def instance_callback() -> bool:
            return False

        def custom_callback() -> bool:
            return True

        ws = WebSocketManager("wss://example.com/ws", should_reconnect=instance_callback)

        result = await ws.wait_for_reconnect_window(
            should_reconnect=custom_callback,
            timeout=1.0,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_for_reconnect_window_timeout(self) -> None:
        """wait_for_reconnect_window returns False on timeout."""
        from kstlib.websocket import WebSocketManager

        def never_reconnect() -> bool:
            return False

        ws = WebSocketManager("wss://example.com/ws", should_reconnect=never_reconnect)

        result = await ws.wait_for_reconnect_window(timeout=0.05)
        assert result is False

    @pytest.mark.asyncio
    async def test_wait_for_reconnect_window_callback_returns_delay(self) -> None:
        """wait_for_reconnect_window handles callback returning delay."""
        from kstlib.websocket import WebSocketManager

        call_count = 0

        def delayed_reconnect() -> bool | float:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                return True
            return 0.01  # Wait 10ms

        ws = WebSocketManager("wss://example.com/ws", should_reconnect=delayed_reconnect)

        result = await ws.wait_for_reconnect_window(timeout=1.0)
        assert result is True
        assert call_count >= 2


class TestProactiveCallbacks:
    """Tests for proactive callback handling."""

    def test_should_disconnect_callback_initialization(self) -> None:
        """should_disconnect callback is properly initialized."""
        from kstlib.websocket import WebSocketManager

        call_count = 0

        def should_disconnect() -> bool:
            nonlocal call_count
            call_count += 1
            return False

        ws = WebSocketManager("wss://example.com/ws", should_disconnect=should_disconnect)
        assert ws._should_disconnect is not None

    def test_should_reconnect_callback_initialization(self) -> None:
        """should_reconnect callback is properly initialized."""
        from kstlib.websocket import WebSocketManager

        def should_reconnect() -> bool:
            return True

        ws = WebSocketManager("wss://example.com/ws", should_reconnect=should_reconnect)
        assert ws._should_reconnect is not None

    def test_disconnect_check_interval_configuration(self) -> None:
        """disconnect_check_interval is properly configured."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager(
            "wss://example.com/ws",
            disconnect_check_interval=5.0,
        )
        assert ws._disconnect_check_interval == 5.0

    def test_reconnect_check_interval_configuration(self) -> None:
        """reconnect_check_interval is properly configured."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager(
            "wss://example.com/ws",
            reconnect_check_interval=2.0,
        )
        assert ws._reconnect_check_interval == 2.0


class TestOnDisconnectCallback:
    """Tests for on_disconnect callback handling."""

    @pytest.mark.asyncio
    async def test_on_disconnect_receives_reason(self) -> None:
        """on_disconnect callback receives disconnect reason."""
        from kstlib.websocket import WebSocketManager

        received_reason: DisconnectReason | None = None

        def on_disconnect(reason: DisconnectReason) -> None:
            nonlocal received_reason
            received_reason = reason

        ws = WebSocketManager("wss://example.com/ws", on_disconnect=on_disconnect)
        ws._state = ConnectionState.CONNECTED
        ws._auto_reconnect = False

        await ws._handle_disconnect(DisconnectReason.USER_REQUESTED)
        assert received_reason == DisconnectReason.USER_REQUESTED

    @pytest.mark.asyncio
    async def test_on_disconnect_async_callback(self) -> None:
        """on_disconnect supports async callbacks."""
        from kstlib.websocket import WebSocketManager

        received_reason: DisconnectReason | None = None

        async def on_disconnect(reason: DisconnectReason) -> None:
            nonlocal received_reason
            await asyncio.sleep(0.001)
            received_reason = reason

        ws = WebSocketManager("wss://example.com/ws", on_disconnect=on_disconnect)
        ws._state = ConnectionState.CONNECTED
        ws._auto_reconnect = False

        await ws._handle_disconnect(DisconnectReason.SERVER_CLOSED)
        assert received_reason == DisconnectReason.SERVER_CLOSED


class TestDisconnectReasonTracking:
    """Tests for disconnect reason tracking in stats."""

    @pytest.mark.asyncio
    async def test_proactive_disconnect_tracked(self) -> None:
        """Proactive disconnects are tracked separately."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CONNECTED
        ws._auto_reconnect = False

        await ws._handle_disconnect(DisconnectReason.USER_REQUESTED)

        assert ws.stats.proactive_disconnects == 1
        assert ws.stats.reactive_disconnects == 0

    @pytest.mark.asyncio
    async def test_reactive_disconnect_tracked(self) -> None:
        """Reactive disconnects are tracked separately."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._state = ConnectionState.CONNECTED
        ws._auto_reconnect = False

        await ws._handle_disconnect(DisconnectReason.NETWORK_ERROR)

        assert ws.stats.proactive_disconnects == 0
        assert ws.stats.reactive_disconnects == 1


class TestDisconnectMargin:
    """Tests for disconnect margin configuration."""

    def test_disconnect_margin_default(self) -> None:
        """disconnect_margin uses default value."""
        from kstlib.limits import DEFAULT_WS_DISCONNECT_MARGIN
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        assert ws._disconnect_margin == DEFAULT_WS_DISCONNECT_MARGIN

    def test_disconnect_margin_custom(self) -> None:
        """disconnect_margin accepts custom value."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws", disconnect_margin=600.0)
        assert ws._disconnect_margin == 600.0

    def test_disconnect_margin_from_config(self) -> None:
        """disconnect_margin reads from config."""
        from kstlib.websocket import WebSocketManager

        config = {
            "websocket": {
                "proactive": {
                    "disconnect_margin": 900.0,
                }
            }
        }
        ws = WebSocketManager("wss://example.com/ws", config=config)
        assert ws._disconnect_margin == 900.0
