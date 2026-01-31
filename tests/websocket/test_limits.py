"""Tests for WebSocket limits in kstlib.limits module."""

from __future__ import annotations

import pytest

from kstlib.limits import (
    DEFAULT_WS_CONNECTION_TIMEOUT,
    DEFAULT_WS_DISCONNECT_CHECK,
    DEFAULT_WS_DISCONNECT_MARGIN,
    DEFAULT_WS_MAX_RECONNECT_DELAY,
    DEFAULT_WS_PING_INTERVAL,
    DEFAULT_WS_PING_TIMEOUT,
    DEFAULT_WS_QUEUE_SIZE,
    DEFAULT_WS_RECONNECT_ATTEMPTS,
    DEFAULT_WS_RECONNECT_CHECK,
    DEFAULT_WS_RECONNECT_DELAY,
    HARD_MAX_WS_CONNECTION_TIMEOUT,
    HARD_MAX_WS_DISCONNECT_CHECK,
    HARD_MAX_WS_DISCONNECT_MARGIN,
    HARD_MAX_WS_MAX_RECONNECT_DELAY,
    HARD_MAX_WS_PING_INTERVAL,
    HARD_MAX_WS_PING_TIMEOUT,
    HARD_MAX_WS_QUEUE_SIZE,
    HARD_MAX_WS_RECONNECT_ATTEMPTS,
    HARD_MAX_WS_RECONNECT_CHECK,
    HARD_MAX_WS_RECONNECT_DELAY,
    HARD_MIN_WS_CONNECTION_TIMEOUT,
    HARD_MIN_WS_DISCONNECT_CHECK,
    HARD_MIN_WS_DISCONNECT_MARGIN,
    HARD_MIN_WS_MAX_RECONNECT_DELAY,
    HARD_MIN_WS_PING_INTERVAL,
    HARD_MIN_WS_PING_TIMEOUT,
    HARD_MIN_WS_QUEUE_SIZE,
    HARD_MIN_WS_RECONNECT_ATTEMPTS,
    HARD_MIN_WS_RECONNECT_CHECK,
    HARD_MIN_WS_RECONNECT_DELAY,
    WebSocketLimits,
    get_websocket_limits,
)


class TestWebSocketLimits:
    """Tests for WebSocketLimits dataclass."""

    def test_frozen_dataclass(self) -> None:
        """WebSocketLimits is immutable."""
        limits = WebSocketLimits(
            ping_interval=20.0,
            ping_timeout=10.0,
            connection_timeout=30.0,
            reconnect_delay=1.0,
            max_reconnect_delay=60.0,
            max_reconnect_attempts=10,
            queue_size=1000,
            disconnect_check_interval=10.0,
            reconnect_check_interval=5.0,
            disconnect_margin=300.0,
        )
        with pytest.raises(AttributeError):
            limits.ping_interval = 15.0  # type: ignore[misc]

    def test_all_attributes_present(self) -> None:
        """WebSocketLimits has all required attributes."""
        limits = WebSocketLimits(
            ping_interval=20.0,
            ping_timeout=10.0,
            connection_timeout=30.0,
            reconnect_delay=1.0,
            max_reconnect_delay=60.0,
            max_reconnect_attempts=10,
            queue_size=1000,
            disconnect_check_interval=10.0,
            reconnect_check_interval=5.0,
            disconnect_margin=300.0,
        )
        assert limits.ping_interval == 20.0
        assert limits.ping_timeout == 10.0
        assert limits.connection_timeout == 30.0
        assert limits.reconnect_delay == 1.0
        assert limits.max_reconnect_delay == 60.0
        assert limits.max_reconnect_attempts == 10
        assert limits.queue_size == 1000
        assert limits.disconnect_check_interval == 10.0
        assert limits.reconnect_check_interval == 5.0
        assert limits.disconnect_margin == 300.0


