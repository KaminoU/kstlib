"""MonitoringService orchestrator for data collection, rendering, and delivery.

The MonitoringService provides a high-level API for building monitoring dashboards:

1. **Collect** - Run data collectors (sync or async callables)
2. **Render** - Generate HTML using Jinja2 templates and render types
3. **Deliver** - Send via email (kstlib.mail) or save to file

Examples:
    Basic usage with collectors:

    >>> from kstlib.monitoring import MonitoringService, StatusCell, StatusLevel
    >>> service = MonitoringService(
    ...     template=\"\"\"<p>Status: {{ status | render }}</p>\"\"\",
    ...     collectors={
    ...         "status": lambda: StatusCell("UP", StatusLevel.OK),
    ...     },
    ... )
    >>> result = service.run_sync()
    >>> "status-ok" in result.html
    True

    Async collectors for real-time data:

    >>> async def get_metrics():
    ...     # Fetch from API, database, etc.
    ...     return {"cpu": 75.2, "memory": 8192}
    >>> service = MonitoringService(
    ...     template=\"\"\"<p>CPU: {{ metrics.cpu }}%</p>\"\"\",
    ...     collectors={"metrics": get_metrics},
    ... )
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from kstlib.monitoring.exceptions import CollectorError, RenderError
from kstlib.monitoring.renderer import create_environment

if TYPE_CHECKING:
    from email.message import EmailMessage

    from kstlib.mail.transport import AsyncMailTransport, MailTransport

# Type alias for collectors: sync or async callables returning any data
Collector = Callable[[], Any] | Callable[[], Awaitable[Any]]


@dataclass
class MonitoringResult:
    """Result of a monitoring run.

    Attributes:
        html: The rendered HTML string.
        data: The collected data dictionary.
        collected_at: Timestamp when data was collected.
        rendered_at: Timestamp when HTML was rendered.
        errors: List of collector errors (if fail_fast=False).
    """

    html: str
    data: dict[str, Any]
    collected_at: datetime
    rendered_at: datetime
    errors: list[CollectorError] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Return True if no collector errors occurred."""
        return len(self.errors) == 0


