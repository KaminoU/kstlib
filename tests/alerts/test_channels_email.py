"""Tests for kstlib.alerts.channels.email module."""

from email.message import EmailMessage

import pytest

from kstlib.alerts.channels.email import LEVEL_PREFIX, EmailChannel
from kstlib.alerts.exceptions import AlertConfigurationError, AlertDeliveryError
from kstlib.alerts.models import AlertLevel, AlertMessage
from kstlib.mail.transport import AsyncMailTransport, MailTransport


class MockSyncTransport(MailTransport):
    """Mock sync transport for testing."""

    def __init__(self) -> None:
        """Initialize mock transport."""
        self.sent_messages: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        """Store sent message."""
        self.sent_messages.append(message)


class MockAsyncTransport(AsyncMailTransport):
    """Mock async transport for testing."""

    def __init__(self, *, should_fail: bool = False) -> None:
        """Initialize mock transport."""
        self.sent_messages: list[EmailMessage] = []
        self._should_fail = should_fail

    async def send(self, message: EmailMessage) -> None:
        """Store sent message or raise error."""
        if self._should_fail:
            raise Exception("Transport failed")
        self.sent_messages.append(message)


class TestEmailChannelInit:
    """Tests for EmailChannel initialization."""

    def test_with_async_transport(self) -> None:
        """Should accept async transport."""
        transport = MockAsyncTransport()
        channel = EmailChannel(
            transport=transport,
            sender="alerts@example.com",
            recipients=["user@example.com"],
        )
        assert channel.name == "email"

    def test_with_sync_transport(self) -> None:
        """Should wrap sync transport."""
        transport = MockSyncTransport()
        channel = EmailChannel(
            transport=transport,
            sender="alerts@example.com",
            recipients=["user@example.com"],
        )
        assert channel.name == "email"

    def test_empty_sender(self) -> None:
        """Should reject empty sender."""
        transport = MockAsyncTransport()
        with pytest.raises(AlertConfigurationError) as exc_info:
            EmailChannel(
                transport=transport,
                sender="",
                recipients=["user@example.com"],
            )
        assert "sender" in str(exc_info.value).lower()

    def test_empty_recipients(self) -> None:
        """Should reject empty recipients list."""
        transport = MockAsyncTransport()
        with pytest.raises(AlertConfigurationError) as exc_info:
            EmailChannel(
                transport=transport,
                sender="alerts@example.com",
                recipients=[],
            )
        assert "recipient" in str(exc_info.value).lower()

    def test_custom_subject_prefix(self) -> None:
        """Should accept custom subject prefix."""
        transport = MockAsyncTransport()
        channel = EmailChannel(
            transport=transport,
            sender="alerts@example.com",
            recipients=["user@example.com"],
            subject_prefix="[PROD]",
        )
        assert channel is not None

    def test_custom_channel_name(self) -> None:
        """Should accept custom channel name."""
        transport = MockAsyncTransport()
        channel = EmailChannel(
            transport=transport,
            sender="alerts@example.com",
            recipients=["user@example.com"],
            channel_name="email_critical",
        )
        assert channel.name == "email_critical"

    def test_repr(self) -> None:
        """repr should show sender and recipient count."""
        transport = MockAsyncTransport()
        channel = EmailChannel(
            transport=transport,
            sender="alerts@example.com",
            recipients=["a@x.com", "b@x.com"],
        )
        repr_str = repr(channel)
        assert "alerts@example.com" in repr_str
        assert "recipients=2" in repr_str


