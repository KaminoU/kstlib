"""Simplified Monitoring API with decorator-based collectors.

This module provides a streamlined API for monitoring dashboards:

- Config in YAML (template, delivery settings)
- Collectors in Python (via @decorator)
- Simple run() to collect, render, and deliver

Examples:
    Basic usage with decorators:

    >>> from kstlib.monitoring import Monitoring, MonitorKV
    >>> mon = Monitoring(template="<p>{{ info | render }}</p>")
    >>> @mon.collector
    ... def info():
    ...     return MonitorKV(items={"status": "OK"})
    >>> result = mon.run_sync()
    >>> "OK" in result.html
    True

    Load from config:

    >>> mon = Monitoring.from_config()  # doctest: +SKIP
    >>> @mon.collector  # doctest: +SKIP
    ... def metrics():  # doctest: +SKIP
    ...     return collect_metrics()  # doctest: +SKIP
    >>> mon.run_sync()  # doctest: +SKIP
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from kstlib.monitoring.service import Collector, MonitoringResult, MonitoringService

if TYPE_CHECKING:
    from kstlib.monitoring.delivery import DeliveryBackend, DeliveryResult

F = TypeVar("F", bound=Callable[..., Any])


class Monitoring:
    """Simplified monitoring with decorator-based collectors.

    This class provides a cleaner API than MonitoringService:

    - Collectors are registered via ``@mon.collector`` decorator
    - Config loaded from ``kstlib.conf.yml`` section ``monitoring:``
    - Automatic template_file resolution
    - Integrated delivery

    Args:
        template: Jinja2 template string (mutually exclusive with template_file).
        template_file: Path to template file (mutually exclusive with template).
        inline_css: Use inline CSS for email compatibility (default True).
        fail_fast: Raise on first collector error (default False).
        delivery: Optional delivery backend (FileDelivery or MailDelivery).
        name: Dashboard name (for delivery subject, default "monitoring").

    Examples:
        Direct instantiation:

        >>> mon = Monitoring(template="<p>{{ msg }}</p>")
        >>> @mon.collector
        ... def msg():
        ...     return "Hello"
        >>> mon.run_sync().html
        '<p>Hello</p>'

        From config file:

        >>> mon = Monitoring.from_config()  # doctest: +SKIP
    """

    def __init__(  # noqa: PLR0913
        self,
        *,
        template: str | None = None,
        template_file: str | Path | None = None,
        inline_css: bool = True,
        fail_fast: bool = False,
        delivery: DeliveryBackend | _DeferredMailDelivery | None = None,
        name: str = "monitoring",
    ) -> None:
        """Initialize monitoring instance."""
        if template is None and template_file is None:
            raise ValueError("Either 'template' or 'template_file' is required")
        if template is not None and template_file is not None:
            raise ValueError("Cannot specify both 'template' and 'template_file'")

        # Resolve template
        if template_file is not None:
            path = Path(template_file)
            if not path.exists():
                raise FileNotFoundError(f"Template not found: {path}")
            template = path.read_text(encoding="utf-8")

        # After validation, template is guaranteed to be str
        assert template is not None  # for mypy
        self._template: str = template
        self._inline_css = inline_css
        self._fail_fast = fail_fast
        self._delivery: DeliveryBackend | _DeferredMailDelivery | None = delivery
        self._name = name
        self._collectors: dict[str, Collector] = {}

    @classmethod
    def from_config(
        cls,
        config_section: str = "monitoring",
        *,
        base_dir: Path | None = None,
    ) -> Monitoring:
        """Create Monitoring instance from kstlib.conf.yml.

        Loads the ``monitoring:`` section from the config file.

        Args:
            config_section: Config section name (default "monitoring").
            base_dir: Base directory for resolving template_file paths.
                      Defaults to current working directory.

        Returns:
            Configured Monitoring instance.

        Raises:
            ValueError: If config section is missing or invalid.

        Examples:
            >>> mon = Monitoring.from_config()  # doctest: +SKIP
            >>> @mon.collector  # doctest: +SKIP
            ... def data():  # doctest: +SKIP
            ...     return {"key": "value"}  # doctest: +SKIP
        """
        from kstlib.config import get_config, load_config

        # Load config if not already loaded
        try:
            config = get_config()
        except Exception:
            config = load_config()

        # Get monitoring section (Box.get is untyped)
        mon_config: dict[str, Any] = config.get(config_section, {})  # type: ignore[no-untyped-call]
        if not mon_config:
            raise ValueError(f"Config section '{config_section}' not found or empty")

        # Resolve base directory
        if base_dir is None:
            base_dir = Path.cwd()

        # Extract settings
        template = mon_config.get("template")
        template_file = mon_config.get("template_file")

        # Resolve template_file path
        if template_file is not None:
            template_file = base_dir / template_file

        # Build delivery backend if configured
        delivery = None
        delivery_config = mon_config.get("delivery")
        if delivery_config:
            delivery = cls._build_delivery(delivery_config)

        return cls(
            template=template,
            template_file=template_file,
            inline_css=mon_config.get("inline_css", True),
            fail_fast=mon_config.get("fail_fast", False),
            delivery=delivery,
            name=mon_config.get("name", "monitoring"),
        )

    @staticmethod
    def _build_delivery(config: dict[str, Any]) -> DeliveryBackend | _DeferredMailDelivery:
        """Build delivery backend from config dict."""
        from kstlib.monitoring.delivery import FileDelivery

        delivery_type = config.get("type", "file")

        if delivery_type == "file":
            return FileDelivery(
                output_dir=config.get("output_dir", "./reports"),
                max_files=config.get("max_files", 100),
            )

        if delivery_type == "mail":
            # Mail delivery requires transport - defer to run() time
            # Store config for later
            return _DeferredMailDelivery(config)

        raise ValueError(f"Unknown delivery type: {delivery_type}")

    @property
    def name(self) -> str:
        """Return dashboard name."""
        return self._name

    @property
    def collector_names(self) -> list[str]:
        """Return list of registered collector names."""
        return list(self._collectors)

    def collector(self, func: F) -> F:
        """Decorator to register a collector function.

        The function name becomes the template variable name.

        Args:
            func: Function returning data for the template.

        Returns:
            The original function (unmodified).

        Examples:
            >>> mon = Monitoring(template="{{ status }}")
            >>> @mon.collector
            ... def status():
            ...     return "OK"
            >>> mon.run_sync().html
            'OK'
        """
        self._collectors[func.__name__] = func
        return func

    def add_collector(self, name: str, func: Collector) -> Monitoring:
        """Add a collector with explicit name.

        Use this when you need a different name than the function name.

        Args:
            name: Name to use in template.
            func: Collector function.

        Returns:
            Self for chaining.
        """
        self._collectors[name] = func
        return self

    def _create_service(self) -> MonitoringService:
        """Create the underlying MonitoringService."""
        return MonitoringService(
            template=self._template,
            collectors=self._collectors,
            inline_css=self._inline_css,
            fail_fast=self._fail_fast,
        )

    async def run(self, *, deliver: bool = True) -> MonitoringResult:
        """Collect data, render template, and optionally deliver.

        Args:
            deliver: If True and delivery is configured, send the result.

        Returns:
            MonitoringResult with HTML and metadata.
        """
        service = self._create_service()
        result = await service.run()

        # Deliver if configured and requested
        if deliver and self._delivery is not None:
            await self._deliver(result)

        return result

    def run_sync(self, *, deliver: bool = True) -> MonitoringResult:
        """Synchronous version of run().

        Args:
            deliver: If True and delivery is configured, send the result.

        Returns:
            MonitoringResult with HTML and metadata.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(asyncio.run, self.run(deliver=deliver))
                return future.result()

        return asyncio.run(self.run(deliver=deliver))

    async def _deliver(self, result: MonitoringResult) -> DeliveryResult:
        """Deliver the result using configured backend."""
        if self._delivery is None:
            raise RuntimeError("No delivery backend configured")

        if isinstance(self._delivery, _DeferredMailDelivery):
            # Build actual mail delivery with transport
            delivery = await self._delivery.build()
            return await delivery.deliver(result, self._name)

        return await self._delivery.deliver(result, self._name)


class _DeferredMailDelivery:
    """Placeholder for mail delivery that needs OAuth token at runtime."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config

    async def build(self) -> DeliveryBackend:
        """Build actual MailDelivery with OAuth transport."""
        from kstlib.auth import OAuth2Provider
        from kstlib.mail.transports import GmailTransport
        from kstlib.monitoring.delivery import MailDelivery, MailDeliveryConfig

        # Get OAuth token
        provider = OAuth2Provider.from_config("google")
        token = provider.get_token()
        if token is None or token.is_expired:
            raise RuntimeError("Gmail token not available or expired. Run 'kstlib auth login google' first.")

        transport = GmailTransport(token=token)

        config = MailDeliveryConfig(
            sender=self._config.get("sender", ""),
            recipients=self._config.get("recipients", []),
            cc=self._config.get("cc", []),
            bcc=self._config.get("bcc", []),
            subject_template=self._config.get("subject_template", "Monitoring: {name}"),
        )

        return MailDelivery(transport=transport, config=config)


__all__ = [
    "Monitoring",
]
