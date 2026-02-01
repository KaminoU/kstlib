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

from kstlib.rapi.exceptions import (
    EndpointAmbiguousError,
    EndpointCollisionError,
    EndpointNotFoundError,
    EnvVarError,
    SafeguardMissingError,
)

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

# Deep defense: safeguard validation
_MAX_SAFEGUARD_LENGTH = 128
_SAFEGUARD_PATTERN = re.compile(r"^[A-Za-z0-9_\-\s\{\}/]+$")

# Default HTTP methods that require safeguard
_DEFAULT_SAFEGUARD_METHODS = frozenset({"DELETE", "PUT"})

# Pattern for environment variable substitution: ${VAR} or ${VAR:-default}
_ENV_VAR_PATTERN = re.compile(r"\$\{([a-zA-Z_][a-zA-Z0-9_]*)(?::-([^}]*))?\}")


def _expand_env_vars(value: str, source: str | None = None) -> str:
    """Expand environment variables in a string value.

    Supports two syntaxes:
    - ``${VAR}`` - required variable, raises EnvVarError if not set
    - ``${VAR:-default}`` - optional variable with default value

    Args:
        value: String potentially containing ${VAR} patterns.
        source: Source file for error messages.

    Returns:
        String with environment variables expanded.

    Raises:
        EnvVarError: If required variable is not set.

    Examples:
        >>> import os
        >>> os.environ["TEST_VAR"] = "hello"
        >>> _expand_env_vars("${TEST_VAR} world")
        'hello world'
        >>> _expand_env_vars("${MISSING:-default}")
        'default'
    """
    import os

    def replacer(match: re.Match[str]) -> str:
        var_name = match.group(1)
        default_value = match.group(2)

        env_value = os.environ.get(var_name)
        if env_value is not None:
            return env_value

        if default_value is not None:
            return default_value

        raise EnvVarError(var_name, source)

    return _ENV_VAR_PATTERN.sub(replacer, value)


def _expand_env_vars_recursive(data: Any, source: str | None = None) -> Any:
    """Recursively expand environment variables in config data.

    Applies ``_expand_env_vars`` to all string values in dicts and lists.

    Args:
        data: Configuration data (dict, list, or scalar).
        source: Source file for error messages.

    Returns:
        Data with all environment variables expanded.

    Examples:
        >>> import os
        >>> os.environ["HOST"] = "example.com"
        >>> _expand_env_vars_recursive({"url": "https://${HOST}"})
        {'url': 'https://example.com'}
    """
    if isinstance(data, dict):
        return {k: _expand_env_vars_recursive(v, source) for k, v in data.items()}
    if isinstance(data, list):
        return [_expand_env_vars_recursive(item, source) for item in data]
    if isinstance(data, str):
        return _expand_env_vars(data, source)
    return data


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


@dataclass(frozen=True, slots=True)
class SafeguardConfig:
    """Global safeguard configuration for dangerous HTTP methods.

    Configures which HTTP methods require a safeguard (confirmation string)
    to be defined on endpoints. This is a safety mechanism to prevent
    accidental calls to destructive endpoints.

    Attributes:
        required_methods: HTTP methods that must have a safeguard configured.

    Examples:
        >>> config = SafeguardConfig()
        >>> "DELETE" in config.required_methods
        True
        >>> config = SafeguardConfig(required_methods=frozenset({"DELETE"}))
        >>> "PUT" in config.required_methods
        False
    """

    required_methods: frozenset[str] = field(default_factory=lambda: _DEFAULT_SAFEGUARD_METHODS)


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


def _merge_with_defaults(data: dict[str, Any], defaults: dict[str, Any] | None) -> dict[str, Any]:
    """Merge file data with defaults (file wins on conflict).

    Args:
        data: Configuration data from the file.
        defaults: Default values to apply.

    Returns:
        Merged configuration with file values taking precedence.
    """
    if not defaults:
        return data

    # Start with defaults, then overlay file data
    merged = dict(defaults)

    for key, value in data.items():
        if key == "headers" and isinstance(value, dict) and isinstance(merged.get("headers"), dict):
            # Merge headers dicts (file headers override default headers)
            merged["headers"] = {**merged["headers"], **value}
        elif key == "credentials" and isinstance(value, dict) and isinstance(merged.get("credentials"), dict):
            # Merge credentials dicts (file credentials override default credentials)
            merged["credentials"] = {**merged["credentials"], **value}
        else:
            # File value takes precedence
            merged[key] = value

    return merged


