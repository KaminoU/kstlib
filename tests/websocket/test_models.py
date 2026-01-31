"""Tests for kstlib.websocket.models module."""

from __future__ import annotations

import time

from kstlib.websocket.models import (
    ConnectionState,
    DisconnectReason,
    ReconnectStrategy,
    WebSocketStats,
)


class TestConnectionState:
    """Tests for ConnectionState enum."""

    def test_all_states_defined(self) -> None:
        """All expected connection states should be defined."""
        states = [
            ConnectionState.DISCONNECTED,
            ConnectionState.CONNECTING,
            ConnectionState.CONNECTED,
            ConnectionState.RECONNECTING,
            ConnectionState.CLOSING,
            ConnectionState.CLOSED,
        ]
        assert len(states) == 6

    def test_can_connect_from_disconnected(self) -> None:
        """Should be able to connect from DISCONNECTED state."""
        assert ConnectionState.DISCONNECTED.can_connect() is True

    def test_can_connect_from_reconnecting(self) -> None:
        """Should be able to connect from RECONNECTING state."""
        assert ConnectionState.RECONNECTING.can_connect() is True

    def test_cannot_connect_from_connected(self) -> None:
        """Should not be able to connect from CONNECTED state."""
        assert ConnectionState.CONNECTED.can_connect() is False

    def test_cannot_connect_from_connecting(self) -> None:
        """Should not be able to connect from CONNECTING state."""
        assert ConnectionState.CONNECTING.can_connect() is False

    def test_cannot_connect_from_closing(self) -> None:
        """Should not be able to connect from CLOSING state."""
        assert ConnectionState.CLOSING.can_connect() is False

    def test_cannot_connect_from_closed(self) -> None:
        """Should not be able to connect from CLOSED state."""
        assert ConnectionState.CLOSED.can_connect() is False

    def test_can_send_from_connected(self) -> None:
        """Should be able to send from CONNECTED state only."""
        assert ConnectionState.CONNECTED.can_send() is True
        assert ConnectionState.DISCONNECTED.can_send() is False
        assert ConnectionState.CONNECTING.can_send() is False
        assert ConnectionState.RECONNECTING.can_send() is False
        assert ConnectionState.CLOSING.can_send() is False
        assert ConnectionState.CLOSED.can_send() is False

    def test_closed_is_terminal(self) -> None:
        """CLOSED should be a terminal state."""
        assert ConnectionState.CLOSED.is_terminal() is True

    def test_other_states_not_terminal(self) -> None:
        """Non-CLOSED states should not be terminal."""
        non_terminal = [
            ConnectionState.DISCONNECTED,
            ConnectionState.CONNECTING,
            ConnectionState.CONNECTED,
            ConnectionState.RECONNECTING,
            ConnectionState.CLOSING,
        ]
        for state in non_terminal:
            assert state.is_terminal() is False


class TestDisconnectReason:
    """Tests for DisconnectReason enum."""

    def test_proactive_reasons(self) -> None:
        """Proactive reasons should be correctly identified."""
        proactive = [
            DisconnectReason.USER_REQUESTED,
            DisconnectReason.SCHEDULED,
            DisconnectReason.CALLBACK_TRIGGERED,
            DisconnectReason.CONNECTION_LIMIT,
        ]
        for reason in proactive:
            assert reason.is_proactive is True
            assert reason.is_reactive is False

    def test_reactive_reasons(self) -> None:
        """Reactive reasons should be correctly identified."""
        reactive = [
            DisconnectReason.SERVER_CLOSED,
            DisconnectReason.NETWORK_ERROR,
            DisconnectReason.PING_TIMEOUT,
            DisconnectReason.PROTOCOL_ERROR,
            DisconnectReason.KILLED,
        ]
        for reason in reactive:
            assert reason.is_reactive is True
            assert reason.is_proactive is False

    def test_all_reasons_covered(self) -> None:
        """All disconnect reasons should be covered."""
        all_reasons = list(DisconnectReason)
        assert len(all_reasons) == 9

    def test_is_proactive_is_opposite_of_is_reactive(self) -> None:
        """is_proactive and is_reactive should be mutually exclusive."""
        for reason in DisconnectReason:
            assert reason.is_proactive != reason.is_reactive


class TestReconnectStrategy:
    """Tests for ReconnectStrategy enum."""

    def test_all_strategies_defined(self) -> None:
        """All expected reconnect strategies should be defined."""
        strategies = [
            ReconnectStrategy.IMMEDIATE,
            ReconnectStrategy.FIXED_DELAY,
            ReconnectStrategy.EXPONENTIAL_BACKOFF,
            ReconnectStrategy.CALLBACK_CONTROLLED,
        ]
        assert len(strategies) == 4


