"""Tests for async mail transport wrapper."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from kstlib.mail.transport import AsyncMailTransport, AsyncTransportWrapper, MailTransport

if TYPE_CHECKING:
    pass


class DummySyncTransport(MailTransport):
    """Sync transport for testing."""

    def __init__(self) -> None:
        """Initialize with call tracking."""
        self.messages_sent: list[EmailMessage] = []
        self.call_count = 0

    def send(self, message: EmailMessage) -> None:
        """Record the sent message."""
        self.messages_sent.append(message)
        self.call_count += 1


class FailingSyncTransport(MailTransport):
    """Sync transport that always fails."""

    def send(self, message: EmailMessage) -> None:
        """Raise an error."""
        raise RuntimeError("Transport failure")


class TestAsyncMailTransport:
    """Tests for AsyncMailTransport abstract class."""

    def test_is_abstract(self) -> None:
        """AsyncMailTransport cannot be instantiated directly."""
        with pytest.raises(TypeError, match="abstract"):
            AsyncMailTransport()  # type: ignore[abstract]

    def test_subclass_must_implement_send(self) -> None:
        """Subclass without send implementation raises TypeError."""

        class IncompleteTransport(AsyncMailTransport):
            pass

        with pytest.raises(TypeError, match="abstract"):
            IncompleteTransport()  # type: ignore[abstract]


class TestAsyncTransportWrapper:
    """Tests for AsyncTransportWrapper."""

    def test_wraps_sync_transport(self) -> None:
        """Wrapper stores the sync transport."""
        sync = DummySyncTransport()
        wrapper = AsyncTransportWrapper(sync)
        assert wrapper.transport is sync

    def test_is_async_mail_transport(self) -> None:
        """Wrapper is an AsyncMailTransport instance."""
        sync = DummySyncTransport()
        wrapper = AsyncTransportWrapper(sync)
        assert isinstance(wrapper, AsyncMailTransport)

    @pytest.mark.asyncio
    async def test_send_delegates_to_sync_transport(self) -> None:
        """Async send calls the underlying sync transport."""
        sync = DummySyncTransport()
        wrapper = AsyncTransportWrapper(sync)

        message = EmailMessage()
        message["Subject"] = "Test"
        message["From"] = "sender@example.com"
        message["To"] = "recipient@example.com"
        message.set_content("Hello")

        await wrapper.send(message)

        assert sync.call_count == 1
        assert len(sync.messages_sent) == 1
        assert sync.messages_sent[0]["Subject"] == "Test"

    @pytest.mark.asyncio
    async def test_send_multiple_messages(self) -> None:
        """Multiple sends work correctly."""
        sync = DummySyncTransport()
        wrapper = AsyncTransportWrapper(sync)

        for i in range(3):
            message = EmailMessage()
            message["Subject"] = f"Test {i}"
            message["From"] = "sender@example.com"
            message["To"] = "recipient@example.com"
            message.set_content(f"Body {i}")
            await wrapper.send(message)

        assert sync.call_count == 3
        assert len(sync.messages_sent) == 3

    @pytest.mark.asyncio
    async def test_send_propagates_exceptions(self) -> None:
        """Exceptions from sync transport are propagated."""
        sync = FailingSyncTransport()
        wrapper = AsyncTransportWrapper(sync)

        message = EmailMessage()
        message["Subject"] = "Test"
        message["From"] = "sender@example.com"
        message["To"] = "recipient@example.com"

        with pytest.raises(RuntimeError, match="Transport failure"):
            await wrapper.send(message)

    @pytest.mark.asyncio
    async def test_uses_custom_executor(self) -> None:
        """Custom executor is used when provided."""
        import asyncio

        sync = DummySyncTransport()
        executor = ThreadPoolExecutor(max_workers=1)
        wrapper = AsyncTransportWrapper(sync, executor=executor)

        message = EmailMessage()
        message["Subject"] = "Test"
        message["From"] = "sender@example.com"
        message["To"] = "recipient@example.com"
        message.set_content("Hello")

        # Track calls to run_in_executor
        captured_executor = None
        original_run_in_executor = asyncio.get_running_loop().run_in_executor

        async def tracking_run_in_executor(exec: ThreadPoolExecutor | None, func: object, *args: object) -> object:
            nonlocal captured_executor
            captured_executor = exec
            return await original_run_in_executor(exec, func, *args)  # type: ignore[arg-type]

        with patch.object(
            asyncio.get_running_loop(),
            "run_in_executor",
            side_effect=tracking_run_in_executor,
        ):
            await wrapper.send(message)

        assert captured_executor is executor
        executor.shutdown(wait=False)

    @pytest.mark.asyncio
    async def test_runs_in_thread_pool(self) -> None:
        """Send runs in thread pool, not blocking event loop."""
        import threading

        sync = DummySyncTransport()
        wrapper = AsyncTransportWrapper(sync)

        main_thread = threading.current_thread()
        send_thread = None

        class ThreadTrackingTransport(MailTransport):
            def send(self, message: EmailMessage) -> None:
                nonlocal send_thread
                send_thread = threading.current_thread()

        tracking = ThreadTrackingTransport()
        wrapper = AsyncTransportWrapper(tracking)

        message = EmailMessage()
        message["Subject"] = "Test"
        message["From"] = "sender@example.com"
        message["To"] = "recipient@example.com"

        await wrapper.send(message)

        # Send should have run in a different thread
        assert send_thread is not None
        assert send_thread != main_thread
