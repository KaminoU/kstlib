"""Email channel for alert delivery.

Sends alerts via email using kstlib.mail transports. Supports both
sync and async transports with automatic wrapping.

Examples:
    With SMTP transport::

        from kstlib.alerts.channels import EmailChannel
        from kstlib.mail.transports import SMTPTransport

        transport = SMTPTransport(host="smtp.example.com", port=587)
        channel = EmailChannel(
            transport=transport,
            sender="alerts@example.com",
            recipients=["oncall@example.com"],
        )

        result = await channel.send(alert)

    With async transport (Resend)::

        from kstlib.mail.transports import ResendTransport

        transport = ResendTransport(api_key="re_xxx")
        channel = EmailChannel(
            transport=transport,
            sender="alerts@example.com",
            recipients=["oncall@example.com", "backup@example.com"],
            subject_prefix="[PROD ALERT]",
        )
"""

from __future__ import annotations

import logging
from email.message import EmailMessage
from typing import TYPE_CHECKING

from kstlib.alerts.channels.base import AsyncAlertChannel
from kstlib.alerts.exceptions import AlertConfigurationError, AlertDeliveryError
from kstlib.alerts.models import AlertLevel, AlertResult
from kstlib.mail.transport import AsyncMailTransport, AsyncTransportWrapper, MailTransport

if TYPE_CHECKING:
    from collections.abc import Sequence

    from kstlib.alerts.models import AlertMessage

__all__ = ["EmailChannel"]

log = logging.getLogger(__name__)

# Subject prefix emoji for alert levels
LEVEL_PREFIX = {
    AlertLevel.INFO: "[INFO]",
    AlertLevel.WARNING: "[WARNING]",
    AlertLevel.CRITICAL: "[CRITICAL]",
}


class EmailChannel(AsyncAlertChannel):
    """Async channel for sending alerts via email.

    Wraps kstlib.mail transports to send alert messages as emails.
    Sync transports are automatically wrapped for async usage.

    Args:
        transport: Mail transport (sync or async).
        sender: Email sender address.
        recipients: List of recipient email addresses.
        subject_prefix: Prefix for email subjects (default: '[ALERT]').
        channel_name: Optional name override for this channel.

    Raises:
        AlertConfigurationError: If configuration is invalid.

    Examples:
        With SMTP::

            transport = SMTPTransport(host="smtp.example.com", port=587)
            channel = EmailChannel(
                transport=transport,
                sender="alerts@example.com",
                recipients=["team@example.com"],
            )

        With Gmail::

            from kstlib.mail.transports import GmailOAuth2Transport

            transport = GmailOAuth2Transport.from_config(config)
            channel = EmailChannel(
                transport=transport,
                sender="alerts@company.com",
                recipients=["oncall@company.com"],
                subject_prefix="[PROD]",
            )
    """

    def __init__(
        self,
        transport: MailTransport | AsyncMailTransport,
        *,
        sender: str,
        recipients: Sequence[str],
        subject_prefix: str = "[ALERT]",
        channel_name: str | None = None,
    ) -> None:
        """Initialize EmailChannel.

        Args:
            transport: Mail transport (sync or async).
            sender: Email sender address.
            recipients: List of recipient email addresses.
            subject_prefix: Prefix for email subjects.
            channel_name: Optional name override for this channel.

        Raises:
            AlertConfigurationError: If configuration is invalid.
        """
        if not sender:
            raise AlertConfigurationError("Email sender is required")

        if not recipients:
            raise AlertConfigurationError("At least one recipient is required")

        # Wrap sync transport for async usage
        if isinstance(transport, MailTransport):
            self._transport: AsyncMailTransport = AsyncTransportWrapper(transport)
        else:
            self._transport = transport

        self._sender = sender
        self._recipients = list(recipients)
        self._subject_prefix = subject_prefix
        self._channel_name = channel_name or "email"

        log.debug(
            "EmailChannel initialized: sender=%s, recipients=%d",
            sender,
            len(self._recipients),
        )

    @property
    def name(self) -> str:
        """Return the channel name."""
        return self._channel_name

    async def send(self, alert: AlertMessage) -> AlertResult:
        """Send an alert via email.

        Constructs an email message with appropriate subject and body
        formatting based on the alert level.

        Args:
            alert: The alert message to send.

        Returns:
            AlertResult with delivery status.

        Raises:
            AlertDeliveryError: If email delivery fails.
        """
        message = self._build_message(alert)

        log.debug(
            "Sending alert email: level=%s, recipients=%d",
            alert.level.name,
            len(self._recipients),
        )

        try:
            await self._transport.send(message)

            log.debug("Alert email sent successfully")
            return AlertResult(
                channel=self.name,
                success=True,
            )

        except Exception as e:
            log.warning("Email delivery failed: %s", e)
            raise AlertDeliveryError(
                f"Email delivery failed: {e}",
                channel=self.name,
                retryable=True,
            ) from e

    def _build_message(self, alert: AlertMessage) -> EmailMessage:
        """Build email message from alert.

        Args:
            alert: The alert message.

        Returns:
            EmailMessage ready for transport.
        """
        message = EmailMessage()

        # Build subject with level indicator (use formatted_title for timestamp)
        level_prefix = LEVEL_PREFIX.get(alert.level, "[ALERT]")
        subject = f"{self._subject_prefix} {level_prefix} {alert.formatted_title}"
        message["Subject"] = subject

        message["From"] = self._sender
        message["To"] = ", ".join(self._recipients)

        # Build body with level context
        formatted = alert.formatted_title
        body = f"""Alert Level: {alert.level.name}

{formatted}
{"=" * len(formatted)}

{alert.body}

---
Sent by kstlib.alerts
"""
        message.set_content(body)

        return message

    def __repr__(self) -> str:
        """Return string representation."""
        return f"EmailChannel(sender={self._sender!r}, recipients={len(self._recipients)}, name={self._channel_name!r})"
