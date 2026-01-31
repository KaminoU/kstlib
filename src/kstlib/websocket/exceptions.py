"""WebSocket exception hierarchy.

All WebSocket exceptions inherit from WebSocketError, allowing users to catch
all WebSocket-specific errors with a single except clause.

Example:
    >>> from kstlib.websocket import WebSocketError
    >>> try:
    ...     await manager.connect()
    ... except WebSocketError as e:  # doctest: +SKIP
    ...     print(f"WebSocket error: {e}")
"""

from __future__ import annotations

from kstlib.config.exceptions import KstlibError

__all__ = [
    "WebSocketClosedError",
    "WebSocketConnectionError",
    "WebSocketError",
    "WebSocketProtocolError",
    "WebSocketQueueFullError",
    "WebSocketReconnectError",
    "WebSocketTimeoutError",
]


class WebSocketError(KstlibError):
    """Base exception for all WebSocket errors.

    All WebSocket-specific exceptions inherit from this class,
    allowing for easy catching of any WebSocket error.
    """


class WebSocketConnectionError(WebSocketError, ConnectionError):
    """Failed to establish WebSocket connection.

    Raised when the initial connection or reconnection fails after
    exhausting all retry attempts.

    Attributes:
        url: The WebSocket URL that failed to connect.
        attempts: Number of connection attempts made.
        last_error: The underlying error from the last attempt.
    """

    def __init__(
        self,
        message: str,
        *,
        url: str = "",
        attempts: int = 0,
        last_error: BaseException | None = None,
    ) -> None:
        """Initialize connection error.

        Args:
            message: Human-readable error description.
            url: The WebSocket URL that failed to connect.
            attempts: Number of connection attempts made.
            last_error: The underlying error from the last attempt.
        """
        super().__init__(message)
        self.url = url
        self.attempts = attempts
        self.last_error = last_error


class WebSocketClosedError(WebSocketError):
    """WebSocket connection was closed.

    Raised when the connection is closed unexpectedly by the server
    or due to a protocol error.

    Attributes:
        code: WebSocket close code (1000-4999).
        reason: Optional human-readable close reason.
    """

    def __init__(
        self,
        message: str,
        *,
        code: int = 1006,
        reason: str = "",
    ) -> None:
        """Initialize closed error.

        Args:
            message: Human-readable error description.
            code: WebSocket close code (1000-4999).
            reason: Optional human-readable close reason.
        """
        super().__init__(message)
        self.code = code
        self.reason = reason


class WebSocketTimeoutError(WebSocketError, TimeoutError):
    """WebSocket operation timed out.

    Raised when a WebSocket operation (connect, ping, receive) exceeds
    its configured timeout.

    Attributes:
        operation: The operation that timed out (connect, ping, receive).
        timeout: The timeout value in seconds.
    """

    def __init__(
        self,
        message: str,
        *,
        operation: str = "",
        timeout: float = 0.0,
    ) -> None:
        """Initialize timeout error.

        Args:
            message: Human-readable error description.
            operation: The operation that timed out.
            timeout: The timeout value in seconds.
        """
        super().__init__(message)
        self.operation = operation
        self.timeout = timeout


class WebSocketReconnectError(WebSocketError):
    """Failed to reconnect after disconnection.

    Raised when all reconnection attempts have been exhausted
    without successfully re-establishing the connection.

    Attributes:
        attempts: Total number of reconnection attempts made.
        last_error: The underlying error from the last attempt.
    """

    def __init__(
        self,
        message: str,
        *,
        attempts: int = 0,
        last_error: BaseException | None = None,
    ) -> None:
        """Initialize reconnect error.

        Args:
            message: Human-readable error description.
            attempts: Total number of reconnection attempts made.
            last_error: The underlying error from the last attempt.
        """
        super().__init__(message)
        self.attempts = attempts
        self.last_error = last_error


class WebSocketProtocolError(WebSocketError):
    """WebSocket protocol violation.

    Raised when the server or client violates the WebSocket protocol,
    such as sending malformed frames or invalid data.

    Attributes:
        protocol_error: Description of the protocol violation.
    """

    def __init__(
        self,
        message: str,
        *,
        protocol_error: str = "",
    ) -> None:
        """Initialize protocol error.

        Args:
            message: Human-readable error description.
            protocol_error: Description of the protocol violation.
        """
        super().__init__(message)
        self.protocol_error = protocol_error


class WebSocketQueueFullError(WebSocketError):
    """Message queue is full.

    Raised when the incoming message queue is full and cannot accept
    more messages. This typically indicates the consumer is too slow.

    Attributes:
        queue_size: Maximum queue size that was exceeded.
        dropped_count: Number of messages dropped due to queue overflow.
    """

    def __init__(
        self,
        message: str,
        *,
        queue_size: int = 0,
        dropped_count: int = 0,
    ) -> None:
        """Initialize queue full error.

        Args:
            message: Human-readable error description.
            queue_size: Maximum queue size that was exceeded.
            dropped_count: Number of messages dropped due to queue overflow.
        """
        super().__init__(message)
        self.queue_size = queue_size
        self.dropped_count = dropped_count