class TestEmailChannelBuildMessage:
    """Tests for EmailChannel._build_message()."""

    def test_message_has_subject(self) -> None:
        """Built message should have correct subject."""
        transport = MockAsyncTransport()
        channel = EmailChannel(
            transport=transport,
            sender="alerts@example.com",
            recipients=["user@example.com"],
        )
        alert = AlertMessage(title="Test Alert", body="Body")

        message = channel._build_message(alert)

        assert message["Subject"] is not None
        assert "Test Alert" in message["Subject"]

    def test_message_has_from(self) -> None:
        """Built message should have correct From header."""
        transport = MockAsyncTransport()
        channel = EmailChannel(
            transport=transport,
            sender="alerts@example.com",
            recipients=["user@example.com"],
        )
        alert = AlertMessage(title="Test", body="Body")

        message = channel._build_message(alert)

        assert message["From"] == "alerts@example.com"

    def test_message_has_to(self) -> None:
        """Built message should have correct To header."""
        transport = MockAsyncTransport()
        channel = EmailChannel(
            transport=transport,
            sender="alerts@example.com",
            recipients=["user1@example.com", "user2@example.com"],
        )
        alert = AlertMessage(title="Test", body="Body")

        message = channel._build_message(alert)

        assert "user1@example.com" in message["To"]
        assert "user2@example.com" in message["To"]

    def test_message_has_body(self) -> None:
        """Built message should have body content."""
        transport = MockAsyncTransport()
        channel = EmailChannel(
            transport=transport,
            sender="alerts@example.com",
            recipients=["user@example.com"],
        )
        alert = AlertMessage(title="Test", body="Alert body content")

        message = channel._build_message(alert)
        body = message.get_content()

        assert "Alert body content" in body

    def test_subject_includes_level(self) -> None:
        """Subject should include level indicator."""
        transport = MockAsyncTransport()
        channel = EmailChannel(
            transport=transport,
            sender="alerts@example.com",
            recipients=["user@example.com"],
        )

        for level, prefix in LEVEL_PREFIX.items():
            alert = AlertMessage(title="Test", body="Body", level=level)
            message = channel._build_message(alert)
            assert prefix in message["Subject"]

    def test_subject_has_prefix(self) -> None:
        """Subject should include custom prefix."""
        transport = MockAsyncTransport()
        channel = EmailChannel(
            transport=transport,
            sender="alerts@example.com",
            recipients=["user@example.com"],
            subject_prefix="[PROD]",
        )
        alert = AlertMessage(title="Test", body="Body")

        message = channel._build_message(alert)

        assert "[PROD]" in message["Subject"]


class TestEmailChannelSend:
    """Tests for EmailChannel.send()."""

    @pytest.mark.asyncio
    async def test_send_success(self) -> None:
        """Should send alert successfully."""
        transport = MockAsyncTransport()
        channel = EmailChannel(
            transport=transport,
            sender="alerts@example.com",
            recipients=["user@example.com"],
        )
        alert = AlertMessage(title="Test", body="Body")

        result = await channel.send(alert)

        assert result.success is True
        assert result.channel == "email"
        assert len(transport.sent_messages) == 1

    @pytest.mark.asyncio
    async def test_send_failure(self) -> None:
        """Should raise AlertDeliveryError on failure."""
        transport = MockAsyncTransport(should_fail=True)
        channel = EmailChannel(
            transport=transport,
            sender="alerts@example.com",
            recipients=["user@example.com"],
        )
        alert = AlertMessage(title="Test", body="Body")

        with pytest.raises(AlertDeliveryError) as exc_info:
            await channel.send(alert)

        assert exc_info.value.channel == "email"
        assert exc_info.value.retryable is True

    @pytest.mark.asyncio
    async def test_send_with_sync_transport(self) -> None:
        """Should work with wrapped sync transport."""
        transport = MockSyncTransport()
        channel = EmailChannel(
            transport=transport,
            sender="alerts@example.com",
            recipients=["user@example.com"],
        )
        alert = AlertMessage(title="Test", body="Body")

        result = await channel.send(alert)

        assert result.success is True
        assert len(transport.sent_messages) == 1

    @pytest.mark.asyncio
    async def test_send_multiple_recipients(self) -> None:
        """Should send to all recipients."""
        transport = MockAsyncTransport()
        channel = EmailChannel(
            transport=transport,
            sender="alerts@example.com",
            recipients=["a@example.com", "b@example.com", "c@example.com"],
        )
        alert = AlertMessage(title="Test", body="Body")

        await channel.send(alert)

        # Single message with all recipients
        assert len(transport.sent_messages) == 1
        to_header = transport.sent_messages[0]["To"]
        assert "a@example.com" in to_header
        assert "b@example.com" in to_header
        assert "c@example.com" in to_header

    @pytest.mark.asyncio
    async def test_send_with_different_levels(self) -> None:
        """Should send alerts of different levels."""
        transport = MockAsyncTransport()
        channel = EmailChannel(
            transport=transport,
            sender="alerts@example.com",
            recipients=["user@example.com"],
        )

        for level in AlertLevel:
            alert = AlertMessage(title=f"{level.name} Alert", body="Body", level=level)
            result = await channel.send(alert)
            assert result.success is True


class TestEmailChannelName:
    """Tests for EmailChannel.name property."""

    def test_default_name(self) -> None:
        """Default name should be 'email'."""
        transport = MockAsyncTransport()
        channel = EmailChannel(
            transport=transport,
            sender="alerts@example.com",
            recipients=["user@example.com"],
        )
        assert channel.name == "email"

    def test_custom_name(self) -> None:
        """Should use custom channel name."""
        transport = MockAsyncTransport()
        channel = EmailChannel(
            transport=transport,
            sender="alerts@example.com",
            recipients=["user@example.com"],
            channel_name="email_ops",
        )
        assert channel.name == "email_ops"
