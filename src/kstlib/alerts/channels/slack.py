"""Slack webhook channel for alert delivery.

Sends alerts to Slack via incoming webhook URLs. Supports all alert
levels with appropriate formatting and emoji indicators.

Requirements:
    pip install httpx

Security:
    - Webhook URLs are validated to prevent SSRF
    - URLs are masked in logs and repr output
    - Payloads are truncated to Slack limits

Examples:
    Basic usage::

        from kstlib.alerts.channels import SlackChannel
        from kstlib.alerts.models import AlertMessage, AlertLevel

        channel = SlackChannel(
            webhook_url="https://hooks.slack.com/services/T.../B.../xxx"
        )

        alert = AlertMessage(
            title="Deployment Complete",
            body="Version 2.1.0 deployed to production",
            level=AlertLevel.INFO,
        )

        result = await channel.send(alert)

    With SOPS credentials::

        channel = SlackChannel.from_config(
            config={"credentials": "slack_webhook"},
            credential_resolver=resolver,
        )
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from kstlib.alerts.channels.base import AsyncAlertChannel
from kstlib.alerts.exceptions import AlertConfigurationError, AlertDeliveryError
from kstlib.alerts.models import AlertLevel, AlertResult
from kstlib.limits import (
    HARD_MAX_CHANNEL_TIMEOUT,
    HARD_MIN_CHANNEL_TIMEOUT,
    clamp_with_limits,
    get_alerts_limits,
)
from kstlib.ssl import build_ssl_context

if TYPE_CHECKING:
    from collections.abc import Mapping

    from kstlib.alerts.models import AlertMessage
    from kstlib.rapi.credentials import CredentialResolver

__all__ = ["SlackChannel"]

log = logging.getLogger(__name__)

# Slack limits
MAX_TITLE_LENGTH = 150
MAX_BODY_LENGTH = 3000

# Trusted Slack webhook URL pattern
SLACK_WEBHOOK_PATTERN = re.compile(r"^https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[a-zA-Z0-9]+$")

# Emoji indicators for alert levels
LEVEL_EMOJI = {
    AlertLevel.INFO: ":information_source:",
    AlertLevel.WARNING: ":warning:",
    AlertLevel.CRITICAL: ":rotating_light:",
}

# Color indicators for alert levels (Slack attachment colors)
LEVEL_COLOR = {
    AlertLevel.INFO: "#36a64f",  # Green
    AlertLevel.WARNING: "#ff9800",  # Orange
    AlertLevel.CRITICAL: "#ff0000",  # Red
}


def _mask_webhook_url(url: str) -> str:
    """Mask a webhook URL for safe logging.

    Args:
        url: The full webhook URL.

    Returns:
        Masked URL like 'https://hooks.slack.com/services/T***/B***/***'.

    Examples:
        >>> _mask_webhook_url("https://hooks.slack.com/services/T123/B456/xyz")
        'https://hooks.slack.com/services/T***/B***/***'
    """
    if not url or "hooks.slack.com" not in url:
        return "***"

    # Extract base and mask the sensitive parts
    parts = url.split("/services/")
    if len(parts) == 2:
        tokens = parts[1].split("/")
        if len(tokens) >= 3:
            return f"https://hooks.slack.com/services/{tokens[0][:1]}***/{tokens[1][:1]}***/***"

    return "https://hooks.slack.com/services/***"


def _truncate(text: str, max_length: int) -> str:
    """Truncate text to max length with ellipsis.

    Args:
        text: Text to truncate.
        max_length: Maximum allowed length.

    Returns:
        Truncated text with '...' if exceeded.
    """
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


class SlackChannel(AsyncAlertChannel):
    """Async channel for sending alerts to Slack via webhooks.

    Uses Slack's incoming webhook API to post formatted messages.
    Supports customizable username, emoji, and timeout settings.

    Args:
        webhook_url: Slack incoming webhook URL.
        username: Bot username shown in Slack (default: 'kstlib-alerts').
        icon_emoji: Emoji for bot avatar (default: ':bell:').
        timeout: HTTP request timeout in seconds (default: 10.0).
        channel_name: Optional name override for this channel.

    Raises:
        AlertConfigurationError: If webhook_url is invalid.

    Examples:
        Basic usage::

            channel = SlackChannel(
                webhook_url="https://hooks.slack.com/services/T.../B.../xxx"
            )
            result = await channel.send(alert)

        Custom settings::

            channel = SlackChannel(
                webhook_url="https://hooks.slack.com/services/T.../B.../xxx",
                username="prod-alerts",
                icon_emoji=":fire:",
                timeout=5.0,
            )
    """

    def __init__(
        self,
        webhook_url: str,
        *,
        username: str = "kstlib-alerts",
        icon_emoji: str = ":bell:",
        timeout: float | None = None,
        channel_name: str | None = None,
        ssl_verify: bool | None = None,
        ssl_ca_bundle: str | None = None,
    ) -> None:
        """Initialize SlackChannel.

        Args:
            webhook_url: Slack incoming webhook URL.
            username: Bot username shown in Slack.
            icon_emoji: Emoji for bot avatar.
            timeout: HTTP request timeout in seconds. If None, uses config.
                Hard limits: [1.0, 120.0].
            channel_name: Optional name override for this channel.
            ssl_verify: Override SSL verification (True/False).
                If None, uses global config from kstlib.conf.yml.
            ssl_ca_bundle: Override CA bundle path.
                If None, uses global config from kstlib.conf.yml.

        Raises:
            AlertConfigurationError: If webhook_url is invalid.
        """
        if not webhook_url:
            raise AlertConfigurationError("Slack webhook URL is required")

        if not SLACK_WEBHOOK_PATTERN.match(webhook_url):
            raise AlertConfigurationError(
                "Invalid Slack webhook URL. Must match pattern: https://hooks.slack.com/services/T.../B.../..."
            )

        # Load config defaults and apply clamping
        limits = get_alerts_limits()
        resolved_timeout = clamp_with_limits(
            timeout if timeout is not None else limits.channel_timeout,
            HARD_MIN_CHANNEL_TIMEOUT,
            HARD_MAX_CHANNEL_TIMEOUT,
        )

        self._webhook_url = webhook_url
        self._username = username
        self._icon_emoji = icon_emoji
        self._timeout = resolved_timeout
        self._channel_name = channel_name or "slack"

        # Build SSL context (cascade: kwargs > global config > default)
        self._ssl_context = build_ssl_context(
            ssl_verify=ssl_verify,
            ssl_ca_bundle=ssl_ca_bundle,
        )

        log.debug("SlackChannel initialized: %s", _mask_webhook_url(webhook_url))

    @property
    def name(self) -> str:
        """Return the channel name."""
        return self._channel_name

    async def send(self, alert: AlertMessage) -> AlertResult:
        """Send an alert to Slack via webhook.

        Formats the alert as a Slack message with appropriate emoji
        and color based on the alert level.

        Args:
            alert: The alert message to send.

        Returns:
            AlertResult with delivery status.

        Raises:
            AlertDeliveryError: If the webhook request fails.
        """
        try:
            import httpx
        except ImportError as e:
            raise AlertConfigurationError("httpx is required for SlackChannel. Install with: pip install httpx") from e

        payload = self._build_payload(alert)

        log.debug(
            "Sending alert to Slack: level=%s, title=%r",
            alert.level.name,
            _truncate(alert.title, 50),
        )

        try:
            async with httpx.AsyncClient(timeout=self._timeout, verify=self._ssl_context) as client:
                response = await client.post(
                    self._webhook_url,
                    json=payload,
                )

                if response.status_code != 200:
                    error_msg = response.text or f"HTTP {response.status_code}"
                    log.warning(
                        "Slack webhook failed: status=%d, error=%s",
                        response.status_code,
                        error_msg,
                    )
                    raise AlertDeliveryError(
                        f"Slack webhook failed: {error_msg}",
                        channel=self.name,
                        retryable=response.status_code >= 500,
                    )

                log.debug("Alert sent to Slack successfully")
                return AlertResult(
                    channel=self.name,
                    success=True,
                )

        except httpx.TimeoutException as e:
            log.warning("Slack webhook timeout")
            raise AlertDeliveryError(
                f"Slack webhook timeout: {e}",
                channel=self.name,
                retryable=True,
            ) from e
        except httpx.RequestError as e:
            log.warning("Slack webhook request failed: %s", e)
            raise AlertDeliveryError(
                f"Slack webhook request failed: {e}",
                channel=self.name,
                retryable=True,
            ) from e

    def _build_payload(self, alert: AlertMessage) -> dict[str, Any]:
        """Build Slack webhook payload from alert.

        Args:
            alert: The alert message.

        Returns:
            Dict suitable for JSON serialization.
        """
        # Truncate to Slack limits (use formatted_title for timestamp support)
        title = _truncate(alert.formatted_title, MAX_TITLE_LENGTH)
        body = _truncate(alert.body, MAX_BODY_LENGTH)

        emoji = LEVEL_EMOJI.get(alert.level, ":bell:")
        color = LEVEL_COLOR.get(alert.level, "#808080")

        return {
            "username": self._username,
            "icon_emoji": self._icon_emoji,
            "attachments": [
                {
                    "color": color,
                    "title": f"{emoji} {title}",
                    "text": body,
                    "footer": f"Alert Level: {alert.level.name}",
                }
            ],
        }

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any],
        credential_resolver: CredentialResolver | None = None,
    ) -> SlackChannel:
        """Create SlackChannel from configuration dict.

        Config format::

            slack_ops:
              type: slack
              credentials: slack_webhook  # reference to credentials section
              username: "kstlib-alerts"
              icon_emoji: ":bell:"
              timeout: 10.0

        The webhook URL is resolved via credential_resolver using the
        'credentials' key, supporting env, file, and SOPS sources.

        Args:
            config: Channel configuration dict.
            credential_resolver: Resolver for credential references.

        Returns:
            Configured SlackChannel instance.

        Raises:
            AlertConfigurationError: If configuration is invalid.
        """
        # Get webhook URL from credentials
        cred_name = config.get("credentials")
        webhook_url = config.get("webhook_url")

        if cred_name and credential_resolver:
            try:
                record = credential_resolver.resolve(cred_name)
                webhook_url = record.value
            except Exception as e:
                raise AlertConfigurationError(f"Failed to resolve Slack credentials '{cred_name}': {e}") from e
        elif not webhook_url:
            raise AlertConfigurationError("SlackChannel requires 'credentials' or 'webhook_url' in config")

        # Parse timeout: None means use config default
        timeout_raw = config.get("timeout")
        timeout = float(timeout_raw) if timeout_raw is not None else None

        # Parse SSL settings: None means use global config
        ssl_verify_raw = config.get("ssl_verify")
        ssl_verify = bool(ssl_verify_raw) if ssl_verify_raw is not None else None
        ssl_ca_bundle = config.get("ssl_ca_bundle")

        return cls(
            webhook_url=webhook_url,
            username=config.get("username", "kstlib-alerts"),
            icon_emoji=config.get("icon_emoji", ":bell:"),
            timeout=timeout,
            channel_name=config.get("name"),
            ssl_verify=ssl_verify,
            ssl_ca_bundle=ssl_ca_bundle,
        )

    def __repr__(self) -> str:
        """Return string representation without secrets."""
        return f"SlackChannel(username={self._username!r}, name={self._channel_name!r})"
