"""Tests for kstlib.monitoring.service module."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from kstlib.monitoring import (
    CollectorError,
    MonitoringResult,
    MonitoringService,
    RenderError,
    StatusCell,
    StatusLevel,
)

if TYPE_CHECKING:
    from email.message import EmailMessage


class TestMonitoringResult:
    """Tests for MonitoringResult dataclass."""

    def test_success_when_no_errors(self) -> None:
        """Result.success is True when errors list is empty."""
        result = MonitoringResult(
            html="<p>test</p>",
            data={"key": "value"},
            collected_at=datetime.now(timezone.utc),
            rendered_at=datetime.now(timezone.utc),
            errors=[],
        )
        assert result.success is True

    def test_not_success_when_errors_present(self) -> None:
        """Result.success is False when errors list has items."""
        error = CollectorError("test", ValueError("fail"))
        result = MonitoringResult(
            html="<p>test</p>",
            data={"key": None},
            collected_at=datetime.now(timezone.utc),
            rendered_at=datetime.now(timezone.utc),
            errors=[error],
        )
        assert result.success is False


class TestMonitoringServiceInit:
    """Tests for MonitoringService initialization."""

    def test_init_with_template_only(self) -> None:
        """Service can be created with just a template."""
        service = MonitoringService(template="<p>{{ msg }}</p>")
        assert service.template == "<p>{{ msg }}</p>"
        assert service.collector_names == []

    def test_init_with_collectors(self) -> None:
        """Service can be created with initial collectors."""
        service = MonitoringService(
            template="<p>{{ x }}</p>",
            collectors={"x": lambda: 42},
        )
        assert service.collector_names == ["x"]

    def test_init_inline_css_default_true(self) -> None:
        """inline_css defaults to True for email compatibility."""
        service = MonitoringService(template="")
        assert service.inline_css is True

    def test_init_inline_css_false(self) -> None:
        """inline_css can be set to False."""
        service = MonitoringService(template="", inline_css=False)
        assert service.inline_css is False


class TestMonitoringServiceCollectors:
    """Tests for collector management."""

    def test_add_collector_returns_self(self) -> None:
        """add_collector returns self for chaining."""
        service = MonitoringService(template="")
        result = service.add_collector("x", lambda: 1)
        assert result is service

    def test_add_multiple_collectors_chainable(self) -> None:
        """Multiple collectors can be added via chaining."""
        service = MonitoringService(template="")
        service.add_collector("a", lambda: 1).add_collector("b", lambda: 2)
        assert set(service.collector_names) == {"a", "b"}

    def test_remove_collector_returns_self(self) -> None:
        """remove_collector returns self for chaining."""
        service = MonitoringService(template="", collectors={"x": lambda: 1})
        result = service.remove_collector("x")
        assert result is service
        assert service.collector_names == []

    def test_remove_collector_raises_key_error(self) -> None:
        """remove_collector raises KeyError for unknown collector."""
        service = MonitoringService(template="")
        with pytest.raises(KeyError):
            service.remove_collector("unknown")


class TestMonitoringServiceCollect:
    """Tests for collect() method."""

    @pytest.mark.asyncio
    async def test_collect_sync_collectors(self) -> None:
        """Sync collectors are called and data returned."""
        service = MonitoringService(
            template="",
            collectors={
                "a": lambda: 1,
                "b": lambda: "two",
            },
        )
        data, errors = await service.collect()
        assert data == {"a": 1, "b": "two"}
        assert errors == []

    @pytest.mark.asyncio
    async def test_collect_async_collectors(self) -> None:
        """Async collectors are awaited and data returned."""

        async def get_value() -> int:
            await asyncio.sleep(0.01)
            return 42

        service = MonitoringService(template="", collectors={"x": get_value})
        data, errors = await service.collect()
        assert data == {"x": 42}
        assert errors == []

    @pytest.mark.asyncio
    async def test_collect_mixed_collectors(self) -> None:
        """Both sync and async collectors work together."""

        async def async_fn() -> str:
            return "async"

        service = MonitoringService(
            template="",
            collectors={
                "sync": lambda: "sync",
                "async": async_fn,
            },
        )
        data, errors = await service.collect()
        assert data == {"sync": "sync", "async": "async"}

    @pytest.mark.asyncio
    async def test_collect_fail_fast_raises_on_sync_error(self) -> None:
        """fail_fast=True raises immediately on sync collector error."""

        def failing() -> None:
            raise ValueError("sync fail")

        service = MonitoringService(
            template="",
            collectors={"fail": failing},
            fail_fast=True,
        )
        with pytest.raises(CollectorError) as exc_info:
            await service.collect()
        assert exc_info.value.collector_name == "fail"
        assert "sync fail" in str(exc_info.value.cause)

    @pytest.mark.asyncio
    async def test_collect_fail_fast_raises_on_async_error(self) -> None:
        """fail_fast=True raises immediately on async collector error."""

        async def failing() -> None:
            raise ValueError("async fail")

        service = MonitoringService(
            template="",
            collectors={"fail": failing},
            fail_fast=True,
        )
        with pytest.raises(CollectorError) as exc_info:
            await service.collect()
        assert exc_info.value.collector_name == "fail"

    @pytest.mark.asyncio
    async def test_collect_no_fail_fast_continues_on_error(self) -> None:
        """fail_fast=False continues after error and reports in errors list."""

        def failing() -> None:
            raise ValueError("oops")

        service = MonitoringService(
            template="",
            collectors={
                "good": lambda: "ok",
                "bad": failing,
            },
            fail_fast=False,
        )
        data, errors = await service.collect()
        assert data["good"] == "ok"
        assert data["bad"] is None
        assert len(errors) == 1
        assert errors[0].collector_name == "bad"


class TestMonitoringServiceRender:
    """Tests for render() method."""

    def test_render_simple_template(self) -> None:
        """Simple template rendering works."""
        service = MonitoringService(template="<p>{{ msg }}</p>", inline_css=True)
        html = service.render({"msg": "Hello"})
        assert "<p>Hello</p>" in html

    def test_render_with_status_cell(self) -> None:
        """Renderable objects work with | render filter."""
        service = MonitoringService(
            template="<p>{{ status | render }}</p>",
            inline_css=True,
        )
        html = service.render({"status": StatusCell("UP", StatusLevel.OK)})
        assert "UP" in html
        assert "<span" in html

    def test_render_inline_css_false_adds_style_block(self) -> None:
        """inline_css=False prepends CSS classes."""
        service = MonitoringService(
            template="<p>{{ msg }}</p>",
            inline_css=False,
        )
        html = service.render({"msg": "test"})
        assert "<style>" in html

    def test_render_invalid_template_raises(self) -> None:
        """Invalid Jinja2 syntax raises RenderError."""
        service = MonitoringService(template="{{ invalid syntax }}")
        with pytest.raises(RenderError):
            service.render({})


class TestMonitoringServiceRun:
    """Tests for run() and run_sync() methods."""

    @pytest.mark.asyncio
    async def test_run_returns_monitoring_result(self) -> None:
        """run() returns a complete MonitoringResult."""
        service = MonitoringService(
            template="<p>{{ x }}</p>",
            collectors={"x": lambda: 42},
        )
        result = await service.run()
        assert isinstance(result, MonitoringResult)
        assert "42" in result.html
        assert result.data == {"x": 42}
        assert result.success is True

    @pytest.mark.asyncio
    async def test_run_sets_timestamps(self) -> None:
        """run() sets collected_at and rendered_at timestamps."""
        service = MonitoringService(template="<p>test</p>")
        before = datetime.now(timezone.utc)
        result = await service.run()
        after = datetime.now(timezone.utc)
        assert before <= result.collected_at <= after
        assert before <= result.rendered_at <= after
        assert result.collected_at <= result.rendered_at

    def test_run_sync_works_outside_async_context(self) -> None:
        """run_sync() works when called from sync code."""
        service = MonitoringService(
            template="<p>{{ msg }}</p>",
            collectors={"msg": lambda: "sync"},
        )
        result = service.run_sync()
        assert "sync" in result.html


class TestMonitoringServiceDeliver:
    """Tests for deliver() method."""

    @pytest.mark.asyncio
    async def test_deliver_calls_async_transport(self) -> None:
        """deliver() works with async transport."""
        transport = AsyncMock()
        transport.send = AsyncMock()

        def build_message(html: str) -> EmailMessage:
            from email.message import EmailMessage

            msg = EmailMessage()
            msg["Subject"] = "Test"
            msg.set_content(html, subtype="html")
            return msg

        service = MonitoringService(
            template="<p>{{ x }}</p>",
            collectors={"x": lambda: 1},
        )
        result = await service.deliver(transport, build_message)

        assert result.success
        transport.send.assert_called_once()
        sent_msg = transport.send.call_args[0][0]
        assert sent_msg["Subject"] == "Test"

    @pytest.mark.asyncio
    async def test_deliver_calls_sync_transport_in_executor(self) -> None:
        """deliver() wraps sync transport in executor."""
        transport = MagicMock()
        transport.send = MagicMock()

        def build_message(html: str) -> EmailMessage:
            from email.message import EmailMessage

            msg = EmailMessage()
            msg.set_content(html, subtype="html")
            return msg

        service = MonitoringService(
            template="<p>test</p>",
        )
        result = await service.deliver(transport, build_message)

        assert result.success
        transport.send.assert_called_once()


class TestCollectorError:
    """Tests for CollectorError exception."""

    def test_collector_error_attributes(self) -> None:
        """CollectorError stores name and cause."""
        cause = ValueError("inner")
        error = CollectorError("my_collector", cause)
        assert error.collector_name == "my_collector"
        assert error.cause is cause

    def test_collector_error_message(self) -> None:
        """CollectorError has descriptive message."""
        error = CollectorError("test", ValueError("fail"))
        assert "test" in str(error)
        assert "fail" in str(error)


class TestMonitoringServiceAsyncErrors:
    """Tests for async collector error handling."""

    @pytest.mark.asyncio
    async def test_async_collector_error_no_fail_fast(self) -> None:
        """Async collector error with fail_fast=False sets data[name]=None."""

        async def failing_async() -> None:
            raise ValueError("async error")

        service = MonitoringService(
            template="<p>{{ x }}</p>",
            collectors={
                "x": failing_async,
                "y": lambda: "ok",
            },
            fail_fast=False,
        )
        data, errors = await service.collect()

        assert data["x"] is None  # Failed async collector
        assert data["y"] == "ok"  # Successful sync collector
        assert len(errors) == 1
        assert errors[0].collector_name == "x"

    @pytest.mark.asyncio
    async def test_fail_fast_cancels_pending_async_tasks(self) -> None:
        """fail_fast=True cancels pending async tasks."""
        call_order: list[str] = []

        def sync_fail() -> None:
            call_order.append("sync_fail")
            raise ValueError("sync error")

        async def slow_async() -> str:
            call_order.append("slow_start")
            await asyncio.sleep(1)  # Long delay
            call_order.append("slow_end")  # Should not be reached
            return "slow"

        service = MonitoringService(
            template="",
            collectors={
                "sync_fail": sync_fail,
                "slow": slow_async,
            },
            fail_fast=True,
        )

        with pytest.raises(CollectorError) as exc_info:
            await service.collect()

        assert exc_info.value.collector_name == "sync_fail"
        # Give a moment for task cancellation
        await asyncio.sleep(0.1)
        # slow_end should not be in call_order (task was cancelled)
        assert "slow_end" not in call_order

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates(self) -> None:
        """CancelledError is re-raised, not caught as collector error."""
        cancelled_event = asyncio.Event()

        async def cancellable() -> str:
            await cancelled_event.wait()
            return "done"

        service = MonitoringService(
            template="",
            collectors={"cancellable": cancellable},
            fail_fast=False,
        )

        # Start collection task
        task = asyncio.create_task(service.collect())
        await asyncio.sleep(0.05)

        # Cancel the task
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task


class TestMonitoringServiceRunSyncInAsyncContext:
    """Tests for run_sync() called from async context."""

    @pytest.mark.asyncio
    async def test_run_sync_from_async_context(self) -> None:
        """run_sync() works when called from within async context."""
        import concurrent.futures

        service = MonitoringService(
            template="<p>{{ msg }}</p>",
            collectors={"msg": lambda: "async-context"},
        )

        # Call run_sync from within an async function
        # This triggers the ThreadPoolExecutor path
        def call_run_sync() -> MonitoringResult:
            return service.run_sync()

        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            result = await loop.run_in_executor(executor, call_run_sync)

        assert "async-context" in result.html
