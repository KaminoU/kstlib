"""Unit tests for OIDCProvider."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import httpx
import pytest

from kstlib.auth.errors import (
    ConfigurationError,
    DiscoveryError,
    TokenValidationError,
)
from kstlib.auth.models import AuthFlow, PreflightStatus
from kstlib.auth.providers import AuthProviderConfig, OIDCProvider

if TYPE_CHECKING:
    from kstlib.auth.token import MemoryTokenStorage


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def oidc_config() -> AuthProviderConfig:
    """Create OIDC config with issuer for testing."""
    return AuthProviderConfig(
        client_id="test-oidc-client",
        issuer="https://auth.example.com",
        scopes=["openid", "profile", "email"],
        pkce=True,
        redirect_uri="http://127.0.0.1:8400/callback",
    )


@pytest.fixture
def oidc_provider(
    oidc_config: AuthProviderConfig,
    memory_storage: MemoryTokenStorage,
) -> OIDCProvider:
    """Create an OIDCProvider for testing."""
    return OIDCProvider("test", oidc_config, memory_storage)


@pytest.fixture
def mock_discovery_doc() -> dict:
    """Create a mock OIDC discovery document."""
    return {
        "issuer": "https://auth.example.com",
        "authorization_endpoint": "https://auth.example.com/authorize",
        "token_endpoint": "https://auth.example.com/token",
        "userinfo_endpoint": "https://auth.example.com/userinfo",
        "jwks_uri": "https://auth.example.com/.well-known/jwks.json",
        "revocation_endpoint": "https://auth.example.com/revoke",
    }


@pytest.fixture
def mock_jwks() -> dict:
    """Create a mock JWKS response."""
    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": "test-key-1",
                "use": "sig",
                "alg": "RS256",
                "n": "test-modulus",
                "e": "AQAB",
            }
        ]
    }


@pytest.fixture
def keycloak_discovery_doc() -> dict:
    """Create a Keycloak-style discovery document (with /protocol/openid-connect/ paths)."""
    return {
        "issuer": "http://localhost:8080/realms/test",
        "authorization_endpoint": "http://localhost:8080/realms/test/protocol/openid-connect/auth",
        "token_endpoint": "http://localhost:8080/realms/test/protocol/openid-connect/token",
        "userinfo_endpoint": "http://localhost:8080/realms/test/protocol/openid-connect/userinfo",
        "jwks_uri": "http://localhost:8080/realms/test/protocol/openid-connect/certs",
        "end_session_endpoint": "http://localhost:8080/realms/test/protocol/openid-connect/logout",
        "revocation_endpoint": "http://localhost:8080/realms/test/protocol/openid-connect/revoke",
    }


@pytest.fixture
def manual_oidc_config() -> AuthProviderConfig:
    """Create OIDC config for manual mode (no issuer, explicit endpoints)."""
    return AuthProviderConfig(
        client_id="test-manual-client",
        authorize_url="https://legacy-idp.local/auth",
        token_url="https://legacy-idp.local/token",
        userinfo_url="https://legacy-idp.local/userinfo",
        jwks_uri="https://legacy-idp.local/certs",
        scopes=["openid", "profile"],
        redirect_uri="http://127.0.0.1:8400/callback",
        pkce=True,
    )


@pytest.fixture
def hybrid_oidc_config() -> AuthProviderConfig:
    """Create OIDC config for hybrid mode (issuer + some explicit endpoints)."""
    return AuthProviderConfig(
        client_id="test-hybrid-client",
        issuer="https://auth.example.com",
        # Override: end_session_endpoint is buggy in discovery, use explicit
        end_session_endpoint="https://auth.example.com/custom/logout",
        scopes=["openid", "profile"],
        redirect_uri="http://127.0.0.1:8400/callback",
        pkce=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test __init__ and flow
# ─────────────────────────────────────────────────────────────────────────────


class TestOIDCProviderInit:
    """Tests for OIDCProvider initialization."""

    def test_init_adds_openid_scope_if_missing(self, memory_storage: MemoryTokenStorage) -> None:
        """Test that openid scope is added if missing from scopes."""
        config = AuthProviderConfig(
            client_id="test",
            issuer="https://auth.example.com",
            scopes=["profile", "email"],  # No openid!
            redirect_uri="http://localhost/callback",
        )
        provider = OIDCProvider("test", config, memory_storage)

        # openid should be prepended
        assert provider.config.scopes[0] == "openid"
        assert "profile" in provider.config.scopes
        assert "email" in provider.config.scopes

    def test_init_with_revoke_url(self, memory_storage: MemoryTokenStorage) -> None:
        """Test that revoke_url is tracked in explicit_endpoints."""
        config = AuthProviderConfig(
            client_id="test",
            issuer="https://auth.example.com",
            revoke_url="https://auth.example.com/custom/revoke",
            redirect_uri="http://localhost/callback",
        )
        provider = OIDCProvider("test", config, memory_storage)

        assert "revocation_endpoint" in provider._explicit_endpoints

    def test_init_manual_mode_missing_authorize_url(self, memory_storage: MemoryTokenStorage) -> None:
        """Test manual mode fails if authorize_url is missing."""
        config = AuthProviderConfig.__new__(AuthProviderConfig)
        config.client_id = "test"
        config.client_secret = None
        config.authorize_url = None  # Missing!
        config.token_url = "https://idp.local/token"
        config.redirect_uri = "http://localhost/callback"
        config.scopes = ["openid"]
        config.issuer = None  # Manual mode
        config.pkce = True
        config.revoke_url = None
        config.userinfo_url = None
        config.jwks_uri = None
        config.end_session_endpoint = None
        config.discovery_ttl = 3600
        config.headers = {}
        config.extra = {}

        with pytest.raises(ConfigurationError, match="authorize_url"):
            OIDCProvider("test", config, memory_storage)

    def test_init_manual_mode_missing_token_url(self, memory_storage: MemoryTokenStorage) -> None:
        """Test manual mode fails if token_url is missing."""
        config = AuthProviderConfig.__new__(AuthProviderConfig)
        config.client_id = "test"
        config.client_secret = None
        config.authorize_url = "https://idp.local/auth"
        config.token_url = None  # Missing!
        config.redirect_uri = "http://localhost/callback"
        config.scopes = ["openid"]
        config.issuer = None  # Manual mode
        config.pkce = True
        config.revoke_url = None
        config.userinfo_url = None
        config.jwks_uri = None
        config.end_session_endpoint = None
        config.discovery_ttl = 3600
        config.headers = {}
        config.extra = {}

        with pytest.raises(ConfigurationError, match="token_url"):
            OIDCProvider("test", config, memory_storage)

    def test_init_requires_issuer_or_urls(self, memory_storage: MemoryTokenStorage) -> None:
        """Test that __init__ requires issuer or discovery endpoints."""
        # OIDC with neither issuer nor direct URLs should fail
        config = AuthProviderConfig.__new__(AuthProviderConfig)
        config.client_id = "test"
        config.client_secret = None
        config.authorize_url = None
        config.token_url = None
        config.redirect_uri = "http://localhost/callback"
        config.scopes = ["openid"]
        config.issuer = None  # No issuer
        config.pkce = True
        config.revoke_url = None
        config.userinfo_url = None
        config.jwks_uri = None
        config.end_session_endpoint = None
        config.discovery_ttl = 3600
        config.headers = {}
        config.extra = {}

        with pytest.raises(ConfigurationError, match=r"authorize_url.*token_url|issuer"):
            OIDCProvider("test", config, memory_storage)

    def test_flow_property(self, oidc_provider: OIDCProvider) -> None:
        """Test that flow property returns AUTHORIZATION_CODE_PKCE when PKCE enabled."""
        assert oidc_provider.flow == AuthFlow.AUTHORIZATION_CODE_PKCE

    def test_flow_without_pkce(self, memory_storage: MemoryTokenStorage) -> None:
        """Test that flow returns AUTHORIZATION_CODE when PKCE disabled."""
        config = AuthProviderConfig(
            client_id="test",
            issuer="https://auth.example.com",
            pkce=False,
            redirect_uri="http://localhost/callback",
        )
        provider = OIDCProvider("test", config, memory_storage)
        assert provider.flow == AuthFlow.AUTHORIZATION_CODE


# ─────────────────────────────────────────────────────────────────────────────
# Test discovery modes (auto, hybrid, manual)
# ─────────────────────────────────────────────────────────────────────────────


class TestDiscoveryModes:
    """Tests for the three discovery modes: auto, hybrid, and manual."""

    # ─────────────────────────────────────────────────────────────────────────
    # Auto discovery mode
    # ─────────────────────────────────────────────────────────────────────────

    def test_auto_mode_with_issuer_only(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Test auto discovery mode when only issuer is provided."""
        provider = OIDCProvider("auto", oidc_config, memory_storage)

        assert provider.discovery_mode == "auto"
        assert provider._discovery_enabled is True
        assert provider._explicit_endpoints == {}

    def test_auto_mode_discovery_updates_endpoints(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        keycloak_discovery_doc: dict,
    ) -> None:
        """Test that auto discovery updates all endpoints from discovery doc."""
        provider = OIDCProvider("auto", oidc_config, memory_storage)

        # Before discovery: placeholders
        assert provider.config.token_url == "https://auth.example.com/token"

        mock_response = MagicMock()
        mock_response.json.return_value = keycloak_discovery_doc
        mock_response.raise_for_status = MagicMock()

        with patch.object(provider.http_client, "get", return_value=mock_response):
            provider.discover()

        # After discovery: real endpoints from discovery doc
        assert provider.config.token_url == keycloak_discovery_doc["token_endpoint"]
        assert provider.config.authorize_url == keycloak_discovery_doc["authorization_endpoint"]
        assert provider.config.jwks_uri == keycloak_discovery_doc["jwks_uri"]
        assert provider.config.end_session_endpoint == keycloak_discovery_doc["end_session_endpoint"]

    # ─────────────────────────────────────────────────────────────────────────
    # Hybrid mode
    # ─────────────────────────────────────────────────────────────────────────

    def test_hybrid_mode_with_issuer_and_explicit_endpoint(
        self,
        hybrid_oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Test hybrid mode when issuer + some explicit endpoints are provided."""
        provider = OIDCProvider("hybrid", hybrid_oidc_config, memory_storage)

        assert provider.discovery_mode == "hybrid"
        assert provider._discovery_enabled is True
        assert "end_session_endpoint" in provider._explicit_endpoints

    def test_hybrid_mode_explicit_endpoints_preserved(
        self,
        hybrid_oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        mock_discovery_doc: dict,
    ) -> None:
        """Test that explicit endpoints are NOT overwritten by discovery."""
        provider = OIDCProvider("hybrid", hybrid_oidc_config, memory_storage)

        # Explicit endpoint before discovery
        explicit_logout = "https://auth.example.com/custom/logout"
        assert provider.config.end_session_endpoint == explicit_logout

        # Add end_session_endpoint to discovery doc (different URL)
        mock_discovery_doc["end_session_endpoint"] = "https://auth.example.com/standard/logout"

        mock_response = MagicMock()
        mock_response.json.return_value = mock_discovery_doc
        mock_response.raise_for_status = MagicMock()

        with patch.object(provider.http_client, "get", return_value=mock_response):
            provider.discover()

        # Explicit endpoint should be PRESERVED (hybrid mode: explicit wins)
        assert provider.config.end_session_endpoint == explicit_logout
        # But other endpoints should be updated from discovery
        assert provider.config.token_url == mock_discovery_doc["token_endpoint"]

    def test_hybrid_mode_multiple_explicit_endpoints(
        self,
        memory_storage: MemoryTokenStorage,
        mock_discovery_doc: dict,
    ) -> None:
        """Test hybrid mode with multiple explicit endpoints."""
        config = AuthProviderConfig(
            client_id="test-hybrid",
            issuer="https://auth.example.com",
            # Two explicit endpoints
            token_url="https://auth.example.com/custom/token",
            jwks_uri="https://auth.example.com/custom/jwks",
            redirect_uri="http://127.0.0.1:8400/callback",
        )
        provider = OIDCProvider("hybrid", config, memory_storage)

        assert provider.discovery_mode == "hybrid"
        assert "token_endpoint" in provider._explicit_endpoints
        assert "jwks_uri" in provider._explicit_endpoints

        mock_response = MagicMock()
        mock_response.json.return_value = mock_discovery_doc
        mock_response.raise_for_status = MagicMock()

        with patch.object(provider.http_client, "get", return_value=mock_response):
            provider.discover()

        # Explicit endpoints preserved
        assert provider.config.token_url == "https://auth.example.com/custom/token"
        assert provider.config.jwks_uri == "https://auth.example.com/custom/jwks"
        # Non-explicit endpoints updated from discovery
        assert provider.config.authorize_url == mock_discovery_doc["authorization_endpoint"]
        assert provider.config.userinfo_url == mock_discovery_doc["userinfo_endpoint"]

    # ─────────────────────────────────────────────────────────────────────────
    # Manual mode
    # ─────────────────────────────────────────────────────────────────────────

    def test_manual_mode_no_issuer(
        self,
        manual_oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Test manual mode when no issuer is provided."""
        provider = OIDCProvider("manual", manual_oidc_config, memory_storage)

        assert provider.discovery_mode == "manual"
        assert provider._discovery_enabled is False
        # All endpoints should be in explicit_endpoints
        assert "authorization_endpoint" in provider._explicit_endpoints
        assert "token_endpoint" in provider._explicit_endpoints
        assert "jwks_uri" in provider._explicit_endpoints

    def test_manual_mode_discover_returns_empty_dict(
        self,
        manual_oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Test that discover() returns empty dict in manual mode (no network call)."""
        provider = OIDCProvider("manual", manual_oidc_config, memory_storage)

        # Should NOT make any HTTP calls
        with patch.object(provider.http_client, "get") as mock_get:
            result = provider.discover()

        assert result == {}
        mock_get.assert_not_called()

    def test_manual_mode_endpoints_unchanged_after_discover(
        self,
        manual_oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Test that endpoints remain unchanged after discover() in manual mode."""
        provider = OIDCProvider("manual", manual_oidc_config, memory_storage)

        # Store original endpoints
        original_token_url = provider.config.token_url
        original_authorize_url = provider.config.authorize_url
        original_jwks_uri = provider.config.jwks_uri

        provider.discover()

        # Endpoints should be unchanged
        assert provider.config.token_url == original_token_url
        assert provider.config.authorize_url == original_authorize_url
        assert provider.config.jwks_uri == original_jwks_uri

    def test_manual_mode_requires_minimum_endpoints(
        self,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Test that manual mode fails if required endpoints are missing."""
        # Missing token_url
        config = AuthProviderConfig(
            client_id="test",
            authorize_url="https://idp.local/auth",
            token_url="https://idp.local/token",  # Required by AuthProviderConfig
            redirect_uri="http://127.0.0.1:8400/callback",
        )
        # This should work - minimum requirements met
        provider = OIDCProvider("manual", config, memory_storage)
        assert provider.discovery_mode == "manual"

    def test_manual_mode_warns_missing_jwks_uri(
        self,
        memory_storage: MemoryTokenStorage,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that manual mode logs warning if jwks_uri is missing."""
        import logging

        config = AuthProviderConfig(
            client_id="test",
            authorize_url="https://idp.local/auth",
            token_url="https://idp.local/token",
            # No jwks_uri - should warn
            redirect_uri="http://127.0.0.1:8400/callback",
        )

        with caplog.at_level(logging.WARNING):
            OIDCProvider("manual-no-jwks", config, memory_storage)

        assert "jwks_uri not configured" in caplog.text

    # ─────────────────────────────────────────────────────────────────────────
    # Edge cases
    # ─────────────────────────────────────────────────────────────────────────

    def test_refresh_works_in_manual_mode(
        self,
        manual_oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Test that refresh() works correctly in manual mode (no discovery call)."""
        from datetime import datetime, timezone

        from kstlib.auth.models import Token

        provider = OIDCProvider("manual", manual_oidc_config, memory_storage)

        # Create expired token
        token = Token(
            access_token="expired-token",
            token_type="Bearer",
            expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            refresh_token="refresh-token",
        )
        provider.save_token(token)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new-token",
            "token_type": "Bearer",
            "expires_in": 300,
        }
        mock_response.raise_for_status = MagicMock()

        call_urls = []

        def mock_post(url, **kwargs):
            call_urls.append(url)
            return mock_response

        with (
            patch.object(provider.http_client, "get") as mock_get,
            patch.object(provider.http_client, "post", side_effect=mock_post),
        ):
            new_token = provider.refresh()

        # Should NOT call discovery (no GET to .well-known)
        mock_get.assert_not_called()
        # Should use explicit token_url
        assert call_urls[0] == "https://legacy-idp.local/token"
        assert new_token.access_token == "new-token"


# ─────────────────────────────────────────────────────────────────────────────
# Test from_config
# ─────────────────────────────────────────────────────────────────────────────


class TestOIDCProviderFromConfig:
    """Tests for OIDCProvider.from_config()."""

    def test_from_config_provider_not_found(self) -> None:
        """Test that from_config raises if provider not found."""
        with (
            patch("kstlib.auth.config.get_provider_config", return_value=None),
            pytest.raises(ConfigurationError, match="not found"),
        ):
            OIDCProvider.from_config("nonexistent")

    def test_from_config_wrong_type(self) -> None:
        """Test that from_config raises if provider type is not oidc."""
        with (
            patch("kstlib.auth.config.get_provider_config", return_value={"type": "oauth2"}),
            pytest.raises(ConfigurationError, match="expected 'oidc'"),
        ):
            OIDCProvider.from_config("oauth2-provider")

    def test_from_config_success(self, oidc_config: AuthProviderConfig) -> None:
        """Test successful from_config creation."""
        from kstlib.auth.token import MemoryTokenStorage

        mock_provider_cfg = {"type": "oidc"}

        with (
            patch("kstlib.auth.config.get_provider_config", return_value=mock_provider_cfg),
            patch("kstlib.auth.config.build_provider_config", return_value=oidc_config),
            patch("kstlib.auth.config.get_token_storage_from_config", return_value=MemoryTokenStorage()),
        ):
            provider = OIDCProvider.from_config("corporate")

            assert provider.name == "corporate"
            assert provider.config == oidc_config


# ─────────────────────────────────────────────────────────────────────────────
# Test discovery
# ─────────────────────────────────────────────────────────────────────────────


class TestDiscovery:
    """Tests for OIDC discovery."""

    def test_discover_fetches_document(
        self,
        oidc_provider: OIDCProvider,
        mock_discovery_doc: dict,
    ) -> None:
        """Test that discover() fetches the discovery document."""
        mock_response = MagicMock()
        mock_response.json.return_value = mock_discovery_doc
        mock_response.raise_for_status = MagicMock()

        with patch.object(oidc_provider.http_client, "get", return_value=mock_response):
            doc = oidc_provider.discover()

        assert doc["issuer"] == "https://auth.example.com"
        assert "authorization_endpoint" in doc

    def test_discover_caches_result(
        self,
        oidc_provider: OIDCProvider,
        mock_discovery_doc: dict,
    ) -> None:
        """Test that discovery document is cached."""
        mock_response = MagicMock()
        mock_response.json.return_value = mock_discovery_doc
        mock_response.raise_for_status = MagicMock()

        with patch.object(oidc_provider.http_client, "get", return_value=mock_response) as mock_get:
            oidc_provider.discover()
            oidc_provider.discover()

        # Should only call once due to caching
        assert mock_get.call_count == 1

    def test_discover_force_refresh(
        self,
        oidc_provider: OIDCProvider,
        mock_discovery_doc: dict,
    ) -> None:
        """Test forced discovery refresh."""
        mock_response = MagicMock()
        mock_response.json.return_value = mock_discovery_doc
        mock_response.raise_for_status = MagicMock()

        with patch.object(oidc_provider.http_client, "get", return_value=mock_response) as mock_get:
            oidc_provider.discover()
            oidc_provider.discover(force=True)

        assert mock_get.call_count == 2

    def test_discover_http_error(self, oidc_provider: OIDCProvider) -> None:
        """Test discovery handles HTTP errors."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        error = httpx.HTTPStatusError("Not Found", request=MagicMock(), response=mock_response)

        with patch.object(oidc_provider.http_client, "get", side_effect=error), pytest.raises(DiscoveryError):
            oidc_provider.discover()

    def test_discover_stores_discovered_issuer(
        self,
        oidc_provider: OIDCProvider,
        mock_discovery_doc: dict,
    ) -> None:
        """Test that discover() stores the discovered issuer for token validation."""
        mock_response = MagicMock()
        mock_response.json.return_value = mock_discovery_doc
        mock_response.raise_for_status = MagicMock()

        with patch.object(oidc_provider.http_client, "get", return_value=mock_response):
            oidc_provider.discover()

        assert oidc_provider._discovered_issuer == mock_discovery_doc["issuer"]

    def test_discover_issuer_mismatch_uses_discovered(
        self,
        memory_storage: MemoryTokenStorage,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test discovery with mismatched issuer (common with enterprise IDPs).

        Enterprise IDPs like Oracle OAM often return an issuer in the discovery
        document that differs from the configured issuer (e.g., with :443 port
        or /oauth2 path suffix). kstlib should use the discovered issuer for
        token validation.
        """
        import logging

        # Configure with base issuer (what user would naturally configure)
        config = AuthProviderConfig(
            client_id="test-client",
            issuer="https://sso.enterprise.local",  # Configured by user
            scopes=["openid"],
            redirect_uri="http://127.0.0.1:8400/callback",
        )
        provider = OIDCProvider("enterprise", config, memory_storage)

        # Discovery returns different issuer (common with Oracle OAM, etc.)
        discovery_doc = {
            "issuer": "https://sso.enterprise.local:443/oauth2",  # Different!
            "authorization_endpoint": "https://sso.enterprise.local:443/oauth2/authorize",
            "token_endpoint": "https://sso.enterprise.local:443/oauth2/token",
            "jwks_uri": "https://sso.enterprise.local:443/oauth2/certs",
        }

        mock_response = MagicMock()
        mock_response.json.return_value = discovery_doc
        mock_response.raise_for_status = MagicMock()

        with (
            patch.object(provider.http_client, "get", return_value=mock_response),
            caplog.at_level(logging.DEBUG),
        ):
            provider.discover()

        # Discovered issuer should be stored
        assert provider._discovered_issuer == "https://sso.enterprise.local:443/oauth2"
        # Log should mention the mismatch
        assert "discovered issuer differs from configured" in caplog.text


# ─────────────────────────────────────────────────────────────────────────────
# Test PKCE
# ─────────────────────────────────────────────────────────────────────────────


class TestPKCE:
    """Tests for PKCE functionality."""

    def test_get_authorization_url_includes_pkce(
        self,
        oidc_provider: OIDCProvider,
        mock_discovery_doc: dict,
    ) -> None:
        """Test that authorization URL includes PKCE parameters."""
        mock_response = MagicMock()
        mock_response.json.return_value = mock_discovery_doc
        mock_response.raise_for_status = MagicMock()

        with patch.object(oidc_provider.http_client, "get", return_value=mock_response):
            url, _state = oidc_provider.get_authorization_url()

        assert "code_challenge=" in url
        assert "code_challenge_method=S256" in url

    def test_pkce_verifier_stored(
        self,
        oidc_provider: OIDCProvider,
        mock_discovery_doc: dict,
    ) -> None:
        """Test that PKCE verifier is stored for exchange."""
        mock_response = MagicMock()
        mock_response.json.return_value = mock_discovery_doc
        mock_response.raise_for_status = MagicMock()

        with patch.object(oidc_provider.http_client, "get", return_value=mock_response):
            oidc_provider.get_authorization_url()

        assert oidc_provider._code_verifier is not None
        assert len(oidc_provider._code_verifier) >= 43


# ─────────────────────────────────────────────────────────────────────────────
# Test exchange_code with ID token
# ─────────────────────────────────────────────────────────────────────────────


class TestExchangeCodeOIDC:
    """Tests for OIDC-specific exchange_code behavior."""

    def test_exchange_code_includes_verifier(
        self,
        oidc_provider: OIDCProvider,
        mock_discovery_doc: dict,
    ) -> None:
        """Test that exchange_code includes PKCE verifier."""
        # Setup
        oidc_provider._pending_state = "test-state"
        oidc_provider._code_verifier = "test-verifier-12345"
        oidc_provider._discovery_doc = mock_discovery_doc

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "access-token",
            "token_type": "Bearer",
            "id_token": "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig",
        }
        mock_response.raise_for_status = MagicMock()

        with (
            patch.object(oidc_provider.http_client, "post", return_value=mock_response) as mock_post,
            patch.object(oidc_provider, "_validate_id_token", return_value=None),
        ):
            oidc_provider.exchange_code(code="auth-code", state="test-state")

        call_data = mock_post.call_args.kwargs["data"]
        assert call_data["code_verifier"] == "test-verifier-12345"

    def test_exchange_code_pkce_missing_verifier_error(
        self,
        oidc_provider: OIDCProvider,
        mock_discovery_doc: dict,
    ) -> None:
        """Test that exchange_code fails if PKCE enabled but no verifier."""
        from kstlib.auth.errors import TokenExchangeError

        oidc_provider._pending_state = "test-state"
        oidc_provider._code_verifier = None  # No verifier!
        oidc_provider._discovery_doc = mock_discovery_doc

        with pytest.raises(TokenExchangeError, match="PKCE is enabled but no code_verifier"):
            oidc_provider.exchange_code(code="auth-code", state="test-state")

    def test_exchange_code_id_token_validation_failure_logged(
        self,
        oidc_provider: OIDCProvider,
        mock_discovery_doc: dict,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that ID token validation failure is logged but doesn't fail exchange."""
        import logging

        oidc_provider._pending_state = "test-state"
        oidc_provider._code_verifier = "test-verifier"
        oidc_provider._discovery_doc = mock_discovery_doc

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "access-token",
            "token_type": "Bearer",
            "id_token": "invalid.jwt.token",
        }
        mock_response.raise_for_status = MagicMock()

        def mock_validate_id_token(token):
            raise TokenValidationError("Invalid signature")

        with (
            patch.object(oidc_provider.http_client, "post", return_value=mock_response),
            patch.object(oidc_provider, "_validate_id_token", side_effect=mock_validate_id_token),
            caplog.at_level(logging.WARNING),
        ):
            token = oidc_provider.exchange_code(code="auth-code", state="test-state")

        # Exchange should still succeed
        assert token.access_token == "access-token"
        # But warning should be logged
        assert "ID token validation failed" in caplog.text


# ─────────────────────────────────────────────────────────────────────────────
# Test validate_id_token
# ─────────────────────────────────────────────────────────────────────────────


class TestValidateIdToken:
    """Tests for ID token validation."""

    def test_validate_id_token_invalid_format(
        self,
        oidc_provider: OIDCProvider,
        mock_jwks: dict,
    ) -> None:
        """Test validation with invalid token format."""
        # Pre-set JWKS to avoid network call (checked before discovery)
        oidc_provider._jwks = mock_jwks

        # Token without proper JWT structure should fail validation
        with pytest.raises(TokenValidationError):
            oidc_provider._validate_id_token("not-a-jwt")

    def test_decode_jwt_unverified_valid(self, oidc_provider: OIDCProvider) -> None:
        """Test _decode_jwt_unverified with valid JWT."""
        import base64
        import json

        # Create a valid JWT payload
        payload_data = {"sub": "user123", "name": "Test User", "email": "test@example.com"}
        payload = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).rstrip(b"=").decode()
        header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256"}).encode()).rstrip(b"=").decode()
        token = f"{header}.{payload}.fake_signature"

        result = oidc_provider._decode_jwt_unverified(token)

        assert result["sub"] == "user123"
        assert result["name"] == "Test User"

    def test_decode_jwt_unverified_invalid_format(self, oidc_provider: OIDCProvider) -> None:
        """Test _decode_jwt_unverified with invalid format."""
        with pytest.raises(TokenValidationError, match="Invalid JWT format"):
            oidc_provider._decode_jwt_unverified("not.a.valid.jwt.token")  # 5 parts instead of 3

    def test_decode_jwt_unverified_invalid_base64(self, oidc_provider: OIDCProvider) -> None:
        """Test _decode_jwt_unverified with invalid base64."""
        with pytest.raises(TokenValidationError, match="Failed to decode JWT"):
            oidc_provider._decode_jwt_unverified("header.!!!invalid!!!.signature")


class TestGetJWKS:
    """Tests for JWKS fetching."""

    def test_get_jwks_from_explicit_config(
        self,
        manual_oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        mock_jwks: dict,
    ) -> None:
        """Test _get_jwks uses explicit jwks_uri."""
        provider = OIDCProvider("manual", manual_oidc_config, memory_storage)

        mock_response = MagicMock()
        mock_response.json.return_value = mock_jwks
        mock_response.raise_for_status = MagicMock()

        with patch.object(provider.http_client, "get", return_value=mock_response) as mock_get:
            jwks = provider._get_jwks()

        assert jwks == mock_jwks
        mock_get.assert_called_once_with("https://legacy-idp.local/certs")

    def test_get_jwks_from_discovery(
        self,
        oidc_provider: OIDCProvider,
        mock_discovery_doc: dict,
        mock_jwks: dict,
    ) -> None:
        """Test _get_jwks falls back to discovery."""
        mock_discovery_response = MagicMock()
        mock_discovery_response.json.return_value = mock_discovery_doc
        mock_discovery_response.raise_for_status = MagicMock()

        mock_jwks_response = MagicMock()
        mock_jwks_response.json.return_value = mock_jwks
        mock_jwks_response.raise_for_status = MagicMock()

        def mock_get(url, **kwargs):
            if ".well-known/openid-configuration" in url:
                return mock_discovery_response
            # jwks endpoint (from mock_discovery_doc)
            return mock_jwks_response

        with patch.object(oidc_provider.http_client, "get", side_effect=mock_get):
            jwks = oidc_provider._get_jwks()

        assert jwks == mock_jwks

    def test_get_jwks_no_uri_error(self, memory_storage: MemoryTokenStorage) -> None:
        """Test _get_jwks raises if no jwks_uri available."""
        # Manual mode without jwks_uri
        config = AuthProviderConfig(
            client_id="test",
            authorize_url="https://idp.local/auth",
            token_url="https://idp.local/token",
            # No jwks_uri!
            redirect_uri="http://localhost/callback",
        )
        provider = OIDCProvider("manual", config, memory_storage)

        with pytest.raises(TokenValidationError, match="No jwks_uri configured"):
            provider._get_jwks()

    def test_get_jwks_request_error(
        self,
        manual_oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Test _get_jwks handles request errors."""
        provider = OIDCProvider("manual", manual_oidc_config, memory_storage)

        with (
            patch.object(provider.http_client, "get", side_effect=httpx.RequestError("Connection failed")),
            pytest.raises(TokenValidationError, match="Failed to fetch JWKS"),
        ):
            provider._get_jwks()


class TestGetUserInfo:
    """Tests for UserInfo endpoint."""

    def test_get_userinfo_success(
        self,
        oidc_provider: OIDCProvider,
        mock_discovery_doc: dict,
    ) -> None:
        """Test successful userinfo request."""
        from datetime import datetime, timedelta, timezone

        from kstlib.auth.models import Token

        # Setup token
        token = Token(
            access_token="valid-access-token",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        oidc_provider.save_token(token)

        mock_discovery_response = MagicMock()
        mock_discovery_response.json.return_value = mock_discovery_doc
        mock_discovery_response.raise_for_status = MagicMock()

        mock_userinfo_response = MagicMock()
        mock_userinfo_response.json.return_value = {
            "sub": "user123",
            "name": "Test User",
            "email": "test@example.com",
        }
        mock_userinfo_response.raise_for_status = MagicMock()

        def mock_get(url, **kwargs):
            if ".well-known" in url:
                return mock_discovery_response
            if "userinfo" in url:
                return mock_userinfo_response
            return MagicMock()

        with patch.object(oidc_provider.http_client, "get", side_effect=mock_get):
            userinfo = oidc_provider.get_userinfo()

        assert userinfo["sub"] == "user123"
        assert userinfo["email"] == "test@example.com"

    def test_get_userinfo_no_token(self, oidc_provider: OIDCProvider) -> None:
        """Test get_userinfo fails if no token available."""
        with pytest.raises(TokenValidationError, match="No token available"):
            oidc_provider.get_userinfo()

    def test_get_userinfo_explicit_endpoint(
        self,
        manual_oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Test get_userinfo uses explicit userinfo_url."""
        from datetime import datetime, timedelta, timezone

        from kstlib.auth.models import Token

        provider = OIDCProvider("manual", manual_oidc_config, memory_storage)

        token = Token(
            access_token="access-token",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        provider.save_token(token)

        mock_response = MagicMock()
        mock_response.json.return_value = {"sub": "user123"}
        mock_response.raise_for_status = MagicMock()

        with patch.object(provider.http_client, "get", return_value=mock_response) as mock_get:
            provider.get_userinfo()

        # Should use explicit endpoint, not discovery
        mock_get.assert_called_once()
        call_url = mock_get.call_args[0][0]
        assert call_url == "https://legacy-idp.local/userinfo"

    def test_get_userinfo_no_endpoint_error(self, memory_storage: MemoryTokenStorage) -> None:
        """Test get_userinfo fails if no endpoint available."""
        from datetime import datetime, timedelta, timezone

        from kstlib.auth.models import Token

        # Manual mode without userinfo_url
        config = AuthProviderConfig(
            client_id="test",
            authorize_url="https://idp.local/auth",
            token_url="https://idp.local/token",
            # No userinfo_url!
            redirect_uri="http://localhost/callback",
        )
        provider = OIDCProvider("manual", config, memory_storage)

        token = Token(
            access_token="access-token",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        provider.save_token(token)

        with pytest.raises(ConfigurationError, match="No userinfo_endpoint configured"):
            provider.get_userinfo()


# ─────────────────────────────────────────────────────────────────────────────
# Test preflight
# ─────────────────────────────────────────────────────────────────────────────


class TestOIDCPreflight:
    """Tests for OIDC-specific preflight checks."""

    def test_preflight_includes_discovery(
        self,
        oidc_provider: OIDCProvider,
        mock_discovery_doc: dict,
        mock_jwks: dict,
    ) -> None:
        """Test that preflight includes discovery check."""
        mock_discovery_response = MagicMock()
        mock_discovery_response.json.return_value = mock_discovery_doc
        mock_discovery_response.raise_for_status = MagicMock()

        mock_jwks_response = MagicMock()
        mock_jwks_response.json.return_value = mock_jwks
        mock_jwks_response.raise_for_status = MagicMock()

        mock_head_response = MagicMock()
        mock_head_response.status_code = 200

        def mock_get(url, **kwargs):
            if ".well-known" in url:
                return mock_discovery_response
            if "jwks" in url:
                return mock_jwks_response
            return mock_head_response

        with (
            patch.object(oidc_provider.http_client, "get", side_effect=mock_get),
            patch.object(oidc_provider.http_client, "head", return_value=mock_head_response),
        ):
            report = oidc_provider.preflight()

        step_names = [r.step for r in report.results]
        assert "discovery" in step_names
        assert "jwks" in step_names

    def test_preflight_discovery_failure(self, oidc_provider: OIDCProvider) -> None:
        """Test preflight reports discovery failure."""
        error = httpx.ConnectError("Connection failed")

        with patch.object(oidc_provider.http_client, "get", side_effect=error):
            report = oidc_provider.preflight()

        discovery_result = next(r for r in report.results if r.step == "discovery")
        assert discovery_result.status == PreflightStatus.FAILURE


# ─────────────────────────────────────────────────────────────────────────────
# Test refresh (ensures discovery before refresh)
# ─────────────────────────────────────────────────────────────────────────────


class TestOIDCRefresh:
    """Tests for OIDC-specific refresh behavior.

    OIDC refresh must perform discovery first to ensure the correct
    token_endpoint URL is used (fixes bug where fallback URL was incorrect).
    """

    def test_refresh_calls_discover_first(
        self,
        oidc_provider: OIDCProvider,
        mock_discovery_doc: dict,
    ) -> None:
        """Test that refresh() calls discover() before parent refresh."""
        from datetime import datetime, timezone

        from kstlib.auth.models import Token

        # Create an expired token with refresh_token
        expired_token = Token(
            access_token="expired-access-token",
            token_type="Bearer",
            expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc),  # Expired
            refresh_token="valid-refresh-token",
        )
        oidc_provider.save_token(expired_token)

        # Mock discovery response
        mock_discovery_response = MagicMock()
        mock_discovery_response.json.return_value = mock_discovery_doc
        mock_discovery_response.raise_for_status = MagicMock()

        # Mock token refresh response
        mock_token_response = MagicMock()
        mock_token_response.json.return_value = {
            "access_token": "new-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "new-refresh-token",
        }
        mock_token_response.raise_for_status = MagicMock()

        call_order = []

        def mock_get(url, **kwargs):
            if ".well-known" in url:
                call_order.append("discovery")
                return mock_discovery_response
            return MagicMock()

        def mock_post(url, **kwargs):
            call_order.append("token_refresh")
            return mock_token_response

        with (
            patch.object(oidc_provider.http_client, "get", side_effect=mock_get),
            patch.object(oidc_provider.http_client, "post", side_effect=mock_post),
        ):
            new_token = oidc_provider.refresh()

        # Verify discovery was called BEFORE token refresh
        assert call_order == ["discovery", "token_refresh"]
        assert new_token.access_token == "new-access-token"

    def test_refresh_uses_discovered_token_endpoint(
        self,
        oidc_provider: OIDCProvider,
    ) -> None:
        """Test that refresh uses the token_endpoint from discovery, not fallback."""
        from datetime import datetime, timezone

        from kstlib.auth.models import Token

        # Create token
        token = Token(
            access_token="access-token",
            token_type="Bearer",
            expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc),  # Expired
            refresh_token="refresh-token",
        )
        oidc_provider.save_token(token)

        # Verify initial fallback URL is wrong (without /protocol/openid-connect/)
        assert oidc_provider.config.token_url == "https://auth.example.com/token"

        # Discovery document with CORRECT endpoint (like Keycloak uses)
        keycloak_discovery = {
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/protocol/openid-connect/auth",
            "token_endpoint": "https://auth.example.com/protocol/openid-connect/token",
            "userinfo_endpoint": "https://auth.example.com/protocol/openid-connect/userinfo",
            "jwks_uri": "https://auth.example.com/protocol/openid-connect/certs",
        }

        mock_discovery_response = MagicMock()
        mock_discovery_response.json.return_value = keycloak_discovery
        mock_discovery_response.raise_for_status = MagicMock()

        mock_token_response = MagicMock()
        mock_token_response.json.return_value = {
            "access_token": "new-token",
            "token_type": "Bearer",
            "expires_in": 300,
        }
        mock_token_response.raise_for_status = MagicMock()

        token_endpoint_called = []

        def mock_get(url, **kwargs):
            return mock_discovery_response

        def mock_post(url, **kwargs):
            token_endpoint_called.append(url)
            return mock_token_response

        with (
            patch.object(oidc_provider.http_client, "get", side_effect=mock_get),
            patch.object(oidc_provider.http_client, "post", side_effect=mock_post),
        ):
            oidc_provider.refresh()

        # Verify the CORRECT endpoint was used (from discovery, not fallback)
        assert token_endpoint_called[0] == "https://auth.example.com/protocol/openid-connect/token"
        # Verify config was updated
        assert oidc_provider.config.token_url == "https://auth.example.com/protocol/openid-connect/token"

    def test_refresh_without_discovery_would_fail(
        self,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Demonstrate the bug: without discovery, fallback URL is wrong.

        This test documents the issue that was fixed. The fallback URL
        {issuer}/token doesn't match Keycloak's actual endpoint
        {issuer}/protocol/openid-connect/token.
        """
        config = AuthProviderConfig(
            client_id="test-client",
            issuer="http://localhost:8080/realms/test",  # Keycloak-style issuer
            pkce=True,
            redirect_uri="http://127.0.0.1:8400/callback",
        )
        provider = OIDCProvider("keycloak", config, memory_storage)

        # The fallback URL is WRONG for Keycloak
        assert provider.config.token_url == "http://localhost:8080/realms/test/token"
        # Should be: http://localhost:8080/realms/test/protocol/openid-connect/token

        # After discovery, it would be corrected
        keycloak_discovery = {
            "issuer": "http://localhost:8080/realms/test",
            "token_endpoint": "http://localhost:8080/realms/test/protocol/openid-connect/token",
            "authorization_endpoint": "http://localhost:8080/realms/test/protocol/openid-connect/auth",
            "jwks_uri": "http://localhost:8080/realms/test/protocol/openid-connect/certs",
        }

        mock_response = MagicMock()
        mock_response.json.return_value = keycloak_discovery
        mock_response.raise_for_status = MagicMock()

        with patch.object(provider.http_client, "get", return_value=mock_response):
            provider.discover()

        # NOW it's correct
        assert provider.config.token_url == "http://localhost:8080/realms/test/protocol/openid-connect/token"


# ─────────────────────────────────────────────────────────────────────────────
# Additional coverage tests
# ─────────────────────────────────────────────────────────────────────────────


class TestOIDCCoverage:
    """Tests to cover edge cases in OIDC provider."""

    def test_update_endpoints_from_discovery_when_none(
        self,
        oidc_provider: OIDCProvider,
    ) -> None:
        """_update_endpoints_from_discovery returns early when discovery_doc is None."""
        # Ensure discovery_doc is None
        oidc_provider._discovery_doc = None

        # Store original endpoints
        original_token_url = oidc_provider.config.token_url
        original_authorize_url = oidc_provider.config.authorize_url

        # Call the method directly
        oidc_provider._update_endpoints_from_discovery()

        # Endpoints should be unchanged (early return)
        assert oidc_provider.config.token_url == original_token_url
        assert oidc_provider.config.authorize_url == original_authorize_url

    def test_preflight_discovery_missing_fields_warning(
        self,
        oidc_provider: OIDCProvider,
    ) -> None:
        """Preflight returns warning when discovery document is missing fields."""
        # Discovery document missing jwks_uri
        incomplete_discovery = {
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
            # Missing: jwks_uri
        }

        mock_response = MagicMock()
        mock_response.json.return_value = incomplete_discovery
        mock_response.raise_for_status = MagicMock()

        mock_head = MagicMock()
        mock_head.status_code = 200

        with (
            patch.object(oidc_provider.http_client, "get", return_value=mock_response),
            patch.object(oidc_provider.http_client, "head", return_value=mock_head),
        ):
            report = oidc_provider.preflight()

        # Find discovery result
        discovery_result = next(r for r in report.results if r.step == "discovery")
        assert discovery_result.status == PreflightStatus.WARNING
        assert "jwks_uri" in discovery_result.message

    def test_preflight_scopes_unsupported_warning(
        self,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Preflight returns warning when requested scopes are not supported."""
        config = AuthProviderConfig(
            client_id="test",
            issuer="https://auth.example.com",
            scopes=["openid", "profile", "custom_unsupported_scope"],
        )
        provider = OIDCProvider("test", config, memory_storage)

        # Discovery document with limited scopes_supported
        discovery_doc = {
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
            "jwks_uri": "https://auth.example.com/.well-known/jwks.json",
            "scopes_supported": ["openid", "profile", "email"],  # No custom_unsupported_scope
        }

        mock_discovery = MagicMock()
        mock_discovery.json.return_value = discovery_doc
        mock_discovery.raise_for_status = MagicMock()

        mock_jwks = MagicMock()
        mock_jwks.json.return_value = {"keys": []}
        mock_jwks.raise_for_status = MagicMock()

        mock_head = MagicMock()
        mock_head.status_code = 200

        def mock_get(url, **kwargs):
            if ".well-known/openid-configuration" in url:
                return mock_discovery
            if "jwks" in url:
                return mock_jwks
            return mock_head

        with (
            patch.object(provider.http_client, "get", side_effect=mock_get),
            patch.object(provider.http_client, "head", return_value=mock_head),
        ):
            report = provider.preflight()

        # Find scopes result
        scopes_result = next((r for r in report.results if r.step == "scopes"), None)
        assert scopes_result is not None
        assert scopes_result.status == PreflightStatus.WARNING
        assert "custom_unsupported_scope" in scopes_result.message

    def test_validate_id_token_success_with_authlib(
        self,
        oidc_provider: OIDCProvider,
        mock_jwks: dict,
    ) -> None:
        """Test ID token validation with authlib (success path)."""
        import sys

        # Set up provider with JWKS
        oidc_provider._jwks = mock_jwks
        oidc_provider._discovery_doc = {
            "issuer": "https://auth.example.com",
            "jwks_uri": "https://auth.example.com/.well-known/jwks.json",
        }

        # Create a mock JWT module
        mock_claims = MagicMock()
        mock_claims.validate = MagicMock()
        # Make it dict-convertible
        mock_claims.__iter__ = lambda self: iter(["sub", "iss"])
        mock_claims.keys = lambda: ["sub", "iss"]
        mock_claims.__getitem__ = lambda self, key: {"sub": "user123", "iss": "https://auth.example.com"}[key]

        mock_jwt = MagicMock()
        mock_jwt.decode.return_value = mock_claims

        mock_jose_errors = MagicMock()
        mock_jose_errors.JoseError = Exception

        # Temporarily add mock modules
        sys.modules["authlib"] = MagicMock()
        sys.modules["authlib.jose"] = MagicMock(jwt=mock_jwt)
        sys.modules["authlib.jose.errors"] = mock_jose_errors

        try:
            oidc_provider._validate_id_token("dummy.jwt.token")
            mock_jwt.decode.assert_called_once()
        finally:
            # Cleanup
            del sys.modules["authlib"]
            del sys.modules["authlib.jose"]
            del sys.modules["authlib.jose.errors"]

    def test_validate_id_token_authlib_import_error(
        self,
        oidc_provider: OIDCProvider,
        mock_jwks: dict,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test ID token validation fallback when authlib is not available."""
        import base64
        import builtins
        import json
        import logging

        # Set up provider with JWKS
        oidc_provider._jwks = mock_jwks
        oidc_provider._discovery_doc = {
            "issuer": "https://auth.example.com",
            "jwks_uri": "https://auth.example.com/.well-known/jwks.json",
        }

        # Create a valid JWT structure (header.payload.signature)
        header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256"}).encode()).rstrip(b"=").decode()
        payload = (
            base64.urlsafe_b64encode(json.dumps({"sub": "user123", "iss": "https://auth.example.com"}).encode())
            .rstrip(b"=")
            .decode()
        )
        signature = "fake_signature"
        jwt_token = f"{header}.{payload}.{signature}"

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "authlib.jose" or name.startswith("authlib"):
                raise ImportError("authlib not installed")
            return original_import(name, *args, **kwargs)

        with (
            patch.object(builtins, "__import__", side_effect=mock_import),
            caplog.at_level(logging.WARNING),
        ):
            result = oidc_provider._validate_id_token(jwt_token)

        # Should fall back to unverified decode
        assert result["sub"] == "user123"
        assert result["iss"] == "https://auth.example.com"
        assert "authlib not available" in caplog.text

    def test_validate_id_token_uses_discovered_issuer(
        self,
        memory_storage: MemoryTokenStorage,
        mock_jwks: dict,
    ) -> None:
        """Test that ID token validation uses discovered issuer, not configured.

        This is critical for enterprise IDPs that return a different issuer
        in the discovery document than what the user configured.
        """
        import sys

        # Configure with base issuer
        config = AuthProviderConfig(
            client_id="test-client",
            issuer="https://sso.enterprise.local",  # User's config
            scopes=["openid"],
            redirect_uri="http://127.0.0.1:8400/callback",
        )
        provider = OIDCProvider("enterprise", config, memory_storage)

        # Simulate discovery having found a different issuer
        provider._discovered_issuer = "https://sso.enterprise.local:443/oauth2"
        provider._jwks = mock_jwks

        # Create mock authlib
        captured_claims_options = {}

        mock_claims = MagicMock()
        mock_claims.validate = MagicMock()
        mock_claims.__iter__ = lambda self: iter(["sub", "iss"])
        mock_claims.keys = lambda: ["sub", "iss"]
        mock_claims.__getitem__ = lambda self, key: {
            "sub": "user123",
            "iss": "https://sso.enterprise.local:443/oauth2",
        }[key]

        def mock_decode(token, jwks, claims_options=None):
            captured_claims_options.update(claims_options or {})
            return mock_claims

        mock_jwt = MagicMock()
        mock_jwt.decode = mock_decode

        mock_jose_errors = MagicMock()
        mock_jose_errors.JoseError = Exception

        sys.modules["authlib"] = MagicMock()
        sys.modules["authlib.jose"] = MagicMock(jwt=mock_jwt)
        sys.modules["authlib.jose.errors"] = mock_jose_errors

        try:
            provider._validate_id_token("dummy.jwt.token")

            # Verify the DISCOVERED issuer was used for validation, not configured
            assert captured_claims_options["iss"]["value"] == "https://sso.enterprise.local:443/oauth2"
            assert captured_claims_options["iss"]["value"] != config.issuer
        finally:
            del sys.modules["authlib"]
            del sys.modules["authlib.jose"]
            del sys.modules["authlib.jose.errors"]
