"""Tests for kstlib.monitoring.monitoring (simplified Monitoring API)."""

from __future__ import annotations

import pathlib
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kstlib.monitoring import MonitorKV, MonitorTable
from kstlib.monitoring.monitoring import Monitoring, _DeferredMailDelivery


class TestMonitoringInit:
    """Tests for Monitoring initialization."""

    def test_requires_template_or_template_file(self) -> None:
        """Must provide either template or template_file."""
        with pytest.raises(ValueError, match="Either 'template' or 'template_file' is required"):
            Monitoring()

    def test_cannot_specify_both_template_and_template_file(self, tmp_path: pathlib.Path) -> None:
        """Cannot provide both template and template_file."""
        template_file = tmp_path / "test.html.j2"
        template_file.write_text("<p>test</p>")

        with pytest.raises(ValueError, match="Cannot specify both"):
            Monitoring(template="<p>test</p>", template_file=template_file)

    def test_init_with_template_string(self) -> None:
        """Initialize with template string."""
        mon = Monitoring(template="<p>{{ msg }}</p>")
        assert mon.name == "monitoring"

    def test_init_with_template_file(self, tmp_path: pathlib.Path) -> None:
        """Initialize with template file path."""
        template_file = tmp_path / "test.html.j2"
        template_file.write_text("<h1>{{ title }}</h1>")

        mon = Monitoring(template_file=template_file)
        assert mon.name == "monitoring"

    def test_template_file_not_found(self, tmp_path: pathlib.Path) -> None:
        """FileNotFoundError when template file doesn't exist."""
        missing_file = tmp_path / "nonexistent.html.j2"

        with pytest.raises(FileNotFoundError, match="Template not found"):
            Monitoring(template_file=missing_file)

    def test_custom_name(self) -> None:
        """Custom name is set."""
        mon = Monitoring(template="<p>test</p>", name="my-dashboard")
        assert mon.name == "my-dashboard"

    def test_inline_css_default_true(self) -> None:
        """inline_css defaults to True."""
        mon = Monitoring(template="<p>test</p>")
        assert mon._inline_css is True

    def test_inline_css_false(self) -> None:
        """inline_css can be set to False."""
        mon = Monitoring(template="<p>test</p>", inline_css=False)
        assert mon._inline_css is False

    def test_fail_fast_default_false(self) -> None:
        """fail_fast defaults to False."""
        mon = Monitoring(template="<p>test</p>")
        assert mon._fail_fast is False


class TestMonitoringCollector:
    """Tests for collector decorator and registration."""

    def test_collector_decorator_registers_function(self) -> None:
        """@collector decorator registers the function."""
        mon = Monitoring(template="<p>test</p>")

        @mon.collector
        def my_data() -> str:
            return "hello"

        assert "my_data" in mon.collector_names

    def test_collector_decorator_returns_original_function(self) -> None:
        """@collector returns the original function unchanged."""
        mon = Monitoring(template="<p>test</p>")

        def my_data() -> str:
            return "hello"

        decorated = mon.collector(my_data)
        assert decorated is my_data

    def test_collector_names_property(self) -> None:
        """collector_names returns list of registered collector names."""
        mon = Monitoring(template="<p>test</p>")

        @mon.collector
        def data1() -> str:
            return "a"

        @mon.collector
        def data2() -> str:
            return "b"

        assert set(mon.collector_names) == {"data1", "data2"}

    def test_add_collector_with_explicit_name(self) -> None:
        """add_collector allows custom name."""
        mon = Monitoring(template="<p>test</p>")

        def my_func() -> str:
            return "test"

        mon.add_collector("custom_name", my_func)
        assert "custom_name" in mon.collector_names

    def test_add_collector_returns_self(self) -> None:
        """add_collector returns self for chaining."""
        mon = Monitoring(template="<p>test</p>")

        result = mon.add_collector("test", lambda: "value")
        assert result is mon


class TestMonitoringRun:
    """Tests for run() and run_sync() methods."""

    def test_run_sync_simple_template(self) -> None:
        """run_sync renders template with collector data."""
        mon = Monitoring(template="<p>{{ msg }}</p>")

        @mon.collector
        def msg() -> str:
            return "Hello"

        result = mon.run_sync(deliver=False)
        assert result.html == "<p>Hello</p>"

    def test_run_sync_with_monitor_types(self) -> None:
        """run_sync works with MonitorKV and MonitorTable."""
        mon = Monitoring(
            template="<div>{{ info | render }}</div><div>{{ table | render }}</div>",
            inline_css=False,
        )

        @mon.collector
        def info() -> MonitorKV:
            return MonitorKV(items={"status": "OK"})

        @mon.collector
        def table() -> MonitorTable:
            t = MonitorTable(headers=["Name", "Value"])
            t.add_row(["cpu", "50%"])
            return t

        result = mon.run_sync(deliver=False)
        assert "status" in result.html
        assert "OK" in result.html
        assert "cpu" in result.html

    @pytest.mark.asyncio
    async def test_run_async(self) -> None:
        """run() works asynchronously."""
        mon = Monitoring(template="{{ data }}")

        @mon.collector
        def data() -> str:
            return "async-test"

        result = await mon.run(deliver=False)
        assert "async-test" in result.html

    @pytest.mark.asyncio
    async def test_run_with_async_collector(self) -> None:
        """run() handles async collectors."""
        mon = Monitoring(template="{{ data }}")

        @mon.collector
        async def data() -> str:
            return "from-async"

        result = await mon.run(deliver=False)
        assert "from-async" in result.html

    def test_run_sync_no_delivery_when_disabled(self) -> None:
        """run_sync with deliver=False does not call delivery."""
        mock_delivery = AsyncMock()
        mon = Monitoring(template="{{ x }}", delivery=mock_delivery)

        @mon.collector
        def x() -> str:
            return "test"

        mon.run_sync(deliver=False)
        mock_delivery.deliver.assert_not_called()


