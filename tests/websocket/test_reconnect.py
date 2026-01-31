"""Tests for WebSocketManager reconnection features."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from kstlib.websocket.models import ConnectionState, DisconnectReason, ReconnectStrategy

# Skip all tests if websockets is not installed
pytestmark = pytest.mark.skipif(
    not pytest.importorskip("websockets", reason="websockets not installed"),
    reason="websockets not installed",
)


class TestReconnectStrategy:
    """Tests for reconnect strategy configuration."""

    def test_default_strategy_is_exponential_backoff(self) -> None:
        """Default reconnect strategy is EXPONENTIAL_BACKOFF."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        assert ws._reconnect_strategy == ReconnectStrategy.EXPONENTIAL_BACKOFF

    def test_immediate_strategy(self) -> None:
        """IMMEDIATE strategy can be configured."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager(
            "wss://example.com/ws",
            reconnect_strategy=ReconnectStrategy.IMMEDIATE,
        )
        assert ws._reconnect_strategy == ReconnectStrategy.IMMEDIATE

    def test_fixed_delay_strategy(self) -> None:
        """FIXED_DELAY strategy can be configured."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager(
            "wss://example.com/ws",
            reconnect_strategy=ReconnectStrategy.FIXED_DELAY,
        )
        assert ws._reconnect_strategy == ReconnectStrategy.FIXED_DELAY

    def test_callback_controlled_strategy(self) -> None:
        """CALLBACK_CONTROLLED strategy can be configured."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager(
            "wss://example.com/ws",
            reconnect_strategy=ReconnectStrategy.CALLBACK_CONTROLLED,
        )
        assert ws._reconnect_strategy == ReconnectStrategy.CALLBACK_CONTROLLED


class TestReconnectDelay:
    """Tests for reconnect delay configuration."""

    def test_default_reconnect_delay(self) -> None:
        """Default reconnect delay is from limits."""
        from kstlib.limits import DEFAULT_WS_RECONNECT_DELAY
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        assert ws._reconnect_delay == DEFAULT_WS_RECONNECT_DELAY

    def test_custom_reconnect_delay(self) -> None:
        """Custom reconnect delay can be configured."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws", reconnect_delay=2.5)
        assert ws._reconnect_delay == 2.5

    def test_max_reconnect_delay(self) -> None:
        """Max reconnect delay can be configured."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws", max_reconnect_delay=120.0)
        assert ws._max_reconnect_delay == 120.0


class TestMaxReconnectAttempts:
    """Tests for max reconnect attempts configuration."""

    def test_default_max_attempts(self) -> None:
        """Default max attempts is from limits."""
        from kstlib.limits import DEFAULT_WS_RECONNECT_ATTEMPTS
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        assert ws._max_reconnect_attempts == DEFAULT_WS_RECONNECT_ATTEMPTS

    def test_custom_max_attempts(self) -> None:
        """Custom max attempts can be configured."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws", max_reconnect_attempts=20)
        assert ws._max_reconnect_attempts == 20


class TestAutoReconnect:
    """Tests for auto reconnect configuration."""

    def test_auto_reconnect_enabled_by_default(self) -> None:
        """Auto reconnect is enabled by default."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        assert ws._auto_reconnect is True

    def test_auto_reconnect_can_be_disabled(self) -> None:
        """Auto reconnect can be disabled."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws", auto_reconnect=False)
        assert ws._auto_reconnect is False


