"""
Cascading configuration loader for kstlib.

Features:
- Object-oriented ConfigLoader class for clean architecture
- Dot notation everywhere (using Box)
- 'include' key for recursive multi-format includes (yaml, toml, JSON, ini)
- Deep merge for overrides
- Fallback to package default config
- Backward-compatible functional API

Examples:
    Modern class-based approach (recommended)::

        >>> from kstlib.config import ConfigLoader  # doctest: +SKIP
        >>> config = ConfigLoader.from_file("config.yml")  # doctest: +SKIP
        >>> config = ConfigLoader(strict_format=True).load_from_file("config.yml")  # doctest: +SKIP

    Functional API (backward compatible)::

        >>> from kstlib.config import load_from_file, get_config  # doctest: +SKIP
        >>> config = load_from_file("config.yml")  # doctest: +SKIP
        >>> config = get_config()  # doctest: +SKIP
"""

from __future__ import annotations

import json
import os
import pathlib
import time
from configparser import ConfigParser
from dataclasses import dataclass
from typing import Any, Literal, cast

import yaml
from box import Box

try:
    import tomli
except ImportError:
    tomli = None  # type: ignore[assignment]

from kstlib.config.exceptions import (
    ConfigCircularIncludeError,
    ConfigFileNotFoundError,
    ConfigFormatError,
    ConfigIncludeDepthError,
    ConfigNotLoadedError,
)
from kstlib.utils.dict import deep_merge

CONFIG_FILENAME = "kstlib.conf.yml"
USER_CONFIG_DIR = ".config"
DEFAULT_ENCODING = "utf-8"

# Deep defense: Maximum include depth to prevent resource exhaustion
MAX_INCLUDE_DEPTH = 10


# ============================================================================
# Internal loader functions (format-specific)
# ============================================================================


def _load_yaml_file(path: pathlib.Path, encoding: str = DEFAULT_ENCODING) -> dict[str, Any]:
    """
    Load a YAML configuration file and return its contents as a dictionary.

    Args:
        path: Path to the YAML file.
        encoding: File encoding.

    Returns:
        dict: Parsed YAML content.

    Raises:
        ConfigFileNotFoundError: If the file does not exist.
    """
    if not path.is_file():
        raise ConfigFileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding=encoding) as f:
        return yaml.safe_load(f) or {}


def _load_toml_file(path: pathlib.Path) -> dict[str, Any]:
    """
    Load a TOML configuration file and return its contents as a dictionary.

    Args:
        path: Path to the TOML file.

    Returns:
        dict: Parsed TOML content.

    Raises:
        ConfigFileNotFoundError: If the file does not exist.
        ConfigFormatError: If tomli package is not installed.
    """
    if not path.is_file():
        raise ConfigFileNotFoundError(f"Config file not found: {path}")
    if tomli is None:
        raise ConfigFormatError("TOML support requires the 'tomli' package. Install it with: pip install tomli")
    with path.open("rb") as f:
        return tomli.load(f)


def _load_json_file(path: pathlib.Path, encoding: str = DEFAULT_ENCODING) -> dict[str, Any]:
    """
    Load a JSON configuration file and return its contents as a dictionary.

    Args:
        path: Path to the JSON file.
        encoding: File encoding.

    Returns:
        dict: Parsed JSON content.

    Raises:
        ConfigFileNotFoundError: If the file does not exist.
    """
    if not path.is_file():
        raise ConfigFileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding=encoding) as f:
        data = json.load(f)
        return data if isinstance(data, dict) else {}


def _load_ini_file(path: pathlib.Path, encoding: str = DEFAULT_ENCODING) -> dict[str, Any]:
    """
    Load an INI configuration file and return its contents as a dictionary.

    Args:
        path: Path to the INI file.
        encoding: File encoding.

    Returns:
        dict: Parsed INI content.

    Raises:
        ConfigFileNotFoundError: If the file does not exist.
    """
    if not path.is_file():
        raise ConfigFileNotFoundError(f"Config file not found: {path}")
    parser = ConfigParser()
    parser.read(path, encoding=encoding)
    return {s: dict(parser.items(s)) for s in parser.sections()}