class TestWebSocketStats:
    """Tests for WebSocketStats dataclass."""

    def test_default_values(self) -> None:
        """WebSocketStats should have correct default values."""
        stats = WebSocketStats()
        assert stats.connects == 0
        assert stats.disconnects == 0
        assert stats.proactive_disconnects == 0
        assert stats.reactive_disconnects == 0
        assert stats.messages_received == 0
        assert stats.messages_sent == 0
        assert stats.bytes_received == 0
        assert stats.bytes_sent == 0
        assert stats.last_connect_time == 0.0
        assert stats.last_disconnect_time == 0.0
        assert stats.last_message_time == 0.0

    def test_record_connect(self) -> None:
        """record_connect should increment connects counter."""
        stats = WebSocketStats()
        stats.record_connect()
        assert stats.connects == 1
        stats.record_connect()
        assert stats.connects == 2

    def test_record_connect_updates_time(self) -> None:
        """record_connect should update last_connect_time."""
        stats = WebSocketStats()
        before = time.time()
        stats.record_connect()
        after = time.time()
        assert before <= stats.last_connect_time <= after

    def test_record_disconnect_proactive(self) -> None:
        """record_disconnect with proactive=True should increment proactive counter."""
        stats = WebSocketStats()
        stats.record_disconnect(proactive=True)
        assert stats.disconnects == 1
        assert stats.proactive_disconnects == 1
        assert stats.reactive_disconnects == 0

    def test_record_disconnect_reactive(self) -> None:
        """record_disconnect with proactive=False should increment reactive counter."""
        stats = WebSocketStats()
        stats.record_disconnect(proactive=False)
        assert stats.disconnects == 1
        assert stats.proactive_disconnects == 0
        assert stats.reactive_disconnects == 1

    def test_record_disconnect_updates_time(self) -> None:
        """record_disconnect should update last_disconnect_time."""
        stats = WebSocketStats()
        before = time.time()
        stats.record_disconnect()
        after = time.time()
        assert before <= stats.last_disconnect_time <= after

    def test_record_message_received(self) -> None:
        """record_message_received should increment counters."""
        stats = WebSocketStats()
        stats.record_message_received(100)
        assert stats.messages_received == 1
        assert stats.bytes_received == 100
        stats.record_message_received(50)
        assert stats.messages_received == 2
        assert stats.bytes_received == 150

    def test_record_message_received_updates_time(self) -> None:
        """record_message_received should update last_message_time."""
        stats = WebSocketStats()
        before = time.time()
        stats.record_message_received(0)
        after = time.time()
        assert before <= stats.last_message_time <= after

    def test_record_message_sent(self) -> None:
        """record_message_sent should increment counters."""
        stats = WebSocketStats()
        stats.record_message_sent(200)
        assert stats.messages_sent == 1
        assert stats.bytes_sent == 200
        stats.record_message_sent(75)
        assert stats.messages_sent == 2
        assert stats.bytes_sent == 275

    def test_record_message_sent_updates_time(self) -> None:
        """record_message_sent should update last_message_time."""
        stats = WebSocketStats()
        before = time.time()
        stats.record_message_sent(0)
        after = time.time()
        assert before <= stats.last_message_time <= after

    def test_uptime(self) -> None:
        """uptime should return time since creation."""
        stats = WebSocketStats()
        # Uptime should start near zero
        initial_uptime = stats.uptime
        assert initial_uptime >= 0
        assert initial_uptime < 1  # Should be very small initially
        # After sleep, uptime should increase
        time.sleep(0.05)
        assert stats.uptime > initial_uptime

    def test_connection_time_when_never_connected(self) -> None:
        """connection_time should return 0 when never connected."""
        stats = WebSocketStats()
        assert stats.connection_time == 0.0

    def test_connection_time_after_connect(self) -> None:
        """connection_time should return time since last connect."""
        stats = WebSocketStats()
        stats.record_connect()
        time.sleep(0.01)
        assert stats.connection_time >= 0.01

    def test_reset(self) -> None:
        """reset should clear all counters."""
        stats = WebSocketStats()
        stats.record_connect()
        stats.record_disconnect(proactive=True)
        stats.record_message_received(100)
        stats.record_message_sent(50)

        stats.reset()

        assert stats.connects == 0
        assert stats.disconnects == 0
        assert stats.proactive_disconnects == 0
        assert stats.reactive_disconnects == 0
        assert stats.messages_received == 0
        assert stats.messages_sent == 0
        assert stats.bytes_received == 0
        assert stats.bytes_sent == 0
        assert stats.last_connect_time == 0.0
        assert stats.last_disconnect_time == 0.0
        assert stats.last_message_time == 0.0

    def test_multiple_operations(self) -> None:
        """Stats should correctly track multiple operations."""
        stats = WebSocketStats()

        # Simulate a session
        stats.record_connect()
        for _ in range(10):
            stats.record_message_received(100)
            stats.record_message_sent(50)
        stats.record_disconnect(proactive=False)

        # Reconnect
        stats.record_connect()
        for _ in range(5):
            stats.record_message_received(200)
        stats.record_disconnect(proactive=True)

        assert stats.connects == 2
        assert stats.disconnects == 2
        assert stats.proactive_disconnects == 1
        assert stats.reactive_disconnects == 1
        assert stats.messages_received == 15
        assert stats.messages_sent == 10
        assert stats.bytes_received == 2000  # 10*100 + 5*200
        assert stats.bytes_sent == 500  # 10*50
