"""Tests for kstlib.monitoring.config module."""

from __future__ import annotations

import os
import pathlib
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from kstlib.monitoring import (
    CollectorConfig,
    MonitoringConfig,
    MonitoringConfigCollectorError,
    MonitoringConfigFileNotFoundError,
    MonitoringConfigFormatError,
    MonitoringService,
    create_services_from_directory,
    discover_monitoring_configs,
    load_monitoring_config,
)

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture
def temp_config_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a temporary directory for config files."""
    return tmp_path


@pytest.fixture
def simple_config_file(temp_config_dir: pathlib.Path) -> pathlib.Path:
    """Create a simple monitoring config file."""
    config_path = temp_config_dir / "simple.monitor.yml"
    config_path.write_text(
        """
name: simple-dashboard
template: "<p>{{ message }}</p>"
collectors:
  message: "Hello World"
"""
    )
    return config_path


@pytest.fixture
def full_config_file(temp_config_dir: pathlib.Path) -> pathlib.Path:
    """Create a monitoring config with all options."""
    config_path = temp_config_dir / "full.monitor.yml"
    config_path.write_text(
        """
name: full-dashboard
template: |
  <h1>{{ title }}</h1>
  <p>{{ static_value }}</p>
inline_css: false
fail_fast: false
collectors:
  title:
    type: static
    value: "Dashboard Title"
  static_value: "Simple static"
