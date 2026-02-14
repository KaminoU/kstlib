"""Tests for auth CLI commands."""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import click.exceptions
import pytest
from typer.testing import CliRunner

from kstlib.auth.models import Token
from kstlib.cli.commands.auth import auth_app
from kstlib.cli.commands.auth.common import (
    get_provider,
    resolve_provider_name,
)

# Mark all tests in this module as CLI tests (excluded from main tox runs)
# Run with: tox -e cli OR pytest -m cli
pytestmark = pytest.mark.cli

runner = CliRunner()

# Import modules for monkeypatching
common_mod = importlib.import_module("kstlib.cli.commands.auth.common")
check_mod = importlib.import_module("kstlib.cli.commands.auth.check")
login_mod = importlib.import_module("kstlib.cli.commands.auth.login")
logout_mod = importlib.import_module("kstlib.cli.commands.auth.logout")
status_mod = importlib.import_module("kstlib.cli.commands.auth.status")
providers_mod = importlib.import_module("kstlib.cli.commands.auth.providers")
token_mod = importlib.import_module("kstlib.cli.commands.auth.token")
whoami_mod = importlib.import_module("kstlib.cli.commands.auth.whoami")
auth_config_mod = importlib.import_module("kstlib.auth.config")


# ─────────────────────────────────────────────────────────────────────────────
# common.py tests
# ─────────────────────────────────────────────────────────────────────────────


class TestResolveProviderName:
    """Tests for resolve_provider_name function."""

    def test_returns_explicit_provider(self) -> None:
        """Returns explicit provider name when provided."""
        result = resolve_provider_name("my-provider")
        assert result == "my-provider"

    def test_returns_default_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns default provider when no explicit provider."""
        monkeypatch.setattr(common_mod, "get_default_provider_name", lambda: "default-prov")

        result = resolve_provider_name(None)

        assert result == "default-prov"

    def test_returns_single_configured_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns single configured provider when no default."""
        monkeypatch.setattr(common_mod, "get_default_provider_name", lambda: None)
        monkeypatch.setattr(common_mod, "list_configured_providers", lambda: ["only-provider"])

        result = resolve_provider_name(None)

        assert result == "only-provider"

    def test_exits_when_no_providers_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exits with error when no providers configured."""
        monkeypatch.setattr(common_mod, "get_default_provider_name", lambda: None)
        monkeypatch.setattr(common_mod, "list_configured_providers", lambda: [])

        with pytest.raises((SystemExit, click.exceptions.Exit)):
            resolve_provider_name(None)

    def test_exits_when_multiple_providers_no_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exits with error when multiple providers and no default."""
        monkeypatch.setattr(common_mod, "get_default_provider_name", lambda: None)
        monkeypatch.setattr(common_mod, "list_configured_providers", lambda: ["prov1", "prov2"])

        with pytest.raises((SystemExit, click.exceptions.Exit)):
            resolve_provider_name(None)