class TestWaitReconnectDelay:
    """Tests for _wait_reconnect_delay method."""

    @pytest.mark.asyncio
    async def test_immediate_strategy_no_delay(self) -> None:
        """IMMEDIATE strategy has no delay."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager(
            "wss://example.com/ws",
            reconnect_strategy=ReconnectStrategy.IMMEDIATE,
        )

        start = asyncio.get_event_loop().time()
        await ws._wait_reconnect_delay(1)
        elapsed = asyncio.get_event_loop().time() - start

        assert elapsed < 0.1  # Should be nearly instant

    @pytest.mark.asyncio
    async def test_fixed_delay_strategy(self) -> None:
        """FIXED_DELAY strategy uses constant delay."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager(
            "wss://example.com/ws",
            reconnect_strategy=ReconnectStrategy.FIXED_DELAY,
            reconnect_delay=0.05,  # 50ms for testing
        )

        start = asyncio.get_event_loop().time()
        await ws._wait_reconnect_delay(1)
        elapsed = asyncio.get_event_loop().time() - start

        assert 0.04 < elapsed < 0.15  # Allow some tolerance

    @pytest.mark.asyncio
    async def test_exponential_backoff_first_attempt(self) -> None:
        """EXPONENTIAL_BACKOFF uses base delay for first attempt."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager(
            "wss://example.com/ws",
            reconnect_strategy=ReconnectStrategy.EXPONENTIAL_BACKOFF,
            reconnect_delay=0.05,  # 50ms for testing
        )

        start = asyncio.get_event_loop().time()
        await ws._wait_reconnect_delay(1)
        elapsed = asyncio.get_event_loop().time() - start

        assert 0.04 < elapsed < 0.15

    @pytest.mark.asyncio
    async def test_exponential_backoff_increases(self) -> None:
        """EXPONENTIAL_BACKOFF delay increases with attempts."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager(
            "wss://example.com/ws",
            reconnect_strategy=ReconnectStrategy.EXPONENTIAL_BACKOFF,
            reconnect_delay=1.0,  # 1s base (for calculation, we mock sleep)
            max_reconnect_delay=60.0,
        )

        delays: list[float] = []

        async def capture_sleep(delay: float) -> None:
            delays.append(delay)

        with patch("asyncio.sleep", side_effect=capture_sleep):
            await ws._wait_reconnect_delay(1)  # Should be 1.0
            await ws._wait_reconnect_delay(2)  # Should be 2.0
            await ws._wait_reconnect_delay(3)  # Should be 4.0

        # Each delay should be exactly double the previous
        assert delays[0] == 1.0
        assert delays[1] == 2.0
        assert delays[2] == 4.0

    @pytest.mark.asyncio
    async def test_exponential_backoff_capped_at_max(self) -> None:
        """EXPONENTIAL_BACKOFF is capped at max_reconnect_delay."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager(
            "wss://example.com/ws",
            reconnect_strategy=ReconnectStrategy.EXPONENTIAL_BACKOFF,
            reconnect_delay=0.05,
            max_reconnect_delay=0.08,  # Low cap for testing
        )

        # Attempt 10 would be 0.05 * 2^9 = 25.6s, but capped at 0.08s
        start = asyncio.get_event_loop().time()
        await ws._wait_reconnect_delay(10)
        elapsed = asyncio.get_event_loop().time() - start

        assert elapsed < 0.15  # Should be capped


class TestAttemptReconnect:
    """Tests for _attempt_reconnect method."""

    @pytest.mark.asyncio
    async def test_reconnect_count_increments(self) -> None:
        """Reconnect count increments on each attempt."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._reconnect_count = 0

        # Mock _establish_connection to fail
        ws._establish_connection = AsyncMock(side_effect=Exception("Connection failed"))
        ws._wait_reconnect_delay = AsyncMock()

        # Attempt reconnect (will fail)
        with pytest.raises(Exception):
            await ws._attempt_reconnect()

        assert ws._reconnect_count == 1

    @pytest.mark.asyncio
    async def test_max_attempts_exceeded(self) -> None:
        """WebSocketReconnectError raised when max attempts exceeded."""
        from kstlib.websocket import WebSocketManager
        from kstlib.websocket.exceptions import WebSocketReconnectError

        ws = WebSocketManager("wss://example.com/ws", max_reconnect_attempts=5)
        ws._reconnect_count = 5  # Already at max

        with pytest.raises(WebSocketReconnectError):
            await ws._attempt_reconnect()


