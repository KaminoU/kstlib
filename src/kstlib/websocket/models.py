"""WebSocket data models and enumerations.

This module provides the core data structures for the WebSocket manager:

- **ConnectionState**: State machine for connection lifecycle
- **DisconnectReason**: Categorizes disconnection causes (proactive vs reactive)
- **ReconnectStrategy**: Available reconnection strategies
- **WebSocketStats**: Connection and message statistics

Examples:
    >>> from kstlib.websocket.models import ConnectionState, DisconnectReason
    >>> state = ConnectionState.CONNECTED
    >>> reason = DisconnectReason.USER_REQUESTED
    >>> reason.is_proactive
    True
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto

__all__ = [
    "ConnectionState",
    "DisconnectReason",
    "ReconnectStrategy",
    "WebSocketStats",
]


class ConnectionState(Enum):
    """WebSocket connection state machine.

    State transitions:
        DISCONNECTED -> CONNECTING -> CONNECTED
        CONNECTED -> RECONNECTING -> CONNECTED (on success)
        CONNECTED -> RECONNECTING -> DISCONNECTED (on failure)
        CONNECTED -> CLOSING -> CLOSED
        Any state -> CLOSED (on force_close)

    Attributes:
        DISCONNECTED: Initial state, not connected.
        CONNECTING: Connection attempt in progress.
        CONNECTED: WebSocket connection is active.
        RECONNECTING: Attempting to restore lost connection.
        CLOSING: Graceful shutdown in progress.
        CLOSED: Terminal state, cannot reconnect.
    """

    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    RECONNECTING = auto()
    CLOSING = auto()
    CLOSED = auto()

    def can_connect(self) -> bool:
        """Check if a connection attempt is allowed from this state.

        Returns:
            True if connect() can be called from this state.

        Examples:
            >>> ConnectionState.DISCONNECTED.can_connect()
            True
            >>> ConnectionState.CONNECTED.can_connect()
            False
        """
        return self in (ConnectionState.DISCONNECTED, ConnectionState.RECONNECTING)

    def can_send(self) -> bool:
        """Check if sending messages is allowed from this state.

        Returns:
            True if send() can be called from this state.

        Examples:
            >>> ConnectionState.CONNECTED.can_send()
            True
            >>> ConnectionState.DISCONNECTED.can_send()
            False
        """
        return self == ConnectionState.CONNECTED

    def is_terminal(self) -> bool:
        """Check if this is a terminal state.

        Returns:
            True if no further state transitions are possible.

        Examples:
            >>> ConnectionState.CLOSED.is_terminal()
            True
            >>> ConnectionState.DISCONNECTED.is_terminal()
            False
        """
        return self == ConnectionState.CLOSED


class DisconnectReason(Enum):
    """Reason for WebSocket disconnection.

    Disconnections are categorized as either proactive (user-controlled)
    or reactive (forced by external factors). This distinction is key
    for the proactive connection control feature.

    Proactive reasons (user-controlled):
        USER_REQUESTED: Manual disconnect via request_disconnect()
        SCHEDULED: Disconnect triggered by schedule_reconnect()
        CALLBACK_TRIGGERED: should_disconnect() callback returned True
        CONNECTION_LIMIT: Preemptive disconnect before platform limit

    Reactive reasons (forced):
        SERVER_CLOSED: Server initiated the close
        NETWORK_ERROR: Network connectivity issue
        PING_TIMEOUT: No pong response within timeout
        PROTOCOL_ERROR: WebSocket protocol violation
    """

    # Proactive (user-controlled) disconnections
    USER_REQUESTED = auto()
    SCHEDULED = auto()
    CALLBACK_TRIGGERED = auto()
    CONNECTION_LIMIT = auto()

    # Reactive (forced) disconnections
    SERVER_CLOSED = auto()
    NETWORK_ERROR = auto()
    PING_TIMEOUT = auto()
    PROTOCOL_ERROR = auto()
    KILLED = auto()  # Simulated external kill (e.g., Binance forced disconnect)

    @property
    def is_proactive(self) -> bool:
        """Check if this is a proactive (user-controlled) disconnection.

        Returns:
            True if the disconnection was initiated by the user/application.

        Examples:
            >>> DisconnectReason.USER_REQUESTED.is_proactive
            True
            >>> DisconnectReason.NETWORK_ERROR.is_proactive
            False
        """
        return self in (
            DisconnectReason.USER_REQUESTED,
            DisconnectReason.SCHEDULED,
            DisconnectReason.CALLBACK_TRIGGERED,
            DisconnectReason.CONNECTION_LIMIT,
        )

    @property
    def is_reactive(self) -> bool:
        """Check if this is a reactive (forced) disconnection.

        Returns:
            True if the disconnection was forced by external factors.

        Examples:
            >>> DisconnectReason.SERVER_CLOSED.is_reactive
            True
            >>> DisconnectReason.USER_REQUESTED.is_reactive
            False
        """
        return not self.is_proactive


class ReconnectStrategy(Enum):
    """Reconnection strategy after disconnection.

    Attributes:
        IMMEDIATE: Reconnect immediately without delay.
        FIXED_DELAY: Wait a fixed delay before each attempt.
        EXPONENTIAL_BACKOFF: Exponentially increasing delays.
        CALLBACK_CONTROLLED: Reconnection timing controlled by callback.
    """

    IMMEDIATE = auto()
    FIXED_DELAY = auto()
    EXPONENTIAL_BACKOFF = auto()
    CALLBACK_CONTROLLED = auto()


@dataclass
class WebSocketStats:
    """WebSocket connection and message statistics.

    Tracks both connection lifecycle events and message throughput.
    The key distinction is between proactive and reactive disconnections,
    which is central to the proactive control feature.

    Attributes:
        connects: Total successful connection count.
        disconnects: Total disconnection count.
        proactive_disconnects: Disconnections initiated by user/application.
        reactive_disconnects: Disconnections forced by external factors.
        messages_received: Total messages received.
        messages_sent: Total messages sent.
        bytes_received: Total bytes received.
        bytes_sent: Total bytes sent.
        last_connect_time: Unix timestamp of last successful connection.
        last_disconnect_time: Unix timestamp of last disconnection.
        last_message_time: Unix timestamp of last message (sent or received).

    Examples:
        >>> stats = WebSocketStats()
        >>> stats.record_connect()
        >>> stats.connects
        1
        >>> stats.record_disconnect(proactive=True)
        >>> stats.proactive_disconnects
        1
    """

    connects: int = 0
    disconnects: int = 0
    proactive_disconnects: int = 0
    reactive_disconnects: int = 0
    messages_received: int = 0
    messages_sent: int = 0
    bytes_received: int = 0
    bytes_sent: int = 0
    last_connect_time: float = 0.0
    last_disconnect_time: float = 0.0
    last_message_time: float = 0.0
    _start_time: float = field(default_factory=time.monotonic)

    def record_connect(self) -> None:
        """Record a successful connection.

        Examples:
            >>> stats = WebSocketStats()
            >>> stats.record_connect()
            >>> stats.connects
            1
        """
        self.connects += 1
        self.last_connect_time = time.time()

    def record_disconnect(self, *, proactive: bool = False) -> None:
        """Record a disconnection.

        Args:
            proactive: True if this was a user-initiated disconnection.

        Examples:
            >>> stats = WebSocketStats()
            >>> stats.record_disconnect(proactive=True)
            >>> stats.proactive_disconnects
            1
            >>> stats.record_disconnect(proactive=False)
            >>> stats.reactive_disconnects
            1
        """
        self.disconnects += 1
        self.last_disconnect_time = time.time()
        if proactive:
            self.proactive_disconnects += 1
        else:
            self.reactive_disconnects += 1

    def record_message_received(self, size: int = 0) -> None:
        """Record a received message.

        Args:
            size: Size of the message in bytes.

        Examples:
            >>> stats = WebSocketStats()
            >>> stats.record_message_received(100)
            >>> stats.messages_received
            1
            >>> stats.bytes_received
            100
        """
        self.messages_received += 1
        self.bytes_received += size
        self.last_message_time = time.time()

    def record_message_sent(self, size: int = 0) -> None:
        """Record a sent message.

        Args:
            size: Size of the message in bytes.

        Examples:
            >>> stats = WebSocketStats()
            >>> stats.record_message_sent(50)
            >>> stats.messages_sent
            1
            >>> stats.bytes_sent
            50
        """
        self.messages_sent += 1
        self.bytes_sent += size
        self.last_message_time = time.time()

    @property
    def uptime(self) -> float:
        """Time since stats object was created, in seconds.

        Returns:
            Elapsed time in seconds.

        Examples:
            >>> import time
            >>> stats = WebSocketStats()
            >>> time.sleep(0.05)
            >>> stats.uptime > 0
            True
        """
        return time.monotonic() - self._start_time

    @property
    def connection_time(self) -> float:
        """Time since last connection, in seconds.

        Returns zero if never connected.

        Returns:
            Elapsed time since last connect, or 0 if never connected.

        Examples:
            >>> stats = WebSocketStats()
            >>> stats.connection_time
            0.0
            >>> stats.record_connect()
            >>> stats.connection_time > 0 or stats.connection_time == 0.0
            True
        """
        if self.last_connect_time == 0.0:
            return 0.0
        return time.time() - self.last_connect_time

    def reset(self) -> None:
        """Reset all statistics to zero.

        Examples:
            >>> stats = WebSocketStats()
            >>> stats.record_connect()
            >>> stats.record_message_sent(100)
            >>> stats.reset()
            >>> stats.connects
            0
            >>> stats.messages_sent
            0
        """
        self.connects = 0
        self.disconnects = 0
        self.proactive_disconnects = 0
        self.reactive_disconnects = 0
        self.messages_received = 0
        self.messages_sent = 0
        self.bytes_received = 0
        self.bytes_sent = 0
        self.last_connect_time = 0.0
        self.last_disconnect_time = 0.0
        self.last_message_time = 0.0
        self._start_time = time.monotonic()