def _try_sops_decrypt(path: pathlib.Path) -> str | None:
    """Attempt SOPS decryption, returning content or None on failure."""
    # Lazy import to avoid circular dependencies
    import logging

    from kstlib.config.exceptions import ConfigSopsError, ConfigSopsNotAvailableError
    from kstlib.config.sops import get_decryptor

    _logger = logging.getLogger(__name__)
    try:
        content = get_decryptor().decrypt_file(path)
        _logger.debug("Decrypted SOPS file: %s", path.name)
        return content
    except ConfigSopsNotAvailableError as exc:
        _logger.warning("SOPS not available, loading raw: %s", exc)
    except ConfigSopsError as exc:
        _logger.warning("SOPS decryption failed: %s", exc)
    return None


def _parse_content_by_format(
    content: str,
    ext: str,
    path: pathlib.Path,
    encoding: str,
) -> dict[str, Any]:
    """Parse decrypted content based on file extension."""
    if ext in (".yml", ".yaml"):
        return yaml.safe_load(content) or {}
    if ext == ".toml":
        if tomli is None:
            raise ConfigFormatError("TOML support requires the 'tomli' package. Install it with: pip install tomli")
        return tomli.loads(content)
    if ext == ".json":
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else {}
    if ext == ".ini":
        parser = ConfigParser()
        parser.read_string(content)
        return {s: dict(parser.items(s)) for s in parser.sections()}
    raise ConfigFormatError(f"Unsupported config file type: {path}")


def _load_file_by_format(
    path: pathlib.Path,
    ext: str,
    encoding: str,
) -> dict[str, Any]:
    """Load file directly based on extension."""
    if ext in (".yml", ".yaml"):
        return _load_yaml_file(path, encoding)
    if ext == ".toml":
        return _load_toml_file(path)
    if ext == ".json":
        return _load_json_file(path, encoding)
    if ext == ".ini":
        return _load_ini_file(path, encoding)
    raise ConfigFormatError(f"Unsupported config file type: {path}")


def _warn_encrypted_values(data: dict[str, Any], path: pathlib.Path) -> None:
    """Warn if ENC[...] values found in non-decrypted data."""
    import logging

    from kstlib.config.sops import has_encrypted_values

    enc_keys = has_encrypted_values(data)
    if enc_keys:
        _logger = logging.getLogger(__name__)
        _logger.warning(
            "Found ENC[...] values at %s in %s. Use a .sops.yml file for auto-decryption.",
            enc_keys[:3],
            path.name,
        )


def _load_any_config_file(
    path: pathlib.Path,
    encoding: str = DEFAULT_ENCODING,
    *,
    sops_decrypt: bool = True,
) -> dict[str, Any]:
    """
    Load a configuration file in any supported format (YAML, TOML, JSON, INI).

    Supports automatic SOPS decryption for files with .sops.* extensions.

    Args:
        path: Path to the configuration file.
        encoding: File encoding.
        sops_decrypt: If True, auto-decrypt .sops.* files via SOPS binary.

    Returns:
        dict: Parsed content of the file.

    Raises:
        ConfigFormatError: If the file extension is not supported.
    """
    from kstlib.config.sops import get_real_extension, is_sops_file

    content: str | None = None
    is_sops = is_sops_file(path)

    # Handle SOPS-encrypted files
    if sops_decrypt and is_sops:
        content = _try_sops_decrypt(path)

    # Get real extension for parsing (strips .sops prefix)
    ext = get_real_extension(path) if is_sops else path.suffix.lower()

    # Parse content or load file
    if content is not None:
        data = _parse_content_by_format(content, ext, path, encoding)
    else:
        data = _load_file_by_format(path, ext, encoding)
        _warn_encrypted_values(data, path)

    return data


