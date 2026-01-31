"""Configuration management for RAPI module.

This module handles loading and resolving endpoint configurations
from kstlib.conf.yml or external ``*.rapi.yml`` files.

Supports:
- Loading from kstlib.conf.yml (default)
- Loading from external YAML files (``*.rapi.yml``)
- Auto-discovery of ``*.rapi.yml`` files in current directory
- Include patterns in kstlib.conf.yml
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from kstlib.rapi.exceptions import EndpointAmbiguousError, EndpointNotFoundError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

log = logging.getLogger(__name__)

# Pattern for path parameters: {param} or {0}, {1}
_PATH_PARAM_PATTERN = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*|\d+)\}")


# Deep defense: allowed values for HMAC config (hardcoded limits)
_ALLOWED_HMAC_ALGORITHMS = frozenset({"sha256", "sha512"})
_ALLOWED_SIGNATURE_FORMATS = frozenset({"hex", "base64"})
_MAX_FIELD_NAME_LENGTH = 64  # Max length for field names (timestamp_field, etc.)
_MAX_HEADER_NAME_LENGTH = 128  # Max length for header names


@dataclass(frozen=True, slots=True)
class HmacConfig:
    """HMAC signing configuration.

    Supports various exchange APIs like Binance (SHA256) and Kraken (SHA512).

    Attributes:
        algorithm: Hash algorithm (sha256, sha512).
        timestamp_field: Query param name for timestamp.
        nonce_field: Query param name for nonce (alternative to timestamp).
        signature_field: Query param name for signature.
        signature_format: Output format (hex, base64).
        key_header: Header name for API key.
        sign_body: If True, sign request body instead of query string.

    Examples:
        >>> config = HmacConfig(algorithm="sha512", signature_format="base64")
        >>> config.algorithm
        'sha512'
    """

    algorithm: str = "sha256"
    timestamp_field: str = "timestamp"
    nonce_field: str | None = None
    signature_field: str = "signature"
    signature_format: str = "hex"
    key_header: str | None = None
    sign_body: bool = False

    def __post_init__(self) -> None:
        """Validate HMAC config values (deep defense)."""
        # Validate algorithm
        if self.algorithm not in _ALLOWED_HMAC_ALGORITHMS:
            raise ValueError(f"Invalid HMAC algorithm: {self.algorithm!r}. Allowed: {sorted(_ALLOWED_HMAC_ALGORITHMS)}")

        # Validate signature format
        if self.signature_format not in _ALLOWED_SIGNATURE_FORMATS:
            raise ValueError(
                f"Invalid signature format: {self.signature_format!r}. Allowed: {sorted(_ALLOWED_SIGNATURE_FORMATS)}"
            )

        # Validate field name lengths
        if len(self.timestamp_field) > _MAX_FIELD_NAME_LENGTH:
            raise ValueError(f"timestamp_field too long: {len(self.timestamp_field)} > {_MAX_FIELD_NAME_LENGTH}")
        if len(self.signature_field) > _MAX_FIELD_NAME_LENGTH:
            raise ValueError(f"signature_field too long: {len(self.signature_field)} > {_MAX_FIELD_NAME_LENGTH}")
        if self.nonce_field and len(self.nonce_field) > _MAX_FIELD_NAME_LENGTH:
            raise ValueError(f"nonce_field too long: {len(self.nonce_field)} > {_MAX_FIELD_NAME_LENGTH}")
        if self.key_header and len(self.key_header) > _MAX_HEADER_NAME_LENGTH:
            raise ValueError(f"key_header too long: {len(self.key_header)} > {_MAX_HEADER_NAME_LENGTH}")


def _extract_credentials_from_rapi(
    data: dict[str, Any],
    api_name: str,
    file_path: Path,
) -> tuple[str | None, dict[str, Any]]:
    """Extract credentials configuration from RAPI file data.

    Args:
        data: Parsed YAML data.
        api_name: Name of the API.
        file_path: Path to the file (for resolving relative paths).

    Returns:
        Tuple of (credentials_ref, credentials_config).
    """
    credentials_config: dict[str, Any] = {}
    credentials_ref: str | None = None

    if "credentials" not in data:
        return None, {}

    cred_data = data["credentials"]
    if isinstance(cred_data, dict):
        # Inline credentials definition
        credentials_ref = f"_rapi_{api_name}_cred"
        # Resolve relative paths in credentials (expand ~ first)
        if "path" in cred_data:
            cred_path = Path(cred_data["path"]).expanduser()
            if cred_path.is_absolute():
                # Already absolute (or was ~ expanded to absolute)
                cred_data["path"] = str(cred_path)
            else:
                # Relative path: resolve against file location
                cred_data["path"] = str(file_path.parent / cred_data["path"])
        credentials_config[credentials_ref] = cred_data
    elif isinstance(cred_data, str):
        # Reference to existing credential
        credentials_ref = cred_data

    return credentials_ref, credentials_config


def _extract_auth_config(
    data: dict[str, Any],
) -> tuple[str | None, HmacConfig | None]:
    """Extract auth type and HMAC config from RAPI file data.

    Args:
        data: Parsed YAML data.

    Returns:
        Tuple of (auth_type, HmacConfig or None).
    """
    if "auth" not in data:
        return None, None

    auth_data = data["auth"]
    if isinstance(auth_data, str):
        return auth_data, None

    if not isinstance(auth_data, dict):
        return None, None

    auth_type = auth_data.get("type")

    # Parse HMAC config if auth type is hmac
    hmac_config: HmacConfig | None = None
    if auth_type == "hmac":
        hmac_config = HmacConfig(
            algorithm=auth_data.get("algorithm", "sha256"),
            timestamp_field=auth_data.get("timestamp_field", "timestamp"),
            nonce_field=auth_data.get("nonce_field"),
            signature_field=auth_data.get("signature_field", "signature"),
            signature_format=auth_data.get("signature_format", "hex"),
            key_header=auth_data.get("key_header"),
            sign_body=auth_data.get("sign_body", False),
        )

    return auth_type, hmac_config


def _parse_rapi_file(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Parse a ``*.rapi.yml`` file into internal config format.

    Converts the simplified format:
    ```yaml
    name: github
    base_url: "https://api.github.com"
    credentials:
      type: sops
      path: "./tokens/github.sops.json"
    auth:
      type: bearer
    endpoints:
      user:
        path: "/user"
    ```

    Into the internal format:
    ```python
    {
        "api": {
            "github": {
                "base_url": "...",
                "credentials": "_github_cred",
                "auth_type": "bearer",
                "endpoints": {...}
            }
        }
    }
    ```

    Args:
        path: Path to the ``*.rapi.yml`` file.

    Returns:
        Tuple of (api_config, credentials_config).

    Raises:
        TypeError: If file format is invalid.
        ValueError: If required fields are missing.
    """
    import yaml

    content = path.read_text(encoding="utf-8")
    data = yaml.safe_load(content)

    if not isinstance(data, dict):
        raise TypeError(f"Invalid RAPI config format in {path}: expected dict")

    # Extract API name (or derive from filename)
    api_name = data.get("name")
    if not api_name:
        api_name = path.stem.replace(".rapi", "")
        log.debug("API name not specified, derived from filename: %s", api_name)

    # Validate required fields
    base_url = data.get("base_url")
    if not base_url:
        raise ValueError(f"Missing 'base_url' in {path}")

    # Extract credentials and auth
    credentials_ref, credentials_config = _extract_credentials_from_rapi(data, api_name, path)
    auth_type, hmac_config = _extract_auth_config(data)

    # Build API config
    api_config: dict[str, Any] = {
        "api": {
            api_name: {
                "base_url": base_url,
                "credentials": credentials_ref,
                "auth_type": auth_type,
                "hmac_config": hmac_config,
                "headers": data.get("headers", {}),
                "endpoints": data.get("endpoints", {}),
            }
        }
    }

    log.debug(
        "Parsed %s: api=%s, %d endpoints, credentials=%s",
        path.name,
        api_name,
        len(data.get("endpoints", {})),
        "inline" if credentials_ref and credentials_ref.startswith("_rapi_") else credentials_ref,
    )

    return api_config, credentials_config


