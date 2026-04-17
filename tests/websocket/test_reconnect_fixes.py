"""Tests for WebSocketManager reconnect fixes (v2.2.1).

Covers:
- Delayed reset of ``_reconnect_count`` after ``stable_connection_time``.
- Forced backoff on WebSocket close code 1013 (Try Again Later).
- Throttled ``on_disconnect_alert`` with aggregated count.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from kstlib.websocket.models import ConnectionState, DisconnectReason

pytestmark = pytest.mark.skipif(
    not pytest.importorskip("websockets", reason="websockets not installed"),
    reason="websockets not installed",
)


class TestStableConnectionReset:
    """Tests for delayed reset of ``_reconnect_count``."""

    @pytest.mark.asyncio
    async def test_stable_connection_resets_counter_after_delay(self) -> None:
        """Counter resets to 0 after stable_connection_time elapses."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager(
            "wss://example.com/ws",
            stable_connection_time=0.05,
        )
        ws._reconnect_count = 4
        ws._state = ConnectionState.CONNECTED

        task = asyncio.create_task(ws._stable_connection_reset_loop())
        ws._stable_connection_task = task

        await asyncio.sleep(0.1)

        assert ws._reconnect_count == 0
        assert task.done()

    @pytest.mark.asyncio
    async def test_early_disconnect_preserves_counter(self) -> None:
        """Cancelling the stable-connection task does NOT reset the counter."""
        from kstlib.websocket import WebSocketManager

        ws = WebSocketManager(
            "wss://example.com/ws",
            stable_connection_time=1.0,
        )
        ws._reconnect_count = 3
        ws._state = ConnectionState.CONNECTED

        task = asyncio.create_task(ws._stable_connection_reset_loop())
        ws._stable_connection_task = task

        # Cancel well before stable_connection_time elapses
        await asyncio.sleep(0.01)
        await ws._cancel_background_tasks()

        assert ws._reconnect_count == 3, "Counter must not be reset on early cancel"


class TestForcedBackoffOn1013:
    """Tests for forced backoff on WebSocket close code 1013."""

    @pytest.mark.asyncio
    async def test_code_1013_forces_backoff(self) -> None:
        """Close code 1013 triggers server_unavailable_delay before reconnect."""
        from kstlib.websocket import WebSocketManager
        from kstlib.websocket.manager import WS_CODE_TRY_AGAIN_LATER

        ws = WebSocketManager(
            "wss://example.com/ws",
            auto_reconnect=False,  # avoid real reconnect flow
            server_unavailable_delay=0.2,
        )
        ws._state = ConnectionState.CONNECTED

        await ws._handle_disconnect(
            DisconnectReason.SERVER_CLOSED,
            code=WS_CODE_TRY_AGAIN_LATER,
        )

        assert ws._force_backoff_delay == pytest.approx(0.2)

        # _attempt_reconnect consumes _force_backoff_delay as its first step
        ws._establish_connection = AsyncMock()
        ws._state = ConnectionState.RECONNECTING

        loop = asyncio.get_running_loop()
        start = loop.time()
        await ws._attempt_reconnect()
        elapsed = loop.time() - start

        # Allow a small margin for Windows timer granularity (~16ms).
        assert elapsed >= 0.15, f"Expected near-0.2s backoff, got {elapsed:.3f}s"
        assert ws._force_backoff_delay is None


class TestDisconnectAlertThrottle:
    """Tests for throttled disconnect alert callback."""

    @pytest.mark.asyncio
    async def test_disconnect_alert_throttled(self) -> None:
        """10 rapid disconnects fire on_disconnect_alert only once."""
        from kstlib.websocket import WebSocketManager

        calls: list[tuple[DisconnectReason, int]] = []

        async def alert_cb(reason: DisconnectReason, count: int) -> None:
            calls.append((reason, count))

        ws = WebSocketManager(
            "wss://example.com/ws",
            auto_reconnect=False,
            on_disconnect_alert=alert_cb,
            disconnect_alert_interval=60.0,  # long enough to ensure throttling
        )
        ws._state = ConnectionState.CONNECTED

        for _ in range(10):
            ws._state = ConnectionState.CONNECTED  # reset for each call
            await ws._handle_disconnect(DisconnectReason.NETWORK_ERROR)

        assert len(calls) == 1, f"Expected 1 alert, got {len(calls)}"

    @pytest.mark.asyncio
    async def test_disconnect_alert_aggregates_count(self) -> None:
        """on_disconnect_alert receives aggregated count of disconnects in window."""
        from kstlib.websocket import WebSocketManager

        calls: list[tuple[DisconnectReason, int]] = []

        def alert_cb(reason: DisconnectReason, count: int) -> None:
            calls.append((reason, count))

        ws = WebSocketManager(
            "wss://example.com/ws",
            auto_reconnect=False,
            on_disconnect_alert=alert_cb,
            disconnect_alert_interval=60.0,
        )
        ws._state = ConnectionState.CONNECTED

        # First window: 5 disconnects, first fires alert with count=1
        for _ in range(5):
            ws._state = ConnectionState.CONNECTED
            await ws._handle_disconnect(DisconnectReason.NETWORK_ERROR)

        assert len(calls) == 1
        assert calls[0] == (DisconnectReason.NETWORK_ERROR, 1)

        # After 4 additional throttled disconnects, aggregated count is 4.
        # Simulate window elapsing by rewinding last-alert timestamp.
        ws._last_disconnect_alert_at = 0.0
        ws._state = ConnectionState.CONNECTED
        await ws._handle_disconnect(DisconnectReason.NETWORK_ERROR)

        assert len(calls) == 2
        assert calls[1] == (DisconnectReason.NETWORK_ERROR, 5), (
            f"Expected aggregated count=5 (4 skipped + 1 new), got {calls[1][1]}"
        )