metadata_field: "extra data"
"""
    )
    return config_path


class TestCollectorConfig:
    """Tests for CollectorConfig dataclass."""

    def test_static_collector_default_type(self) -> None:
        """Static is the default collector type."""
        config = CollectorConfig(name="test", value="hello")
        assert config.collector_type == "static"

    def test_static_collector_to_collector(self) -> None:
        """Static collector returns the configured value."""
        config = CollectorConfig(name="test", collector_type="static", value=42)
        collector = config.to_collector()
        assert collector() == 42

    def test_static_collector_with_none_value(self) -> None:
        """Static collector can return None."""
        config = CollectorConfig(name="test", collector_type="static", value=None)
        collector = config.to_collector()
        assert collector() is None

    def test_static_collector_with_dict_value(self) -> None:
        """Static collector can return complex objects."""
        data = {"key": "value", "nested": {"a": 1}}
        config = CollectorConfig(name="test", collector_type="static", value=data)
        collector = config.to_collector()
        assert collector() == data

    def test_env_collector_reads_env_var(self) -> None:
        """Env collector reads from environment variable."""
        config = CollectorConfig(name="test", collector_type="env", env_var="TEST_VAR_123")
        with patch.dict(os.environ, {"TEST_VAR_123": "test_value"}):
            collector = config.to_collector()
            assert collector() == "test_value"

    def test_env_collector_with_default(self) -> None:
        """Env collector uses default when var not set."""
        config = CollectorConfig(
            name="test",
            collector_type="env",
            env_var="NONEXISTENT_VAR_XYZ",
            default="fallback",
        )
        collector = config.to_collector()
        assert collector() == "fallback"

    def test_env_collector_missing_env_var_raises(self) -> None:
        """Env collector without env_var raises error."""
        config = CollectorConfig(name="test", collector_type="env")
        with pytest.raises(MonitoringConfigCollectorError) as exc_info:
            config.to_collector()
        assert "env_var" in str(exc_info.value)

    def test_callable_collector_missing_module_raises(self) -> None:
        """Callable collector without module raises error."""
        config = CollectorConfig(name="test", collector_type="callable", function="some_func")
        with pytest.raises(MonitoringConfigCollectorError) as exc_info:
            config.to_collector()
        assert "module" in str(exc_info.value)

    def test_callable_collector_missing_function_raises(self) -> None:
        """Callable collector without function raises error."""
        config = CollectorConfig(name="test", collector_type="callable", module="some_module")
        with pytest.raises(MonitoringConfigCollectorError) as exc_info:
            config.to_collector()
        assert "function" in str(exc_info.value)

    def test_callable_collector_import_error(self) -> None:
        """Callable collector with invalid module raises error."""
        config = CollectorConfig(
            name="test",
            collector_type="callable",
            module="nonexistent_module_xyz",
            function="func",
        )
        with pytest.raises(MonitoringConfigCollectorError) as exc_info:
            config.to_collector()
        assert "import" in str(exc_info.value).lower()

    def test_callable_collector_attribute_error(self) -> None:
        """Callable collector with invalid function raises error."""
        config = CollectorConfig(
            name="test",
            collector_type="callable",
            module="datetime",
            function="nonexistent_function_xyz",
        )
        with pytest.raises(MonitoringConfigCollectorError) as exc_info:
            config.to_collector()
        assert "not found" in str(exc_info.value)

    def test_callable_collector_valid_reference(self) -> None:
        """Callable collector with valid reference works."""
        config = CollectorConfig(
            name="test",
            collector_type="callable",
            module="json",
            function="dumps",
        )
        collector = config.to_collector()
        assert callable(collector)

    def test_unknown_collector_type_raises(self) -> None:
        """Unknown collector type raises error."""
        config = CollectorConfig(name="test", collector_type="unknown")
        with pytest.raises(MonitoringConfigCollectorError) as exc_info:
            config.to_collector()
        assert "unknown" in str(exc_info.value).lower()


class TestMonitoringConfigFromDict:
    """Tests for MonitoringConfig.from_dict()."""

    def test_minimal_config(self) -> None:
        """Config with only template is valid."""
        config = MonitoringConfig.from_dict({"template": "<p>test</p>"})
        assert config.template == "<p>test</p>"
        assert config.name == "unnamed"
        assert config.collectors == []

    def test_missing_template_raises(self) -> None:
        """Config without template raises error."""
        with pytest.raises(MonitoringConfigFormatError) as exc_info:
            MonitoringConfig.from_dict({"name": "test"})
        assert "template" in str(exc_info.value)

    def test_name_from_config(self) -> None:
        """Name is read from config."""
        config = MonitoringConfig.from_dict({"name": "my-dashboard", "template": "<p>test</p>"})
        assert config.name == "my-dashboard"

    def test_name_from_source_path(self) -> None:
        """Name is derived from source path if not in config."""
        config = MonitoringConfig.from_dict(
            {"template": "<p>test</p>"},
            source_path=pathlib.Path("/path/to/dashboard.monitor.yml"),
        )
        assert config.name == "dashboard"

    def test_inline_css_default_true(self) -> None:
        """inline_css defaults to True."""
        config = MonitoringConfig.from_dict({"template": "<p>test</p>"})
        assert config.inline_css is True

    def test_inline_css_false(self) -> None:
        """inline_css can be set to False."""
        config = MonitoringConfig.from_dict({"template": "<p>test</p>", "inline_css": False})
        assert config.inline_css is False

    def test_fail_fast_default_true(self) -> None:
        """fail_fast defaults to True."""
        config = MonitoringConfig.from_dict({"template": "<p>test</p>"})
        assert config.fail_fast is True

    def test_fail_fast_false(self) -> None:
        """fail_fast can be set to False."""
        config = MonitoringConfig.from_dict({"template": "<p>test</p>", "fail_fast": False})
        assert config.fail_fast is False

    def test_simple_collector_values(self) -> None:
        """Simple values become static collectors."""
        config = MonitoringConfig.from_dict(
            {
                "template": "<p>{{ msg }}</p>",
                "collectors": {"msg": "hello", "count": 42},
            }
        )
        assert len(config.collectors) == 2
        names = {c.name for c in config.collectors}
        assert names == {"msg", "count"}

    def test_collector_with_type(self) -> None:
        """Collector with explicit type is parsed."""
        config = MonitoringConfig.from_dict(
            {
                "template": "<p>{{ val }}</p>",
                "collectors": {
                    "val": {"type": "static", "value": "test"},
                },
            }
        )
        assert len(config.collectors) == 1
        assert config.collectors[0].collector_type == "static"
        assert config.collectors[0].value == "test"

    def test_collectors_not_dict_raises(self) -> None:
        """collectors as non-dict raises error."""
        with pytest.raises(MonitoringConfigFormatError) as exc_info:
            MonitoringConfig.from_dict({"template": "<p>test</p>", "collectors": ["a", "b"]})
        assert "dictionary" in str(exc_info.value)

    def test_metadata_preserved(self) -> None:
        """Unknown fields are stored in metadata."""
        config = MonitoringConfig.from_dict(
            {
                "template": "<p>test</p>",
                "custom_field": "value",
                "another": 123,
            }
        )
        assert config.metadata == {"custom_field": "value", "another": 123}


class TestMonitoringConfigToService:
    """Tests for MonitoringConfig.to_service()."""

    def test_creates_service(self) -> None:
        """to_service() creates a MonitoringService."""
        config = MonitoringConfig(
            name="test",
            template="<p>{{ msg }}</p>",
            collectors=[CollectorConfig(name="msg", value="hello")],
        )
        service = config.to_service()
        assert isinstance(service, MonitoringService)

    def test_service_has_template(self) -> None:
        """Service has the configured template."""
        config = MonitoringConfig(name="test", template="<p>custom</p>")
        service = config.to_service()
        assert service.template == "<p>custom</p>"

    def test_service_has_collectors(self) -> None:
        """Service has the configured collectors."""
        config = MonitoringConfig(
            name="test",
            template="<p>{{ a }} {{ b }}</p>",
            collectors=[
                CollectorConfig(name="a", value=1),
                CollectorConfig(name="b", value=2),
            ],
        )
        service = config.to_service()
        assert set(service.collector_names) == {"a", "b"}

    def test_service_inline_css(self) -> None:
        """Service has inline_css setting."""
        config = MonitoringConfig(name="test", template="", inline_css=False)
        service = config.to_service()
        assert service.inline_css is False

    def test_service_runs_correctly(self) -> None:
        """Service created from config can run."""
        config = MonitoringConfig(
            name="test",
            template="<p>{{ msg }}</p>",
            collectors=[CollectorConfig(name="msg", value="hello")],
        )
        service = config.to_service()
        result = service.run_sync()
        assert "hello" in result.html


class TestLoadMonitoringConfig:
    """Tests for load_monitoring_config() function."""

    def test_load_simple_config(self, simple_config_file: pathlib.Path) -> None:
        """Load a simple config file."""
        config = load_monitoring_config(simple_config_file)
        assert config.name == "simple-dashboard"
        assert "{{ message }}" in config.template

    def test_load_full_config(self, full_config_file: pathlib.Path) -> None:
        """Load a config with all options."""
        config = load_monitoring_config(full_config_file)
        assert config.name == "full-dashboard"
        assert config.inline_css is False
        assert config.fail_fast is False
        assert "metadata_field" in config.metadata

    def test_load_string_path(self, simple_config_file: pathlib.Path) -> None:
        """Load from string path."""
        config = load_monitoring_config(str(simple_config_file))
        assert config.name == "simple-dashboard"

    def test_load_nonexistent_file_raises(self) -> None:
        """Loading nonexistent file raises error."""
        with pytest.raises(MonitoringConfigFileNotFoundError):
            load_monitoring_config("/nonexistent/path/config.monitor.yml")

    def test_load_invalid_yaml_raises(self, temp_config_dir: pathlib.Path) -> None:
        """Loading invalid YAML raises error."""
        bad_file = temp_config_dir / "bad.monitor.yml"
        bad_file.write_text("invalid: yaml: content: [")
        with pytest.raises(MonitoringConfigFormatError) as exc_info:
            load_monitoring_config(bad_file)
        assert "YAML" in str(exc_info.value)

    def test_load_non_dict_yaml_raises(self, temp_config_dir: pathlib.Path) -> None:
        """Loading YAML that's not a dict raises error."""
        bad_file = temp_config_dir / "list.monitor.yml"
        bad_file.write_text("- item1\n- item2")
        with pytest.raises(MonitoringConfigFormatError) as exc_info:
            load_monitoring_config(bad_file)
        assert "dictionary" in str(exc_info.value)

    def test_source_path_is_resolved(self, simple_config_file: pathlib.Path) -> None:
        """source_path is resolved to absolute path."""
        config = load_monitoring_config(simple_config_file)
        assert config.source_path is not None
        assert config.source_path.is_absolute()


