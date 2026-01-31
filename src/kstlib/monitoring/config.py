"""Configuration loader for monitoring dashboards.

This module provides tools to load monitoring configurations from YAML files,
with auto-discovery of ``*.monitor.yml`` files in specified directories.

Examples:
    Load a single monitoring config:

    >>> from kstlib.monitoring.config import load_monitoring_config
    >>> config = load_monitoring_config("dashboard.monitor.yml")  # doctest: +SKIP
    >>> service = config.to_service()  # doctest: +SKIP

    Discover all monitoring configs in a directory:

    >>> from kstlib.monitoring.config import discover_monitoring_configs
    >>> configs = discover_monitoring_configs("./configs")  # doctest: +SKIP
    >>> for name, config in configs.items():  # doctest: +SKIP
    ...     print(f"Found: {name}")  # doctest: +SKIP
"""

from __future__ import annotations

import importlib
import pathlib
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from kstlib.monitoring.exceptions import MonitoringConfigError
from kstlib.monitoring.service import Collector, MonitoringService

# File pattern for monitoring configs
MONITORING_CONFIG_PATTERN = "*.monitor.yml"
MONITORING_CONFIG_SUFFIX = ".monitor.yml"

# Deep defense: Security limits
MAX_CONFIG_FILE_SIZE = 1024 * 1024  # 1 MB max config file size
MAX_COLLECTORS = 100  # Maximum number of collectors per config
MAX_NAME_LENGTH = 128  # Maximum length for names (config name, collector names)
MAX_TEMPLATE_SIZE = 512 * 1024  # 512 KB max template size

# Module import restrictions for callable collectors
BLOCKED_MODULE_PREFIXES = (
    "os.",
    "sys.",
    "subprocess",
    "shutil",
    "socket",
    "pickle",
    "marshal",
    "__",
)
ALLOWED_MODULE_PATTERN = r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*$"


class MonitoringConfigFileNotFoundError(MonitoringConfigError, FileNotFoundError):
    """Monitoring configuration file not found."""


class MonitoringConfigFormatError(MonitoringConfigError, ValueError):
    """Invalid monitoring configuration format."""


class MonitoringConfigCollectorError(MonitoringConfigError):
    """Error loading a collector from configuration."""


@dataclass
class CollectorConfig:
    """Configuration for a single collector.

    Attributes:
        name: Name of the collector (used as template variable).
        collector_type: Type of collector ("static", "callable", "env").
        value: Static value (for type="static").
        module: Module path (for type="callable").
        function: Function name (for type="callable").
        env_var: Environment variable name (for type="env").
        default: Default value if env var not set (for type="env").
    """

    name: str
    collector_type: str = "static"
    value: Any = None
    module: str | None = None
    function: str | None = None
    env_var: str | None = None
    default: Any = None

    def to_collector(self) -> Collector:
        """Convert config to a collector callable.

        Returns:
            Callable that can be used as a MonitoringService collector.

        Raises:
            MonitoringConfigCollectorError: If collector cannot be created.
        """
        if self.collector_type == "static":
            return self._create_static_collector()
        if self.collector_type == "callable":
            return self._create_callable_collector()
        if self.collector_type == "env":
            return self._create_env_collector()
        raise MonitoringConfigCollectorError(f"Unknown collector type: {self.collector_type}")

    def _create_static_collector(self) -> Collector:
        """Create a static value collector."""
        value = self.value

        def collector() -> Any:
            return value

        return collector

    def _create_callable_collector(self) -> Collector:
        """Create a collector from a module.function reference."""
        if not self.module or not self.function:
            raise MonitoringConfigCollectorError(
                f"Collector '{self.name}' type='callable' requires 'module' and 'function'"
            )
        # Deep defense: Validate module name format
        if not re.match(ALLOWED_MODULE_PATTERN, self.module):
            raise MonitoringConfigCollectorError(f"Invalid module name format: '{self.module}'")
        # Deep defense: Block dangerous modules
        for prefix in BLOCKED_MODULE_PREFIXES:
            if self.module.startswith(prefix) or self.module == prefix.rstrip("."):
                raise MonitoringConfigCollectorError(f"Module '{self.module}' is blocked for security reasons")
        try:
            mod = importlib.import_module(self.module)
            func: Collector = getattr(mod, self.function)
            if not callable(func):
                raise MonitoringConfigCollectorError(f"'{self.module}.{self.function}' is not callable")
            return func
        except ImportError as e:
            raise MonitoringConfigCollectorError(f"Cannot import module '{self.module}': {e}") from e
        except AttributeError as e:
            raise MonitoringConfigCollectorError(f"Function '{self.function}' not found in '{self.module}': {e}") from e

    def _create_env_collector(self) -> Collector:
        """Create a collector that reads from environment variable."""
        import os

        env_var = self.env_var
        default = self.default
        name = self.name

        if not env_var:
            raise MonitoringConfigCollectorError(f"Collector '{name}' type='env' requires 'env_var'")

        def collector() -> Any:
            return os.environ.get(env_var, default)

        return collector


