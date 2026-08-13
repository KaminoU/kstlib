"""Unit tests for OIDCProvider."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from kstlib.auth.errors import (
    ConfigurationError,
    DiscoveryError,
    TokenExchangeError,
    TokenValidationError,
)
from kstlib.auth.models import AuthFlow, PreflightStatus, Token
from kstlib.auth.providers import AuthProviderConfig, OIDCProvider
from kstlib.logging import TRACE_LEVEL

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from kstlib.auth.token import MemoryTokenStorage

# ─────────────────────────────────────────────────────────────────────────────
# Fake IDP over httpx.MockTransport
# ─────────────────────────────────────────────────────────────────────────────


def idp_handler(
    *,
    discovery: dict[str, Any] | None = None,
    jwks: dict[str, Any] | None = None,
    token: dict[str, Any] | None = None,
    userinfo: dict[str, Any] | None = None,
    calls: list[str] | None = None,
    bodies: list[str] | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    """Build a MockTransport handler for a well behaved IDP.

    Requests are routed on their path so a scenario only declares the
    documents it needs. Anything undeclared answers 404, so an unexpected
    call surfaces as a failure instead of passing silently.

    Args:
        discovery: Document served at ``.well-known/openid-configuration``.
        jwks: Document served at the JWKS endpoint.
        token: Document served to any POST (the token endpoint).
        userinfo: Document served at the UserInfo endpoint.
        calls: Optional list collecting ``"<METHOD> <path>"`` per request.
        bodies: Optional list collecting the decoded body of each POST.

    Returns:
        Handler suitable for ``httpx.MockTransport``.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if calls is not None:
            calls.append(f"{request.method} {path}")

        if path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json=discovery) if discovery is not None else httpx.Response(404)

        # Preflight probes endpoint reachability with HEAD.
        if request.method == "HEAD":
            return httpx.Response(200)

        if request.method == "POST":
            if bodies is not None:
                bodies.append(request.content.decode())
            return httpx.Response(200, json=token) if token is not None else httpx.Response(404)

        if "jwks" in path or path.endswith("/certs"):
            return httpx.Response(200, json=jwks) if jwks is not None else httpx.Response(404)

        if "userinfo" in path:
            return httpx.Response(200, json=userinfo) if userinfo is not None else httpx.Response(404)

        return httpx.Response(404)

    return handler


def make_id_token(key: Any, *, issuer: str, audience: str, signer: Any = None, **claims: Any) -> str:
    """Sign a real RS256 ID token.

    Args:
        key: Key whose thumbprint is advertised as ``kid``.
        issuer: Value of the ``iss`` claim.
        audience: Value of the ``aud`` claim.
        signer: Key actually signing, defaults to ``key``. Passing a
            different key produces a token whose signature does not match
            the advertised JWKS.
        **claims: Extra claims overriding the defaults.

    Returns:
        Encoded JWT.
    """
    from authlib.jose import jwt

    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": issuer,
        "aud": audience,
        "sub": "user-123",
        "iat": now,
        "exp": now + 3600,
    }
    payload.update(claims)
    signed = jwt.encode({"alg": "RS256", "kid": key.thumbprint()}, payload, signer or key)
    return signed.decode() if isinstance(signed, bytes) else signed


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def signing_key() -> Any:
    """Generate one RSA key pair shared by the whole module.

    RSA generation is expensive and every test needing a real signature
    can share the same pair.
    """
    from authlib.jose import JsonWebKey

    return JsonWebKey.generate_key("RSA", 2048, is_private=True)


@pytest.fixture(scope="module")
def signing_jwks(signing_key: Any) -> dict[str, Any]:
    """Public JWKS matching signing_key."""
    return {"keys": [signing_key.as_dict(is_private=False)]}


