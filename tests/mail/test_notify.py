"""Tests for the mail notification decorator."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from email.message import EmailMessage

import pytest

from kstlib.mail import MailBuilder, MailTransportError, NotifyResult
from kstlib.mail.transport import MailTransport


class MockTransport(MailTransport):
    """Mock transport that records sent messages."""

    def __init__(self, *, should_fail: bool = False) -> None:
        """Initialize with optional failure mode."""
        self.sent_messages: list[EmailMessage] = []
        self.should_fail = should_fail

    def send(self, message: EmailMessage) -> None:
        """Record sent message or raise if failure mode."""
        if self.should_fail:
            raise MailTransportError("Mock transport failure")
        self.sent_messages.append(message)


class TestNotifyResult:
    """Tests for the NotifyResult dataclass."""

    def test_success_result(self) -> None:
        """Create a success result with all fields."""
        now = datetime.now(timezone.utc)
        result = NotifyResult(
            function_name="my_func",
            success=True,
            started_at=now,
            ended_at=now,
            duration_ms=100.5,
            return_value={"data": 42},
        )
        assert result.function_name == "my_func"
        assert result.success is True
        assert result.duration_ms == 100.5
        assert result.return_value == {"data": 42}
        assert result.exception is None
        assert result.traceback_str is None

    def test_failure_result(self) -> None:
        """Create a failure result with exception and traceback."""
        now = datetime.now(timezone.utc)
        exc = ValueError("test error")
        result = NotifyResult(
            function_name="failing_func",
            success=False,
            started_at=now,
            ended_at=now,
            duration_ms=50.0,
            exception=exc,
            traceback_str="Traceback...",
        )
        assert result.success is False
        assert result.exception is exc
        assert result.traceback_str == "Traceback..."


class TestNotifyDecorator:
    """Tests for the @mail.notify() decorator."""

    def test_notify_sync_success(self) -> None:
        """Notify decorator sends email on sync function success."""
        transport = MockTransport()
        mail = MailBuilder(transport=transport).sender("bot@example.com").to("admin@example.com").subject("ETL Job")

        @mail.notify
        def extract() -> dict[str, int]:
            return {"rows": 100}

        result = extract()

        assert result == {"rows": 100}
        assert len(transport.sent_messages) == 1
        msg = transport.sent_messages[0]
        assert "[OK] ETL Job - extract" in msg["Subject"]

    def test_notify_sync_failure(self) -> None:
        """Notify decorator sends email on sync function failure."""
        transport = MockTransport()
        mail = MailBuilder(transport=transport).sender("bot@example.com").to("admin@example.com").subject("ETL Job")

        @mail.notify
        def load() -> None:
            raise ValueError("Database connection failed")

        with pytest.raises(ValueError, match="Database connection failed"):
            load()

        assert len(transport.sent_messages) == 1
        msg = transport.sent_messages[0]
        assert "[FAILED] ETL Job - load" in msg["Subject"]

    def test_notify_with_subject_override(self) -> None:
        """Subject override in decorator takes precedence."""
        transport = MockTransport()
        mail = (
            MailBuilder(transport=transport).sender("bot@example.com").to("admin@example.com").subject("Global Subject")
        )

        @mail.notify(subject="Step 2 - Transform")
        def transform() -> str:
            return "done"

        transform()

        msg = transport.sent_messages[0]
        assert "[OK] Step 2 - Transform - transform" in msg["Subject"]

    def test_notify_on_error_only_success(self) -> None:
        """No notification sent when on_error_only=True and function succeeds."""
        transport = MockTransport()
        mail = MailBuilder(transport=transport).sender("bot@example.com").to("admin@example.com").subject("Job")

        @mail.notify(on_error_only=True)
        def quiet_task() -> int:
            return 42

        result = quiet_task()

        assert result == 42
        assert len(transport.sent_messages) == 0

    def test_notify_on_error_only_failure(self) -> None:
        """Notification sent when on_error_only=True and function fails."""
        transport = MockTransport()
        mail = MailBuilder(transport=transport).sender("bot@example.com").to("admin@example.com").subject("Job")

        @mail.notify(on_error_only=True)
        def failing_task() -> None:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            failing_task()

        assert len(transport.sent_messages) == 1

    def test_notify_include_return(self) -> None:
        """Return value included in notification when include_return=True."""
        transport = MockTransport()
        mail = MailBuilder(transport=transport).sender("bot@example.com").to("admin@example.com").subject("Job")

        @mail.notify(include_return=True)
        def compute() -> dict[str, int]:
            return {"answer": 42}

        compute()

        # Check HTML body contains return value
        msg = transport.sent_messages[0]
        body = msg.get_body("html")
        assert body is not None
        content = body.get_content()
        assert "answer" in content
        assert "42" in content

    def test_notify_without_traceback(self) -> None:
        """Traceback excluded when include_traceback=False."""
        transport = MockTransport()
        mail = MailBuilder(transport=transport).sender("bot@example.com").to("admin@example.com").subject("Job")

        @mail.notify(include_traceback=False)
        def crash() -> None:
            raise KeyError("missing")

        with pytest.raises(KeyError):
            crash()

        msg = transport.sent_messages[0]
        body = msg.get_body("html")
        assert body is not None
        content = body.get_content()
        assert "Traceback" not in content

    def test_notify_with_traceback(self) -> None:
        """Traceback included by default."""
        transport = MockTransport()
        mail = MailBuilder(transport=transport).sender("bot@example.com").to("admin@example.com").subject("Job")

        @mail.notify
        def crash() -> None:
            raise KeyError("missing")

        with pytest.raises(KeyError):
            crash()

        msg = transport.sent_messages[0]
        body = msg.get_body("html")
        assert body is not None
        content = body.get_content()
        assert "Traceback" in content

    def test_notify_transport_failure_does_not_crash(self) -> None:
        """Transport failure in notification does not crash decorated function."""
        transport = MockTransport(should_fail=True)
        mail = MailBuilder(transport=transport).sender("bot@example.com").to("admin@example.com").subject("Job")

        @mail.notify
        def work() -> str:
            return "done"

        # Should not raise despite transport failure
        result = work()
        assert result == "done"

    def test_notify_preserves_function_metadata(self) -> None:
        """Decorated function preserves original name and docstring."""
        transport = MockTransport()
        mail = MailBuilder(transport=transport).sender("bot@example.com").to("admin@example.com").subject("Job")

        @mail.notify
        def documented_function() -> None:
            """This is the docstring."""

        assert documented_function.__name__ == "documented_function"
        assert documented_function.__doc__ == "This is the docstring."

    def test_notify_independent_builders(self) -> None:
        """Each decorated function gets independent builder copy."""
        transport = MockTransport()
        mail = MailBuilder(transport=transport).sender("bot@example.com").to("admin@example.com").subject("Original")

        @mail.notify(subject="First")
        def first() -> int:
            return 1

        @mail.notify(subject="Second")
        def second() -> int:
            return 2

        first()
        second()

        assert len(transport.sent_messages) == 2
        assert "First" in transport.sent_messages[0]["Subject"]
        assert "Second" in transport.sent_messages[1]["Subject"]


class TestNotifyDecoratorAsync:
    """Tests for async function support."""

    @pytest.mark.asyncio
    async def test_notify_async_success(self) -> None:
        """Notify decorator works with async functions."""
        transport = MockTransport()
        mail = MailBuilder(transport=transport).sender("bot@example.com").to("admin@example.com").subject("Async Job")

        @mail.notify
        async def async_task() -> str:
            await asyncio.sleep(0.001)
            return "async done"

        result = await async_task()

        assert result == "async done"
        assert len(transport.sent_messages) == 1
        assert "[OK] Async Job - async_task" in transport.sent_messages[0]["Subject"]

    @pytest.mark.asyncio
    async def test_notify_async_failure(self) -> None:
        """Notify decorator handles async function failures."""
        transport = MockTransport()
        mail = MailBuilder(transport=transport).sender("bot@example.com").to("admin@example.com").subject("Async Job")

        @mail.notify
        async def async_crash() -> None:
            await asyncio.sleep(0.001)
            raise OSError("network error")

        with pytest.raises(OSError, match="network error"):
            await async_crash()

        assert len(transport.sent_messages) == 1
        assert "[FAILED]" in transport.sent_messages[0]["Subject"]

    @pytest.mark.asyncio
    async def test_notify_async_on_error_only(self) -> None:
        """on_error_only works with async functions."""
        transport = MockTransport()
        mail = MailBuilder(transport=transport).sender("bot@example.com").to("admin@example.com").subject("Job")

        @mail.notify(on_error_only=True)
        async def quiet_async() -> int:
            return 42

        result = await quiet_async()

        assert result == 42
        assert len(transport.sent_messages) == 0


class TestFormatMethods:
    """Tests for email body formatting methods."""

    def test_format_success_body_basic(self) -> None:
        """Format success body with minimal data."""
        mail = MailBuilder()
        now = datetime.now(timezone.utc)
        result = NotifyResult(
            function_name="test_func",
            success=True,
            started_at=now,
            ended_at=now,
            duration_ms=123.45,
        )

        body = mail._format_success_body(result, include_return=False)

        assert "completed successfully" in body
        assert "test_func" in body
        assert "123.45" in body

    def test_format_success_body_with_return(self) -> None:
        """Format success body with return value."""
        mail = MailBuilder()
        now = datetime.now(timezone.utc)
        result = NotifyResult(
            function_name="test_func",
            success=True,
            started_at=now,
            ended_at=now,
            duration_ms=100.0,
            return_value={"key": "value"},
        )

        body = mail._format_success_body(result, include_return=True)

        assert "Return value" in body
        assert "key" in body

    def test_format_failure_body(self) -> None:
        """Format failure body with exception and traceback."""
        mail = MailBuilder()
        now = datetime.now(timezone.utc)
        result = NotifyResult(
            function_name="crash_func",
            success=False,
            started_at=now,
            ended_at=now,
            duration_ms=50.0,
            exception=ValueError("bad input"),
            traceback_str="Traceback (most recent call last):\n  ...",
        )

        body = mail._format_failure_body(result)

        assert "execution failed" in body
        assert "crash_func" in body
        assert "ValueError" in body
        assert "bad input" in body
        assert "Traceback" in body

    def test_format_failure_body_escapes_html(self) -> None:
        """HTML special characters are escaped in failure body."""
        mail = MailBuilder()
        now = datetime.now(timezone.utc)
        result = NotifyResult(
            function_name="test_func",
            success=False,
            started_at=now,
            ended_at=now,
            duration_ms=10.0,
            exception=ValueError("<script>alert('xss')</script>"),
            traceback_str="<dangerous>",
        )

        body = mail._format_failure_body(result)

        assert "<script>" not in body
        assert "&lt;script&gt;" in body
        assert "&lt;dangerous&gt;" in body

    def test_format_success_body_escapes_html(self) -> None:
        """HTML special characters are escaped in success body."""
        mail = MailBuilder()
        now = datetime.now(timezone.utc)
        result = NotifyResult(
            function_name="<script>bad</script>",
            success=True,
            started_at=now,
            ended_at=now,
            duration_ms=10.0,
            return_value="<img src=x>",
        )

        body = mail._format_success_body(result, include_return=True)

        assert "<script>" not in body
        assert "&lt;script&gt;" in body


class TestSnapshot:
    """Tests for the _snapshot method."""

    def test_snapshot_creates_independent_copy(self) -> None:
        """Snapshot creates a copy with shared transport but independent state."""
        transport = MockTransport()
        original = (
            MailBuilder(transport=transport)
            .sender("original@example.com")
            .to("admin@example.com")
            .subject("Original Subject")
        )

        snapshot = original._snapshot()

        # Transport should be shared
        assert snapshot._transport is original._transport

        # Modify original
        original.subject("Modified Subject")
        original.to("another@example.com")

        # Snapshot state should be unchanged
        assert snapshot._subject == "Original Subject"
        assert len(snapshot._to) == 1
