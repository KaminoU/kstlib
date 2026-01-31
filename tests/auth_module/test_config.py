"""Tests for auth config module."""

from __future__ import annotations

import pytest

from kstlib.auth.config import (
    DEFAULT_AUTH_CONFIG,
    build_provider_config,
    get_auth_config,
    get_callback_server_config,
    get_default_provider_name,
    get_provider_config,
    get_token_storage_from_config,
    list_configured_providers,
)
from kstlib.auth.errors import ConfigurationError
from kstlib.auth.providers.base import AuthProviderConfig
from kstlib.auth.token import MemoryTokenStorage, SOPSTokenStorage


class TestGetAuthConfig:
    """Tests for get_auth_config()."""

    def test_returns_defaults_without_config_file(self):
        """Should return DEFAULT_AUTH_CONFIG when no config loaded."""
        config = get_auth_config()

        assert config["token_storage"] == "memory"
        assert config["discovery_ttl"] == 3600
        assert config["callback_server"]["host"] == "127.0.0.1"
        assert config["callback_server"]["port"] == 8400

    def test_includes_all_default_keys(self):
        """Should include all keys from DEFAULT_AUTH_CONFIG."""
        config = get_auth_config()

        for key in DEFAULT_AUTH_CONFIG:
            assert key in config


class TestGetProviderConfig:
    """Tests for get_provider_config()."""

    def test_returns_none_for_missing_provider(self):
        """Should return None when provider doesn't exist."""
        result = get_provider_config("nonexistent")
        assert result is None

    def test_returns_provider_from_explicit_config(self):
        """Should return provider config from explicit dict."""
        config = {
            "providers": {
                "test": {
                    "client_id": "test-id",
                    "issuer": "https://test.example.com",
                }
            }
        }

        result = get_provider_config("test", config=config)

        assert result is not None
        assert result["client_id"] == "test-id"
        assert result["issuer"] == "https://test.example.com"


class TestGetCallbackServerConfig:
    """Tests for get_callback_server_config()."""

    def test_returns_defaults(self):
        """Should return default callback server config."""
        config = get_callback_server_config()

        assert config["host"] == "127.0.0.1"
        assert config["port"] == 8400
        assert config["timeout"] == 120

    def test_uses_explicit_config(self):
        """Should use values from explicit config."""
        config = get_callback_server_config(
            config={
                "callback_server": {
                    "host": "0.0.0.0",
                    "port": 9000,
                }
            }
        )

        assert config["host"] == "0.0.0.0"
        assert config["port"] == 9000


class TestGetTokenStorageFromConfig:
    """Tests for get_token_storage_from_config()."""

    def test_returns_memory_by_default(self):
        """Should return MemoryTokenStorage by default."""
        storage = get_token_storage_from_config()
        assert isinstance(storage, MemoryTokenStorage)

    def test_returns_memory_when_explicit(self):
        """Should return MemoryTokenStorage when explicitly specified."""
        storage = get_token_storage_from_config(storage_type="memory")
        assert isinstance(storage, MemoryTokenStorage)

    def test_returns_sops_storage(self, tmp_path):
        """Should return SOPSTokenStorage for sops type."""
        config = {
            "storage": {
                "sops": {
                    "directory": str(tmp_path / "tokens"),
                }
            }
        }
        storage = get_token_storage_from_config(storage_type="sops", config=config)
        assert isinstance(storage, SOPSTokenStorage)

    def test_file_storage_supported(self):
        """Should return FileTokenStorage for file storage type."""
        from kstlib.auth.token import FileTokenStorage

        storage = get_token_storage_from_config(storage_type="file")
        assert isinstance(storage, FileTokenStorage)

    def test_raises_for_invalid_type(self):
        """Should raise ConfigurationError for invalid storage type."""
        with pytest.raises(ConfigurationError, match="Unknown token storage"):
            get_token_storage_from_config(storage_type="invalid")


class TestBuildProviderConfig:
    """Tests for build_provider_config()."""

    def test_builds_oidc_provider_config(self):
        """Should build AuthProviderConfig from config dict."""
        config = {
            "providers": {
                "test": {
                    "type": "oidc",
                    "client_id": "test-client",
                    "issuer": "https://auth.example.com",
                    "scopes": ["openid", "profile"],
                    "pkce": True,
                }
            }
        }

        result = build_provider_config("test", config=config)

        assert isinstance(result, AuthProviderConfig)
        assert result.client_id == "test-client"
        assert result.issuer == "https://auth.example.com"
        assert "openid" in result.scopes
        assert result.pkce is True

    def test_applies_overrides(self):
        """Should apply explicit overrides over config values."""
        config = {
            "providers": {
                "test": {
                    "client_id": "original-id",
                    "issuer": "https://original.example.com",
                }
            }
        }

        result = build_provider_config(
            "test",
            config=config,
            client_id="override-id",
        )

        assert result.client_id == "override-id"
        assert result.issuer == "https://original.example.com"

    def test_raises_for_missing_client_id(self):
        """Should raise ConfigurationError when client_id is missing."""
        config = {
            "providers": {
                "test": {
                    "issuer": "https://auth.example.com",
                    # Missing client_id
                }
            }
        }

        with pytest.raises(ConfigurationError, match="missing required 'client_id'"):
            build_provider_config("test", config=config)

    def test_raises_for_missing_endpoints(self):
        """Should raise ConfigurationError when endpoints are missing."""
        config = {
            "providers": {
                "test": {
                    "client_id": "test-client",
                    # Missing issuer and endpoints
                }
            }
        }

        with pytest.raises(ConfigurationError, match="requires either 'issuer'"):
            build_provider_config("test", config=config)


class TestListConfiguredProviders:
    """Tests for list_configured_providers()."""

    def test_returns_empty_by_default(self):
        """Should return empty list when no providers configured."""
        # Use explicit empty config to avoid global config pollution
        providers = list_configured_providers(config={"providers": {}})
        assert providers == []

    def test_returns_provider_names_from_config(self):
        """Should return list of provider names from config."""
        config = {
            "providers": {
                "google": {"client_id": "google-id"},
                "github": {"client_id": "github-id"},
            }
        }

        providers = list_configured_providers(config=config)

        assert "google" in providers
        assert "github" in providers
        assert len(providers) == 2


class TestGetDefaultProviderName:
    """Tests for get_default_provider_name()."""

    def test_returns_none_by_default(self):
        """Should return None when no default provider set."""
        result = get_default_provider_name()
        assert result is None

    def test_returns_default_from_config(self):
        """Should return default provider name from config."""
        config = {"default_provider": "corporate"}

        result = get_default_provider_name(config=config)

        assert result == "corporate"