@pytest.fixture
def offline_client() -> Generator[httpx.Client, None, None]:
    """Client whose transport refuses every request.

    Used by scenarios that must not reach the network at all: an
    unexpected call fails the test loudly instead of hitting a real host.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        msg = f"unexpected request: {request.method} {request.url}"
        raise AssertionError(msg)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        yield client


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
    offline_client: httpx.Client,
) -> OIDCProvider:
    """Create an OIDCProvider that must not touch the network."""
    return OIDCProvider("test", oidc_config, memory_storage, http_client=offline_client)


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
    """Create a mock JWKS response.

    Structurally valid but not usable for signature verification: for
    that, use the ``signing_jwks`` fixture instead.
    """
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
        """Test that an explicit revoke_url is not overwritten by discovery."""
        explicit_revoke = "https://auth.example.com/custom/revoke"
        config = AuthProviderConfig(
            client_id="test",
            issuer="https://auth.example.com",
            revoke_url=explicit_revoke,
            redirect_uri="http://localhost/callback",
        )
        discovery = {
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
            "revocation_endpoint": "https://auth.example.com/standard/revoke",
        }

        with httpx.Client(transport=httpx.MockTransport(idp_handler(discovery=discovery))) as client:
            provider = OIDCProvider("test", config, memory_storage, http_client=client)
            provider.discover()

        assert provider.config.revoke_url == explicit_revoke

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
        offline_client: httpx.Client,
    ) -> None:
        """Test auto discovery mode when only issuer is provided."""
        provider = OIDCProvider("auto", oidc_config, memory_storage, http_client=offline_client)

        # "auto" means discovery is on and no endpoint is operator-pinned
        assert provider.discovery_mode == "auto"

    def test_auto_mode_discovery_updates_endpoints(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        keycloak_discovery_doc: dict,
    ) -> None:
        """Test that auto discovery updates all endpoints from discovery doc."""
        handler = idp_handler(discovery=keycloak_discovery_doc)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("auto", oidc_config, memory_storage, http_client=client)

            # Before discovery: endpoints are unresolved (no issuer-derived guess)
            assert provider.config.token_url is None

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
        offline_client: httpx.Client,
    ) -> None:
        """Test hybrid mode when issuer + some explicit endpoints are provided."""
        provider = OIDCProvider("hybrid", hybrid_oidc_config, memory_storage, http_client=offline_client)

        # "hybrid" means discovery is on and at least one endpoint is pinned
        assert provider.discovery_mode == "hybrid"

    def test_hybrid_mode_explicit_endpoints_preserved(
        self,
        hybrid_oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        mock_discovery_doc: dict,
    ) -> None:
        """Test that explicit endpoints are NOT overwritten by discovery."""
        explicit_logout = "https://auth.example.com/custom/logout"
        assert hybrid_oidc_config.end_session_endpoint == explicit_logout

        # Add end_session_endpoint to discovery doc (different URL)
        mock_discovery_doc["end_session_endpoint"] = "https://auth.example.com/standard/logout"
        handler = idp_handler(discovery=mock_discovery_doc)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("hybrid", hybrid_oidc_config, memory_storage, http_client=client)
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
        handler = idp_handler(discovery=mock_discovery_doc)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("hybrid", config, memory_storage, http_client=client)
            assert provider.discovery_mode == "hybrid"

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
        offline_client: httpx.Client,
    ) -> None:
        """Test manual mode when no issuer is provided."""
        provider = OIDCProvider("manual", manual_oidc_config, memory_storage, http_client=offline_client)

        # "manual" means discovery is off: every endpoint is operator-pinned
        assert provider.discovery_mode == "manual"
        assert provider.config.authorize_url == "https://legacy-idp.local/auth"
        assert provider.config.token_url == "https://legacy-idp.local/token"
        assert provider.config.jwks_uri == "https://legacy-idp.local/certs"

    def test_manual_mode_discover_returns_empty_dict(
        self,
        manual_oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        offline_client: httpx.Client,
    ) -> None:
        """Test that discover() returns empty dict in manual mode (no network call)."""
        provider = OIDCProvider("manual", manual_oidc_config, memory_storage, http_client=offline_client)

        # offline_client raises on any request, so reaching the network fails here
        result = provider.discover()

        assert result == {}

    def test_manual_mode_endpoints_unchanged_after_discover(
        self,
        manual_oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        offline_client: httpx.Client,
    ) -> None:
        """Test that endpoints remain unchanged after discover() in manual mode."""
        provider = OIDCProvider("manual", manual_oidc_config, memory_storage, http_client=offline_client)

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
        calls: list[str] = []
        handler = idp_handler(
            token={"access_token": "new-token", "token_type": "Bearer", "expires_in": 300},
            calls=calls,
        )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("manual", manual_oidc_config, memory_storage, http_client=client)

            # Create expired token
            token = Token(
                access_token="expired-token",
                token_type="Bearer",
                expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
                refresh_token="refresh-token",
            )
            provider.save_token(token)

            new_token = provider.refresh()

        # Should NOT call discovery
        assert not any(".well-known" in call for call in calls), calls
        # Should use explicit token_url
        assert calls == ["POST /token"]
        assert new_token.access_token == "new-token"


# ─────────────────────────────────────────────────────────────────────────────
# Test config reuse across providers
# ─────────────────────────────────────────────────────────────────────────────


class TestConfigReuseAcrossProviders:
    """Reusing one AuthProviderConfig object across successive providers.

    Values kstlib itself writes into the caller's config (discovered
    endpoints) must never be reclassified as operator-explicit endpoints
    by a later construction: "explicit wins" only protects operator input.
    """

    def test_discovery_recovers_after_transient_failure_on_reused_config(
        self,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """A failed first discovery must not freeze endpoints on config reuse."""
        config = AuthProviderConfig(
            client_id="reuse-client",
            issuer="https://auth.example.com",
            redirect_uri="http://127.0.0.1:8400/callback",
        )
        discovery_doc = {
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/protocol/openid-connect/auth",
            "token_endpoint": "https://auth.example.com/protocol/openid-connect/token",
            "jwks_uri": "https://auth.example.com/protocol/openid-connect/certs",
        }
        calls = {"discovery": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/.well-known/openid-configuration"):
                calls["discovery"] += 1
                if calls["discovery"] == 1:
                    raise httpx.ConnectError("Connection refused", request=request)
                return httpx.Response(200, json=discovery_doc)
            return httpx.Response(404)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            p1 = OIDCProvider("reuse", config, memory_storage, http_client=client)
            with pytest.raises(DiscoveryError):
                p1.discover()

            p2 = OIDCProvider("reuse", config, memory_storage, http_client=client)
            p2.discover()

            assert config.authorize_url == discovery_doc["authorization_endpoint"]
            assert config.token_url == discovery_doc["token_endpoint"]

            url, _state = p2.get_authorization_url()

        assert url.startswith(discovery_doc["authorization_endpoint"] + "?")

    def test_rotated_endpoint_wins_on_reused_config(
        self,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """A previously discovered endpoint must not block a rotated one."""
        config = AuthProviderConfig(
            client_id="reuse-client",
            issuer="https://auth.example.com",
            redirect_uri="http://127.0.0.1:8400/callback",
        )
        doc_v1 = {
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/v1/authorize",
            "token_endpoint": "https://auth.example.com/v1/token",
        }
        doc_v2 = {
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/v2/authorize",
            "token_endpoint": "https://auth.example.com/v2/token",
        }
        docs = iter([doc_v1, doc_v2])

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=next(docs))

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            p1 = OIDCProvider("reuse", config, memory_storage, http_client=client)
            p1.discover()
            assert config.authorize_url == doc_v1["authorization_endpoint"]

            p2 = OIDCProvider("reuse", config, memory_storage, http_client=client)
            p2.discover()

        assert config.authorize_url == doc_v2["authorization_endpoint"]
        assert config.token_url == doc_v2["token_endpoint"]

    def test_authorization_url_never_derived_from_issuer(
        self,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Without a discovered or explicit endpoint, emission fails loudly.

        A discovery document without authorization_endpoint must produce an
        explicit error, never a well-formed but wrong issuer-derived URL.
        """
        config = AuthProviderConfig(
            client_id="incomplete-client",
            issuer="https://auth.example.com",
            redirect_uri="http://127.0.0.1:8400/callback",
        )
        incomplete_doc = {
            "issuer": "https://auth.example.com",
            "token_endpoint": "https://auth.example.com/protocol/openid-connect/token",
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=incomplete_doc)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("incomplete", config, memory_storage, http_client=client)

            with pytest.raises(ConfigurationError, match="authorization endpoint"):
                provider.get_authorization_url()

    def test_operator_explicit_endpoint_still_wins_on_reused_config(
        self,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Operator-explicit endpoints keep winning over discovery on reuse."""
        explicit_authorize = "https://idp.corp.example/custom/authorize"
        config = AuthProviderConfig(
            client_id="hybrid-client",
            issuer="https://auth.example.com",
            authorize_url=explicit_authorize,
            redirect_uri="http://127.0.0.1:8400/callback",
        )
        discovery_doc = {
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/protocol/openid-connect/auth",
            "token_endpoint": "https://auth.example.com/protocol/openid-connect/token",
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=discovery_doc)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            p1 = OIDCProvider("hybrid", config, memory_storage, http_client=client)
            p1.discover()
            assert config.authorize_url == explicit_authorize

            p2 = OIDCProvider("hybrid", config, memory_storage, http_client=client)
            p2.discover()

            assert config.authorize_url == explicit_authorize
            assert p2.discovery_mode == "hybrid"


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
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        mock_discovery_doc: dict,
    ) -> None:
        """Test that discover() fetches the discovery document."""
        handler = idp_handler(discovery=mock_discovery_doc)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)
            doc = provider.discover()

        assert doc["issuer"] == "https://auth.example.com"
        assert "authorization_endpoint" in doc

    def test_discover_caches_result(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        mock_discovery_doc: dict,
    ) -> None:
        """Test that discovery document is cached."""
        calls: list[str] = []
        handler = idp_handler(discovery=mock_discovery_doc, calls=calls)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)
            provider.discover()
            provider.discover()

        # Should only fetch once due to caching
        assert calls == ["GET /.well-known/openid-configuration"]

    def test_discover_force_refresh(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        mock_discovery_doc: dict,
    ) -> None:
        """Test forced discovery refresh."""
        calls: list[str] = []
        handler = idp_handler(discovery=mock_discovery_doc, calls=calls)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)
            provider.discover()
            provider.discover(force=True)

        assert len(calls) == 2

    def test_discover_http_error(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Test discovery handles HTTP errors."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="Not Found")

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)

            with pytest.raises(DiscoveryError):
                provider.discover()

    def test_discover_stores_discovered_issuer(
        self,
        memory_storage: MemoryTokenStorage,
        signing_key: Any,
        signing_jwks: dict[str, Any],
    ) -> None:
        """Test that discover() stores the discovered issuer for token validation.

        Proven by use: an ID token carrying the DISCOVERED issuer is
        accepted, which can only happen if discovery overrode the
        configured one.
        """
        config = AuthProviderConfig(
            client_id="test-client",
            issuer="https://sso.enterprise.local",
            scopes=["openid"],
            redirect_uri="http://127.0.0.1:8400/callback",
        )
        discovered_issuer = "https://sso.enterprise.local:443/oauth2"
        discovery_doc = {
            "issuer": discovered_issuer,
            "authorization_endpoint": f"{discovered_issuer}/authorize",
            "token_endpoint": f"{discovered_issuer}/token",
            "jwks_uri": f"{discovered_issuer}/certs",
        }
        id_token = make_id_token(signing_key, issuer=discovered_issuer, audience="test-client")
        handler = idp_handler(
            discovery=discovery_doc,
            jwks=signing_jwks,
            token={"access_token": "at", "token_type": "Bearer", "id_token": id_token},
        )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("enterprise", config, memory_storage, http_client=client)
            token = provider.exchange_code_stateless(code="auth-code", code_verifier="v")

        assert token.access_token == "at"

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
        # Configure with base issuer (what user would naturally configure)
        config = AuthProviderConfig(
            client_id="test-client",
            issuer="https://sso.enterprise.local",  # Configured by user
            scopes=["openid"],
            redirect_uri="http://127.0.0.1:8400/callback",
        )

        # Discovery returns different issuer (common with Oracle OAM, etc.)
        discovery_doc = {
            "issuer": "https://sso.enterprise.local:443/oauth2",  # Different!
            "authorization_endpoint": "https://sso.enterprise.local:443/oauth2/authorize",
            "token_endpoint": "https://sso.enterprise.local:443/oauth2/token",
            "jwks_uri": "https://sso.enterprise.local:443/oauth2/certs",
        }
        handler = idp_handler(discovery=discovery_doc)

        with (
            httpx.Client(transport=httpx.MockTransport(handler)) as client,
            caplog.at_level(logging.DEBUG),
        ):
            provider = OIDCProvider("enterprise", config, memory_storage, http_client=client)
            provider.discover()

        # Log should mention the mismatch
        assert "discovered issuer differs from configured" in caplog.text


# ─────────────────────────────────────────────────────────────────────────────
# Test discovery error contract (provider-responded vs transport)
# ─────────────────────────────────────────────────────────────────────────────


class TestDiscoveryErrorContract:
    """Locks the provider-responded vs transport discriminant on discover().

    Contract: ``status_code`` is the HTTP status answered by the provider to
    the discovery request, ``None`` when no HTTP response was received.
    """

    def test_discover_provider_error_sets_status_code(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Provider answering 500 to discovery sets status_code=500."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Internal Server Error")

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)

            with pytest.raises(DiscoveryError) as exc_info:
                provider.discover()

        assert exc_info.value.status_code == 500
        assert exc_info.value.reason == "HTTP 500"

    def test_discover_transport_error_status_code_none(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Unreachable provider at discovery keeps status_code None."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused", request=request)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)

            with pytest.raises(DiscoveryError) as exc_info:
                provider.discover()

        assert exc_info.value.status_code is None


# ─────────────────────────────────────────────────────────────────────────────
# Test PKCE
# ─────────────────────────────────────────────────────────────────────────────


def s256_challenge(verifier: str) -> str:
    """Return the S256 code_challenge for a PKCE code_verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class TestPKCE:
    """Tests for PKCE functionality."""

    def test_get_authorization_url_includes_pkce(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        mock_discovery_doc: dict,
    ) -> None:
        """Test that authorization URL includes PKCE parameters."""
        handler = idp_handler(discovery=mock_discovery_doc)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)
            url, _state = provider.get_authorization_url()

        assert "code_challenge=" in url
        assert "code_challenge_method=S256" in url

    def test_pkce_verifier_stored(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        mock_discovery_doc: dict,
    ) -> None:
        """Test that the verifier kept for the exchange matches the published challenge.

        The verifier is only useful if it is the pre-image of the
        challenge the IDP received, so the binding is what gets asserted
        rather than the raw stored value.
        """
        bodies: list[str] = []
        handler = idp_handler(
            discovery=mock_discovery_doc,
            token={"access_token": "at", "token_type": "Bearer"},
            bodies=bodies,
        )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)
            url, state = provider.get_authorization_url()
            provider.exchange_code(code="auth-code", state=state)

        published_challenge = parse_qs(urlparse(url).query)["code_challenge"][0]
        sent_verifier = parse_qs(bodies[0])["code_verifier"][0]

        assert s256_challenge(sent_verifier) == published_challenge
        assert len(sent_verifier) >= 43