def _load_with_includes(
    path: pathlib.Path,
    loaded_paths: set[pathlib.Path] | None = None,
    strict_format: bool = False,
    encoding: str = DEFAULT_ENCODING,
    *,
    sops_decrypt: bool = True,
    _depth: int = 0,
) -> dict[str, Any]:
    """
    Recursively load a config file and all files specified in its 'include' key.

    Args:
        path: Path to the main config file.
        loaded_paths: Set of already loaded paths to prevent cycles.
        strict_format: If True, included files must have the same format as parent file.
        encoding: File encoding.
        sops_decrypt: If True, auto-decrypt .sops.* files via SOPS binary.
        _depth: Internal counter for recursion depth (do not set manually).

    Returns:
        Final merged configuration dictionary.

    Raises:
        ConfigCircularIncludeError: If a circular include is detected.
        ConfigIncludeDepthError: If include depth exceeds MAX_INCLUDE_DEPTH.
        ConfigFormatError: If format mismatch occurs (strict_format=True).
    """
    # Lazy import for SOPS extension detection
    from kstlib.config.sops import get_real_extension, is_sops_file

    # Deep defense: prevent excessive recursion
    if _depth > MAX_INCLUDE_DEPTH:
        raise ConfigIncludeDepthError(
            f"Include depth exceeds maximum ({MAX_INCLUDE_DEPTH}). "
            "Check for deeply nested includes or misconfiguration."
        )

    if loaded_paths is None:
        loaded_paths = set()
    path = path.resolve()
    if path in loaded_paths:
        raise ConfigCircularIncludeError(f"Circular include detected for {path}")
    loaded_paths.add(path)

    data = _load_any_config_file(path, encoding, sops_decrypt=sops_decrypt)
    includes = data.pop("include", [])
    if isinstance(includes, str):
        includes = [includes]

    # Get real extension (handles .sops.yml -> .yml)
    parent_ext = get_real_extension(path) if is_sops_file(path) else path.suffix.lower()
    merged: dict[str, Any] = {}
    for inc in includes:
        inc_path = (path.parent / inc).resolve()

        # Validate format consistency if strict mode enabled
        if strict_format:
            inc_ext = get_real_extension(inc_path) if is_sops_file(inc_path) else inc_path.suffix.lower()
            if inc_ext != parent_ext:
                raise ConfigFormatError(
                    f"Include format mismatch: parent is {parent_ext}, include is {inc_ext} (file: {inc_path})"
                )

        merged = deep_merge(
            merged,
            _load_with_includes(
                inc_path, loaded_paths, strict_format, encoding, sops_decrypt=sops_decrypt, _depth=_depth + 1
            ),
        )
    merged = deep_merge(merged, data)
    return merged


def _load_default_config(encoding: str = DEFAULT_ENCODING) -> dict[str, Any]:
    """
    Load the package's default configuration.

    Args:
        encoding: File encoding.

    Returns:
        dict: Default configuration as parsed from kstlib.conf.yml, or empty dict if missing.
    """
    config_path = pathlib.Path(__file__).resolve().parent.parent / CONFIG_FILENAME
    if not config_path.is_file():
        return {}
    return _load_yaml_file(config_path, encoding)


# ============================================================================
# ConfigLoader Class (Modern OOP API)
# ============================================================================


AutoDiscoverySource = Literal["cascading", "env", "file"]


@dataclass(slots=True)
class AutoDiscoveryConfig:
    """Encapsulate auto-discovery options for ``ConfigLoader``."""

    enabled: bool
    source: AutoDiscoverySource
    filename: str
    env_var: str
    path: pathlib.Path | None


