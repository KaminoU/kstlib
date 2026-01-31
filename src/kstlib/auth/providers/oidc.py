"""OIDC provider with PKCE support and automatic discovery."""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import httpx

from kstlib.auth.errors import (
    ConfigurationError,
    DiscoveryError,
    TokenExchangeError,
    TokenValidationError,
)
from kstlib.auth.models import (
    AuthFlow,
    PreflightReport,
    PreflightResult,
    PreflightStatus,
    Token,
)
from kstlib.auth.providers.base import load_provider_from_config
from kstlib.auth.providers.oauth2 import OAuth2Provider
from kstlib.logging import TRACE_LEVEL, get_logger

if TYPE_CHECKING:
    from kstlib.auth.providers.base import AuthProviderConfig
    from kstlib.auth.token import AbstractTokenStorage

logger = get_logger(__name__)


class OIDCProvider(OAuth2Provider):
    """OpenID Connect provider with PKCE and automatic discovery.

    Extends OAuth2Provider with:
    - Automatic discovery of endpoints via .well-known/openid-configuration
    - PKCE (Proof Key for Code Exchange) for enhanced security
    - ID token validation (signature, claims)
    - UserInfo endpoint support

    Example:
        >>> from kstlib.auth.providers import OIDCProvider, AuthProviderConfig  # doctest: +SKIP
        >>> from kstlib.auth.token import MemoryTokenStorage  # doctest: +SKIP
        >>>
        >>> config = AuthProviderConfig(  # doctest: +SKIP
        ...     client_id="my-app",
        ...     issuer="https://auth.example.com",
        ...     scopes=["openid", "profile", "email"],
        ...     pkce=True,  # Enabled by default
        ... )
        >>> provider = OIDCProvider("example", config, MemoryTokenStorage())  # doctest: +SKIP
        >>> url, state = provider.get_authorization_url()  # doctest: +SKIP
        >>> # User authenticates, provider.exchange_code() handles PKCE automatically

    Config-driven usage:
        >>> # Configure in kstlib.conf.yml:
        >>> # auth:
        >>> #   providers:
        >>> #     corporate:
        >>> #       type: oidc
        >>> #       issuer: https://idp.corp.local/realms/main
        >>> #       client_id: my-app
        >>> #       scopes: [openid, profile, email]
        >>> #       pkce: true
        >>> provider = OIDCProvider.from_config("corporate")  # doctest: +SKIP
    """

    @classmethod
    def from_config(
        cls,
        provider_name: str,
        *,
        config: dict[str, Any] | None = None,
        http_client: httpx.Client | None = None,
        **overrides: Any,
    ) -> OIDCProvider:
        """Create an OIDCProvider from configuration.

        Loads provider settings from kstlib.conf.yml (auth.providers section)
        and creates a fully configured provider instance.

        Args:
            provider_name: Name of the provider in config (e.g., "corporate").
            config: Optional explicit config dict (overrides global config).
            http_client: Optional custom HTTP client.
            **overrides: Direct parameter overrides (highest priority).

        Returns:
            Configured OIDCProvider instance.

        Raises:
            ConfigurationError: If provider not found or required fields missing.

        Example:
            >>> provider = OIDCProvider.from_config("corporate")  # doctest: +SKIP
            >>> provider = OIDCProvider.from_config(
            ...     "corporate",
            ...     client_id="override-id",  # Override config value
            ... )  # doctest: +SKIP
        """
        auth_config, token_storage = load_provider_from_config(
            provider_name,
            allowed_types=("oidc", "openid", "openidconnect"),
            type_label="oidc",
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
        """Initialize OIDC provider.

        Supports three configuration modes:

        1. **Auto discovery**: Only ``issuer`` provided. Endpoints discovered via
           ``.well-known/openid-configuration``.

        2. **Hybrid mode**: ``issuer`` + some explicit endpoints. Discovery fills
           missing endpoints, explicit ones take precedence (useful for buggy IDPs).

        3. **Full manual**: No ``issuer``, all required endpoints explicit.
           No discovery attempted (for IDPs without discovery support).

        Args:
            name: Provider identifier.
            config: Provider configuration.
            token_storage: Token storage backend.
            http_client: Optional custom HTTP client.

        Raises:
            ConfigurationError: If configuration is invalid.
        """
        # Track which endpoints were explicitly configured (before any modification)
        endpoint_map = [
            ("authorize_url", "authorization_endpoint"),
            ("token_url", "token_endpoint"),
            ("userinfo_url", "userinfo_endpoint"),
            ("jwks_uri", "jwks_uri"),
            ("end_session_endpoint", "end_session_endpoint"),
            ("revoke_url", "revocation_endpoint"),
        ]
        self._explicit_endpoints: dict[str, str] = {
            discovery_key: getattr(config, attr) for attr, discovery_key in endpoint_map if getattr(config, attr)
        }

        # Determine discovery mode
        self._discovery_enabled = config.issuer is not None

        # For auto-discovery mode, set temporary placeholders ONLY if no explicit endpoints
        # These will be replaced by discovery
        if self._discovery_enabled:
            issuer = config.issuer
            assert issuer is not None  # Guaranteed by _discovery_enabled check
            if not config.authorize_url:
                config.authorize_url = f"{issuer.rstrip('/')}/authorize"  # Placeholder
            if not config.token_url:
                config.token_url = f"{issuer.rstrip('/')}/token"  # Placeholder

        super().__init__(name, config, token_storage, http_client=http_client)

        # Validate configuration
        if not self._discovery_enabled:
            # Full manual mode: require minimum endpoints
            self._validate_manual_config()

        # OIDC-specific state
        self._discovery_doc: dict[str, Any] | None = None
        self._discovery_fetched_at: datetime | None = None
        self._discovered_issuer: str | None = None  # Issuer from discovery (authoritative)
        self._code_verifier: str | None = None
        self._jwks: dict[str, Any] | None = None

        # Ensure 'openid' scope is included
        if "openid" not in config.scopes:
            config.scopes = ["openid", *config.scopes]

    def _validate_manual_config(self) -> None:
        """Validate configuration for full manual mode (no discovery).

        Note: Basic endpoint validation (authorize_url, token_url) is handled by
        OAuth2Provider.__init__ which runs before this method. This method only
        handles OIDC-specific warnings.
        """
        # Warn about missing but recommended endpoints for ID token validation
        if not self.config.jwks_uri:
            logger.warning(
                "Provider '%s': jwks_uri not configured. ID token signature verification may fail.",
                self.name,
            )

    @property
    def flow(self) -> AuthFlow:
        """Return the OAuth2/OIDC flow type."""
        return AuthFlow.AUTHORIZATION_CODE_PKCE if self.config.pkce else AuthFlow.AUTHORIZATION_CODE

    @property
    def discovery_mode(self) -> str:
        """Return the current discovery mode.

        Returns:
            One of: "auto", "hybrid", "manual"
        """
        if not self._discovery_enabled:
            return "manual"
        if self._explicit_endpoints:
            return "hybrid"
        return "auto"

    # ─────────────────────────────────────────────────────────────────────────
    # Discovery
    # ─────────────────────────────────────────────────────────────────────────

    def discover(self, *, force: bool = False) -> dict[str, Any]:
        """Fetch and cache the OIDC discovery document.

        In manual mode (no issuer), this returns an empty dict without
        making any network calls. In auto/hybrid mode, it fetches the
        discovery document and updates endpoints accordingly.

        Args:
            force: Force refresh even if cached.

        Returns:
            Discovery document as dict (empty in manual mode).

        Raises:
            DiscoveryError: If discovery fails (only in auto/hybrid mode).
        """
        # Manual mode: no discovery, return empty dict
        if not self._discovery_enabled:
            logger.debug(
                "Provider '%s' in manual mode, skipping discovery",
                self.name,
            )
            return {}

        # Check cache
        if not force and self._discovery_doc and self._discovery_fetched_at:
            age = (datetime.now(timezone.utc) - self._discovery_fetched_at).total_seconds()
            if age < self.config.discovery_ttl:
                return self._discovery_doc

        assert self.config.issuer is not None
        discovery_url = f"{self.config.issuer.rstrip('/')}/.well-known/openid-configuration"

        if logger.isEnabledFor(TRACE_LEVEL):
            logger.log(TRACE_LEVEL, "[OIDC] Fetching discovery document from %s", discovery_url)

        try:
            response = self.http_client.get(discovery_url)
            response.raise_for_status()
            discovery_doc: dict[str, Any] = response.json()
            self._discovery_doc = discovery_doc
            self._discovery_fetched_at = datetime.now(timezone.utc)

            if logger.isEnabledFor(TRACE_LEVEL):
                endpoints_found = [k for k in discovery_doc if k.endswith("_endpoint") or k == "jwks_uri"]
                logger.log(
                    TRACE_LEVEL,
                    "[OIDC] Discovery response: issuer=%s | endpoints=%s",
                    discovery_doc.get("issuer"),
                    endpoints_found,
                )
        except httpx.HTTPStatusError as e:
            raise DiscoveryError(
                self.config.issuer or "unknown",
                f"HTTP {e.response.status_code}",
            ) from e
        except httpx.RequestError as e:
            raise DiscoveryError(
                self.config.issuer or "unknown",
                str(e),
            ) from e

        # Store discovered issuer (authoritative for token validation)
        discovered_issuer = discovery_doc.get("issuer")
        if discovered_issuer:
            self._discovered_issuer = discovered_issuer
            # Warn if configured issuer differs from discovered (common with enterprise IDPs)
            if self.config.issuer and discovered_issuer != self.config.issuer:
                logger.debug(
                    "Provider '%s': discovered issuer differs from configured "
                    "(configured=%s, discovered=%s). Using discovered issuer for token validation.",
                    self.name,
                    self.config.issuer,
                    discovered_issuer,
                )

        # Update endpoints from discovery (respects explicit overrides)
        self._update_endpoints_from_discovery()

        mode = self.discovery_mode
        logger.info(
            "OIDC discovery completed for '%s' (mode: %s)",
            self.config.issuer,
            mode,
        )
        assert self._discovery_doc is not None
        return self._discovery_doc

    def _update_endpoints_from_discovery(self) -> None:
        """Update config endpoints from discovery document.

        In hybrid mode, explicit endpoints take precedence over discovered ones.
        Only endpoints not explicitly configured are updated from discovery.
        """
        if not self._discovery_doc:
            return

        # Map discovery keys to config attributes
        endpoint_mapping = {
            "authorization_endpoint": "authorize_url",
            "token_endpoint": "token_url",
            "revocation_endpoint": "revoke_url",
            "userinfo_endpoint": "userinfo_url",
            "jwks_uri": "jwks_uri",
            "end_session_endpoint": "end_session_endpoint",
        }

        for discovery_key, config_attr in endpoint_mapping.items():
            # Skip if explicitly configured (hybrid mode: explicit wins)
            if discovery_key in self._explicit_endpoints:
                logger.debug(
                    "Provider '%s': keeping explicit %s (hybrid mode)",
                    self.name,
                    discovery_key,
                )
                continue

            # Update from discovery if available
            if discovery_key in self._discovery_doc:
                setattr(self.config, config_attr, self._discovery_doc[discovery_key])
                logger.debug(
                    "Provider '%s': set %s from discovery",
                    self.name,
                    discovery_key,
                )

    # ─────────────────────────────────────────────────────────────────────────
    # PKCE
    # ─────────────────────────────────────────────────────────────────────────

    def _generate_pkce(self) -> tuple[str, str]:
        """Generate PKCE code_verifier and code_challenge.

        Returns:
            Tuple of (code_verifier, code_challenge).
        """
        # Generate 32 bytes of random data for code_verifier
        # Base64url encode -> 43 characters
        code_verifier = secrets.token_urlsafe(32)
        self._code_verifier = code_verifier

        # Create code_challenge = base64url(sha256(code_verifier))
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

        if logger.isEnabledFor(TRACE_LEVEL):
            logger.log(
                TRACE_LEVEL,
                "[PKCE] Generated code_verifier (len=%d) | challenge_method=S256",
                len(code_verifier),
            )

        return code_verifier, code_challenge

    # ─────────────────────────────────────────────────────────────────────────
    # Override OAuth2 methods for OIDC
    # ─────────────────────────────────────────────────────────────────────────

    def get_authorization_url(self, state: str | None = None) -> tuple[str, str]:
        """Generate the authorization URL with PKCE if enabled.

        Args:
            state: Optional state parameter.

        Returns:
            Tuple of (authorization_url, state).
        """
        # Ensure discovery is done first
        self.discover()

        if state is None:
            state = secrets.token_urlsafe(32)

        self._pending_state = state

        params = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "state": state,
            "scope": " ".join(self.config.scopes),
        }

        # Add PKCE if enabled
        if self.config.pkce:
            _, code_challenge = self._generate_pkce()
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"

        # Add nonce for OIDC (prevents replay attacks)
        nonce = secrets.token_urlsafe(16)
        params["nonce"] = nonce

        # Add any extra parameters
        params.update(self.config.extra.get("authorize_params", {}))

        from urllib.parse import urlencode

        url = f"{self.config.authorize_url}?{urlencode(params)}"
        logger.debug("Generated OIDC authorization URL for provider '%s' (PKCE=%s)", self.name, self.config.pkce)
        return url, state

    def exchange_code(
        self,
        code: str,
        state: str,
        *,
        code_verifier: str | None = None,
    ) -> Token:
        """Exchange authorization code for tokens, with PKCE support.

        Args:
            code: Authorization code from callback.
            state: State parameter for validation.
            code_verifier: PKCE code verifier (auto-used from internal state if not provided).

        Returns:
            Token with access_token, id_token, etc.

        Raises:
            TokenExchangeError: If exchange fails.
        """
        # Use internally stored code_verifier if not provided
        if code_verifier is None and self.config.pkce:
            code_verifier = self._code_verifier

        if self.config.pkce and not code_verifier:
            msg = "PKCE is enabled but no code_verifier available"
            raise TokenExchangeError(msg, error_code="pkce_missing")

        # Call parent implementation with code_verifier
        token = super().exchange_code(code, state, code_verifier=code_verifier)

        # Clear code_verifier after use
        self._code_verifier = None

        # Validate ID token if present
        if token.id_token:
            try:
                self._validate_id_token(token.id_token)
            except TokenValidationError as e:
                logger.warning("ID token validation failed: %s", e)
                # Don't fail the exchange, just log warning
                # Application can decide whether to reject

        return token

    # ─────────────────────────────────────────────────────────────────────────
    # ID Token validation
    # ─────────────────────────────────────────────────────────────────────────

    def _validate_id_token(self, id_token: str) -> dict[str, Any]:
        """Validate and decode an ID token.

        Args:
            id_token: JWT ID token.

        Returns:
            Decoded claims.

        Raises:
            TokenValidationError: If validation fails.
        """
        # Use discovered issuer if available (authoritative), fallback to configured
        # This handles cases where the IDP returns a different issuer in discovery
        # (e.g., with port or path suffix like :443/oauth2)
        expected_issuer = self._discovered_issuer or self.config.issuer

        if logger.isEnabledFor(TRACE_LEVEL):
            logger.log(TRACE_LEVEL, "[ID_TOKEN] Validating token (expected issuer=%s)", expected_issuer)

        try:
            # Try using authlib if available
            from authlib.jose import jwt
            from authlib.jose.errors import JoseError

            # Fetch JWKS for signature verification
            jwks = self._get_jwks()

            claims = jwt.decode(  # type: ignore[call-overload]
                id_token,
                jwks,  # pyright: ignore[reportArgumentType] - authlib accepts dict JWKS
                claims_options={
                    "iss": {"essential": True, "value": expected_issuer},
                    "aud": {"essential": True, "value": self.config.client_id},
                    "exp": {"essential": True},
                },
            )
            claims.validate()

            if logger.isEnabledFor(TRACE_LEVEL):
                logger.log(
                    TRACE_LEVEL,
                    "[ID_TOKEN] Validated: iss=%s | aud=%s | sub=%s",
                    claims.get("iss"),
                    claims.get("aud"),
                    claims.get("sub"),
                )

            return dict(claims)
        except ImportError:
            # Fallback: decode without verification (not recommended for production)
            logger.warning("authlib not available, skipping ID token signature verification")
            return self._decode_jwt_unverified(id_token)
        except JoseError as e:
            raise TokenValidationError(str(e)) from e

    def _decode_jwt_unverified(self, token: str) -> dict[str, Any]:
        """Decode JWT without signature verification (fallback)."""
        import json

        try:
            parts = token.split(".")
            if len(parts) != 3:
                raise TokenValidationError("Invalid JWT format")

            # Decode payload (second part)
            payload = parts[1]
            # Add padding if needed
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += "=" * padding

            decoded = base64.urlsafe_b64decode(payload)
            result: dict[str, Any] = json.loads(decoded)
            return result
        except Exception as e:
            raise TokenValidationError(f"Failed to decode JWT: {e}") from e

    def _get_jwks(self) -> dict[str, Any]:
        """Fetch JSON Web Key Set for ID token verification.

        Uses explicit jwks_uri if configured, otherwise gets it from discovery.
        """
        if self._jwks:
            return self._jwks

        # Try explicit config first (manual/hybrid mode)
        jwks_uri = self.config.jwks_uri

        # Fall back to discovery
        if not jwks_uri and self._discovery_enabled:
            discovery = self.discover()
            jwks_uri = discovery.get("jwks_uri")

        if not jwks_uri:
            raise TokenValidationError(
                "No jwks_uri configured or found in discovery. "
                "Configure 'jwks_uri' explicitly or ensure discovery document contains it."
            )

        if logger.isEnabledFor(TRACE_LEVEL):
            logger.log(TRACE_LEVEL, "[JWKS] Fetching keys from %s", jwks_uri)

        try:
            response = self.http_client.get(jwks_uri)
            response.raise_for_status()
            self._jwks = response.json()
            assert self._jwks is not None

            if logger.isEnabledFor(TRACE_LEVEL):
                keys = self._jwks.get("keys", [])
                key_ids = [k.get("kid", "no-kid") for k in keys]
                logger.log(TRACE_LEVEL, "[JWKS] Loaded %d keys: %s", len(keys), key_ids)

            return self._jwks
        except httpx.HTTPStatusError as e:
            raise TokenValidationError(f"Failed to fetch JWKS from {jwks_uri}: HTTP {e.response.status_code}") from e
        except httpx.RequestError as e:
            raise TokenValidationError(f"Failed to fetch JWKS from {jwks_uri}: {e}") from e

    # ─────────────────────────────────────────────────────────────────────────
    # Token refresh (with discovery)
    # ─────────────────────────────────────────────────────────────────────────

    def refresh(self, token: Token | None = None) -> Token:
        """Refresh an access token, ensuring OIDC discovery is done first.

        For OIDC providers, we must perform discovery before refreshing
        to ensure we have the correct token_endpoint URL. This is necessary
        because the endpoint URLs set during __init__ are temporary fallbacks
        that may not match the actual IDP endpoints.

        Args:
            token: Token to refresh. Uses stored token if not provided.

        Returns:
            New token with refreshed access_token.

        Raises:
            TokenRefreshError: If refresh fails.
        """
        # Ensure discovery is done to get correct token_endpoint
        self.discover()
        return super().refresh(token)

    # ─────────────────────────────────────────────────────────────────────────
    # UserInfo endpoint
    # ─────────────────────────────────────────────────────────────────────────

    def get_userinfo(self, token: Token | None = None) -> dict[str, Any]:
        """Fetch user information from the UserInfo endpoint.

        Uses explicit userinfo_url if configured, otherwise gets it from discovery.

        Args:
            token: Token to use. Uses stored token if not provided.

        Returns:
            User claims from the UserInfo endpoint.

        Raises:
            AuthError: If request fails or endpoint not configured.
        """
        if token is None:
            token = self.get_token()

        if token is None:
            msg = "No token available"
            raise TokenValidationError(msg)

        # Try explicit config first (manual/hybrid mode)
        userinfo_endpoint = self.config.userinfo_url

        # Fall back to discovery
        if not userinfo_endpoint and self._discovery_enabled:
            discovery = self.discover()
            userinfo_endpoint = discovery.get("userinfo_endpoint")

        if not userinfo_endpoint:
            msg = (
                "No userinfo_endpoint configured or found in discovery. "
                "Configure 'userinfo_url' explicitly or ensure discovery document contains it."
            )
            raise ConfigurationError(msg)

        headers = {"Authorization": f"Bearer {token.access_token}"}
        response = self.http_client.get(
            userinfo_endpoint,
            headers=headers,
        )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Preflight validation (extended for OIDC)
    # ─────────────────────────────────────────────────────────────────────────

    def preflight(self) -> PreflightReport:
        """Run preflight validation with OIDC-specific checks."""
        report = PreflightReport(provider_name=self.name)

        # Check 1: Configuration
        report.results.append(self._check_config())

        # Check 2: Discovery endpoint
        report.results.append(self._check_discovery())

        # Check 3: JWKS endpoint
        report.results.append(self._check_jwks())

        # Check 4: Required scopes supported
        report.results.append(self._check_scopes())

        # Check 5: Authorization endpoint
        report.results.append(self._check_endpoint("authorize", self.config.authorize_url))

        # Check 6: Token endpoint
        report.results.append(self._check_endpoint("token", self.config.token_url))

        return report

    def _check_discovery(self) -> PreflightResult:
        """Check OIDC discovery endpoint."""
        start = time.time()
        try:
            doc = self.discover(force=True)
            duration = int((time.time() - start) * 1000)

            required_fields = ["issuer", "authorization_endpoint", "token_endpoint", "jwks_uri"]
            missing = [f for f in required_fields if f not in doc]

            if missing:
                return PreflightResult(
                    step="discovery",
                    status=PreflightStatus.WARNING,
                    message=f"Discovery missing fields: {', '.join(missing)}",
                    details={"missing": missing, "found": list(doc)},
                    duration_ms=duration,
                )

            return PreflightResult(
                step="discovery",
                status=PreflightStatus.SUCCESS,
                message="Discovery document valid",
                details={
                    "issuer": doc.get("issuer"),
                    "endpoints": len([k for k in doc if k.endswith("_endpoint")]),
                },
                duration_ms=duration,
            )
        except DiscoveryError as e:
            duration = int((time.time() - start) * 1000)
            return PreflightResult(
                step="discovery",
                status=PreflightStatus.FAILURE,
                message=f"Discovery failed: {e.reason}",
                details={"issuer": self.config.issuer},
                duration_ms=duration,
            )

    def _check_jwks(self) -> PreflightResult:
        """Check JWKS endpoint."""
        start = time.time()
        try:
            jwks = self._get_jwks()
            duration = int((time.time() - start) * 1000)

            keys = jwks.get("keys", [])
            if not keys:
                return PreflightResult(
                    step="jwks",
                    status=PreflightStatus.WARNING,
                    message="JWKS contains no keys",
                    duration_ms=duration,
                )

            return PreflightResult(
                step="jwks",
                status=PreflightStatus.SUCCESS,
                message=f"JWKS valid ({len(keys)} keys)",
                details={"key_count": len(keys)},
                duration_ms=duration,
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            # Preflight returns result for any error
            duration = int((time.time() - start) * 1000)
            return PreflightResult(
                step="jwks",
                status=PreflightStatus.FAILURE,
                message=f"JWKS fetch failed: {e}",
                duration_ms=duration,
            )

    def _check_scopes(self) -> PreflightResult:
        """Check if required scopes are supported."""
        start = time.time()
        try:
            doc = self.discover()
            supported = doc.get("scopes_supported", [])
            duration = int((time.time() - start) * 1000)

            if not supported:
                return PreflightResult(
                    step="scopes",
                    status=PreflightStatus.WARNING,
                    message="Server does not advertise supported scopes",
                    duration_ms=duration,
                )

            unsupported = [s for s in self.config.scopes if s not in supported]
            if unsupported:
                return PreflightResult(
                    step="scopes",
                    status=PreflightStatus.WARNING,
                    message=f"Requested scopes may not be supported: {', '.join(unsupported)}",
                    details={"unsupported": unsupported, "supported": supported},
                    duration_ms=duration,
                )

            return PreflightResult(
                step="scopes",
                status=PreflightStatus.SUCCESS,
                message="All requested scopes are supported",
                details={"requested": self.config.scopes},
                duration_ms=duration,
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            # Preflight returns result for any error
            duration = int((time.time() - start) * 1000)
            return PreflightResult(
                step="scopes",
                status=PreflightStatus.FAILURE,
                message=f"Scope check failed: {e}",
                duration_ms=duration,
            )


__all__ = ["OIDCProvider"]
