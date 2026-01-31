"""Tests for the abstract auth provider base classes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from kstlib.auth.models import AuthFlow, PreflightReport, PreflightResult, PreflightStatus, Token
from kstlib.auth.providers.base import (
    AbstractAuthProvider,
    AuthProviderConfig,
    load_provider_from_config,
)
from kstlib.auth.token import MemoryTokenStorage

# ─────────────────────────────────────────────────────────────────────────────
# AuthProviderConfig tests
# ─────────────────────────────────────────────────────────────────────────────


class TestAuthProviderConfig:
    """Tests for AuthProviderConfig dataclass."""

    def test_valid_config_with_issuer(self) -> None:
        """Config with issuer is valid (OIDC discovery mode)."""
        config = AuthProviderConfig(
            client_id="my-app",
            issuer="https://auth.example.com",
        )
        assert config.client_id == "my-app"
        assert config.issuer == "https://auth.example.com"

    def test_valid_config_with_endpoints(self) -> None:
        """Config with explicit endpoints is valid (manual mode)."""
        config = AuthProviderConfig(
            client_id="my-app",
            authorize_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
        )
        assert config.authorize_url is not None
        assert config.token_url is not None

    def test_invalid_config_raises_valueerror(self) -> None:
        """Config without issuer or endpoints raises ValueError."""
        with pytest.raises(ValueError, match=r"Either 'issuer'.*or both 'authorize_url' and 'token_url'"):
            AuthProviderConfig(client_id="my-app")

    def test_invalid_config_with_only_authorize_url(self) -> None:
        """Config with only authorize_url raises ValueError."""
        with pytest.raises(ValueError):
            AuthProviderConfig(
                client_id="my-app",
                authorize_url="https://auth.example.com/authorize",
            )

    def test_has_explicit_endpoints_true(self) -> None:
        """has_explicit_endpoints returns True when endpoints are set."""
        config = AuthProviderConfig(
            client_id="my-app",
            authorize_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
        )
        assert config.has_explicit_endpoints is True

    def test_has_explicit_endpoints_with_revoke_url(self) -> None:
        """has_explicit_endpoints returns True for revoke_url only."""
        config = AuthProviderConfig(
            client_id="my-app",
            issuer="https://auth.example.com",
            revoke_url="https://auth.example.com/revoke",
        )
        assert config.has_explicit_endpoints is True

    def test_has_explicit_endpoints_false(self) -> None:
        """has_explicit_endpoints returns False when only issuer is set."""
        config = AuthProviderConfig(
            client_id="my-app",
            issuer="https://auth.example.com",
        )
        assert config.has_explicit_endpoints is False

    def test_default_values(self) -> None:
        """Config has sensible defaults."""
        config = AuthProviderConfig(
            client_id="my-app",
            issuer="https://auth.example.com",
        )
        assert config.scopes == ["openid"]
        assert config.redirect_uri == "http://127.0.0.1:8400/callback"
        assert config.pkce is True
        assert config.discovery_ttl == 3600
        assert config.extra == {}


# ─────────────────────────────────────────────────────────────────────────────
# Concrete implementation for testing AbstractAuthProvider
# ─────────────────────────────────────────────────────────────────────────────


class ConcreteAuthProvider(AbstractAuthProvider):
    """Concrete implementation of AbstractAuthProvider for testing."""

    @property
    def flow(self) -> AuthFlow:
        return AuthFlow.AUTHORIZATION_CODE

    def get_authorization_url(self, state: str | None = None) -> tuple[str, str]:
        return ("https://auth.example.com/authorize", state or "test-state")

    def exchange_code(
        self,
        code: str,
        state: str,
        *,
        code_verifier: str | None = None,
    ) -> Token:
        return Token(
            access_token="new_access_token",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

    def refresh(self, token: Token | None = None) -> Token:
        return Token(
            access_token="refreshed_access_token",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

    def revoke(self, token: Token | None = None) -> bool:
        return True

    def preflight(self) -> PreflightReport:
        return PreflightReport(
            provider_name=self.name,
            results=[PreflightResult(step="test", status=PreflightStatus.SUCCESS, message="OK")],
        )


# ─────────────────────────────────────────────────────────────────────────────
# AbstractAuthProvider tests
# ─────────────────────────────────────────────────────────────────────────────


class TestAbstractAuthProvider:
    """Tests for AbstractAuthProvider."""

    @pytest.fixture
    def provider(self) -> ConcreteAuthProvider:
        """Create a concrete provider for testing."""
        config = AuthProviderConfig(
            client_id="test-client",
            issuer="https://auth.example.com",
        )
        storage = MemoryTokenStorage()
        return ConcreteAuthProvider("test-provider", config, storage)

    @pytest.fixture
    def valid_token(self) -> Token:
        """Create a valid non-expired token."""
        return Token(
            access_token="valid_access_token",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            refresh_token="valid_refresh_token",
        )

    @pytest.fixture
    def expired_refreshable_token(self) -> Token:
        """Create an expired token that can be refreshed."""
        return Token(
            access_token="expired_access_token",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            refresh_token="valid_refresh_token",
        )

    @pytest.fixture
    def expired_non_refreshable_token(self) -> Token:
        """Create an expired token without refresh token."""
        return Token(
            access_token="expired_access_token",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

    def test_is_authenticated_with_valid_token(self, provider: ConcreteAuthProvider, valid_token: Token) -> None:
        """is_authenticated returns True with valid token."""
        provider.save_token(valid_token)
        assert provider.is_authenticated is True

    def test_is_authenticated_with_no_token(self, provider: ConcreteAuthProvider) -> None:
        """is_authenticated returns False with no token."""
        assert provider.is_authenticated is False

    def test_is_authenticated_with_expired_token(
        self, provider: ConcreteAuthProvider, expired_non_refreshable_token: Token
    ) -> None:
        """is_authenticated returns False with expired token."""
        provider.save_token(expired_non_refreshable_token)
        # is_authenticated uses auto_refresh=False, so it won't try to refresh
        assert provider.is_authenticated is False

    def test_get_token_returns_none_when_no_token(self, provider: ConcreteAuthProvider) -> None:
        """get_token returns None when no token is stored."""
        assert provider.get_token() is None

    def test_get_token_returns_valid_token(self, provider: ConcreteAuthProvider, valid_token: Token) -> None:
        """get_token returns token when available."""
        provider.save_token(valid_token)
        token = provider.get_token()
        assert token is not None
        assert token.access_token == "valid_access_token"

    def test_get_token_refreshes_expired_token(
        self, provider: ConcreteAuthProvider, expired_refreshable_token: Token
    ) -> None:
        """get_token refreshes expired token when auto_refresh=True."""
        provider.save_token(expired_refreshable_token)
        token = provider.get_token(auto_refresh=True)
        assert token is not None
        assert token.access_token == "refreshed_access_token"

    def test_get_token_no_refresh_when_disabled(
        self, provider: ConcreteAuthProvider, expired_refreshable_token: Token
    ) -> None:
        """get_token doesn't refresh when auto_refresh=False."""
        provider.save_token(expired_refreshable_token)
        token = provider.get_token(auto_refresh=False)
        assert token is not None
        assert token.access_token == "expired_access_token"

    def test_get_token_handles_refresh_failure(
        self, provider: ConcreteAuthProvider, expired_refreshable_token: Token
    ) -> None:
        """get_token returns cached token when refresh fails."""
        provider.save_token(expired_refreshable_token)

        # Make refresh fail
        original_refresh = provider.refresh
        provider.refresh = MagicMock(side_effect=Exception("Refresh failed"))

        token = provider.get_token(auto_refresh=True)

        # Should return the old token despite refresh failure
        assert token is not None
        assert token.access_token == "expired_access_token"

        # Restore original refresh
        provider.refresh = original_refresh

    def test_get_token_logs_non_refreshable_token(
        self, provider: ConcreteAuthProvider, expired_non_refreshable_token: Token
    ) -> None:
        """get_token logs debug message for non-refreshable expired token."""
        provider.save_token(expired_non_refreshable_token)

        with patch("kstlib.auth.providers.base.logger") as mock_logger:
            token = provider.get_token(auto_refresh=True)

            # Should still return the expired token
            assert token is not None
            assert token.access_token == "expired_access_token"

            # Should have logged debug message about non-refreshable token
            mock_logger.debug.assert_called()

    def test_save_token(self, provider: ConcreteAuthProvider, valid_token: Token) -> None:
        """save_token stores token in memory and storage."""
        provider.save_token(valid_token)
        assert provider._current_token == valid_token
        assert provider.token_storage.load("test-provider") == valid_token

    def test_clear_token(self, provider: ConcreteAuthProvider, valid_token: Token) -> None:
        """clear_token removes token from memory and storage."""
        provider.save_token(valid_token)
        provider.clear_token()
        assert provider._current_token is None
        assert provider.token_storage.load("test-provider") is None

    def test_context_manager_enter(self, provider: ConcreteAuthProvider) -> None:
        """Context manager __enter__ returns provider."""
        with provider as p:
            assert p is provider

    def test_context_manager_exit_clears_token(self, provider: ConcreteAuthProvider, valid_token: Token) -> None:
        """Context manager __exit__ clears token from memory."""
        provider.save_token(valid_token)

        with provider:
            assert provider._current_token is not None

        # After exiting context, token should be cleared from memory
        assert provider._current_token is None

    def test_context_manager_exit_on_exception(self, provider: ConcreteAuthProvider, valid_token: Token) -> None:
        """Context manager __exit__ clears token even on exception."""
        provider.save_token(valid_token)

        with pytest.raises(ValueError), provider:
            raise ValueError("Test error")

        assert provider._current_token is None


