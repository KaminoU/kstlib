"""Tests for kstlib.alerts.manager module."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from kstlib.alerts.channels.base import AlertChannel, AsyncAlertChannel
from kstlib.alerts.exceptions import AlertConfigurationError, AlertThrottledError
from kstlib.alerts.manager import (
    AlertManager,
    _create_email_channel,
    _create_email_transport,
    _parse_level,
)
from kstlib.alerts.models import AlertLevel, AlertMessage, AlertResult
from kstlib.alerts.throttle import AlertThrottle


class MockAsyncChannel(AsyncAlertChannel):
    """Mock async channel for testing."""

    def __init__(
        self,
        name: str = "mock",
        *,
        should_fail: bool = False,
        fail_message: str = "Mock failure",
    ) -> None:
        """Initialize mock channel."""
        self._name = name
        self._should_fail = should_fail
        self._fail_message = fail_message
        self.sent_alerts: list[AlertMessage] = []

    @property
    def name(self) -> str:
        """Return channel name."""
        return self._name

    async def send(self, alert: AlertMessage) -> AlertResult:
        """Store alert and return result."""
        if self._should_fail:
            return AlertResult(
                channel=self._name,
                success=False,
                error=self._fail_message,
            )
        self.sent_alerts.append(alert)
        return AlertResult(channel=self._name, success=True)


class MockSyncChannel(AlertChannel):
    """Mock sync channel for testing."""

    def __init__(self, name: str = "sync_mock") -> None:
        """Initialize mock channel."""
        self._name = name
        self.sent_alerts: list[AlertMessage] = []

    @property
    def name(self) -> str:
        """Return channel name."""
        return self._name

    def send(self, alert: AlertMessage) -> AlertResult:
        """Store alert and return result."""
        self.sent_alerts.append(alert)
        return AlertResult(channel=self._name, success=True)


class TestAlertManagerInit:
    """Tests for AlertManager initialization."""

    def test_empty_init(self) -> None:
        """Should initialize with no channels."""
        manager = AlertManager()
        assert manager.channel_count == 0

    def test_repr(self) -> None:
        """repr should show channel count."""
        manager = AlertManager()
        assert "channels=0" in repr(manager)


class TestAlertManagerAddChannel:
    """Tests for AlertManager.add_channel()."""

    def test_add_async_channel(self) -> None:
        """Should add async channel."""
        manager = AlertManager()
        channel = MockAsyncChannel()

        manager.add_channel(channel)

        assert manager.channel_count == 1

    def test_add_sync_channel(self) -> None:
        """Should wrap and add sync channel."""
        manager = AlertManager()
        channel = MockSyncChannel()

        manager.add_channel(channel)

        assert manager.channel_count == 1

    def test_add_multiple_channels(self) -> None:
        """Should add multiple channels."""
        manager = AlertManager()
        manager.add_channel(MockAsyncChannel("ch1"))
        manager.add_channel(MockAsyncChannel("ch2"))
        manager.add_channel(MockAsyncChannel("ch3"))

        assert manager.channel_count == 3

    def test_fluent_api(self) -> None:
        """add_channel should return self for chaining."""
        manager = AlertManager()
        result = manager.add_channel(MockAsyncChannel())

        assert result is manager

    def test_fluent_chain(self) -> None:
        """Should support fluent chaining."""
        manager = AlertManager().add_channel(MockAsyncChannel("ch1")).add_channel(MockAsyncChannel("ch2"))

        assert manager.channel_count == 2

    def test_with_min_level(self) -> None:
        """Should accept min_level parameter."""
        manager = AlertManager()
        manager.add_channel(
            MockAsyncChannel(),
            min_level=AlertLevel.CRITICAL,
        )

        assert manager.channel_count == 1

    def test_with_throttle(self) -> None:
        """Should accept throttle parameter."""
        manager = AlertManager()
        throttle = AlertThrottle(rate=10, per=60.0)
        manager.add_channel(
            MockAsyncChannel(),
            throttle=throttle,
        )

        assert manager.channel_count == 1


class TestAlertManagerSend:
    """Tests for AlertManager.send()."""

    @pytest.mark.asyncio
    async def test_send_to_single_channel(self) -> None:
        """Should send alert to single channel."""
        channel = MockAsyncChannel()
        manager = AlertManager().add_channel(channel)
        alert = AlertMessage(title="Test", body="Body")

        results = await manager.send(alert)

        assert len(results) == 1
        assert results[0].success is True
        assert len(channel.sent_alerts) == 1

    @pytest.mark.asyncio
    async def test_send_to_multiple_channels(self) -> None:
        """Should send alert to all matching channels."""
        ch1 = MockAsyncChannel("ch1")
        ch2 = MockAsyncChannel("ch2")
        manager = AlertManager().add_channel(ch1).add_channel(ch2)
        alert = AlertMessage(title="Test", body="Body")

        results = await manager.send(alert)

        assert len(results) == 2
        assert all(r.success for r in results)
        assert len(ch1.sent_alerts) == 1
        assert len(ch2.sent_alerts) == 1

    @pytest.mark.asyncio
    async def test_send_no_channels(self) -> None:
        """Should return empty list when no channels configured."""
        manager = AlertManager()
        alert = AlertMessage(title="Test", body="Body")

        results = await manager.send(alert)

        assert results == []

    @pytest.mark.asyncio
    async def test_level_filtering_info(self) -> None:
        """Should filter channels by min_level (INFO alert)."""
        info_channel = MockAsyncChannel("info")
        warning_channel = MockAsyncChannel("warning")

        manager = (
            AlertManager()
            .add_channel(info_channel, min_level=AlertLevel.INFO)
            .add_channel(warning_channel, min_level=AlertLevel.WARNING)
        )

        alert = AlertMessage(title="Test", body="Body", level=AlertLevel.INFO)
        results = await manager.send(alert)

        # Only info channel should receive (INFO < WARNING)
        assert len(results) == 1
        assert results[0].channel == "info"

    @pytest.mark.asyncio
    async def test_level_filtering_warning(self) -> None:
        """Should filter channels by min_level (WARNING alert)."""
        info_channel = MockAsyncChannel("info")
        warning_channel = MockAsyncChannel("warning")
        critical_channel = MockAsyncChannel("critical")

        manager = (
            AlertManager()
            .add_channel(info_channel, min_level=AlertLevel.INFO)
            .add_channel(warning_channel, min_level=AlertLevel.WARNING)
            .add_channel(critical_channel, min_level=AlertLevel.CRITICAL)
        )

        alert = AlertMessage(title="Test", body="Body", level=AlertLevel.WARNING)
        results = await manager.send(alert)

        # INFO and WARNING channels should receive
        assert len(results) == 2
        channels = {r.channel for r in results}
        assert "info" in channels
        assert "warning" in channels
        assert "critical" not in channels

    @pytest.mark.asyncio
    async def test_level_filtering_critical(self) -> None:
        """Should filter channels by min_level (CRITICAL alert)."""
        info_channel = MockAsyncChannel("info")
        critical_channel = MockAsyncChannel("critical")

        manager = (
            AlertManager()
            .add_channel(info_channel, min_level=AlertLevel.INFO)
            .add_channel(critical_channel, min_level=AlertLevel.CRITICAL)
        )

        alert = AlertMessage(title="Test", body="Body", level=AlertLevel.CRITICAL)
        results = await manager.send(alert)

        # Both should receive
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_send_partial_failure(self) -> None:
        """Should continue when one channel fails."""
        success_channel = MockAsyncChannel("success")
        fail_channel = MockAsyncChannel("fail", should_fail=True)

        manager = AlertManager().add_channel(success_channel).add_channel(fail_channel)
        alert = AlertMessage(title="Test", body="Body")

        results = await manager.send(alert)

        assert len(results) == 2
        success_results = [r for r in results if r.success]
        fail_results = [r for r in results if not r.success]
        assert len(success_results) == 1
        assert len(fail_results) == 1

    @pytest.mark.asyncio
    async def test_throttle_blocks(self) -> None:
        """Should respect throttle on channel."""
        channel = MockAsyncChannel()
        throttle = AlertThrottle(rate=1, per=60.0)
        manager = AlertManager().add_channel(channel, throttle=throttle)

        alert = AlertMessage(title="Test", body="Body")

        # First send should succeed
        results = await manager.send(alert)
        assert results[0].success is True

        # Second send should be throttled
        results = await manager.send(alert)
        assert results[0].success is False
        assert results[0].error is not None
        assert "rate limit" in results[0].error.lower()


class TestAlertManagerStats:
    """Tests for AlertManager.stats."""

    @pytest.mark.asyncio
    async def test_stats_sent(self) -> None:
        """Should track successful sends."""
        channel = MockAsyncChannel()
        manager = AlertManager().add_channel(channel)
        alert = AlertMessage(title="Test", body="Body")

        await manager.send(alert)
        await manager.send(alert)

        assert manager.stats.total_sent == 2

    @pytest.mark.asyncio
    async def test_stats_failed(self) -> None:
        """Should track failed sends."""
        channel = MockAsyncChannel(should_fail=True)
        manager = AlertManager().add_channel(channel)
        alert = AlertMessage(title="Test", body="Body")

        await manager.send(alert)

        assert manager.stats.total_failed == 1

    @pytest.mark.asyncio
    async def test_stats_throttled(self) -> None:
        """Should track throttled alerts."""
        channel = MockAsyncChannel()
        throttle = AlertThrottle(rate=1, per=60.0)
        manager = AlertManager().add_channel(channel, throttle=throttle)
        alert = AlertMessage(title="Test", body="Body")

        await manager.send(alert)
        await manager.send(alert)  # Throttled

        assert manager.stats.total_throttled == 1

    @pytest.mark.asyncio
    async def test_stats_by_channel(self) -> None:
        """Should track per-channel stats."""
        ch1 = MockAsyncChannel("ch1")
        ch2 = MockAsyncChannel("ch2", should_fail=True)
        manager = AlertManager().add_channel(ch1).add_channel(ch2)
        alert = AlertMessage(title="Test", body="Body")

        await manager.send(alert)

        assert manager.stats.by_channel["ch1"]["sent"] == 1
        assert manager.stats.by_channel["ch2"]["failed"] == 1


class TestParseLevelHelper:
    """Tests for _parse_level helper function."""

    def test_parse_info(self) -> None:
        """Should parse 'info' level."""
        assert _parse_level("info") == AlertLevel.INFO

    def test_parse_warning(self) -> None:
        """Should parse 'warning' level."""
        assert _parse_level("warning") == AlertLevel.WARNING

    def test_parse_critical(self) -> None:
        """Should parse 'critical' level."""
        assert _parse_level("critical") == AlertLevel.CRITICAL

    def test_parse_case_insensitive(self) -> None:
        """Should parse levels case-insensitively."""
        assert _parse_level("INFO") == AlertLevel.INFO
        assert _parse_level("Warning") == AlertLevel.WARNING
        assert _parse_level("CRITICAL") == AlertLevel.CRITICAL

    def test_parse_invalid(self) -> None:
        """Should raise error for invalid level."""
        with pytest.raises(AlertConfigurationError):
            _parse_level("invalid")


class TestAlertManagerFromConfig:
    """Tests for AlertManager.from_config()."""

    def test_empty_config(self) -> None:
        """Should create manager with empty channels config."""
        config: dict[str, Any] = {"channels": {}}
        manager = AlertManager.from_config(config)
        assert manager.channel_count == 0

    def test_no_channels_key(self) -> None:
        """Should create manager when channels key missing."""
        config: dict[str, Any] = {}
        manager = AlertManager.from_config(config)
        assert manager.channel_count == 0

    def test_unknown_channel_type(self) -> None:
        """Should raise error for unknown channel type."""
        config = {
            "channels": {
                "unknown": {"type": "unknown"},
            },
        }
        with pytest.raises(AlertConfigurationError):
            AlertManager.from_config(config)

    def test_global_throttle(self) -> None:
        """Should apply global throttle to all channels."""
        config = {
            "throttle": {"rate": 5, "per": 30},
            "channels": {
                "slack": {
                    "type": "slack",
                    "webhook_url": "https://hooks.slack.com/services/T123/B456/xyz",
                },
            },
        }
        manager = AlertManager.from_config(config)
        assert manager.channel_count == 1

    def test_per_channel_throttle(self) -> None:
        """Should support per-channel throttle override."""
        config = {
            "throttle": {"rate": 10, "per": 60},
            "channels": {
                "slack": {
                    "type": "slack",
                    "webhook_url": "https://hooks.slack.com/services/T123/B456/xyz",
                    "throttle": {"rate": 5, "per": 30},
                },
            },
        }
        manager = AlertManager.from_config(config)
        assert manager.channel_count == 1

    def test_min_level_from_config(self) -> None:
        """Should parse min_level from config."""
        config = {
            "channels": {
                "slack": {
                    "type": "slack",
                    "webhook_url": "https://hooks.slack.com/services/T123/B456/xyz",
                    "min_level": "warning",
                },
            },
        }
        manager = AlertManager.from_config(config)
        assert manager.channel_count == 1

    def test_slack_channel_from_config(self) -> None:
        """Should create Slack channel from config."""
        config = {
            "channels": {
                "slack_ops": {
                    "type": "slack",
                    "webhook_url": "https://hooks.slack.com/services/T123/B456/xyz",
                    "username": "my-alerts",
                },
            },
        }
        manager = AlertManager.from_config(config)
        assert manager.channel_count == 1

    def test_slack_with_credentials(self) -> None:
        """Should create Slack channel with credential resolver."""
        config = {
            "channels": {
                "slack_ops": {
                    "type": "slack",
                    "credentials": "slack_webhook",
                },
            },
        }
        mock_resolver = MagicMock()
        mock_resolver.resolve.return_value = MagicMock(value="https://hooks.slack.com/services/T123/B456/xyz")

        manager = AlertManager.from_config(config, mock_resolver)
        assert manager.channel_count == 1

    def test_email_channel_smtp(self) -> None:
        """Should create email channel with SMTP transport."""
        config = {
            "channels": {
                "email_ops": {
                    "type": "email",
                    "transport": {
                        "type": "smtp",
                        "host": "smtp.example.com",
                        "port": 587,
                        "username": "user@example.com",
                        "password": "secret",
                    },
                    "sender": "alerts@example.com",
                    "recipients": ["oncall@example.com"],
                },
            },
        }
        manager = AlertManager.from_config(config)
        assert manager.channel_count == 1

    def test_email_channel_resend(self) -> None:
        """Should create email channel with Resend transport."""
        config = {
            "channels": {
                "email_ops": {
                    "type": "email",
                    "transport": {
                        "type": "resend",
                        "api_key": "re_123456",
                    },
                    "sender": "alerts@example.com",
                    "recipients": ["oncall@example.com"],
                },
            },
        }
        manager = AlertManager.from_config(config)
        assert manager.channel_count == 1

    def test_email_channel_resend_with_credentials(self) -> None:
        """Should create email channel with Resend transport using credential resolver."""
        config = {
            "channels": {
                "email_ops": {
                    "type": "email",
                    "transport": {
                        "type": "resend",
                        "credentials": "resend_api_key",
                    },
                    "sender": "alerts@example.com",
                    "recipients": ["oncall@example.com"],
                },
            },
        }
        mock_resolver = MagicMock()
        mock_resolver.resolve.return_value = MagicMock(value="re_123456")

        manager = AlertManager.from_config(config, mock_resolver)
        assert manager.channel_count == 1

    def test_email_channel_missing_transport(self) -> None:
        """Should raise error when email channel missing transport."""
        config = {
            "channels": {
                "email_ops": {
                    "type": "email",
                    "sender": "alerts@example.com",
                    "recipients": ["oncall@example.com"],
                },
            },
        }
        with pytest.raises(AlertConfigurationError, match="requires 'transport'"):
            AlertManager.from_config(config)

    def test_email_channel_missing_sender(self) -> None:
        """Should raise error when email channel missing sender."""
        config = {
            "channels": {
                "email_ops": {
                    "type": "email",
                    "transport": {"type": "smtp", "host": "localhost"},
                    "recipients": ["oncall@example.com"],
                },
            },
        }
        with pytest.raises(AlertConfigurationError, match="requires 'sender'"):
            AlertManager.from_config(config)

    def test_email_channel_missing_recipients(self) -> None:
        """Should raise error when email channel missing recipients."""
        config = {
            "channels": {
                "email_ops": {
                    "type": "email",
                    "transport": {"type": "smtp", "host": "localhost"},
                    "sender": "alerts@example.com",
                },
            },
        }
        with pytest.raises(AlertConfigurationError, match="requires 'recipients'"):
            AlertManager.from_config(config)

    def test_email_gmail_not_supported_in_config(self) -> None:
        """Should raise error for Gmail transport in config."""
        config = {
            "channels": {
                "email_ops": {
                    "type": "email",
                    "transport": {"type": "gmail"},
                    "sender": "alerts@example.com",
                    "recipients": ["oncall@example.com"],
                },
            },
        }
        with pytest.raises(AlertConfigurationError, match="requires programmatic"):
            AlertManager.from_config(config)

    def test_email_unknown_transport_type(self) -> None:
        """Should raise error for unknown transport type."""
        config = {
            "channels": {
                "email_ops": {
                    "type": "email",
                    "transport": {"type": "unknown"},
                    "sender": "alerts@example.com",
                    "recipients": ["oncall@example.com"],
                },
            },
        }
        with pytest.raises(AlertConfigurationError, match="Unknown transport type"):
            AlertManager.from_config(config)

    def test_email_resend_missing_api_key(self) -> None:
        """Should raise error when Resend transport missing API key."""
        config = {
            "channels": {
                "email_ops": {
                    "type": "email",
                    "transport": {"type": "resend"},
                    "sender": "alerts@example.com",
                    "recipients": ["oncall@example.com"],
                },
            },
        }
        with pytest.raises(AlertConfigurationError, match="requires 'api_key'"):
            AlertManager.from_config(config)

    def test_channel_with_alias(self) -> None:
        """Should create channel with alias from config 'name' field."""
        config = {
            "channels": {
                "hb": {
                    "type": "slack",
                    "webhook_url": "https://hooks.slack.com/services/T123/B456/xyz",
                    "name": "heartbeat",
                },
            },
        }
        manager = AlertManager.from_config(config)
        assert manager.channel_count == 1


class TestAlertManagerChannelTargeting:
    """Tests for AlertManager channel targeting."""

    @pytest.mark.asyncio
    async def test_send_to_specific_channel_by_key(self) -> None:
        """Should send to specific channel by key."""
        ch1 = MockAsyncChannel("ch1")
        ch2 = MockAsyncChannel("ch2")
        manager = AlertManager().add_channel(ch1, key="primary").add_channel(ch2, key="secondary")
        alert = AlertMessage(title="Test", body="Body")

        results = await manager.send(alert, channel="primary")

        assert len(results) == 1
        assert results[0].channel == "ch1"
        assert len(ch1.sent_alerts) == 1
        assert len(ch2.sent_alerts) == 0

    @pytest.mark.asyncio
    async def test_send_to_specific_channel_by_alias(self) -> None:
        """Should send to specific channel by alias."""
        ch1 = MockAsyncChannel("ch1")
        ch2 = MockAsyncChannel("ch2")
        manager = AlertManager().add_channel(ch1, alias="heartbeat").add_channel(ch2, alias="watchdog")
        alert = AlertMessage(title="Test", body="Body")

        results = await manager.send(alert, channel="watchdog")

        assert len(results) == 1
        assert results[0].channel == "ch2"

    @pytest.mark.asyncio
    async def test_send_to_specific_channel_by_name(self) -> None:
        """Should send to specific channel by channel name."""
        ch1 = MockAsyncChannel("slack_ops")
        ch2 = MockAsyncChannel("email_critical")
        manager = AlertManager().add_channel(ch1).add_channel(ch2)
        alert = AlertMessage(title="Test", body="Body")

        results = await manager.send(alert, channel="email_critical")

        assert len(results) == 1
        assert results[0].channel == "email_critical"

    @pytest.mark.asyncio
    async def test_send_channel_not_found(self) -> None:
        """Should return empty list when target channel not found."""
        ch1 = MockAsyncChannel("ch1")
        manager = AlertManager().add_channel(ch1, key="primary")
        alert = AlertMessage(title="Test", body="Body")

        results = await manager.send(alert, channel="nonexistent")

        assert results == []

    @pytest.mark.asyncio
    async def test_send_empty_alerts_list(self) -> None:
        """Should return empty list for empty alerts."""
        ch1 = MockAsyncChannel("ch1")
        manager = AlertManager().add_channel(ch1)

        results = await manager.send([])

        assert results == []

    @pytest.mark.asyncio
    async def test_send_multiple_alerts(self) -> None:
        """Should send multiple alerts to channels."""
        ch1 = MockAsyncChannel("ch1")
        manager = AlertManager().add_channel(ch1)
        alerts = [
            AlertMessage(title="Alert 1", body="Body 1"),
            AlertMessage(title="Alert 2", body="Body 2"),
            AlertMessage(title="Alert 3", body="Body 3"),
        ]

        results = await manager.send(alerts)

        assert len(results) == 3
        assert len(ch1.sent_alerts) == 3

    @pytest.mark.asyncio
    async def test_no_matching_channels_for_level(self) -> None:
        """Should return empty when no channels match alert level."""
        ch1 = MockAsyncChannel("critical_only")
        manager = AlertManager().add_channel(ch1, min_level=AlertLevel.CRITICAL)
        alert = AlertMessage(title="Test", body="Body", level=AlertLevel.INFO)

        results = await manager.send(alert)

        assert results == []


class TestAlertManagerExceptionHandling:
    """Tests for AlertManager exception handling."""

    @pytest.mark.asyncio
    async def test_channel_raises_throttled_error(self) -> None:
        """Should handle AlertThrottledError from channel."""

        class ThrottledChannel(AsyncAlertChannel):
            """Channel that raises AlertThrottledError."""

            @property
            def name(self) -> str:
                return "throttled"

            async def send(self, alert: AlertMessage) -> AlertResult:
                raise AlertThrottledError("Rate limited", retry_after=30)

        channel = ThrottledChannel()
        manager = AlertManager().add_channel(channel)
        alert = AlertMessage(title="Test", body="Body")

        results = await manager.send(alert)

        assert len(results) == 1
        assert results[0].success is False
        assert results[0].error is not None
        assert "retry after" in results[0].error.lower()
        assert manager.stats.total_throttled == 1

    @pytest.mark.asyncio
    async def test_channel_raises_generic_exception(self) -> None:
        """Should handle generic exceptions from channel."""

        class ExplodingChannel(AsyncAlertChannel):
            """Channel that raises generic exception."""

            @property
            def name(self) -> str:
                return "exploding"

            async def send(self, alert: AlertMessage) -> AlertResult:
                raise RuntimeError("Connection failed")

        channel = ExplodingChannel()
        manager = AlertManager().add_channel(channel)
        alert = AlertMessage(title="Test", body="Body")

        results = await manager.send(alert)

        assert len(results) == 1
        assert results[0].success is False
        assert results[0].error is not None
        assert "Connection failed" in results[0].error
        assert manager.stats.total_failed == 1


class TestCreateEmailTransport:
    """Tests for _create_email_transport helper."""

    def test_smtp_minimal(self) -> None:
        """Should create SMTP transport with minimal config."""
        config: dict[str, Any] = {"type": "smtp", "host": "localhost"}
        transport = _create_email_transport(config, "test", None)
        assert transport is not None

    def test_smtp_with_credentials(self) -> None:
        """Should create SMTP transport with credentials."""
        config: dict[str, Any] = {
            "type": "smtp",
            "host": "smtp.example.com",
            "port": 465,
            "username": "user",
            "password": "pass",
            "use_tls": False,
        }
        transport = _create_email_transport(config, "test", None)
        assert transport is not None

    def test_resend_with_api_key(self) -> None:
        """Should create Resend transport with API key."""
        config: dict[str, Any] = {"type": "resend", "api_key": "re_123"}
        transport = _create_email_transport(config, "test", None)
        assert transport is not None

    def test_gmail_raises_error(self) -> None:
        """Should raise error for Gmail transport."""
        config: dict[str, Any] = {"type": "gmail"}
        with pytest.raises(AlertConfigurationError, match="requires programmatic"):
            _create_email_transport(config, "test", None)

    def test_unknown_type_raises_error(self) -> None:
        """Should raise error for unknown transport type."""
        config: dict[str, Any] = {"type": "sendgrid"}
        with pytest.raises(AlertConfigurationError, match="Unknown transport type"):
            _create_email_transport(config, "test", None)


class TestCreateEmailChannel:
    """Tests for _create_email_channel helper."""

    def test_create_email_channel(self) -> None:
        """Should create EmailChannel from config."""
        config: dict[str, Any] = {
            "transport": {"type": "smtp", "host": "localhost"},
            "sender": "alerts@example.com",
            "recipients": ["oncall@example.com"],
            "subject_prefix": "[ALERT]",
        }
        channel = _create_email_channel(config, "email_test", None)
        assert channel is not None
        assert channel.name == "email_test"

    def test_create_email_channel_missing_transport(self) -> None:
        """Should raise error when transport missing."""
        config: dict[str, Any] = {
            "sender": "alerts@example.com",
            "recipients": ["oncall@example.com"],
        }
        with pytest.raises(AlertConfigurationError, match="requires 'transport'"):
            _create_email_channel(config, "test", None)

    def test_create_email_channel_missing_sender(self) -> None:
        """Should raise error when sender missing."""
        config: dict[str, Any] = {
            "transport": {"type": "smtp", "host": "localhost"},
            "recipients": ["oncall@example.com"],
        }
        with pytest.raises(AlertConfigurationError, match="requires 'sender'"):
            _create_email_channel(config, "test", None)

    def test_create_email_channel_empty_recipients(self) -> None:
        """Should raise error when recipients empty."""
        config: dict[str, Any] = {
            "transport": {"type": "smtp", "host": "localhost"},
            "sender": "alerts@example.com",
            "recipients": [],
        }
        with pytest.raises(AlertConfigurationError, match="requires 'recipients'"):
            _create_email_channel(config, "test", None)

    def test_create_email_channel_import_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should wrap ImportError from transport creation."""
        config: dict[str, Any] = {
            "transport": {"type": "smtp", "host": "localhost"},
            "sender": "alerts@example.com",
            "recipients": ["oncall@example.com"],
        }

        def mock_create_transport(*args: Any, **kwargs: Any) -> None:
            raise ImportError("smtplib not found")

        import kstlib.alerts.manager as manager_module

        monkeypatch.setattr(manager_module, "_create_email_transport", mock_create_transport)

        with pytest.raises(AlertConfigurationError, match="Missing dependency"):
            _create_email_channel(config, "test", None)


class TestFromConfigExceptionWrapping:
    """Tests for from_config exception wrapping."""

    def test_wraps_non_config_exceptions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should wrap non-AlertConfigurationError exceptions."""
        config = {
            "channels": {
                "slack_ops": {
                    "type": "slack",
                    "webhook_url": "https://hooks.slack.com/services/T123/B456/xyz",
                },
            },
        }

        from kstlib.alerts.channels import SlackChannel

        def failing_from_config(*args: Any, **kwargs: Any) -> None:
            raise ValueError("Unexpected error in channel init")

        monkeypatch.setattr(SlackChannel, "from_config", staticmethod(failing_from_config))

        with pytest.raises(AlertConfigurationError, match="Failed to configure channel"):
            AlertManager.from_config(config)
