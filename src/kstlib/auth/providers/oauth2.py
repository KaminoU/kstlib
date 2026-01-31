"""OAuth2 Authorization Code provider implementation."""

from __future__ import annotations

import secrets
import time
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

import httpx

from kstlib.auth.errors import (
    AuthError,
    ConfigurationError,
    TokenExchangeError,
    TokenRefreshError,
)
from kstlib.auth.models import (
    AuthFlow,
    PreflightReport,
    PreflightResult,
    PreflightStatus,
    Token,
)
from kstlib.auth.providers.base import (
    AbstractAuthProvider,
    AuthProviderConfig,
    load_provider_from_config,
)
from kstlib.logging import TRACE_LEVEL, get_logger
from kstlib.utils.http_trace import HTTPTraceLogger

if TYPE_CHECKING:
    from kstlib.auth.token import AbstractTokenStorage

logger = get_logger(__name__)

# Default trace settings (can be overridden by config)
# TRACE mode = debug mode, show full body by default
_TRACE_MAX_BODY_DEFAULT = 10000
_TRACE_MAX_BODY_HARD_LIMIT = 10000  # Defense in depth: never log more than 10KB
_TRACE_PRETTY_DEFAULT = True

# Default timeout for HTTP requests
DEFAULT_TIMEOUT = 30.0