@dataclass(frozen=True, slots=True)
class EndpointConfig:
    """Configuration for a single API endpoint.

    Attributes:
        name: Endpoint name (e.g., "get_ip").
        api_name: Parent API name (e.g., "httpbin").
        path: URL path template (e.g., "/delay/{seconds}").
        method: HTTP method (GET, POST, PUT, DELETE, PATCH).
        query: Default query parameters.
        headers: Endpoint-level headers (merged with service headers).
        body_template: Default body template for POST/PUT.
        auth: Whether to apply API-level authentication to this endpoint.
            Set to False for public endpoints that don't require auth.

    Examples:
        >>> config = EndpointConfig(
        ...     name="get_ip",
        ...     api_name="httpbin",
        ...     path="/ip",
        ...     method="GET",
        ... )
        >>> config.full_ref
        'httpbin.get_ip'
    """

    name: str
    api_name: str
    path: str
    method: str = "GET"
    query: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    body_template: dict[str, Any] | None = None
    auth: bool = True

    @property
    def full_ref(self) -> str:
        """Return full reference: api_name.endpoint_name."""
        return f"{self.api_name}.{self.name}"

    def build_path(self, *args: Any, **kwargs: Any) -> str:
        """Build path with positional and keyword arguments.

        Args:
            *args: Positional arguments for {0}, {1}, etc.
            **kwargs: Keyword arguments for {name} placeholders.

        Returns:
            Formatted path string.

        Raises:
            ValueError: If required parameters are missing.

        Examples:
            >>> config = EndpointConfig(
            ...     name="delay",
            ...     api_name="httpbin",
            ...     path="/delay/{seconds}",
            ... )
            >>> config.build_path(seconds=5)
            '/delay/5'
            >>> config.build_path(5)
            '/delay/5'
        """
        path = self.path

        # Find all placeholders
        placeholders = _PATH_PARAM_PATTERN.findall(path)

        for placeholder in placeholders:
            if placeholder.isdigit():
                # Positional: {0}, {1}
                idx = int(placeholder)
                if idx < len(args):
                    path = path.replace(f"{{{placeholder}}}", str(args[idx]))
                else:
                    raise ValueError(f"Missing positional argument {idx} for path {self.path}")
            elif placeholder in kwargs:
                # Named: {name}
                path = path.replace(f"{{{placeholder}}}", str(kwargs[placeholder]))
            elif len(args) > 0:
                # Try to use first positional arg for first named placeholder
                path = path.replace(f"{{{placeholder}}}", str(args[0]))
                args = args[1:]
            else:
                raise ValueError(f"Missing parameter '{placeholder}' for path {self.path}")

        return path