# ─────────────────────────────────────────────────────────────────────────────
# Test exchange_code with ID token
# ─────────────────────────────────────────────────────────────────────────────


class TestExchangeCodeOIDC:
    """Tests for OIDC-specific exchange_code behavior."""

    def test_exchange_code_includes_verifier(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        mock_discovery_doc: dict,
    ) -> None:
        """Test that exchange_code includes PKCE verifier."""
        bodies: list[str] = []
        handler = idp_handler(
            discovery=mock_discovery_doc,
            token={"access_token": "access-token", "token_type": "Bearer"},
            bodies=bodies,
        )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)
            _url, state = provider.get_authorization_url()
            provider.exchange_code(code="auth-code", state=state)

        assert "code_verifier" in parse_qs(bodies[0])

    def test_exchange_code_pkce_missing_verifier_error(
        self,
        oidc_provider: OIDCProvider,
    ) -> None:
        """Test that exchange_code fails if PKCE enabled but no verifier.

        No authorization URL was requested, so no verifier was armed: the
        guard fires before any network call.
        """
        with pytest.raises(TokenExchangeError, match="PKCE is enabled but no code_verifier"):
            oidc_provider.exchange_code(code="auth-code", state="test-state")

    def test_pkce_missing_guard_error_code(self, oidc_provider: OIDCProvider) -> None:
        """Local PKCE guard rejects with error_code 'pkce_missing' before any request."""
        with pytest.raises(TokenExchangeError) as exc_info:
            oidc_provider.exchange_code(code="auth-code", state="any-state")

        assert exc_info.value.error_code == "pkce_missing"

    def test_pkce_missing_guard_status_code_none_not_retryable(self, oidc_provider: OIDCProvider) -> None:
        """Local PKCE guard has status_code None (no provider contact) and is not retryable."""
        with pytest.raises(TokenExchangeError) as exc_info:
            oidc_provider.exchange_code(code="auth-code", state="any-state")

        assert exc_info.value.status_code is None
        assert exc_info.value.retryable is False

    def test_stateless_pkce_missing_guard(self, oidc_provider: OIDCProvider) -> None:
        """Stateless exchange enforces the PKCE guard on the explicit argument only."""
        with pytest.raises(TokenExchangeError) as exc_info:
            oidc_provider.exchange_code_stateless(code="auth-code")

        assert exc_info.value.error_code == "pkce_missing"
        assert exc_info.value.status_code is None
        assert exc_info.value.retryable is False

    def test_stateless_success_with_discovery_routing(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        mock_discovery_doc: dict,
    ) -> None:
        """Stateless exchange runs discovery, posts the verifier, returns the token unsaved."""
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/.well-known/openid-configuration"):
                return httpx.Response(200, json=mock_discovery_doc)
            captured["body"] = request.content.decode()
            return httpx.Response(
                200,
                json={"access_token": "stateless-at", "token_type": "Bearer"},
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)
            token = provider.exchange_code_stateless(code="auth-code", code_verifier="verifier-123")

        assert token.access_token == "stateless-at"
        assert "code_verifier=verifier-123" in captured["body"]
        assert memory_storage.load("test") is None

    def test_stateless_validates_id_token_when_present(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        mock_discovery_doc: dict,
        signing_key: Any,
        signing_jwks: dict[str, Any],
    ) -> None:
        """Stateless exchange still runs ID token validation when an id_token is returned."""
        calls: list[str] = []
        id_token = make_id_token(signing_key, issuer="https://auth.example.com", audience="test-oidc-client")
        handler = idp_handler(
            discovery=mock_discovery_doc,
            jwks=signing_jwks,
            token={"access_token": "at", "token_type": "Bearer", "id_token": id_token},
            calls=calls,
        )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)
            token = provider.exchange_code_stateless(code="auth-code", code_verifier="v")

        # Validation ran for real: the JWKS was fetched to check the signature
        assert token.id_token == id_token
        assert "GET /.well-known/jwks.json" in calls, calls

    def test_exchange_code_id_token_validation_failure_raises(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        mock_discovery_doc: dict,
        signing_key: Any,
        signing_jwks: dict[str, Any],
    ) -> None:
        """Test that ID token validation failure raises (mandatory for OIDC).

        The ID token is signed by a key the advertised JWKS does not
        contain, so the signature check fails for real.
        """
        from authlib.jose import JsonWebKey

        rogue_key = JsonWebKey.generate_key("RSA", 2048, is_private=True)
        forged = make_id_token(
            signing_key,
            issuer="https://auth.example.com",
            audience="test-oidc-client",
            signer=rogue_key,
        )
        handler = idp_handler(
            discovery=mock_discovery_doc,
            jwks=signing_jwks,
            token={"access_token": "access-token", "token_type": "Bearer", "id_token": forged},
        )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)
            _url, state = provider.get_authorization_url()

            with pytest.raises(TokenValidationError):
                provider.exchange_code(code="auth-code", state=state)


