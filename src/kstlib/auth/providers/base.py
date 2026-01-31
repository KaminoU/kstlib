"""Abstract base class for authentication providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from typing_extensions import Self

from kstlib.logging import TRACE_LEVEL, get_logger
from kstlib.ssl import validate_ca_bundle_path, validate_ssl_verify

if TYPE_CHECKING:
    import types

    from kstlib.auth.models import AuthFlow, PreflightReport, Token
    from kstlib.auth.token import AbstractTokenStorage

logger = get_logger(__name__)


@dataclass
class AuthProviderConfig:  # pylint: disable=too-many-instance-attributes
    """Configuration for an authentication provider.

    Supports three modes:

    1. **Auto discovery** (OIDC): Only ``issuer`` provided, endpoints discovered via
       ``.well-known/openid-configuration``.

    2. **Hybrid mode** (OIDC): ``issuer`` + some explicit endpoints. Discovery fills
       missing endpoints, explicit ones take precedence.

    3. **Full manual** (OAuth2/OIDC): No ``issuer``, all endpoints explicit.
       No discovery attempted.

    Attributes:
        client_id: OAuth2 client identifier.
        client_secret: Optional client secret (not needed for public clients with PKCE).
        authorize_url: Authorization endpoint URL.
        token_url: Token endpoint URL.
        revoke_url: Optional token revocation endpoint.
        userinfo_url: Optional UserInfo endpoint URL.
        jwks_uri: JWKS endpoint for ID token signature verification.
        end_session_endpoint: Logout/end session endpoint.
        issuer: OIDC issuer URL (enables discovery).
        scopes: List of OAuth2 scopes to request.
        redirect_uri: Callback URI for authorization code flow.
        pkce: Enable PKCE extension (default True for OIDC).
        discovery_ttl: Cache TTL for OIDC discovery document (seconds).
        headers: Custom HTTP headers to send with all IDP requests.
        ssl_verify: Enable SSL certificate verification (default True).
            Set to False only for development with self-signed certificates.
        ssl_ca_bundle: Path to custom CA bundle file for corporate PKI.
            If provided, ssl_verify is implicitly True.
        extra: Additional provider-specific configuration.

    Example:
        Auto discovery (Keycloak, Auth0, etc.)::

            AuthProviderConfig(
                client_id="my-app",
                issuer="http://localhost:8080/realms/test",
            )

        Hybrid mode (discovery + override)::

            AuthProviderConfig(
                client_id="my-app",
                issuer="https://idp.corp.local",
                end_session_endpoint="https://idp.corp.local/custom/logout",  # Override
            )

        Full manual (legacy IDP without discovery)::

            AuthProviderConfig(
                client_id="my-app",
                authorize_url="https://old-idp.local/auth",
                token_url="https://old-idp.local/token",
                jwks_uri="https://old-idp.local/certs",
            )
    """

    client_id: str
    client_secret: str | None = None
    authorize_url: str | None = None
    token_url: str | None = None
    revoke_url: str | None = None
    userinfo_url: str | None = None
    jwks_uri: str | None = None
    end_session_endpoint: str | None = None
    issuer: str | None = None
    scopes: list[str] = field(default_factory=lambda: ["openid"])
    redirect_uri: str = "http://127.0.0.1:8400/callback"
    pkce: bool = True
    discovery_ttl: int = 3600
    headers: dict[str, str] = field(default_factory=dict)
    ssl_verify: bool = True
    ssl_ca_bundle: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate configuration."""
        if not self.issuer and not (self.authorize_url and self.token_url):
            msg = "Either 'issuer' (OIDC with discovery) or both 'authorize_url' and 'token_url' (manual) required"
            raise ValueError(msg)

        # SSL/TLS validation (delegated to kstlib.ssl for DRY)
        validate_ssl_verify(self.ssl_verify)

        if self.ssl_ca_bundle is not None:
            validated_path = validate_ca_bundle_path(self.ssl_ca_bundle)
            object.__setattr__(self, "ssl_ca_bundle", validated_path)

    @property
    def has_explicit_endpoints(self) -> bool:
        """Check if any endpoints are explicitly configured."""
        return any(
            [
                self.authorize_url,
                self.token_url,
                self.userinfo_url,
                self.jwks_uri,
                self.end_session_endpoint,
                self.revoke_url,
            ]
        )


