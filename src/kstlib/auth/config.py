"""Configuration loading for the auth module.

This module provides helpers to load and parse auth configuration from
kstlib.conf.yml, following the config-driven pattern used by other modules.

Configuration hierarchy (lowest to highest priority):
    1. Default values in kstlib.conf.yml
    2. User config file overrides
    3. Explicit constructor parameters

Example:
    >>> from kstlib.auth.config import get_auth_config
    >>> auth_config = get_auth_config()
    >>> auth_config["token_storage"]
    'memory'
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from kstlib.auth.errors import ConfigurationError
from kstlib.logging import TRACE_LEVEL, get_logger
from kstlib.utils.dict import deep_merge

if TYPE_CHECKING:
    from collections.abc import Mapping

    from kstlib.auth.providers.base import AuthProviderConfig
    from kstlib.auth.token import AbstractTokenStorage

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Default values (fallback when no config file is loaded)
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_AUTH_CONFIG: dict[str, Any] = {
    "default_provider": None,
    "token_storage": "memory",  # "memory", "file", or "sops"
    "discovery_ttl": 3600,
    "callback_server": {
        "host": "127.0.0.1",
        "port": 8400,
        "port_range": None,
        "timeout": 120,
    },
    "storage": {
        "file": {
            "directory": "~/.config/kstlib/auth/tokens",
        },
        "sops": {
            "directory": "~/.config/kstlib/auth/tokens",
        },
    },
    "status": {
        "expiring_soon_threshold": 300,  # seconds (5 min) - hard min: 60s
        "refresh_expiring_soon_threshold": 600,  # seconds (10 min) - hard min: 60s
        "display_timezone": "local",  # "local" or "utc"
    },
    "providers": {},
}

# Hard limits for status display (defense in depth)
_STATUS_EXPIRING_SOON_MIN = 60  # Minimum threshold: 60 seconds
_STATUS_EXPIRING_SOON_MAX = 3600  # Maximum threshold: 1 hour (for access tokens)
_STATUS_REFRESH_EXPIRING_SOON_MAX = 172800  # Maximum threshold: 48 hours (for refresh tokens)


# ─────────────────────────────────────────────────────────────────────────────
# Config loading helpers
# ─────────────────────────────────────────────────────────────────────────────


def get_auth_config() -> dict[str, Any]:
    """Load the auth configuration section from global config.

    Falls back to DEFAULT_AUTH_CONFIG if no config file is loaded or
    the auth section is missing.

    Returns:
        Auth configuration dictionary.

    Example:
        >>> config = get_auth_config()
        >>> config["token_storage"]
        'memory'
    """
    try:
        from kstlib.config import get_config
        from kstlib.config.exceptions import ConfigNotLoadedError

        global_config = get_config()
        auth_section = global_config.get("auth") if global_config else None  # type: ignore[no-untyped-call]

        if auth_section:
            # Merge with defaults for missing keys
            result = {**DEFAULT_AUTH_CONFIG}
            deep_merge(result, dict(auth_section))
            return result

    except (ConfigNotLoadedError, ImportError, FileNotFoundError):
        logger.debug("No config file loaded, using auth defaults")

    return dict(DEFAULT_AUTH_CONFIG)


def get_provider_config(
    provider_name: str,
    *,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Get configuration for a specific auth provider.

    Args:
        provider_name: Name of the provider to look up.
        config: Optional explicit config dict (overrides global).

    Returns:
        Provider configuration dict, or None if not found.

    Example:
        >>> cfg = get_provider_config("nonexistent")
        >>> cfg is None
        True
    """
    auth_config = dict(config) if config else get_auth_config()
    providers = auth_config.get("providers", {})

    if isinstance(providers, dict):
        return dict(providers.get(provider_name, {})) or None

    # Handle legacy list format (unlikely but defensive)
    if isinstance(providers, list):
        for p in providers:
            if isinstance(p, dict) and p.get("name") == provider_name:
                return dict(p)

    return None


