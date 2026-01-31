"""Data models for the alerts module.

This module defines the core data structures for alert messages, levels,
and delivery results.

Examples:
    Creating an alert message::

        from kstlib.alerts.models import AlertLevel, AlertMessage

        alert = AlertMessage(
            title="Server Down",
            body="Production server api-1 is not responding",
            level=AlertLevel.CRITICAL,
        )

    Checking alert results::

        from kstlib.alerts.models import AlertResult

        result = AlertResult(channel="slack", success=True, message_id="12345")
        if result.success:
            print(f"Alert delivered: {result.message_id}")
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum


class AlertLevel(IntEnum):
    """Severity level for alerts.

    Values are ordered by severity (higher value = more severe).
    Use these to filter which alerts go to which channels.

    Attributes:
        INFO: Informational messages (10).
        WARNING: Warning conditions that need attention (20).
        CRITICAL: Critical issues requiring immediate action (30).

    Examples:
        >>> AlertLevel.CRITICAL > AlertLevel.WARNING
        True
        >>> AlertLevel.INFO.name
        'INFO'
        >>> int(AlertLevel.WARNING)
        20
    """

    INFO = 10
    WARNING = 20
    CRITICAL = 30


@dataclass(frozen=True, slots=True)
class AlertMessage:
    """An alert message to be sent via one or more channels.

    Attributes:
        title: Short summary of the alert (max 150 chars for Slack).
        body: Detailed message content (max 3000 chars for Slack).
        level: Severity level of the alert.
        timestamp: If True, prefix title with send datetime.

    Examples:
        >>> msg = AlertMessage(title="Disk Full", body="Server disk at 95%")
        >>> msg.level
        <AlertLevel.INFO: 10>
        >>> msg = AlertMessage(
        ...     title="DB Connection Failed",
        ...     body="Cannot connect to primary database",
        ...     level=AlertLevel.CRITICAL,
        ... )
        >>> msg.level.name
        'CRITICAL'
        >>> msg = AlertMessage(
        ...     title="Alert",
        ...     body="With timestamp",
        ...     timestamp=True,
        ... )
        >>> ":::" in msg.formatted_title
        True
    """

    title: str
    body: str
    level: AlertLevel = AlertLevel.INFO
    timestamp: bool = False

    @property
    def formatted_title(self) -> str:
        """Return title with optional timestamp prefix.

        If timestamp is True, prefixes the title with current datetime
        in format "YYYY-MM-DD HH:MM:SS ::: ".

        Returns:
            Title string, optionally prefixed with timestamp.

        Examples:
            >>> msg = AlertMessage(title="Test", body="Body", timestamp=False)
            >>> msg.formatted_title
            'Test'
            >>> msg = AlertMessage(title="Test", body="Body", timestamp=True)
            >>> "Test" in msg.formatted_title
            True
        """
        if self.timestamp:
            now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
            return f"{now} ::: {self.title}"
        return self.title


@dataclass(frozen=True, slots=True)
class AlertResult:
    """Result of sending an alert to a channel.

    Attributes:
        channel: Name of the channel that processed this alert.
        success: Whether the alert was delivered successfully.
        message_id: ID assigned by the channel (if available).
        error: Error message if delivery failed.

    Examples:
        >>> result = AlertResult(channel="slack", success=True, message_id="msg123")
        >>> result.success
        True
        >>> result = AlertResult(channel="email", success=False, error="SMTP timeout")
        >>> result.error
        'SMTP timeout'
    """

    channel: str
    success: bool
    message_id: str | None = None
    error: str | None = None


__all__ = ["AlertLevel", "AlertMessage", "AlertResult"]