class TestGetWebSocketLimits:
    """Tests for get_websocket_limits function."""

    def test_defaults_when_no_config(self) -> None:
        """Use defaults when no config is provided."""
        limits = get_websocket_limits(config={})
        assert limits.ping_interval == DEFAULT_WS_PING_INTERVAL
        assert limits.ping_timeout == DEFAULT_WS_PING_TIMEOUT
        assert limits.connection_timeout == DEFAULT_WS_CONNECTION_TIMEOUT
        assert limits.reconnect_delay == DEFAULT_WS_RECONNECT_DELAY
        assert limits.max_reconnect_delay == DEFAULT_WS_MAX_RECONNECT_DELAY
        assert limits.max_reconnect_attempts == DEFAULT_WS_RECONNECT_ATTEMPTS
        assert limits.queue_size == DEFAULT_WS_QUEUE_SIZE
        assert limits.disconnect_check_interval == DEFAULT_WS_DISCONNECT_CHECK
        assert limits.reconnect_check_interval == DEFAULT_WS_RECONNECT_CHECK
        assert limits.disconnect_margin == DEFAULT_WS_DISCONNECT_MARGIN

    def test_reads_from_config(self) -> None:
        """Read limits from config mapping."""
        config = {
            "websocket": {
                "ping": {"interval": 15, "timeout": 8},
                "connection": {"timeout": 45},
                "reconnect": {"delay": 2.0, "max_delay": 120.0, "max_attempts": 20},
                "queue": {"size": 500},
                "proactive": {
                    "disconnect_check_interval": 5.0,
                    "reconnect_check_interval": 2.0,
                    "disconnect_margin": 600.0,
                },
            }
        }
        limits = get_websocket_limits(config=config)
        assert limits.ping_interval == 15.0
        assert limits.ping_timeout == 8.0
        assert limits.connection_timeout == 45.0
        assert limits.reconnect_delay == 2.0
        assert limits.max_reconnect_delay == 120.0
        assert limits.max_reconnect_attempts == 20
        assert limits.queue_size == 500
        assert limits.disconnect_check_interval == 5.0
        assert limits.reconnect_check_interval == 2.0
        assert limits.disconnect_margin == 600.0

    def test_clamps_to_hard_maximums(self) -> None:
        """Clamp values to hard maximums."""
        config = {
            "websocket": {
                "ping": {"interval": 9999, "timeout": 9999},
                "connection": {"timeout": 9999},
                "reconnect": {"delay": 9999, "max_delay": 9999, "max_attempts": 9999},
                "queue": {"size": 99999},
                "proactive": {
                    "disconnect_check_interval": 9999,
                    "reconnect_check_interval": 9999,
                    "disconnect_margin": 99999,
                },
            }
        }
        limits = get_websocket_limits(config=config)
        assert limits.ping_interval == HARD_MAX_WS_PING_INTERVAL
        assert limits.ping_timeout == HARD_MAX_WS_PING_TIMEOUT
        assert limits.connection_timeout == HARD_MAX_WS_CONNECTION_TIMEOUT
        assert limits.reconnect_delay == HARD_MAX_WS_RECONNECT_DELAY
        assert limits.max_reconnect_delay == HARD_MAX_WS_MAX_RECONNECT_DELAY
        assert limits.max_reconnect_attempts == HARD_MAX_WS_RECONNECT_ATTEMPTS
        assert limits.queue_size == HARD_MAX_WS_QUEUE_SIZE
        assert limits.disconnect_check_interval == HARD_MAX_WS_DISCONNECT_CHECK
        assert limits.reconnect_check_interval == HARD_MAX_WS_RECONNECT_CHECK
        assert limits.disconnect_margin == HARD_MAX_WS_DISCONNECT_MARGIN

    def test_clamps_to_hard_minimums(self) -> None:
        """Clamp values to hard minimums."""
        config = {
            "websocket": {
                "ping": {"interval": 0.001, "timeout": 0.001},
                "connection": {"timeout": 0.001},
                "reconnect": {"delay": -1, "max_delay": 0.001, "max_attempts": -1},
                "queue": {"size": -1},
                "proactive": {
                    "disconnect_check_interval": 0.001,
                    "reconnect_check_interval": 0.001,
                    "disconnect_margin": 0.001,
                },
            }
        }
        limits = get_websocket_limits(config=config)
        assert limits.ping_interval == HARD_MIN_WS_PING_INTERVAL
        assert limits.ping_timeout == HARD_MIN_WS_PING_TIMEOUT
        assert limits.connection_timeout == HARD_MIN_WS_CONNECTION_TIMEOUT
        assert limits.reconnect_delay == HARD_MIN_WS_RECONNECT_DELAY
        assert limits.max_reconnect_delay == HARD_MIN_WS_MAX_RECONNECT_DELAY
        assert limits.max_reconnect_attempts == HARD_MIN_WS_RECONNECT_ATTEMPTS
        assert limits.queue_size == HARD_MIN_WS_QUEUE_SIZE
        assert limits.disconnect_check_interval == HARD_MIN_WS_DISCONNECT_CHECK
        assert limits.reconnect_check_interval == HARD_MIN_WS_RECONNECT_CHECK
        assert limits.disconnect_margin == HARD_MIN_WS_DISCONNECT_MARGIN

    def test_handles_invalid_ping_interval(self) -> None:
        """Fall back to default for invalid ping interval."""
        config = {
            "websocket": {
                "ping": {"interval": "not_a_number"},
            }
        }
        limits = get_websocket_limits(config=config)
        assert limits.ping_interval == DEFAULT_WS_PING_INTERVAL

    def test_handles_invalid_ping_timeout(self) -> None:
        """Fall back to default for invalid ping timeout."""
        config = {
            "websocket": {
                "ping": {"timeout": "invalid"},
            }
        }
        limits = get_websocket_limits(config=config)
        assert limits.ping_timeout == DEFAULT_WS_PING_TIMEOUT

    def test_handles_invalid_connection_timeout(self) -> None:
        """Fall back to default for invalid connection timeout."""
        config = {
            "websocket": {
                "connection": {"timeout": "invalid"},
            }
        }
        limits = get_websocket_limits(config=config)
        assert limits.connection_timeout == DEFAULT_WS_CONNECTION_TIMEOUT

    def test_handles_invalid_reconnect_delay(self) -> None:
        """Fall back to default for invalid reconnect delay."""
        config = {
            "websocket": {
                "reconnect": {"delay": "invalid"},
            }
        }
        limits = get_websocket_limits(config=config)
        assert limits.reconnect_delay == DEFAULT_WS_RECONNECT_DELAY

    def test_handles_invalid_max_reconnect_delay(self) -> None:
        """Fall back to default for invalid max reconnect delay."""
        config = {
            "websocket": {
                "reconnect": {"max_delay": "invalid"},
            }
        }
        limits = get_websocket_limits(config=config)
        assert limits.max_reconnect_delay == DEFAULT_WS_MAX_RECONNECT_DELAY

    def test_handles_invalid_max_reconnect_attempts(self) -> None:
        """Fall back to default for invalid max reconnect attempts."""
        config = {
            "websocket": {
                "reconnect": {"max_attempts": "invalid"},
            }
        }
        limits = get_websocket_limits(config=config)
        assert limits.max_reconnect_attempts == DEFAULT_WS_RECONNECT_ATTEMPTS

    def test_handles_invalid_queue_size(self) -> None:
        """Fall back to default for invalid queue size."""
        config = {
            "websocket": {
                "queue": {"size": "invalid"},
            }
        }
        limits = get_websocket_limits(config=config)
        assert limits.queue_size == DEFAULT_WS_QUEUE_SIZE

    def test_handles_invalid_disconnect_check_interval(self) -> None:
        """Fall back to default for invalid disconnect check interval."""
        config = {
            "websocket": {
                "proactive": {"disconnect_check_interval": "invalid"},
            }
        }
        limits = get_websocket_limits(config=config)
        assert limits.disconnect_check_interval == DEFAULT_WS_DISCONNECT_CHECK

    def test_handles_invalid_reconnect_check_interval(self) -> None:
        """Fall back to default for invalid reconnect check interval."""
        config = {
            "websocket": {
                "proactive": {"reconnect_check_interval": "invalid"},
            }
        }
        limits = get_websocket_limits(config=config)
        assert limits.reconnect_check_interval == DEFAULT_WS_RECONNECT_CHECK

    def test_handles_invalid_disconnect_margin(self) -> None:
        """Fall back to default for invalid disconnect margin."""
        config = {
            "websocket": {
                "proactive": {"disconnect_margin": "invalid"},
            }
        }
        limits = get_websocket_limits(config=config)
        assert limits.disconnect_margin == DEFAULT_WS_DISCONNECT_MARGIN

    def test_handles_none_config(self) -> None:
        """Handle None config gracefully."""
        limits = get_websocket_limits(config=None)
        assert limits.ping_interval == DEFAULT_WS_PING_INTERVAL

    def test_handles_partial_config(self) -> None:
        """Handle partially missing config paths."""
        config: dict[str, dict[str, str]] = {
            "websocket": {
                # Missing ping, reconnect, etc.
            }
        }
        limits = get_websocket_limits(config=config)
        assert limits.ping_interval == DEFAULT_WS_PING_INTERVAL
        assert limits.reconnect_delay == DEFAULT_WS_RECONNECT_DELAY

    def test_handles_type_error_on_conversion(self) -> None:
        """Handle TypeError during value conversion."""
        config = {
            "websocket": {
                "ping": {"interval": {"nested": "dict"}},
                "reconnect": {"max_attempts": ["list", "value"]},
            }
        }
        limits = get_websocket_limits(config=config)
        assert limits.ping_interval == DEFAULT_WS_PING_INTERVAL
        assert limits.max_reconnect_attempts == DEFAULT_WS_RECONNECT_ATTEMPTS