class ConfigLoader:
    """
    Configuration loader with support for multiple formats and sources.

    This class provides a clean, object-oriented interface for loading
    configuration from various sources with customizable behavior.

    Attributes:
        strict_format: If True, included files must match parent format.
        encoding: File encoding for text-based formats.
        sops_decrypt: If True, auto-decrypt .sops.* files via SOPS binary.
        auto_discovery: Whether the constructor should immediately hydrate the config.
        auto_source: Source used for auto-discovery (cascading/env/file).
        auto_filename: Filename searched when auto-discovery cascades.
        auto_env_var: Environment variable used when auto_source is ``"env"``.
        auto_path: Explicit path used when auto_source is ``"file"``.
        auto: :class:`AutoDiscoveryConfig` carrying the effective auto-discovery options.

    Examples:
        Instance-based usage with custom settings::

            >>> loader = ConfigLoader(strict_format=True, encoding='utf-8')  # doctest: +SKIP
            >>> config = loader.load_from_file("config.yml")  # doctest: +SKIP
            >>> print(config.app.name)  # doctest: +SKIP

        Factory methods (one-liner convenience)::

            >>> config = ConfigLoader.from_file("config.yml")  # doctest: +SKIP
            >>> config = ConfigLoader.from_env("CONFIG_PATH")  # doctest: +SKIP
            >>> config = ConfigLoader.from_cascading("myapp.yml")  # doctest: +SKIP

        Multiple independent configs::

            >>> dev_config = ConfigLoader().load_from_file("dev.yml")  # doctest: +SKIP
            >>> prod_config = ConfigLoader(strict_format=True).load_from_file("prod.yml")  # doctest: +SKIP

        Disable SOPS decryption::

            >>> loader = ConfigLoader(sops_decrypt=False)  # doctest: +SKIP
            >>> config = loader.load_from_file("secrets.sops.yml")  # Loads raw  # doctest: +SKIP
    """

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        strict_format: bool = False,
        encoding: str = DEFAULT_ENCODING,
        sops_decrypt: bool = True,
        *,
        auto: AutoDiscoveryConfig | None = None,
        **auto_kwargs: Any,
    ) -> None:
        """Initialize a ConfigLoader with specific settings.

        Args:
            strict_format: If True, included files must match parent file format.
            encoding: File encoding for text-based configuration formats.
            sops_decrypt: If True, auto-decrypt .sops.* files via SOPS binary.
            auto: Pre-built auto-discovery options. When omitted, keyword arguments
                such as ``auto_source`` or ``auto_filename`` are honoured.
            auto_kwargs: Legacy keyword arguments controlling auto-discovery:
                ``auto_discovery``, ``auto_source``, ``auto_filename``,
                ``auto_env_var``, and ``auto_path``.
        """
        self.strict_format = strict_format
        self.encoding = encoding
        self.sops_decrypt = sops_decrypt
        self._cache: Box | None = None
        self._cache_timestamp: float | None = None
        self.auto = self._build_auto_config(auto, auto_kwargs)

        if self.auto.enabled:
            self._auto_load()

    def _build_auto_config(
        self,
        auto: AutoDiscoveryConfig | None,
        auto_kwargs: dict[str, Any],
    ) -> AutoDiscoveryConfig:
        """Normalize legacy auto-discovery kwargs into a dataclass instance."""
        if auto is not None and auto_kwargs:
            raise ValueError("'auto' parameter cannot be combined with legacy auto_* keyword arguments.")
        if auto is not None:
            return auto

        allowed = {
            "auto_discovery",
            "auto_source",
            "auto_filename",
            "auto_env_var",
            "auto_path",
        }
        unexpected = set(auto_kwargs) - allowed
        if unexpected:
            raise TypeError(f"Unexpected auto configuration keywords: {sorted(unexpected)}")

        auto_source = cast("AutoDiscoverySource", auto_kwargs.get("auto_source", "cascading"))
        auto_path = cast("str | pathlib.Path | None", auto_kwargs.get("auto_path"))
        auto_filename = cast("str", auto_kwargs.get("auto_filename", CONFIG_FILENAME))
        auto_env_var = cast("str", auto_kwargs.get("auto_env_var", "CONFIG_PATH"))
        auto_discovery = bool(auto_kwargs.get("auto_discovery", True))
        resolved_path = pathlib.Path(auto_path).resolve() if auto_path else None
        return AutoDiscoveryConfig(
            enabled=auto_discovery,
            source=auto_source,
            filename=auto_filename,
            env_var=auto_env_var,
            path=resolved_path,
        )

    @property
    def cache(self) -> Box | None:
        """Return the cached configuration instance, if any."""
        return self._cache

    @cache.setter
    def cache(self, value: Box | None) -> None:
        """Update the cached configuration instance."""
        self._cache = value
        self._cache_timestamp = time.time() if value is not None else None

    @property
    def cache_timestamp(self) -> float | None:
        """Return the epoch timestamp when the cache was last refreshed."""
        return self._cache_timestamp

    @property
    def config(self) -> Box:
        """Return the currently loaded configuration or raise if missing."""
        if self._cache is None:
            raise ConfigNotLoadedError(
                "Configuration not loaded. Enable auto_discovery or call a load_* method before accessing data."
            )
        return self._cache

    def __getattr__(self, item: str) -> Any:  # pragma: no cover - thin proxy
        """Proxy attribute access to the cached configuration."""
        try:
            return getattr(self.config, item)
        except ConfigNotLoadedError as exc:  # pragma: no cover - attribute fallback
            raise AttributeError(str(exc)) from exc

    def __getitem__(self, key: str) -> Any:
        """Provide dict-style access to the cached configuration."""
        return self.config[key]

    def _auto_load(self) -> None:
        if self.auto.source == "cascading":
            self.load(self.auto.filename)
            return
        if self.auto.source == "env":
            self.load_from_env(self.auto.env_var)
            return
        if self.auto.source == "file":
            if self.auto.path is None:
                raise ConfigNotLoadedError(
                    "auto_path must be provided when auto_source='file'. Set auto_discovery=False to skip auto load."
                )
            self.load_from_file(self.auto.path)
            return
        raise ConfigFormatError(f"Unsupported auto_discovery source: {self.auto.source}")

    def _merge_into_cache(self, conf: Box, purge_cache: bool) -> Box:
        if purge_cache or self._cache is None:
            self.cache = conf
            return conf

        existing = self._cache.to_dict()
        merged = deep_merge(existing, conf.to_dict())
        new_box = Box(merged, default_box=True, default_box_attr=None)
        self.cache = new_box
        return new_box

    def load_from_file(self, path: str | pathlib.Path, *, purge_cache: bool = True) -> Box:
        """
        Load configuration from a specific file path.

        Args:
            path: Path to configuration file (str or Path object).
            purge_cache: If True, replace the cached config with the freshly loaded data.

        Returns:
            Configuration object with dot notation support.

        Raises:
            ConfigFileNotFoundError: If the specified file doesn't exist.
            ConfigFormatError: On unsupported format or format mismatch.
            ConfigCircularIncludeError: On circular includes.

        Examples:
            >>> loader = ConfigLoader()  # doctest: +SKIP
            >>> config = loader.load_from_file("/opt/myapp/config.yml")  # doctest: +SKIP
            >>> print(config.database.host)  # doctest: +SKIP
        """
        path = pathlib.Path(path).resolve()
        if not path.is_file():
            raise ConfigFileNotFoundError(f"Config file not found: {path}")
        conf = _load_with_includes(
            path,
            strict_format=self.strict_format,
            encoding=self.encoding,
            sops_decrypt=self.sops_decrypt,
        )
        box_conf = Box(conf, default_box=True, default_box_attr=None)
        return self._merge_into_cache(box_conf, purge_cache)

    def load_from_env(self, env_var: str = "CONFIG_PATH", *, purge_cache: bool = True) -> Box:
        """
        Load configuration from path specified in an environment variable.

        Args:
            env_var: Name of environment variable containing config file path.
            purge_cache: If True, replace the cached config with the freshly loaded data.

        Returns:
            Configuration object with dot notation support.

        Raises:
            ValueError: If environment variable is not set or empty.
            ConfigFileNotFoundError: If the path in environment variable doesn't exist.

        Examples:
            >>> import os  # doctest: +SKIP
            >>> os.environ["CONFIG_PATH"] = "/opt/config.yml"  # doctest: +SKIP
            >>> loader = ConfigLoader()  # doctest: +SKIP
            >>> config = loader.load_from_env()  # doctest: +SKIP
        """
        path_str = os.getenv(env_var)
        if not path_str:
            raise ValueError(f"Environment variable '{env_var}' is not set or empty")
        return self.load_from_file(path_str, purge_cache=purge_cache)

    def load(self, filename: str = CONFIG_FILENAME, *, purge_cache: bool = True) -> Box:
        """
        Load configuration using cascading search across multiple locations.

        Search order (priority from lowest to highest):
            1. Package default config (lowest priority - base layer)
            2. User's config directory (e.g., ~/.config/kstlib.conf.yml)
            3. User's home directory (e.g., ~/kstlib.conf.yml)
            4. Current working directory (highest priority - overrides all)

        Args:
            filename: Config filename to search for.
            purge_cache: If True, replace the cached config with the freshly loaded data.

        Returns:
            Configuration object with dot notation support.

        Raises:
            ConfigFileNotFoundError: If no config file is found in any location.

        Examples:
            >>> loader = ConfigLoader()  # doctest: +SKIP
            >>> config = loader.load("myapp.yml")  # doctest: +SKIP
        """
        # Start with package default config
        _config = _load_default_config(self.encoding)

        # Search multiple locations
        home = pathlib.Path.home()
        search_paths = [
            home / USER_CONFIG_DIR / filename,
            home / filename,
            pathlib.Path.cwd() / filename,
        ]

        for search_path in search_paths:
            if search_path.is_file():
                conf = _load_with_includes(
                    search_path,
                    strict_format=self.strict_format,
                    encoding=self.encoding,
                    sops_decrypt=self.sops_decrypt,
                )
                _config = deep_merge(_config, conf)

        if not _config:
            raise ConfigFileNotFoundError(
                f"No configuration file found in working directory, home, {USER_CONFIG_DIR}, "
                f"or package data (searched for '{filename}')."
            )
        box_conf = Box(_config, default_box=True, default_box_attr=None)
        return self._merge_into_cache(box_conf, purge_cache)

    # Factory methods for one-liner convenience

    @classmethod
    def from_file(
        cls,
        path: str | pathlib.Path,
        strict_format: bool = False,
        encoding: str = DEFAULT_ENCODING,
        sops_decrypt: bool = True,
    ) -> Box:
        """
        Create loader and load file in one call (factory method).

        Args:
            path: Path to configuration file.
            strict_format: If True, included files must match parent format.
            encoding: File encoding.
            sops_decrypt: If True, auto-decrypt .sops.* files via SOPS binary.

        Returns:
            Configuration object with dot notation support.

        Examples:
            >>> config = ConfigLoader.from_file("config.yml")  # doctest: +SKIP
            >>> config = ConfigLoader.from_file("config.yml", strict_format=True)  # doctest: +SKIP
        """
        return cls(strict_format=strict_format, encoding=encoding, sops_decrypt=sops_decrypt).load_from_file(path)

    @classmethod
    def from_env(
        cls,
        env_var: str = "CONFIG_PATH",
        strict_format: bool = False,
        encoding: str = DEFAULT_ENCODING,
        sops_decrypt: bool = True,
    ) -> Box:
        """
        Create loader and load from environment variable in one call (factory method).

        Args:
            env_var: Name of environment variable containing config file path.
            strict_format: If True, included files must match parent format.
            encoding: File encoding.
            sops_decrypt: If True, auto-decrypt .sops.* files via SOPS binary.

        Returns:
            Configuration object with dot notation support.

        Examples:
            >>> config = ConfigLoader.from_env("CONFIG_PATH")  # doctest: +SKIP
            >>> config = ConfigLoader.from_env("MYAPP_CONFIG", strict_format=True)  # doctest: +SKIP
        """
        return cls(strict_format=strict_format, encoding=encoding, sops_decrypt=sops_decrypt).load_from_env(env_var)

    @classmethod
    def from_cascading(
        cls,
        filename: str = CONFIG_FILENAME,
        strict_format: bool = False,
        encoding: str = DEFAULT_ENCODING,
        sops_decrypt: bool = True,
    ) -> Box:
        """
        Create loader and perform cascading search in one call (factory method).

        Args:
            filename: Config filename to search for.
            strict_format: If True, included files must match parent format.
            encoding: File encoding.
            sops_decrypt: If True, auto-decrypt .sops.* files via SOPS binary.

        Returns:
            Configuration object with dot notation support.

        Examples:
            >>> config = ConfigLoader.from_cascading("myapp.yml")  # doctest: +SKIP
            >>> config = ConfigLoader.from_cascading(strict_format=True)  # doctest: +SKIP
        """
        return cls(strict_format=strict_format, encoding=encoding, sops_decrypt=sops_decrypt).load(filename)