class TestDiscoverMonitoringConfigs:
    """Tests for discover_monitoring_configs() function."""

    def test_discover_single_config(self, simple_config_file: pathlib.Path) -> None:
        """Discover a single config file."""
        configs = discover_monitoring_configs(simple_config_file.parent)
        assert len(configs) == 1
        assert "simple-dashboard" in configs

    def test_discover_multiple_configs(self, temp_config_dir: pathlib.Path) -> None:
        """Discover multiple config files."""
        (temp_config_dir / "first.monitor.yml").write_text("name: first\ntemplate: '<p>1</p>'")
        (temp_config_dir / "second.monitor.yml").write_text("name: second\ntemplate: '<p>2</p>'")
        configs = discover_monitoring_configs(temp_config_dir)
        assert len(configs) == 2
        assert "first" in configs
        assert "second" in configs

    def test_discover_ignores_non_monitor_files(self, temp_config_dir: pathlib.Path) -> None:
        """Only *.monitor.yml files are discovered."""
        (temp_config_dir / "valid.monitor.yml").write_text("name: valid\ntemplate: '<p>ok</p>'")
        (temp_config_dir / "other.yml").write_text("name: other\ntemplate: '<p>no</p>'")
        (temp_config_dir / "config.yaml").write_text("name: yaml\ntemplate: '<p>no</p>'")
        configs = discover_monitoring_configs(temp_config_dir)
        assert len(configs) == 1
        assert "valid" in configs

    def test_discover_nonexistent_dir_raises(self) -> None:
        """Discovering in nonexistent directory raises error."""
        with pytest.raises(FileNotFoundError):
            discover_monitoring_configs("/nonexistent/directory")

    def test_discover_recursive(self, temp_config_dir: pathlib.Path) -> None:
        """Recursive discovery finds configs in subdirectories."""
        subdir = temp_config_dir / "subdir"
        subdir.mkdir()
        (temp_config_dir / "root.monitor.yml").write_text("name: root\ntemplate: '<p>1</p>'")
        (subdir / "nested.monitor.yml").write_text("name: nested\ntemplate: '<p>2</p>'")

        # Non-recursive should only find root
        configs = discover_monitoring_configs(temp_config_dir, recursive=False)
        assert len(configs) == 1
        assert "root" in configs

        # Recursive should find both
        configs = discover_monitoring_configs(temp_config_dir, recursive=True)
        assert len(configs) == 2
        assert "root" in configs
        assert "nested" in configs

    def test_discover_empty_directory(self, temp_config_dir: pathlib.Path) -> None:
        """Discovering in empty directory returns empty dict."""
        configs = discover_monitoring_configs(temp_config_dir)
        assert configs == {}


