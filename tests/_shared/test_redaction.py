"""Tests for kstlib._shared.redaction helpers."""

from __future__ import annotations

import re


from kstlib._shared.redaction import (
    DEFAULT_URL_SENSITIVE_QUERY_KEYS,
    mask_url,
    mask_webhook_url,
    redact_sensitive,
)


class TestRedactSensitive:
    """Tests for redact_sensitive() pattern-based redaction."""

    def test_redact_aws_arn(self) -> None:
        """Redact AWS ARN to [REDACTED_ARN]."""
        message = "boto3 ClientError on arn:aws:kms:us-east-1:123456789012:key/abcd-1234"
        redacted = redact_sensitive(message)
        assert "arn:aws" not in redacted
        assert "[REDACTED_ARN]" in redacted

    def test_redact_aws_access_key(self) -> None:
        """Redact AKIA-prefixed access key id."""
        message = "Access denied for AKIA1234567890ABCDEF in region"
        redacted = redact_sensitive(message)
        assert "AKIA1234567890ABCDEF" not in redacted
        assert "[REDACTED_AWS_KEY]" in redacted

    def test_redact_home_path(self) -> None:
        """Redact /home/user/... paths leaking username."""
        message = "Config not found at /home/alice/.sas/credentials.json"
        redacted = redact_sensitive(message)
        assert "alice" not in redacted
        assert "[REDACTED_PATH]" in redacted

    def test_redact_users_path(self) -> None:
        """Redact /Users/foo/... paths (macOS)."""
        message = "Failed to read /Users/bob/secrets.yml"
        redacted = redact_sensitive(message)
        assert "bob" not in redacted
        assert "[REDACTED_PATH]" in redacted

    def test_redact_authorization_bearer(self) -> None:
        """Redact Bearer token in Authorization header."""
        message = "headers={'Authorization: Bearer sk_live_abc123def456'}"
        redacted = redact_sensitive(message)
        assert "sk_live_abc123def456" not in redacted
        assert "[REDACTED]" in redacted

    def test_redact_cli_password(self) -> None:
        """Redact --password flag value."""
        message = "running curl --password mySecret123 -u user"
        redacted = redact_sensitive(message)
        assert "mySecret123" not in redacted
        assert "[REDACTED]" in redacted

    def test_redact_cli_api_key(self) -> None:
        """Redact --api-key flag value (with hyphen, underscore, or equals)."""
        message1 = "tool --api-key abcXYZ"
        message2 = "tool --api_key=abcXYZ"
        for msg in (message1, message2):
            redacted = redact_sensitive(msg)
            assert "abcXYZ" not in redacted

    def test_redact_url_userinfo(self) -> None:
        """Redact user:password in URL userinfo."""
        message = "Connecting to https://admin:hunter2@db.host.com/db"
        redacted = redact_sensitive(message)
        assert "admin:hunter2" not in redacted
        assert "[REDACTED]@db.host.com" in redacted

    def test_redact_no_match_returns_unchanged(self) -> None:
        """Message without sensitive patterns is unchanged."""
        message = "Connection timeout after 30s"
        assert redact_sensitive(message) == message

    def test_redact_empty_message(self) -> None:
        """Empty input returns empty output."""
        assert redact_sensitive("") == ""

    def test_redact_additional_patterns(self) -> None:
        """Caller can supply additional (pattern, replacement) pairs."""
        custom = ((re.compile(r"INTERNAL-\d{4}"), "[REDACTED_INTERNAL_ID]"),)
        message = "request id INTERNAL-1234 failed"
        redacted = redact_sensitive(message, additional_patterns=custom)
        assert "INTERNAL-1234" not in redacted
        assert "[REDACTED_INTERNAL_ID]" in redacted