class TestReconnectOnDisconnect:
    """Tests for auto-reconnect behavior on disconnection."""

    @pytest.mark.asyncio
    async def test_reactive_disconnect_triggers_reconnect(self) -> None:
        """Reactive disconnect triggers auto-reconnect when enabled."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws", auto_reconnect=True)
        ws._state = ConnectionState.CONNECTED
        ws._attempt_reconnect = AsyncMock()

        await ws._handle_disconnect(DisconnectReason.NETWORK_ERROR)

        ws._attempt_reconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_proactive_disconnect_no_auto_reconnect(self) -> None:
        """Proactive disconnect does not trigger auto-reconnect by default."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws", auto_reconnect=True)
        ws._state = ConnectionState.CONNECTED
        ws._attempt_reconnect = AsyncMock()

        await ws._handle_disconnect(DisconnectReason.USER_REQUESTED)

        # Proactive disconnect should not auto-reconnect
        ws._attempt_reconnect.assert_not_called()

    @pytest.mark.asyncio
    async def test_proactive_disconnect_with_reconnect_after(self) -> None:
        """Proactive disconnect with reconnect_after schedules reconnect."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws", auto_reconnect=True)
        ws._state = ConnectionState.CONNECTED
        ws._attempt_reconnect = AsyncMock()
        ws._scheduled_reconnect_delay = 0.01  # Very short for testing

        await ws._handle_disconnect(DisconnectReason.USER_REQUESTED)

        # Should have attempted reconnect after delay
        await asyncio.sleep(0.05)  # Wait for scheduled reconnect
        ws._attempt_reconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_with_auto_reconnect_disabled(self) -> None:
        """Disconnect does not reconnect when auto_reconnect is False."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws", auto_reconnect=False)
        ws._state = ConnectionState.CONNECTED
        ws._attempt_reconnect = AsyncMock()

        await ws._handle_disconnect(DisconnectReason.NETWORK_ERROR)

        ws._attempt_reconnect.assert_not_called()
        assert ws.state == ConnectionState.DISCONNECTED


class TestReconnectWithSubscriptions:
    """Tests for subscription handling during reconnection."""

    @pytest.mark.asyncio
    async def test_subscriptions_preserved_after_disconnect(self) -> None:
        """Subscriptions are preserved after disconnect."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        await ws.subscribe("btcusdt@trade", "ethusdt@trade")

        ws._state = ConnectionState.CONNECTED
        ws._auto_reconnect = False
        await ws._handle_disconnect(DisconnectReason.USER_REQUESTED)

        assert "btcusdt@trade" in ws.subscriptions
        assert "ethusdt@trade" in ws.subscriptions

    @pytest.mark.asyncio
    async def test_resubscribe_on_reconnect(self) -> None:
        """Subscriptions are restored after reconnection."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        ws._subscriptions = {"btcusdt@trade", "ethusdt@trade"}

        # Mock _send_subscribe
        ws._send_subscribe = AsyncMock()

        await ws._resubscribe()

        assert ws._send_subscribe.call_count == 2


class TestReconnectStats:
    """Tests for reconnection statistics."""

    @pytest.mark.asyncio
    async def test_connect_count_increases(self) -> None:
        """Connect count increases on successful connection."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        initial_connects = ws.stats.connects

        # Simulate successful connection
        ws._stats.record_connect()

        assert ws.stats.connects == initial_connects + 1

    @pytest.mark.asyncio
    async def test_disconnect_count_increases(self) -> None:
        """Disconnect count increases on disconnection."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager("wss://example.com/ws")
        initial_disconnects = ws.stats.disconnects

        ws._state = ConnectionState.CONNECTED
        ws._auto_reconnect = False
        await ws._handle_disconnect(DisconnectReason.USER_REQUESTED)

        assert ws.stats.disconnects == initial_disconnects + 1
