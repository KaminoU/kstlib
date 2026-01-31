"""Pytest fixtures for auth module tests."""

from __future__ import annotations

import contextlib
import os
import shutil
import socket
from collections.abc import Generator
from typing import TYPE_CHECKING

import httpx
import pytest

if TYPE_CHECKING:
    from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Skip markers
# ─────────────────────────────────────────────────────────────────────────────

KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "kstlib-test")


def is_keycloak_available() -> bool:
    """Check if Keycloak is running and accessible."""
    try:
        response = httpx.get(f"{KEYCLOAK_URL}/health/ready", timeout=5)
        return response.status_code == 200
    except Exception:
        return False


def _has_sops() -> bool:
    """Check if sops binary is available."""
    return shutil.which("sops") is not None


def _has_age_keygen() -> bool:
    """Check if age-keygen binary is available."""
    return shutil.which("age-keygen") is not None


requires_keycloak = pytest.mark.skipif(
    not is_keycloak_available(),
    reason="Keycloak not available (run: docker compose -f infra/docker-compose.yml up -d keycloak)",
)

requires_sops = pytest.mark.skipif(
    not _has_sops(),
    reason="sops not installed",
)

requires_age = pytest.mark.skipif(
    not _has_age_keygen(),
    reason="age-keygen not installed",
)


# ─────────────────────────────────────────────────────────────────────────────
# Basic fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def memory_storage():
    """Create a fresh MemoryTokenStorage."""
    from kstlib.auth.token import MemoryTokenStorage

    return MemoryTokenStorage()


@pytest.fixture
def file_storage(temp_storage_dir):
    """Create a FileTokenStorage in a temporary directory."""
    from kstlib.auth.token import FileTokenStorage

    return FileTokenStorage(directory=temp_storage_dir)


@pytest.fixture
def temp_storage_dir(tmp_path: Path):
    """Create a temporary directory for token storage."""
    storage_dir = tmp_path / "tokens"
    storage_dir.mkdir()
    return storage_dir


@pytest.fixture
def sample_token():
    """Create a sample valid token."""
    from datetime import datetime, timedelta, timezone

    from kstlib.auth.models import Token

    return Token(
        access_token="test_access_token_12345",
        token_type="Bearer",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        refresh_token="test_refresh_token_67890",
        scope=["openid", "profile", "email"],
        id_token="eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature",
    )


@pytest.fixture
def expired_token():
    """Create an expired token."""
    from datetime import datetime, timedelta, timezone

    from kstlib.auth.models import Token

    return Token(
        access_token="expired_access_token",
        token_type="Bearer",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        refresh_token="expired_refresh_token",
        scope=["openid"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# OAuth2/OIDC Provider fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def oauth2_config():
    """Create a basic OAuth2 provider config."""
    from kstlib.auth.providers import AuthProviderConfig

    return AuthProviderConfig(
        client_id="test-client",
        client_secret="test-secret",
        authorize_url="https://auth.example.com/authorize",
        token_url="https://auth.example.com/token",
        revoke_url="https://auth.example.com/revoke",
        scopes=["read", "write"],
        redirect_uri="http://127.0.0.1:8400/callback",
    )


@pytest.fixture
def oidc_config():
    """Create an OIDC provider config."""
    from kstlib.auth.providers import AuthProviderConfig

    return AuthProviderConfig(
        client_id="test-oidc-client",
        issuer="https://auth.example.com",
        scopes=["openid", "profile", "email"],
        pkce=True,
        redirect_uri="http://127.0.0.1:8400/callback",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Keycloak fixtures (for e2e tests)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def keycloak_issuer() -> str:
    """Get the Keycloak issuer URL."""
    return f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}"


@pytest.fixture
def keycloak_public_client_config(keycloak_issuer: str):
    """Create config for Keycloak public client (PKCE)."""
    from kstlib.auth.providers import AuthProviderConfig

    return AuthProviderConfig(
        client_id="kstlib-test-public",
        issuer=keycloak_issuer,
        scopes=["openid", "profile", "email"],
        pkce=True,
        redirect_uri="http://127.0.0.1:8400/callback",
    )


@pytest.fixture
def keycloak_confidential_client_config(keycloak_issuer: str):
    """Create config for Keycloak confidential client."""
    from kstlib.auth.providers import AuthProviderConfig

    return AuthProviderConfig(
        client_id="kstlib-test-confidential",
        client_secret="kstlib-test-secret",
        issuer=keycloak_issuer,
        scopes=["openid", "profile", "email"],
        pkce=False,
        redirect_uri="http://127.0.0.1:8400/callback",
    )


@pytest.fixture
def keycloak_test_user() -> dict[str, str]:
    """Get test user credentials for Keycloak."""
    return {
        "username": "testuser",
        "password": "testpass123",
        "email": "testuser@example.com",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Callback server fixture
# ─────────────────────────────────────────────────────────────────────────────


def find_free_port() -> int:
    """Find a free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def callback_server() -> Generator:
    """Create and start a callback server."""
    from kstlib.auth.callback import CallbackServer

    port = find_free_port()
    server = CallbackServer(host="127.0.0.1", port=port)

    yield server

    # Cleanup
    with contextlib.suppress(Exception):
        server.stop()
