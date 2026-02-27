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

    # ── _decode_jwt() unit tests ──────────────────────────────────────────────

    def test_decode_jwt_valid(self) -> None:
        """Decodes a well-formed JWT into header and payload dicts."""
        import base64

        header_data = {"alg": "RS256", "typ": "JWT"}
        payload_data = {"sub": "user1", "exp": 9999999999}
        header_b64 = base64.urlsafe_b64encode(json.dumps(header_data).encode()).rstrip(b"=").decode()
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).rstrip(b"=").decode()
        jwt_str = f"{header_b64}.{payload_b64}.fakesignature"

        result = token_mod._decode_jwt(jwt_str)

        assert result is not None
        header, payload = result
        assert header["alg"] == "RS256"
        assert payload["sub"] == "user1"

    def test_decode_jwt_not_three_parts(self) -> None:
        """Returns None when token does not have exactly three dot-separated parts."""
        result = token_mod._decode_jwt("not-a-jwt")

        assert result is None

    def test_decode_jwt_invalid_base64(self) -> None:
        """Returns None when base64 decoding of a part fails."""
        result = token_mod._decode_jwt("!!!.!!!.fakesig")

        assert result is None

    def test_decode_jwt_invalid_json(self) -> None:
        """Returns None when decoded bytes are not valid JSON."""
        import base64

        bad_b64 = base64.urlsafe_b64encode(b"not-json").rstrip(b"=").decode()
        result = token_mod._decode_jwt(f"{bad_b64}.{bad_b64}.sig")

        assert result is None

    # ── _format_decoded() unit tests ─────────────────────────────────────────

    def test_format_decoded_yaml_like(self) -> None:
        """Returns Rich-marked YAML-like text when as_json is False."""
        header = {"alg": "RS256", "typ": "JWT"}
        payload = {"sub": "user1", "name": "Alice"}

        output = token_mod._format_decoded(header, payload, as_json=False)

        assert "JWT Header" in output
        assert "JWT Payload" in output
        assert "RS256" in output
        assert "Alice" in output

    def test_format_decoded_json(self) -> None:
        """Returns valid JSON string when as_json is True."""
        header = {"alg": "RS256"}
        payload = {"sub": "user1"}

        output = token_mod._format_decoded(header, payload, as_json=True)

        parsed = json.loads(output)
        assert parsed["header"]["alg"] == "RS256"
        assert parsed["payload"]["sub"] == "user1"

    def test_format_decoded_timestamp_fields(self) -> None:
        """Appends ISO timestamp for exp/iat/nbf/auth_time integer fields."""
        import time

        header = {"alg": "RS256"}
        payload = {"exp": int(time.time()) + 3600, "iat": int(time.time())}

        output = token_mod._format_decoded(header, payload, as_json=False)

        # ISO format contains "T" and "+" or "Z"
        assert "T" in output

    def test_format_decoded_list_field(self) -> None:
        """Renders list payload values as comma-separated string."""
        header = {"alg": "RS256"}
        payload = {"roles": ["admin", "user"]}

        output = token_mod._format_decoded(header, payload, as_json=False)

        assert "admin" in output
        assert "user" in output

    # ── token() command – basic display ──────────────────────────────────────

    def test_token_show_prints_raw_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Prints raw access token to stdout when no flags set."""
        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.get_token.return_value = Token(
            access_token="my-raw-access-token",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        monkeypatch.setattr(token_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(token_mod, "get_provider", lambda p: mock_provider)

        result = runner.invoke(auth_app, ["token", "show"])

        assert result.exit_code == 0
        assert "my-raw-access-token" in result.stdout

    def test_token_not_authenticated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exits with error when provider returns no token."""
        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.get_token.return_value = None

        monkeypatch.setattr(token_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(token_mod, "get_provider", lambda p: mock_provider)

        result = runner.invoke(auth_app, ["token", "show"])

        assert result.exit_code == 1
        assert "not authenticated" in result.stdout.lower() or "login" in result.stdout.lower()

    # ── --header flag ─────────────────────────────────────────────────────────

    def test_token_header_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Outputs 'Bearer <token>' when --header flag is set."""
        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.get_token.return_value = Token(
            access_token="header-access-token",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        monkeypatch.setattr(token_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(token_mod, "get_provider", lambda p: mock_provider)

        result = runner.invoke(auth_app, ["token", "show", "--header"])

        assert result.exit_code == 0
        assert "Bearer header-access-token" in result.stdout

    def test_token_header_flag_with_enum_token_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Outputs correct prefix when token_type is a TokenType enum value."""
        from kstlib.auth.models import TokenType

        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.get_token.return_value = Token(
            access_token="enum-type-token",
            token_type=TokenType.BEARER,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        monkeypatch.setattr(token_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(token_mod, "get_provider", lambda p: mock_provider)

        result = runner.invoke(auth_app, ["token", "show", "--header"])

        assert result.exit_code == 0
        assert "Bearer enum-type-token" in result.stdout

    # ── --show-refresh flag ───────────────────────────────────────────────────

    def test_token_show_refresh_with_refresh_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Displays refresh token when --show-refresh and refresh_token exists."""
        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.get_token.return_value = Token(
            access_token="access-tok",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            refresh_token="my-refresh-token-value",
        )

        monkeypatch.setattr(token_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(token_mod, "get_provider", lambda p: mock_provider)

        result = runner.invoke(auth_app, ["token", "show", "--show-refresh"])

        assert result.exit_code == 0
        assert "my-refresh-token-value" in result.stdout

    def test_token_show_refresh_without_refresh_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exits with error when --show-refresh but no refresh_token available."""
        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.get_token.return_value = Token(
            access_token="access-tok",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            refresh_token=None,
        )

        monkeypatch.setattr(token_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(token_mod, "get_provider", lambda p: mock_provider)

        result = runner.invoke(auth_app, ["token", "show", "--show-refresh"])

        assert result.exit_code == 1
        assert "refresh" in result.stdout.lower()

    def test_token_header_with_show_refresh_incompatible(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exits with error when --header and --show-refresh used together."""
        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.get_token.return_value = Token(
            access_token="access-tok",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            refresh_token="refresh-tok",
        )

        monkeypatch.setattr(token_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(token_mod, "get_provider", lambda p: mock_provider)

        result = runner.invoke(auth_app, ["token", "show", "--header", "--show-refresh"])

        assert result.exit_code == 1
        assert "header" in result.stdout.lower() or "refresh" in result.stdout.lower()

    # ── --refresh flag ────────────────────────────────────────────────────────

    def test_token_refresh_flag_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Refreshes token and prints new access token when --refresh flag used."""
        old_token = Token(
            access_token="old-access-token",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            refresh_token="valid-refresh-token",
        )
        new_token = Token(
            access_token="new-access-token",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.get_token.return_value = old_token
        mock_provider.refresh.return_value = new_token

        monkeypatch.setattr(token_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(token_mod, "get_provider", lambda p: mock_provider)

        result = runner.invoke(auth_app, ["token", "show", "--refresh"])

        assert result.exit_code == 0
        assert "new-access-token" in result.stdout

    def test_token_refresh_flag_not_authenticated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exits with error when --refresh used but not authenticated."""
        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.get_token.return_value = None

        monkeypatch.setattr(token_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(token_mod, "get_provider", lambda p: mock_provider)

        result = runner.invoke(auth_app, ["token", "show", "--refresh"])

        assert result.exit_code == 1
        assert "not authenticated" in result.stdout.lower() or "login" in result.stdout.lower()

    def test_token_refresh_flag_no_refresh_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exits with error when --refresh used but token has no refresh_token."""
        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.get_token.return_value = Token(
            access_token="access-tok",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            refresh_token=None,
        )

        monkeypatch.setattr(token_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(token_mod, "get_provider", lambda p: mock_provider)

        result = runner.invoke(auth_app, ["token", "show", "--refresh"])

        assert result.exit_code == 1
        assert "refresh" in result.stdout.lower()

    def test_token_refresh_flag_refresh_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exits with error when provider.refresh() raises an exception."""
        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.get_token.return_value = Token(
            access_token="old-tok",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            refresh_token="expired-refresh",
        )
        mock_provider.refresh.side_effect = RuntimeError("Refresh endpoint unreachable")

        monkeypatch.setattr(token_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(token_mod, "get_provider", lambda p: mock_provider)

        result = runner.invoke(auth_app, ["token", "show", "--refresh"])

        assert result.exit_code == 1
        assert "refresh failed" in result.stdout.lower() or "refresh" in result.stdout.lower()

    # ── --copy flag ───────────────────────────────────────────────────────────

    def test_token_copy_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Copies access token to clipboard and shows confirmation."""
        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.get_token.return_value = Token(
            access_token="clipboard-token",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        monkeypatch.setattr(token_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(token_mod, "get_provider", lambda p: mock_provider)

        import builtins
        import sys

        mock_pyperclip = MagicMock()
        monkeypatch.setattr(builtins, "pyperclip", mock_pyperclip, raising=False)

        mock_pyperclip_mod = MagicMock()
        monkeypatch.setitem(sys.modules, "pyperclip", mock_pyperclip_mod)

        result = runner.invoke(auth_app, ["token", "show", "--copy"])

        assert result.exit_code == 0
        mock_pyperclip_mod.copy.assert_called_once_with("clipboard-token")
        assert "clipboard" in result.stdout.lower() or "copied" in result.stdout.lower()

    def test_token_copy_pyperclip_not_installed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exits with error when pyperclip is not installed."""
        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.get_token.return_value = Token(
            access_token="clipboard-token",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        monkeypatch.setattr(token_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(token_mod, "get_provider", lambda p: mock_provider)

        import sys

        monkeypatch.setitem(sys.modules, "pyperclip", None)

        result = runner.invoke(auth_app, ["token", "show", "--copy"])

        assert result.exit_code == 1
        assert "pyperclip" in result.stdout.lower() or "clipboard" in result.stdout.lower()

    def test_token_copy_clipboard_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exits with error when clipboard operation itself fails."""
        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.get_token.return_value = Token(
            access_token="clipboard-token",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        monkeypatch.setattr(token_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(token_mod, "get_provider", lambda p: mock_provider)

        import sys

        mock_pyperclip_mod = MagicMock()
        mock_pyperclip_mod.copy.side_effect = Exception("No display available")
        monkeypatch.setitem(sys.modules, "pyperclip", mock_pyperclip_mod)

        result = runner.invoke(auth_app, ["token", "show", "--copy"])

        assert result.exit_code == 1
        assert "clipboard" in result.stdout.lower() or "failed" in result.stdout.lower()

    # ── --decode flag ─────────────────────────────────────────────────────────

    def test_token_decode_valid_jwt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Decodes a valid JWT access token and displays header and payload."""
        import base64

        header_data = {"alg": "RS256", "typ": "JWT"}
        payload_data = {"sub": "user123", "iss": "https://idp.test"}
        header_b64 = base64.urlsafe_b64encode(json.dumps(header_data).encode()).rstrip(b"=").decode()
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).rstrip(b"=").decode()
        valid_jwt = f"{header_b64}.{payload_b64}.fakesig"

        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.get_token.return_value = Token(
            access_token=valid_jwt,
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        monkeypatch.setattr(token_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(token_mod, "get_provider", lambda p: mock_provider)

        result = runner.invoke(auth_app, ["token", "show", "--decode"])

        assert result.exit_code == 0
        assert "RS256" in result.stdout
        assert "user123" in result.stdout

    def test_token_decode_non_jwt_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exits with error when --decode used but token is not a valid JWT."""
        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.get_token.return_value = Token(
            access_token="opaque-non-jwt-token",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        monkeypatch.setattr(token_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(token_mod, "get_provider", lambda p: mock_provider)

        result = runner.invoke(auth_app, ["token", "show", "--decode"])

        assert result.exit_code == 1
        assert "jwt" in result.stdout.lower() or "format" in result.stdout.lower()

    # ── --json flag ───────────────────────────────────────────────────────────

    def test_token_decode_json_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Outputs valid JSON when --decode and --json flags are combined."""
        import base64

        header_data = {"alg": "HS256"}
        payload_data = {"sub": "json-user", "exp": 9999999999}
        header_b64 = base64.urlsafe_b64encode(json.dumps(header_data).encode()).rstrip(b"=").decode()
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).rstrip(b"=").decode()
        valid_jwt = f"{header_b64}.{payload_b64}.fakesig"

        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.get_token.return_value = Token(
            access_token=valid_jwt,
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        monkeypatch.setattr(token_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(token_mod, "get_provider", lambda p: mock_provider)

        result = runner.invoke(auth_app, ["token", "show", "--decode", "--json"])

        assert result.exit_code == 0
        parsed = json.loads(result.stdout.strip())
        assert parsed["header"]["alg"] == "HS256"
        assert parsed["payload"]["sub"] == "json-user"

    def test_token_json_without_decode_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exits with error when --json used without --decode."""
        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.get_token.return_value = Token(
            access_token="some-token",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        monkeypatch.setattr(token_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(token_mod, "get_provider", lambda p: mock_provider)

        result = runner.invoke(auth_app, ["token", "show", "--json"])

        assert result.exit_code == 1
        assert "decode" in result.stdout.lower() or "json" in result.stdout.lower()

    # ── incompatible flag combinations ────────────────────────────────────────

    def test_token_decode_and_header_incompatible(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exits with error when --decode and --header used together."""
        import base64

        header_data = {"alg": "RS256"}
        payload_data = {"sub": "user1"}
        header_b64 = base64.urlsafe_b64encode(json.dumps(header_data).encode()).rstrip(b"=").decode()
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).rstrip(b"=").decode()
        valid_jwt = f"{header_b64}.{payload_b64}.fakesig"

        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.get_token.return_value = Token(
            access_token=valid_jwt,
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        monkeypatch.setattr(token_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(token_mod, "get_provider", lambda p: mock_provider)

        result = runner.invoke(auth_app, ["token", "show", "--decode", "--header"])

        assert result.exit_code == 1
        assert "decode" in result.stdout.lower() or "header" in result.stdout.lower()

    def test_token_decode_and_copy_incompatible(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exits with error when --decode and --copy used together."""
        import base64

        import sys

        mock_pyperclip_mod = MagicMock()
        monkeypatch.setitem(sys.modules, "pyperclip", mock_pyperclip_mod)

        header_data = {"alg": "RS256"}
        payload_data = {"sub": "user1"}
        header_b64 = base64.urlsafe_b64encode(json.dumps(header_data).encode()).rstrip(b"=").decode()
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).rstrip(b"=").decode()
        valid_jwt = f"{header_b64}.{payload_b64}.fakesig"

        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.get_token.return_value = Token(
            access_token=valid_jwt,
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        monkeypatch.setattr(token_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(token_mod, "get_provider", lambda p: mock_provider)

        result = runner.invoke(auth_app, ["token", "show", "--decode", "--copy"])

        assert result.exit_code == 1
        assert "decode" in result.stdout.lower() or "copy" in result.stdout.lower()


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
        """Rejects code that exceeds maximum code length (2048)."""
        from kstlib.cli.commands.auth.login import _MAX_CODE_LENGTH, _extract_code_from_input

        long_code = "a" * (_MAX_CODE_LENGTH + 1)
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

    # ── _login_manual() tests ─────────────────────────────────────────────────

    def test_login_manual_success_with_pkce(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Manual mode succeeds with PKCE provider and full redirect URL."""
        from datetime import datetime, timedelta, timezone

        from kstlib.auth.models import Token, TokenType

        mock_token = Token(
            access_token="access-xyz",
            token_type=TokenType.BEARER,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scope=["openid", "profile"],
        )
        mock_provider = MagicMock()
        mock_provider.name = "test-provider"
        mock_provider.is_authenticated = False
        mock_provider.get_authorization_url_with_pkce.return_value = (
            "https://idp.test/auth?response_type=code&client_id=x",
            "state-abc",
            "verifier-xyz",
        )
        mock_provider.exchange_code.return_value = mock_token

        monkeypatch.setattr(login_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(login_mod, "get_provider", lambda p: mock_provider)
        monkeypatch.setattr(
            login_mod,
            "Prompt",
            MagicMock(ask=MagicMock(return_value="https://app.test/cb?code=authcode123&state=state-abc")),
        )

        result = runner.invoke(auth_app, ["login", "--manual"])

        assert result.exit_code == 0
        assert "successfully authenticated" in result.stdout.lower()
        mock_provider.exchange_code.assert_called_once_with(
            code="authcode123",
            state="state-abc",
            code_verifier="verifier-xyz",
        )

    def test_login_manual_success_without_pkce(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Manual mode succeeds with standard provider (no PKCE)."""
        from datetime import datetime, timedelta, timezone

        from kstlib.auth.models import Token, TokenType

        mock_token = Token(
            access_token="access-abc",
            token_type=TokenType.BEARER,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scope=["openid"],
        )

        # Provider without get_authorization_url_with_pkce attribute
        mock_provider = MagicMock(spec=["is_authenticated", "get_authorization_url", "exchange_code"])
        mock_provider.is_authenticated = False
        mock_provider.get_authorization_url.return_value = (
            "https://idp.test/auth",
            "state-nopkce",
        )
        mock_provider.exchange_code.return_value = mock_token

        monkeypatch.setattr(login_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(login_mod, "get_provider", lambda p: mock_provider)
        monkeypatch.setattr(
            login_mod,
            "Prompt",
            MagicMock(ask=MagicMock(return_value="rawcode456")),
        )

        result = runner.invoke(auth_app, ["login", "--manual"])

        assert result.exit_code == 0
        mock_provider.exchange_code.assert_called_once_with(
            code="rawcode456",
            state="state-nopkce",
            code_verifier=None,
        )

    def test_login_manual_empty_input(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Manual mode exits with error when user provides empty input."""
        mock_provider = MagicMock()
        mock_provider.is_authenticated = False
        mock_provider.get_authorization_url_with_pkce.return_value = (
            "https://idp.test/auth",
            "state-xyz",
            "verifier-xyz",
        )

        monkeypatch.setattr(login_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(login_mod, "get_provider", lambda p: mock_provider)
        monkeypatch.setattr(
            login_mod,
            "Prompt",
            MagicMock(ask=MagicMock(return_value="")),
        )

        result = runner.invoke(auth_app, ["login", "--manual"])

        assert result.exit_code != 0
        assert "no input" in result.stdout.lower()

    def test_login_manual_invalid_code(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Manual mode exits with error when code cannot be extracted."""
        mock_provider = MagicMock()
        mock_provider.is_authenticated = False
        mock_provider.get_authorization_url_with_pkce.return_value = (
            "https://idp.test/auth",
            "state-xyz",
            "verifier-xyz",
        )

        monkeypatch.setattr(login_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(login_mod, "get_provider", lambda p: mock_provider)
        # Input with invalid characters that fail code extraction
        monkeypatch.setattr(
            login_mod,
            "Prompt",
            MagicMock(ask=MagicMock(return_value="invalid code with spaces!")),
        )

        result = runner.invoke(auth_app, ["login", "--manual"])

        assert result.exit_code != 0
        assert "authorization code" in result.stdout.lower() or "could not extract" in result.stdout.lower()

    def test_login_manual_state_mismatch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Manual mode exits with error when state parameter does not match."""
        mock_provider = MagicMock()
        mock_provider.is_authenticated = False
        mock_provider.get_authorization_url_with_pkce.return_value = (
            "https://idp.test/auth",
            "expected-state",
            "verifier-xyz",
        )

        monkeypatch.setattr(login_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(login_mod, "get_provider", lambda p: mock_provider)
        # Redirect URL with a different state value
        monkeypatch.setattr(
            login_mod,
            "Prompt",
            MagicMock(ask=MagicMock(return_value="https://app.test/cb?code=abc123&state=tampered-state")),
        )

        result = runner.invoke(auth_app, ["login", "--manual"])

        assert result.exit_code != 0
        assert "state mismatch" in result.stdout.lower() or "csrf" in result.stdout.lower()

    def test_login_manual_token_exchange_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Manual mode exits with error when token exchange fails."""
        from kstlib.auth.errors import TokenExchangeError

        mock_provider = MagicMock()
        mock_provider.is_authenticated = False
        mock_provider.get_authorization_url_with_pkce.return_value = (
            "https://idp.test/auth",
            "state-abc",
            "verifier-xyz",
        )
        mock_provider.exchange_code.side_effect = TokenExchangeError("invalid_grant")

        monkeypatch.setattr(login_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(login_mod, "get_provider", lambda p: mock_provider)
        monkeypatch.setattr(
            login_mod,
            "Prompt",
            MagicMock(ask=MagicMock(return_value="https://app.test/cb?code=authcode123&state=state-abc")),
        )

        result = runner.invoke(auth_app, ["login", "--manual"])

        assert result.exit_code != 0
        assert "token exchange failed" in result.stdout.lower()

    def test_login_manual_quiet_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Manual mode with --quiet suppresses verbose output."""
        from datetime import datetime, timedelta, timezone

        from kstlib.auth.models import Token, TokenType

        mock_token = Token(
            access_token="access-quiet",
            token_type=TokenType.BEARER,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scope=[],
        )
        mock_provider = MagicMock()
        mock_provider.is_authenticated = False
        mock_provider.get_authorization_url_with_pkce.return_value = (
            "https://idp.test/auth",
            "state-abc",
            "verifier-xyz",
        )
        mock_provider.exchange_code.return_value = mock_token

        monkeypatch.setattr(login_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(login_mod, "get_provider", lambda p: mock_provider)
        monkeypatch.setattr(
            login_mod,
            "Prompt",
            MagicMock(ask=MagicMock(return_value="https://app.test/cb?code=code1&state=state-abc")),
        )

        result = runner.invoke(auth_app, ["login", "--manual", "--quiet"])

        assert result.exit_code == 0
        # Quiet mode should not print "Exchanging authorization code for token..."
        assert "exchanging" not in result.stdout.lower()

    # ── _login_with_callback() tests ──────────────────────────────────────────

    def test_login_callback_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Callback mode completes successfully with valid code and state."""
        from datetime import datetime, timedelta, timezone

        from kstlib.auth.callback import CallbackResult
        from kstlib.auth.models import Token, TokenType

        mock_token = Token(
            access_token="access-callback",
            token_type=TokenType.BEARER,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scope=["openid"],
        )
        mock_provider = MagicMock()
        mock_provider.is_authenticated = False
        mock_provider.get_authorization_url_with_pkce.return_value = (
            "https://idp.test/auth",
            "state-cb",
            "verifier-cb",
        )
        mock_provider.exchange_code.return_value = mock_token

        mock_server = MagicMock()
        mock_server.wait_for_callback.return_value = CallbackResult(
            code="cbcode123",
            state="state-cb",
        )
        mock_server.__enter__ = MagicMock(return_value=mock_server)
        mock_server.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr(login_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(login_mod, "get_provider", lambda p: mock_provider)
        monkeypatch.setattr(login_mod, "get_callback_server_config", lambda: {"host": "127.0.0.1", "port": 8400})
        monkeypatch.setattr(login_mod, "CallbackServer", MagicMock(return_value=mock_server))
        monkeypatch.setattr(login_mod, "webbrowser", MagicMock())

        result = runner.invoke(auth_app, ["login"])

        assert result.exit_code == 0
        assert "successfully authenticated" in result.stdout.lower()

    def test_login_callback_no_browser_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Callback mode with --no-browser prints URL instead of opening browser."""
        from datetime import datetime, timedelta, timezone

        from kstlib.auth.callback import CallbackResult
        from kstlib.auth.models import Token, TokenType

        mock_token = Token(
            access_token="access-nobrowser",
            token_type=TokenType.BEARER,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scope=[],
        )
        mock_provider = MagicMock()
        mock_provider.is_authenticated = False
        mock_provider.get_authorization_url_with_pkce.return_value = (
            "https://idp.test/auth?response_type=code",
            "state-nb",
            "verifier-nb",
        )
        mock_provider.exchange_code.return_value = mock_token

        mock_browser = MagicMock()
        mock_server = MagicMock()
        mock_server.wait_for_callback.return_value = CallbackResult(
            code="nbcode",
            state="state-nb",
        )
        mock_server.__enter__ = MagicMock(return_value=mock_server)
        mock_server.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr(login_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(login_mod, "get_provider", lambda p: mock_provider)
        monkeypatch.setattr(login_mod, "get_callback_server_config", lambda: {"host": "127.0.0.1", "port": 8400})
        monkeypatch.setattr(login_mod, "CallbackServer", MagicMock(return_value=mock_server))
        monkeypatch.setattr(login_mod, "webbrowser", mock_browser)

        result = runner.invoke(auth_app, ["login", "--no-browser"])

        assert result.exit_code == 0
        # URL printed in output, browser not opened
        assert "https://idp.test/auth" in result.stdout
        mock_browser.open.assert_not_called()

    def test_login_callback_without_pkce(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Callback mode works with provider that does not support PKCE."""
        from datetime import datetime, timedelta, timezone

        from kstlib.auth.callback import CallbackResult
        from kstlib.auth.models import Token, TokenType

        mock_token = Token(
            access_token="access-nopkce",
            token_type=TokenType.BEARER,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scope=[],
        )

        mock_provider = MagicMock(spec=["is_authenticated", "get_authorization_url", "exchange_code"])
        mock_provider.is_authenticated = False
        mock_provider.get_authorization_url.return_value = ("https://idp.test/auth", "state-nopkce")
        mock_provider.exchange_code.return_value = mock_token

        mock_server = MagicMock()
        mock_server.wait_for_callback.return_value = CallbackResult(
            code="nopkce-code",
            state="state-nopkce",
        )
        mock_server.__enter__ = MagicMock(return_value=mock_server)
        mock_server.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr(login_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(login_mod, "get_provider", lambda p: mock_provider)
        monkeypatch.setattr(login_mod, "get_callback_server_config", lambda: {"host": "127.0.0.1", "port": 8400})
        monkeypatch.setattr(login_mod, "CallbackServer", MagicMock(return_value=mock_server))
        monkeypatch.setattr(login_mod, "webbrowser", MagicMock())

        result = runner.invoke(auth_app, ["login"])

        assert result.exit_code == 0
        mock_provider.exchange_code.assert_called_once_with(
            code="nopkce-code",
            state="state-nopkce",
            code_verifier=None,
        )

    def test_login_callback_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Callback mode exits with error when IdP returns an error response."""
        from kstlib.auth.callback import CallbackResult

        mock_provider = MagicMock()
        mock_provider.is_authenticated = False
        mock_provider.get_authorization_url_with_pkce.return_value = (
            "https://idp.test/auth",
            "state-err",
            "verifier-err",
        )

        mock_server = MagicMock()
        mock_server.wait_for_callback.return_value = CallbackResult(
            code=None,
            state="state-err",
            error="access_denied",
            error_description="User denied access",
        )
        mock_server.__enter__ = MagicMock(return_value=mock_server)
        mock_server.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr(login_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(login_mod, "get_provider", lambda p: mock_provider)
        monkeypatch.setattr(login_mod, "get_callback_server_config", lambda: {"host": "127.0.0.1", "port": 8400})
        monkeypatch.setattr(login_mod, "CallbackServer", MagicMock(return_value=mock_server))
        monkeypatch.setattr(login_mod, "webbrowser", MagicMock())

        result = runner.invoke(auth_app, ["login"])

        assert result.exit_code != 0
        assert "authorization failed" in result.stdout.lower() or "user denied" in result.stdout.lower()

    def test_login_callback_no_code_received(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Callback mode exits with error when no authorization code is received."""
        from kstlib.auth.callback import CallbackResult

        mock_provider = MagicMock()
        mock_provider.is_authenticated = False
        mock_provider.get_authorization_url_with_pkce.return_value = (
            "https://idp.test/auth",
            "state-nocode",
            "verifier-nocode",
        )

        mock_server = MagicMock()
        mock_server.wait_for_callback.return_value = CallbackResult(
            code=None,
            state="state-nocode",
            error=None,
        )
        mock_server.__enter__ = MagicMock(return_value=mock_server)
        mock_server.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr(login_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(login_mod, "get_provider", lambda p: mock_provider)
        monkeypatch.setattr(login_mod, "get_callback_server_config", lambda: {"host": "127.0.0.1", "port": 8400})
        monkeypatch.setattr(login_mod, "CallbackServer", MagicMock(return_value=mock_server))
        monkeypatch.setattr(login_mod, "webbrowser", MagicMock())

        result = runner.invoke(auth_app, ["login"])

        assert result.exit_code != 0
        assert "no authorization code" in result.stdout.lower()

    def test_login_callback_state_mismatch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Callback mode exits with error when returned state does not match."""
        from kstlib.auth.callback import CallbackResult

        mock_provider = MagicMock()
        mock_provider.is_authenticated = False
        mock_provider.get_authorization_url_with_pkce.return_value = (
            "https://idp.test/auth",
            "expected-state",
            "verifier-xyz",
        )

        mock_server = MagicMock()
        mock_server.wait_for_callback.return_value = CallbackResult(
            code="valid-code",
            state="tampered-state",
        )
        mock_server.__enter__ = MagicMock(return_value=mock_server)
        mock_server.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr(login_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(login_mod, "get_provider", lambda p: mock_provider)
        monkeypatch.setattr(login_mod, "get_callback_server_config", lambda: {"host": "127.0.0.1", "port": 8400})
        monkeypatch.setattr(login_mod, "CallbackServer", MagicMock(return_value=mock_server))
        monkeypatch.setattr(login_mod, "webbrowser", MagicMock())

        result = runner.invoke(auth_app, ["login"])

        assert result.exit_code != 0
        assert "state mismatch" in result.stdout.lower() or "csrf" in result.stdout.lower()

    def test_login_callback_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Callback mode exits with error when waiting for callback times out."""
        mock_provider = MagicMock()
        mock_provider.is_authenticated = False
        mock_provider.get_authorization_url_with_pkce.return_value = (
            "https://idp.test/auth",
            "state-timeout",
            "verifier-timeout",
        )

        mock_server = MagicMock()
        mock_server.wait_for_callback.side_effect = TimeoutError("timed out")
        mock_server.__enter__ = MagicMock(return_value=mock_server)
        mock_server.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr(login_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(login_mod, "get_provider", lambda p: mock_provider)
        monkeypatch.setattr(login_mod, "get_callback_server_config", lambda: {"host": "127.0.0.1", "port": 8400})
        monkeypatch.setattr(login_mod, "CallbackServer", MagicMock(return_value=mock_server))
        monkeypatch.setattr(login_mod, "webbrowser", MagicMock())

        result = runner.invoke(auth_app, ["login"])

        assert result.exit_code != 0
        assert "timed out" in result.stdout.lower()

    def test_login_callback_quiet_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Callback mode with --quiet suppresses progress messages."""
        from datetime import datetime, timedelta, timezone

        from kstlib.auth.callback import CallbackResult
        from kstlib.auth.models import Token, TokenType

        mock_token = Token(
            access_token="access-quiet-cb",
            token_type=TokenType.BEARER,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scope=[],
        )
        mock_provider = MagicMock()
        mock_provider.is_authenticated = False
        mock_provider.get_authorization_url_with_pkce.return_value = (
            "https://idp.test/auth",
            "state-quiet",
            "verifier-quiet",
        )
        mock_provider.exchange_code.return_value = mock_token

        mock_server = MagicMock()
        mock_server.wait_for_callback.return_value = CallbackResult(
            code="quiet-code",
            state="state-quiet",
        )
        mock_server.__enter__ = MagicMock(return_value=mock_server)
        mock_server.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr(login_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(login_mod, "get_provider", lambda p: mock_provider)
        monkeypatch.setattr(login_mod, "get_callback_server_config", lambda: {"host": "127.0.0.1", "port": 8400})
        monkeypatch.setattr(login_mod, "CallbackServer", MagicMock(return_value=mock_server))
        monkeypatch.setattr(login_mod, "webbrowser", MagicMock())

        result = runner.invoke(auth_app, ["login", "--quiet"])

        assert result.exit_code == 0
        assert "opening browser" not in result.stdout.lower()
        assert "waiting for callback" not in result.stdout.lower()

    # ── login() entry point tests ─────────────────────────────────────────────

    def test_login_force_flag_re_authenticates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """--force flag bypasses already-authenticated check."""
        from datetime import datetime, timedelta, timezone

        from kstlib.auth.callback import CallbackResult
        from kstlib.auth.models import Token, TokenType

        mock_token = Token(
            access_token="access-force",
            token_type=TokenType.BEARER,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scope=[],
        )
        mock_provider = MagicMock()
        # Already authenticated, but --force should bypass the check
        mock_provider.is_authenticated = True
        mock_provider.get_authorization_url_with_pkce.return_value = (
            "https://idp.test/auth",
            "state-force",
            "verifier-force",
        )
        mock_provider.exchange_code.return_value = mock_token

        mock_server = MagicMock()
        mock_server.wait_for_callback.return_value = CallbackResult(
            code="force-code",
            state="state-force",
        )
        mock_server.__enter__ = MagicMock(return_value=mock_server)
        mock_server.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr(login_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(login_mod, "get_provider", lambda p: mock_provider)
        monkeypatch.setattr(login_mod, "get_callback_server_config", lambda: {"host": "127.0.0.1", "port": 8400})
        monkeypatch.setattr(login_mod, "CallbackServer", MagicMock(return_value=mock_server))
        monkeypatch.setattr(login_mod, "webbrowser", MagicMock())

        result = runner.invoke(auth_app, ["login", "--force"])

        assert result.exit_code == 0
        # Should NOT show "already authenticated" message
        assert "already" not in result.stdout.lower()

    def test_login_already_authenticated_quiet(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Already-authenticated message is shorter in --quiet mode."""
        mock_provider = MagicMock()
        mock_provider.is_authenticated = True

        monkeypatch.setattr(login_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(login_mod, "get_provider", lambda p: mock_provider)

        result = runner.invoke(auth_app, ["login", "--quiet"])

        assert result.exit_code == 0
        assert "already authenticated" in result.stdout.lower()

    def test_login_token_exchange_error_at_top_level(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TokenExchangeError raised in callback mode is caught at top level."""
        from kstlib.auth.errors import TokenExchangeError

        mock_provider = MagicMock()
        mock_provider.is_authenticated = False
        mock_provider.get_authorization_url_with_pkce.return_value = (
            "https://idp.test/auth",
            "state-te",
            "verifier-te",
        )

        mock_server = MagicMock()
        mock_server.wait_for_callback.return_value = MagicMock(
            error=None,
            code="te-code",
            state="state-te",
        )
        mock_server.__enter__ = MagicMock(return_value=mock_server)
        mock_server.__exit__ = MagicMock(return_value=False)

        mock_provider.exchange_code.side_effect = TokenExchangeError("server_error")

        monkeypatch.setattr(login_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(login_mod, "get_provider", lambda p: mock_provider)
        monkeypatch.setattr(login_mod, "get_callback_server_config", lambda: {"host": "127.0.0.1", "port": 8400})
        monkeypatch.setattr(login_mod, "CallbackServer", MagicMock(return_value=mock_server))
        monkeypatch.setattr(login_mod, "webbrowser", MagicMock())

        result = runner.invoke(auth_app, ["login"])

        assert result.exit_code != 0
        assert "token exchange failed" in result.stdout.lower()

    def test_login_auth_error_at_top_level(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AuthError raised during login is caught and displayed."""
        from kstlib.auth.errors import AuthError

        mock_provider = MagicMock()
        mock_provider.is_authenticated = False
        mock_provider.get_authorization_url_with_pkce.side_effect = AuthError("auth backend unavailable")

        monkeypatch.setattr(login_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(login_mod, "get_provider", lambda p: mock_provider)
        monkeypatch.setattr(login_mod, "get_callback_server_config", lambda: {"host": "127.0.0.1", "port": 8400})

        mock_server = MagicMock()
        mock_server.__enter__ = MagicMock(return_value=mock_server)
        mock_server.__exit__ = MagicMock(return_value=False)
        monkeypatch.setattr(login_mod, "CallbackServer", MagicMock(return_value=mock_server))
        monkeypatch.setattr(login_mod, "webbrowser", MagicMock())

        result = runner.invoke(auth_app, ["login"])

        assert result.exit_code != 0
        assert "authentication failed" in result.stdout.lower()

    def test_login_keyboard_interrupt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KeyboardInterrupt during login is caught and shows cancellation message."""
        mock_provider = MagicMock()
        mock_provider.is_authenticated = False
        mock_provider.get_authorization_url_with_pkce.return_value = (
            "https://idp.test/auth",
            "state-ki",
            "verifier-ki",
        )

        mock_server = MagicMock()
        mock_server.wait_for_callback.side_effect = KeyboardInterrupt()
        mock_server.__enter__ = MagicMock(return_value=mock_server)
        mock_server.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr(login_mod, "resolve_provider_name", lambda p: "test-provider")
        monkeypatch.setattr(login_mod, "get_provider", lambda p: mock_provider)
        monkeypatch.setattr(login_mod, "get_callback_server_config", lambda: {"host": "127.0.0.1", "port": 8400})
        monkeypatch.setattr(login_mod, "CallbackServer", MagicMock(return_value=mock_server))
        monkeypatch.setattr(login_mod, "webbrowser", MagicMock())

        result = runner.invoke(auth_app, ["login"])

        assert result.exit_code != 0
        assert "cancelled" in result.stdout.lower()


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

    def test_check_inherits_ssl_ca_bundle_from_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Passes provider ssl_ca_bundle to httpx.Client verify parameter."""
        captured_kwargs: dict[str, object] = {}

        original_client = __import__("httpx").Client

        def spy_client(**kwargs: object) -> object:
            captured_kwargs.update(kwargs)
            return original_client()

        monkeypatch.setattr("httpx.Client", spy_client)

        mock_provider = MagicMock()
        mock_provider.get_token.return_value = Token(
            access_token="tok",
            token_type="Bearer",
            id_token="a.b.c",
        )
        mock_provider.config = MagicMock()
        mock_provider.config.ssl_ca_bundle = "/path/to/corporate-ca.pem"
        mock_provider.config.ssl_verify = True
        mock_provider.config.issuer = "https://idp.test"
        mock_provider.config.client_id = "test-client"

        monkeypatch.setattr(check_mod, "resolve_provider_name", lambda _p: "test")
        monkeypatch.setattr(check_mod, "get_provider", lambda _p: mock_provider)

        runner.invoke(auth_app, ["check"])

        assert captured_kwargs.get("verify") == "/path/to/corporate-ca.pem"

    def test_check_inherits_ssl_verify_false_from_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Passes provider ssl_verify=False to httpx.Client verify parameter."""
        captured_kwargs: dict[str, object] = {}

        original_client = __import__("httpx").Client

        def spy_client(**kwargs: object) -> object:
            captured_kwargs.update(kwargs)
            return original_client()

        monkeypatch.setattr("httpx.Client", spy_client)

        mock_provider = MagicMock()
        mock_provider.get_token.return_value = Token(
            access_token="tok",
            token_type="Bearer",
            id_token="a.b.c",
        )
        mock_provider.config = MagicMock()
        mock_provider.config.ssl_ca_bundle = None
        mock_provider.config.ssl_verify = False
        mock_provider.config.issuer = "https://idp.test"
        mock_provider.config.client_id = "test-client"

        monkeypatch.setattr(check_mod, "resolve_provider_name", lambda _p: "test")
        monkeypatch.setattr(check_mod, "get_provider", lambda _p: mock_provider)

        runner.invoke(auth_app, ["check"])

        assert captured_kwargs.get("verify") is False

    def test_check_ssl_fallback_without_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Falls back to build_ssl_context() when using explicit --token."""
        captured_kwargs: dict[str, object] = {}
        sentinel = object()

        original_client = __import__("httpx").Client

        def spy_client(**kwargs: object) -> object:
            captured_kwargs.update(kwargs)
            return original_client()

        monkeypatch.setattr("httpx.Client", spy_client)
        monkeypatch.setattr(check_mod, "build_ssl_context", lambda: sentinel)

        runner.invoke(auth_app, ["check", "--token", "a.b.c"])

        assert captured_kwargs.get("verify") is sentinel