class MonitoringService:
    """Orchestrator for collecting, rendering, and delivering monitoring dashboards.

    The service manages the full lifecycle of a monitoring dashboard:

    1. **Collectors** - Register data sources as sync or async callables
    2. **Template** - Jinja2 template with ``| render`` filter support
    3. **Render** - Generate HTML with automatic CSS handling
    4. **Deliver** - Optional email delivery via kstlib.mail transports

    Args:
        template: Jinja2 template string for rendering the dashboard.
        collectors: Optional dict mapping names to collector callables.
        inline_css: If True (default), use inline CSS for email compatibility.
        fail_fast: If True, raise on first collector error. If False, continue
            and report errors in the result.

    Examples:
        Simple dashboard with status cell:

        >>> from kstlib.monitoring import MonitoringService, StatusCell, StatusLevel
        >>> service = MonitoringService(
        ...     template=\"\"\"<div>{{ status | render }}</div>\"\"\",
        ...     collectors={"status": lambda: StatusCell("OK", StatusLevel.OK)},
        ... )
        >>> result = service.run_sync()
        >>> "OK" in result.html
        True

        Adding collectors after construction (chainable):

        >>> service = MonitoringService(template="<p>{{ msg }}</p>")
        >>> service.add_collector("msg", lambda: "Hello").run_sync().html
        '<p>Hello</p>'
    """

    def __init__(
        self,
        template: str,
        collectors: dict[str, Collector] | None = None,
        *,
        inline_css: bool = True,
        fail_fast: bool = True,
    ) -> None:
        """Initialize the monitoring service.

        Args:
            template: Jinja2 template string.
            collectors: Optional initial collectors dict.
            inline_css: Use inline CSS for email compatibility.
            fail_fast: Raise immediately on collector errors.
        """
        self._template = template
        self._collectors: dict[str, Collector] = dict(collectors) if collectors else {}
        self._inline_css = inline_css
        self._fail_fast = fail_fast
        self._env = create_environment()

    @property
    def template(self) -> str:
        """Return the template string."""
        return self._template

    @property
    def inline_css(self) -> bool:
        """Return whether inline CSS is enabled."""
        return self._inline_css

    @property
    def collector_names(self) -> list[str]:
        """Return list of registered collector names."""
        return list(self._collectors)

    def add_collector(self, name: str, collector: Collector) -> MonitoringService:
        """Add a data collector.

        Collectors are callables (sync or async) that return data to be passed
        to the template. The returned data can be any type including Renderable
        objects like StatusCell, MonitorTable, etc.

        Args:
            name: Name to use in the template (e.g., "status" for {{ status }}).
            collector: Callable returning the data. Can be sync or async.

        Returns:
            Self for method chaining.

        Examples:
            >>> service = MonitoringService(template="<p>{{ x }} + {{ y }}</p>")
            >>> service.add_collector("x", lambda: 1).add_collector("y", lambda: 2)
            <kstlib.monitoring.service.MonitoringService object at ...>
        """
        self._collectors[name] = collector
        return self

    def remove_collector(self, name: str) -> MonitoringService:
        """Remove a collector by name.

        Args:
            name: Name of the collector to remove.

        Returns:
            Self for method chaining.

        Raises:
            KeyError: If collector name not found.
        """
        del self._collectors[name]
        return self

    def _cancel_tasks(self, tasks: dict[str, asyncio.Task[Any]], exclude: str = "") -> None:
        """Cancel all pending async tasks except the excluded one."""
        for name, task in tasks.items():
            if name != exclude and not task.done():
                task.cancel()

    def _handle_collector_error(
        self,
        name: str,
        exc: Exception,
        errors: list[CollectorError],
        tasks: dict[str, asyncio.Task[Any]],
    ) -> CollectorError:
        """Handle a collector error: cancel tasks if fail_fast, else append to errors."""
        error = CollectorError(name, exc)
        if self._fail_fast:
            self._cancel_tasks(tasks)
            raise error from exc
        errors.append(error)
        return error

    async def collect(self) -> tuple[dict[str, Any], list[CollectorError]]:
        """Run all collectors and gather data.

        Collectors are run concurrently when possible. Async collectors are
        awaited, sync collectors are called directly.

        Returns:
            Tuple of (collected data dict, list of errors).

        Raises:
            CollectorError: If fail_fast=True and any collector fails.
        """
        data: dict[str, Any] = {}
        errors: list[CollectorError] = []
        async_tasks: dict[str, asyncio.Task[Any]] = {}
        sync_collectors: dict[str, Collector] = {}

        # Separate and schedule collectors
        for name, collector in self._collectors.items():
            if inspect.iscoroutinefunction(collector):
                async_tasks[name] = asyncio.create_task(collector())
            else:
                sync_collectors[name] = collector

        # Run sync collectors
        for name, collector in sync_collectors.items():
            try:
                data[name] = collector()
            except Exception as e:
                self._handle_collector_error(name, e, errors, async_tasks)
                data[name] = None

        # Await async collectors
        for name, task in async_tasks.items():
            try:
                data[name] = await task
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._handle_collector_error(name, e, errors, async_tasks)
                data[name] = None

        return data, errors

    def render(self, data: dict[str, Any]) -> str:
        """Render the template with collected data.

        Args:
            data: Dictionary of data to pass to the template.

        Returns:
            Rendered HTML string.

        Raises:
            RenderError: If template rendering fails.
        """
        from kstlib.monitoring._styles import get_css_classes

        try:
            template = self._env.from_string(self._template)
            html = template.render(**data)
        except Exception as e:
            raise RenderError(f"Template rendering failed: {e}") from e

        # Prepend CSS classes if not using inline CSS
        if not self._inline_css:
            html = get_css_classes() + "\n" + html

        return html

    async def run(self) -> MonitoringResult:
        """Collect data and render the dashboard.

        This is the main entry point for async usage. It runs all collectors,
        renders the template, and returns a MonitoringResult.

        Returns:
            MonitoringResult with HTML, data, timestamps, and any errors.

        Examples:
            >>> import asyncio
            >>> service = MonitoringService(
            ...     template="<p>{{ msg }}</p>",
            ...     collectors={"msg": lambda: "Hello"},
            ... )
            >>> result = asyncio.run(service.run())
            >>> "Hello" in result.html
            True
        """
        collected_at = datetime.now(timezone.utc)
        data, errors = await self.collect()

        html = self.render(data)
        rendered_at = datetime.now(timezone.utc)

        return MonitoringResult(
            html=html,
            data=data,
            collected_at=collected_at,
            rendered_at=rendered_at,
            errors=errors,
        )

    def run_sync(self) -> MonitoringResult:
        """Synchronous version of run().

        Convenience method for non-async contexts. Creates a new event loop
        if needed.

        Returns:
            MonitoringResult with HTML, data, timestamps, and any errors.

        Examples:
            >>> service = MonitoringService(
            ...     template="<p>{{ msg }}</p>",
            ...     collectors={"msg": lambda: "World"},
            ... )
            >>> "World" in service.run_sync().html
            True
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            # Already in an async context - can't use asyncio.run
            # Use a new thread or raise
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(asyncio.run, self.run())
                return future.result()

        return asyncio.run(self.run())

    async def deliver(
        self,
        transport: MailTransport | AsyncMailTransport,
        message_builder: Callable[[str], EmailMessage],
    ) -> MonitoringResult:
        """Collect, render, and deliver via email transport.

        This combines run() with email delivery. The message_builder callable
        receives the rendered HTML and should return a complete EmailMessage.

        Args:
            transport: Mail transport (sync or async) from kstlib.mail.
            message_builder: Callable that takes HTML and returns EmailMessage.

        Returns:
            MonitoringResult from the run.

        Examples:
            >>> from email.message import EmailMessage
            >>> def build_message(html: str) -> EmailMessage:
            ...     msg = EmailMessage()
            ...     msg["From"] = "bot@example.com"
            ...     msg["To"] = "team@example.com"
            ...     msg["Subject"] = "Dashboard"
            ...     msg.set_content(html, subtype="html")
            ...     return msg
        """
        result = await self.run()

        message = message_builder(result.html)

        # Check if transport is async or sync
        if hasattr(transport, "send") and inspect.iscoroutinefunction(transport.send):
            await transport.send(message)
        else:
            # Sync transport - run in thread pool
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, transport.send, message)

        return result


__all__ = [
    "Collector",
    "MonitoringResult",
    "MonitoringService",
]