class TestHardLimits:
    """Tests for hard limit constants."""

    def test_ping_interval_limits(self) -> None:
        """Ping interval hard limits are reasonable."""
        assert HARD_MIN_WS_PING_INTERVAL == 5.0
        assert HARD_MAX_WS_PING_INTERVAL == 60.0
        assert HARD_MIN_WS_PING_INTERVAL < HARD_MAX_WS_PING_INTERVAL

    def test_ping_timeout_limits(self) -> None:
        """Ping timeout hard limits are reasonable."""
        assert HARD_MIN_WS_PING_TIMEOUT == 5.0
        assert HARD_MAX_WS_PING_TIMEOUT == 30.0
        assert HARD_MIN_WS_PING_TIMEOUT < HARD_MAX_WS_PING_TIMEOUT

    def test_connection_timeout_limits(self) -> None:
        """Connection timeout hard limits are reasonable."""
        assert HARD_MIN_WS_CONNECTION_TIMEOUT == 5.0
        assert HARD_MAX_WS_CONNECTION_TIMEOUT == 120.0
        assert HARD_MIN_WS_CONNECTION_TIMEOUT < HARD_MAX_WS_CONNECTION_TIMEOUT

    def test_reconnect_delay_limits(self) -> None:
        """Reconnect delay hard limits are reasonable."""
        assert HARD_MIN_WS_RECONNECT_DELAY == 0.0  # Immediate allowed
        assert HARD_MAX_WS_RECONNECT_DELAY == 300.0  # 5 minutes
        assert HARD_MIN_WS_RECONNECT_DELAY < HARD_MAX_WS_RECONNECT_DELAY

    def test_max_reconnect_delay_limits(self) -> None:
        """Max reconnect delay hard limits are reasonable."""
        assert HARD_MIN_WS_MAX_RECONNECT_DELAY == 1.0
        assert HARD_MAX_WS_MAX_RECONNECT_DELAY == 600.0  # 10 minutes
        assert HARD_MIN_WS_MAX_RECONNECT_DELAY < HARD_MAX_WS_MAX_RECONNECT_DELAY

    def test_reconnect_attempts_limits(self) -> None:
        """Reconnect attempts hard limits are reasonable."""
        assert HARD_MIN_WS_RECONNECT_ATTEMPTS == 0  # No retry allowed
        assert HARD_MAX_WS_RECONNECT_ATTEMPTS == 100
        assert HARD_MIN_WS_RECONNECT_ATTEMPTS < HARD_MAX_WS_RECONNECT_ATTEMPTS

    def test_queue_size_limits(self) -> None:
        """Queue size hard limits are reasonable."""
        assert HARD_MIN_WS_QUEUE_SIZE == 0  # Unlimited allowed
        assert HARD_MAX_WS_QUEUE_SIZE == 10000
        assert HARD_MIN_WS_QUEUE_SIZE < HARD_MAX_WS_QUEUE_SIZE

    def test_disconnect_check_limits(self) -> None:
        """Disconnect check interval hard limits are reasonable."""
        assert HARD_MIN_WS_DISCONNECT_CHECK == 1.0
        assert HARD_MAX_WS_DISCONNECT_CHECK == 60.0
        assert HARD_MIN_WS_DISCONNECT_CHECK < HARD_MAX_WS_DISCONNECT_CHECK

    def test_reconnect_check_limits(self) -> None:
        """Reconnect check interval hard limits are reasonable."""
        assert HARD_MIN_WS_RECONNECT_CHECK == 0.5
        assert HARD_MAX_WS_RECONNECT_CHECK == 60.0
        assert HARD_MIN_WS_RECONNECT_CHECK < HARD_MAX_WS_RECONNECT_CHECK

    def test_disconnect_margin_limits(self) -> None:
        """Disconnect margin hard limits are reasonable."""
        assert HARD_MIN_WS_DISCONNECT_MARGIN == 60.0  # At least 1 minute
        assert HARD_MAX_WS_DISCONNECT_MARGIN == 3600.0  # Max 1 hour
        assert HARD_MIN_WS_DISCONNECT_MARGIN < HARD_MAX_WS_DISCONNECT_MARGIN


