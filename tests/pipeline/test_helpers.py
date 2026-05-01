"""Tests for kstlib.pipeline.steps._helpers."""

from __future__ import annotations

from kstlib.pipeline.steps._helpers import _sanitize_command


class TestSanitizeCommand:
    """Tests for _sanitize_command() pattern-based redaction."""

    def test_authorization_bearer_header(self) -> None:
        """Authorization Bearer token in -H flag is redacted."""
        cmd = "curl -H 'Authorization: Bearer sk_live_abc123' https://api.example.com"
        sanitized = _sanitize_command(cmd)
        assert "sk_live_abc123" not in sanitized
        assert "[REDACTED]" in sanitized

    def test_authorization_basic_header(self) -> None:
        """Authorization Basic credential is redacted."""
        cmd = 'curl -H "Authorization: Basic dXNlcjpwYXNz" https://api.example.com'
        sanitized = _sanitize_command(cmd)
        assert "dXNlcjpwYXNz" not in sanitized

    def test_password_flag_with_space(self) -> None:
        """--password value form is redacted."""
        cmd = "tool --password mySecret123 --user admin"
        sanitized = _sanitize_command(cmd)
        assert "mySecret123" not in sanitized
        assert "[REDACTED]" in sanitized

    def test_password_flag_with_equals(self) -> None:
        """--password=value form is redacted."""
        cmd = "tool --password=mySecret123"
        sanitized = _sanitize_command(cmd)
        assert "mySecret123" not in sanitized

    def test_api_key_variants(self) -> None:
        """--api-key, --api_key, --apikey are all redacted."""
        for flag in ("--api-key", "--api_key", "--apikey"):
            cmd = f"tool {flag} myToken123"
            sanitized = _sanitize_command(cmd)
            assert "myToken123" not in sanitized, f"flag={flag!r} did not redact"

    def test_token_flag(self) -> None:
        """--token value is redacted."""
        cmd = "tool --token myToken123"
        sanitized = _sanitize_command(cmd)
        assert "myToken123" not in sanitized

    def test_secret_flag(self) -> None:
        """--secret value is redacted."""
        cmd = "tool --secret mySuperSecret"
        sanitized = _sanitize_command(cmd)
        assert "mySuperSecret" not in sanitized

    def test_sshpass(self) -> None:
        """sshpass -p <password> is redacted."""
        cmd = "sshpass -p MyPa55word ssh user@host"
        sanitized = _sanitize_command(cmd)
        assert "MyPa55word" not in sanitized
        assert "[REDACTED]" in sanitized

    def test_url_with_userinfo(self) -> None:
        """URL with userinfo (user:pass@host) is redacted."""
        cmd = "curl https://admin:hunter2@db.host.com/path"
        sanitized = _sanitize_command(cmd)
        assert "admin:hunter2" not in sanitized
        assert "[REDACTED]@db.host.com" in sanitized

    def test_pgpassword_inline_env(self) -> None:
        """PGPASSWORD=value inline env-var prefix is redacted."""
        cmd = "PGPASSWORD=hunter2 psql -h host -U user"
        sanitized = _sanitize_command(cmd)
        assert "hunter2" not in sanitized
        assert "[REDACTED]" in sanitized

    def test_mysql_pwd_inline_env(self) -> None:
        """MYSQL_PWD=value inline env-var prefix is redacted."""
        cmd = "MYSQL_PWD=secret123 mysql -h host"
        sanitized = _sanitize_command(cmd)
        assert "secret123" not in sanitized

    def test_argv_list_input(self) -> None:
        """Sequence input is joined and redacted."""
        cmd = ["curl", "--password", "secret123", "https://host"]
        sanitized = _sanitize_command(cmd)
        assert "secret123" not in sanitized
        assert "curl" in sanitized

    def test_innocuous_command_unchanged(self) -> None:
        """Commands without sensitive patterns are returned as-is."""
        cmd = "echo hello world"
        assert _sanitize_command(cmd) == cmd

    def test_empty_command(self) -> None:
        """Empty input returns empty string."""
        assert _sanitize_command("") == ""

    def test_argv_with_non_string_parts(self) -> None:
        """Non-string parts in argv are stringified.

        The signature is ``Sequence[str]`` but we exercise the str()
        coercion defensively in case a caller passes mixed types.
        """
        cmd = ["echo", 42, None, "done"]
        sanitized = _sanitize_command(cmd)  # type: ignore[arg-type]
        assert "echo" in sanitized
        assert "42" in sanitized
        assert "done" in sanitized
