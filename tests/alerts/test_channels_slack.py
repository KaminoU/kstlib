"""Tests for kstlib.alerts.channels.slack module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kstlib.alerts.channels.slack import (
    LEVEL_COLOR,
    LEVEL_EMOJI,
    MAX_BODY_LENGTH,
    MAX_TITLE_LENGTH,
    SlackChannel,
    _mask_webhook_url,
    _truncate,
)
from kstlib.alerts.exceptions import AlertConfigurationError, AlertDeliveryError
from kstlib.alerts.models import AlertMessage
from kstlib.limits import HARD_MAX_CHANNEL_TIMEOUT, HARD_MIN_CHANNEL_TIMEOUT


class TestMaskWebhookUrl:
    """Tests for _mask_webhook_url helper."""

    def test_mask_valid_url(self) -> None:
        """Should mask valid webhook URL."""
        url = "https://hooks.slack.com/services/T123ABC/B456DEF/xyzSecret123"
        masked = _mask_webhook_url(url)
        assert masked == "https://hooks.slack.com/services/T***/B***/***"

    def test_mask_empty_url(self) -> None:
        """Should return *** for empty URL."""
        assert _mask_webhook_url("") == "***"

    def test_mask_invalid_url(self) -> None:
        """Should return *** for non-Slack URL."""
        assert _mask_webhook_url("https://example.com") == "***"

    def test_mask_partial_url(self) -> None:
        """Should handle partial Slack URLs."""
        url = "https://hooks.slack.com/services/"
        masked = _mask_webhook_url(url)
        assert "***" in masked


class TestTruncate:
    """Tests for _truncate helper."""

    def test_no_truncation_needed(self) -> None:
        """Should not truncate short text."""
        text = "Short text"
        assert _truncate(text, 100) == text

    def test_truncation_at_limit(self) -> None:
        """Should not truncate text at exact limit."""
        text = "Exact"
        assert _truncate(text, 5) == "Exact"

    def test_truncation_with_ellipsis(self) -> None:
        """Should truncate long text with ellipsis."""
        text = "This is a very long text"
        truncated = _truncate(text, 10)
        assert truncated == "This is..."
        assert len(truncated) == 10


class TestSlackChannelInit:
    """Tests for SlackChannel initialization."""

    def test_valid_webhook_url(self) -> None:
        """Should accept valid Slack webhook URL."""
        url = "https://hooks.slack.com/services/T123ABC/B456DEF/xyzSecret123"
        channel = SlackChannel(webhook_url=url)
        assert channel.name == "slack"

    def test_empty_webhook_url(self) -> None:
        """Should reject empty webhook URL."""
        with pytest.raises(AlertConfigurationError) as exc_info:
            SlackChannel(webhook_url="")
        assert "required" in str(exc_info.value).lower()

    def test_invalid_webhook_url(self) -> None:
        """Should reject invalid webhook URL."""
        with pytest.raises(AlertConfigurationError) as exc_info:
            SlackChannel(webhook_url="https://example.com/webhook")
        assert "Invalid Slack webhook URL" in str(exc_info.value)

    def test_custom_username(self) -> None:
        """Should accept custom username."""
        url = "https://hooks.slack.com/services/T123ABC/B456DEF/xyz"
        channel = SlackChannel(webhook_url=url, username="my-alerts")
        assert "my-alerts" in repr(channel)

    def test_custom_icon_emoji(self) -> None:
        """Should accept custom icon emoji."""
        url = "https://hooks.slack.com/services/T123ABC/B456DEF/xyz"
        channel = SlackChannel(webhook_url=url, icon_emoji=":fire:")
        assert channel is not None

    def test_custom_channel_name(self) -> None:
        """Should accept custom channel name."""
        url = "https://hooks.slack.com/services/T123ABC/B456DEF/xyz"
        channel = SlackChannel(webhook_url=url, channel_name="slack_ops")
        assert channel.name == "slack_ops"

    def test_default_timeout_from_config(self) -> None:
        """Should use config default when timeout not specified."""
        url = "https://hooks.slack.com/services/T123ABC/B456DEF/xyz"
        channel = SlackChannel(webhook_url=url)
        # Default from config is 30.0 (alerts.channels.timeout)
        assert channel._timeout == 30.0

    def test_custom_timeout(self) -> None:
        """Should accept custom timeout value."""
        url = "https://hooks.slack.com/services/T123ABC/B456DEF/xyz"
        channel = SlackChannel(webhook_url=url, timeout=15.0)
        assert channel._timeout == 15.0

    def test_timeout_clamped_to_minimum(self) -> None:
        """Should clamp timeout to hard minimum."""
        url = "https://hooks.slack.com/services/T123ABC/B456DEF/xyz"
        channel = SlackChannel(webhook_url=url, timeout=0.1)
        assert channel._timeout == HARD_MIN_CHANNEL_TIMEOUT

    def test_timeout_clamped_to_maximum(self) -> None:
        """Should clamp timeout to hard maximum."""
        url = "https://hooks.slack.com/services/T123ABC/B456DEF/xyz"
        channel = SlackChannel(webhook_url=url, timeout=999.0)
        assert channel._timeout == HARD_MAX_CHANNEL_TIMEOUT

    def test_repr_no_secrets(self) -> None:
        """repr should not contain webhook URL."""
        url = "https://hooks.slack.com/services/T123ABC/B456DEF/secretXYZ"
        channel = SlackChannel(webhook_url=url)
        repr_str = repr(channel)
        assert "secret" not in repr_str.lower()
        assert "T123ABC" not in repr_str
        assert "username=" in repr_str


class TestSlackChannelBuildPayload:
    """Tests for SlackChannel payload building."""

    def test_basic_payload(self) -> None:
        """Should build basic payload with title and body."""
        url = "https://hooks.slack.com/services/T123ABC/B456DEF/xyz"
        channel = SlackChannel(webhook_url=url)
        alert = AlertMessage(title="Test", body="Test body")

        payload = channel._build_payload(alert)

        assert payload["username"] == "kstlib-alerts"
        assert payload["icon_emoji"] == ":bell:"
        assert "attachments" in payload
        assert len(payload["attachments"]) == 1

    def test_payload_has_title(self) -> None:
        """Payload attachment should include title."""
        url = "https://hooks.slack.com/services/T123ABC/B456DEF/xyz"
        channel = SlackChannel(webhook_url=url)
        alert = AlertMessage(title="My Alert", body="Body")

        payload = channel._build_payload(alert)
        attachment = payload["attachments"][0]

        assert "My Alert" in attachment["title"]

    def test_payload_has_body(self) -> None:
        """Payload attachment should include body."""
        url = "https://hooks.slack.com/services/T123ABC/B456DEF/xyz"
        channel = SlackChannel(webhook_url=url)
        alert = AlertMessage(title="Title", body="Alert body content")

        payload = channel._build_payload(alert)
        attachment = payload["attachments"][0]

        assert attachment["text"] == "Alert body content"

    def test_payload_truncates_title(self) -> None:
        """Payload should truncate long titles."""
        url = "https://hooks.slack.com/services/T123ABC/B456DEF/xyz"
        channel = SlackChannel(webhook_url=url)
        long_title = "A" * 200
        alert = AlertMessage(title=long_title, body="Body")

        payload = channel._build_payload(alert)
        attachment = payload["attachments"][0]

        # Title includes emoji, so check total length is reasonable
        assert len(attachment["title"]) <= MAX_TITLE_LENGTH + 30

    def test_payload_truncates_body(self) -> None:
        """Payload should truncate long body."""
        url = "https://hooks.slack.com/services/T123ABC/B456DEF/xyz"
        channel = SlackChannel(webhook_url=url)
        long_body = "B" * 4000
        alert = AlertMessage(title="Title", body=long_body)

        payload = channel._build_payload(alert)
        attachment = payload["attachments"][0]

        assert len(attachment["text"]) <= MAX_BODY_LENGTH

    def test_level_colors(self) -> None:
        """Payload should use correct colors for levels."""
        url = "https://hooks.slack.com/services/T123ABC/B456DEF/xyz"
        channel = SlackChannel(webhook_url=url)

        for level, expected_color in LEVEL_COLOR.items():
            alert = AlertMessage(title="Test", body="Body", level=level)
            payload = channel._build_payload(alert)
            assert payload["attachments"][0]["color"] == expected_color

    def test_level_emojis(self) -> None:
        """Payload should use correct emojis for levels."""
        url = "https://hooks.slack.com/services/T123ABC/B456DEF/xyz"
        channel = SlackChannel(webhook_url=url)

        for level, expected_emoji in LEVEL_EMOJI.items():
            alert = AlertMessage(title="Test", body="Body", level=level)
            payload = channel._build_payload(alert)
            assert expected_emoji in payload["attachments"][0]["title"]


class TestSlackChannelSend:
    """Tests for SlackChannel.send()."""

    @pytest.mark.asyncio
    async def test_send_success(self) -> None:
        """Should send alert successfully."""
        url = "https://hooks.slack.com/services/T123ABC/B456DEF/xyz"
        channel = SlackChannel(webhook_url=url)
        alert = AlertMessage(title="Test", body="Body")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_async_client.return_value.__aenter__.return_value = mock_client

            result = await channel.send(alert)

        assert result.success is True
        assert result.channel == "slack"

    @pytest.mark.asyncio
    async def test_send_http_error(self) -> None:
        """Should raise AlertDeliveryError on HTTP error."""
        url = "https://hooks.slack.com/services/T123ABC/B456DEF/xyz"
        channel = SlackChannel(webhook_url=url)
        alert = AlertMessage(title="Test", body="Body")

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_async_client.return_value.__aenter__.return_value = mock_client

            with pytest.raises(AlertDeliveryError) as exc_info:
                await channel.send(alert)

        assert exc_info.value.channel == "slack"
        assert exc_info.value.retryable is True  # 5xx is retryable

    @pytest.mark.asyncio
    async def test_send_client_error_not_retryable(self) -> None:
        """Should mark 4xx errors as not retryable."""
        url = "https://hooks.slack.com/services/T123ABC/B456DEF/xyz"
        channel = SlackChannel(webhook_url=url)
        alert = AlertMessage(title="Test", body="Body")

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_async_client.return_value.__aenter__.return_value = mock_client

            with pytest.raises(AlertDeliveryError) as exc_info:
                await channel.send(alert)

        assert exc_info.value.retryable is False

    @pytest.mark.asyncio
    async def test_send_timeout(self) -> None:
        """Should raise AlertDeliveryError on timeout."""
        import httpx

        url = "https://hooks.slack.com/services/T123ABC/B456DEF/xyz"
        channel = SlackChannel(webhook_url=url)
        alert = AlertMessage(title="Test", body="Body")

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.TimeoutException("timeout")
            mock_async_client.return_value.__aenter__.return_value = mock_client

            with pytest.raises(AlertDeliveryError) as exc_info:
                await channel.send(alert)

        assert exc_info.value.retryable is True

    @pytest.mark.asyncio
    async def test_send_request_error(self) -> None:
        """Should raise AlertDeliveryError on request error."""
        import httpx

        url = "https://hooks.slack.com/services/T123ABC/B456DEF/xyz"
        channel = SlackChannel(webhook_url=url)
        alert = AlertMessage(title="Test", body="Body")

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.RequestError("connection failed")
            mock_async_client.return_value.__aenter__.return_value = mock_client

            with pytest.raises(AlertDeliveryError) as exc_info:
                await channel.send(alert)

        assert exc_info.value.retryable is True


class TestSlackChannelFromConfig:
    """Tests for SlackChannel.from_config()."""

    def test_from_config_with_webhook_url(self) -> None:
        """Should create channel from config with webhook_url."""
        config = {
            "webhook_url": "https://hooks.slack.com/services/T123ABC/B456DEF/xyz",
            "username": "my-alerts",
        }
        channel = SlackChannel.from_config(config)
        assert "my-alerts" in repr(channel)

    def test_from_config_with_credentials(self) -> None:
        """Should create channel from config with credentials."""
        config = {
            "credentials": "slack_webhook",
        }
        mock_resolver = MagicMock()
        mock_resolver.resolve.return_value = MagicMock(value="https://hooks.slack.com/services/T123ABC/B456DEF/xyz")

        channel = SlackChannel.from_config(config, mock_resolver)
        mock_resolver.resolve.assert_called_once_with("slack_webhook")
        assert channel is not None

    def test_from_config_missing_webhook(self) -> None:
        """Should raise error when no webhook source provided."""
        config = {"username": "alerts"}
        with pytest.raises(AlertConfigurationError):
            SlackChannel.from_config(config)

    def test_from_config_credential_error(self) -> None:
        """Should raise error when credential resolution fails."""
        config = {"credentials": "bad_cred"}
        mock_resolver = MagicMock()
        mock_resolver.resolve.side_effect = Exception("Not found")

        with pytest.raises(AlertConfigurationError) as exc_info:
            SlackChannel.from_config(config, mock_resolver)
        assert "Failed to resolve" in str(exc_info.value)

    def test_from_config_with_name(self) -> None:
        """Should use name from config."""
        config = {
            "webhook_url": "https://hooks.slack.com/services/T123ABC/B456DEF/xyz",
            "name": "slack_ops",
        }
        channel = SlackChannel.from_config(config)
        assert channel.name == "slack_ops"