class TestDefaultValues:
    """Tests for default value constants."""

    def test_defaults_within_hard_limits(self) -> None:
        """Default values are within hard limits."""
        assert HARD_MIN_WS_PING_INTERVAL <= DEFAULT_WS_PING_INTERVAL <= HARD_MAX_WS_PING_INTERVAL
        assert HARD_MIN_WS_PING_TIMEOUT <= DEFAULT_WS_PING_TIMEOUT <= HARD_MAX_WS_PING_TIMEOUT
        assert HARD_MIN_WS_CONNECTION_TIMEOUT <= DEFAULT_WS_CONNECTION_TIMEOUT <= HARD_MAX_WS_CONNECTION_TIMEOUT
        assert HARD_MIN_WS_RECONNECT_DELAY <= DEFAULT_WS_RECONNECT_DELAY <= HARD_MAX_WS_RECONNECT_DELAY
        assert HARD_MIN_WS_MAX_RECONNECT_DELAY <= DEFAULT_WS_MAX_RECONNECT_DELAY <= HARD_MAX_WS_MAX_RECONNECT_DELAY
        assert HARD_MIN_WS_RECONNECT_ATTEMPTS <= DEFAULT_WS_RECONNECT_ATTEMPTS <= HARD_MAX_WS_RECONNECT_ATTEMPTS
        assert HARD_MIN_WS_QUEUE_SIZE <= DEFAULT_WS_QUEUE_SIZE <= HARD_MAX_WS_QUEUE_SIZE
        assert HARD_MIN_WS_DISCONNECT_CHECK <= DEFAULT_WS_DISCONNECT_CHECK <= HARD_MAX_WS_DISCONNECT_CHECK
        assert HARD_MIN_WS_RECONNECT_CHECK <= DEFAULT_WS_RECONNECT_CHECK <= HARD_MAX_WS_RECONNECT_CHECK
        assert HARD_MIN_WS_DISCONNECT_MARGIN <= DEFAULT_WS_DISCONNECT_MARGIN <= HARD_MAX_WS_DISCONNECT_MARGIN

    def test_default_values(self) -> None:
        """Default values are correct."""
        assert DEFAULT_WS_PING_INTERVAL == 20.0
        assert DEFAULT_WS_PING_TIMEOUT == 10.0
        assert DEFAULT_WS_CONNECTION_TIMEOUT == 30.0
        assert DEFAULT_WS_RECONNECT_DELAY == 1.0
        assert DEFAULT_WS_MAX_RECONNECT_DELAY == 60.0
        assert DEFAULT_WS_RECONNECT_ATTEMPTS == 10
        assert DEFAULT_WS_QUEUE_SIZE == 1000
        assert DEFAULT_WS_DISCONNECT_CHECK == 10.0
        assert DEFAULT_WS_RECONNECT_CHECK == 5.0
        assert DEFAULT_WS_DISCONNECT_MARGIN == 300.0