class TestMonitoringDelivery:
    """Tests for delivery integration."""

    @pytest.mark.asyncio
    async def test_run_calls_delivery_when_configured(self) -> None:
        """run() calls delivery.deliver() when configured."""
        mock_delivery = AsyncMock()
        mock_delivery.deliver = AsyncMock()

        mon = Monitoring(template="{{ x }}", delivery=mock_delivery, name="test-dash")

        @mon.collector
        def x() -> str:
            return "data"

        await mon.run(deliver=True)
        mock_delivery.deliver.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_passes_name_to_delivery(self) -> None:
        """run() passes dashboard name to delivery."""
        mock_delivery = AsyncMock()
        mock_delivery.deliver = AsyncMock()

        mon = Monitoring(template="{{ x }}", delivery=mock_delivery, name="my-report")

        @mon.collector
        def x() -> str:
            return "data"

        await mon.run(deliver=True)
        call_args = mock_delivery.deliver.call_args
        assert call_args[0][1] == "my-report"  # name argument

    @pytest.mark.asyncio
    async def test_deliver_without_backend_raises(self) -> None:
        """_deliver() raises when no delivery configured."""
        mon = Monitoring(template="{{ x }}")

        @mon.collector
        def x() -> str:
            return "data"

        with pytest.raises(RuntimeError, match="No delivery backend"):
            await mon._deliver(MagicMock())


class TestMonitoringBuildDelivery:
    """Tests for _build_delivery static method."""

    def test_build_file_delivery(self) -> None:
        """_build_delivery creates FileDelivery."""
        from kstlib.monitoring.delivery import FileDelivery

        config = {"type": "file", "output_dir": "./reports", "max_files": 10}
        delivery = Monitoring._build_delivery(config)

        assert isinstance(delivery, FileDelivery)
        assert delivery.config.max_files == 10

    def test_build_mail_delivery_returns_deferred(self) -> None:
        """_build_delivery returns _DeferredMailDelivery for mail type."""
        config = {"type": "mail", "sender": "bot@example.com", "recipients": ["team@example.com"]}
        delivery = Monitoring._build_delivery(config)

        assert isinstance(delivery, _DeferredMailDelivery)

    def test_build_unknown_type_raises(self) -> None:
        """_build_delivery raises for unknown type."""
        config = {"type": "unknown"}

        with pytest.raises(ValueError, match="Unknown delivery type"):
            Monitoring._build_delivery(config)


class TestMonitoringFromConfig:
    """Tests for from_config() class method."""

    def test_from_config_missing_section_raises(self) -> None:
        """from_config raises when config section missing."""
        mock_config = MagicMock()
        mock_config.get = MagicMock(return_value={})

        with patch("kstlib.config.get_config", return_value=mock_config):
            with pytest.raises(ValueError, match="not found or empty"):
                Monitoring.from_config()

    def test_from_config_loads_template(self, tmp_path: pathlib.Path) -> None:
        """from_config loads template from config."""
        template_file = tmp_path / "test.html.j2"
        template_file.write_text("<p>from config</p>")

        mock_config = MagicMock()
        mock_config.get = MagicMock(
            return_value={
                "template_file": "test.html.j2",
                "name": "test-monitor",
            }
        )

        with patch("kstlib.config.get_config", return_value=mock_config):
            mon = Monitoring.from_config(base_dir=tmp_path)

        assert mon.name == "test-monitor"

    def test_from_config_with_inline_template(self) -> None:
        """from_config works with inline template."""
        mock_config = MagicMock()
        mock_config.get = MagicMock(
            return_value={
                "template": "<p>inline</p>",
                "inline_css": False,
                "fail_fast": True,
            }
        )

        with patch("kstlib.config.get_config", return_value=mock_config):
            mon = Monitoring.from_config()

        assert mon._inline_css is False
        assert mon._fail_fast is True

    def test_from_config_builds_file_delivery(self, tmp_path: pathlib.Path) -> None:
        """from_config builds FileDelivery when configured."""
        from kstlib.monitoring.delivery import FileDelivery

        template_file = tmp_path / "test.html.j2"
        template_file.write_text("<p>test</p>")

        mock_config = MagicMock()
        mock_config.get = MagicMock(
            return_value={
                "template_file": "test.html.j2",
                "delivery": {
                    "type": "file",
                    "output_dir": str(tmp_path / "reports"),
                },
            }
        )

        with patch("kstlib.config.get_config", return_value=mock_config):
            mon = Monitoring.from_config(base_dir=tmp_path)

        assert isinstance(mon._delivery, FileDelivery)

    def test_from_config_falls_back_to_load_config(self) -> None:
        """from_config calls load_config if get_config fails."""
        mock_config = MagicMock()
        mock_config.get = MagicMock(return_value={"template": "<p>loaded</p>"})

        with (
            patch("kstlib.config.get_config", side_effect=Exception("not loaded")),
            patch("kstlib.config.load_config", return_value=mock_config),
        ):
            mon = Monitoring.from_config()

        assert mon is not None