class AbstractAuthProvider(ABC):
    """Abstract base class for OAuth2/OIDC authentication providers.

    Subclasses must implement the abstract methods to handle the specific
    authentication flow (OAuth2, OIDC, etc.).

    Attributes:
        name: Provider identifier (matches config key).
        config: Provider configuration.
        token_storage: Storage backend for tokens.
    """

    def __init__(
        self,
        name: str,
        config: AuthProviderConfig,
        token_storage: AbstractTokenStorage,
    ) -> None:
        """Initialize the provider.

        Args:
            name: Provider identifier.
            config: Provider configuration.
            token_storage: Token storage backend.
        """
        self.name = name
        self.config = config
        self.token_storage = token_storage
        self._current_token: Token | None = None

    # ─────────────────────────────────────────────────────────────────────────
    # Properties
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def is_authenticated(self) -> bool:
        """Check if a valid (non-expired) token is available."""
        token = self.get_token(auto_refresh=False)
        return token is not None and not token.is_expired

    @property
    @abstractmethod
    def flow(self) -> AuthFlow:
        """Return the OAuth2 flow used by this provider."""

    # ─────────────────────────────────────────────────────────────────────────
    # Authorization flow (abstract)
    # ─────────────────────────────────────────────────────────────────────────

    @abstractmethod
    def get_authorization_url(self, state: str | None = None) -> tuple[str, str]:
        """Generate the authorization URL for the user to visit.

        Args:
            state: Optional state parameter. Generated if not provided.

        Returns:
            Tuple of (authorization_url, state).
        """

    @abstractmethod
    def exchange_code(
        self,
        code: str,
        state: str,
        *,
        code_verifier: str | None = None,
    ) -> Token:
        """Exchange an authorization code for tokens.

        Args:
            code: Authorization code from callback.
            state: State parameter for CSRF validation.
            code_verifier: PKCE code verifier (required if PKCE was used).

        Returns:
            Token object with access_token, refresh_token, etc.

        Raises:
            TokenExchangeError: If the exchange fails.
        """

    @abstractmethod
    def refresh(self, token: Token | None = None) -> Token:
        """Refresh an expired token.

        Args:
            token: Token to refresh. Uses stored token if not provided.

        Returns:
            New Token object.

        Raises:
            TokenRefreshError: If refresh fails or no refresh_token available.
        """

    @abstractmethod
    def revoke(self, token: Token | None = None) -> bool:
        """Revoke a token at the authorization server.

        Args:
            token: Token to revoke. Uses stored token if not provided.

        Returns:
            True if revoked successfully, False if revocation not supported.
        """

    # ─────────────────────────────────────────────────────────────────────────
    # Token management
    # ─────────────────────────────────────────────────────────────────────────

    def get_token(self, *, auto_refresh: bool = True) -> Token | None:
        """Get the current token, optionally refreshing if expired.

        Args:
            auto_refresh: If True and token is expired, attempt refresh.

        Returns:
            Token if available, None otherwise.
        """
        if self._current_token is None:
            if logger.isEnabledFor(TRACE_LEVEL):
                logger.log(TRACE_LEVEL, "[AUTH] Loading token from storage for '%s'", self.name)
            self._current_token = self.token_storage.load(self.name)

        if self._current_token is None:
            if logger.isEnabledFor(TRACE_LEVEL):
                logger.log(TRACE_LEVEL, "[AUTH] No token found for '%s'", self.name)
            return None

        if self._current_token.should_refresh and auto_refresh:
            if self._current_token.is_refreshable:
                if logger.isEnabledFor(TRACE_LEVEL):
                    logger.log(TRACE_LEVEL, "[AUTH] Token needs refresh for '%s'", self.name)
                try:
                    self._current_token = self.refresh(self._current_token)
                    self.token_storage.save(self.name, self._current_token)
                    if logger.isEnabledFor(TRACE_LEVEL):
                        logger.log(TRACE_LEVEL, "[AUTH] Token refreshed successfully for '%s'", self.name)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    # Best-effort refresh, return potentially expired token
                    # Clean warning for user, full traceback in DEBUG only
                    logger.warning(
                        "Token refresh failed for '%s': %s. Using cached token.",
                        self.name,
                        e,
                    )
                    logger.debug("Token refresh traceback:", exc_info=True)
            else:
                logger.debug("Token expired and not refreshable for provider '%s'", self.name)

        return self._current_token

    def save_token(self, token: Token) -> None:
        """Save a token to storage.

        Args:
            token: Token to save.
        """
        self._current_token = token
        self.token_storage.save(self.name, token)

    def clear_token(self) -> None:
        """Clear the current token from memory and storage."""
        self._current_token = None
        self.token_storage.delete(self.name)

    # ─────────────────────────────────────────────────────────────────────────
    # Preflight validation
    # ─────────────────────────────────────────────────────────────────────────

    @abstractmethod
    def preflight(self) -> PreflightReport:
        """Run preflight validation checks.

        Returns:
            PreflightReport with results for each validation step.
        """

    # ─────────────────────────────────────────────────────────────────────────
    # Context manager support
    # ─────────────────────────────────────────────────────────────────────────

    def __enter__(self) -> Self:
        """Enter context manager."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Exit context manager - clear sensitive data from memory."""
        self._current_token = None


