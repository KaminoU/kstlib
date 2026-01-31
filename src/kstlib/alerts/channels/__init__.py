"""Alert channel implementations.

Provides both sync and async channel interfaces for different alert
delivery backends (Slack, Email, etc.).

Examples:
    Using SlackChannel::

        from kstlib.alerts.channels import SlackChannel

        channel = SlackChannel(webhook_url="https://hooks.slack.com/...")
        await channel.send(alert)

    Using EmailChannel with existing mail transport::

        from kstlib.alerts.channels import EmailChannel
        from kstlib.mail.transports import SMTPTransport

        transport = SMTPTransport(host="smtp.example.com", port=587)
        channel = EmailChannel(
            transport=transport,
            sender="alerts@example.com",
            recipients=["oncall@example.com"],
        )
"""

from kstlib.alerts.channels.base import AlertChannel, AsyncAlertChannel
from kstlib.alerts.channels.email import EmailChannel
from kstlib.alerts.channels.slack import SlackChannel

__all__ = [
    "AlertChannel",
    "AsyncAlertChannel",
    "EmailChannel",
    "SlackChannel",
]