def get_callback_server_config(
    *,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Get callback server configuration.

    Args:
        config: Optional explicit config dict.

    Returns:
        Callback server configuration with defaults applied.
    """
    auth_config = dict(config) if config else get_auth_config()
    callback_cfg = auth_config.get("callback_server", {})
    defaults = DEFAULT_AUTH_CONFIG["callback_server"]

    return {
        "host": callback_cfg.get("host", defaults["host"]),
        "port": callback_cfg.get("port", defaults["port"]),
        "port_range": callback_cfg.get("port_range", defaults["port_range"]),
        "timeout": callback_cfg.get("timeout", defaults["timeout"]),
    }


def get_status_config(
    *,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Get status display configuration with hard limits enforced.

    Args:
        config: Optional explicit config dict.

    Returns:
        Status configuration with validated values.

    Example:
        >>> cfg = get_status_config()
        >>> cfg["expiring_soon_threshold"]
        120
        >>> cfg["display_timezone"]
        'local'
    """
    auth_config = dict(config) if config else get_auth_config()
    status_cfg = auth_config.get("status", {})
    defaults = DEFAULT_AUTH_CONFIG["status"]

    # Get access token threshold with hard limits
    threshold = status_cfg.get("expiring_soon_threshold", defaults["expiring_soon_threshold"])
    threshold = max(_STATUS_EXPIRING_SOON_MIN, min(_STATUS_EXPIRING_SOON_MAX, int(threshold)))

    # Get refresh token threshold with hard limits (higher max since refresh tokens live longer)
    refresh_threshold = status_cfg.get(
        "refresh_expiring_soon_threshold",
        defaults["refresh_expiring_soon_threshold"],
    )
    refresh_threshold = max(
        _STATUS_EXPIRING_SOON_MIN,
        min(_STATUS_REFRESH_EXPIRING_SOON_MAX, int(refresh_threshold)),
    )

    # Get timezone (validate allowed values)
    tz_display = status_cfg.get("display_timezone", defaults["display_timezone"])
    if tz_display not in ("local", "utc"):
        tz_display = "local"

    return {
        "expiring_soon_threshold": threshold,
        "refresh_expiring_soon_threshold": refresh_threshold,
        "display_timezone": tz_display,
    }


def get_token_storage_from_config(
    *,
    storage_type: str | None = None,
    provider_name: str | None = None,
    config: Mapping[str, Any] | None = None,
) -> AbstractTokenStorage:
    """Create a token storage instance based on configuration.

    Priority for storage_type:
        1. Explicit storage_type parameter
        2. Provider-specific token_storage setting
        3. Global auth.token_storage setting

    Args:
        storage_type: Explicit storage type override.
        provider_name: Provider name to check for specific settings.
        config: Optional explicit config dict.

    Returns:
        Configured token storage instance.

    Raises:
        ConfigurationError: If storage type is invalid.
    """
    from kstlib.auth.token import get_token_storage

    auth_config = dict(config) if config else get_auth_config()

    # Determine storage type
    resolved_type = storage_type

    if resolved_type is None and provider_name:
        provider_cfg = get_provider_config(provider_name, config=auth_config)
        if provider_cfg:
            resolved_type = provider_cfg.get("token_storage")

    if resolved_type is None:
        resolved_type = auth_config.get("token_storage", "memory")

    if logger.isEnabledFor(TRACE_LEVEL):
        logger.log(
            TRACE_LEVEL,
            "[CONFIG] Token storage type resolved: %s (provider=%s)",
            resolved_type,
            provider_name or "global",
        )

    # Get storage-specific settings
    storage_settings = auth_config.get("storage", {})

    try:
        if resolved_type == "memory":
            return get_token_storage("memory")

        if resolved_type == "file":
            file_cfg = storage_settings.get("file", {})
            directory = file_cfg.get("directory", DEFAULT_AUTH_CONFIG["storage"]["file"]["directory"])
            directory = Path(directory).expanduser()
            return get_token_storage("file", directory=directory)

        if resolved_type == "sops":
            sops_cfg = storage_settings.get("sops", {})
            directory = Path(sops_cfg.get("directory", DEFAULT_AUTH_CONFIG["storage"]["sops"]["directory"]))
            directory = directory.expanduser()
            return get_token_storage("sops", directory=directory)

        msg = f"Unknown token storage type: {resolved_type}. Use 'memory', 'file', or 'sops'."
        raise ConfigurationError(msg)

    except Exception as e:
        if isinstance(e, ConfigurationError):
            raise
        msg = f"Failed to create token storage '{resolved_type}': {e}"
        raise ConfigurationError(msg) from e


# ─────────────────────────────────────────────────────────────────────────────
# AuthProviderConfig builder
# ─────────────────────────────────────────────────────────────────────────────


def build_provider_config(
    provider_name: str,
    *,
    config: Mapping[str, Any] | None = None,
    **overrides: Any,
) -> AuthProviderConfig:
    """Build an AuthProviderConfig from configuration.

    Merges global defaults, provider-specific config, and explicit overrides.

    Args:
        provider_name: Name of the provider in config.
        config: Optional explicit config dict.
        **overrides: Direct overrides (highest priority).

    Returns:
        Configured AuthProviderConfig instance.

    Raises:
        ConfigurationError: If required fields are missing.

    Example:
        >>> cfg = build_provider_config("keycloak", client_id="my-app")  # doctest: +SKIP
    """
    from kstlib.auth.providers.base import AuthProviderConfig

    auth_config = dict(config) if config else get_auth_config()
    provider_cfg = get_provider_config(provider_name, config=auth_config) or {}
    callback_cfg = get_callback_server_config(config=auth_config)

    if logger.isEnabledFor(TRACE_LEVEL):
        logger.log(
            TRACE_LEVEL,
            "[CONFIG] Building provider config for '%s' | overrides=%s",
            provider_name,
            list(overrides) if overrides else [],
        )

    # Merge: provider config < overrides
    merged = {**provider_cfg, **overrides}

    # Validate required fields
    if not merged.get("client_id"):
        raise ConfigurationError(f"Provider '{provider_name}' missing required 'client_id'")

    # Resolve client_secret (may be SOPS reference)
    client_secret = merged.get("client_secret")
    if client_secret and isinstance(client_secret, str) and client_secret.startswith("sops://"):
        client_secret = _resolve_sops_secret(client_secret)

    # Determine endpoints (OIDC issuer or explicit OAuth2 URLs)
    issuer = merged.get("issuer")
    authorize_url = merged.get("authorization_endpoint") or merged.get("authorize_url")
    token_url = merged.get("token_endpoint") or merged.get("token_url")

    if not issuer and not (authorize_url and token_url):
        raise ConfigurationError(
            f"Provider '{provider_name}' requires either 'issuer' (OIDC) or "
            f"both 'authorization_endpoint' and 'token_endpoint' (OAuth2)"
        )

    # Normalize scopes: ensure it's always a list (YAML may parse as string)
    scopes_raw = merged.get("scopes", ["openid", "profile", "email"])
    if isinstance(scopes_raw, str):
        # Single scope as string, or space-separated scopes
        scopes = scopes_raw.split() if " " in scopes_raw else [scopes_raw]
    else:
        scopes = list(scopes_raw) if scopes_raw else ["openid", "profile", "email"]

    # Normalize redirect_uri: ensure it's a string (YAML may parse as list by mistake)
    redirect_uri_raw = merged.get("redirect_uri")
    if isinstance(redirect_uri_raw, list | tuple):
        redirect_uri = str(redirect_uri_raw[0]) if redirect_uri_raw else None
    elif redirect_uri_raw:
        redirect_uri = str(redirect_uri_raw)
    else:
        redirect_uri = None

    return AuthProviderConfig(
        client_id=merged["client_id"],
        client_secret=client_secret,
        issuer=issuer,
        authorize_url=authorize_url,
        token_url=token_url,
        revoke_url=merged.get("revocation_endpoint") or merged.get("revoke_url"),
        userinfo_url=merged.get("userinfo_endpoint") or merged.get("userinfo_url"),
        jwks_uri=merged.get("jwks_uri"),
        end_session_endpoint=merged.get("end_session_endpoint"),
        scopes=scopes,
        redirect_uri=redirect_uri or f"http://{callback_cfg['host']}:{callback_cfg['port']}/callback",
        pkce=merged.get("pkce", True),
        discovery_ttl=merged.get("discovery_ttl", auth_config.get("discovery_ttl", 3600)),
        headers=merged.get("headers", {}),
        # SSL/TLS options
        ssl_verify=merged.get("ssl_verify", True),
        ssl_ca_bundle=merged.get("ssl_ca_bundle"),
        extra=merged.get("extra", {}),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Utility functions
# ─────────────────────────────────────────────────────────────────────────────


def _resolve_sops_secret(sops_uri: str) -> str | None:
    """Resolve a SOPS secret reference.

    Format: sops://path/to/file.yaml#key.path

    Args:
        sops_uri: SOPS URI to resolve.

    Returns:
        Resolved secret value, or None if resolution fails.
    """
    if logger.isEnabledFor(TRACE_LEVEL):
        # Log path but not the key (could reveal structure)
        safe_uri = sops_uri.split("#")[0] if "#" in sops_uri else sops_uri
        logger.log(TRACE_LEVEL, "[CONFIG] Resolving SOPS secret: %s", safe_uri)

    try:
        from kstlib.secrets import resolve_secret

        # Parse sops://path#key format
        if not sops_uri.startswith("sops://"):
            return sops_uri

        remainder = sops_uri[7:]  # Remove "sops://"
        if "#" in remainder:
            path, key = remainder.rsplit("#", 1)
        else:
            path, key = remainder, None

        # Resolve via secrets module
        result = resolve_secret(f"sops:{path}", key=key)

        if logger.isEnabledFor(TRACE_LEVEL):
            logger.log(TRACE_LEVEL, "[CONFIG] SOPS secret resolved successfully")

        return str(result) if result else None

    except Exception as e:  # pylint: disable=broad-exception-caught
        # Graceful fallback for secret resolution
        logger.warning("Failed to resolve SOPS secret '%s': %s", sops_uri, e)
        return None


def list_configured_providers(
    *,
    config: Mapping[str, Any] | None = None,
) -> list[str]:
    """List all configured provider names.

    Args:
        config: Optional explicit config dict.

    Returns:
        List of provider names.
    """
    auth_config = dict(config) if config else get_auth_config()
    providers = auth_config.get("providers", {})

    if isinstance(providers, dict):
        return list(providers)

    # Legacy list format
    if isinstance(providers, list):
        names: list[str] = []
        for p in providers:
            if isinstance(p, dict):
                name = p.get("name")
                if name and isinstance(name, str):
                    names.append(name)
        return names

    return []


def get_default_provider_name(
    *,
    config: Mapping[str, Any] | None = None,
) -> str | None:
    """Get the default provider name from config.

    Args:
        config: Optional explicit config dict.

    Returns:
        Default provider name, or None if not set.
    """
    auth_config = dict(config) if config else get_auth_config()
    return auth_config.get("default_provider")


__all__ = [
    "DEFAULT_AUTH_CONFIG",
    "build_provider_config",
    "get_auth_config",
    "get_callback_server_config",
    "get_default_provider_name",
    "get_provider_config",
    "get_status_config",
    "get_token_storage_from_config",
    "list_configured_providers",
]
