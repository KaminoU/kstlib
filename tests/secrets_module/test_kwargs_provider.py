"""Tests for the KwargsProvider."""

from __future__ import annotations

import pytest

from kstlib.secrets.models import SecretRequest, SecretSource
from kstlib.secrets.providers.kwargs import KwargsProvider
from kstlib.secrets.resolver import resolve_secret


class TestKwargsProvider:
    """Tests for KwargsProvider class."""

    def test_resolve_returns_secret_when_present(self) -> None:
        """Returns a record when the secret is in the kwargs."""
        provider = KwargsProvider({"api.key": "test-value"})
        request = SecretRequest(name="api.key")

        record = provider.resolve(request)

        assert record is not None
        assert record.value == "test-value"
        assert record.source == SecretSource.KWARGS

    def test_resolve_returns_none_when_missing(self) -> None:
        """Returns None when secret is not in kwargs."""
        provider = KwargsProvider({"other.key": "value"})
        request = SecretRequest(name="api.key")

        record = provider.resolve(request)

        assert record is None

    def test_resolve_with_empty_provider(self) -> None:
        """Returns None when provider has no secrets."""
        provider = KwargsProvider()
        request = SecretRequest(name="api.key")

        record = provider.resolve(request)

        assert record is None

    def test_set_adds_secret(self) -> None:
        """Set method adds a new secret."""
        provider = KwargsProvider()
        provider.set("api.key", "new-value")
        request = SecretRequest(name="api.key")

        record = provider.resolve(request)

        assert record is not None
        assert record.value == "new-value"

    def test_set_updates_existing_secret(self) -> None:
        """Set method updates an existing secret."""
        provider = KwargsProvider({"api.key": "old-value"})
        provider.set("api.key", "new-value")
        request = SecretRequest(name="api.key")

        record = provider.resolve(request)

        assert record is not None
        assert record.value == "new-value"

    def test_remove_deletes_secret(self) -> None:
        """Remove method deletes an existing secret."""
        provider = KwargsProvider({"api.key": "value"})

        result = provider.remove("api.key")

        assert result is True
        assert provider.resolve(SecretRequest(name="api.key")) is None

    def test_remove_returns_false_for_missing(self) -> None:
        """Remove returns False when secret doesn't exist."""
        provider = KwargsProvider()

        result = provider.remove("missing.key")

        assert result is False

    def test_clear_removes_all_secrets(self) -> None:
        """Clear removes all secrets from the provider."""
        provider = KwargsProvider({"key1": "v1", "key2": "v2"})

        provider.clear()

        assert provider.resolve(SecretRequest(name="key1")) is None
        assert provider.resolve(SecretRequest(name="key2")) is None

    def test_configure_merges_additional_secrets(self) -> None:
        """Configure merges new secrets from settings."""
        provider = KwargsProvider({"existing": "value"})

        provider.configure({"secrets": {"new.key": "new-value"}})

        assert provider.resolve(SecretRequest(name="existing")) is not None
        assert provider.resolve(SecretRequest(name="new.key")) is not None

    def test_configure_with_none_is_noop(self) -> None:
        """Configure with None does nothing."""
        provider = KwargsProvider({"key": "value"})

        provider.configure(None)

        assert provider.resolve(SecretRequest(name="key")) is not None


class TestResolveSecretWithKwargs:
    """Integration tests for resolve_secret with secrets parameter."""

    def test_secrets_override_takes_precedence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Secrets parameter overrides other providers."""
        # Set up env var that would normally be found
        monkeypatch.setenv("KSTLIB__API__KEY", "env-value")

        record = resolve_secret(
            "api.key",
            secrets={"api.key": "override-value"},
            config={},  # Empty config to avoid loading global
        )

        assert record.value == "override-value"
        assert record.source == SecretSource.KWARGS

    def test_falls_through_when_not_in_secrets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Falls through to next provider when not in secrets."""
        monkeypatch.setenv("KSTLIB__API__KEY", "env-value")

        record = resolve_secret(
            "api.key",
            secrets={"other.key": "other-value"},
            config={},
        )

        assert record.value == "env-value"
        assert record.source == SecretSource.ENVIRONMENT

    def test_no_secrets_parameter_uses_normal_cascade(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without secrets parameter, uses normal provider cascade."""
        monkeypatch.setenv("KSTLIB__API__KEY", "env-value")

        record = resolve_secret("api.key", config={})

        assert record.value == "env-value"
        assert record.source == SecretSource.ENVIRONMENT
