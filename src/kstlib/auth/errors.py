"""Authentication module exceptions."""

from __future__ import annotations

from typing import Any

from kstlib.config.exceptions import KstlibError


class AuthError(KstlibError):
    """Base exception for all authentication errors."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConfigurationError(AuthError):
    """Raised when auth configuration is invalid or missing."""


class ProviderNotFoundError(AuthError):
    """Raised when a named provider is not configured."""

    def __init__(self, provider_name: str) -> None:
        super().__init__(f"Provider '{provider_name}' not found in configuration")
        self.provider_name = provider_name


class DiscoveryError(AuthError):
    """Raised when OIDC discovery fails."""

    def __init__(self, issuer: str, reason: str) -> None:
        super().__init__(f"Discovery failed for '{issuer}': {reason}")
        self.issuer = issuer
        self.reason = reason


class TokenError(AuthError):
    """Base exception for token-related errors."""


class TokenExpiredError(TokenError):
    """Raised when a token has expired and cannot be refreshed."""


class TokenRefreshError(TokenError):
    """Raised when token refresh fails."""

    def __init__(self, reason: str, *, retryable: bool = False) -> None:
        super().__init__(f"Token refresh failed: {reason}")
        self.reason = reason
        self.retryable = retryable


class TokenExchangeError(TokenError):
    """Raised when authorization code exchange fails."""

    def __init__(self, reason: str, *, error_code: str | None = None) -> None:
        super().__init__(f"Token exchange failed: {reason}")
        self.reason = reason
        self.error_code = error_code


class TokenValidationError(TokenError):
    """Raised when JWT validation fails (signature, claims, expiry)."""

    def __init__(self, reason: str, *, claim: str | None = None) -> None:
        super().__init__(f"Token validation failed: {reason}")
        self.reason = reason
        self.claim = claim


class TokenStorageError(TokenError):
    """Raised when token persistence fails (save/load/delete)."""


class AuthorizationError(AuthError):
    """Raised during authorization flow failures."""

    def __init__(
        self,
        reason: str,
        *,
        error_code: str | None = None,
        error_description: str | None = None,
    ) -> None:
        super().__init__(f"Authorization failed: {reason}")
        self.reason = reason
        self.error_code = error_code
        self.error_description = error_description


class CallbackServerError(AuthError):
    """Raised when the local callback server fails to start or receive callback."""

    def __init__(self, reason: str, *, port: int | None = None) -> None:
        super().__init__(f"Callback server error: {reason}")
        self.reason = reason
        self.port = port


class PreflightError(AuthError):
    """Raised when preflight validation fails."""

    def __init__(self, step: str, reason: str) -> None:
        super().__init__(f"Preflight failed at '{step}': {reason}")
        self.step = step
        self.reason = reason


__all__ = [
    "AuthError",
    "AuthorizationError",
    "CallbackServerError",
    "ConfigurationError",
    "DiscoveryError",
    "PreflightError",
    "ProviderNotFoundError",
    "TokenError",
    "TokenExchangeError",
    "TokenExpiredError",
    "TokenRefreshError",
    "TokenStorageError",
    "TokenValidationError",
]