@dataclass
class MonitoringConfig:
    """Parsed monitoring configuration.

    Attributes:
        name: Dashboard name (defaults to filename without extension).
        template: Jinja2 template string for rendering.
        collectors: List of collector configurations.
        inline_css: Whether to use inline CSS (default True).
        fail_fast: Whether to fail on first collector error (default True).
        source_path: Path to the source config file (if loaded from file).
        metadata: Additional metadata from the config file.
    """

    name: str
    template: str
    collectors: list[CollectorConfig] = field(default_factory=list)
    inline_css: bool = True
    fail_fast: bool = True
    source_path: pathlib.Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_service(self) -> MonitoringService:
        """Create a MonitoringService from this configuration.

        Returns:
            Configured MonitoringService instance.

        Raises:
            MonitoringConfigCollectorError: If any collector cannot be created.
        """
        collectors: dict[str, Collector] = {}
        for collector_config in self.collectors:
            collectors[collector_config.name] = collector_config.to_collector()

        return MonitoringService(
            template=self.template,
            collectors=collectors,
            inline_css=self.inline_css,
            fail_fast=self.fail_fast,
        )

    @classmethod
    def _parse_collectors(cls, collectors_data: Any) -> list[CollectorConfig]:
        """Parse collectors from config data with validation."""
        if not isinstance(collectors_data, dict):
            raise MonitoringConfigFormatError("'collectors' must be a dictionary mapping names to collector configs")

        # Deep defense: Limit number of collectors
        if len(collectors_data) > MAX_COLLECTORS:
            raise MonitoringConfigFormatError(f"Too many collectors ({len(collectors_data)} > {MAX_COLLECTORS})")

        collectors: list[CollectorConfig] = []
        for name, collector_data in collectors_data.items():
            # Deep defense: Validate collector name length
            if len(str(name)) > MAX_NAME_LENGTH:
                raise MonitoringConfigFormatError(
                    f"Collector name '{name[:20]}...' exceeds maximum length ({MAX_NAME_LENGTH})"
                )
            if not isinstance(collector_data, dict):
                # Simple static value
                collectors.append(CollectorConfig(name=name, collector_type="static", value=collector_data))
            else:
                collectors.append(
                    CollectorConfig(
                        name=name,
                        collector_type=collector_data.get("type", "static"),
                        value=collector_data.get("value"),
                        module=collector_data.get("module"),
                        function=collector_data.get("function"),
                        env_var=collector_data.get("env_var"),
                        default=collector_data.get("default"),
                    )
                )
        return collectors

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        source_path: pathlib.Path | None = None,
    ) -> MonitoringConfig:
        """Create a MonitoringConfig from a dictionary.

        Args:
            data: Configuration dictionary.
            source_path: Optional path to source file.

        Returns:
            Parsed MonitoringConfig.

        Raises:
            MonitoringConfigFormatError: If required fields are missing.
        """
        # Validate required fields
        if "template" not in data:
            raise MonitoringConfigFormatError("Monitoring config must have a 'template' field")

        # Deep defense: Validate template size
        template = data["template"]
        if not isinstance(template, str):
            raise MonitoringConfigFormatError("'template' must be a string")
        if len(template) > MAX_TEMPLATE_SIZE:
            raise MonitoringConfigFormatError(f"Template exceeds maximum size ({MAX_TEMPLATE_SIZE} bytes)")

        # Deep defense: Validate config name length
        config_name = data.get("name")
        if config_name and len(str(config_name)) > MAX_NAME_LENGTH:
            raise MonitoringConfigFormatError(f"Config name exceeds maximum length ({MAX_NAME_LENGTH})")

        # Parse collectors
        collectors = cls._parse_collectors(data.get("collectors", {}))

        # Determine name
        name = data.get("name")
        if not name and source_path:
            # Use filename without .monitor.yml suffix
            name = source_path.name
            name = name.removesuffix(MONITORING_CONFIG_SUFFIX)

        # Extract known fields for metadata
        known_fields = {
            "name",
            "template",
            "collectors",
            "inline_css",
            "fail_fast",
        }
        metadata = {k: v for k, v in data.items() if k not in known_fields}

        return cls(
            name=name or "unnamed",
            template=data["template"],
            collectors=collectors,
            inline_css=data.get("inline_css", True),
            fail_fast=data.get("fail_fast", True),
            source_path=source_path,
            metadata=metadata,
        )