def _parse_rapi_file(
    path: Path,
    defaults: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
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

    With defaults support, a minimal file can inherit from kstlib.conf.yml:
    ```yaml
    name: github
    endpoints:
      user:
        path: "/user"
    ```

    Args:
        path: Path to the ``*.rapi.yml`` file.
        defaults: Default values inherited from kstlib.conf.yml rapi.defaults section.

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

    # Merge with defaults first (file wins on conflict)
    data = _merge_with_defaults(data, defaults)

    # Expand environment variables in all string values (after merge so defaults can use env vars too)
    data = _expand_env_vars_recursive(data, source=str(path))

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

    # Handle nested includes (relative to this file)
    include_patterns = data.get("include")
    if include_patterns:
        included_endpoints, included_creds = _resolve_rapi_includes(include_patterns, path.parent, defaults)
        # Merge included endpoints into this API
        api_config["api"][api_name]["endpoints"].update(included_endpoints)
        credentials_config.update(included_creds)
        log.debug(
            "Merged %d endpoints from includes into %s",
            len(included_endpoints),
            api_name,
        )

    return api_config, credentials_config


def _resolve_rapi_includes(
    patterns: list[str] | str,
    base_dir: Path,
    defaults: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve include patterns relative to a rapi file.

    Args:
        patterns: Include pattern(s) relative to base_dir.
        base_dir: Directory containing the parent rapi file.
        defaults: Default values to pass to included files.

    Returns:
        Tuple of (merged_endpoints, merged_credentials).
    """
    if isinstance(patterns, str):
        patterns = [patterns]

    merged_endpoints: dict[str, Any] = {}
    merged_credentials: dict[str, Any] = {}

    for pattern in patterns:
        # Resolve relative path (remove leading ./)
        clean_pattern = pattern.removeprefix("./")
        resolved_path = base_dir / clean_pattern

        # Support glob patterns or single file
        matches = (
            list(base_dir.glob(clean_pattern))
            if "*" in clean_pattern
            else ([resolved_path] if resolved_path.exists() else [])
        )

        for file_path in matches:
            if not file_path.exists():
                log.warning("Include file not found: %s", file_path)
                continue

            log.debug("Including nested file: %s", file_path.name)
            api_config, creds = _parse_rapi_file(file_path, defaults=defaults)

            # Extract endpoints from the included file (ignore API name)
            for api_data in api_config.get("api", {}).values():
                endpoints = api_data.get("endpoints", {})
                merged_endpoints.update(endpoints)

            merged_credentials.update(creds)

    return merged_endpoints, merged_credentials


def _check_endpoint_collisions(
    api_name: str,
    existing_api: dict[str, Any],
    api_data: dict[str, Any],
    path: Path,
    ctx: tuple[dict[str, list[str]], bool],
) -> None:
    """Check for endpoint collisions and warn or raise.

    Args:
        api_name: Name of the API.
        existing_api: Existing API data from previous files.
        api_data: New API data from current file.
        path: Current file path.
        ctx: Tuple of (endpoint_sources dict, strict flag).
    """
    endpoint_sources, strict = ctx
    existing_endpoints = set(existing_api.get("endpoints", {}).keys())
    new_endpoints = set(api_data.get("endpoints", {}).keys())
    collisions = existing_endpoints & new_endpoints

    for ep_name in collisions:
        full_ref = f"{api_name}.{ep_name}"
        if full_ref not in endpoint_sources:
            endpoint_sources[full_ref] = []
        endpoint_sources[full_ref].append(str(path))
        if strict:
            raise EndpointCollisionError(full_ref, endpoint_sources[full_ref])
        log.warning(
            "Endpoint '%s' redefined in %s, overwriting (use rapi.strict: true to error)",
            full_ref,
            path.name,
        )


def _merge_api_endpoints(
    api_name: str,
    existing_api: dict[str, Any],
    api_data: dict[str, Any],
    path: Path,
) -> None:
    """Merge endpoints from existing API with new API data.

    Args:
        api_name: Name of the API.
        existing_api: Existing API data from previous files.
        api_data: New API data from current file (modified in place).
        path: Current file path (for logging).
    """
    merged_endpoints = {**existing_api.get("endpoints", {}), **api_data.get("endpoints", {})}
    api_data["endpoints"] = merged_endpoints
    log.warning("API '%s' redefined in %s, merging endpoints", api_name, path.name)


def _track_endpoint_sources(
    api_name: str,
    api_data: dict[str, Any],
    path: Path,
    endpoint_sources: dict[str, list[str]],
) -> None:
    """Track endpoint sources for debugging.

    Args:
        api_name: Name of the API.
        api_data: API data from current file.
        path: Current file path.
        endpoint_sources: Tracking dict for endpoint sources.
    """
    for ep_name in api_data.get("endpoints", {}):
        full_ref = f"{api_name}.{ep_name}"
        if full_ref not in endpoint_sources:
            endpoint_sources[full_ref] = []
        if str(path) not in endpoint_sources[full_ref]:
            endpoint_sources[full_ref].append(str(path))


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
        description: Human-readable description of the endpoint.

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
    safeguard: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        """Validate safeguard field (deep defense)."""
        if self.safeguard is not None:
            if len(self.safeguard) > _MAX_SAFEGUARD_LENGTH:
                raise ValueError(f"safeguard too long: {len(self.safeguard)} > {_MAX_SAFEGUARD_LENGTH}")
            if not _SAFEGUARD_PATTERN.match(self.safeguard):
                raise ValueError(
                    f"safeguard contains invalid characters: {self.safeguard!r}. "
                    f"Allowed: A-Z, a-z, 0-9, _, -, space, {'{}'}, /"
                )

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

    def build_safeguard(self, *args: Any, **kwargs: Any) -> str | None:
        """Build safeguard string with variable substitution.

        Substitutes ``{param}`` placeholders in the safeguard string with
        provided arguments, similar to ``build_path``.

        Args:
            *args: Positional arguments for {0}, {1}, etc.
            **kwargs: Keyword arguments for {name} placeholders.

        Returns:
            Substituted safeguard string, or None if no safeguard configured.

        Examples:
            >>> config = EndpointConfig(
            ...     name="delete",
            ...     api_name="test",
            ...     path="/users/{userId}",
            ...     method="DELETE",
            ...     safeguard="DELETE USER {userId}",
            ... )
            >>> config.build_safeguard(userId="abc123")
            'DELETE USER abc123'
        """
        if self.safeguard is None:
            return None

        result = self.safeguard
        placeholders = _PATH_PARAM_PATTERN.findall(result)

        for placeholder in placeholders:
            if placeholder.isdigit():
                idx = int(placeholder)
                if idx < len(args):
                    result = result.replace(f"{{{placeholder}}}", str(args[idx]))
            elif placeholder in kwargs:
                result = result.replace(f"{{{placeholder}}}", str(kwargs[placeholder]))
            elif len(args) > 0:
                result = result.replace(f"{{{placeholder}}}", str(args[0]))
                args = args[1:]

        return result


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
        safeguard_config: SafeguardConfig | None = None,
        strict: bool = False,
    ) -> None:
        """Initialize RapiConfigManager.

        Args:
            rapi_config: The 'rapi' section from configuration.
            credentials_config: Inline credentials from ``*.rapi.yml`` files.
            safeguard_config: Safeguard configuration (default: DELETE and PUT require safeguard).
            strict: If True, raise error on endpoint collisions. If False, warn and overwrite.
        """
        self._config = rapi_config or {}
        self._credentials_config = dict(credentials_config) if credentials_config else {}
        self._safeguard_config = safeguard_config or SafeguardConfig()
        self._strict = strict
        self._apis: dict[str, ApiConfig] = {}
        self._endpoint_index: dict[str, list[str]] = {}  # endpoint_name -> [api_names]
        self._endpoint_sources: dict[str, str] = {}  # full_ref -> source file
        self._source_files: list[Path] = []  # Track loaded files for debugging

        self._load_apis()

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        base_dir: Path | None = None,
        safeguard_config: SafeguardConfig | None = None,
        defaults: dict[str, Any] | None = None,
        strict: bool = False,
    ) -> RapiConfigManager:
        """Load configuration from a single ``*.rapi.yml`` file.

        The file format is simplified compared to kstlib.conf.yml,
        with top-level keys: name, base_url, credentials, auth, headers, endpoints.

        Args:
            path: Path to the ``*.rapi.yml`` file.
            base_dir: Base directory for resolving relative paths in credentials.
            safeguard_config: Safeguard configuration (default: DELETE and PUT require safeguard).
            defaults: Default values inherited from kstlib.conf.yml rapi.defaults section.
            strict: If True, raise error on endpoint collisions. If False, warn and overwrite.

        Returns:
            Configured RapiConfigManager instance.

        Raises:
            FileNotFoundError: If file does not exist.
            ValueError: If file format is invalid.

        Examples:
            >>> manager = RapiConfigManager.from_file("github.rapi.yml")  # doctest: +SKIP
        """
        return cls.from_files(
            [path], base_dir=base_dir, safeguard_config=safeguard_config, defaults=defaults, strict=strict
        )

    @classmethod
    def from_files(
        cls,
        paths: Sequence[str | Path],
        base_dir: Path | None = None,
        safeguard_config: SafeguardConfig | None = None,
        defaults: dict[str, Any] | None = None,
        strict: bool = False,
    ) -> RapiConfigManager:
        """Load configuration from multiple ``*.rapi.yml`` files.

        Args:
            paths: List of paths to ``*.rapi.yml`` files.
            base_dir: Base directory for resolving relative paths.
            safeguard_config: Safeguard configuration (default: DELETE and PUT require safeguard).
            defaults: Default values inherited from kstlib.conf.yml rapi.defaults section.
                Supports: base_url, credentials, auth, headers.
            strict: If True, raise error on endpoint collisions. If False, warn and overwrite.

        Returns:
            Configured RapiConfigManager instance with merged configs.

        Raises:
            FileNotFoundError: If any file does not exist.
            ValueError: If any file format is invalid.
            EndpointCollisionError: If strict=True and endpoints collide.

        Examples:
            >>> manager = RapiConfigManager.from_files([
            ...     "github.rapi.yml",
            ...     "slack.rapi.yml",
            ... ])  # doctest: +SKIP
        """
        merged_api_config: dict[str, Any] = {"api": {}}
        merged_credentials: dict[str, Any] = {}
        source_files: list[Path] = []
        # Track endpoint sources: full_ref -> [source_files]
        endpoint_sources: dict[str, list[str]] = {}

        for file_path in paths:
            path = Path(file_path)
            if not path.is_absolute() and base_dir:
                path = base_dir / path

            if not path.exists():
                raise FileNotFoundError(f"RAPI config file not found: {path}")

            log.debug("Loading RAPI config from: %s", path)
            api_config, credentials = _parse_rapi_file(path, defaults=defaults)

            # Merge API config with collision detection
            collision_ctx = (endpoint_sources, strict)
            for api_name, api_data in api_config.get("api", {}).items():
                existing_api = merged_api_config["api"].get(api_name)
                if existing_api:
                    _check_endpoint_collisions(api_name, existing_api, api_data, path, collision_ctx)
                    _merge_api_endpoints(api_name, existing_api, api_data, path)

                _track_endpoint_sources(api_name, api_data, path, endpoint_sources)
                merged_api_config["api"][api_name] = api_data

            # Merge credentials
            merged_credentials.update(credentials)
            source_files.append(path)

        manager = cls(merged_api_config, merged_credentials, safeguard_config, strict=strict)
        manager._source_files = source_files
        # Store endpoint sources for debugging
        for full_ref, sources in endpoint_sources.items():
            if sources:
                manager._endpoint_sources[full_ref] = sources[0]
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

    @property
    def safeguard_config(self) -> SafeguardConfig:
        """Get safeguard configuration.

        Returns:
            SafeguardConfig instance.
        """
        return self._safeguard_config

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

                method = ep_data.get("method", "GET").upper()
                safeguard = ep_data.get("safeguard")

                endpoint = EndpointConfig(
                    name=ep_name,
                    api_name=api_name,
                    path=ep_data.get("path", f"/{ep_name}"),
                    method=method,
                    query=dict(ep_data.get("query", {})),
                    headers=dict(ep_data.get("headers", {})),
                    body_template=ep_data.get("body"),
                    auth=ep_data.get("auth", True),
                    safeguard=safeguard,
                    description=ep_data.get("description"),
                )

                # Validate safeguard requirement
                if method in self._safeguard_config.required_methods and safeguard is None:
                    raise SafeguardMissingError(endpoint.full_ref, method)

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
                self._handle_api_conflict(api_name, api_config, other)
                continue

            self._apis[api_name] = api_config
            self._update_endpoint_index(api_name, api_config)
            self._copy_endpoint_sources(api_name, api_config, other)

        # Merge credentials
        for cred_name, cred_config in other.credentials_config.items():
            if cred_name not in self._credentials_config:
                self._credentials_config[cred_name] = cred_config

    def _handle_api_conflict(
        self,
        api_name: str,
        api_config: ApiConfig,
        other: RapiConfigManager,
    ) -> None:
        """Handle API name conflict during merge.

        Args:
            api_name: Name of the conflicting API.
            api_config: The incoming API config.
            other: Source manager to merge from.
        """
        existing_endpoints = set(self._apis[api_name].endpoints.keys())
        new_endpoints = set(api_config.endpoints.keys())
        collisions = existing_endpoints & new_endpoints

        for ep_name in collisions:
            full_ref = f"{api_name}.{ep_name}"
            sources = ["inline config"]
            if full_ref in other._endpoint_sources:
                sources.append(other._endpoint_sources[full_ref])
            if self._strict:
                raise EndpointCollisionError(full_ref, sources)
            log.warning(
                "Endpoint '%s' in include conflicts with inline config, keeping inline",
                full_ref,
            )

        log.warning(
            "API '%s' in include conflicts with inline config, keeping inline",
            api_name,
        )

    def _update_endpoint_index(self, api_name: str, api_config: ApiConfig) -> None:
        """Update endpoint index for an API.

        Args:
            api_name: Name of the API.
            api_config: The API configuration.
        """
        for ep_name in api_config.endpoints:
            if ep_name not in self._endpoint_index:
                self._endpoint_index[ep_name] = []
            if api_name not in self._endpoint_index[ep_name]:
                self._endpoint_index[ep_name].append(api_name)

    def _copy_endpoint_sources(
        self,
        api_name: str,
        api_config: ApiConfig,
        other: RapiConfigManager,
    ) -> None:
        """Copy endpoint source tracking from another manager.

        Args:
            api_name: Name of the API.
            api_config: The API configuration.
            other: Source manager to copy from.
        """
        for ep_name in api_config.endpoints:
            full_ref = f"{api_name}.{ep_name}"
            if full_ref in other._endpoint_sources:
                self._endpoint_sources[full_ref] = other._endpoint_sources[full_ref]

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


def _parse_safeguard_config(rapi_section: dict[str, Any]) -> SafeguardConfig:
    """Parse safeguard configuration from rapi section.

    Args:
        rapi_section: The 'rapi' section from configuration.

    Returns:
        SafeguardConfig instance.
    """
    safeguard_data = rapi_section.get("safeguard", {})
    if not safeguard_data:
        return SafeguardConfig()

    required_methods = safeguard_data.get("required_methods")
    if required_methods is None:
        return SafeguardConfig()

    # Convert list to frozenset, uppercase all methods
    methods = frozenset(m.upper() for m in required_methods)
    return SafeguardConfig(required_methods=methods)


def load_rapi_config() -> RapiConfigManager:
    """Load RAPI configuration from kstlib.conf.yml with include support.

    Supports including external ``*.rapi.yml`` files via glob patterns,
    and a ``defaults`` section that is inherited by included files:

    .. code-block:: yaml

        rapi:
          # Strict mode: error on endpoint collisions (default: false = warn only)
          strict: true

          # Defaults inherited by all included *.rapi.yml files
          defaults:
            base_url: "https://${VIYA_HOST}"
            credentials:
              type: file
              path: ~/.sas/credentials.json
              token_path: ".Default['access-token']"
            auth: bearer
            headers:
              Accept: application/json

          include:
            - "./apis/*.rapi.yml"
            - "~/.config/kstlib/*.rapi.yml"

          safeguard:
            required_methods:
              - DELETE

          api:
            httpbin:
              base_url: "https://httpbin.org"
              # ...

    With defaults, included files can be minimal:

    .. code-block:: yaml

        # annotations.rapi.yml
        name: annotations
        headers:
          Accept: application/vnd.sas.annotation+json
        endpoints:
          root:
            path: /annotations/
            method: GET

    Returns:
        Configured RapiConfigManager instance with merged configs.

    Examples:
        >>> manager = load_rapi_config()  # doctest: +SKIP
    """
    from kstlib.config import get_config

    config = get_config()
    rapi_section = dict(config.get("rapi", {}))  # type: ignore[no-untyped-call]

    log.debug("Loading RAPI config from kstlib.conf.yml")

    # Extract strict mode (default: False = warn on collisions)
    strict = rapi_section.pop("strict", False)
    if strict:
        log.debug("Strict mode enabled: endpoint collisions will raise errors")

    # Extract defaults for included files
    defaults = rapi_section.pop("defaults", None)
    if defaults:
        log.debug("Found rapi.defaults section with keys: %s", list(defaults.keys()))

    # Process includes if present
    include_patterns = rapi_section.pop("include", None)

    # Parse safeguard config
    safeguard_config = _parse_safeguard_config(rapi_section)

    # Create manager for inline config first
    manager = RapiConfigManager(rapi_section, safeguard_config=safeguard_config, strict=strict)

    # Merge included files if any
    if include_patterns:
        included_files = _resolve_include_patterns(include_patterns)
        if included_files:
            log.info("Including %d external RAPI config file(s)", len(included_files))
            included_manager = RapiConfigManager.from_files(
                included_files,
                safeguard_config=safeguard_config,
                defaults=defaults,
                strict=strict,
            )
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
    "SafeguardConfig",
    "load_rapi_config",
]
