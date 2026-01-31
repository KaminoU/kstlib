"""End-to-end tests for OAuth2/OIDC authentication with Keycloak.

These tests require a running Keycloak instance:
    docker compose -f infra/docker-compose.yml up -d keycloak

The tests will be skipped if Keycloak is not available.
"""

from __future__ import annotations

import time
from threading import Thread

import httpx
import pytest

from kstlib.auth import (
    AuthSession,
    OIDCProvider,
    PreflightStatus,
)

from .conftest import KEYCLOAK_URL, requires_keycloak


@requires_keycloak
class TestKeycloakDiscovery:
    """Tests for OIDC discovery with Keycloak."""

    def test_discovery_fetches_endpoints(self, keycloak_public_client_config, memory_storage):
        """Test that discovery fetches the OIDC configuration."""
        provider = OIDCProvider("keycloak", keycloak_public_client_config, memory_storage)

        discovery = provider.discover()

        assert "authorization_endpoint" in discovery
        assert "token_endpoint" in discovery
        assert "jwks_uri" in discovery
        assert discovery["issuer"] == keycloak_public_client_config.issuer

    def test_discovery_caching(self, keycloak_public_client_config, memory_storage):
        """Test that discovery document is cached."""
        provider = OIDCProvider("keycloak", keycloak_public_client_config, memory_storage)

        # First call
        doc1 = provider.discover()
        fetch_time1 = provider._discovery_fetched_at

        # Second call should use cache
        doc2 = provider.discover()
        fetch_time2 = provider._discovery_fetched_at

        assert doc1 == doc2
        assert fetch_time1 == fetch_time2

    def test_discovery_force_refresh(self, keycloak_public_client_config, memory_storage):
        """Test forced discovery refresh."""
        provider = OIDCProvider("keycloak", keycloak_public_client_config, memory_storage)

        provider.discover()
        fetch_time1 = provider._discovery_fetched_at

        time.sleep(0.1)  # Small delay

        provider.discover(force=True)
        fetch_time2 = provider._discovery_fetched_at

        assert fetch_time2 > fetch_time1


@requires_keycloak
class TestKeycloakPreflight:
    """Tests for preflight validation with Keycloak."""

    def test_preflight_public_client(self, keycloak_public_client_config, memory_storage):
        """Test preflight validation for public client."""
        provider = OIDCProvider("keycloak", keycloak_public_client_config, memory_storage)

        report = provider.preflight()

        assert report.provider_name == "keycloak"
        assert report.success is True
        assert len(report.failed_steps) == 0

        # Check specific steps
        step_names = [r.step for r in report.results]
        assert "discovery" in step_names
        assert "jwks" in step_names

    def test_preflight_confidential_client(self, keycloak_confidential_client_config, memory_storage):
        """Test preflight validation for confidential client."""
        provider = OIDCProvider("keycloak", keycloak_confidential_client_config, memory_storage)

        report = provider.preflight()

        assert report.success is True

    def test_preflight_reports_duration(self, keycloak_public_client_config, memory_storage):
        """Test that preflight reports include duration."""
        provider = OIDCProvider("keycloak", keycloak_public_client_config, memory_storage)

        report = provider.preflight()

        assert report.total_duration_ms > 0
        for result in report.results:
            if result.status != PreflightStatus.SKIPPED:
                assert result.duration_ms is not None
                assert result.duration_ms >= 0


@requires_keycloak
class TestKeycloakAuthorizationURL:
    """Tests for authorization URL generation with Keycloak."""

    def test_authorization_url_generation(self, keycloak_public_client_config, memory_storage):
        """Test authorization URL is generated correctly."""
        provider = OIDCProvider("keycloak", keycloak_public_client_config, memory_storage)

        url, state = provider.get_authorization_url()

        assert KEYCLOAK_URL in url
        assert "response_type=code" in url
        assert f"client_id={keycloak_public_client_config.client_id}" in url
        assert "state=" in url
        assert len(state) > 20  # State should be sufficiently random

    def test_authorization_url_includes_pkce(self, keycloak_public_client_config, memory_storage):
        """Test PKCE parameters are included in authorization URL."""
        keycloak_public_client_config.pkce = True
        provider = OIDCProvider("keycloak", keycloak_public_client_config, memory_storage)

        url, _ = provider.get_authorization_url()

        assert "code_challenge=" in url
        assert "code_challenge_method=S256" in url

    def test_authorization_url_scopes(self, keycloak_public_client_config, memory_storage):
        """Test scopes are included in authorization URL."""
        provider = OIDCProvider("keycloak", keycloak_public_client_config, memory_storage)

        url, _ = provider.get_authorization_url()

        # Scopes are URL encoded
        assert "scope=" in url
        assert "openid" in url


