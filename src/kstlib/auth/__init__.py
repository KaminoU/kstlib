# pylint: disable=duplicate-code
"""OAuth2/OIDC authentication module for kstlib.

This module provides a config-driven authentication layer supporting:
- OAuth2 Authorization Code flow
- OIDC with PKCE extension
- Automatic token refresh
- Secure token storage (SOPS encrypted or memory)
- Preflight validation for IdP configuration

Example (explicit configuration):
    >>> from kstlib.auth import AuthSession, OIDCProvider, AuthProviderConfig  # doctest: +SKIP
    >>> from kstlib.auth import MemoryTokenStorage  # doctest: +SKIP
    >>>
    >>> config = AuthProviderConfig(  # doctest: +SKIP
    ...     client_id="my-app",
    ...     issuer="https://auth.example.com",
    ...     scopes=["openid", "profile"],
    ... )
    >>> provider = OIDCProvider("example", config, MemoryTokenStorage())  # doctest: +SKIP
    >>> with AuthSession(provider) as session:  # doctest: +SKIP
    ...     resp = session.get("https://api.example.com/users/me")

Example (config-driven):
    >>> # Configure in kstlib.conf.yml:
    >>> # auth:
    >>> #   providers:
    >>> #     corporate:
    >>> #       type: oidc
    >>> #       issuer: https://idp.corp.local/realms/main
    >>> #       client_id: my-app
    >>> #       pkce: true
    >>> from kstlib.auth import OIDCProvider, AuthSession
    >>> provider = OIDCProvider.from_config("corporate")  # doctest: +SKIP
    >>> with AuthSession(provider) as session:  # doctest: +SKIP
    ...     resp = session.get("https://api.corp.local/users/me")

See Also:
    - :mod:`kstlib.auth.config` for config loading helpers
    - :mod:`kstlib.auth.models` for data models
    - :mod:`kstlib.auth.errors` for exception hierarchy
    - :mod:`kstlib.auth.providers` for provider implementations
"""

from __future__ import annotations

from kstlib.auth.callback import CallbackResult, CallbackServer
from kstlib.auth.config import (
    build_provider_config,
    get_auth_config,
    get_callback_server_config,
    get_default_provider_name,
    get_provider_config,
    get_token_storage_from_config,
    list_configured_providers,
)
from kstlib.auth.errors import (
    AuthError,
    AuthorizationError,
    CallbackServerError,
    ConfigurationError,
    DiscoveryError,
    PreflightError,
    ProviderNotFoundError,
    TokenError,
    TokenExchangeError,
    TokenExpiredError,
    TokenRefreshError,
    TokenStorageError,
    TokenValidationError,
)
from kstlib.auth.models import (
    AuthFlow,
    PreflightReport,
    PreflightResult,
    PreflightStatus,
    Token,
    TokenType,
)
from kstlib.auth.providers import (
    AbstractAuthProvider,
    AuthProviderConfig,
    OAuth2Provider,
    OIDCProvider,
)
from kstlib.auth.session import AuthSession
from kstlib.auth.token import (
    AbstractTokenStorage,
    MemoryTokenStorage,
    SOPSTokenStorage,
    get_token_storage,
)

__all__ = [
    # Providers
    "AbstractAuthProvider",
    # Token storage
    "AbstractTokenStorage",
    # Errors
    "AuthError",
    # Models
    "AuthFlow",
    "AuthProviderConfig",
    # Session
    "AuthSession",
    "AuthorizationError",
    # Callback server
    "CallbackResult",
    "CallbackServer",
    "CallbackServerError",
    "ConfigurationError",
    "DiscoveryError",
    "MemoryTokenStorage",
    "OAuth2Provider",
    "OIDCProvider",
    "PreflightError",
    "PreflightReport",
    "PreflightResult",
    "PreflightStatus",
    "ProviderNotFoundError",
    "SOPSTokenStorage",
    "Token",
    "TokenError",
    "TokenExchangeError",
    "TokenExpiredError",
    "TokenRefreshError",
    "TokenStorageError",
    "TokenType",
    "TokenValidationError",
    # Config helpers
    "build_provider_config",
    "get_auth_config",
    "get_callback_server_config",
    "get_default_provider_name",
    "get_provider_config",
    "get_token_storage",
    "get_token_storage_from_config",
    "list_configured_providers",
]
