"""Tests for authentication error classes."""

from __future__ import annotations

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


class TestAuthError:
    """Tests for base AuthError class."""

    def test_basic_message(self) -> None:
        """AuthError stores message correctly."""
        err = AuthError("Something went wrong")
        assert str(err) == "Something went wrong"
        assert err.message == "Something went wrong"
        assert err.details == {}

    def test_with_details(self) -> None:
        """AuthError stores details correctly."""
        err = AuthError("Error", details={"key": "value"})
        assert err.details == {"key": "value"}


class TestConfigurationError:
    """Tests for ConfigurationError."""

    def test_inherits_from_auth_error(self) -> None:
        """ConfigurationError inherits from AuthError."""
        err = ConfigurationError("Bad config")
        assert isinstance(err, AuthError)


class TestProviderNotFoundError:
    """Tests for ProviderNotFoundError."""

    def test_message_format(self) -> None:
        """ProviderNotFoundError formats message with provider name."""
        err = ProviderNotFoundError("my-provider")
        assert "my-provider" in str(err)
        assert err.provider_name == "my-provider"

    def test_inherits_from_auth_error(self) -> None:
        """ProviderNotFoundError inherits from AuthError."""
        err = ProviderNotFoundError("test")
        assert isinstance(err, AuthError)


class TestDiscoveryError:
    """Tests for DiscoveryError."""

    def test_message_format(self) -> None:
        """DiscoveryError formats message with issuer and reason."""
        err = DiscoveryError("https://issuer.example.com", "Connection timeout")
        assert "https://issuer.example.com" in str(err)
        assert "Connection timeout" in str(err)
        assert err.issuer == "https://issuer.example.com"
        assert err.reason == "Connection timeout"


class TestTokenError:
    """Tests for TokenError base class."""

    def test_inherits_from_auth_error(self) -> None:
        """TokenError inherits from AuthError."""
        err = TokenError("Token issue")
        assert isinstance(err, AuthError)


class TestTokenExpiredError:
    """Tests for TokenExpiredError."""

    def test_inherits_from_token_error(self) -> None:
        """TokenExpiredError inherits from TokenError."""
        err = TokenExpiredError("Token has expired")
        assert isinstance(err, TokenError)


class TestTokenRefreshError:
    """Tests for TokenRefreshError."""

    def test_message_format(self) -> None:
        """TokenRefreshError formats message correctly."""
        err = TokenRefreshError("Invalid refresh token")
        assert "Invalid refresh token" in str(err)
        assert err.reason == "Invalid refresh token"
        assert err.retryable is False

    def test_retryable_flag(self) -> None:
        """TokenRefreshError supports retryable flag."""
        err = TokenRefreshError("Network timeout", retryable=True)
        assert err.retryable is True


class TestTokenExchangeError:
    """Tests for TokenExchangeError."""

    def test_message_format(self) -> None:
        """TokenExchangeError formats message correctly."""
        err = TokenExchangeError("Invalid code")
        assert "Invalid code" in str(err)
        assert err.reason == "Invalid code"
        assert err.error_code is None

    def test_with_error_code(self) -> None:
        """TokenExchangeError supports error_code."""
        err = TokenExchangeError("Invalid grant", error_code="invalid_grant")
        assert err.error_code == "invalid_grant"


class TestTokenValidationError:
    """Tests for TokenValidationError."""

    def test_message_format(self) -> None:
        """TokenValidationError formats message correctly."""
        err = TokenValidationError("Signature mismatch")
        assert "Signature mismatch" in str(err)
        assert err.reason == "Signature mismatch"
        assert err.claim is None

    def test_with_claim(self) -> None:
        """TokenValidationError supports claim attribute."""
        err = TokenValidationError("Audience mismatch", claim="aud")
        assert err.claim == "aud"


class TestTokenStorageError:
    """Tests for TokenStorageError."""

    def test_inherits_from_token_error(self) -> None:
        """TokenStorageError inherits from TokenError."""
        err = TokenStorageError("Storage failure")
        assert isinstance(err, TokenError)


class TestAuthorizationError:
    """Tests for AuthorizationError."""

    def test_message_format(self) -> None:
        """AuthorizationError formats message correctly."""
        err = AuthorizationError("User denied consent")
        assert "User denied consent" in str(err)
        assert err.reason == "User denied consent"

    def test_with_error_code_and_description(self) -> None:
        """AuthorizationError supports error_code and description."""
        err = AuthorizationError(
            "Access denied",
            error_code="access_denied",
            error_description="The user denied access to the application",
        )
        assert err.error_code == "access_denied"
        assert err.error_description == "The user denied access to the application"


class TestCallbackServerError:
    """Tests for CallbackServerError."""

    def test_message_format(self) -> None:
        """CallbackServerError formats message correctly."""
        err = CallbackServerError("Port already in use")
        assert "Port already in use" in str(err)
        assert err.reason == "Port already in use"
        assert err.port is None

    def test_with_port(self) -> None:
        """CallbackServerError supports port attribute."""
        err = CallbackServerError("Port busy", port=8400)
        assert err.port == 8400


class TestPreflightError:
    """Tests for PreflightError."""

    def test_message_format(self) -> None:
        """PreflightError formats message with step and reason."""
        err = PreflightError("discovery", "Cannot reach issuer")
        assert "discovery" in str(err)
        assert "Cannot reach issuer" in str(err)
        assert err.step == "discovery"
        assert err.reason == "Cannot reach issuer"

    def test_inherits_from_auth_error(self) -> None:
        """PreflightError inherits from AuthError."""
        err = PreflightError("test", "reason")
        assert isinstance(err, AuthError)


class TestExceptionHierarchy:
    """Tests for exception inheritance hierarchy."""

    def test_all_inherit_from_auth_error(self) -> None:
        """All auth exceptions inherit from AuthError."""
        exceptions = [
            ConfigurationError("test"),
            ProviderNotFoundError("test"),
            DiscoveryError("issuer", "reason"),
            TokenError("test"),
            TokenExpiredError("test"),
            TokenRefreshError("test"),
            TokenExchangeError("test"),
            TokenValidationError("test"),
            TokenStorageError("test"),
            AuthorizationError("test"),
            CallbackServerError("test"),
            PreflightError("step", "reason"),
        ]

        for exc in exceptions:
            assert isinstance(exc, AuthError), f"{type(exc).__name__} should inherit from AuthError"
            assert isinstance(exc, Exception)

    def test_token_errors_inherit_from_token_error(self) -> None:
        """Token-related exceptions inherit from TokenError."""
        token_exceptions = [
            TokenExpiredError("test"),
            TokenRefreshError("test"),
            TokenExchangeError("test"),
            TokenValidationError("test"),
            TokenStorageError("test"),
        ]

        for exc in token_exceptions:
            assert isinstance(exc, TokenError), f"{type(exc).__name__} should inherit from TokenError"