# ============================================================================
# Backward-compatible functional API
# ============================================================================

# Global singleton for backward compatibility
_default_loader = ConfigLoader(auto_discovery=False)


def load_config(
    filename: str = CONFIG_FILENAME,
    path: pathlib.Path | None = None,
    strict_format: bool = False,
    sops_decrypt: bool = True,
) -> Box:
    """
    Load configuration either from cascading search or from an explicit file path.

    Two modes of operation:
    1. Cascading mode: Searches multiple locations and merges configs
    2. Direct mode: Loads from specific file path only

    Cascading search order (priority from lowest to highest):
        1. Package default config (lowest priority - base layer)
        2. User's config directory (e.g., ~/.config/kstlib.conf.yml)
        3. User's home directory (e.g., ~/kstlib.conf.yml)
        4. Current working directory (highest priority - overrides all)

    Note: Files are merged using deep merge, so later files override earlier ones.
    The current working directory config has final say on all values.

    This is a backward-compatible wrapper. For new code, prefer ConfigLoader class.

    Args:
        filename: Config filename to search for (cascading mode only).
        path: Explicit path to config file (direct mode). If set, cascading is disabled.
        strict_format: If True, included files must match parent file format.
        sops_decrypt: If True, auto-decrypt .sops.* files via SOPS binary.

    Returns:
        Configuration object with dot notation support (Box object).
        Missing keys return empty Box() instead of raising AttributeError.

    Raises:
        ConfigFileNotFoundError: If no config file is found or specified path doesn't exist.
        ConfigFormatError: On unsupported format or format mismatch.
        ConfigCircularIncludeError: On circular includes.

    Examples:
        Cascading search (default)::

            >>> config = load_config("myapp.yml")  # doctest: +SKIP

        Direct load from specific path::

            >>> config = load_config(path="/opt/myapp/config.yml")  # doctest: +SKIP

        Direct load with strict format enforcement::

            >>> config = load_config(path="/etc/app.yml", strict_format=True)  # doctest: +SKIP
    """
    loader = ConfigLoader(strict_format=strict_format, sops_decrypt=sops_decrypt)
    if path is not None:
        return loader.load_from_file(path)
    return loader.load(filename)


