"""Authentication module exceptions."""

from __future__ import annotations

from typing import Any

from kstlib.config.exceptions import KstlibError


class AuthError(KstlibError):
    """Base exception for all authentication errors."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        """Initialize the auth error with a message and optional structured details."""
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConfigurationError(AuthError):
    """Raised when auth configuration is invalid or missing."""


class ProviderNotFoundError(AuthError):
    """Raised when a named provider is not configured."""

    def __init__(self, provider_name: str) -> None:
        """Initialize with the name of the missing provider."""
        super().__init__(f"Provider '{provider_name}' not found in configuration")
        self.provider_name = provider_name


class DiscoveryError(AuthError):
    """Raised when OIDC discovery fails.

    ``status_code`` encodes whether the provider answered the discovery
    request, so consumers can distinguish "the provider answered an error
    status" from "the provider could not be reached" without parsing
    ``reason``:

    - ``status_code is not None``: the provider was reached and answered
      this HTTP error status to the discovery request.
    - ``status_code is None``: transport-level failure (DNS resolution,
      connection refused, timeout): no HTTP response was received.

    Attributes:
        issuer: Issuer URL whose discovery document could not be fetched.
        reason: Human-readable description of the failure.
        status_code: HTTP status answered by the provider, or ``None`` when
            no HTTP response was received.

    Examples:
        >>> err = DiscoveryError("https://idp.example.com", "HTTP 502", status_code=502)
        >>> err.status_code
        502
        >>> unreachable = DiscoveryError("https://idp.example.com", "connection refused")
        >>> unreachable.status_code is None
        True

    """

    def __init__(self, issuer: str, reason: str, *, status_code: int | None = None) -> None:
        """Initialize with the failing issuer URL, the failure reason and the HTTP status.

        Args:
            issuer: Issuer URL whose discovery document could not be fetched.
            reason: Human-readable description of the failure.
            status_code: HTTP status answered by the provider. ``None``
                (default) when no HTTP response was received.

        """
        super().__init__(f"Discovery failed for '{issuer}': {reason}")
        self.issuer = issuer
        self.reason = reason
        self.status_code = status_code


class TokenError(AuthError):
    """Base exception for token-related errors."""


class TokenExpiredError(TokenError):
    """Raised when a token has expired and cannot be refreshed."""


class TokenRefreshError(TokenError):
    """Raised when token refresh fails.

    Attributes:
        reason: Human-readable description of the refresh failure.
        retryable: ``True`` when retrying the refresh may succeed (transport
            failure or provider 5xx answer). ``False`` when the rejection is
            definitive (provider 4xx: invalid, expired or revoked refresh
            token, or a misconfigured token endpoint). Same semantics as
            :attr:`TokenExchangeError.retryable`.

    """

    def __init__(self, reason: str, *, retryable: bool = False) -> None:
        """Initialize with the reason for the refresh failure and a retryable flag."""
        super().__init__(f"Token refresh failed: {reason}")
        self.reason = reason
        self.retryable = retryable


class TokenExchangeError(TokenError):
    """Raised when authorization code exchange fails.

    The attributes encode where the exchange failed, so consumers can
    distinguish "the provider answered an error" from "the provider could
    not be reached" without parsing messages:

    - ``status_code is not None``: the provider was reached and answered
      this HTTP error status. ``error_code`` is then guaranteed non-None:
      the OAuth2 ``error`` code from the response body, or ``"unknown"``
      when the body is missing or unreadable.
    - ``status_code is None`` and ``error_code is None``: transport-level
      failure (DNS resolution, connection refused, timeout): no HTTP
      response was received from the provider.
    - ``status_code is None`` and ``error_code is not None``: a local
      pre-network guard rejected the exchange before any request was sent.
      Guard codes: ``"state_mismatch"`` (CSRF state validation failed) and
      ``"pkce_missing"`` (PKCE enabled but no code verifier available).

    Attributes:
        reason: Human-readable description of the exchange failure.
        error_code: OAuth2 error code answered by the provider (``"unknown"``
            when the error body is unreadable), one of the local guard codes
            listed above, or ``None`` for transport-level failures.
        status_code: HTTP status answered by the provider, or ``None`` when
            no HTTP response was received (transport failure or local guard).
        retryable: ``True`` when retrying the same exchange may succeed
            (transport failure or provider 5xx answer). ``False`` when the
            rejection is definitive: provider 4xx (authorization codes are
            single-use) or local guard (restart the authorization flow
            instead). Same semantics as :attr:`TokenRefreshError.retryable`.

    Examples:
        >>> rejected = TokenExchangeError("Rejected", error_code="not_allowed", status_code=400)
        >>> rejected.status_code is not None  # the provider answered
        True
        >>> rejected.retryable
        False
        >>> transport = TokenExchangeError("Network error: timeout", retryable=True)
        >>> transport.status_code is None and transport.error_code is None
        True

    """

    def __init__(
        self,
        reason: str,
        *,
        error_code: str | None = None,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        """Initialize with the exchange failure reason and its structured discriminants.

        Args:
            reason: Human-readable description of the exchange failure.
            error_code: OAuth2 error code from the provider response body, or
                a local guard code. ``None`` (default) for transport failures.
            status_code: HTTP status answered by the provider. ``None``
                (default) when no HTTP response was received.
            retryable: Whether retrying the same exchange may succeed.

        """
        super().__init__(f"Token exchange failed: {reason}")
        self.reason = reason
        self.error_code = error_code
        self.status_code = status_code
        self.retryable = retryable


class TokenValidationError(TokenError):
    """Raised when JWT validation fails (signature, claims, expiry)."""

    def __init__(self, reason: str, *, claim: str | None = None) -> None:
        """Initialize with the reason for the validation failure and the offending claim name."""
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
        """Initialize with the reason for the failure plus optional OAuth error code and description."""
        super().__init__(f"Authorization failed: {reason}")
        self.reason = reason
        self.error_code = error_code
        self.error_description = error_description


class CallbackServerError(AuthError):
    """Raised when the local callback server fails to start or receive callback."""

    def __init__(self, reason: str, *, port: int | None = None) -> None:
        """Initialize with the reason for the callback server failure and the port that was in use."""
        super().__init__(f"Callback server error: {reason}")
        self.reason = reason
        self.port = port


class PreflightError(AuthError):
    """Raised when preflight validation fails."""

    def __init__(self, step: str, reason: str) -> None:
        """Initialize with the failing preflight step name and the reason for the failure."""
        super().__init__(f"Preflight failed at '{step}': {reason}")
        self.step = step
        self.reason = reason


class AuthExpiredError(AuthError):
    """Raised when an authenticated request returns HTTP 401 indicating token expiration.

    Surfaced by ``kstlib.rapi.client`` (and any other consumer) when a
    server response signals that the previously-valid access token has
    expired or been invalidated during the session. The user must
    re-authenticate via the appropriate channel (for example,
    ``sas-admin auth login`` for Viya, or via a dedicated OAuth client
    when configured in :mod:`kstlib.auth`).

    Note:
        Distinct from :class:`TokenExpiredError`. The two cover
        different lifecycle points and originate from different
        sub-systems :

        - ``AuthExpiredError`` (this class, inherits from
          :class:`AuthError`) is raised by ``kstlib.rapi.client`` when
          the server returns HTTP 401 at runtime, signalling that a
          token which was valid at send time has been expired or
          invalidated by the identity provider during the session.

        - :class:`TokenExpiredError` (inherits from :class:`TokenError`)
          is raised by ``kstlib.auth`` when a loaded token is detected
          as already expired before the request is sent (client-side
          pre-flight check).

    Attributes:
        token_source: Optional label identifying where the token was
            loaded from (for example, ``'~/.sas/credentials.json'``,
            ``'env:KSTLIB_TOKEN'``, ``'sops:secrets/api.sops.json'``).
            ``None`` when the source is unknown.
        suggested_action: Optional human-readable hint guiding the
            user toward a successful re-authentication (for example,
            ``'Run: sas-admin auth login -u <user>'``). ``None`` when
            no contextual hint is available.

    Examples:
        >>> err = AuthExpiredError(
        ...     "Access token expired (HTTP 401).",
        ...     token_source="~/.sas/credentials.json",
        ...     suggested_action="Run: sas-admin auth login -u <user>",
        ... )
        >>> err.token_source
        '~/.sas/credentials.json'
        >>> isinstance(err, AuthError)
        True

    """

    def __init__(
        self,
        message: str,
        *,
        token_source: str | None = None,
        suggested_action: str | None = None,
    ) -> None:
        """Initialize AuthExpiredError.

        Args:
            message: Human-readable description of the expiration
                (typically including the HTTP status and a short
                rationale, never the raw token or response body).
            token_source: Optional label for where the token came from
                (used by callers to surface a contextual hint without
                exposing the secret material itself).
            suggested_action: Optional hint pointing the user to the
                right re-authentication procedure.

        """
        super().__init__(
            message,
            details={
                "token_source": token_source,
                "suggested_action": suggested_action,
            },
        )
        self.token_source = token_source
        self.suggested_action = suggested_action


__all__ = [
    "AuthError",
    "AuthExpiredError",
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