@dataclass(frozen=True, slots=True)
class ApiConfig:
    """Configuration for an API service.

    Attributes:
        name: API service name (e.g., "httpbin").
        base_url: Base URL for the API.
        credentials: Name of credential config to use.
        auth_type: Authentication type (bearer, basic, api_key, hmac).
        hmac_config: HMAC signing configuration (required when auth_type is hmac).
        headers: Service-level headers (applied to all endpoints).
        endpoints: Dictionary of endpoint configurations.

    Examples:
        >>> api = ApiConfig(
        ...     name="httpbin",
        ...     base_url="https://httpbin.org",
        ...     endpoints={},
        ... )
    """

    name: str
    base_url: str
    credentials: str | None = None
    auth_type: str | None = None
    hmac_config: HmacConfig | None = None
    headers: dict[str, str] = field(default_factory=dict)
    endpoints: dict[str, EndpointConfig] = field(default_factory=dict)


class RapiConfigManager:
    """Manage RAPI configuration and endpoint resolution.

    Loads API and endpoint configurations from kstlib.conf.yml and provides
    resolution methods supporting both full references (api.endpoint) and
    short references (endpoint only, auto-resolved if unique).

    Supports loading from:
    - kstlib.conf.yml (default)
    - External ``*.rapi.yml`` files (via from_file/from_files)
    - Auto-discovery of ``*.rapi.yml`` in current directory (via discover)

    Args:
        rapi_config: The 'rapi' section from configuration.
        credentials_config: Inline credentials extracted from ``*.rapi.yml`` files.

    Examples:
        >>> manager = RapiConfigManager({"api": {"httpbin": {"base_url": "..."}}})
        >>> endpoint = manager.resolve("httpbin.get_ip")  # doctest: +SKIP

        >>> manager = RapiConfigManager.from_file("github.rapi.yml")  # doctest: +SKIP
        >>> manager = RapiConfigManager.discover()  # doctest: +SKIP
    """

    def __init__(
        self,
        rapi_config: Mapping[str, Any] | None = None,
        credentials_config: Mapping[str, Any] | None = None,
    ) -> None:
        """Initialize RapiConfigManager.

        Args:
            rapi_config: The 'rapi' section from configuration.
            credentials_config: Inline credentials from ``*.rapi.yml`` files.
        """
        self._config = rapi_config or {}
        self._credentials_config = dict(credentials_config) if credentials_config else {}
        self._apis: dict[str, ApiConfig] = {}
        self._endpoint_index: dict[str, list[str]] = {}  # endpoint_name -> [api_names]
        self._source_files: list[Path] = []  # Track loaded files for debugging

        self._load_apis()

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        base_dir: Path | None = None,
    ) -> RapiConfigManager:
        """Load configuration from a single ``*.rapi.yml`` file.

        The file format is simplified compared to kstlib.conf.yml,
        with top-level keys: name, base_url, credentials, auth, headers, endpoints.

        Args:
            path: Path to the ``*.rapi.yml`` file.
            base_dir: Base directory for resolving relative paths in credentials.

        Returns:
            Configured RapiConfigManager instance.

        Raises:
            FileNotFoundError: If file does not exist.
            ValueError: If file format is invalid.

        Examples:
            >>> manager = RapiConfigManager.from_file("github.rapi.yml")  # doctest: +SKIP
        """
        return cls.from_files([path], base_dir=base_dir)

    @classmethod
    def from_files(
        cls,
        paths: Sequence[str | Path],
        base_dir: Path | None = None,
    ) -> RapiConfigManager:
        """Load configuration from multiple ``*.rapi.yml`` files.

        Args:
            paths: List of paths to ``*.rapi.yml`` files.
            base_dir: Base directory for resolving relative paths.

        Returns:
            Configured RapiConfigManager instance with merged configs.

        Raises:
            FileNotFoundError: If any file does not exist.
            ValueError: If any file format is invalid.

        Examples:
            >>> manager = RapiConfigManager.from_files([
            ...     "github.rapi.yml",
            ...     "slack.rapi.yml",
            ... ])  # doctest: +SKIP
        """
        merged_api_config: dict[str, Any] = {"api": {}}
        merged_credentials: dict[str, Any] = {}
        source_files: list[Path] = []

        for file_path in paths:
            path = Path(file_path)
            if not path.is_absolute() and base_dir:
                path = base_dir / path

            if not path.exists():
                raise FileNotFoundError(f"RAPI config file not found: {path}")

            log.debug("Loading RAPI config from: %s", path)
            api_config, credentials = _parse_rapi_file(path)

            # Merge API config
            for api_name, api_data in api_config.get("api", {}).items():
                if api_name in merged_api_config["api"]:
                    log.warning("API '%s' redefined in %s, overwriting", api_name, path)
                merged_api_config["api"][api_name] = api_data

            # Merge credentials
            merged_credentials.update(credentials)
            source_files.append(path)

        manager = cls(merged_api_config, merged_credentials)
        manager._source_files = source_files
        return manager

    @classmethod
    def discover(
        cls,
        directory: str | Path | None = None,
        pattern: str = "*.rapi.yml",
    ) -> RapiConfigManager:
        """Auto-discover and load ``*.rapi.yml`` files from a directory.

        Searches for files matching the pattern in the specified directory
        (defaults to current working directory).

        Args:
            directory: Directory to search in (default: current directory).
            pattern: Glob pattern for files (default: ``*.rapi.yml``).

        Returns:
            Configured RapiConfigManager instance.

        Raises:
            FileNotFoundError: If no matching files found.

        Examples:
            >>> manager = RapiConfigManager.discover()  # doctest: +SKIP
            >>> manager = RapiConfigManager.discover("./apis/")  # doctest: +SKIP
        """
        search_dir = Path(directory) if directory else Path.cwd()

        if not search_dir.exists():
            raise FileNotFoundError(f"Directory not found: {search_dir}")

        # Find all matching files
        files = list(search_dir.glob(pattern))

        if not files:
            raise FileNotFoundError(f"No RAPI config files found matching '{pattern}' in {search_dir}")

        log.info("Discovered %d RAPI config file(s) in %s", len(files), search_dir)
        for f in files:
            log.debug("  - %s", f.name)

        return cls.from_files(files, base_dir=search_dir)

    @property
    def credentials_config(self) -> dict[str, Any]:
        """Get inline credentials config extracted from ``*.rapi.yml`` files.

        Returns:
            Dictionary of credentials configurations.
        """
        return self._credentials_config

    @property
    def source_files(self) -> list[Path]:
        """Get list of source files loaded.

        Returns:
            List of Path objects for loaded files.
        """
        return self._source_files

    def _load_apis(self) -> None:
        """Load API configurations from config."""
        api_section = self._config.get("api", {})

        for api_name, api_data in api_section.items():
            if not isinstance(api_data, dict):
                log.warning("Skipping invalid API config: %s", api_name)
                continue

            base_url = api_data.get("base_url", "")
            if not base_url:
                log.warning("API '%s' missing base_url, skipping", api_name)
                continue

            # Parse endpoints
            endpoints: dict[str, EndpointConfig] = {}
            endpoints_data = api_data.get("endpoints", {})

            for ep_name, ep_data in endpoints_data.items():
                if not isinstance(ep_data, dict):
                    log.warning("Skipping invalid endpoint: %s.%s", api_name, ep_name)
                    continue

                endpoint = EndpointConfig(
                    name=ep_name,
                    api_name=api_name,
                    path=ep_data.get("path", f"/{ep_name}"),
                    method=ep_data.get("method", "GET").upper(),
                    query=dict(ep_data.get("query", {})),
                    headers=dict(ep_data.get("headers", {})),
                    body_template=ep_data.get("body"),
                    auth=ep_data.get("auth", True),
                )
                endpoints[ep_name] = endpoint

                # Index for short reference lookup
                if ep_name not in self._endpoint_index:
                    self._endpoint_index[ep_name] = []
                self._endpoint_index[ep_name].append(api_name)

                log.debug("Loaded endpoint: %s.%s", api_name, ep_name)

            # Create API config
            api_config = ApiConfig(
                name=api_name,
                base_url=base_url.rstrip("/"),
                credentials=api_data.get("credentials"),
                auth_type=api_data.get("auth_type"),
                hmac_config=api_data.get("hmac_config"),
                headers=dict(api_data.get("headers", {})),
                endpoints=endpoints,
            )
            self._apis[api_name] = api_config
            log.debug("Loaded API: %s (%d endpoints)", api_name, len(endpoints))

    def _merge_apis(
        self,
        other: RapiConfigManager,
        *,
        overwrite: bool = False,
    ) -> None:
        """Merge APIs from another manager into this one.

        Args:
            other: Source manager to merge from.
            overwrite: If True, overwrite existing APIs. If False, skip conflicts.
        """
        for api_name, api_config in other.apis.items():
            if api_name in self._apis and not overwrite:
                log.warning(
                    "API '%s' in include conflicts with inline config, keeping inline",
                    api_name,
                )
                continue

            self._apis[api_name] = api_config

            # Update endpoint index
            for ep_name in api_config.endpoints:
                if ep_name not in self._endpoint_index:
                    self._endpoint_index[ep_name] = []
                if api_name not in self._endpoint_index[ep_name]:
                    self._endpoint_index[ep_name].append(api_name)

        # Merge credentials
        for cred_name, cred_config in other.credentials_config.items():
            if cred_name not in self._credentials_config:
                self._credentials_config[cred_name] = cred_config

    def resolve(self, endpoint_ref: str) -> tuple[ApiConfig, EndpointConfig]:
        """Resolve endpoint reference to configuration.

        Supports both full references (api.endpoint) and short references
        (endpoint only). Short references are auto-resolved if the endpoint
        name is unique across all APIs.

        Args:
            endpoint_ref: Full reference (api.endpoint) or short (endpoint).

        Returns:
            Tuple of (ApiConfig, EndpointConfig).

        Raises:
            EndpointNotFoundError: If endpoint cannot be found.
            EndpointAmbiguousError: If short reference matches multiple APIs.

        Examples:
            >>> manager = RapiConfigManager({...})  # doctest: +SKIP
            >>> api, endpoint = manager.resolve("httpbin.get_ip")  # doctest: +SKIP
            >>> api, endpoint = manager.resolve("get_ip")  # doctest: +SKIP
        """
        log.debug("Resolving endpoint reference: %s", endpoint_ref)

        if "." in endpoint_ref:
            # Full reference: api.endpoint
            return self._resolve_full(endpoint_ref)

        # Short reference: endpoint only
        return self._resolve_short(endpoint_ref)

    def _resolve_full(self, endpoint_ref: str) -> tuple[ApiConfig, EndpointConfig]:
        """Resolve full reference (api.endpoint)."""
        parts = endpoint_ref.split(".", 1)
        if len(parts) != 2:
            raise EndpointNotFoundError(endpoint_ref, list(self._apis))

        api_name, endpoint_name = parts

        if api_name not in self._apis:
            raise EndpointNotFoundError(
                endpoint_ref,
                list(self._apis),
            )

        api_config = self._apis[api_name]

        if endpoint_name not in api_config.endpoints:
            raise EndpointNotFoundError(
                endpoint_ref,
                [api_name],
            )

        endpoint_config = api_config.endpoints[endpoint_name]
        log.debug("Resolved full reference: %s", endpoint_config.full_ref)

        return api_config, endpoint_config

    def _resolve_short(self, endpoint_name: str) -> tuple[ApiConfig, EndpointConfig]:
        """Resolve short reference (endpoint only, auto-resolve if unique)."""
        if endpoint_name not in self._endpoint_index:
            raise EndpointNotFoundError(endpoint_name, list(self._apis))

        matching_apis = self._endpoint_index[endpoint_name]

        if len(matching_apis) > 1:
            raise EndpointAmbiguousError(endpoint_name, matching_apis)

        api_name = matching_apis[0]
        api_config = self._apis[api_name]
        endpoint_config = api_config.endpoints[endpoint_name]

        log.debug(
            "Resolved short reference '%s' to '%s'",
            endpoint_name,
            endpoint_config.full_ref,
        )

        return api_config, endpoint_config

    def get_api(self, api_name: str) -> ApiConfig | None:
        """Get API configuration by name.

        Args:
            api_name: API service name.

        Returns:
            ApiConfig or None if not found.
        """
        return self._apis.get(api_name)

    def list_apis(self) -> list[str]:
        """List all configured API names.

        Returns:
            List of API names.
        """
        return list(self._apis)

    @property
    def apis(self) -> dict[str, ApiConfig]:
        """Get all configured APIs.

        Returns:
            Dictionary mapping API names to ApiConfig objects.
        """
        return self._apis

    def list_endpoints(self, api_name: str | None = None) -> list[str]:
        """List endpoint references.

        Args:
            api_name: Filter by API name (optional).

        Returns:
            List of full endpoint references.
        """
        if api_name:
            api = self._apis.get(api_name)
            if not api:
                return []
            return [f"{api_name}.{ep}" for ep in api.endpoints]

        # All endpoints
        result: list[str] = []
        for api in self._apis.values():
            result.extend(f"{api.name}.{ep}" for ep in api.endpoints)
        return result


