"""Unit tests for auth config module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kstlib.auth.config import (
    DEFAULT_AUTH_CONFIG,
    _resolve_sops_secret,
    build_provider_config,
    get_auth_config,
    get_callback_server_config,
    get_default_provider_name,
    get_provider_config,
    get_status_config,
    get_token_storage_from_config,
    list_configured_providers,
)
from kstlib.auth.errors import ConfigurationError
from kstlib.utils.dict import deep_merge

# ─────────────────────────────────────────────────────────────────────────────
# Test get_auth_config
# ─────────────────────────────────────────────────────────────────────────────


class TestGetAuthConfig:
    """Tests for get_auth_config()."""

    def test_returns_defaults_when_no_config(self) -> None:
        """Test returns defaults when no config is loaded."""
        with patch("kstlib.config.get_config", side_effect=ImportError):
            config = get_auth_config()

        assert config["token_storage"] == "memory"
        assert config["discovery_ttl"] == 3600

    def test_merges_with_defaults(self) -> None:
        """Test merges loaded config with defaults."""
        mock_config = MagicMock()
        mock_config.get.return_value = {"token_storage": "sops", "providers": {"test": {}}}

        with patch("kstlib.config.get_config", return_value=mock_config):
            config = get_auth_config()

        assert config["token_storage"] == "sops"
        assert config["discovery_ttl"] == 3600  # From defaults
        assert "test" in config["providers"]

    def test_handles_config_not_loaded_error(self) -> None:
        """Test handles ConfigNotLoadedError gracefully."""
        from kstlib.config.exceptions import ConfigNotLoadedError

        with patch("kstlib.config.get_config", side_effect=ConfigNotLoadedError("test")):
            config = get_auth_config()

        assert config == DEFAULT_AUTH_CONFIG


# ─────────────────────────────────────────────────────────────────────────────
# Test get_provider_config
# ─────────────────────────────────────────────────────────────────────────────


class TestGetProviderConfig:
    """Tests for get_provider_config()."""

    def test_returns_none_for_missing_provider(self) -> None:
        """Test returns None when provider not found."""
        config = {"providers": {"other": {"client_id": "test"}}}
        result = get_provider_config("missing", config=config)
        assert result is None

    def test_returns_provider_config(self) -> None:
        """Test returns provider configuration."""
        config = {"providers": {"test": {"client_id": "my-app", "issuer": "https://example.com"}}}
        result = get_provider_config("test", config=config)

        assert result is not None
        assert result["client_id"] == "my-app"

    def test_handles_legacy_list_format(self) -> None:
        """Test handles legacy list format for providers."""
        config = {
            "providers": [
                {"name": "first", "client_id": "first-app"},
                {"name": "second", "client_id": "second-app"},
            ]
        }

        result = get_provider_config("second", config=config)

        assert result is not None
        assert result["client_id"] == "second-app"

    def test_legacy_list_format_not_found(self) -> None:
        """Test returns None when provider not found in legacy list format."""
        config = {
            "providers": [
                {"name": "first", "client_id": "first-app"},
                {"name": "second", "client_id": "second-app"},
            ]
        }

        result = get_provider_config("missing", config=config)

        assert result is None

    def test_returns_none_for_empty_provider(self) -> None:
        """Test returns None for empty provider config."""
        config = {"providers": {"empty": {}}}
        result = get_provider_config("empty", config=config)
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# Test get_callback_server_config
# ─────────────────────────────────────────────────────────────────────────────


class TestGetCallbackServerConfig:
    """Tests for get_callback_server_config()."""

    def test_returns_defaults(self) -> None:
        """Test returns default callback server config."""
        config = get_callback_server_config(config={})

        assert config["host"] == "127.0.0.1"
        assert config["port"] == 8400
        assert config["timeout"] == 120

    def test_overrides_defaults(self) -> None:
        """Test overrides defaults with config values."""
        config = get_callback_server_config(config={"callback_server": {"host": "localhost", "port": 9000}})

        assert config["host"] == "localhost"
        assert config["port"] == 9000
        assert config["timeout"] == 120  # Still default


# ─────────────────────────────────────────────────────────────────────────────
# Test get_status_config
# ─────────────────────────────────────────────────────────────────────────────


class TestGetStatusConfig:
    """Tests for get_status_config()."""

    def test_returns_defaults_from_default_config(self) -> None:
        """Test returns values from DEFAULT_AUTH_CONFIG when status section is empty."""
        # When passing config with empty status, defaults come from DEFAULT_AUTH_CONFIG
        config = get_status_config(config={"status": {}})

        # These values come from DEFAULT_AUTH_CONFIG["status"] defaults
        # Note: the actual values in DEFAULT_AUTH_CONFIG are:
        # expiring_soon_threshold: 300, refresh_expiring_soon_threshold: 600
        assert config["expiring_soon_threshold"] == DEFAULT_AUTH_CONFIG["status"]["expiring_soon_threshold"]
        assert (
            config["refresh_expiring_soon_threshold"]
            == DEFAULT_AUTH_CONFIG["status"]["refresh_expiring_soon_threshold"]
        )
        assert config["display_timezone"] == "local"

    def test_overrides_with_custom_values(self) -> None:
        """Test overrides defaults with custom values."""
        config = get_status_config(
            config={
                "status": {
                    "expiring_soon_threshold": 500,
                    "refresh_expiring_soon_threshold": 7200,
                    "display_timezone": "utc",
                }
            }
        )

        assert config["expiring_soon_threshold"] == 500
        assert config["refresh_expiring_soon_threshold"] == 7200
        assert config["display_timezone"] == "utc"

    def test_enforces_minimum_threshold(self) -> None:
        """Test enforces minimum threshold for expiring_soon."""
        # Hard minimum is 60 seconds (_STATUS_EXPIRING_SOON_MIN)
        config = get_status_config(config={"status": {"expiring_soon_threshold": 5}})

        assert config["expiring_soon_threshold"] == 60

    def test_enforces_maximum_threshold(self) -> None:
        """Test enforces maximum threshold for expiring_soon."""
        # Hard maximum is 3600 seconds for access tokens (_STATUS_EXPIRING_SOON_MAX)
        config = get_status_config(config={"status": {"expiring_soon_threshold": 99999}})

        assert config["expiring_soon_threshold"] == 3600

    def test_enforces_refresh_threshold_limits(self) -> None:
        """Test enforces limits for refresh_expiring_soon_threshold."""
        # Maximum is 172800 for refresh tokens (_STATUS_REFRESH_EXPIRING_SOON_MAX)
        config = get_status_config(config={"status": {"refresh_expiring_soon_threshold": 999999}})

        assert config["refresh_expiring_soon_threshold"] == 172800

    def test_invalid_timezone_falls_back_to_local(self) -> None:
        """Test invalid timezone falls back to local."""
        config = get_status_config(config={"status": {"display_timezone": "invalid"}})

        assert config["display_timezone"] == "local"

    def test_loads_from_global_config_when_no_explicit_config(self) -> None:
        """Test loads from global config when no explicit config provided."""
        with patch(
            "kstlib.auth.config.get_auth_config",
            return_value={"status": {"expiring_soon_threshold": 800}},
        ):
            config = get_status_config()

        assert config["expiring_soon_threshold"] == 800


# ─────────────────────────────────────────────────────────────────────────────
# Test get_token_storage_from_config
# ─────────────────────────────────────────────────────────────────────────────


class TestGetTokenStorageFromConfig:
    """Tests for get_token_storage_from_config()."""

    def test_creates_memory_storage(self) -> None:
        """Test creates memory storage."""
        storage = get_token_storage_from_config(storage_type="memory")

        from kstlib.auth.token import MemoryTokenStorage

        assert isinstance(storage, MemoryTokenStorage)

    def test_uses_provider_specific_storage(self) -> None:
        """Test uses provider-specific storage setting."""
        config = {
            "token_storage": "sops",  # Global default
            "providers": {"test": {"token_storage": "memory"}},  # Provider-specific
        }

        storage = get_token_storage_from_config(provider_name="test", config=config)

        from kstlib.auth.token import MemoryTokenStorage

        assert isinstance(storage, MemoryTokenStorage)

    def test_raises_for_unknown_storage_type(self) -> None:
        """Test raises ConfigurationError for unknown storage type."""
        with pytest.raises(ConfigurationError, match="Unknown token storage type"):
            get_token_storage_from_config(storage_type="invalid")

    def test_wraps_storage_creation_errors(self) -> None:
        """Test wraps errors during storage creation."""
        with (
            patch("kstlib.auth.token.get_token_storage", side_effect=ValueError("Creation failed")),
            pytest.raises(ConfigurationError, match="Failed to create token storage"),
        ):
            get_token_storage_from_config(storage_type="memory")

    def test_file_storage_uses_custom_directory(self, tmp_path: Path) -> None:
        """Test file storage uses custom directory from config."""
        custom_dir = tmp_path / "custom_tokens"
        config = {
            "token_storage": "file",
            "storage": {
                "file": {
                    "directory": str(custom_dir),
                },
            },
        }

        storage = get_token_storage_from_config(storage_type="file", config=config)

        from kstlib.auth.token import FileTokenStorage

        assert isinstance(storage, FileTokenStorage)
        assert storage.directory == custom_dir

    def test_file_storage_uses_default_directory_when_not_specified(self) -> None:
        """Test file storage uses default directory when not specified in config."""
        config = {"token_storage": "file"}

        storage = get_token_storage_from_config(storage_type="file", config=config)

        from kstlib.auth.token import FileTokenStorage

        assert isinstance(storage, FileTokenStorage)
        expected_default = Path("~/.config/kstlib/auth/tokens").expanduser()
        assert storage.directory == expected_default


# ─────────────────────────────────────────────────────────────────────────────
# Test build_provider_config
# ─────────────────────────────────────────────────────────────────────────────


class TestBuildProviderConfig:
    """Tests for build_provider_config()."""

    def test_builds_oidc_config(self) -> None:
        """Test builds OIDC config from provider settings."""
        config = {
            "providers": {
                "test": {
                    "client_id": "my-app",
                    "issuer": "https://auth.example.com",
                    "scopes": ["openid", "profile"],
                }
            }
        }

        result = build_provider_config("test", config=config)

        assert result.client_id == "my-app"
        assert result.issuer == "https://auth.example.com"
        assert result.scopes == ["openid", "profile"]

    def test_builds_oauth2_config(self) -> None:
        """Test builds OAuth2 config with explicit endpoints."""
        config = {
            "providers": {
                "github": {
                    "client_id": "github-app",
                    "authorization_endpoint": "https://github.com/login/oauth/authorize",
                    "token_endpoint": "https://github.com/login/oauth/access_token",
                }
            }
        }

        result = build_provider_config("github", config=config)

        assert result.client_id == "github-app"
        assert result.authorize_url == "https://github.com/login/oauth/authorize"
        assert result.token_url == "https://github.com/login/oauth/access_token"

    def test_raises_for_missing_client_id(self) -> None:
        """Test raises ConfigurationError when client_id is missing."""
        config = {"providers": {"test": {"issuer": "https://example.com"}}}

        with pytest.raises(ConfigurationError, match="missing required 'client_id'"):
            build_provider_config("test", config=config)

    def test_raises_for_missing_endpoints(self) -> None:
        """Test raises when neither issuer nor endpoints are provided."""
        config = {"providers": {"test": {"client_id": "app"}}}

        with pytest.raises(ConfigurationError, match="requires either 'issuer'"):
            build_provider_config("test", config=config)

    def test_overrides_take_precedence(self) -> None:
        """Test that overrides take precedence over config."""
        config = {
            "providers": {
                "test": {
                    "client_id": "config-app",
                    "issuer": "https://config.example.com",
                }
            }
        }

        result = build_provider_config("test", config=config, client_id="override-app")

        assert result.client_id == "override-app"

    def test_resolves_sops_secret(self) -> None:
        """Test resolves SOPS secret reference for client_secret."""
        config = {
            "providers": {
                "test": {
                    "client_id": "app",
                    "issuer": "https://example.com",
                    "client_secret": "sops://secrets.yaml#auth.secret",
                }
            }
        }

        with patch("kstlib.auth.config._resolve_sops_secret", return_value="resolved-secret"):
            result = build_provider_config("test", config=config)

        assert result.client_secret == "resolved-secret"

    def test_builds_redirect_uri_from_callback_config(self) -> None:
        """Test builds redirect_uri from callback server config."""
        config = {
            "callback_server": {"host": "localhost", "port": 9000},
            "providers": {"test": {"client_id": "app", "issuer": "https://example.com"}},
        }

        result = build_provider_config("test", config=config)

        assert result.redirect_uri == "http://localhost:9000/callback"


# ─────────────────────────────────────────────────────────────────────────────
# Test _resolve_sops_secret
# ─────────────────────────────────────────────────────────────────────────────


class TestResolveSopsSecret:
    """Tests for _resolve_sops_secret()."""

    def test_returns_non_sops_uri_unchanged(self) -> None:
        """Test returns non-SOPS URI unchanged."""
        result = _resolve_sops_secret("plain-secret")
        assert result == "plain-secret"

    def test_resolves_sops_uri_with_key(self) -> None:
        """Test resolves SOPS URI with key path."""
        with patch("kstlib.secrets.resolve_secret", return_value="secret-value"):
            result = _resolve_sops_secret("sops://secrets.yaml#auth.password")

        assert result == "secret-value"

    def test_resolves_sops_uri_without_key(self) -> None:
        """Test resolves SOPS URI without key path."""
        with patch("kstlib.secrets.resolve_secret", return_value="full-file"):
            result = _resolve_sops_secret("sops://secrets.yaml")

        assert result == "full-file"

    def test_returns_none_on_resolution_failure(self) -> None:
        """Test returns None when resolution fails."""
        with patch("kstlib.secrets.resolve_secret", side_effect=Exception("Failed")):
            result = _resolve_sops_secret("sops://invalid.yaml#key")

        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# Test list_configured_providers
# ─────────────────────────────────────────────────────────────────────────────


class TestListConfiguredProviders:
    """Tests for list_configured_providers()."""

    def test_returns_provider_names_from_dict(self) -> None:
        """Test returns provider names from dict format."""
        config = {"providers": {"keycloak": {}, "github": {}, "google": {}}}

        result = list_configured_providers(config=config)

        assert set(result) == {"keycloak", "github", "google"}

    def test_returns_provider_names_from_list(self) -> None:
        """Test returns provider names from legacy list format."""
        config = {
            "providers": [
                {"name": "keycloak", "client_id": "app1"},
                {"name": "github", "client_id": "app2"},
            ]
        }

        result = list_configured_providers(config=config)

        assert result == ["keycloak", "github"]

    def test_returns_empty_list_when_no_providers(self) -> None:
        """Test returns empty list when no providers configured."""
        config = {"providers": {}}

        result = list_configured_providers(config=config)

        assert result == []

    def test_returns_empty_list_for_invalid_providers_type(self) -> None:
        """Test returns empty list when providers is neither dict nor list."""
        config = {"providers": "invalid"}

        result = list_configured_providers(config=config)

        assert result == []

    def test_legacy_list_skips_invalid_entries(self) -> None:
        """Test skips entries without name in legacy list format."""
        config = {
            "providers": [
                {"name": "valid", "client_id": "app"},
                {"client_id": "no-name"},  # Missing name
                "not-a-dict",  # Invalid entry
            ]
        }

        result = list_configured_providers(config=config)

        assert result == ["valid"]


# ─────────────────────────────────────────────────────────────────────────────
# Test get_default_provider_name
# ─────────────────────────────────────────────────────────────────────────────


class TestGetDefaultProviderName:
    """Tests for get_default_provider_name()."""

    def test_returns_default_provider(self) -> None:
        """Test returns configured default provider."""
        config = {"default_provider": "corporate"}

        result = get_default_provider_name(config=config)

        assert result == "corporate"

    def test_returns_none_when_not_set(self) -> None:
        """Test returns None when no default is set."""
        config = {}

        result = get_default_provider_name(config=config)

        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# Test deep_merge
# ─────────────────────────────────────────────────────────────────────────────


class TestDeepMerge:
    """Tests for deep_merge()."""

    def test_merges_nested_dicts(self) -> None:
        """Test deep merges nested dictionaries."""
        base = {"a": {"b": 1, "c": 2}, "d": 3}
        updates = {"a": {"b": 10, "e": 5}}

        deep_merge(base, updates)

        assert base == {"a": {"b": 10, "c": 2, "e": 5}, "d": 3}

    def test_overwrites_non_dict_values(self) -> None:
        """Test overwrites non-dict values."""
        base = {"a": 1, "b": {"c": 2}}
        updates = {"a": 100, "b": "replaced"}

        deep_merge(base, updates)

        assert base == {"a": 100, "b": "replaced"}


# ─────────────────────────────────────────────────────────────────────────────
# Test TRACE logging branches
# ─────────────────────────────────────────────────────────────────────────────


class TestTraceLogging:
    """Tests for TRACE logging branches in auth config."""

    def test_token_storage_trace_logging(self) -> None:
        """Test TRACE logging in get_token_storage_from_config."""

        from kstlib.logging import TRACE_LEVEL

        config = {"token_storage": "memory", "providers": {}}

        with patch("kstlib.auth.config.logger") as mock_logger:
            mock_logger.isEnabledFor.return_value = True

            get_token_storage_from_config(storage_type="memory", config=config)

            mock_logger.isEnabledFor.assert_called_with(TRACE_LEVEL)
            mock_logger.log.assert_called()
            # Verify the log message contains expected info
            call_args = mock_logger.log.call_args
            assert call_args[0][0] == TRACE_LEVEL
            assert "Token storage type resolved" in call_args[0][1]

    def test_build_provider_config_trace_logging(self) -> None:
        """Test TRACE logging in build_provider_config."""
        from kstlib.logging import TRACE_LEVEL

        config = {
            "providers": {
                "test": {
                    "client_id": "app",
                    "issuer": "https://example.com",
                }
            }
        }

        with patch("kstlib.auth.config.logger") as mock_logger:
            mock_logger.isEnabledFor.return_value = True

            build_provider_config("test", config=config)

            mock_logger.isEnabledFor.assert_called_with(TRACE_LEVEL)
            # Find the call with "Building provider config"
            log_calls = [c for c in mock_logger.log.call_args_list if "Building provider config" in str(c)]
            assert len(log_calls) >= 1

    def test_resolve_sops_secret_trace_logging_with_key(self) -> None:
        """Test TRACE logging in _resolve_sops_secret with key in URI."""
        from kstlib.logging import TRACE_LEVEL

        with (
            patch("kstlib.auth.config.logger") as mock_logger,
            patch("kstlib.secrets.resolve_secret", return_value="secret"),
        ):
            mock_logger.isEnabledFor.return_value = True

            result = _resolve_sops_secret("sops://secrets.yaml#auth.key")

            assert result == "secret"
            # Verify TRACE logging was called
            trace_calls = [c for c in mock_logger.log.call_args_list if c[0][0] == TRACE_LEVEL]
            assert len(trace_calls) >= 1
            # Verify safe_uri is logged (path without key)
            logged_args = str(trace_calls[0])
            assert "secrets.yaml" in logged_args

    def test_resolve_sops_secret_trace_logging_success(self) -> None:
        """Test TRACE logging for successful SOPS resolution."""
        from kstlib.logging import TRACE_LEVEL

        with (
            patch("kstlib.auth.config.logger") as mock_logger,
            patch("kstlib.secrets.resolve_secret", return_value="secret"),
        ):
            mock_logger.isEnabledFor.return_value = True

            _resolve_sops_secret("sops://secrets.yaml#key")

            # Should have two TRACE logs: one for resolving, one for success
            trace_calls = [c for c in mock_logger.log.call_args_list if c[0][0] == TRACE_LEVEL]
            assert len(trace_calls) == 2
            assert "resolved successfully" in str(trace_calls[1])
