"""Multi-channel alerting module with Slack and Email support.

This module provides a flexible alerting system for sending notifications
to multiple channels (Slack, Email) with level-based filtering and
rate limiting.

Key components:

- :class:`AlertManager`: Orchestrates multi-channel delivery
- :class:`AlertMessage`: The alert payload with title, body, and level
- :class:`AlertLevel`: Severity levels (INFO, WARNING, CRITICAL)
- :class:`AlertThrottle`: Rate limiting for alert floods

Channels:

- :class:`SlackChannel`: Slack webhook delivery
- :class:`EmailChannel`: Email delivery via kstlib.mail transports

Examples:
    Basic Slack alert::

        from kstlib.alerts import AlertManager, AlertMessage, AlertLevel
        from kstlib.alerts.channels import SlackChannel

        channel = SlackChannel(
            webhook_url="https://hooks.slack.com/services/T.../B.../xxx"
        )

        manager = AlertManager().add_channel(channel)

        alert = AlertMessage(
            title="Deployment Complete",
            body="Version 2.1.0 deployed to production",
            level=AlertLevel.INFO,
        )

        results = await manager.send(alert)

    Multi-channel with level filtering::

        from kstlib.alerts.channels import EmailChannel
        from kstlib.mail.transports import SMTPTransport

        smtp = SMTPTransport(host="smtp.example.com", port=587)
        email_channel = EmailChannel(
            transport=smtp,
            sender="alerts@example.com",
            recipients=["oncall@example.com"],
        )

        manager = (
            AlertManager()
            .add_channel(slack_channel, min_level=AlertLevel.WARNING)
            .add_channel(email_channel, min_level=AlertLevel.CRITICAL)
        )

        # This goes to Slack only (WARNING level)
        await manager.send(AlertMessage(
            title="High Memory",
            body="Memory at 85%",
            level=AlertLevel.WARNING,
        ))

        # This goes to both Slack and Email (CRITICAL level)
        await manager.send(AlertMessage(
            title="Server Down",
            body="API server not responding",
            level=AlertLevel.CRITICAL,
        ))

    With rate limiting::

        from kstlib.alerts.throttle import AlertThrottle

        throttle = AlertThrottle(rate=10, per=60.0)  # 10 per minute

        manager = AlertManager().add_channel(
            slack_channel,
            throttle=throttle,
        )

    From configuration::

        manager = AlertManager.from_config(
            config=app_config["alerts"],
            credential_resolver=resolver,
        )
"""

from kstlib.alerts.exceptions import (
    AlertConfigurationError,
    AlertDeliveryError,
    AlertError,
    AlertThrottledError,
)
from kstlib.alerts.manager import AlertManager
from kstlib.alerts.models import AlertLevel, AlertMessage, AlertResult
from kstlib.alerts.throttle import AlertThrottle

__all__ = [
    "AlertConfigurationError",
    "AlertDeliveryError",
    "AlertError",
    "AlertLevel",
    "AlertManager",
    "AlertMessage",
    "AlertResult",
    "AlertThrottle",
    "AlertThrottledError",
]