class TestMaskWebhookUrl:
    """Tests for mask_webhook_url() across providers."""

    def test_mask_slack_full(self) -> None:
        """Slack webhook : keep host + first letter of each token."""
        url = "https://hooks.slack.com/services/T123ABC/B456DEF/xyzSecret123"
        masked = mask_webhook_url(url)
        assert masked == "https://hooks.slack.com/services/T***/B***/***"

    def test_mask_slack_partial_path(self) -> None:
        """Slack URL without full token path returns generic mask."""
        url = "https://hooks.slack.com/services/"
        masked = mask_webhook_url(url)
        assert "hooks.slack.com" in masked
        assert "***" in masked

    def test_mask_discord(self) -> None:
        """Discord webhook : preserve host, mask all path segments."""
        url = "https://discord.com/api/webhooks/1234567890/abcdefgSecret"
        masked = mask_webhook_url(url)
        assert "abcdefgSecret" not in masked
        assert "discord.com" in masked

    def test_mask_teams(self) -> None:
        """Teams webhook : preserve host, mask all path."""
        url = "https://webhook.office.com/abc/def/ghi"
        masked = mask_webhook_url(url)
        assert "webhook.office.com" in masked
        assert "ghi" not in masked

    def test_mask_empty(self) -> None:
        """Empty URL returns ***."""
        assert mask_webhook_url("") == "***"

    def test_mask_unknown_host(self) -> None:
        """Non-recognized host returns *** (conservative default)."""
        assert mask_webhook_url("https://example.com/hook") == "***"


class TestMaskUrl:
    """Tests for mask_url() URL credentials and query params."""

    def test_mask_userinfo(self) -> None:
        """user:pass@host -> [REDACTED]@host."""
        url = "https://user:secret@host.com/path"
        masked = mask_url(url)
        assert "user:secret" not in masked
        assert "[REDACTED]@host.com" in masked

    def test_mask_query_token(self) -> None:
        """?token=xxx is redacted while keeping the key visible."""
        url = "https://host.com/?token=secret123"
        masked = mask_url(url)
        assert "secret123" not in masked
        assert "token=[REDACTED]" in masked

    def test_mask_query_multiple_keys(self) -> None:
        """Multiple sensitive query keys are all redacted; non-sensitive preserved."""
        url = "https://host.com/api?api_key=abc&page=1&token=xyz"
        masked = mask_url(url)
        assert "abc" not in masked
        assert "xyz" not in masked
        assert "page=1" in masked

    def test_mask_query_case_insensitive(self) -> None:
        """Sensitive key matching is case-insensitive."""
        url = "https://host.com/?TOKEN=xyz&Api_Key=abc"
        masked = mask_url(url)
        assert "xyz" not in masked
        assert "abc" not in masked

    def test_mask_websocket_with_token(self) -> None:
        """wss:// URL with credentials and query token."""
        url = "wss://user:pass@host.com:8080/ws?token=secret"
        masked = mask_url(url)
        assert "user:pass" not in masked
        assert "secret" not in masked
        assert "[REDACTED]@host.com:8080" in masked
        assert "token=[REDACTED]" in masked

    def test_mask_no_credentials_unchanged(self) -> None:
        """URL without credentials or sensitive query is unchanged."""
        url = "https://host.com/api?page=2&size=10"
        assert mask_url(url) == url

    def test_mask_empty_returns_empty(self) -> None:
        """Empty URL returns empty."""
        assert mask_url("") == ""

    def test_mask_no_scheme_unchanged(self) -> None:
        """String without scheme returns unchanged (best-effort)."""
        url = "host.com/path"
        assert mask_url(url) == url

    def test_mask_custom_sensitive_keys(self) -> None:
        """Caller can supply custom set of sensitive query keys."""
        url = "https://host.com/?my_secret=abc&token=xyz"
        custom_keys = frozenset({"my_secret"})
        masked = mask_url(url, sensitive_query_keys=custom_keys)
        assert "abc" not in masked
        assert "token=xyz" in masked  # not in custom set, kept

    def test_default_sensitive_keys_includes_oauth(self) -> None:
        """OAuth-related keys are in the default sensitive set."""
        for key in ("access_token", "refresh_token", "code", "client_secret"):
            assert key in DEFAULT_URL_SENSITIVE_QUERY_KEYS

    def test_mask_query_without_value(self) -> None:
        """Query param without value (e.g. '?flag') is preserved as-is."""
        url = "https://host.com/?flag&token=xyz"
        masked = mask_url(url)
        assert "flag" in masked
        assert "xyz" not in masked

    def test_mask_preserves_fragment(self) -> None:
        """Fragment is preserved through masking."""
        url = "https://host.com/path?token=xyz#section1"
        masked = mask_url(url)
        assert "#section1" in masked
        assert "xyz" not in masked