# ─────────────────────────────────────────────────────────────────────────────
# Test validate_id_token
# ─────────────────────────────────────────────────────────────────────────────


class TestValidateIdToken:
    """Tests for ID token validation."""

    def test_validate_id_token_invalid_format(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        mock_discovery_doc: dict,
        signing_jwks: dict[str, Any],
    ) -> None:
        """Test validation with invalid token format."""
        handler = idp_handler(
            discovery=mock_discovery_doc,
            jwks=signing_jwks,
            token={"access_token": "at", "token_type": "Bearer", "id_token": "not-a-jwt"},
        )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)

            with pytest.raises(TokenValidationError):
                provider.exchange_code_stateless(code="auth-code", code_verifier="v")

    def test_decode_jwt_unverified_valid(self, oidc_provider: OIDCProvider) -> None:
        """Test _decode_jwt_unverified with valid JWT."""
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
        memory_storage: MemoryTokenStorage,
        signing_key: Any,
        signing_jwks: dict[str, Any],
    ) -> None:
        """Test that an explicit jwks_uri is used instead of the discovered one."""
        explicit_jwks_uri = "https://auth.example.com/custom/jwks"
        config = AuthProviderConfig(
            client_id="test-oidc-client",
            issuer="https://auth.example.com",
            jwks_uri=explicit_jwks_uri,
            redirect_uri="http://127.0.0.1:8400/callback",
        )
        discovery_doc = {
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
            "jwks_uri": "https://auth.example.com/discovered/jwks",
        }
        id_token = make_id_token(signing_key, issuer="https://auth.example.com", audience="test-oidc-client")
        calls: list[str] = []
        handler = idp_handler(
            discovery=discovery_doc,
            jwks=signing_jwks,
            token={"access_token": "at", "token_type": "Bearer", "id_token": id_token},
            calls=calls,
        )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("hybrid", config, memory_storage, http_client=client)
            provider.exchange_code_stateless(code="auth-code", code_verifier="v")

        assert "GET /custom/jwks" in calls, calls
        assert "GET /discovered/jwks" not in calls, calls

    def test_get_jwks_from_discovery(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        mock_discovery_doc: dict,
        signing_key: Any,
        signing_jwks: dict[str, Any],
    ) -> None:
        """Test that the JWKS URI falls back to discovery."""
        id_token = make_id_token(signing_key, issuer="https://auth.example.com", audience="test-oidc-client")
        calls: list[str] = []
        handler = idp_handler(
            discovery=mock_discovery_doc,
            jwks=signing_jwks,
            token={"access_token": "at", "token_type": "Bearer", "id_token": id_token},
            calls=calls,
        )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)
            provider.exchange_code_stateless(code="auth-code", code_verifier="v")

        assert "GET /.well-known/jwks.json" in calls, calls

    def test_get_jwks_cached_between_validations(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        mock_discovery_doc: dict,
        signing_key: Any,
        signing_jwks: dict[str, Any],
    ) -> None:
        """The JWKS is fetched once and reused while within its TTL."""
        id_token = make_id_token(signing_key, issuer="https://auth.example.com", audience="test-oidc-client")
        calls: list[str] = []
        handler = idp_handler(
            discovery=mock_discovery_doc,
            jwks=signing_jwks,
            token={"access_token": "at", "token_type": "Bearer", "id_token": id_token},
            calls=calls,
        )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)
            provider.exchange_code_stateless(code="code-1", code_verifier="v")
            provider.exchange_code_stateless(code="code-2", code_verifier="v")

        assert calls.count("GET /.well-known/jwks.json") == 1, calls

    def test_get_jwks_no_uri_error(self, memory_storage: MemoryTokenStorage) -> None:
        """Test that validation raises if no jwks_uri is available."""
        # Manual mode without jwks_uri
        config = AuthProviderConfig(
            client_id="test",
            authorize_url="https://idp.local/auth",
            token_url="https://idp.local/token",
            # No jwks_uri!
            redirect_uri="http://localhost/callback",
        )
        handler = idp_handler(token={"access_token": "at", "token_type": "Bearer", "id_token": "a.b.c"})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("manual", config, memory_storage, http_client=client)

            with pytest.raises(TokenValidationError, match="No jwks_uri configured"):
                provider.exchange_code_stateless(code="auth-code", code_verifier="v")

    def test_get_jwks_request_error(
        self,
        manual_oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Test that a JWKS transport failure surfaces as TokenValidationError."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                return httpx.Response(
                    200,
                    json={"access_token": "at", "token_type": "Bearer", "id_token": "a.b.c"},
                )
            raise httpx.RequestError("Connection failed", request=request)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("manual", manual_oidc_config, memory_storage, http_client=client)

            with pytest.raises(TokenValidationError, match="Failed to fetch JWKS"):
                provider.exchange_code_stateless(code="auth-code", code_verifier="v")


