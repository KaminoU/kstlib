"""Abstract base classes for alert channels.

Provides both sync and async channel interfaces following the same
pattern as :mod:`kstlib.mail.transport`.

Examples:
    Implementing a sync channel::

        class WebhookChannel(AlertChannel):
            @property
            def name(self) -> str:
                return "webhook"

            def send(self, alert: AlertMessage) -> AlertResult:
                # Send via HTTP POST
                return AlertResult(channel=self.name, success=True)

    Implementing an async channel::

        class AsyncWebhookChannel(AsyncAlertChannel):
            @property
            def name(self) -> str:
                return "async_webhook"

            async def send(self, alert: AlertMessage) -> AlertResult:
                async with httpx.AsyncClient() as client:
                    # Send via HTTP POST
                    pass
                return AlertResult(channel=self.name, success=True)
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from concurrent.futures import ThreadPoolExecutor

    from kstlib.alerts.models import AlertMessage, AlertResult


class AlertChannel(ABC):
    """Abstract sync channel for delivering alerts.

    Subclass this for synchronous alert delivery implementations.

    Examples:
        Implementing a custom sync channel::

            class LogChannel(AlertChannel):
                @property
                def name(self) -> str:
                    return "log"

                def send(self, alert: AlertMessage) -> AlertResult:
                    print(f"[{alert.level.name}] {alert.title}")
                    return AlertResult(channel=self.name, success=True)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the unique name of this channel.

        Used for logging, metrics, and result identification.
        """

    @abstractmethod
    def send(self, alert: AlertMessage) -> AlertResult:
        """Deliver the alert via this channel.

        Args:
            alert: The alert message to deliver.

        Returns:
            AlertResult with delivery status.

        Raises:
            AlertDeliveryError: If delivery fails.
        """


class AsyncAlertChannel(ABC):
    """Abstract async channel for delivering alerts.

    Subclass this for asynchronous alert delivery implementations
    that use async HTTP clients or other async I/O.

    Examples:
        Implementing a custom async channel::

            class SlackChannel(AsyncAlertChannel):
                @property
                def name(self) -> str:
                    return "slack"

                async def send(self, alert: AlertMessage) -> AlertResult:
                    async with httpx.AsyncClient() as client:
                        await client.post(...)
                    return AlertResult(channel=self.name, success=True)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the unique name of this channel.

        Used for logging, metrics, and result identification.
        """

    @abstractmethod
    async def send(self, alert: AlertMessage) -> AlertResult:
        """Deliver the alert asynchronously via this channel.

        Args:
            alert: The alert message to deliver.

        Returns:
            AlertResult with delivery status.

        Raises:
            AlertDeliveryError: If delivery fails.
        """


class AsyncChannelWrapper(AsyncAlertChannel):
    """Wrap a sync channel for async usage.

    Executes the sync channel's send method in a thread pool executor
    to avoid blocking the event loop. Follows the same pattern as
    :class:`kstlib.mail.transport.AsyncTransportWrapper`.

    Args:
        channel: The sync channel to wrap.
        executor: Optional thread pool executor. If None, uses the default.

    Examples:
        Wrapping a sync channel::

            sync_channel = LogChannel()
            async_channel = AsyncChannelWrapper(sync_channel)

            # Now usable in async context
            await async_channel.send(alert)
    """

    def __init__(
        self,
        channel: AlertChannel,
        *,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        """Initialize the async wrapper.

        Args:
            channel: The sync channel to wrap.
            executor: Optional custom thread pool executor.
        """
        self._channel = channel
        self._executor = executor

    @property
    def name(self) -> str:
        """Return the name of the wrapped channel."""
        return self._channel.name

    @property
    def channel(self) -> AlertChannel:
        """Return the wrapped sync channel."""
        return self._channel

    async def send(self, alert: AlertMessage) -> AlertResult:
        """Send alert asynchronously via the wrapped channel.

        Runs the sync channel's send method in a thread pool to avoid
        blocking the async event loop.

        Args:
            alert: The alert message to send.

        Returns:
            AlertResult from the wrapped channel.

        Raises:
            AlertDeliveryError: If the underlying channel fails.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            self._channel.send,
            alert,
        )


__all__ = ["AlertChannel", "AsyncAlertChannel", "AsyncChannelWrapper"]
