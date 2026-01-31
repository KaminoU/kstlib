"""Tests for kstlib.websocket.exceptions module."""

from __future__ import annotations

import pytest

from kstlib.config.exceptions import KstlibError
from kstlib.websocket.exceptions import (
    WebSocketClosedError,
    WebSocketConnectionError,
    WebSocketError,
    WebSocketProtocolError,
    WebSocketQueueFullError,
    WebSocketReconnectError,
    WebSocketTimeoutError,
)


class TestWebSocketError:
    """Tests for WebSocketError base exception."""

    def test_inherits_from_kstlib_error(self) -> None:
        """WebSocketError should inherit from KstlibError."""
        assert issubclass(WebSocketError, KstlibError)

    def test_can_raise_with_message(self) -> None:
        """WebSocketError can be raised with a message."""
        with pytest.raises(WebSocketError, match="test error"):
            raise WebSocketError("test error")


class TestWebSocketConnectionError:
    """Tests for WebSocketConnectionError exception."""

    def test_inherits_from_websocket_error(self) -> None:
        """WebSocketConnectionError should inherit from WebSocketError."""
        assert issubclass(WebSocketConnectionError, WebSocketError)

    def test_inherits_from_connection_error(self) -> None:
        """WebSocketConnectionError should inherit from ConnectionError."""
        assert issubclass(WebSocketConnectionError, ConnectionError)

    def test_stores_url(self) -> None:
        """WebSocketConnectionError stores url attribute."""
        error = WebSocketConnectionError("Failed", url="wss://example.com")
        assert error.url == "wss://example.com"
        assert str(error) == "Failed"

    def test_stores_attempts(self) -> None:
        """WebSocketConnectionError stores attempts attribute."""
        error = WebSocketConnectionError("Failed", attempts=5)
        assert error.attempts == 5

    def test_stores_last_error(self) -> None:
        """WebSocketConnectionError stores last_error attribute."""
        cause = OSError("Connection refused")
        error = WebSocketConnectionError("Failed", last_error=cause)
        assert error.last_error is cause

    def test_default_values(self) -> None:
        """WebSocketConnectionError has correct default values."""
        error = WebSocketConnectionError("Failed")
        assert error.url == ""
        assert error.attempts == 0
        assert error.last_error is None

    def test_can_raise_and_catch(self) -> None:
        """WebSocketConnectionError can be raised and caught."""
        with pytest.raises(WebSocketConnectionError) as exc_info:
            raise WebSocketConnectionError(
                "Connection failed",
                url="wss://test.com",
                attempts=3,
            )
        assert exc_info.value.url == "wss://test.com"
        assert exc_info.value.attempts == 3


class TestWebSocketClosedError:
    """Tests for WebSocketClosedError exception."""

    def test_inherits_from_websocket_error(self) -> None:
        """WebSocketClosedError should inherit from WebSocketError."""
        assert issubclass(WebSocketClosedError, WebSocketError)

    def test_stores_code(self) -> None:
        """WebSocketClosedError stores code attribute."""
        error = WebSocketClosedError("Connection closed", code=1000)
        assert error.code == 1000

    def test_stores_reason(self) -> None:
        """WebSocketClosedError stores reason attribute."""
        error = WebSocketClosedError("Closed", reason="Normal closure")
        assert error.reason == "Normal closure"

    def test_default_values(self) -> None:
        """WebSocketClosedError has correct default values."""
        error = WebSocketClosedError("Closed")
        assert error.code == 1006  # Default abnormal closure
        assert error.reason == ""

    def test_can_raise_and_catch(self) -> None:
        """WebSocketClosedError can be raised and caught."""
        with pytest.raises(WebSocketClosedError) as exc_info:
            raise WebSocketClosedError("Server closed", code=1001, reason="Going away")
        assert exc_info.value.code == 1001
        assert exc_info.value.reason == "Going away"


class TestWebSocketTimeoutError:
    """Tests for WebSocketTimeoutError exception."""

    def test_inherits_from_websocket_error(self) -> None:
        """WebSocketTimeoutError should inherit from WebSocketError."""
        assert issubclass(WebSocketTimeoutError, WebSocketError)

    def test_inherits_from_timeout_error(self) -> None:
        """WebSocketTimeoutError should inherit from TimeoutError."""
        assert issubclass(WebSocketTimeoutError, TimeoutError)

    def test_stores_operation(self) -> None:
        """WebSocketTimeoutError stores operation attribute."""
        error = WebSocketTimeoutError("Timed out", operation="connect")
        assert error.operation == "connect"

    def test_stores_timeout(self) -> None:
        """WebSocketTimeoutError stores timeout attribute."""
        error = WebSocketTimeoutError("Timed out", timeout=30.0)
        assert error.timeout == 30.0

    def test_default_values(self) -> None:
        """WebSocketTimeoutError has correct default values."""
        error = WebSocketTimeoutError("Timed out")
        assert error.operation == ""
        assert error.timeout == 0.0

    def test_can_raise_and_catch(self) -> None:
        """WebSocketTimeoutError can be raised and caught."""
        with pytest.raises(WebSocketTimeoutError) as exc_info:
            raise WebSocketTimeoutError(
                "Ping timeout",
                operation="ping",
                timeout=10.0,
            )
        assert exc_info.value.operation == "ping"
        assert exc_info.value.timeout == 10.0


