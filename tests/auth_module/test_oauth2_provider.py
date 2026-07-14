"""Unit tests for OAuth2Provider."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import httpx
import pytest

from kstlib.auth.errors import (
    AuthError,
    ConfigurationError,
    TokenExchangeError,
    TokenRefreshError,
)
from kstlib.auth.models import AuthFlow, PreflightStatus, Token
from kstlib.auth.providers import AuthProviderConfig, OAuth2Provider

if TYPE_CHECKING:
    from kstlib.auth.token import MemoryTokenStorage


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def minimal_oauth2_config() -> AuthProviderConfig:
    """Create minimal OAuth2 config for testing."""
    return AuthProviderConfig(
        client_id="test-client",
        client_secret="test-secret",
        authorize_url="https://auth.example.com/authorize",
        token_url="https://auth.example.com/token",
        redirect_uri="http://127.0.0.1:8400/callback",
        scopes=["read", "write"],
    )


@pytest.fixture
def oauth2_provider(
    minimal_oauth2_config: AuthProviderConfig,
    memory_storage: MemoryTokenStorage,
) -> OAuth2Provider:
    """Create an OAuth2Provider for testing."""
    return OAuth2Provider("test", minimal_oauth2_config, memory_storage)


# ─────────────────────────────────────────────────────────────────────────────
# Test __init__ validation
# ─────────────────────────────────────────────────────────────────────────────


class TestOAuth2ProviderInit:
    """Tests for OAuth2Provider initialization."""

    def test_init_requires_authorize_url(self, memory_storage: MemoryTokenStorage) -> None:
        """Test that __init__ raises if authorize_url missing."""
        # Create config object directly to bypass AuthProviderConfig validation
        config = AuthProviderConfig.__new__(AuthProviderConfig)
        config.client_id = "test"
        config.client_secret = None
        config.authorize_url = None  # Missing
        config.token_url = "https://auth.example.com/token"
        config.redirect_uri = "http://localhost/callback"
        config.scopes = []
        config.issuer = None
        config.pkce = False
        config.revoke_url = None
        config.userinfo_url = None
        config.jwks_uri = None
        config.end_session_endpoint = None
        config.discovery_ttl = 3600
        config.headers = {}
        config.extra = {}

        with pytest.raises(ConfigurationError, match="authorize_url"):
            OAuth2Provider("test", config, memory_storage)

    def test_init_requires_token_url(self, memory_storage: MemoryTokenStorage) -> None:
        """Test that __init__ raises if token_url missing."""
        config = AuthProviderConfig.__new__(AuthProviderConfig)
        config.client_id = "test"
        config.client_secret = None
        config.authorize_url = "https://auth.example.com/authorize"
        config.token_url = None  # Missing
        config.redirect_uri = "http://localhost/callback"
        config.scopes = []
        config.issuer = None
        config.pkce = False
        config.revoke_url = None
        config.userinfo_url = None
        config.jwks_uri = None
        config.end_session_endpoint = None
        config.discovery_ttl = 3600
        config.headers = {}
        config.extra = {}

        with pytest.raises(ConfigurationError, match="token_url"):
            OAuth2Provider("test", config, memory_storage)

    def test_flow_property(self, oauth2_provider: OAuth2Provider) -> None:
        """Test that flow property returns AUTHORIZATION_CODE."""
        assert oauth2_provider.flow == AuthFlow.AUTHORIZATION_CODE


# ─────────────────────────────────────────────────────────────────────────────
# Test from_config
# ─────────────────────────────────────────────────────────────────────────────


class TestOAuth2ProviderFromConfig:
    """Tests for OAuth2Provider.from_config()."""

    def test_from_config_provider_not_found(self) -> None:
        """Test that from_config raises if provider not found."""
        with (
            patch("kstlib.auth.config.get_provider_config", return_value=None),
            pytest.raises(ConfigurationError, match="not found"),
        ):
            OAuth2Provider.from_config("nonexistent")

    def test_from_config_wrong_type(self) -> None:
        """Test that from_config raises if provider type is not oauth2."""
        with (
            patch("kstlib.auth.config.get_provider_config", return_value={"type": "oidc"}),
            pytest.raises(ConfigurationError, match="expected 'oauth2'"),
        ):
            OAuth2Provider.from_config("oidc-provider")

    def test_from_config_success(self, minimal_oauth2_config: AuthProviderConfig) -> None:
        """Test successful from_config creation."""
        from kstlib.auth.token import MemoryTokenStorage

        mock_provider_cfg = {"type": "oauth2"}

        with (
            patch("kstlib.auth.config.get_provider_config", return_value=mock_provider_cfg),
            patch("kstlib.auth.config.build_provider_config", return_value=minimal_oauth2_config),
            patch("kstlib.auth.config.get_token_storage_from_config", return_value=MemoryTokenStorage()),
        ):
            provider = OAuth2Provider.from_config("github")

            assert provider.name == "github"
            assert provider.config == minimal_oauth2_config


# ─────────────────────────────────────────────────────────────────────────────
# Test get_authorization_url
# ─────────────────────────────────────────────────────────────────────────────


class TestGetAuthorizationUrl:
    """Tests for get_authorization_url()."""

    def test_generates_state_if_not_provided(self, oauth2_provider: OAuth2Provider) -> None:
        """Test that state is auto-generated."""
        url, state = oauth2_provider.get_authorization_url()

        assert state is not None
        assert len(state) > 0
        assert "state=" in url

    def test_uses_provided_state(self, oauth2_provider: OAuth2Provider) -> None:
        """Test that provided state is used."""
        url, state = oauth2_provider.get_authorization_url(state="my-custom-state")

        assert state == "my-custom-state"
        assert "state=my-custom-state" in url

    def test_url_contains_required_params(self, oauth2_provider: OAuth2Provider) -> None:
        """Test that URL contains all required OAuth2 params."""
        url, _ = oauth2_provider.get_authorization_url()

        assert "response_type=code" in url
        assert "client_id=test-client" in url
        assert "redirect_uri=" in url
        assert "scope=read+write" in url

    def test_url_includes_extra_params(self, memory_storage: MemoryTokenStorage) -> None:
        """Test that extra authorize_params are included."""
        config = AuthProviderConfig(
            client_id="test",
            authorize_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
            redirect_uri="http://localhost/callback",
            extra={"authorize_params": {"prompt": "consent"}},
        )
        provider = OAuth2Provider("test", config, memory_storage)

        url, _ = provider.get_authorization_url()

        assert "prompt=consent" in url


# ─────────────────────────────────────────────────────────────────────────────
# Test exchange_code
# ─────────────────────────────────────────────────────────────────────────────


class TestExchangeCode:
    """Tests for exchange_code()."""

    def test_exchange_code_state_mismatch(self, oauth2_provider: OAuth2Provider) -> None:
        """Test that state mismatch raises error."""
        oauth2_provider._pending_state = "expected-state"

        with pytest.raises(TokenExchangeError, match="State mismatch"):
            oauth2_provider.exchange_code(code="auth-code", state="wrong-state")

    def test_exchange_code_success(self, oauth2_provider: OAuth2Provider) -> None:
        """Test successful token exchange."""
        oauth2_provider._pending_state = "test-state"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "new-refresh-token",
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(oauth2_provider.http_client, "post", return_value=mock_response):
            token = oauth2_provider.exchange_code(code="auth-code", state="test-state")

        assert token.access_token == "new-access-token"
        assert token.refresh_token == "new-refresh-token"
        assert oauth2_provider._pending_state is None

    def test_exchange_code_with_pkce_verifier(self, oauth2_provider: OAuth2Provider) -> None:
        """Test that code_verifier is included in request."""
        oauth2_provider._pending_state = "test-state"

        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "token", "token_type": "Bearer"}
        mock_response.raise_for_status = MagicMock()

        with patch.object(oauth2_provider.http_client, "post", return_value=mock_response) as mock_post:
            oauth2_provider.exchange_code(code="code", state="test-state", code_verifier="verifier123")

        call_data = mock_post.call_args.kwargs["data"]
        assert call_data["code_verifier"] == "verifier123"

    def test_exchange_code_http_error(self, oauth2_provider: OAuth2Provider) -> None:
        """Test exchange_code handles HTTP errors."""
        oauth2_provider._pending_state = "test-state"

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"error": "invalid_grant", "error_description": "Code expired"}
        mock_response.text = "Code expired"

        error = httpx.HTTPStatusError("Bad Request", request=MagicMock(), response=mock_response)

        with (
            patch.object(oauth2_provider.http_client, "post", side_effect=error),
            pytest.raises(TokenExchangeError, match="Code expired"),
        ):
            oauth2_provider.exchange_code(code="code", state="test-state")

    def test_exchange_code_network_error(self, oauth2_provider: OAuth2Provider) -> None:
        """Test exchange_code handles network errors."""
        oauth2_provider._pending_state = "test-state"

        with (
            patch.object(oauth2_provider.http_client, "post", side_effect=httpx.ConnectError("Connection failed")),
            pytest.raises(TokenExchangeError, match="Network error"),
        ):
            oauth2_provider.exchange_code(code="code", state="test-state")


# ─────────────────────────────────────────────────────────────────────────────
# Test exchange_code error contract (provider-responded vs transport)
# ─────────────────────────────────────────────────────────────────────────────


class TestExchangeCodeErrorContract:
    """Locks the provider-responded vs transport discriminant on exchange_code.

    Contract: ``status_code`` is the HTTP status answered by the provider
    (``error_code`` is then guaranteed non-None), ``None`` when no HTTP
    response was received (transport failure or local pre-network guard).
    """

    def test_provider_error_carries_error_code(
        self,
        minimal_oauth2_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Provider answering 400 with a JSON error body yields its error code."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400,
                json={"error": "not_allowed", "error_description": "Client not allowed"},
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OAuth2Provider("test", minimal_oauth2_config, memory_storage, http_client=client)
            _, state = provider.get_authorization_url()

            with pytest.raises(TokenExchangeError) as exc_info:
                provider.exchange_code(code="auth-code", state=state)

        assert exc_info.value.error_code == "not_allowed"
        assert "Client not allowed" in str(exc_info.value)

    def test_transport_error_error_code_none(
        self,
        minimal_oauth2_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Transport failure (no HTTP response) yields error_code None."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused", request=request)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OAuth2Provider("test", minimal_oauth2_config, memory_storage, http_client=client)
            _, state = provider.get_authorization_url()

            with pytest.raises(TokenExchangeError, match="Network error") as exc_info:
                provider.exchange_code(code="auth-code", state=state)

        assert exc_info.value.error_code is None

    def test_provider_error_non_json_body_falls_back_unknown(
        self,
        minimal_oauth2_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Provider error with an unreadable body falls back to error_code 'unknown'."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, text="<html>Bad Request</html>")

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OAuth2Provider("test", minimal_oauth2_config, memory_storage, http_client=client)
            _, state = provider.get_authorization_url()

            with pytest.raises(TokenExchangeError) as exc_info:
                provider.exchange_code(code="auth-code", state=state)

        assert exc_info.value.error_code == "unknown"

    def test_provider_4xx_sets_status_code_not_retryable(
        self,
        minimal_oauth2_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Provider 400 sets status_code=400; a 4xx rejection is definitive (not retryable)."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400,
                json={"error": "invalid_grant", "error_description": "Code expired"},
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OAuth2Provider("test", minimal_oauth2_config, memory_storage, http_client=client)
            _, state = provider.get_authorization_url()

            with pytest.raises(TokenExchangeError) as exc_info:
                provider.exchange_code(code="auth-code", state=state)

        assert exc_info.value.status_code == 400
        assert exc_info.value.retryable is False

    def test_provider_5xx_sets_status_code_retryable(
        self,
        minimal_oauth2_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Provider 503 sets status_code=503; a 5xx answer is transient (retryable)."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                503,
                json={"error": "temporarily_unavailable", "error_description": "Try again later"},
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OAuth2Provider("test", minimal_oauth2_config, memory_storage, http_client=client)
            _, state = provider.get_authorization_url()

            with pytest.raises(TokenExchangeError) as exc_info:
                provider.exchange_code(code="auth-code", state=state)

        assert exc_info.value.status_code == 503
        assert exc_info.value.retryable is True

    def test_transport_error_status_code_none_retryable(
        self,
        minimal_oauth2_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Transport failure keeps status_code None and is retryable."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused", request=request)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OAuth2Provider("test", minimal_oauth2_config, memory_storage, http_client=client)
            _, state = provider.get_authorization_url()

            with pytest.raises(TokenExchangeError) as exc_info:
                provider.exchange_code(code="auth-code", state=state)

        assert exc_info.value.status_code is None
        assert exc_info.value.retryable is True

    def test_state_mismatch_guard_error_code(self, oauth2_provider: OAuth2Provider) -> None:
        """Local CSRF guard rejects with error_code 'state_mismatch' before any request."""
        oauth2_provider.get_authorization_url()

        with pytest.raises(TokenExchangeError) as exc_info:
            oauth2_provider.exchange_code(code="auth-code", state="wrong-state")

        assert exc_info.value.error_code == "state_mismatch"

    def test_state_mismatch_guard_status_code_none_not_retryable(self, oauth2_provider: OAuth2Provider) -> None:
        """Local CSRF guard has status_code None (no provider contact) and is not retryable."""
        oauth2_provider.get_authorization_url()

        with pytest.raises(TokenExchangeError) as exc_info:
            oauth2_provider.exchange_code(code="auth-code", state="wrong-state")

        assert exc_info.value.status_code is None
        assert exc_info.value.retryable is False


# ─────────────────────────────────────────────────────────────────────────────
# Test exchange_code_stateless (server-side profile)
# ─────────────────────────────────────────────────────────────────────────────


class TestExchangeCodeStateless:
    """Tests for the stateless exchange path and its stateful non-regression locks.

    The stateless path is for server-side multi-user consumers: the caller
    owns state (CSRF) and PKCE, so the method must touch no per-flow instance
    state, emit no [SECURITY] warning, and never persist the token (storage
    is keyed by provider name, not by end user).
    """

    def test_stateless_success_returns_token_without_saving(
        self,
        minimal_oauth2_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Stateless exchange returns the token, persists nothing, warns nothing."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"access_token": "stateless-access-token", "token_type": "Bearer"},
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OAuth2Provider("test", minimal_oauth2_config, memory_storage, http_client=client)
            with caplog.at_level("WARNING"):
                token = provider.exchange_code_stateless(code="auth-code")

        assert token.access_token == "stateless-access-token"
        assert memory_storage.load("test") is None
        security_records = [r for r in caplog.records if "[SECURITY]" in r.getMessage()]
        assert not security_records, security_records

    def test_stateless_sends_code_verifier(
        self,
        minimal_oauth2_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Stateless exchange forwards the explicit code_verifier to the token endpoint."""
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = request.content.decode()
            return httpx.Response(200, json={"access_token": "at", "token_type": "Bearer"})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OAuth2Provider("test", minimal_oauth2_config, memory_storage, http_client=client)
            provider.exchange_code_stateless(code="auth-code", code_verifier="verifier-123")

        assert "code_verifier=verifier-123" in captured["body"]

    def test_stateless_provider_4xx_contract(
        self,
        minimal_oauth2_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Stateless exchange carries the C3 contract on a provider 4xx answer."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400,
                json={"error": "invalid_grant", "error_description": "Code expired"},
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OAuth2Provider("test", minimal_oauth2_config, memory_storage, http_client=client)

            with pytest.raises(TokenExchangeError) as exc_info:
                provider.exchange_code_stateless(code="auth-code")

        assert exc_info.value.error_code == "invalid_grant"
        assert exc_info.value.status_code == 400
        assert exc_info.value.retryable is False

    def test_stateless_provider_5xx_retryable(
        self,
        minimal_oauth2_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Stateless exchange marks a provider 5xx answer as retryable."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"error": "temporarily_unavailable"})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OAuth2Provider("test", minimal_oauth2_config, memory_storage, http_client=client)

            with pytest.raises(TokenExchangeError) as exc_info:
                provider.exchange_code_stateless(code="auth-code")

        assert exc_info.value.status_code == 503
        assert exc_info.value.retryable is True

    def test_stateless_transport_error_contract(
        self,
        minimal_oauth2_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Stateless exchange keeps the transport discriminant (both None, retryable)."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused", request=request)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OAuth2Provider("test", minimal_oauth2_config, memory_storage, http_client=client)

            with pytest.raises(TokenExchangeError, match="Network error") as exc_info:
                provider.exchange_code_stateless(code="auth-code")

        assert exc_info.value.error_code is None
        assert exc_info.value.status_code is None
        assert exc_info.value.retryable is True

    def test_stateless_does_not_touch_pending_state(
        self,
        minimal_oauth2_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Stateless exchange leaves the per-flow instance state untouched."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"access_token": "at", "token_type": "Bearer"})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OAuth2Provider("test", minimal_oauth2_config, memory_storage, http_client=client)
            _, state = provider.get_authorization_url()
            provider.exchange_code_stateless(code="auth-code")

        assert provider._pending_state == state

    def test_stateful_exchange_sends_code_verifier(
        self,
        minimal_oauth2_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """exchange_code forwards code_verifier to the token endpoint (lock, pre-existing behavior)."""
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = request.content.decode()
            return httpx.Response(200, json={"access_token": "at", "token_type": "Bearer"})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OAuth2Provider("test", minimal_oauth2_config, memory_storage, http_client=client)
            _, state = provider.get_authorization_url()
            provider.exchange_code(code="auth-code", state=state, code_verifier="verifier-123")

        assert "code_verifier=verifier-123" in captured["body"]

    def test_stateful_no_pending_state_warns(
        self,
        minimal_oauth2_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """exchange_code without prior get_authorization_url still warns (lock, CLI behavior)."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"access_token": "at", "token_type": "Bearer"})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OAuth2Provider("test", minimal_oauth2_config, memory_storage, http_client=client)
            with caplog.at_level("WARNING"):
                provider.exchange_code(code="auth-code", state="some-state")

        assert any("[SECURITY]" in r.getMessage() and "No pending state" in r.getMessage() for r in caplog.records), (
            caplog.records
        )


# ─────────────────────────────────────────────────────────────────────────────
# Test refresh
# ─────────────────────────────────────────────────────────────────────────────


class TestRefresh:
    """Tests for refresh()."""

    def test_refresh_no_token(self, oauth2_provider: OAuth2Provider) -> None:
        """Test refresh raises if no token available."""
        with pytest.raises(TokenRefreshError, match="No token to refresh"):
            oauth2_provider.refresh()

    def test_refresh_no_refresh_token(self, oauth2_provider: OAuth2Provider, sample_token: Token) -> None:
        """Test refresh raises if token has no refresh_token."""
        token_without_refresh = Token(
            access_token="access",
            token_type="Bearer",
            refresh_token=None,
        )
        with pytest.raises(TokenRefreshError, match="no refresh_token"):
            oauth2_provider.refresh(token=token_without_refresh)

    def test_refresh_success(self, oauth2_provider: OAuth2Provider, sample_token: Token) -> None:
        """Test successful token refresh."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(oauth2_provider.http_client, "post", return_value=mock_response):
            new_token = oauth2_provider.refresh(token=sample_token)

        assert new_token.access_token == "new-access-token"
        # Refresh token should be preserved if not returned
        assert new_token.refresh_token == sample_token.refresh_token

    def test_refresh_http_error_5xx(self, oauth2_provider: OAuth2Provider, sample_token: Token) -> None:
        """Test refresh handles 5xx errors as retryable."""
        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.json.return_value = {"error": "service_unavailable"}
        mock_response.text = "Service unavailable"

        error = httpx.HTTPStatusError("Service Unavailable", request=MagicMock(), response=mock_response)

        with (
            patch.object(oauth2_provider.http_client, "post", side_effect=error),
            pytest.raises(TokenRefreshError) as exc_info,
        ):
            oauth2_provider.refresh(token=sample_token)

        assert exc_info.value.retryable is True

    def test_refresh_network_error(self, oauth2_provider: OAuth2Provider, sample_token: Token) -> None:
        """Test refresh handles network errors as retryable."""
        with (
            patch.object(oauth2_provider.http_client, "post", side_effect=httpx.ConnectError("Connection failed")),
            pytest.raises(TokenRefreshError) as exc_info,
        ):
            oauth2_provider.refresh(token=sample_token)

        assert exc_info.value.retryable is True

    def test_refresh_404_error(self, oauth2_provider: OAuth2Provider, sample_token: Token) -> None:
        """Test refresh handles 404 with clear message about token endpoint."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"

        error = httpx.HTTPStatusError("Not Found", request=MagicMock(), response=mock_response)

        with (
            patch.object(oauth2_provider.http_client, "post", side_effect=error),
            pytest.raises(TokenRefreshError) as exc_info,
        ):
            oauth2_provider.refresh(token=sample_token)

        # Should have clear message about endpoint not found
        assert "Token endpoint not found" in str(exc_info.value)
        assert "re-authenticate" in str(exc_info.value).lower()
        assert exc_info.value.retryable is False

    def test_refresh_401_error(self, oauth2_provider: OAuth2Provider, sample_token: Token) -> None:
        """Test refresh handles 401 with message about expired token."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"error": "invalid_grant", "error_description": "Token has been revoked"}
        mock_response.text = "Unauthorized"

        error = httpx.HTTPStatusError("Unauthorized", request=MagicMock(), response=mock_response)

        with (
            patch.object(oauth2_provider.http_client, "post", side_effect=error),
            pytest.raises(TokenRefreshError) as exc_info,
        ):
            oauth2_provider.refresh(token=sample_token)

        # Should include the error_description and suggest re-auth
        assert "Token has been revoked" in str(exc_info.value)
        assert "re-authenticate" in str(exc_info.value).lower()
        assert exc_info.value.retryable is False

    def test_refresh_400_error(self, oauth2_provider: OAuth2Provider, sample_token: Token) -> None:
        """Test refresh handles 400 with message about invalid token."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"error": "invalid_grant", "error_description": "Refresh token expired"}
        mock_response.text = "Bad Request"

        error = httpx.HTTPStatusError("Bad Request", request=MagicMock(), response=mock_response)

        with (
            patch.object(oauth2_provider.http_client, "post", side_effect=error),
            pytest.raises(TokenRefreshError) as exc_info,
        ):
            oauth2_provider.refresh(token=sample_token)

        # Should include the error_description and suggest re-auth
        assert "Refresh token expired" in str(exc_info.value)
        assert "re-authenticate" in str(exc_info.value).lower()
        assert exc_info.value.retryable is False


# ─────────────────────────────────────────────────────────────────────────────
# Test revoke
# ─────────────────────────────────────────────────────────────────────────────


class TestRevoke:
    """Tests for revoke()."""

    def test_revoke_no_revoke_url(self, memory_storage: MemoryTokenStorage) -> None:
        """Test revoke returns False if no revoke_url configured."""
        config = AuthProviderConfig(
            client_id="test",
            authorize_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
            redirect_uri="http://localhost/callback",
            # No revoke_url
        )
        provider = OAuth2Provider("test", config, memory_storage)

        assert provider.revoke() is False

    def test_revoke_no_token(
        self,
        minimal_oauth2_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Test revoke returns False if no token to revoke."""
        config = AuthProviderConfig(
            client_id="test",
            authorize_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
            revoke_url="https://auth.example.com/revoke",
            redirect_uri="http://localhost/callback",
        )
        provider = OAuth2Provider("test", config, memory_storage)

        assert provider.revoke() is False

    def test_revoke_success(self, memory_storage: MemoryTokenStorage, sample_token: Token) -> None:
        """Test successful token revocation."""
        config = AuthProviderConfig(
            client_id="test",
            client_secret="secret",
            authorize_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
            revoke_url="https://auth.example.com/revoke",
            redirect_uri="http://localhost/callback",
        )
        provider = OAuth2Provider("test", config, memory_storage)
        provider.save_token(sample_token)

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(provider.http_client, "post", return_value=mock_response):
            result = provider.revoke()

        assert result is True
        assert provider.get_token(auto_refresh=False) is None

    def test_revoke_network_error_logs_warning(
        self,
        memory_storage: MemoryTokenStorage,
        sample_token: Token,
    ) -> None:
        """Test revoke logs warning on network error but continues."""
        config = AuthProviderConfig(
            client_id="test",
            authorize_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
            revoke_url="https://auth.example.com/revoke",
            redirect_uri="http://localhost/callback",
        )
        provider = OAuth2Provider("test", config, memory_storage)
        provider.save_token(sample_token)

        with patch.object(provider.http_client, "post", side_effect=httpx.ConnectError("Failed")):
            result = provider.revoke()

        # Should return False since all revocation attempts failed
        assert result is False

    @staticmethod
    def _revoke_provider(storage: MemoryTokenStorage) -> OAuth2Provider:
        """Build a provider with a revoke_url configured."""
        config = AuthProviderConfig(
            client_id="test",
            client_secret="secret",
            authorize_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
            revoke_url="https://auth.example.com/revoke",
            redirect_uri="http://localhost/callback",
        )
        return OAuth2Provider("test", config, storage)

    @staticmethod
    def _posted_hints(mock_post: MagicMock) -> list[str]:
        """Return the token_type_hint of each revocation POST made."""
        return [call.kwargs["data"]["token_type_hint"] for call in mock_post.call_args_list]

    def test_revoke_kinds_refresh_only(self, memory_storage: MemoryTokenStorage, sample_token: Token) -> None:
        """Verify kinds=('refresh_token',) posts only the refresh token."""
        provider = self._revoke_provider(memory_storage)
        mock_response = MagicMock()
        mock_response.status_code = 200
        with patch.object(provider.http_client, "post", return_value=mock_response) as mock_post:
            result = provider.revoke(sample_token, kinds=("refresh_token",))
        assert result is True
        assert self._posted_hints(mock_post) == ["refresh_token"]

    def test_revoke_empty_access_no_empty_post(self, memory_storage: MemoryTokenStorage) -> None:
        """Verify an empty access_token never triggers a POST with an empty token value."""
        provider = self._revoke_provider(memory_storage)
        token = Token(access_token="", refresh_token="rt_value")
        mock_response = MagicMock()
        mock_response.status_code = 200
        with patch.object(provider.http_client, "post", return_value=mock_response) as mock_post:
            provider.revoke(token)
        posted_tokens = [call.kwargs["data"]["token"] for call in mock_post.call_args_list]
        assert "" not in posted_tokens
        assert posted_tokens == ["rt_value"]

    def test_revoke_bool_reflects_targeted_subset(self, memory_storage: MemoryTokenStorage) -> None:
        """Verify the returned bool reflects only the targeted subset."""
        provider = self._revoke_provider(memory_storage)
        mock_response = MagicMock()
        mock_response.status_code = 200
        token = Token(access_token="at", refresh_token="rt")
        with patch.object(provider.http_client, "post", return_value=mock_response):
            assert provider.revoke(token, kinds=("refresh_token",)) is True
        token_no_refresh = Token(access_token="at", refresh_token=None)
        with patch.object(provider.http_client, "post", return_value=mock_response) as mock_post:
            assert provider.revoke(token_no_refresh, kinds=("refresh_token",)) is False
        assert self._posted_hints(mock_post) == []

    def test_revoke_unknown_kind_raises(self, memory_storage: MemoryTokenStorage, sample_token: Token) -> None:
        """Verify an unknown kind fails fast with ValueError."""
        provider = self._revoke_provider(memory_storage)
        with pytest.raises(ValueError, match="unknown revoke kind"):
            provider.revoke(sample_token, kinds=("bogus_kind",))

    def test_revoke_empty_kinds_no_post(self, memory_storage: MemoryTokenStorage, sample_token: Token) -> None:
        """Verify kinds=() posts nothing and returns False."""
        provider = self._revoke_provider(memory_storage)
        with patch.object(provider.http_client, "post") as mock_post:
            result = provider.revoke(sample_token, kinds=())
        assert result is False
        mock_post.assert_not_called()

    def test_revoke_default_kinds_posts_both(self, memory_storage: MemoryTokenStorage, sample_token: Token) -> None:
        """Verify revoke without kinds posts both access and refresh (backward-compat)."""
        provider = self._revoke_provider(memory_storage)
        mock_response = MagicMock()
        mock_response.status_code = 200
        with patch.object(provider.http_client, "post", return_value=mock_response) as mock_post:
            provider.revoke(sample_token)
        assert self._posted_hints(mock_post) == ["access_token", "refresh_token"]


# ─────────────────────────────────────────────────────────────────────────────
# Test get_userinfo
# ─────────────────────────────────────────────────────────────────────────────


class TestGetUserInfo:
    """Tests for get_userinfo()."""

    def test_get_userinfo_no_url_configured(self, oauth2_provider: OAuth2Provider) -> None:
        """Test get_userinfo raises if userinfo_url not configured."""
        # Default fixture has no userinfo_url
        with pytest.raises(ConfigurationError, match="userinfo_url"):
            oauth2_provider.get_userinfo()

    def test_get_userinfo_no_token(self, memory_storage: MemoryTokenStorage) -> None:
        """Test get_userinfo raises if no token available."""
        config = AuthProviderConfig(
            client_id="test",
            authorize_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
            userinfo_url="https://auth.example.com/userinfo",
            redirect_uri="http://localhost/callback",
        )
        provider = OAuth2Provider("test", config, memory_storage)

        with pytest.raises(AuthError, match="No token available"):
            provider.get_userinfo()

    def test_get_userinfo_success(self, memory_storage: MemoryTokenStorage, sample_token: Token) -> None:
        """Test successful userinfo fetch."""
        config = AuthProviderConfig(
            client_id="test",
            authorize_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
            userinfo_url="https://auth.example.com/userinfo",
            redirect_uri="http://localhost/callback",
        )
        provider = OAuth2Provider("test", config, memory_storage)
        provider.save_token(sample_token)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "sub": "user123",
            "name": "Test User",
            "email": "test@example.com",
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(provider.http_client, "get", return_value=mock_response) as mock_get:
            userinfo = provider.get_userinfo()

        assert userinfo["sub"] == "user123"
        assert userinfo["name"] == "Test User"
        assert userinfo["email"] == "test@example.com"

        # Verify Authorization header was set
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args.kwargs
        assert "Authorization" in call_kwargs["headers"]
        assert call_kwargs["headers"]["Authorization"] == f"Bearer {sample_token.access_token}"

    def test_get_userinfo_with_explicit_token(self, memory_storage: MemoryTokenStorage) -> None:
        """Test get_userinfo with explicit token parameter."""
        config = AuthProviderConfig(
            client_id="test",
            authorize_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
            userinfo_url="https://auth.example.com/userinfo",
            redirect_uri="http://localhost/callback",
        )
        provider = OAuth2Provider("test", config, memory_storage)

        explicit_token = Token(access_token="explicit-token", token_type="Bearer")

        mock_response = MagicMock()
        mock_response.json.return_value = {"sub": "user456"}
        mock_response.raise_for_status = MagicMock()

        with patch.object(provider.http_client, "get", return_value=mock_response) as mock_get:
            userinfo = provider.get_userinfo(token=explicit_token)

        assert userinfo["sub"] == "user456"
        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs["headers"]["Authorization"] == "Bearer explicit-token"

    def test_get_userinfo_http_error(self, memory_storage: MemoryTokenStorage, sample_token: Token) -> None:
        """Test get_userinfo handles HTTP errors."""
        config = AuthProviderConfig(
            client_id="test",
            authorize_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
            userinfo_url="https://auth.example.com/userinfo",
            redirect_uri="http://localhost/callback",
        )
        provider = OAuth2Provider("test", config, memory_storage)
        provider.save_token(sample_token)

        mock_response = MagicMock()
        mock_response.status_code = 401
        error = httpx.HTTPStatusError("Unauthorized", request=MagicMock(), response=mock_response)

        with (
            patch.object(provider.http_client, "get", side_effect=error),
            pytest.raises(AuthError, match="HTTP 401"),
        ):
            provider.get_userinfo()

    def test_get_userinfo_network_error(self, memory_storage: MemoryTokenStorage, sample_token: Token) -> None:
        """Test get_userinfo handles network errors."""
        config = AuthProviderConfig(
            client_id="test",
            authorize_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
            userinfo_url="https://auth.example.com/userinfo",
            redirect_uri="http://localhost/callback",
        )
        provider = OAuth2Provider("test", config, memory_storage)
        provider.save_token(sample_token)

        with (
            patch.object(provider.http_client, "get", side_effect=httpx.ConnectError("Connection failed")),
            pytest.raises(AuthError, match="Connection failed"),
        ):
            provider.get_userinfo()


# ─────────────────────────────────────────────────────────────────────────────
# Test preflight
# ─────────────────────────────────────────────────────────────────────────────


class TestPreflight:
    """Tests for preflight validation."""

    def test_preflight_checks_config(self, oauth2_provider: OAuth2Provider) -> None:
        """Test that preflight includes config check."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(oauth2_provider.http_client, "head", return_value=mock_response):
            report = oauth2_provider.preflight()

        step_names = [r.step for r in report.results]
        assert "config" in step_names

    def test_preflight_config_missing_fields(
        self,
        minimal_oauth2_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Test preflight reports config errors."""
        # Create a valid provider first
        provider = OAuth2Provider("test", minimal_oauth2_config, memory_storage)

        # Now replace config with one that has empty required fields
        bad_config = AuthProviderConfig.__new__(AuthProviderConfig)
        bad_config.client_id = ""  # Empty - should be flagged
        bad_config.client_secret = None
        bad_config.authorize_url = ""  # Empty - should be flagged
        bad_config.token_url = ""  # Empty - should be flagged
        bad_config.redirect_uri = ""  # Empty - should be flagged
        bad_config.scopes = []
        bad_config.issuer = None
        bad_config.pkce = False
        bad_config.revoke_url = None
        bad_config.userinfo_url = None
        bad_config.jwks_uri = None
        bad_config.end_session_endpoint = None
        bad_config.discovery_ttl = 3600
        bad_config.headers = {}
        bad_config.extra = {}

        # Replace config to test _check_config directly
        provider.config = bad_config

        result = provider._check_config()

        assert result.status == PreflightStatus.FAILURE
        assert "client_id" in result.message
        assert "redirect_uri" in result.message

    def test_preflight_endpoint_check_success(self, oauth2_provider: OAuth2Provider) -> None:
        """Test endpoint check success."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(oauth2_provider.http_client, "head", return_value=mock_response):
            result = oauth2_provider._check_endpoint("token", oauth2_provider.config.token_url)

        assert result.status == PreflightStatus.SUCCESS

    def test_preflight_endpoint_check_5xx(self, oauth2_provider: OAuth2Provider) -> None:
        """Test endpoint check returns warning on 5xx."""
        mock_response = MagicMock()
        mock_response.status_code = 503

        with patch.object(oauth2_provider.http_client, "head", return_value=mock_response):
            result = oauth2_provider._check_endpoint("token", oauth2_provider.config.token_url)

        assert result.status == PreflightStatus.WARNING

    def test_preflight_endpoint_check_unreachable(self, oauth2_provider: OAuth2Provider) -> None:
        """Test endpoint check failure on network error."""
        with patch.object(oauth2_provider.http_client, "head", side_effect=httpx.ConnectError("Failed")):
            result = oauth2_provider._check_endpoint("token", oauth2_provider.config.token_url)

        assert result.status == PreflightStatus.FAILURE
        assert "unreachable" in result.message

    def test_preflight_endpoint_not_configured(self, oauth2_provider: OAuth2Provider) -> None:
        """Test endpoint check skipped when not configured."""
        result = oauth2_provider._check_endpoint("userinfo", None)

        assert result.status == PreflightStatus.SKIPPED

    def test_preflight_includes_revoke_url(self, memory_storage: MemoryTokenStorage) -> None:
        """Test preflight includes revoke endpoint check when configured."""
        config = AuthProviderConfig(
            client_id="test",
            authorize_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
            revoke_url="https://auth.example.com/revoke",
            redirect_uri="http://localhost/callback",
        )
        provider = OAuth2Provider("test", config, memory_storage)

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(provider.http_client, "head", return_value=mock_response):
            report = provider.preflight()

        step_names = [r.step for r in report.results]
        assert "revoke" in step_names

    def test_preflight_includes_userinfo_url(self, memory_storage: MemoryTokenStorage) -> None:
        """Test preflight includes userinfo endpoint check when configured."""
        config = AuthProviderConfig(
            client_id="test",
            authorize_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
            userinfo_url="https://auth.example.com/userinfo",
            redirect_uri="http://localhost/callback",
        )
        provider = OAuth2Provider("test", config, memory_storage)

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(provider.http_client, "head", return_value=mock_response):
            report = provider.preflight()

        step_names = [r.step for r in report.results]
        assert "userinfo" in step_names


# ─────────────────────────────────────────────────────────────────────────────
# Test _parse_error_response
# ─────────────────────────────────────────────────────────────────────────────


class TestParseErrorResponse:
    """Tests for _parse_error_response()."""

    def test_parse_json_error(self, oauth2_provider: OAuth2Provider) -> None:
        """Test parsing JSON error response."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "error": "invalid_request",
            "error_description": "Missing parameter",
        }

        result = oauth2_provider._parse_error_response(mock_response)

        assert result["error"] == "invalid_request"
        assert result["error_description"] == "Missing parameter"

    def test_parse_non_json_error(self, oauth2_provider: OAuth2Provider) -> None:
        """Test parsing non-JSON error response."""
        mock_response = MagicMock()
        mock_response.json.side_effect = ValueError("Not JSON")
        mock_response.text = "Internal Server Error"

        result = oauth2_provider._parse_error_response(mock_response)

        assert result["error"] == "unknown"
        assert result["error_description"] == "Internal Server Error"


# ─────────────────────────────────────────────────────────────────────────────
# Test custom headers
# ─────────────────────────────────────────────────────────────────────────────


class TestCustomHeaders:
    """Tests for custom HTTP headers support."""

    def test_http_client_includes_custom_headers(self, memory_storage: MemoryTokenStorage) -> None:
        """Test that http_client includes headers from config."""
        config = AuthProviderConfig(
            client_id="test",
            authorize_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
            redirect_uri="http://localhost/callback",
            headers={"Host": "idp.corp.local", "X-Custom": "value"},
        )
        provider = OAuth2Provider("test", config, memory_storage)

        # Access http_client to trigger creation
        client = provider.http_client

        # Verify headers are set on the client
        assert client.headers["Host"] == "idp.corp.local"
        assert client.headers["X-Custom"] == "value"

    def test_http_client_no_headers_when_empty(self, memory_storage: MemoryTokenStorage) -> None:
        """Test that http_client works with empty headers."""
        config = AuthProviderConfig(
            client_id="test",
            authorize_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
            redirect_uri="http://localhost/callback",
            headers={},
        )
        provider = OAuth2Provider("test", config, memory_storage)

        # Should not raise
        client = provider.http_client
        assert client is not None

    def test_custom_headers_sent_with_token_exchange(self, memory_storage: MemoryTokenStorage) -> None:
        """Test that custom headers are sent during token exchange."""
        config = AuthProviderConfig(
            client_id="test",
            authorize_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
            redirect_uri="http://localhost/callback",
            headers={"Host": "idp.corp.local"},
        )
        provider = OAuth2Provider("test", config, memory_storage)
        provider._pending_state = "test-state"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "token",
            "token_type": "Bearer",
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(provider.http_client, "post", return_value=mock_response) as mock_post:
            provider.exchange_code(code="code", state="test-state")

        # Verify the call was made (headers are set at client level, not call level)
        mock_post.assert_called_once()

    def test_custom_headers_merged_with_request_headers(self, memory_storage: MemoryTokenStorage) -> None:
        """Test that custom headers are merged with request-specific headers."""
        config = AuthProviderConfig(
            client_id="test",
            authorize_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
            userinfo_url="https://auth.example.com/userinfo",
            redirect_uri="http://localhost/callback",
            headers={"Host": "idp.corp.local", "X-Tenant": "corp"},
        )
        provider = OAuth2Provider("test", config, memory_storage)
        token = Token(access_token="test-token", token_type="Bearer")
        provider.save_token(token)

        mock_response = MagicMock()
        mock_response.json.return_value = {"sub": "user123"}
        mock_response.raise_for_status = MagicMock()

        with patch.object(provider.http_client, "get", return_value=mock_response) as mock_get:
            provider.get_userinfo()

        # Verify Authorization header is passed in the call
        call_kwargs = mock_get.call_args.kwargs
        assert "Authorization" in call_kwargs["headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Test TRACE logging hooks
# ─────────────────────────────────────────────────────────────────────────────


class TestTraceLoggingHooks:
    """Tests for tracer on_request and on_response TRACE logging."""

    def test_on_request_with_body_redacts_secrets(
        self,
        oauth2_provider: OAuth2Provider,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test on_request redacts sensitive data in body."""
        import logging

        from kstlib.auth.providers.oauth2 import TRACE_LEVEL

        # Enable TRACE level
        logger = logging.getLogger("kstlib.auth.providers.oauth2")
        original_level = logger.level
        logger.setLevel(TRACE_LEVEL)

        try:
            # Create mock request with sensitive body
            mock_request = MagicMock(spec=httpx.Request)
            mock_request.method = "POST"
            mock_request.url = "https://auth.example.com/token"
            mock_request.content = b"client_secret=supersecret&code=authcode123&grant_type=authorization_code"
            mock_request.headers = {"Content-Type": "application/x-www-form-urlencoded"}

            with caplog.at_level(TRACE_LEVEL, logger="kstlib.auth.providers.oauth2"):
                oauth2_provider.tracer.on_request(mock_request)

            # Check that secrets were redacted
            assert "supersecret" not in caplog.text
            assert "authcode123" not in caplog.text
            assert "REDACTED" in caplog.text
        finally:
            logger.setLevel(original_level)

    def test_on_request_with_binary_body(
        self,
        oauth2_provider: OAuth2Provider,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test on_request handles binary/unparseable body."""
        import logging

        from kstlib.auth.providers.oauth2 import TRACE_LEVEL

        logger = logging.getLogger("kstlib.auth.providers.oauth2")
        original_level = logger.level
        logger.setLevel(TRACE_LEVEL)

        try:
            mock_request = MagicMock(spec=httpx.Request)
            mock_request.method = "POST"
            mock_request.url = "https://auth.example.com/token"
            # Use invalid UTF-8 sequence that will fail to decode
            mock_request.content = b"\xff\xfe invalid utf-8 \x80\x81"
            mock_request.headers = {}

            with caplog.at_level(TRACE_LEVEL, logger="kstlib.auth.providers.oauth2"):
                oauth2_provider.tracer.on_request(mock_request)

            assert "binary or unparseable" in caplog.text
        finally:
            logger.setLevel(original_level)

    def test_on_request_without_body(
        self,
        oauth2_provider: OAuth2Provider,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test on_request handles request without body."""
        import logging

        from kstlib.auth.providers.oauth2 import TRACE_LEVEL

        logger = logging.getLogger("kstlib.auth.providers.oauth2")
        original_level = logger.level
        logger.setLevel(TRACE_LEVEL)

        try:
            mock_request = MagicMock(spec=httpx.Request)
            mock_request.method = "GET"
            mock_request.url = "https://auth.example.com/userinfo"
            mock_request.content = None
            mock_request.headers = {"Authorization": "Bearer token123"}

            with caplog.at_level(TRACE_LEVEL, logger="kstlib.auth.providers.oauth2"):
                oauth2_provider.tracer.on_request(mock_request)

            # Authorization header should NOT be logged
            assert "token123" not in caplog.text
            assert "[HTTP]" in caplog.text
        finally:
            logger.setLevel(original_level)

    def test_on_request_skipped_when_trace_disabled(
        self,
        oauth2_provider: OAuth2Provider,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test on_request does nothing when TRACE not enabled."""
        import logging

        # Ensure TRACE is NOT enabled
        logger = logging.getLogger("kstlib.auth.providers.oauth2")
        logger.setLevel(logging.INFO)

        mock_request = MagicMock(spec=httpx.Request)
        mock_request.content = b"secret=value"

        with caplog.at_level(logging.DEBUG, logger="kstlib.auth.providers.oauth2"):
            oauth2_provider.tracer.on_request(mock_request)

        # Nothing should be logged
        assert "[HTTP]" not in caplog.text

    def test_on_response_logs_json_body(
        self,
        oauth2_provider: OAuth2Provider,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test on_response logs and pretty-prints JSON body."""
        import logging

        from kstlib.auth.providers.oauth2 import TRACE_LEVEL

        logger = logging.getLogger("kstlib.auth.providers.oauth2")
        original_level = logger.level
        logger.setLevel(TRACE_LEVEL)

        try:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.text = '{"access_token":"token123","token_type":"Bearer"}'
            mock_response.read = MagicMock()
            mock_response.request = MagicMock()
            mock_response.request.method = "POST"
            mock_response.request.url = "https://auth.example.com/token"

            with caplog.at_level(TRACE_LEVEL, logger="kstlib.auth.providers.oauth2"):
                oauth2_provider.tracer.on_response(mock_response)

            assert "[HTTP]" in caplog.text
            assert "status=200" in caplog.text
        finally:
            logger.setLevel(original_level)

    def test_on_response_truncates_long_body(
        self,
        oauth2_provider: OAuth2Provider,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test on_response truncates very long response body."""
        import logging

        from kstlib.auth.providers.oauth2 import TRACE_LEVEL

        logger = logging.getLogger("kstlib.auth.providers.oauth2")
        original_level = logger.level
        logger.setLevel(TRACE_LEVEL)

        try:
            # Create a response with very long body
            long_body = "x" * 20000
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.text = long_body
            mock_response.read = MagicMock()
            mock_response.request = MagicMock()
            mock_response.request.method = "GET"
            mock_response.request.url = "https://auth.example.com/data"

            with caplog.at_level(TRACE_LEVEL, logger="kstlib.auth.providers.oauth2"):
                oauth2_provider.tracer.on_response(mock_response)

            assert "truncated" in caplog.text
        finally:
            logger.setLevel(original_level)

    def test_on_response_handles_read_error(
        self,
        oauth2_provider: OAuth2Provider,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test on_response handles error when reading body."""
        import logging

        from kstlib.auth.providers.oauth2 import TRACE_LEVEL

        logger = logging.getLogger("kstlib.auth.providers.oauth2")
        original_level = logger.level
        logger.setLevel(TRACE_LEVEL)

        try:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.read = MagicMock(side_effect=Exception("Read failed"))
            mock_response.request = MagicMock()
            mock_response.request.method = "POST"
            mock_response.request.url = "https://auth.example.com/token"

            with caplog.at_level(TRACE_LEVEL, logger="kstlib.auth.providers.oauth2"):
                oauth2_provider.tracer.on_response(mock_response)

            assert "unable to read body" in caplog.text
        finally:
            logger.setLevel(original_level)

    def test_on_response_skipped_when_trace_disabled(
        self,
        oauth2_provider: OAuth2Provider,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test on_response does nothing when TRACE not enabled."""
        import logging

        logger = logging.getLogger("kstlib.auth.providers.oauth2")
        logger.setLevel(logging.INFO)

        mock_response = MagicMock(spec=httpx.Response)

        with caplog.at_level(logging.DEBUG, logger="kstlib.auth.providers.oauth2"):
            oauth2_provider.tracer.on_response(mock_response)

        assert "[HTTP]" not in caplog.text


class TestGetTraceConfig:
    """Tests for _get_trace_config()."""

    def test_get_trace_config_from_kstlib_config(
        self,
        oauth2_provider: OAuth2Provider,
    ) -> None:
        """Test _get_trace_config reads from kstlib config."""
        mock_config = MagicMock()
        mock_config.auth.trace.pretty = False
        mock_config.auth.trace.max_body_length = 5000

        with patch("kstlib.config.load_config", return_value=mock_config):
            pretty, max_body = oauth2_provider._get_trace_config()

        assert pretty is False
        assert max_body == 5000

    def test_get_trace_config_enforces_hard_limit(
        self,
        oauth2_provider: OAuth2Provider,
    ) -> None:
        """Test _get_trace_config enforces hard limit on max_body."""
        from kstlib.auth.providers.oauth2 import _TRACE_MAX_BODY_HARD_LIMIT

        mock_config = MagicMock()
        mock_config.auth.trace.pretty = True
        mock_config.auth.trace.max_body_length = 999999999  # Way over limit

        with patch("kstlib.config.load_config", return_value=mock_config):
            _, max_body = oauth2_provider._get_trace_config()

        assert max_body <= _TRACE_MAX_BODY_HARD_LIMIT

    def test_get_trace_config_fallback_on_error(
        self,
        oauth2_provider: OAuth2Provider,
    ) -> None:
        """Test _get_trace_config returns defaults on error."""
        from kstlib.auth.providers.oauth2 import (
            _TRACE_MAX_BODY_DEFAULT,
            _TRACE_PRETTY_DEFAULT,
        )

        with patch("kstlib.config.load_config", side_effect=Exception("Config error")):
            pretty, max_body = oauth2_provider._get_trace_config()

        assert pretty == _TRACE_PRETTY_DEFAULT
        assert max_body == _TRACE_MAX_BODY_DEFAULT

    def test_get_trace_config_no_trace_section(
        self,
        oauth2_provider: OAuth2Provider,
    ) -> None:
        """Test _get_trace_config handles missing trace section."""
        from kstlib.auth.providers.oauth2 import (
            _TRACE_MAX_BODY_DEFAULT,
            _TRACE_PRETTY_DEFAULT,
        )

        mock_config = MagicMock()
        mock_config.auth.trace = None  # No trace section

        with patch("kstlib.config.load_config", return_value=mock_config):
            pretty, max_body = oauth2_provider._get_trace_config()

        assert pretty == _TRACE_PRETTY_DEFAULT
        assert max_body == _TRACE_MAX_BODY_DEFAULT


class TestGetExtraSensitiveKeys:
    """Tests for _get_extra_sensitive_keys() config resolution."""

    def test_absent_returns_empty(
        self,
        oauth2_provider: OAuth2Provider,
    ) -> None:
        """Test missing extra_sensitive_keys resolves to an empty set (floor only)."""
        mock_config = MagicMock()
        mock_config.auth.trace.extra_sensitive_keys = None

        with patch("kstlib.config.load_config", return_value=mock_config):
            keys = oauth2_provider._get_extra_sensitive_keys()

        assert keys == frozenset()

    def test_valid_list_returns_frozenset(
        self,
        oauth2_provider: OAuth2Provider,
    ) -> None:
        """Test a valid list of strings resolves to a frozenset."""
        mock_config = MagicMock()
        mock_config.auth.trace.extra_sensitive_keys = ["x_custom", "y_custom", "*token*"]

        with patch("kstlib.config.load_config", return_value=mock_config):
            keys = oauth2_provider._get_extra_sensitive_keys()

        assert keys == frozenset({"x_custom", "y_custom", "*token*"})

    def test_invalid_type_raises_config_error(
        self,
        oauth2_provider: OAuth2Provider,
    ) -> None:
        """Test a non-list value fails fast with ConfigError."""
        from kstlib.config import ConfigError

        mock_config = MagicMock()
        mock_config.auth.trace.extra_sensitive_keys = "not_a_list"

        with patch("kstlib.config.load_config", return_value=mock_config), pytest.raises(ConfigError):
            oauth2_provider._get_extra_sensitive_keys()

    def test_invalid_element_type_raises_config_error(
        self,
        oauth2_provider: OAuth2Provider,
    ) -> None:
        """Test a list containing a non-string element fails fast with ConfigError."""
        from kstlib.config import ConfigError

        mock_config = MagicMock()
        mock_config.auth.trace.extra_sensitive_keys = ["ok", 123]

        with patch("kstlib.config.load_config", return_value=mock_config), pytest.raises(ConfigError):
            oauth2_provider._get_extra_sensitive_keys()

    def test_load_error_returns_empty(
        self,
        oauth2_provider: OAuth2Provider,
    ) -> None:
        """Test a config load failure resolves to an empty set (fail-safe, floor holds)."""
        with patch("kstlib.config.load_config", side_effect=Exception("Config error")):
            keys = oauth2_provider._get_extra_sensitive_keys()

        assert keys == frozenset()

    def test_no_trace_section_returns_empty(
        self,
        oauth2_provider: OAuth2Provider,
    ) -> None:
        """Test a missing trace section resolves to an empty set."""
        mock_config = MagicMock()
        mock_config.auth.trace = None

        with patch("kstlib.config.load_config", return_value=mock_config):
            keys = oauth2_provider._get_extra_sensitive_keys()

        assert keys == frozenset()

    def test_tracer_includes_config_extra_keys(
        self,
        oauth2_provider: OAuth2Provider,
    ) -> None:
        """Test the tracer property unions config extra keys with the immutable floor."""
        from kstlib.utils.http_trace import DEFAULT_SENSITIVE_KEYS

        mock_config = MagicMock()
        mock_config.auth.trace.pretty = True
        mock_config.auth.trace.max_body_length = 5000
        mock_config.auth.trace.extra_sensitive_keys = ["x_custom_secret"]

        with patch("kstlib.config.load_config", return_value=mock_config):
            tracer = oauth2_provider.tracer

        assert "x_custom_secret" in tracer.sensitive_keys
        assert DEFAULT_SENSITIVE_KEYS.issubset(tracer.sensitive_keys)

    def test_real_box_empty_list_returns_empty(
        self,
        oauth2_provider: OAuth2Provider,
    ) -> None:
        """Test a real Box (BoxList) with an empty list resolves to an empty set."""
        from box import Box

        cfg = Box({"auth": {"trace": {"extra_sensitive_keys": []}}})

        with patch("kstlib.config.load_config", return_value=cfg):
            keys = oauth2_provider._get_extra_sensitive_keys()

        assert keys == frozenset()

    def test_real_box_valid_list_returns_frozenset(
        self,
        oauth2_provider: OAuth2Provider,
    ) -> None:
        """Test a real Box (BoxList) with a valid list resolves to a frozenset."""
        from box import Box

        cfg = Box({"auth": {"trace": {"extra_sensitive_keys": ["x_custom", "*token*"]}}})

        with patch("kstlib.config.load_config", return_value=cfg):
            keys = oauth2_provider._get_extra_sensitive_keys()

        assert keys == frozenset({"x_custom", "*token*"})

    def test_real_box_mapping_raises_config_error(
        self,
        oauth2_provider: OAuth2Provider,
    ) -> None:
        """Test a real Box with a mapping value fails fast with ConfigError."""
        from box import Box

        from kstlib.config import ConfigError

        cfg = Box({"auth": {"trace": {"extra_sensitive_keys": {"not": "a list"}}}})

        with patch("kstlib.config.load_config", return_value=cfg), pytest.raises(ConfigError):
            oauth2_provider._get_extra_sensitive_keys()
