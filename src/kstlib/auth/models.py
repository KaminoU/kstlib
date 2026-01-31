"""Data models for the authentication module."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any


class AuthFlow(str, Enum):
    """OAuth2/OIDC authentication flows supported by the module.

    Attributes:
        AUTHORIZATION_CODE: Standard OAuth2 Authorization Code flow.
        AUTHORIZATION_CODE_PKCE: Authorization Code with PKCE extension (recommended).
        CLIENT_CREDENTIALS: Machine-to-machine authentication (no user interaction).
        DEVICE_CODE: For devices with limited input capabilities.
        REFRESH_TOKEN: Token refresh flow (internal use).
    """

    AUTHORIZATION_CODE = "authorization_code"
    AUTHORIZATION_CODE_PKCE = "authorization_code_pkce"
    CLIENT_CREDENTIALS = "client_credentials"
    DEVICE_CODE = "device_code"
    REFRESH_TOKEN = "refresh_token"


class TokenType(str, Enum):
    """Token type as returned by the authorization server."""

    BEARER = "Bearer"
    MAC = "MAC"
    DPOP = "DPoP"


class PreflightStatus(str, Enum):
    """Status of a preflight validation step."""

    SUCCESS = "success"
    FAILURE = "failure"
    WARNING = "warning"
    SKIPPED = "skipped"


@dataclass(slots=True)
class Token:  # pylint: disable=too-many-instance-attributes
    """Represents an OAuth2/OIDC token set.

    Attributes:
        access_token: The access token issued by the authorization server.
        token_type: Token type (usually "Bearer").
        expires_at: Absolute expiration time (UTC). None if unknown.
        refresh_token: Optional refresh token for obtaining new access tokens.
        scope: List of granted scopes.
        id_token: OIDC ID token (JWT) containing user claims. None for pure OAuth2.
        issued_at: When the token was issued (UTC).
        metadata: Additional provider-specific data.

    Example:
        >>> from datetime import datetime, timezone
        >>> token = Token(
        ...     access_token="eyJhbGc...",
        ...     expires_at=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        ...     refresh_token="dGhpcyBpcyBh...",
        ...     scope=["openid", "profile"],
        ... )
        >>> token.is_expired
        True
        >>> token.is_refreshable
        True
    """

    access_token: str
    token_type: TokenType | str = TokenType.BEARER
    expires_at: datetime | None = None
    refresh_token: str | None = None
    scope: list[str] = field(default_factory=list)
    id_token: str | None = None
    issued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """Check if the access token has expired.

        Returns:
            True if expired or expiration is unknown and token is old (>1h).
        """
        if self.expires_at is None:
            # Conservative: assume expired after 1 hour if no expiry info
            return datetime.now(timezone.utc) > self.issued_at + timedelta(hours=1)
        return datetime.now(timezone.utc) >= self.expires_at

    @property
    def is_refreshable(self) -> bool:
        """Check if the token can be refreshed.

        Returns:
            True if a refresh_token is available.
        """
        return self.refresh_token is not None

    @property
    def expires_in(self) -> int | None:
        """Seconds until expiration. None if unknown, negative if expired."""
        if self.expires_at is None:
            return None
        delta = self.expires_at - datetime.now(timezone.utc)
        return int(delta.total_seconds())

    @property
    def should_refresh(self) -> bool:
        """Check if the token should be proactively refreshed.

        Returns:
            True if token expires within 60 seconds or is already expired.
        """
        if self.expires_at is None:
            return self.is_expired
        # Refresh 60 seconds before actual expiry
        buffer = timedelta(seconds=60)
        return datetime.now(timezone.utc) >= (self.expires_at - buffer)

    @classmethod
    def from_response(cls, data: dict[str, Any]) -> Token:
        """Create a Token from an OAuth2 token response.

        Args:
            data: Raw token response from the authorization server.

        Returns:
            Token instance populated from the response.

        Example:
            >>> response = {
            ...     "access_token": "eyJhbGc...",
            ...     "token_type": "Bearer",
            ...     "expires_in": 3600,
            ...     "refresh_token": "dGhpcyBpcyBh...",
            ...     "scope": "openid profile",
            ...     "id_token": "eyJhbGc...",
            ... }
            >>> token = Token.from_response(response)
            >>> token.scope
            ['openid', 'profile']
        """
        now = datetime.now(timezone.utc)

        # Parse expires_at from expires_in
        expires_at = None
        if "expires_in" in data:
            expires_at = now + timedelta(seconds=int(data["expires_in"]))
        elif "expires_at" in data:
            # Some servers return absolute timestamp
            expires_at = datetime.fromtimestamp(data["expires_at"], tz=timezone.utc)

        # Parse scope (can be string or list)
        scope_raw = data.get("scope", [])
        scope = (scope_raw.split() if scope_raw else []) if isinstance(scope_raw, str) else list(scope_raw)

        # Extract known fields, rest goes to metadata
        known_fields = {
            "access_token",
            "token_type",
            "expires_in",
            "expires_at",
            "refresh_token",
            "scope",
            "id_token",
        }
        metadata = {k: v for k, v in data.items() if k not in known_fields}

        return cls(
            access_token=data["access_token"],
            token_type=data.get("token_type", TokenType.BEARER),
            expires_at=expires_at,
            refresh_token=data.get("refresh_token"),
            scope=scope,
            id_token=data.get("id_token"),
            issued_at=now,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize token to dictionary for storage.

        Returns:
            Dictionary representation suitable for JSON serialization.
        """
        return {
            "access_token": self.access_token,
            "token_type": str(self.token_type.value if isinstance(self.token_type, TokenType) else self.token_type),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "refresh_token": self.refresh_token,
            "scope": self.scope,
            "id_token": self.id_token,
            "issued_at": self.issued_at.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Token:
        """Deserialize token from dictionary (storage retrieval).

        Args:
            data: Dictionary from to_dict() or storage.

        Returns:
            Token instance.
        """
        expires_at = None
        if data.get("expires_at"):
            expires_at = datetime.fromisoformat(data["expires_at"])

        issued_at = datetime.now(timezone.utc)
        if data.get("issued_at"):
            issued_at = datetime.fromisoformat(data["issued_at"])

        return cls(
            access_token=data["access_token"],
            token_type=data.get("token_type", TokenType.BEARER),
            expires_at=expires_at,
            refresh_token=data.get("refresh_token"),
            scope=data.get("scope", []),
            id_token=data.get("id_token"),
            issued_at=issued_at,
            metadata=data.get("metadata", {}),
        )


@dataclass(slots=True)
class PreflightResult:
    """Result of a single preflight validation step.

    Attributes:
        step: Name/identifier of the validation step.
        status: Outcome of the step (success, failure, warning, skipped).
        message: Human-readable description of the result.
        details: Optional additional information (URLs checked, errors, etc.).
        duration_ms: Time taken for this step in milliseconds.

    Example:
        >>> result = PreflightResult(
        ...     step="discovery",
        ...     status=PreflightStatus.SUCCESS,
        ...     message="Discovery document fetched successfully",
        ...     details={"issuer": "https://idp.example.com", "endpoints": 5},
        ...     duration_ms=234,
        ... )
        >>> result.success
        True
    """

    step: str
    status: PreflightStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    duration_ms: int | None = None

    @property
    def success(self) -> bool:
        """Check if step passed (success or warning)."""
        return self.status in (PreflightStatus.SUCCESS, PreflightStatus.WARNING)

    @property
    def failed(self) -> bool:
        """Check if step failed."""
        return self.status == PreflightStatus.FAILURE


@dataclass(slots=True)
class PreflightReport:
    """Aggregated results from a complete preflight check.

    Attributes:
        provider_name: Name of the provider being validated.
        results: List of individual step results.
        started_at: When the preflight started.
        completed_at: When the preflight finished.
    """

    provider_name: str
    results: list[PreflightResult] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    @property
    def success(self) -> bool:
        """Check if all steps passed (no failures)."""
        return all(not r.failed for r in self.results)

    @property
    def total_duration_ms(self) -> int:
        """Total time for all steps in milliseconds."""
        return sum(r.duration_ms or 0 for r in self.results)

    @property
    def failed_steps(self) -> list[PreflightResult]:
        """List of failed steps."""
        return [r for r in self.results if r.failed]

    @property
    def warnings(self) -> list[PreflightResult]:
        """List of steps with warnings."""
        return [r for r in self.results if r.status == PreflightStatus.WARNING]


__all__ = [
    "AuthFlow",
    "PreflightReport",
    "PreflightResult",
    "PreflightStatus",
    "Token",
    "TokenType",
]