class TestCreateServicesFromDirectory:
    """Tests for create_services_from_directory() function."""

    def test_creates_services(self, temp_config_dir: pathlib.Path) -> None:
        """Creates MonitoringService instances from configs."""
        (temp_config_dir / "test.monitor.yml").write_text(
            "name: test\ntemplate: '<p>{{ msg }}</p>'\ncollectors:\n  msg: hello"
        )
        services = create_services_from_directory(temp_config_dir)
        assert len(services) == 1
        assert "test" in services
        assert isinstance(services["test"], MonitoringService)

    def test_services_are_runnable(self, temp_config_dir: pathlib.Path) -> None:
        """Created services can run and produce output."""
        (temp_config_dir / "run.monitor.yml").write_text(
            "name: run\ntemplate: '<p>{{ val }}</p>'\ncollectors:\n  val: 42"
        )
        services = create_services_from_directory(temp_config_dir)
        result = services["run"].run_sync()
        assert "42" in result.html
        assert result.success


class TestEnvCollectorIntegration:
    """Integration tests for env collector type."""

    def test_env_collector_in_config_file(self, temp_config_dir: pathlib.Path) -> None:
        """Env collector works when loaded from file."""
        (temp_config_dir / "env.monitor.yml").write_text(
            """
name: env-test
template: "<p>{{ value }}</p>"
collectors:
  value:
    type: env
    env_var: TEST_MONITOR_VAR
    default: fallback
"""
        )
        config = load_monitoring_config(temp_config_dir / "env.monitor.yml")
        service = config.to_service()

        # Without env var set, uses default
        result = service.run_sync()
        assert "fallback" in result.html

        # With env var set, uses env value
        with patch.dict(os.environ, {"TEST_MONITOR_VAR": "from_env"}):
            result = service.run_sync()
            assert "from_env" in result.html