class TestDeferredMailDelivery:
    """Tests for _DeferredMailDelivery placeholder class."""

    def test_init_stores_config(self) -> None:
        """_DeferredMailDelivery stores config."""
        config = {"sender": "bot@example.com", "recipients": ["team@example.com"]}
        deferred = _DeferredMailDelivery(config)

        assert deferred._config == config

    @pytest.mark.asyncio
    async def test_build_creates_mail_delivery(self) -> None:
        """build() creates MailDelivery with OAuth transport."""
        from kstlib.monitoring.delivery import MailDelivery

        config = {
            "sender": "bot@example.com",
            "recipients": ["team@example.com"],
            "cc": ["cc@example.com"],
            "subject_template": "Report: {name}",
        }
        deferred = _DeferredMailDelivery(config)

        # Mock OAuth provider
        mock_token = MagicMock()
        mock_token.is_expired = False

        mock_provider = MagicMock()
        mock_provider.get_token.return_value = mock_token

        with patch("kstlib.auth.OAuth2Provider") as mock_oauth:
            mock_oauth.from_config.return_value = mock_provider
            with patch("kstlib.mail.transports.GmailTransport"):
                delivery = await deferred.build()

        assert isinstance(delivery, MailDelivery)
        assert delivery.config.sender == "bot@example.com"

    @pytest.mark.asyncio
    async def test_build_raises_when_token_unavailable(self) -> None:
        """build() raises when OAuth token unavailable."""
        config = {"sender": "bot@example.com", "recipients": ["team@example.com"]}
        deferred = _DeferredMailDelivery(config)

        mock_provider = MagicMock()
        mock_provider.get_token.return_value = None

        with (
            patch("kstlib.auth.OAuth2Provider") as mock_oauth,
            pytest.raises(RuntimeError, match="token not available"),
        ):
            mock_oauth.from_config.return_value = mock_provider
            await deferred.build()

    @pytest.mark.asyncio
    async def test_build_raises_when_token_expired(self) -> None:
        """build() raises when OAuth token is expired."""
        config = {"sender": "bot@example.com", "recipients": ["team@example.com"]}
        deferred = _DeferredMailDelivery(config)

        mock_token = MagicMock()
        mock_token.is_expired = True

        mock_provider = MagicMock()
        mock_provider.get_token.return_value = mock_token

        with (
            patch("kstlib.auth.OAuth2Provider") as mock_oauth,
            pytest.raises(RuntimeError, match="expired"),
        ):
            mock_oauth.from_config.return_value = mock_provider
            await deferred.build()


class TestMonitoringDeferredDelivery:
    """Tests for deferred mail delivery integration."""

    @pytest.mark.asyncio
    async def test_run_builds_deferred_delivery(self) -> None:
        """run() builds deferred delivery before calling it."""
        mock_built_delivery = AsyncMock()
        mock_built_delivery.deliver = AsyncMock()

        deferred = _DeferredMailDelivery({"sender": "bot@example.com", "recipients": ["team@example.com"]})

        mon = Monitoring(template="{{ x }}", delivery=deferred)

        @mon.collector
        def x() -> str:
            return "test"

        with patch.object(deferred, "build", new=AsyncMock(return_value=mock_built_delivery)) as mock_build:
            await mon.run(deliver=True)

            mock_build.assert_called_once()
            mock_built_delivery.deliver.assert_called_once()


class TestMonitoringNameProperty:
    """Tests for name property."""

    def test_name_returns_configured_name(self) -> None:
        """name property returns the configured name."""
        mon = Monitoring(template="<p>test</p>", name="my-dashboard")
        assert mon.name == "my-dashboard"

    def test_name_default_is_monitoring(self) -> None:
        """name defaults to 'monitoring'."""
        mon = Monitoring(template="<p>test</p>")
        assert mon.name == "monitoring"