def get_config(
    filename: str = CONFIG_FILENAME,
    force_reload: bool = False,
    max_age: float | None = None,
) -> Box:
    """
    Returns the current kstlib configuration object (singleton).

    Loads the configuration only once, unless `force_reload=True` is set.

    This is a backward-compatible wrapper. For new code, prefer ConfigLoader class.

    Args:
        filename: Name of the config file to search for.
        force_reload: Force reloading the configuration from disk.
        max_age: Optional cache lifetime in seconds; refreshes automatically
            when the cached configuration is older than this value.

    Returns:
        Box: Configuration object (dot notation enabled).

    Raises:
        ConfigFileNotFoundError: If no configuration file is found in any location.

    Examples:
        >>> config = get_config()  # doctest: +SKIP
        >>> config = get_config(force_reload=True)  # doctest: +SKIP
    """
    cache_stale = False
    if not force_reload and max_age is not None and _default_loader.cache is not None:
        loaded_at = _default_loader.cache_timestamp
        cache_stale = loaded_at is None or (time.time() - loaded_at > max_age)

    if _default_loader.cache is None or force_reload or cache_stale:
        _default_loader.cache = _default_loader.load(filename)
    return _default_loader.cache


def require_config() -> Box:
    """
    Returns the configuration object, raising an exception if not loaded.

    Use this when you need to ensure a config is available.

    This is a backward-compatible wrapper. For new code, prefer ConfigLoader class.

    Returns:
        Loaded configuration.

    Raises:
        ConfigNotLoadedError: If configuration has not been loaded yet.

    Examples:
        >>> config = require_config()  # doctest: +SKIP
    """
    if _default_loader.cache is None:
        raise ConfigNotLoadedError("Configuration not loaded yet. Call get_config() before accessing the config.")
    return _default_loader.cache


