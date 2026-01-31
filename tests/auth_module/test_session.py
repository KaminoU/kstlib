"""Unit tests for AuthSession."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import httpx
import pytest

from kstlib.auth.errors import AuthError, TokenExpiredError
from kstlib.auth.models import Token
from kstlib.auth.session import AuthSession

if TYPE_CHECKING:
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_provider() -> MagicMock:
    """Create a mock auth provider."""
    provider = MagicMock()
    provider.get_token.return_value = Token(
        access_token="test-access-token",
        token_type="Bearer",
        expires_at=None,
        refresh_token="test-refresh-token",
    )
    return provider


@pytest.fixture
def auth_session(mock_provider: MagicMock) -> AuthSession:
    """Create an AuthSession for testing."""
    return AuthSession(mock_provider)


# ─────────────────────────────────────────────────────────────────────────────
# Test initialization
# ─────────────────────────────────────────────────────────────────────────────


class TestAuthSessionInit:
    """Tests for AuthSession initialization."""

    def test_init_with_defaults(self, mock_provider: MagicMock) -> None:
        """Test initialization with default values."""
        session = AuthSession(mock_provider)

        assert session.provider is mock_provider
        assert session.timeout == 30.0
        assert session.auto_refresh is True
        assert session.retry_on_401 is True

    def test_init_with_custom_values(self, mock_provider: MagicMock) -> None:
        """Test initialization with custom values."""
        session = AuthSession(
            mock_provider,
            timeout=60.0,
            auto_refresh=False,
            retry_on_401=False,
        )

        assert session.timeout == 60.0
        assert session.auto_refresh is False
        assert session.retry_on_401 is False


# ─────────────────────────────────────────────────────────────────────────────
# Test context managers
# ─────────────────────────────────────────────────────────────────────────────


class TestContextManagers:
    """Tests for sync and async context managers."""

    def test_sync_context_manager(self, auth_session: AuthSession) -> None:
        """Test sync context manager creates and closes client."""
        assert auth_session._sync_client is None

        with auth_session as session:
            assert session._sync_client is not None
            assert isinstance(session._sync_client, httpx.Client)

        assert auth_session._sync_client is None

    @pytest.mark.asyncio
    async def test_async_context_manager(self, auth_session: AuthSession) -> None:
        """Test async context manager creates and closes client."""
        assert auth_session._async_client is None

        async with auth_session as session:
            assert session._async_client is not None
            assert isinstance(session._async_client, httpx.AsyncClient)

        assert auth_session._async_client is None


# ─────────────────────────────────────────────────────────────────────────────
# Test token handling
# ─────────────────────────────────────────────────────────────────────────────


class TestTokenHandling:
    """Tests for _get_auth_header."""

    def test_get_auth_header_success(self, auth_session: AuthSession) -> None:
        """Test getting auth header with valid token."""
        header = auth_session._get_auth_header()

        assert header == {"Authorization": "Bearer test-access-token"}

    def test_get_auth_header_no_token(self, mock_provider: MagicMock) -> None:
        """Test getting auth header with no token raises error."""
        mock_provider.get_token.return_value = None
        session = AuthSession(mock_provider)

        with pytest.raises(TokenExpiredError, match="No token available"):
            session._get_auth_header()

    def test_get_auth_header_expired_not_refreshable(self, mock_provider: MagicMock) -> None:
        """Test getting auth header with expired non-refreshable token."""
        expired_token = MagicMock()
        expired_token.is_expired = True
        expired_token.is_refreshable = False
        mock_provider.get_token.return_value = expired_token

        session = AuthSession(mock_provider)

        with pytest.raises(TokenExpiredError, match="expired and cannot be refreshed"):
            session._get_auth_header()

    def test_get_auth_header_with_enum_token_type(self, mock_provider: MagicMock) -> None:
        """Test getting auth header when token_type is an Enum."""
        from enum import Enum

        class TokenType(Enum):
            BEARER = "Bearer"

        token = MagicMock()
        token.access_token = "access-token"
        token.token_type = TokenType.BEARER
        token.is_expired = False
        mock_provider.get_token.return_value = token

        session = AuthSession(mock_provider)
        header = session._get_auth_header()

        assert header == {"Authorization": "Bearer access-token"}


# ─────────────────────────────────────────────────────────────────────────────
# Test sync HTTP methods
# ─────────────────────────────────────────────────────────────────────────────


class TestSyncHttpMethods:
    """Tests for sync HTTP request methods."""

    def test_request_without_context_raises(self, auth_session: AuthSession) -> None:
        """Test that request without context manager raises error."""
        with pytest.raises(AuthError, match="Session not initialized"):
            auth_session.get("https://example.com")

    def test_get_request(self, auth_session: AuthSession) -> None:
        """Test GET request."""
        with auth_session as session:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            session._sync_client.request = MagicMock(return_value=mock_response)

            session.get("https://api.example.com/users")

            session._sync_client.request.assert_called_once()
            call_args = session._sync_client.request.call_args
            assert call_args[0] == ("GET", "https://api.example.com/users")
            assert "Authorization" in call_args[1]["headers"]

    def test_post_request(self, auth_session: AuthSession) -> None:
        """Test POST request."""
        with auth_session as session:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 201
            session._sync_client.request = MagicMock(return_value=mock_response)

            session.post("https://api.example.com/users", json={"name": "test"})

            call_args = session._sync_client.request.call_args
            assert call_args[0] == ("POST", "https://api.example.com/users")

    def test_put_request(self, auth_session: AuthSession) -> None:
        """Test PUT request."""
        with auth_session as session:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            session._sync_client.request = MagicMock(return_value=mock_response)

            session.put("https://api.example.com/users/1", json={"name": "test"})

            call_args = session._sync_client.request.call_args
            assert call_args[0] == ("PUT", "https://api.example.com/users/1")

    def test_patch_request(self, auth_session: AuthSession) -> None:
        """Test PATCH request."""
        with auth_session as session:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            session._sync_client.request = MagicMock(return_value=mock_response)

            session.patch("https://api.example.com/users/1", json={"name": "test"})

            call_args = session._sync_client.request.call_args
            assert call_args[0] == ("PATCH", "https://api.example.com/users/1")

    def test_delete_request(self, auth_session: AuthSession) -> None:
        """Test DELETE request."""
        with auth_session as session:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 204
            session._sync_client.request = MagicMock(return_value=mock_response)

            session.delete("https://api.example.com/users/1")

            call_args = session._sync_client.request.call_args
            assert call_args[0] == ("DELETE", "https://api.example.com/users/1")

    def test_head_request(self, auth_session: AuthSession) -> None:
        """Test HEAD request."""
        with auth_session as session:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            session._sync_client.request = MagicMock(return_value=mock_response)

            session.head("https://api.example.com/users")

            call_args = session._sync_client.request.call_args
            assert call_args[0] == ("HEAD", "https://api.example.com/users")

    def test_options_request(self, auth_session: AuthSession) -> None:
        """Test OPTIONS request."""
        with auth_session as session:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            session._sync_client.request = MagicMock(return_value=mock_response)

            session.options("https://api.example.com/users")

            call_args = session._sync_client.request.call_args
            assert call_args[0] == ("OPTIONS", "https://api.example.com/users")


# ─────────────────────────────────────────────────────────────────────────────
# Test 401 retry logic
# ─────────────────────────────────────────────────────────────────────────────


class TestRetryOn401:
    """Tests for 401 retry logic."""

    def test_retry_on_401_success(self, mock_provider: MagicMock) -> None:
        """Test successful retry after 401."""
        session = AuthSession(mock_provider, retry_on_401=True)

        with session:
            # First response is 401, second is 200
            response_401 = MagicMock(spec=httpx.Response)
            response_401.status_code = HTTPStatus.UNAUTHORIZED

            response_200 = MagicMock(spec=httpx.Response)
            response_200.status_code = HTTPStatus.OK

            session._sync_client.request = MagicMock(side_effect=[response_401, response_200])

            response = session.get("https://api.example.com/users")

            # Should have retried
            assert session._sync_client.request.call_count == 2
            mock_provider.refresh.assert_called_once()
            assert response.status_code == HTTPStatus.OK

    def test_retry_on_401_refresh_fails(self, mock_provider: MagicMock) -> None:
        """Test that original 401 is returned when refresh fails."""
        mock_provider.refresh.side_effect = Exception("Refresh failed")
        session = AuthSession(mock_provider, retry_on_401=True)

        with session:
            response_401 = MagicMock(spec=httpx.Response)
            response_401.status_code = HTTPStatus.UNAUTHORIZED

            session._sync_client.request = MagicMock(return_value=response_401)

            response = session.get("https://api.example.com/users")

            # Should return original 401
            assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_no_retry_when_disabled(self, mock_provider: MagicMock) -> None:
        """Test no retry when retry_on_401 is disabled."""
        session = AuthSession(mock_provider, retry_on_401=False)

        with session:
            response_401 = MagicMock(spec=httpx.Response)
            response_401.status_code = HTTPStatus.UNAUTHORIZED

            session._sync_client.request = MagicMock(return_value=response_401)

            session.get("https://api.example.com/users")

            # Should not retry
            assert session._sync_client.request.call_count == 1
            mock_provider.refresh.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Test async HTTP methods
# ─────────────────────────────────────────────────────────────────────────────


class TestAsyncHttpMethods:
    """Tests for async HTTP request methods."""

    @pytest.mark.asyncio
    async def test_arequest_without_context_raises(self, auth_session: AuthSession) -> None:
        """Test that async request without context manager raises error."""
        with pytest.raises(AuthError, match="Session not initialized"):
            await auth_session.aget("https://example.com")

    @pytest.mark.asyncio
    async def test_aget_request(self, auth_session: AuthSession) -> None:
        """Test async GET request."""
        async with auth_session as session:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200

            async def mock_request(*args, **kwargs):
                return mock_response

            session._async_client.request = mock_request

            response = await session.aget("https://api.example.com/users")

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_apost_request(self, auth_session: AuthSession) -> None:
        """Test async POST request."""
        async with auth_session as session:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 201

            async def mock_request(*args, **kwargs):
                return mock_response

            session._async_client.request = mock_request

            response = await session.apost("https://api.example.com/users")

            assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_aput_request(self, auth_session: AuthSession) -> None:
        """Test async PUT request."""
        async with auth_session as session:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200

            async def mock_request(*args, **kwargs):
                return mock_response

            session._async_client.request = mock_request

            response = await session.aput("https://api.example.com/users/1")

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_apatch_request(self, auth_session: AuthSession) -> None:
        """Test async PATCH request."""
        async with auth_session as session:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200

            async def mock_request(*args, **kwargs):
                return mock_response

            session._async_client.request = mock_request

            response = await session.apatch("https://api.example.com/users/1")

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_adelete_request(self, auth_session: AuthSession) -> None:
        """Test async DELETE request."""
        async with auth_session as session:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 204

            async def mock_request(*args, **kwargs):
                return mock_response

            session._async_client.request = mock_request

            response = await session.adelete("https://api.example.com/users/1")

            assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_ahead_request(self, auth_session: AuthSession) -> None:
        """Test async HEAD request."""
        async with auth_session as session:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200

            async def mock_request(*args, **kwargs):
                return mock_response

            session._async_client.request = mock_request

            response = await session.ahead("https://api.example.com/users")

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_aoptions_request(self, auth_session: AuthSession) -> None:
        """Test async OPTIONS request."""
        async with auth_session as session:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200

            async def mock_request(*args, **kwargs):
                return mock_response

            session._async_client.request = mock_request

            response = await session.aoptions("https://api.example.com/users")

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_async_retry_on_401(self, mock_provider: MagicMock) -> None:
        """Test async retry after 401."""
        session = AuthSession(mock_provider, retry_on_401=True)

        async with session:
            response_401 = MagicMock(spec=httpx.Response)
            response_401.status_code = HTTPStatus.UNAUTHORIZED

            response_200 = MagicMock(spec=httpx.Response)
            response_200.status_code = HTTPStatus.OK

            call_count = 0

            async def mock_request(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return response_401
                return response_200

            session._async_client.request = mock_request

            response = await session.aget("https://api.example.com/users")

            assert call_count == 2
            mock_provider.refresh.assert_called_once()
            assert response.status_code == HTTPStatus.OK

    @pytest.mark.asyncio
    async def test_async_retry_on_401_refresh_fails(self, mock_provider: MagicMock) -> None:
        """Test that async returns original 401 when refresh fails."""
        mock_provider.refresh.side_effect = Exception("Refresh failed")
        session = AuthSession(mock_provider, retry_on_401=True)

        async with session:
            response_401 = MagicMock(spec=httpx.Response)
            response_401.status_code = HTTPStatus.UNAUTHORIZED

            async def mock_request(*args, **kwargs):
                return response_401

            session._async_client.request = mock_request

            response = await session.aget("https://api.example.com/users")

            # Should return original 401 when refresh fails
            assert response.status_code == HTTPStatus.UNAUTHORIZED
            mock_provider.refresh.assert_called_once()