# ─────────────────────────────────────────────────────────────────────────────
# load_provider_from_config tests
# ─────────────────────────────────────────────────────────────────────────────


class TestLoadProviderFromConfig:
    """Tests for load_provider_from_config helper."""

    def test_provider_not_found_raises(self) -> None:
        """Raises ConfigurationError when provider not found."""
        from kstlib.auth.errors import ConfigurationError

        with pytest.raises(ConfigurationError, match="not found"):
            load_provider_from_config(
                "nonexistent-provider",
                allowed_types=("oidc",),
                type_label="oidc",
                config={"providers": {}},
            )

    def test_type_mismatch_raises(self) -> None:
        """Raises ConfigurationError on provider type mismatch."""
        from kstlib.auth.errors import ConfigurationError

        config = {
            "providers": {
                "my-provider": {
                    "type": "oauth2",
                    "client_id": "test",
                    "authorize_url": "https://example.com/auth",
                    "token_url": "https://example.com/token",
                }
            }
        }

        with pytest.raises(ConfigurationError, match="has type 'oauth2', expected 'oidc'"):
            load_provider_from_config(
                "my-provider",
                allowed_types=("oidc", "openid"),
                type_label="oidc",
                config=config,
            )

    def test_valid_config_returns_tuple(self) -> None:
        """Valid config returns (AuthProviderConfig, AbstractTokenStorage)."""
        config = {
            "providers": {
                "my-oidc-provider": {
                    "type": "oidc",
                    "client_id": "test-client",
                    "issuer": "https://auth.example.com",
                }
            }
        }

        auth_config, token_storage = load_provider_from_config(
            "my-oidc-provider",
            allowed_types=("oidc", "openid"),
            type_label="oidc",
            config=config,
        )

        assert auth_config.client_id == "test-client"
        assert auth_config.issuer == "https://auth.example.com"
        assert token_storage is not None

    def test_uses_first_allowed_type_as_default(self) -> None:
        """When type not specified, uses first allowed type."""
        config = {
            "providers": {
                "my-provider": {
                    "client_id": "test-client",
                    "issuer": "https://auth.example.com",
                }
            }
        }

        # Should not raise because default type matches first allowed
        auth_config, _ = load_provider_from_config(
            "my-provider",
            allowed_types=("oidc", "openid"),
            type_label="oidc",
            config=config,
        )

        assert auth_config.client_id == "test-client"