class TestWebSocketReconnectError:
    """Tests for WebSocketReconnectError exception."""

    def test_inherits_from_websocket_error(self) -> None:
        """WebSocketReconnectError should inherit from WebSocketError."""
        assert issubclass(WebSocketReconnectError, WebSocketError)

    def test_stores_attempts(self) -> None:
        """WebSocketReconnectError stores attempts attribute."""
        error = WebSocketReconnectError("Reconnect failed", attempts=10)
        assert error.attempts == 10

    def test_stores_last_error(self) -> None:
        """WebSocketReconnectError stores last_error attribute."""
        cause = OSError("Network unreachable")
        error = WebSocketReconnectError("Reconnect failed", last_error=cause)
        assert error.last_error is cause

    def test_default_values(self) -> None:
        """WebSocketReconnectError has correct default values."""
        error = WebSocketReconnectError("Reconnect failed")
        assert error.attempts == 0
        assert error.last_error is None

    def test_can_raise_and_catch(self) -> None:
        """WebSocketReconnectError can be raised and caught."""
        with pytest.raises(WebSocketReconnectError) as exc_info:
            raise WebSocketReconnectError(
                "Max attempts exceeded",
                attempts=5,
            )
        assert exc_info.value.attempts == 5


class TestWebSocketProtocolError:
    """Tests for WebSocketProtocolError exception."""

    def test_inherits_from_websocket_error(self) -> None:
        """WebSocketProtocolError should inherit from WebSocketError."""
        assert issubclass(WebSocketProtocolError, WebSocketError)

    def test_stores_protocol_error(self) -> None:
        """WebSocketProtocolError stores protocol_error attribute."""
        error = WebSocketProtocolError("Protocol violation", protocol_error="Invalid frame")
        assert error.protocol_error == "Invalid frame"

    def test_default_value(self) -> None:
        """WebSocketProtocolError has correct default value."""
        error = WebSocketProtocolError("Protocol error")
        assert error.protocol_error == ""

    def test_can_raise_and_catch(self) -> None:
        """WebSocketProtocolError can be raised and caught."""
        with pytest.raises(WebSocketProtocolError) as exc_info:
            raise WebSocketProtocolError(
                "Malformed message",
                protocol_error="Invalid JSON",
            )
        assert exc_info.value.protocol_error == "Invalid JSON"


class TestWebSocketQueueFullError:
    """Tests for WebSocketQueueFullError exception."""

    def test_inherits_from_websocket_error(self) -> None:
        """WebSocketQueueFullError should inherit from WebSocketError."""
        assert issubclass(WebSocketQueueFullError, WebSocketError)

    def test_stores_queue_size(self) -> None:
        """WebSocketQueueFullError stores queue_size attribute."""
        error = WebSocketQueueFullError("Queue full", queue_size=1000)
        assert error.queue_size == 1000

    def test_stores_dropped_count(self) -> None:
        """WebSocketQueueFullError stores dropped_count attribute."""
        error = WebSocketQueueFullError("Queue full", dropped_count=50)
        assert error.dropped_count == 50

    def test_default_values(self) -> None:
        """WebSocketQueueFullError has correct default values."""
        error = WebSocketQueueFullError("Queue full")
        assert error.queue_size == 0
        assert error.dropped_count == 0

    def test_can_raise_and_catch(self) -> None:
        """WebSocketQueueFullError can be raised and caught."""
        with pytest.raises(WebSocketQueueFullError) as exc_info:
            raise WebSocketQueueFullError(
                "Message dropped",
                queue_size=500,
                dropped_count=10,
            )
        assert exc_info.value.queue_size == 500
        assert exc_info.value.dropped_count == 10


class TestExceptionHierarchy:
    """Tests for exception hierarchy."""

    def test_all_exceptions_catch_with_base(self) -> None:
        """All WebSocket exceptions can be caught with WebSocketError."""
        exceptions = [
            WebSocketConnectionError("test"),
            WebSocketClosedError("test"),
            WebSocketTimeoutError("test"),
            WebSocketReconnectError("test"),
            WebSocketProtocolError("test"),
            WebSocketQueueFullError("test"),
        ]
        for exc in exceptions:
            with pytest.raises(WebSocketError):
                raise exc

    def test_all_exceptions_catch_with_kstlib_error(self) -> None:
        """All WebSocket exceptions can be caught with KstlibError."""
        exceptions = [
            WebSocketError("test"),
            WebSocketConnectionError("test"),
            WebSocketClosedError("test"),
            WebSocketTimeoutError("test"),
            WebSocketReconnectError("test"),
            WebSocketProtocolError("test"),
            WebSocketQueueFullError("test"),
        ]
        for exc in exceptions:
            with pytest.raises(KstlibError):
                raise exc