def load_rapi_config() -> RapiConfigManager:
    """Load RAPI configuration from kstlib.conf.yml with include support.

    Supports including external ``*.rapi.yml`` files via glob patterns:

    .. code-block:: yaml

        rapi:
          include:
            - "./apis/``*.rapi.yml``"
            - "~/.config/kstlib/``*.rapi.yml``"
          api:
            httpbin:
              base_url: "https://httpbin.org"
              # ...

    Returns:
        Configured RapiConfigManager instance with merged configs.

    Examples:
        >>> manager = load_rapi_config()  # doctest: +SKIP
    """
    from kstlib.config import get_config

    config = get_config()
    rapi_section = dict(config.get("rapi", {}))  # type: ignore[no-untyped-call]

    log.debug("Loading RAPI config from kstlib.conf.yml")

    # Process includes if present
    include_patterns = rapi_section.pop("include", None)

    # Create manager for inline config first
    manager = RapiConfigManager(rapi_section)

    # Merge included files if any
    if include_patterns:
        included_files = _resolve_include_patterns(include_patterns)
        if included_files:
            log.info("Including %d external RAPI config file(s)", len(included_files))
            included_manager = RapiConfigManager.from_files(included_files)
            # Merge included APIs (inline config takes precedence)
            manager._merge_apis(included_manager, overwrite=False)

    return manager


def _resolve_include_patterns(patterns: list[str] | str) -> list[Path]:
    """Resolve include patterns to file paths.

    Args:
        patterns: Glob pattern or list of patterns.

    Returns:
        List of resolved file paths.
    """
    if isinstance(patterns, str):
        patterns = [patterns]

    files: list[Path] = []
    for pattern in patterns:
        expanded = Path(pattern).expanduser()
        if expanded.is_absolute():
            matches = list(expanded.parent.glob(expanded.name))
        else:
            matches = list(Path.cwd().glob(pattern))
        files.extend(matches)

    return files


__all__ = [
    "ApiConfig",
    "EndpointConfig",
    "HmacConfig",
    "RapiConfigManager",
    "load_rapi_config",
]