class OAuth2Provider(AbstractAuthProvider):
    """OAuth2 Authorization Code flow provider.

    Implements the standard OAuth2 Authorization Code flow for confidential
    clients. For public clients or enhanced security, use OIDCProvider with PKCE.

    Example:
        >>> from kstlib.auth.providers import OAuth2Provider, AuthProviderConfig  # doctest: +SKIP
        >>> from kstlib.auth.token import MemoryTokenStorage  # doctest: +SKIP
        >>>
        >>> config = AuthProviderConfig(  # doctest: +SKIP
        ...     client_id="my-app",
        ...     client_secret="secret",
        ...     authorize_url="https://auth.example.com/authorize",
        ...     token_url="https://auth.example.com/token",
        ...     scopes=["read", "write"],
        ... )
        >>> provider = OAuth2Provider("example", config, MemoryTokenStorage())  # doctest: +SKIP
        >>> url, state = provider.get_authorization_url()  # doctest: +SKIP
        >>> # User visits URL, authorizes, redirected back with code
        >>> token = provider.exchange_code(code="...", state=state)  # doctest: +SKIP

    Config-driven usage:
        >>> # Configure in kstlib.conf.yml:
        >>> # auth:
        >>> #   providers:
        >>> #     github:
        >>> #       type: oauth2
        >>> #       authorization_endpoint: https://github.com/login/oauth/authorize
        >>> #       token_endpoint: https://github.com/login/oauth/access_token
        >>> #       client_id: my-app
        >>> #       client_secret: sops://secrets.yaml#github.secret
        >>> provider = OAuth2Provider.from_config("github")  # doctest: +SKIP
    """

    @classmethod
    def from_config(
        cls,
        provider_name: str,
        *,
        config: dict[str, Any] | None = None,
        http_client: httpx.Client | None = None,
        **overrides: Any,
    ) -> OAuth2Provider:
        """Create an OAuth2Provider from configuration.

        Loads provider settings from kstlib.conf.yml (auth.providers section)
        and creates a fully configured provider instance.

        Args:
            provider_name: Name of the provider in config.
            config: Optional explicit config dict (overrides global config).
            http_client: Optional custom HTTP client.
            **overrides: Direct parameter overrides (highest priority).

        Returns:
            Configured OAuth2Provider instance.

        Raises:
            ConfigurationError: If provider not found or required fields missing.

        Example:
            >>> provider = OAuth2Provider.from_config("github")  # doctest: +SKIP
        """
        auth_config, token_storage = load_provider_from_config(
            provider_name,
            allowed_types=("oauth2", "oauth"),
            type_label="oauth2",
            config=config,
            **overrides,
        )

        return cls(
            name=provider_name,
            config=auth_config,
            token_storage=token_storage,
            http_client=http_client,
        )

    def __init__(
        self,
        name: str,
        config: AuthProviderConfig,
        token_storage: AbstractTokenStorage,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        """Initialize OAuth2 provider.

        Args:
            name: Provider identifier.
            config: Provider configuration.
            token_storage: Token storage backend.
            http_client: Optional custom HTTP client.
        """
        super().__init__(name, config, token_storage)
        self._http_client = http_client
        self._pending_state: str | None = None
        self._tracer: HTTPTraceLogger | None = None

        # Validate required OAuth2 config
        if not config.authorize_url or not config.token_url:
            msg = "OAuth2Provider requires 'authorize_url' and 'token_url' in config"
            raise ConfigurationError(msg)

    @property
    def flow(self) -> AuthFlow:
        """Return the OAuth2 flow type."""
        return AuthFlow.AUTHORIZATION_CODE

    @property
    def tracer(self) -> HTTPTraceLogger:
        """Get or create HTTP trace logger with config-driven settings."""
        if self._tracer is None:
            pretty, max_body = self._get_trace_config()
            self._tracer = HTTPTraceLogger(
                logger,
                trace_level=TRACE_LEVEL,
                pretty_print=pretty,
                max_body_length=max_body,
            )
        return self._tracer

    @property
    def http_client(self) -> httpx.Client:
        """Get or create HTTP client with TRACE logging hooks.

        The client automatically includes any custom headers configured in
        ``config.headers``. These headers are sent with all IDP requests,
        useful for environments requiring specific headers (e.g., Host header
        for load balancer validation).

        SSL verification is controlled by ``config.ssl_verify`` and
        ``config.ssl_ca_bundle``. See :class:`AuthProviderConfig` for details.
        """
        if self._http_client is None:
            self._http_client = httpx.Client(
                timeout=DEFAULT_TIMEOUT,
                headers=self.config.headers or {},
                verify=self._build_ssl_context(),
                event_hooks={
                    "request": [self.tracer.on_request],
                    "response": [self.tracer.on_response],
                },
            )
        return self._http_client

    def _build_ssl_context(self) -> bool | str:
        """Build SSL verification context from config.

        Returns:
            - str: Path to CA bundle (if ssl_ca_bundle configured)
            - True: Default SSL verification (if ssl_verify=True, no custom CA)
            - False: Disable SSL verification (if ssl_verify=False)

        Note:
            ssl_ca_bundle takes precedence over ssl_verify=False.
            This is intentional: if you specify a CA bundle, you want verification.
        """
        if self.config.ssl_ca_bundle:
            return self.config.ssl_ca_bundle
        return self.config.ssl_verify

    # ─────────────────────────────────────────────────────────────────────────
    # Authorization flow
    # ─────────────────────────────────────────────────────────────────────────

    def get_authorization_url(self, state: str | None = None) -> tuple[str, str]:
        """Generate the authorization URL.

        Args:
            state: Optional state parameter. Generated if not provided.

        Returns:
            Tuple of (authorization_url, state).
        """
        if state is None:
            state = secrets.token_urlsafe(32)

        self._pending_state = state

        params = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "state": state,
        }

        if self.config.scopes:
            params["scope"] = " ".join(self.config.scopes)

        # Add any extra parameters from config
        params.update(self.config.extra.get("authorize_params", {}))

        url = f"{self.config.authorize_url}?{urlencode(params)}"
        logger.debug("Generated authorization URL for provider '%s'", self.name)
        return url, state

    def exchange_code(
        self,
        code: str,
        state: str,
        *,
        code_verifier: str | None = None,
    ) -> Token:
        """Exchange authorization code for tokens.

        Args:
            code: Authorization code from callback.
            state: State parameter for validation.
            code_verifier: PKCE code verifier (ignored for basic OAuth2).

        Returns:
            Token with access_token and optionally refresh_token.

        Raises:
            TokenExchangeError: If exchange fails.
        """
        # Validate state
        if self._pending_state and state != self._pending_state:
            msg = "State mismatch - possible CSRF attack"
            raise TokenExchangeError(msg, error_code="state_mismatch")

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.config.redirect_uri,
            "client_id": self.config.client_id,
        }

        # Add client_secret for confidential clients
        if self.config.client_secret:
            data["client_secret"] = self.config.client_secret

        # Add PKCE code_verifier if provided (for subclasses)
        if code_verifier:
            data["code_verifier"] = code_verifier

        assert self.config.token_url is not None  # Validated in __init__
        headers = {"Accept": "application/json"}
        try:
            response = self.http_client.post(
                self.config.token_url,
                data=data,
                headers=headers,
            )
            response.raise_for_status()
            token_data = response.json()
        except httpx.HTTPStatusError as e:
            error_data = self._parse_error_response(e.response)
            raise TokenExchangeError(
                error_data.get("error_description", str(e)),
                error_code=error_data.get("error"),
            ) from e
        except httpx.RequestError as e:
            raise TokenExchangeError(f"Network error: {e}") from e

        token = Token.from_response(token_data)
        self.save_token(token)
        self._pending_state = None

        logger.info("Token exchange successful for provider '%s'", self.name)
        return token

    def refresh(self, token: Token | None = None) -> Token:
        """Refresh an expired token.

        Args:
            token: Token to refresh. Uses stored token if not provided.

        Returns:
            New Token.

        Raises:
            TokenRefreshError: If refresh fails.
        """
        if token is None:
            token = self.get_token(auto_refresh=False)

        if token is None:
            raise TokenRefreshError("No token to refresh")

        if not token.refresh_token:
            raise TokenRefreshError("Token has no refresh_token", retryable=False)

        data = {
            "grant_type": "refresh_token",
            "refresh_token": token.refresh_token,
            "client_id": self.config.client_id,
        }

        if self.config.client_secret:
            data["client_secret"] = self.config.client_secret

        assert self.config.token_url is not None  # Validated in __init__
        headers = {"Accept": "application/json"}
        try:
            response = self.http_client.post(
                self.config.token_url,
                data=data,
                headers=headers,
            )
            response.raise_for_status()
            token_data = response.json()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            # Handle 404 specifically - likely wrong token_endpoint URL
            if status == HTTPStatus.NOT_FOUND:
                raise TokenRefreshError(
                    f"Token endpoint not found ({self.config.token_url}). "
                    "Please re-authenticate with 'kstlib auth login'.",
                    retryable=False,
                ) from e
            # Handle 401/400 - token likely expired or revoked
            if status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.BAD_REQUEST):
                error_data = self._parse_error_response(e.response)
                error_desc = error_data.get("error_description", "")
                raise TokenRefreshError(
                    f"Token refresh rejected: {error_desc or 'invalid or expired refresh token'}. "
                    "Please re-authenticate with 'kstlib auth login'.",
                    retryable=False,
                ) from e
            # Other errors
            error_data = self._parse_error_response(e.response)
            retryable = status >= HTTPStatus.INTERNAL_SERVER_ERROR
            raise TokenRefreshError(
                error_data.get("error_description", str(e)),
                retryable=retryable,
            ) from e
        except httpx.RequestError as e:
            raise TokenRefreshError(f"Network error: {e}", retryable=True) from e

        # Preserve refresh_token if not returned in response
        if "refresh_token" not in token_data and token.refresh_token:
            token_data["refresh_token"] = token.refresh_token

        new_token = Token.from_response(token_data)
        self.save_token(new_token)

        logger.info("Token refresh successful for provider '%s'", self.name)
        return new_token

    def revoke(self, token: Token | None = None) -> bool:
        """Revoke a token.

        Args:
            token: Token to revoke. Uses stored token if not provided.

        Returns:
            True if revoked, False if revocation not supported.
        """
        if not self.config.revoke_url:
            logger.debug("Revocation not configured for provider '%s'", self.name)
            return False

        if token is None:
            token = self.get_token(auto_refresh=False)

        if token is None:
            return False

        # Try revoking access_token first, then refresh_token
        tokens_to_revoke = [
            ("access_token", token.access_token),
        ]
        if token.refresh_token:
            tokens_to_revoke.append(("refresh_token", token.refresh_token))

        success = False
        for token_type_hint, token_value in tokens_to_revoke:
            try:
                data: dict[str, Any] = {
                    "token": token_value,
                    "token_type_hint": token_type_hint,
                    "client_id": self.config.client_id,
                }
                if self.config.client_secret:
                    data["client_secret"] = self.config.client_secret

                response = self.http_client.post(
                    self.config.revoke_url,
                    data=data,
                )
                # RFC 7009: 200 OK even if token was already invalid
                if response.status_code == HTTPStatus.OK:
                    success = True
            except httpx.RequestError as e:
                logger.warning("Failed to revoke %s: %s", token_type_hint, e)

        if success:
            self.clear_token()
            logger.info("Token revoked for provider '%s'", self.name)

        return success

    # ─────────────────────────────────────────────────────────────────────────
    # UserInfo endpoint
    # ─────────────────────────────────────────────────────────────────────────

    def get_userinfo(self, token: Token | None = None) -> dict[str, Any]:
        """Fetch user information from the UserInfo endpoint.

        Requires `userinfo_url` to be configured in the provider config.

        Args:
            token: Token to use. Uses stored token if not provided.

        Returns:
            User claims from the UserInfo endpoint.

        Raises:
            ConfigurationError: If userinfo_url is not configured.
            AuthError: If request fails.

        Example:
            >>> provider = OAuth2Provider.from_config("github")  # doctest: +SKIP
            >>> userinfo = provider.get_userinfo()  # doctest: +SKIP
            >>> print(userinfo["login"])  # doctest: +SKIP
        """
        if not self.config.userinfo_url:
            msg = (
                f"Provider '{self.name}' does not have 'userinfo_url' configured. "
                "For OIDC providers, userinfo is auto-discovered. "
                "For OAuth2, you must configure 'userinfo_url' explicitly."
            )
            raise ConfigurationError(msg)

        if token is None:
            token = self.get_token()

        if token is None:
            msg = "No token available"
            raise AuthError(msg)

        try:
            headers = {"Authorization": f"Bearer {token.access_token}"}
            response = self.http_client.get(
                self.config.userinfo_url,
                headers=headers,
            )
            response.raise_for_status()
            result: dict[str, Any] = response.json()
            return result
        except httpx.HTTPStatusError as e:
            msg = f"UserInfo request failed: HTTP {e.response.status_code}"
            raise AuthError(msg) from e
        except httpx.RequestError as e:
            msg = f"UserInfo request failed: {e}"
            raise AuthError(msg) from e

    # ─────────────────────────────────────────────────────────────────────────
    # Preflight validation
    # ─────────────────────────────────────────────────────────────────────────

    def preflight(self) -> PreflightReport:
        """Run preflight validation checks.

        Returns:
            PreflightReport with validation results.
        """
        report = PreflightReport(provider_name=self.name)

        # Check 1: Configuration
        report.results.append(self._check_config())

        # Check 2: Authorization endpoint reachable
        report.results.append(self._check_endpoint("authorize", self.config.authorize_url))

        # Check 3: Token endpoint reachable
        report.results.append(self._check_endpoint("token", self.config.token_url))

        # Check 4: Revocation endpoint (optional)
        if self.config.revoke_url:
            report.results.append(self._check_endpoint("revoke", self.config.revoke_url))

        # Check 5: UserInfo endpoint (optional)
        if self.config.userinfo_url:
            report.results.append(self._check_endpoint("userinfo", self.config.userinfo_url))

        return report

    def _check_config(self) -> PreflightResult:
        """Validate provider configuration."""
        start = time.time()
        issues: list[str] = []

        if not self.config.client_id:
            issues.append("client_id is required")
        if not self.config.authorize_url:
            issues.append("authorize_url is required")
        if not self.config.token_url:
            issues.append("token_url is required")
        if not self.config.redirect_uri:
            issues.append("redirect_uri is required")

        duration = int((time.time() - start) * 1000)

        if issues:
            return PreflightResult(
                step="config",
                status=PreflightStatus.FAILURE,
                message=f"Configuration errors: {'; '.join(issues)}",
                details={"issues": issues},
                duration_ms=duration,
            )

        return PreflightResult(
            step="config",
            status=PreflightStatus.SUCCESS,
            message="Configuration valid",
            details={
                "client_id": self.config.client_id,
                "scopes": self.config.scopes,
            },
            duration_ms=duration,
        )

    def _check_endpoint(self, name: str, url: str | None) -> PreflightResult:
        """Check if an endpoint is reachable."""
        start = time.time()

        if not url:
            return PreflightResult(
                step=name,
                status=PreflightStatus.SKIPPED,
                message=f"{name} endpoint not configured",
                duration_ms=int((time.time() - start) * 1000),
            )

        try:
            # Just check if endpoint responds (HEAD or GET)
            response = self.http_client.head(url, follow_redirects=True)
            duration = int((time.time() - start) * 1000)

            # Accept any 2xx, 3xx, 4xx (4xx is expected without proper auth)
            if response.status_code < 500:
                return PreflightResult(
                    step=name,
                    status=PreflightStatus.SUCCESS,
                    message=f"{name} endpoint reachable",
                    details={"url": url, "status_code": response.status_code},
                    duration_ms=duration,
                )
            return PreflightResult(
                step=name,
                status=PreflightStatus.WARNING,
                message=f"{name} endpoint returned {response.status_code}",
                details={"url": url, "status_code": response.status_code},
                duration_ms=duration,
            )
        except httpx.RequestError as e:
            duration = int((time.time() - start) * 1000)
            return PreflightResult(
                step=name,
                status=PreflightStatus.FAILURE,
                message=f"{name} endpoint unreachable: {e}",
                details={"url": url, "error": str(e)},
                duration_ms=duration,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_error_response(self, response: httpx.Response) -> dict[str, str]:
        """Parse OAuth2 error response."""
        try:
            data = response.json()
            return {
                "error": str(data.get("error", "unknown")),
                "error_description": str(data.get("error_description", response.text)),
            }
        except Exception:  # pylint: disable=broad-exception-caught
            # Fallback for non-JSON error responses
            return {"error": "unknown", "error_description": response.text}

    def _get_trace_config(self) -> tuple[bool, int]:
        """Get trace configuration from kstlib config.

        Returns:
            Tuple of (pretty_print, max_body_length).
        """
        try:
            from kstlib.config import load_config

            cfg = load_config()
            # Box allows dot-notation access with defaults
            pretty: bool = cfg.auth.trace.pretty if cfg.auth.trace else _TRACE_PRETTY_DEFAULT
            max_body: int = cfg.auth.trace.max_body_length if cfg.auth.trace else _TRACE_MAX_BODY_DEFAULT
            # Defense in depth: enforce hard limit
            max_body = min(max_body, _TRACE_MAX_BODY_HARD_LIMIT)
            return pretty, max_body
        except Exception:  # pylint: disable=broad-exception-caught
            return _TRACE_PRETTY_DEFAULT, _TRACE_MAX_BODY_DEFAULT


__all__ = ["OAuth2Provider"]