@requires_keycloak
class TestKeycloakDirectGrant:
    """Tests using Keycloak's Direct Access Grant (password flow).

    Note: This flow is enabled for the confidential test client for testing
    purposes. In production, use the Authorization Code flow.
    """

    def test_direct_grant_token_exchange(self, keycloak_issuer, keycloak_test_user, memory_storage):
        """Test obtaining token via direct grant (resource owner password)."""
        # This test uses direct grant to avoid browser interaction
        # In production, use authorization code flow

        token_url = f"{keycloak_issuer}/protocol/openid-connect/token"

        response = httpx.post(
            token_url,
            data={
                "grant_type": "password",
                "client_id": "kstlib-test-confidential",
                "client_secret": "kstlib-test-secret",
                "username": keycloak_test_user["username"],
                "password": keycloak_test_user["password"],
                "scope": "openid profile email",
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert "access_token" in data
        assert "refresh_token" in data
        assert "id_token" in data
        assert data["token_type"] == "Bearer"

    def test_token_refresh(self, keycloak_issuer, keycloak_test_user, memory_storage):
        """Test refreshing a token."""
        token_url = f"{keycloak_issuer}/protocol/openid-connect/token"

        # Get initial token
        response = httpx.post(
            token_url,
            data={
                "grant_type": "password",
                "client_id": "kstlib-test-confidential",
                "client_secret": "kstlib-test-secret",
                "username": keycloak_test_user["username"],
                "password": keycloak_test_user["password"],
                "scope": "openid",
            },
        )
        initial_token = response.json()

        # Refresh the token
        refresh_response = httpx.post(
            token_url,
            data={
                "grant_type": "refresh_token",
                "client_id": "kstlib-test-confidential",
                "client_secret": "kstlib-test-secret",
                "refresh_token": initial_token["refresh_token"],
            },
        )

        assert refresh_response.status_code == 200
        refreshed = refresh_response.json()
        assert "access_token" in refreshed
        assert refreshed["access_token"] != initial_token["access_token"]


@requires_keycloak
class TestKeycloakUserInfo:
    """Tests for UserInfo endpoint with Keycloak."""

    def test_userinfo_endpoint(self, keycloak_issuer, keycloak_test_user):
        """Test fetching user info with a valid token."""
        token_url = f"{keycloak_issuer}/protocol/openid-connect/token"
        userinfo_url = f"{keycloak_issuer}/protocol/openid-connect/userinfo"

        # Get token
        token_response = httpx.post(
            token_url,
            data={
                "grant_type": "password",
                "client_id": "kstlib-test-confidential",
                "client_secret": "kstlib-test-secret",
                "username": keycloak_test_user["username"],
                "password": keycloak_test_user["password"],
                "scope": "openid profile email",
            },
        )
        token = token_response.json()["access_token"]

        # Fetch user info
        userinfo_response = httpx.get(
            userinfo_url,
            headers={"Authorization": f"Bearer {token}"},
        )

        assert userinfo_response.status_code == 200
        userinfo = userinfo_response.json()

        assert userinfo["preferred_username"] == keycloak_test_user["username"]
        assert userinfo["email"] == keycloak_test_user["email"]


@requires_keycloak
class TestCallbackServer:
    """Tests for the local callback server."""

    def test_callback_server_starts(self, callback_server):
        """Test that callback server starts successfully."""
        callback_server.start()

        assert callback_server._server is not None
        assert callback_server._thread is not None
        assert callback_server._thread.is_alive()

        callback_server.stop()

    def test_callback_server_redirect_uri(self, callback_server):
        """Test redirect URI generation."""
        assert callback_server.redirect_uri == f"http://127.0.0.1:{callback_server.port}/callback"

    def test_callback_server_state_generation(self, callback_server):
        """Test state parameter generation."""
        state = callback_server.generate_state()

        assert len(state) > 20
        assert callback_server._state == state

    def test_callback_server_receives_code(self, callback_server):
        """Test that callback server receives authorization code."""
        callback_server.start()

        # Simulate callback from IdP
        def send_callback():
            time.sleep(0.1)  # Wait for server to be ready
            httpx.get(
                f"{callback_server.redirect_uri}?code=test_code&state=test_state",
                follow_redirects=False,
            )

        thread = Thread(target=send_callback)
        thread.start()

        result = callback_server.wait_for_callback(timeout=5)
        thread.join()

        assert result.success
        assert result.code == "test_code"
        assert result.state == "test_state"

        callback_server.stop()

    def test_callback_server_handles_error(self, callback_server):
        """Test that callback server handles OAuth error response."""
        callback_server.start()

        def send_error_callback():
            time.sleep(0.1)
            httpx.get(
                f"{callback_server.redirect_uri}?error=access_denied&error_description=User+denied+access",
                follow_redirects=False,
            )

        thread = Thread(target=send_error_callback)
        thread.start()

        from kstlib.auth.errors import AuthorizationError

        with pytest.raises(AuthorizationError) as exc_info:
            callback_server.wait_for_callback(timeout=5)

        thread.join()
        assert "access_denied" in str(exc_info.value) or "denied" in str(exc_info.value)

        callback_server.stop()


@requires_keycloak
class TestAuthSession:
    """Tests for AuthSession wrapper with Keycloak."""

    def test_auth_session_with_token(
        self, keycloak_issuer, keycloak_confidential_client_config, memory_storage, keycloak_test_user
    ):
        """Test AuthSession makes authenticated requests."""
        from kstlib.auth.models import Token

        # Get a token first
        token_url = f"{keycloak_issuer}/protocol/openid-connect/token"
        response = httpx.post(
            token_url,
            data={
                "grant_type": "password",
                "client_id": "kstlib-test-confidential",
                "client_secret": "kstlib-test-secret",
                "username": keycloak_test_user["username"],
                "password": keycloak_test_user["password"],
                "scope": "openid profile email",
            },
        )
        token = Token.from_response(response.json())
        memory_storage.save("keycloak", token)

        # Create provider with stored token
        provider = OIDCProvider("keycloak", keycloak_confidential_client_config, memory_storage)

        # Use AuthSession to make request
        userinfo_url = f"{keycloak_issuer}/protocol/openid-connect/userinfo"
        with AuthSession(provider) as session:
            result = session.get(userinfo_url)

        assert result.status_code == 200
        userinfo = result.json()
        assert userinfo["preferred_username"] == keycloak_test_user["username"]
