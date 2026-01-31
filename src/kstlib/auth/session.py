"""Authenticated HTTP session wrapper."""

from __future__ import annotations

from enum import Enum
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import httpx
from typing_extensions import Self

from kstlib.auth.errors import AuthError, TokenExpiredError
from kstlib.logging import TRACE_LEVEL, get_logger
from kstlib.ssl import build_ssl_context

if TYPE_CHECKING:
    import types

    from kstlib.auth.providers.base import AbstractAuthProvider

logger = get_logger(__name__)

# Default timeout for HTTP requests
DEFAULT_TIMEOUT = 30.0


class AuthSession:
    """HTTP session with automatic token injection and refresh.

    Wraps httpx.Client (sync) or httpx.AsyncClient (async) to automatically:
    - Inject Bearer token in Authorization header
    - Refresh expired tokens before making requests
    - Handle 401 responses by refreshing and retrying

    Example (sync):
        >>> from kstlib.auth import AuthSession, get_provider  # doctest: +SKIP
        >>> provider = get_provider("corporate")  # doctest: +SKIP
        >>> with AuthSession(provider) as session:  # doctest: +SKIP
        ...     response = session.get("https://api.example.com/users/me")
        ...     print(response.json())

    Example (async):
        >>> async with AuthSession(provider) as session:  # doctest: +SKIP
        ...     response = await session.get("https://api.example.com/users/me")
        ...     print(response.json())
    """

    def __init__(
        self,
        provider: AbstractAuthProvider,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        auto_refresh: bool = True,
        retry_on_401: bool = True,
        ssl_verify: bool | None = None,
        ssl_ca_bundle: str | None = None,
    ) -> None:
        """Initialize authenticated session.

        Args:
            provider: Authentication provider to use for tokens.
            timeout: Default request timeout in seconds.
            auto_refresh: Automatically refresh expired tokens before requests.
            retry_on_401: Retry request after token refresh on 401 response.
            ssl_verify: Override SSL verification (True/False).
                If None, uses provider's SSL config or global config.
            ssl_ca_bundle: Override CA bundle path.
                If None, uses provider's SSL config or global config.
        """
        self.provider = provider
        self.timeout = timeout
        self.auto_refresh = auto_refresh
        self.retry_on_401 = retry_on_401

        # Build SSL context: kwargs > provider config > global config
        if ssl_verify is None and ssl_ca_bundle is None and hasattr(provider, "config"):
            # Use provider's SSL settings if available
            # Check for actual bool/str values (not MagicMock from tests)
            provider_config = getattr(provider, "config", None)
            provider_ssl_verify: bool | None = None
            provider_ca_bundle: str | None = None

            if provider_config is not None:
                ssl_verify_attr = getattr(provider_config, "ssl_verify", None)
                if isinstance(ssl_verify_attr, bool):
                    provider_ssl_verify = ssl_verify_attr

                ca_bundle_attr = getattr(provider_config, "ssl_ca_bundle", None)
                if isinstance(ca_bundle_attr, str):
                    provider_ca_bundle = ca_bundle_attr

            self._ssl_context = build_ssl_context(
                ssl_verify=provider_ssl_verify,
                ssl_ca_bundle=provider_ca_bundle,
            )
        else:
            # Use explicit kwargs or fall back to global config
            self._ssl_context = build_ssl_context(
                ssl_verify=ssl_verify,
                ssl_ca_bundle=ssl_ca_bundle,
            )

        self._sync_client: httpx.Client | None = None
        self._async_client: httpx.AsyncClient | None = None

    # ─────────────────────────────────────────────────────────────────────────
    # Context managers
    # ─────────────────────────────────────────────────────────────────────────

    def __enter__(self) -> Self:
        """Enter sync context manager."""
        self._sync_client = httpx.Client(timeout=self.timeout, verify=self._ssl_context)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Exit sync context manager."""
        if self._sync_client:
            self._sync_client.close()
            self._sync_client = None

    async def __aenter__(self) -> Self:
        """Enter async context manager."""
        self._async_client = httpx.AsyncClient(timeout=self.timeout, verify=self._ssl_context)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Exit async context manager."""
        if self._async_client:
            await self._async_client.aclose()
            self._async_client = None

    # ─────────────────────────────────────────────────────────────────────────
    # Token handling
    # ─────────────────────────────────────────────────────────────────────────

    def _get_auth_header(self) -> dict[str, str]:
        """Get Authorization header with current token.

        Returns:
            Dict with Authorization header.

        Raises:
            TokenExpiredError: If no valid token is available.
        """
        token = self.provider.get_token(auto_refresh=self.auto_refresh)

        if token is None:
            raise TokenExpiredError("No token available - authentication required")

        if token.is_expired and not token.is_refreshable:
            raise TokenExpiredError("Token expired and cannot be refreshed")

        # Extract string value from TokenType enum or use as-is if already a string
        token_type = token.token_type.value if isinstance(token.token_type, Enum) else token.token_type

        return {"Authorization": f"{token_type} {token.access_token}"}

    def _should_retry(self, response: httpx.Response, retried: bool) -> bool:
        """Check if request should be retried after 401."""
        return (
            self.retry_on_401
            and not retried
            and response.status_code == HTTPStatus.UNAUTHORIZED
            and self.provider.get_token(auto_refresh=False) is not None
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Sync HTTP methods
    # ─────────────────────────────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        url: str,
        *,
        _retried: bool = False,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make an authenticated HTTP request (sync).

        Args:
            method: HTTP method.
            url: Request URL.
            _retried: Internal flag to prevent infinite retry.
            **kwargs: Additional arguments for httpx.

        Returns:
            HTTP response.
        """
        if self._sync_client is None:
            msg = "Session not initialized - use 'with AuthSession(...) as session:'"
            raise AuthError(msg)

        # Merge auth header with any existing headers
        headers = kwargs.pop("headers", {})
        headers.update(self._get_auth_header())
        kwargs["headers"] = headers

        if logger.isEnabledFor(TRACE_LEVEL):
            logger.log(TRACE_LEVEL, "[SESSION] %s %s", method, url)

        response = self._sync_client.request(method, url, **kwargs)

        if logger.isEnabledFor(TRACE_LEVEL):
            logger.log(TRACE_LEVEL, "[SESSION] Response: %d %s", response.status_code, response.reason_phrase)

        # Retry on 401 if configured
        if self._should_retry(response, _retried):
            logger.debug("Got 401, attempting token refresh and retry")
            try:
                self.provider.refresh()
                return self._request(method, url, _retried=True, **kwargs)
            except Exception:  # pylint: disable=broad-exception-caught
                # Intentional catch-all for best-effort refresh
                logger.warning("Token refresh failed, returning original 401 response")

        return response

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """Make authenticated GET request."""
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        """Make authenticated POST request."""
        return self._request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> httpx.Response:
        """Make authenticated PUT request."""
        return self._request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> httpx.Response:
        """Make authenticated PATCH request."""
        return self._request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        """Make authenticated DELETE request."""
        return self._request("DELETE", url, **kwargs)

    def head(self, url: str, **kwargs: Any) -> httpx.Response:
        """Make authenticated HEAD request."""
        return self._request("HEAD", url, **kwargs)

    def options(self, url: str, **kwargs: Any) -> httpx.Response:
        """Make authenticated OPTIONS request."""
        return self._request("OPTIONS", url, **kwargs)

    # ─────────────────────────────────────────────────────────────────────────
    # Async HTTP methods
    # ─────────────────────────────────────────────────────────────────────────

    async def _arequest(
        self,
        method: str,
        url: str,
        *,
        _retried: bool = False,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make an authenticated HTTP request (async).

        Args:
            method: HTTP method.
            url: Request URL.
            _retried: Internal flag to prevent infinite retry.
            **kwargs: Additional arguments for httpx.

        Returns:
            HTTP response.
        """
        if self._async_client is None:
            msg = "Session not initialized - use 'async with AuthSession(...) as session:'"
            raise AuthError(msg)

        # Merge auth header with any existing headers
        headers = kwargs.pop("headers", {})
        headers.update(self._get_auth_header())
        kwargs["headers"] = headers

        if logger.isEnabledFor(TRACE_LEVEL):
            logger.log(TRACE_LEVEL, "[SESSION] %s %s (async)", method, url)

        response = await self._async_client.request(method, url, **kwargs)

        if logger.isEnabledFor(TRACE_LEVEL):
            logger.log(TRACE_LEVEL, "[SESSION] Response: %d %s", response.status_code, response.reason_phrase)

        # Retry on 401 if configured
        if self._should_retry(response, _retried):
            logger.debug("Got 401, attempting token refresh and retry")
            try:
                self.provider.refresh()
                return await self._arequest(method, url, _retried=True, **kwargs)
            except Exception:  # pylint: disable=broad-exception-caught
                # Intentional catch-all for best-effort refresh
                logger.warning("Token refresh failed, returning original 401 response")

        return response

    async def aget(self, url: str, **kwargs: Any) -> httpx.Response:
        """Make authenticated async GET request."""
        return await self._arequest("GET", url, **kwargs)

    async def apost(self, url: str, **kwargs: Any) -> httpx.Response:
        """Make authenticated async POST request."""
        return await self._arequest("POST", url, **kwargs)

    async def aput(self, url: str, **kwargs: Any) -> httpx.Response:
        """Make authenticated async PUT request."""
        return await self._arequest("PUT", url, **kwargs)

    async def apatch(self, url: str, **kwargs: Any) -> httpx.Response:
        """Make authenticated async PATCH request."""
        return await self._arequest("PATCH", url, **kwargs)

    async def adelete(self, url: str, **kwargs: Any) -> httpx.Response:
        """Make authenticated async DELETE request."""
        return await self._arequest("DELETE", url, **kwargs)

    async def ahead(self, url: str, **kwargs: Any) -> httpx.Response:
        """Make authenticated async HEAD request."""
        return await self._arequest("HEAD", url, **kwargs)

    async def aoptions(self, url: str, **kwargs: Any) -> httpx.Response:
        """Make authenticated async OPTIONS request."""
        return await self._arequest("OPTIONS", url, **kwargs)


__all__ = ["AuthSession"]