class TestGetProvider:
    """Tests for get_provider function."""

    def test_exits_when_provider_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exits with error when provider not found."""
        monkeypatch.setattr(common_mod, "list_configured_providers", lambda: ["other"])
        monkeypatch.setattr(auth_config_mod, "get_provider_config", lambda n: None)

        with pytest.raises((SystemExit, click.exceptions.Exit)):
            get_provider("unknown")

    def test_exits_when_no_providers_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exits with helpful message when no providers configured."""
        monkeypatch.setattr(common_mod, "list_configured_providers", lambda: [])
        monkeypatch.setattr(auth_config_mod, "get_provider_config", lambda n: None)

        with pytest.raises((SystemExit, click.exceptions.Exit)):
            get_provider("unknown")

    def test_creates_oidc_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Creates OIDC provider for oidc type."""
        mock_provider = MagicMock()
        mock_from_config = MagicMock(return_value=mock_provider)

        monkeypatch.setattr(auth_config_mod, "get_provider_config", lambda n: {"type": "oidc"})

        with patch("kstlib.auth.providers.oidc.OIDCProvider.from_config", mock_from_config):
            result = get_provider("my-oidc")

        assert result == mock_provider
        mock_from_config.assert_called_once_with("my-oidc")

    def test_creates_oauth2_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Creates OAuth2 provider for oauth2 type."""
        mock_provider = MagicMock()
        mock_from_config = MagicMock(return_value=mock_provider)

        monkeypatch.setattr(auth_config_mod, "get_provider_config", lambda n: {"type": "oauth2"})

        with patch("kstlib.auth.providers.oauth2.OAuth2Provider.from_config", mock_from_config):
            result = get_provider("my-oauth2")

        assert result == mock_provider

    def test_exits_for_unknown_provider_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exits with error for unknown provider type."""
        monkeypatch.setattr(auth_config_mod, "get_provider_config", lambda n: {"type": "unknown"})

        with pytest.raises((SystemExit, click.exceptions.Exit)):
            get_provider("my-provider")

    def test_handles_configuration_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Handles ConfigurationError from provider creation."""
        from kstlib.auth.errors import ConfigurationError

        monkeypatch.setattr(auth_config_mod, "get_provider_config", lambda n: {"type": "oidc"})

        with (
            patch(
                "kstlib.auth.providers.oidc.OIDCProvider.from_config",
                side_effect=ConfigurationError("Bad config"),
            ),
            pytest.raises((SystemExit, click.exceptions.Exit)),
        ):
            get_provider("my-provider")

    def test_handles_auth_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Handles AuthError from provider creation."""
        from kstlib.auth.errors import AuthError

        monkeypatch.setattr(auth_config_mod, "get_provider_config", lambda n: {"type": "oidc"})

        with (
            patch(
                "kstlib.auth.providers.oidc.OIDCProvider.from_config",
                side_effect=AuthError("Auth failed"),
            ),
            pytest.raises((SystemExit, click.exceptions.Exit)),
        ):
            get_provider("my-provider")


# ─────────────────────────────────────────────────────────────────────────────
# CLI command tests
# ─────────────────────────────────────────────────────────────────────────────


class TestAuthProvidersList:
    """Tests for 'auth providers' command."""

    def test_lists_providers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Lists configured providers."""
        monkeypatch.setattr(providers_mod, "list_configured_providers", lambda: ["prov1", "prov2"])
        monkeypatch.setattr(providers_mod, "get_default_provider_name", lambda: "prov1")

        result = runner.invoke(auth_app, ["providers"])

        assert result.exit_code == 0
        assert "prov1" in result.stdout
        assert "prov2" in result.stdout

    def test_shows_no_providers_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Shows message when no providers configured."""
        monkeypatch.setattr(providers_mod, "list_configured_providers", lambda: [])
        monkeypatch.setattr(providers_mod, "get_default_provider_name", lambda: None)

        result = runner.invoke(auth_app, ["providers"])

        assert result.exit_code == 0
        # Message contains "No" and "providers" and "configured"
        assert "no" in result.stdout.lower()
        assert "provider" in result.stdout.lower()


class TestAuthStatus:
    """Tests for 'auth status' command."""

    def test_shows_authenticated_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Shows authenticated status with token info."""
        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.is_authenticated = True
        mock_provider.get_token.return_value = Token(
            access_token="test-token",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        monkeypatch.setattr(status_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(status_mod, "get_provider", lambda p: mock_provider)

        result = runner.invoke(auth_app, ["status"])

        assert result.exit_code == 0
        # Output shows "status" and "valid" or similar
        stdout_lower = result.stdout.lower()
        assert "status" in stdout_lower or "valid" in stdout_lower

    def test_shows_not_authenticated_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Shows not authenticated status."""
        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.is_authenticated = False
        mock_provider.get_token.return_value = None

        monkeypatch.setattr(status_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(status_mod, "get_provider", lambda p: mock_provider)

        result = runner.invoke(auth_app, ["status"])

        assert result.exit_code == 0


class TestAuthLogout:
    """Tests for 'auth logout' command."""

    def test_logout_clears_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Logout clears token and shows success."""
        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.is_authenticated = True
        mock_provider.clear_token = MagicMock()

        monkeypatch.setattr(logout_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(logout_mod, "get_provider", lambda p: mock_provider)

        result = runner.invoke(auth_app, ["logout"])

        assert result.exit_code == 0
        mock_provider.clear_token.assert_called_once()

    def test_logout_already_logged_out(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Logout when already logged out shows message."""
        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.is_authenticated = False

        monkeypatch.setattr(logout_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(logout_mod, "get_provider", lambda p: mock_provider)

        result = runner.invoke(auth_app, ["logout"])

        assert result.exit_code == 0


class TestAuthWhoami:
    """Tests for 'auth whoami' command."""

    def test_shows_user_info(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Shows user info when authenticated."""
        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.is_authenticated = True
        mock_provider.get_userinfo.return_value = {
            "sub": "user123",
            "name": "Test User",
            "email": "test@example.com",
        }

        monkeypatch.setattr(whoami_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(whoami_mod, "get_provider", lambda p: mock_provider)

        result = runner.invoke(auth_app, ["whoami"])

        assert result.exit_code == 0

    def test_shows_not_authenticated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Shows not authenticated when no token."""
        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.is_authenticated = False

        monkeypatch.setattr(whoami_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(whoami_mod, "get_provider", lambda p: mock_provider)

        result = runner.invoke(auth_app, ["whoami"])

        # Should work but show empty or message
        assert result.exit_code == 0


class TestAuthToken:
    """Tests for 'auth token' commands."""

    def test_token_show_displays_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Shows token when authenticated."""
        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.is_authenticated = True
        mock_provider.get_token.return_value = Token(
            access_token="test-access-token-12345",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        monkeypatch.setattr(token_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(token_mod, "get_provider", lambda p: mock_provider)

        result = runner.invoke(auth_app, ["token", "show"])

        assert result.exit_code == 0

    def test_token_refresh(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Refreshes token."""
        old_token = Token(
            access_token="old-token",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            refresh_token="refresh-token",
        )
        new_token = Token(
            access_token="refreshed-token",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.is_authenticated = True
        mock_provider.get_token.return_value = old_token
        mock_provider.refresh.return_value = new_token

        monkeypatch.setattr(token_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(token_mod, "get_provider", lambda p: mock_provider)

        result = runner.invoke(auth_app, ["token", "refresh"])

        assert result.exit_code == 0


class TestExtractCodeFromInput:
    """Tests for _extract_code_from_input helper function."""

    def test_extracts_code_from_full_url(self) -> None:
        """Extracts code and state from full redirect URL."""
        from kstlib.cli.commands.auth.login import _extract_code_from_input

        url = "https://example.com/callback?code=abc123&state=xyz789"
        code, state = _extract_code_from_input(url)

        assert code == "abc123"
        assert state == "xyz789"

    def test_extracts_code_from_url_without_state(self) -> None:
        """Extracts code from URL without state parameter."""
        from kstlib.cli.commands.auth.login import _extract_code_from_input

        url = "https://example.com/callback?code=abc123"
        code, state = _extract_code_from_input(url)

        assert code == "abc123"
        assert state is None

    def test_extracts_code_from_partial_query(self) -> None:
        """Extracts code from partial query string."""
        from kstlib.cli.commands.auth.login import _extract_code_from_input

        query = "?code=abc123&state=xyz789"
        code, state = _extract_code_from_input(query)

        assert code == "abc123"
        assert state == "xyz789"

    def test_extracts_raw_code_value(self) -> None:
        """Treats non-URL input as raw code value."""
        from kstlib.cli.commands.auth.login import _extract_code_from_input

        raw_code = "abc123def456"
        code, state = _extract_code_from_input(raw_code)

        assert code == "abc123def456"
        assert state is None

    def test_handles_empty_input(self) -> None:
        """Returns None for empty input."""
        from kstlib.cli.commands.auth.login import _extract_code_from_input

        code, state = _extract_code_from_input("")

        assert code is None
        assert state is None

    def test_handles_whitespace(self) -> None:
        """Strips whitespace from input."""
        from kstlib.cli.commands.auth.login import _extract_code_from_input

        code, _state = _extract_code_from_input("  abc123  ")

        assert code == "abc123"

    def test_extracts_code_from_url_with_fragment(self) -> None:
        """Extracts code from URL with additional parameters."""
        from kstlib.cli.commands.auth.login import _extract_code_from_input

        url = "https://example.com/callback?code=abc123&state=xyz&session=sess1"
        code, state = _extract_code_from_input(url)

        assert code == "abc123"
        assert state == "xyz"

    def test_rejects_input_exceeding_max_length(self) -> None:
        """Rejects input that exceeds maximum length (DoS protection)."""
        from kstlib.cli.commands.auth.login import _extract_code_from_input

        long_input = "a" * 5000
        code, state = _extract_code_from_input(long_input)

        assert code is None
        assert state is None

    def test_rejects_code_exceeding_max_length(self) -> None:
        """Rejects code that exceeds maximum code length."""
        from kstlib.cli.commands.auth.login import _extract_code_from_input

        long_code = "a" * 600
        url = f"https://example.com/callback?code={long_code}&state=xyz"
        code, _state = _extract_code_from_input(url)

        assert code is None

    def test_rejects_code_with_invalid_characters(self) -> None:
        """Rejects code containing invalid characters (injection protection)."""
        from kstlib.cli.commands.auth.login import _extract_code_from_input

        # Code with shell injection attempt
        malicious = "abc123; rm -rf /"
        code, _state = _extract_code_from_input(malicious)

        assert code is None

    def test_accepts_code_with_valid_rfc6749_characters(self) -> None:
        """Accepts code with valid RFC 6749 characters."""
        from kstlib.cli.commands.auth.login import _extract_code_from_input

        # Valid chars: alphanumeric, ., _, ~, +, /, =, -
        valid_code = "abc123.DEF_456~ghi+jkl/mno=pqr-stu"
        code, _state = _extract_code_from_input(valid_code)

        assert code == valid_code


class TestAuthLogin:
    """Tests for 'auth login' command."""

    def test_login_help(self) -> None:
        """Login --help shows usage."""
        result = runner.invoke(auth_app, ["login", "--help"])

        assert result.exit_code == 0
        assert "login" in result.stdout.lower()

    def test_login_help_shows_manual_option(self) -> None:
        """Login --help shows --manual option."""
        result = runner.invoke(auth_app, ["login", "--help"])

        assert result.exit_code == 0
        assert "--manual" in result.stdout

    def test_login_already_authenticated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Login shows already authenticated message."""
        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.is_authenticated = True

        monkeypatch.setattr(login_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(login_mod, "get_provider", lambda p: mock_provider)

        result = runner.invoke(auth_app, ["login"])

        assert result.exit_code == 0
        assert "already" in result.stdout.lower() or "authenticated" in result.stdout.lower()

    def test_login_callback_server_error_suggests_manual(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Callback server error suggests using --manual mode."""
        from kstlib.auth.errors import CallbackServerError

        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.is_authenticated = False

        monkeypatch.setattr(login_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(login_mod, "get_provider", lambda p: mock_provider)
        monkeypatch.setattr(
            login_mod,
            "get_callback_server_config",
            lambda: {"host": "127.0.0.1", "port": 443},
        )

        # Mock CallbackServer to raise error
        def mock_callback_server(*args: object, **kwargs: object) -> MagicMock:
            mock = MagicMock()
            mock.__enter__ = MagicMock(side_effect=CallbackServerError("Port 443 not available"))
            mock.__exit__ = MagicMock(return_value=False)
            return mock

        monkeypatch.setattr(login_mod, "CallbackServer", mock_callback_server)

        result = runner.invoke(auth_app, ["login"])

        assert result.exit_code == 1
        assert "--manual" in result.stdout


class TestAuthCheck:
    """Tests for 'auth check' command."""

    def test_check_help(self) -> None:
        """Check --help shows usage."""
        result = runner.invoke(auth_app, ["check", "--help"])

        assert result.exit_code == 0
        assert "check" in result.stdout.lower()
        assert "--token" in result.stdout
        assert "--verbose" in result.stdout
        assert "--json" in result.stdout
        assert "--access-token" in result.stdout

    def test_check_not_authenticated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Shows error when not authenticated and no --token."""
        mock_provider = MagicMock()
        mock_provider.get_token.return_value = None

        monkeypatch.setattr(check_mod, "resolve_provider_name", lambda _p: "test-provider")
        monkeypatch.setattr(check_mod, "get_provider", lambda _p: mock_provider)

        result = runner.invoke(auth_app, ["check"])

        assert result.exit_code == 1
        assert "not authenticated" in result.stdout.lower() or "login" in result.stdout.lower()

    def test_check_with_explicit_token_invalid(self) -> None:
        """Check with invalid --token exits with code 1."""
        result = runner.invoke(auth_app, ["check", "--token", "not-a-jwt"])

        assert result.exit_code == 1

    def test_check_with_explicit_token_json_invalid(self) -> None:
        """Check with --json outputs JSON even for invalid token."""
        result = runner.invoke(auth_app, ["check", "--token", "not-a-jwt", "--json"])

        assert result.exit_code == 1
        # Should be valid JSON output
        output = result.stdout.strip()
        data = json.loads(output)
        assert data["valid"] is False

    def test_check_cached_id_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Uses cached id_token by default."""
        import base64
        import time

        # Create a structurally valid JWT (will fail at discovery, but tests token source logic)
        header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "kid": "k1"}).encode()).rstrip(b"=").decode()
        payload_data = {"iss": "https://idp.test", "exp": int(time.time()) + 3600}
        payload = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).rstrip(b"=").decode()
        fake_jwt = f"{header}.{payload}.fakesig"

        mock_token = Token(
            access_token="access-token-value",  # noqa: S106
            token_type="Bearer",  # noqa: S106
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            id_token=fake_jwt,
        )
        mock_provider = MagicMock()
        mock_provider.get_token.return_value = mock_token
        mock_provider.config = MagicMock()
        mock_provider.config.issuer = "https://idp.test"
        mock_provider.config.client_id = "test-client"

        monkeypatch.setattr(check_mod, "resolve_provider_name", lambda _p: "test-provider")
        monkeypatch.setattr(check_mod, "get_provider", lambda _p: mock_provider)

        # Will fail at discovery since we can't reach idp.test, but token source is correct
        result = runner.invoke(auth_app, ["check"])

        # Exits with 1 (invalid - discovery fails) but should not be exit 2
        assert result.exit_code == 1

    def test_check_access_token_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Uses access_token with --access-token flag."""
        import base64
        import time

        header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "kid": "k1"}).encode()).rstrip(b"=").decode()
        payload_data = {"iss": "https://idp.test", "exp": int(time.time()) + 3600}
        payload = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).rstrip(b"=").decode()
        access_jwt = f"{header}.{payload}.fakesig"

        mock_token = Token(
            access_token=access_jwt,
            token_type="Bearer",  # noqa: S106
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            id_token="id-token-value",  # noqa: S106
        )
        mock_provider = MagicMock()
        mock_provider.get_token.return_value = mock_token
        mock_provider.config = MagicMock()
        mock_provider.config.issuer = "https://idp.test"
        mock_provider.config.client_id = "test-client"

        monkeypatch.setattr(check_mod, "resolve_provider_name", lambda _p: "test-provider")
        monkeypatch.setattr(check_mod, "get_provider", lambda _p: mock_provider)

        result = runner.invoke(auth_app, ["check", "--access-token"])

        # Will fail at discovery but should attempt validation
        assert result.exit_code == 1

    def test_check_fallback_to_access_token_when_no_id_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Falls back to access_token when no id_token cached."""
        import base64
        import time

        header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "kid": "k1"}).encode()).rstrip(b"=").decode()
        payload_data = {"iss": "https://idp.test", "exp": int(time.time()) + 3600}
        payload = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).rstrip(b"=").decode()
        access_jwt = f"{header}.{payload}.fakesig"

        mock_token = Token(
            access_token=access_jwt,
            token_type="Bearer",  # noqa: S106
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            id_token=None,  # No id_token
        )
        mock_provider = MagicMock()
        mock_provider.get_token.return_value = mock_token
        mock_provider.config = MagicMock()
        mock_provider.config.issuer = "https://idp.test"
        mock_provider.config.client_id = "test-client"

        monkeypatch.setattr(check_mod, "resolve_provider_name", lambda _p: "test-provider")
        monkeypatch.setattr(check_mod, "get_provider", lambda _p: mock_provider)

        result = runner.invoke(auth_app, ["check"])

        assert result.exit_code == 1