class TestGetUserInfo:
    """Tests for UserInfo endpoint."""

    def test_get_userinfo_success(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        mock_discovery_doc: dict,
    ) -> None:
        """Test successful userinfo request."""
        handler = idp_handler(
            discovery=mock_discovery_doc,
            userinfo={"sub": "user123", "name": "Test User", "email": "test@example.com"},
        )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)

            token = Token(
                access_token="valid-access-token",
                token_type="Bearer",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            provider.save_token(token)

            userinfo = provider.get_userinfo()

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
        calls: list[str] = []
        handler = idp_handler(userinfo={"sub": "user123"}, calls=calls)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("manual", manual_oidc_config, memory_storage, http_client=client)

            token = Token(
                access_token="access-token",
                token_type="Bearer",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            provider.save_token(token)

            provider.get_userinfo()

        # Should use explicit endpoint, not discovery
        assert calls == ["GET /userinfo"]

    def test_get_userinfo_no_endpoint_error(self, memory_storage: MemoryTokenStorage) -> None:
        """Test get_userinfo fails if no endpoint available."""
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
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        mock_discovery_doc: dict,
        mock_jwks: dict,
    ) -> None:
        """Test that preflight includes discovery check."""
        handler = idp_handler(discovery=mock_discovery_doc, jwks=mock_jwks)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)
            report = provider.preflight()

        step_names = [r.step for r in report.results]
        assert "discovery" in step_names
        assert "jwks" in step_names

    def test_preflight_jwks_without_keys_warns(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        mock_discovery_doc: dict,
    ) -> None:
        """Preflight warns when the JWKS document carries no key."""
        handler = idp_handler(discovery=mock_discovery_doc, jwks={"keys": []})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)
            report = provider.preflight()

        jwks_result = next(r for r in report.results if r.step == "jwks")
        assert jwks_result.status == PreflightStatus.WARNING
        assert "no keys" in jwks_result.message

    def test_preflight_discovery_failure(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Test preflight reports discovery failure."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection failed", request=request)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)
            report = provider.preflight()

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
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        mock_discovery_doc: dict,
    ) -> None:
        """Test that refresh() calls discover() before parent refresh."""
        calls: list[str] = []
        handler = idp_handler(
            discovery=mock_discovery_doc,
            token={
                "access_token": "new-access-token",
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": "new-refresh-token",
            },
            calls=calls,
        )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)

            # Create an expired token with refresh_token
            expired_token = Token(
                access_token="expired-access-token",
                token_type="Bearer",
                expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc),  # Expired
                refresh_token="valid-refresh-token",
            )
            provider.save_token(expired_token)

            new_token = provider.refresh()

        # Verify discovery was called BEFORE token refresh
        assert calls == ["GET /.well-known/openid-configuration", "POST /token"]
        assert new_token.access_token == "new-access-token"

    def test_refresh_uses_discovered_token_endpoint(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Test that refresh uses the token_endpoint from discovery, not fallback."""
        # Discovery document with CORRECT endpoint (like Keycloak uses)
        keycloak_discovery = {
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/protocol/openid-connect/auth",
            "token_endpoint": "https://auth.example.com/protocol/openid-connect/token",
            "userinfo_endpoint": "https://auth.example.com/protocol/openid-connect/userinfo",
            "jwks_uri": "https://auth.example.com/protocol/openid-connect/certs",
        }
        calls: list[str] = []
        handler = idp_handler(
            discovery=keycloak_discovery,
            token={"access_token": "new-token", "token_type": "Bearer", "expires_in": 300},
            calls=calls,
        )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)

            # Before discovery: no static token endpoint (discovery resolves it)
            assert provider.config.token_url is None

            token = Token(
                access_token="access-token",
                token_type="Bearer",
                expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc),  # Expired
                refresh_token="refresh-token",
            )
            provider.save_token(token)

            provider.refresh()

        # Verify the CORRECT endpoint was used (from discovery, not fallback)
        assert "POST /protocol/openid-connect/token" in calls, calls
        # Verify config was updated
        assert provider.config.token_url == "https://auth.example.com/protocol/openid-connect/token"

    def test_no_issuer_derived_fallback_before_discovery(
        self,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """No issuer-derived token_url guess exists; discovery sets the real one.

        Keycloak-style IDPs nest endpoints under /protocol/openid-connect/,
        so any {issuer}/token guess would 404. The config stays unresolved
        until discovery provides the actual endpoint.
        """
        config = AuthProviderConfig(
            client_id="test-client",
            issuer="http://localhost:8080/realms/test",  # Keycloak-style issuer
            pkce=True,
            redirect_uri="http://127.0.0.1:8400/callback",
        )
        keycloak_discovery = {
            "issuer": "http://localhost:8080/realms/test",
            "token_endpoint": "http://localhost:8080/realms/test/protocol/openid-connect/token",
            "authorization_endpoint": "http://localhost:8080/realms/test/protocol/openid-connect/auth",
            "jwks_uri": "http://localhost:8080/realms/test/protocol/openid-connect/certs",
        }
        handler = idp_handler(discovery=keycloak_discovery)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("keycloak", config, memory_storage, http_client=client)

            # No fallback guess: unresolved until discovery
            assert provider.config.token_url is None

            provider.discover()

        # NOW it's correct
        assert provider.config.token_url == "http://localhost:8080/realms/test/protocol/openid-connect/token"


# ─────────────────────────────────────────────────────────────────────────────
# Additional coverage tests
# ─────────────────────────────────────────────────────────────────────────────


class TestOIDCCoverage:
    """Tests to cover edge cases in OIDC provider."""

    def test_discovery_document_without_endpoints_leaves_config_unchanged(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """An empty discovery document resolves no endpoint and raises nothing."""
        handler = idp_handler(discovery={})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)

            original_token_url = provider.config.token_url
            original_authorize_url = provider.config.authorize_url

            doc = provider.discover()

        assert doc == {}
        assert provider.config.token_url == original_token_url
        assert provider.config.authorize_url == original_authorize_url

    def test_preflight_discovery_missing_fields_warning(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """Preflight returns warning when discovery document is missing fields."""
        # Discovery document missing jwks_uri
        incomplete_discovery = {
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
            # Missing: jwks_uri
        }
        handler = idp_handler(discovery=incomplete_discovery)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)
            report = provider.preflight()

        # Find discovery result
        discovery_result = next(r for r in report.results if r.step == "discovery")
        assert discovery_result.status == PreflightStatus.WARNING
        assert "jwks_uri" in discovery_result.message

    def test_preflight_scopes_unsupported_warning(
        self,
        memory_storage: MemoryTokenStorage,
        mock_jwks: dict,
    ) -> None:
        """Preflight returns warning when requested scopes are not supported."""
        config = AuthProviderConfig(
            client_id="test",
            issuer="https://auth.example.com",
            scopes=["openid", "profile", "custom_unsupported_scope"],
        )
        # Discovery document with limited scopes_supported
        discovery_doc = {
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
            "jwks_uri": "https://auth.example.com/.well-known/jwks.json",
            "scopes_supported": ["openid", "profile", "email"],  # No custom_unsupported_scope
        }
        handler = idp_handler(discovery=discovery_doc, jwks=mock_jwks)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("test", config, memory_storage, http_client=client)
            report = provider.preflight()

        # Find scopes result
        scopes_result = next((r for r in report.results if r.step == "scopes"), None)
        assert scopes_result is not None
        assert scopes_result.status == PreflightStatus.WARNING
        assert "custom_unsupported_scope" in scopes_result.message

    def test_validate_id_token_success_with_authlib(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        mock_discovery_doc: dict,
        signing_key: Any,
        signing_jwks: dict[str, Any],
    ) -> None:
        """A correctly signed ID token passes validation and is returned intact."""
        id_token = make_id_token(
            signing_key,
            issuer="https://auth.example.com",
            audience="test-oidc-client",
            sub="user123",
        )
        handler = idp_handler(
            discovery=mock_discovery_doc,
            jwks=signing_jwks,
            token={"access_token": "at", "token_type": "Bearer", "id_token": id_token},
        )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)
            token = provider.exchange_code_stateless(code="auth-code", code_verifier="v")

        assert token.id_token == id_token

    def test_discover_trace_logging(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        mock_discovery_doc: dict,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """discover() at TRACE emits the fetch and response introspection lines."""
        handler = idp_handler(discovery=mock_discovery_doc)

        with (
            httpx.Client(transport=httpx.MockTransport(handler)) as client,
            caplog.at_level(TRACE_LEVEL, logger="kstlib.auth.providers.oidc"),
        ):
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)
            provider.discover()

        messages = [record.getMessage() for record in caplog.records]
        assert any("[OIDC] Fetching discovery document" in m for m in messages), messages
        assert any("[OIDC] Discovery response" in m for m in messages), messages

    def test_generate_pkce_trace_logging(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        mock_discovery_doc: dict,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """get_authorization_url at TRACE emits the PKCE generation line."""
        handler = idp_handler(discovery=mock_discovery_doc)

        with (
            httpx.Client(transport=httpx.MockTransport(handler)) as client,
            caplog.at_level(TRACE_LEVEL, logger="kstlib.auth.providers.oidc"),
        ):
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)
            provider.get_authorization_url()

        messages = [record.getMessage() for record in caplog.records]
        assert any("[PKCE] Generated code_verifier" in m for m in messages), messages

    def test_get_jwks_trace_logging(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        mock_discovery_doc: dict,
        signing_key: Any,
        signing_jwks: dict[str, Any],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The JWKS fetch at TRACE emits the fetch and loaded-keys introspection lines."""
        id_token = make_id_token(signing_key, issuer="https://auth.example.com", audience="test-oidc-client")
        handler = idp_handler(
            discovery=mock_discovery_doc,
            jwks=signing_jwks,
            token={"access_token": "at", "token_type": "Bearer", "id_token": id_token},
        )

        with (
            httpx.Client(transport=httpx.MockTransport(handler)) as client,
            caplog.at_level(TRACE_LEVEL, logger="kstlib.auth.providers.oidc"),
        ):
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)
            provider.exchange_code_stateless(code="auth-code", code_verifier="v")

        messages = [record.getMessage() for record in caplog.records]
        assert any("[JWKS] Fetching keys" in m for m in messages), messages
        assert any("[JWKS] Loaded" in m for m in messages), messages

    def test_get_jwks_http_status_error(
        self,
        manual_oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """A JWKS error answer maps to TokenValidationError carrying the status."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                return httpx.Response(
                    200,
                    json={"access_token": "at", "token_type": "Bearer", "id_token": "a.b.c"},
                )
            return httpx.Response(500, text="Server Error")

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("test", manual_oidc_config, memory_storage, http_client=client)

            with pytest.raises(TokenValidationError, match="HTTP 500"):
                provider.exchange_code_stateless(code="auth-code", code_verifier="v")

    def test_get_jwks_null_document_raises(
        self,
        manual_oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
    ) -> None:
        """A JWKS endpoint returning a null body raises ConfigurationError."""

        def null_jwks_handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                return httpx.Response(
                    200,
                    json={"access_token": "at", "token_type": "Bearer", "id_token": "a.b.c"},
                )
            # Literal JSON null, which decodes to None (an empty body would
            # fail to decode instead, and never reach the guard under test)
            return httpx.Response(200, content=b"null")

        with httpx.Client(transport=httpx.MockTransport(null_jwks_handler)) as client:
            provider = OIDCProvider("test", manual_oidc_config, memory_storage, http_client=client)

            with pytest.raises(ConfigurationError, match="empty document"):
                provider.exchange_code_stateless(code="auth-code", code_verifier="v")

    def test_validate_id_token_trace_logging(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        mock_discovery_doc: dict,
        signing_key: Any,
        signing_jwks: dict[str, Any],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """ID token validation at TRACE emits the validating and validated lines."""
        id_token = make_id_token(signing_key, issuer="https://auth.example.com", audience="test-oidc-client")
        handler = idp_handler(
            discovery=mock_discovery_doc,
            jwks=signing_jwks,
            token={"access_token": "at", "token_type": "Bearer", "id_token": id_token},
        )

        with (
            httpx.Client(transport=httpx.MockTransport(handler)) as client,
            caplog.at_level(TRACE_LEVEL, logger="kstlib.auth.providers.oidc"),
        ):
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)
            provider.exchange_code_stateless(code="auth-code", code_verifier="v")

        messages = [record.getMessage() for record in caplog.records]
        assert any("[ID_TOKEN] Validating token" in m for m in messages), messages
        assert any("[ID_TOKEN] Validated" in m for m in messages), messages

    def test_validate_id_token_authlib_import_error_raises(
        self,
        oidc_config: AuthProviderConfig,
        memory_storage: MemoryTokenStorage,
        mock_discovery_doc: dict,
        signing_jwks: dict[str, Any],
    ) -> None:
        """Test ID token validation raises when authlib is not available."""
        handler = idp_handler(
            discovery=mock_discovery_doc,
            jwks=signing_jwks,
            token={"access_token": "at", "token_type": "Bearer", "id_token": "a.b.c"},
        )

        # A None entry in sys.modules makes the import raise ImportError
        with (
            httpx.Client(transport=httpx.MockTransport(handler)) as client,
            patch.dict(sys.modules, {"authlib.jose": None}),
            pytest.raises(TokenValidationError, match="authlib is required"),
        ):
            provider = OIDCProvider("test", oidc_config, memory_storage, http_client=client)
            provider.exchange_code_stateless(code="auth-code", code_verifier="v")

    def test_validate_id_token_uses_discovered_issuer(
        self,
        memory_storage: MemoryTokenStorage,
        signing_key: Any,
        signing_jwks: dict[str, Any],
    ) -> None:
        """Test that ID token validation uses discovered issuer, not configured.

        This is critical for enterprise IDPs that return a different issuer
        in the discovery document than what the user configured. A token
        carrying the CONFIGURED issuer must be rejected, which pins the
        contract from the opposite side of
        ``test_discover_stores_discovered_issuer``.
        """
        configured_issuer = "https://sso.enterprise.local"
        discovered_issuer = "https://sso.enterprise.local:443/oauth2"
        config = AuthProviderConfig(
            client_id="test-client",
            issuer=configured_issuer,  # User's config
            scopes=["openid"],
            redirect_uri="http://127.0.0.1:8400/callback",
        )
        discovery_doc = {
            "issuer": discovered_issuer,
            "authorization_endpoint": f"{discovered_issuer}/authorize",
            "token_endpoint": f"{discovered_issuer}/token",
            "jwks_uri": f"{discovered_issuer}/certs",
        }
        stale = make_id_token(signing_key, issuer=configured_issuer, audience="test-client")
        handler = idp_handler(
            discovery=discovery_doc,
            jwks=signing_jwks,
            token={"access_token": "at", "token_type": "Bearer", "id_token": stale},
        )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            provider = OIDCProvider("enterprise", config, memory_storage, http_client=client)

            with pytest.raises(TokenValidationError):
                provider.exchange_code_stateless(code="auth-code", code_verifier="v")