# ─────────────────────────────────────────────────────────────────────────────
# Helper for from_config factory pattern
# ─────────────────────────────────────────────────────────────────────────────


def load_provider_from_config(
    provider_name: str,
    allowed_types: tuple[str, ...],
    type_label: str,
    config: dict[str, Any] | None = None,
    **overrides: Any,
) -> tuple[AuthProviderConfig, AbstractTokenStorage]:
    """Load provider configuration and token storage from config file.

    This helper factorizes the common logic for OAuth2Provider.from_config()
    and OIDCProvider.from_config().

    Args:
        provider_name: Name of the provider in config.
        allowed_types: Tuple of allowed provider type strings (e.g., ("oidc", "openid")).
        type_label: Human-readable type label for error messages (e.g., "oidc").
        config: Optional explicit config dict.
        **overrides: Direct overrides for provider config.

    Returns:
        Tuple of (AuthProviderConfig, AbstractTokenStorage).

    Raises:
        ConfigurationError: If provider not found or type mismatch.
    """
    from kstlib.auth.config import (
        build_provider_config,
        get_provider_config,
        get_token_storage_from_config,
    )
    from kstlib.auth.errors import ConfigurationError

    # Validate provider exists
    provider_cfg = get_provider_config(provider_name, config=config)
    if provider_cfg is None:
        msg = f"Provider '{provider_name}' not found in auth.providers config"
        raise ConfigurationError(msg)

    # Verify provider type matches
    provider_type = provider_cfg.get("type", allowed_types[0]).lower()
    if provider_type not in allowed_types:
        msg = f"Provider '{provider_name}' has type '{provider_type}', expected '{type_label}'"
        raise ConfigurationError(msg)

    # Build AuthProviderConfig
    auth_config = build_provider_config(provider_name, config=config, **overrides)

    # Get token storage
    token_storage = get_token_storage_from_config(
        provider_name=provider_name,
        config=config,
    )

    return auth_config, token_storage


__all__ = [
    "AbstractAuthProvider",
    "AuthProviderConfig",
    "load_provider_from_config",
]
