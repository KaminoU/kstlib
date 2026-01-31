"""Tests for kstlib.alerts.channels.base module."""

import pytest

from kstlib.alerts.channels.base import (
    AlertChannel,
    AsyncAlertChannel,
    AsyncChannelWrapper,
)
from kstlib.alerts.models import AlertMessage, AlertResult


class ConcreteAlertChannel(AlertChannel):
    """Concrete implementation of AlertChannel for testing."""

    def __init__(self, channel_name: str = "concrete") -> None:
        """Initialize the channel."""
        self._name = channel_name
        self.sent_alerts: list[AlertMessage] = []

    @property
    def name(self) -> str:
        """Return channel name."""
        return self._name

    def send(self, alert: AlertMessage) -> AlertResult:
        """Send alert and return result."""
        self.sent_alerts.append(alert)
        return AlertResult(channel=self._name, success=True, message_id="msg123")


class ConcreteAsyncChannel(AsyncAlertChannel):
    """Concrete implementation of AsyncAlertChannel for testing."""

    def __init__(self, channel_name: str = "async_concrete") -> None:
        """Initialize the channel."""
        self._name = channel_name
        self.sent_alerts: list[AlertMessage] = []

    @property
    def name(self) -> str:
        """Return channel name."""
        return self._name

    async def send(self, alert: AlertMessage) -> AlertResult:
        """Send alert and return result."""
        self.sent_alerts.append(alert)
        return AlertResult(channel=self._name, success=True)


class TestAlertChannel:
    """Tests for AlertChannel abstract class."""

    def test_concrete_implementation(self) -> None:
        """Should allow concrete implementation."""
        channel = ConcreteAlertChannel()
        assert channel.name == "concrete"

    def test_send(self) -> None:
        """Should call send method."""
        channel = ConcreteAlertChannel()
        alert = AlertMessage(title="Test", body="Body")

        result = channel.send(alert)

        assert result.success is True
        assert result.channel == "concrete"
        assert len(channel.sent_alerts) == 1


class TestAsyncAlertChannel:
    """Tests for AsyncAlertChannel abstract class."""

    def test_concrete_implementation(self) -> None:
        """Should allow concrete implementation."""
        channel = ConcreteAsyncChannel()
        assert channel.name == "async_concrete"

    @pytest.mark.asyncio
    async def test_send(self) -> None:
        """Should call async send method."""
        channel = ConcreteAsyncChannel()
        alert = AlertMessage(title="Test", body="Body")

        result = await channel.send(alert)

        assert result.success is True
        assert result.channel == "async_concrete"
        assert len(channel.sent_alerts) == 1


class TestAsyncChannelWrapper:
    """Tests for AsyncChannelWrapper."""

    def test_wrap_sync_channel(self) -> None:
        """Should wrap sync channel."""
        sync_channel = ConcreteAlertChannel("sync")
        wrapper = AsyncChannelWrapper(sync_channel)

        assert wrapper.name == "sync"

    def test_channel_property(self) -> None:
        """Should expose wrapped channel."""
        sync_channel = ConcreteAlertChannel("sync")
        wrapper = AsyncChannelWrapper(sync_channel)

        assert wrapper.channel is sync_channel

    @pytest.mark.asyncio
    async def test_send_calls_sync(self) -> None:
        """Should call sync channel's send method."""
        sync_channel = ConcreteAlertChannel("sync")
        wrapper = AsyncChannelWrapper(sync_channel)
        alert = AlertMessage(title="Test", body="Body")

        result = await wrapper.send(alert)

        assert result.success is True
        assert result.channel == "sync"
        assert len(sync_channel.sent_alerts) == 1

    @pytest.mark.asyncio
    async def test_send_returns_result(self) -> None:
        """Should return result from wrapped channel."""
        sync_channel = ConcreteAlertChannel("sync")
        wrapper = AsyncChannelWrapper(sync_channel)
        alert = AlertMessage(title="Test", body="Body")

        result = await wrapper.send(alert)

        assert result.message_id == "msg123"

    def test_with_executor(self) -> None:
        """Should accept custom executor."""
        from concurrent.futures import ThreadPoolExecutor

        sync_channel = ConcreteAlertChannel()
        executor = ThreadPoolExecutor(max_workers=1)

        wrapper = AsyncChannelWrapper(sync_channel, executor=executor)

        assert wrapper is not None
        executor.shutdown(wait=False)