class TestDeepDefenseSecurity:
    """Tests for deep defense security hardening."""

    def test_blocked_module_os(self) -> None:
        """os module is blocked for callable collectors."""
        config = CollectorConfig(
            name="test",
            collector_type="callable",
            module="os",
            function="getcwd",
        )
        with pytest.raises(MonitoringConfigCollectorError) as exc_info:
            config.to_collector()
        assert "blocked" in str(exc_info.value).lower()

    def test_blocked_module_subprocess(self) -> None:
        """subprocess module is blocked for callable collectors."""
        config = CollectorConfig(
            name="test",
            collector_type="callable",
            module="subprocess",
            function="run",
        )
        with pytest.raises(MonitoringConfigCollectorError) as exc_info:
            config.to_collector()
        assert "blocked" in str(exc_info.value).lower()

    def test_blocked_module_sys(self) -> None:
        """sys module is blocked for callable collectors."""
        config = CollectorConfig(
            name="test",
            collector_type="callable",
            module="sys",
            function="exit",
        )
        with pytest.raises(MonitoringConfigCollectorError) as exc_info:
            config.to_collector()
        assert "blocked" in str(exc_info.value).lower()

    def test_blocked_module_os_path(self) -> None:
        """os.path is blocked (os. prefix)."""
        config = CollectorConfig(
            name="test",
            collector_type="callable",
            module="os.path",
            function="exists",
        )
        with pytest.raises(MonitoringConfigCollectorError) as exc_info:
            config.to_collector()
        assert "blocked" in str(exc_info.value).lower()

    def test_invalid_module_name_format(self) -> None:
        """Invalid module name format is rejected."""
        config = CollectorConfig(
            name="test",
            collector_type="callable",
            module="module..double.dot",
            function="func",
        )
        with pytest.raises(MonitoringConfigCollectorError) as exc_info:
            config.to_collector()
        assert "invalid" in str(exc_info.value).lower()

    def test_allowed_module_works(self) -> None:
        """Allowed modules (like datetime) work correctly."""
        config = CollectorConfig(
            name="test",
            collector_type="callable",
            module="datetime",
            function="datetime",
        )
        # Should not raise
        collector = config.to_collector()
        assert callable(collector)

    def test_too_many_collectors_raises(self) -> None:
        """Config with too many collectors is rejected."""
        collectors = {f"collector_{i}": "value" for i in range(150)}
        with pytest.raises(MonitoringConfigFormatError) as exc_info:
            MonitoringConfig.from_dict({"template": "<p>test</p>", "collectors": collectors})
        assert "too many" in str(exc_info.value).lower()

    def test_config_name_too_long_raises(self) -> None:
        """Config name exceeding max length is rejected."""
        with pytest.raises(MonitoringConfigFormatError) as exc_info:
            MonitoringConfig.from_dict({"template": "<p>test</p>", "name": "x" * 200})
        assert "length" in str(exc_info.value).lower()

    def test_collector_name_too_long_raises(self) -> None:
        """Collector name exceeding max length is rejected."""
        with pytest.raises(MonitoringConfigFormatError) as exc_info:
            MonitoringConfig.from_dict({"template": "<p>test</p>", "collectors": {"x" * 200: "value"}})
        assert "length" in str(exc_info.value).lower()

    def test_template_too_large_raises(self) -> None:
        """Template exceeding max size is rejected."""
        large_template = "<p>" + "x" * (600 * 1024) + "</p>"  # > 512KB
        with pytest.raises(MonitoringConfigFormatError) as exc_info:
            MonitoringConfig.from_dict({"template": large_template})
        assert "size" in str(exc_info.value).lower()

    def test_file_too_large_raises(self, temp_config_dir: pathlib.Path) -> None:
        """Config file exceeding max size is rejected."""
        large_file = temp_config_dir / "large.monitor.yml"
        # Create file larger than 1MB
        large_file.write_text("template: '<p>" + "x" * (1024 * 1024 + 100) + "</p>'")
        with pytest.raises(MonitoringConfigFormatError) as exc_info:
            load_monitoring_config(large_file)
        assert "large" in str(exc_info.value).lower()

    def test_non_string_template_raises(self) -> None:
        """Non-string template is rejected."""
        with pytest.raises(MonitoringConfigFormatError) as exc_info:
            MonitoringConfig.from_dict({"template": ["list", "of", "items"]})
        assert "string" in str(exc_info.value).lower()
