"""Alert manager for orchestrating multi-channel delivery.

The AlertManager coordinates sending alerts to multiple channels with
per-channel level filtering and optional throttling.

Examples:
    Basic setup::

        from kstlib.alerts import AlertManager, AlertLevel
        from kstlib.alerts.channels import SlackChannel, EmailChannel

        manager = AlertManager()
        manager.add_channel(slack_channel, min_level=AlertLevel.WARNING)
        manager.add_channel(email_channel, min_level=AlertLevel.CRITICAL)

        results = await manager.send(alert)

    With throttling::

        from kstlib.alerts.throttle import AlertThrottle

        throttle = AlertThrottle(rate=10, per=60.0)
        manager.add_channel(slack_channel, throttle=throttle)

    Fluent API::

        manager = (
            AlertManager()
            .add_channel(slack_channel, min_level=AlertLevel.INFO)
            .add_channel(email_channel, min_level=AlertLevel.CRITICAL)
        )
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from kstlib.alerts.channels.base import AlertChannel, AsyncAlertChannel, AsyncChannelWrapper
from kstlib.alerts.exceptions import AlertConfigurationError, AlertThrottledError
from kstlib.alerts.models import AlertLevel, AlertResult

if TYPE_CHECKING:
    from collections.abc import Mapping

    from typing_extensions import Self

    from kstlib.alerts.models import AlertMessage
    from kstlib.alerts.throttle import AlertThrottle
    from kstlib.mail.transport import AsyncMailTransport, MailTransport
    from kstlib.rapi.credentials import CredentialResolver

__all__ = ["AlertManager"]

log = logging.getLogger(__name__)


@dataclass
class _ChannelEntry:
    """Internal entry for a registered channel."""

    channel: AsyncAlertChannel
    min_level: AlertLevel = AlertLevel.INFO
    throttle: AlertThrottle | None = None
    key: str | None = None  # Config key (e.g., "hb")
    alias: str | None = None  # Optional alias (e.g., "heartbeat")


@dataclass
class AlertManagerStats:
    """Statistics for alert manager monitoring.

    Attributes:
        total_sent: Total alerts successfully sent.
        total_failed: Total alerts that failed delivery.
        total_throttled: Total alerts dropped due to throttling.
        by_channel: Per-channel statistics.
    """

    total_sent: int = 0
    total_failed: int = 0
    total_throttled: int = 0
    by_channel: dict[str, dict[str, int]] = field(default_factory=dict)

    def record_sent(self, channel: str) -> None:
        """Record a successful send."""
        self.total_sent += 1
        self._ensure_channel(channel)
        self.by_channel[channel]["sent"] += 1

    def record_failed(self, channel: str) -> None:
        """Record a failed send."""
        self.total_failed += 1
        self._ensure_channel(channel)
        self.by_channel[channel]["failed"] += 1

    def record_throttled(self, channel: str) -> None:
        """Record a throttled alert."""
        self.total_throttled += 1
        self._ensure_channel(channel)
        self.by_channel[channel]["throttled"] += 1

    def _ensure_channel(self, channel: str) -> None:
        """Ensure channel stats dict exists."""
        if channel not in self.by_channel:
            self.by_channel[channel] = {"sent": 0, "failed": 0, "throttled": 0}


class AlertManager:
    """Orchestrates alert delivery to multiple channels.

    Manages a collection of alert channels with per-channel level
    filtering and optional throttling. Alerts are sent concurrently
    to all matching channels.

    Examples:
        Basic usage::

            manager = AlertManager()
            manager.add_channel(slack_channel)
            manager.add_channel(email_channel, min_level=AlertLevel.CRITICAL)

            alert = AlertMessage(
                title="Service Down",
                body="API server not responding",
                level=AlertLevel.CRITICAL,
            )

            results = await manager.send(alert)
            for result in results:
                if result.success:
                    print(f"{result.channel}: OK")

        Fluent API::

            manager = (
                AlertManager()
                .add_channel(slack, min_level=AlertLevel.WARNING)
                .add_channel(email, min_level=AlertLevel.CRITICAL)
            )

        From config::

            manager = AlertManager.from_config(
                config=config["alerts"],
                credential_resolver=resolver,
            )
    """

    def __init__(self) -> None:
        """Initialize AlertManager with no channels."""
        self._channels: list[_ChannelEntry] = []
        self._stats = AlertManagerStats()

    @property
    def stats(self) -> AlertManagerStats:
        """Return statistics for this manager."""
        return self._stats

    @property
    def channel_count(self) -> int:
        """Return number of registered channels."""
        return len(self._channels)

    def add_channel(
        self,
        channel: AlertChannel | AsyncAlertChannel,
        *,
        min_level: AlertLevel = AlertLevel.INFO,
        throttle: AlertThrottle | None = None,
        key: str | None = None,
        alias: str | None = None,
    ) -> Self:
        """Add a channel to the manager.

        Args:
            channel: The channel to add (sync or async).
            min_level: Minimum alert level for this channel.
            throttle: Optional throttle for rate limiting.
            key: Config key for targeting (e.g., "hb").
            alias: Human-readable alias for targeting (e.g., "heartbeat").

        Returns:
            Self for fluent chaining.

        Examples:
            >>> manager = AlertManager()
            >>> manager.add_channel(slack_channel)  # doctest: +SKIP
            AlertManager(channels=1)
            >>> manager.add_channel(email_channel, min_level=AlertLevel.CRITICAL)  # doctest: +SKIP
            AlertManager(channels=2)
        """
        # Wrap sync channels for async usage
        if isinstance(channel, AlertChannel):
            async_channel: AsyncAlertChannel = AsyncChannelWrapper(channel)
        else:
            async_channel = channel

        entry = _ChannelEntry(
            channel=async_channel,
            min_level=min_level,
            throttle=throttle,
            key=key,
            alias=alias,
        )
        self._channels.append(entry)

        log.debug(
            "Added channel: name=%s, min_level=%s, throttle=%s",
            async_channel.name,
            min_level.name,
            throttle is not None,
        )

        return self

    async def send(
        self,
        alert: AlertMessage | list[AlertMessage],
        *,
        channel: str | None = None,
    ) -> list[AlertResult]:
        """Send one or more alerts to matching channels.

        Delivers alerts concurrently to channels where the alert level
        meets the channel's minimum level. Optionally target a specific
        channel by key or alias.

        Args:
            alert: Single alert or list of alerts to send.
            channel: Optional channel key or alias to target. If None,
                broadcasts to all matching channels based on level.

        Returns:
            Flat list of AlertResult for all alerts and channels.

        Examples:
            Send single alert (broadcast)::

                >>> results = await manager.send(alert)  # doctest: +SKIP

            Send single alert to specific channel::

                >>> results = await manager.send(alert, channel="hb")  # doctest: +SKIP

            Send multiple alerts to same channel::

                >>> alerts = [alert1, alert2, alert3]  # doctest: +SKIP
                >>> results = await manager.send(alerts, channel="watchdog")  # doctest: +SKIP
        """
        if not self._channels:
            log.warning("No channels configured, alert not sent")
            return []

        # Normalize to list
        alerts = [alert] if not isinstance(alert, list) else alert

        if not alerts:
            return []

        # Get target entries (if channel specified)
        target_entries: list[_ChannelEntry] | None = None
        if channel is not None:
            target_entries = self._find_channel(channel)
            if not target_entries:
                log.warning("Channel '%s' not found", channel)
                return []

        # Send all alerts
        all_results: list[AlertResult] = []
        for single_alert in alerts:
            results = await self._send_alert(single_alert, target_entries)
            all_results.extend(results)

        return all_results

    async def _send_alert(
        self,
        alert: AlertMessage,
        target_entries: list[_ChannelEntry] | None,
    ) -> list[AlertResult]:
        """Send a single alert to matching channels.

        Args:
            alert: The alert to send.
            target_entries: Specific entries to target, or None for broadcast.

        Returns:
            List of results for this alert.
        """
        # Determine matching entries
        if target_entries is not None:
            matching_entries = target_entries
        else:
            # Filter channels by level (broadcast mode)
            matching_entries = [entry for entry in self._channels if alert.level >= entry.min_level]

        if not matching_entries:
            log.debug(
                "No channels match alert level %s",
                alert.level.name,
            )
            return []

        log.debug(
            "Sending alert to %d channels: level=%s, title=%r",
            len(matching_entries),
            alert.level.name,
            alert.title[:50],
        )

        # Send to all matching channels concurrently
        tasks = [self._send_to_entry(entry, alert) for entry in matching_entries]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        return list(results)

    def _find_channel(self, identifier: str) -> list[_ChannelEntry]:
        """Find channel entry by key, alias, or channel name.

        Args:
            identifier: Channel key, alias, or name.

        Returns:
            List with matching entry, or empty list if not found.
        """
        for entry in self._channels:
            # Match by key (e.g., "hb")
            if entry.key and entry.key == identifier:
                return [entry]
            # Match by alias (e.g., "heartbeat")
            if entry.alias and entry.alias == identifier:
                return [entry]
            # Match by channel name (fallback)
            if entry.channel.name == identifier:
                return [entry]
        return []

    async def _send_to_entry(
        self,
        entry: _ChannelEntry,
        alert: AlertMessage,
    ) -> AlertResult:
        """Send alert to a single channel entry.

        Args:
            entry: The channel entry with config.
            alert: The alert to send.

        Returns:
            AlertResult with delivery status.
        """
        channel_name = entry.channel.name

        # Check throttle if configured
        if entry.throttle is not None and not entry.throttle.try_acquire():
            self._stats.record_throttled(channel_name)
            log.debug("Alert throttled for channel: %s", channel_name)
            return AlertResult(
                channel=channel_name,
                success=False,
                error="Rate limit exceeded",
            )

        try:
            result = await entry.channel.send(alert)
            if result.success:
                self._stats.record_sent(channel_name)
            else:
                self._stats.record_failed(channel_name)
            return result

        except AlertThrottledError as e:
            self._stats.record_throttled(channel_name)
            return AlertResult(
                channel=channel_name,
                success=False,
                error=f"Throttled: retry after {e.retry_after}s",
            )

        except Exception as e:
            self._stats.record_failed(channel_name)
            log.warning(
                "Channel %s failed: %s",
                channel_name,
                e,
            )
            return AlertResult(
                channel=channel_name,
                success=False,
                error=str(e),
            )

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any],
        credential_resolver: CredentialResolver | None = None,
    ) -> AlertManager:
        """Create AlertManager from configuration dict.

        Config format::

            alerts:
              throttle:
                rate: 10
                per: 60

              channels:
                slack_ops:
                  type: slack
                  credentials: slack_webhook
                  username: "kstlib-alerts"
                  min_level: warning

                email_critical:
                  type: email
                  transport:
                    type: smtp
                    host: smtp.example.com
                  sender: "alerts@example.com"
                  recipients: ["oncall@example.com"]
                  min_level: critical

        Args:
            config: Alerts configuration dict.
            credential_resolver: Resolver for credential references.

        Returns:
            Configured AlertManager instance.

        Raises:
            AlertConfigurationError: If configuration is invalid.
        """
        from kstlib.alerts.channels import SlackChannel
        from kstlib.alerts.throttle import AlertThrottle

        manager = cls()

        # Parse global throttle config
        global_throttle = None
        throttle_config = config.get("throttle")
        if throttle_config:
            global_throttle = AlertThrottle(
                rate=float(throttle_config.get("rate", 10)),
                per=float(throttle_config.get("per", 60)),
            )

        # Parse channels
        channels_config = config.get("channels", {})
        if not channels_config:
            log.warning("No channels configured in alerts config")
            return manager

        for config_key, channel_config in channels_config.items():
            channel_type = channel_config.get("type", "").lower()

            # Extract alias from config (optional "name" field)
            # If not specified, alias defaults to None (use key for targeting)
            channel_alias = channel_config.get("name")

            # Parse min_level
            min_level_str = channel_config.get("min_level", "info").lower()
            min_level = _parse_level(min_level_str)

            # Parse per-channel throttle (or use global)
            channel_throttle = global_throttle
            if "throttle" in channel_config:
                tc = channel_config["throttle"]
                channel_throttle = AlertThrottle(
                    rate=float(tc.get("rate", 10)),
                    per=float(tc.get("per", 60)),
                )

            # Determine display name: use alias if provided, else config key
            display_name = channel_alias if channel_alias else config_key

            # Create channel based on type
            try:
                if channel_type == "slack":
                    channel: AlertChannel | AsyncAlertChannel = SlackChannel.from_config(
                        {**channel_config, "name": display_name},
                        credential_resolver,
                    )
                elif channel_type == "email":
                    channel = _create_email_channel(
                        channel_config,
                        display_name,
                        credential_resolver,
                    )
                else:
                    raise AlertConfigurationError(f"Unknown channel type '{channel_type}' for channel '{config_key}'")

                manager.add_channel(
                    channel,
                    min_level=min_level,
                    throttle=channel_throttle,
                    key=config_key,
                    alias=channel_alias,
                )

            except Exception as e:
                if isinstance(e, AlertConfigurationError):
                    raise
                raise AlertConfigurationError(f"Failed to configure channel '{config_key}': {e}") from e

        return manager

    def __repr__(self) -> str:
        """Return string representation."""
        return f"AlertManager(channels={len(self._channels)})"


def _parse_level(level_str: str) -> AlertLevel:
    """Parse alert level from string.

    Args:
        level_str: Level name (case-insensitive).

    Returns:
        AlertLevel enum value.

    Raises:
        AlertConfigurationError: If level is invalid.
    """
    level_map = {
        "info": AlertLevel.INFO,
        "warning": AlertLevel.WARNING,
        "critical": AlertLevel.CRITICAL,
    }
    level = level_map.get(level_str.lower())
    if level is None:
        raise AlertConfigurationError(f"Invalid alert level '{level_str}'. Valid levels: {', '.join(level_map.keys())}")
    return level


def _create_email_transport(
    transport_config: Mapping[str, Any],
    name: str,
    credential_resolver: CredentialResolver | None,
) -> MailTransport | AsyncMailTransport:
    """Create a mail transport from configuration.

    Args:
        transport_config: Transport configuration dict.
        name: Channel name for error messages.
        credential_resolver: Credential resolver.

    Returns:
        Configured mail transport.

    Raises:
        AlertConfigurationError: If configuration is invalid.
    """
    transport_type = transport_config.get("type", "smtp").lower()

    if transport_type == "smtp":
        from kstlib.mail.transports import SMTPCredentials, SMTPSecurity, SMTPTransport

        credentials = None
        username = transport_config.get("username")
        if username:
            credentials = SMTPCredentials(
                username=username,
                password=transport_config.get("password"),
            )

        security = SMTPSecurity(
            use_starttls=transport_config.get("use_tls", True),
        )

        return SMTPTransport(
            host=transport_config.get("host", "localhost"),
            port=int(transport_config.get("port", 587)),
            credentials=credentials,
            security=security,
        )

    if transport_type == "gmail":
        # Gmail requires OAuth2 Token from kstlib.auth module
        # Use GmailTransport directly with a Token object in code
        raise AlertConfigurationError(
            f"Gmail transport for '{name}' requires programmatic configuration. "
            "Use GmailTransport(token=...) directly instead of config."
        )

    if transport_type == "resend":
        from kstlib.mail.transports import ResendTransport

        api_key = transport_config.get("api_key")
        if not api_key and credential_resolver:
            cred_name = transport_config.get("credentials")
            if cred_name:
                record = credential_resolver.resolve(cred_name)
                api_key = record.value

        if not api_key:
            raise AlertConfigurationError(f"Resend transport for '{name}' requires 'api_key' or 'credentials'")

        return ResendTransport(api_key=api_key)

    raise AlertConfigurationError(f"Unknown transport type '{transport_type}' for email channel '{name}'")


def _create_email_channel(
    config: Mapping[str, Any],
    name: str,
    credential_resolver: CredentialResolver | None,
) -> AlertChannel | AsyncAlertChannel:
    """Create an EmailChannel from config.

    Args:
        config: Channel configuration.
        name: Channel name.
        credential_resolver: Credential resolver.

    Returns:
        Configured EmailChannel.

    Raises:
        AlertConfigurationError: If configuration is invalid.
    """
    from kstlib.alerts.channels import EmailChannel

    transport_config = config.get("transport")
    if not transport_config:
        raise AlertConfigurationError(f"Email channel '{name}' requires 'transport' configuration")

    try:
        transport = _create_email_transport(transport_config, name, credential_resolver)
    except ImportError as e:
        transport_type = transport_config.get("type", "smtp")
        raise AlertConfigurationError(f"Missing dependency for transport '{transport_type}': {e}") from e

    sender = config.get("sender")
    if not sender:
        raise AlertConfigurationError(f"Email channel '{name}' requires 'sender'")

    recipients = config.get("recipients", [])
    if not recipients:
        raise AlertConfigurationError(f"Email channel '{name}' requires 'recipients'")

    return EmailChannel(
        transport=transport,
        sender=sender,
        recipients=recipients,
        subject_prefix=config.get("subject_prefix", "[ALERT]"),
        channel_name=name,
    )