def load_monitoring_config(
    path: str | pathlib.Path,
    *,
    encoding: str = "utf-8",
) -> MonitoringConfig:
    """Load a monitoring configuration from a YAML file.

    Args:
        path: Path to the monitoring config file.
        encoding: File encoding (default UTF-8).

    Returns:
        Parsed MonitoringConfig.

    Raises:
        MonitoringConfigFileNotFoundError: If file does not exist.
        MonitoringConfigFormatError: If file format is invalid.

    Examples:
        >>> config = load_monitoring_config("dashboard.monitor.yml")  # doctest: +SKIP
        >>> service = config.to_service()  # doctest: +SKIP
        >>> result = service.run_sync()  # doctest: +SKIP
    """
    path = pathlib.Path(path)
    if not path.is_file():
        raise MonitoringConfigFileNotFoundError(f"Config file not found: {path}")

    # Deep defense: Check file size before reading
    file_size = path.stat().st_size
    if file_size > MAX_CONFIG_FILE_SIZE:
        raise MonitoringConfigFormatError(f"Config file too large ({file_size} > {MAX_CONFIG_FILE_SIZE} bytes)")

    try:
        with path.open("r", encoding=encoding) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise MonitoringConfigFormatError(f"Invalid YAML in {path}: {e}") from e

    if not isinstance(data, dict):
        raise MonitoringConfigFormatError(f"Monitoring config must be a YAML dictionary, got {type(data).__name__}")

    return MonitoringConfig.from_dict(data, source_path=path.resolve())


def discover_monitoring_configs(
    directory: str | pathlib.Path,
    *,
    recursive: bool = False,
    encoding: str = "utf-8",
) -> dict[str, MonitoringConfig]:
    """Discover and load all monitoring configs in a directory.

    Searches for files matching ``*.monitor.yml`` pattern.

    Args:
        directory: Directory to search.
        recursive: If True, search subdirectories recursively.
        encoding: File encoding (default UTF-8).

    Returns:
        Dictionary mapping config names to MonitoringConfig objects.

    Raises:
        FileNotFoundError: If directory does not exist.
        MonitoringConfigFormatError: If any config file is invalid.

    Examples:
        >>> configs = discover_monitoring_configs("./monitoring")  # doctest: +SKIP
        >>> for name, config in configs.items():  # doctest: +SKIP
        ...     print(f"Loaded: {name}")  # doctest: +SKIP
    """
    directory = pathlib.Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"Directory not found: {directory}")

    pattern = f"**/{MONITORING_CONFIG_PATTERN}" if recursive else MONITORING_CONFIG_PATTERN
    configs: dict[str, MonitoringConfig] = {}

    for config_path in directory.glob(pattern):
        config = load_monitoring_config(config_path, encoding=encoding)
        configs[config.name] = config

    return configs


def create_services_from_directory(
    directory: str | pathlib.Path,
    *,
    recursive: bool = False,
    encoding: str = "utf-8",
) -> dict[str, MonitoringService]:
    """Discover configs and create MonitoringService instances.

    Convenience function that combines discover_monitoring_configs
    with to_service() for each config.

    Args:
        directory: Directory to search for ``*.monitor.yml`` files.
        recursive: If True, search subdirectories recursively.
        encoding: File encoding (default UTF-8).

    Returns:
        Dictionary mapping config names to MonitoringService instances.

    Examples:
        >>> services = create_services_from_directory("./monitoring")  # doctest: +SKIP
        >>> for name, service in services.items():  # doctest: +SKIP
        ...     result = service.run_sync()  # doctest: +SKIP
        ...     print(f"{name}: {result.success}")  # doctest: +SKIP
    """
    configs = discover_monitoring_configs(directory, recursive=recursive, encoding=encoding)
    return {name: config.to_service() for name, config in configs.items()}


__all__ = [
    "CollectorConfig",
    "MonitoringConfig",
    "MonitoringConfigCollectorError",
    "MonitoringConfigFileNotFoundError",
    "MonitoringConfigFormatError",
    "create_services_from_directory",
    "discover_monitoring_configs",
    "load_monitoring_config",
]