def load_from_file(
    path: str | pathlib.Path,
    strict_format: bool = False,
    sops_decrypt: bool = True,
) -> Box:
    """
    Load configuration from a specific file path.

    Convenience wrapper for load_config(path=...).

    This is a backward-compatible wrapper. For new code, prefer ConfigLoader.from_file().

    Args:
        path: Path to configuration file (str or Path object).
        strict_format: If True, included files must match parent file format.
        sops_decrypt: If True, auto-decrypt .sops.* files via SOPS binary.

    Returns:
        Configuration object with dot notation support.

    Raises:
        ConfigFileNotFoundError: If the specified file doesn't exist.
        ConfigFormatError: On unsupported format or format mismatch.
        ConfigCircularIncludeError: On circular includes.

    Examples:
        >>> config = load_from_file("/opt/myapp/config.yml")  # doctest: +SKIP
        >>> config = load_from_file("/etc/app.yml", strict_format=True)  # doctest: +SKIP
    """
    return ConfigLoader(strict_format=strict_format, sops_decrypt=sops_decrypt).load_from_file(path)


def load_from_env(
    env_var: str = "CONFIG_PATH",
    strict_format: bool = False,
    sops_decrypt: bool = True,
) -> Box:
    """
    Load configuration from path specified in an environment variable.

    This is a backward-compatible wrapper. For new code, prefer ConfigLoader.from_env().

    Args:
        env_var: Name of environment variable containing config file path.
        strict_format: If True, included files must match parent file format.
        sops_decrypt: If True, auto-decrypt .sops.* files via SOPS binary.

    Returns:
        Configuration object with dot notation support.

    Raises:
        ValueError: If environment variable is not set or empty.
        ConfigFileNotFoundError: If the path in environment variable doesn't exist.

    Examples:
        With CONFIG_PATH=/opt/myapp.yml::

            >>> config = load_from_env()  # doctest: +SKIP

        With MYAPP_CONFIG=/etc/app.yml::

            >>> config = load_from_env("MYAPP_CONFIG")  # doctest: +SKIP

        With strict format enforcement::

            >>> config = load_from_env("CONFIG_PATH", strict_format=True)  # doctest: +SKIP
    """
    return ConfigLoader(strict_format=strict_format, sops_decrypt=sops_decrypt).load_from_env(env_var)


def clear_config() -> None:
    """
    Clear the singleton configuration cache.

    Useful for testing or when you need to reload configuration.

    Examples:
        >>> clear_config()  # doctest: +SKIP
        >>> config = get_config()  # Will reload from disk  # doctest: +SKIP
    """
    _default_loader.cache = None


__all__ = [
    "AutoDiscoveryConfig",
    "ConfigLoader",
    "clear_config",
    "get_config",
    "load_config",
    "load_from_env",
    "load_from_file",
    "require_config",
]
