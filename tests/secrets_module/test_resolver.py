"""Tests for the secrets resolver helpers."""

from __future__ import annotations

# pylint: disable=missing-function-docstring,missing-class-docstring,protected-access
import types
from typing import Any

import pytest

import kstlib.secrets.providers as providers_module
from kstlib.secrets import resolver as resolver_module
from kstlib.secrets.exceptions import SecretNotFoundError
from kstlib.secrets.models import SecretRecord, SecretRequest, SecretSource
from kstlib.secrets.providers import register_provider
from kstlib.secrets.providers.base import SecretProvider
from kstlib.secrets.providers.sops import SOPSProvider
from kstlib.secrets.resolver import SecretResolver, get_secret_resolver, resolve_secret


@pytest.fixture(autouse=True)
def reset_provider_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure provider registry mutations do not leak between tests."""

    monkeypatch.setattr(
        providers_module,
        "_REGISTRY",
        providers_module._REGISTRY.copy(),
        raising=False,
    )


class DummyProvider(SecretProvider):
    """Provider returning a predetermined value."""

    name = "dummy"

    def __init__(self, *, value: Any | None) -> None:
        self._value = value

    def resolve(self, request: SecretRequest) -> SecretRecord | None:
        if self._value is None:
            return None
        return SecretRecord(
            value=self._value,
            source=SecretSource.KWARGS,
            metadata={"requested": request.name},
        )


def _make_dummy_provider(**kwargs: Any) -> SecretProvider:
    return DummyProvider(**kwargs)


def _make_dummy_null_provider(**_: Any) -> SecretProvider:
    return DummyProvider(value=None)


register_provider("dummy", _make_dummy_provider)
register_provider("dummy-null", _make_dummy_null_provider)


def test_resolve_secret_returns_provider_value() -> None:
    record = resolve_secret(
        "smtp.password",
        config={"providers": [{"name": "dummy", "options": {"value": "hunter2"}}]},
    )

    assert record.value == "hunter2"
    assert record.source is SecretSource.KWARGS
    assert record.metadata["requested"] == "smtp.password"


def test_resolve_secret_uses_default_when_not_required() -> None:
    record = resolve_secret(
        "missing.secret",
        config={"providers": [{"name": "dummy-null"}]},
        required=False,
        default="fallback",
    )

    assert record.value == "fallback"
    assert record.source is SecretSource.DEFAULT


def test_resolve_secret_raises_when_required_and_missing() -> None:
    with pytest.raises(SecretNotFoundError):
        resolve_secret("missing.secret", config={"providers": [{"name": "dummy-null"}]})


def test_get_secret_resolver_attaches_sops_provider_when_configured(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    secrets_dir = tmp_path_factory.mktemp("secrets")
    secrets_path = secrets_dir / "credentials.sops.yml"
    resolver = get_secret_resolver({"sops": {"path": secrets_path}})

    assert any(isinstance(provider, SOPSProvider) for provider in resolver._providers)


def test_secret_resolver_returns_default_record_when_not_required() -> None:
    resolver = SecretResolver([])
    record = resolver.resolve(
        SecretRequest(name="missing", scope=None, required=False, default="fallback"),
    )

    assert record.value == "fallback"
    assert record.source is SecretSource.DEFAULT
    assert record.metadata == {"resolver": "default"}


def test_secret_resolver_default_record_includes_custom_name() -> None:
    resolver = SecretResolver([], name="secrets")
    record = resolver.resolve(
        SecretRequest(name="example", scope=None, required=False, default=None),
    )

    assert record.source is SecretSource.DEFAULT
    assert record.metadata == {"resolver": "secrets"}


@pytest.mark.asyncio
async def test_secret_resolver_async_raises_when_required() -> None:
    resolver = SecretResolver([])
    request = SecretRequest(name="missing", scope=None, required=True, default=None)

    with pytest.raises(SecretNotFoundError):
        await resolver.resolve_async(request)


@pytest.mark.asyncio
async def test_secret_resolver_async_returns_default_metadata() -> None:
    resolver = SecretResolver([])
    record = await resolver.resolve_async(
        SecretRequest(name="missing", scope=None, required=False, default="value"),
    )

    assert record.value == "value"
    assert record.source is SecretSource.DEFAULT
    assert record.metadata == {"resolver": "default", "async": True}


@pytest.mark.asyncio
async def test_secret_provider_default_resolve_async_uses_thread() -> None:
    class AsyncProbeProvider(SecretProvider):
        name = "probe"

        def __init__(self) -> None:
            self.calls = 0

        def resolve(self, request: SecretRequest) -> SecretRecord | None:
            self.calls += 1
            return SecretRecord(value="ok", source=SecretSource.KWARGS, metadata={})

    provider = AsyncProbeProvider()
    request = SecretRequest(name="value", scope=None, required=True, default=None)
    record = await provider.resolve_async(request)

    assert record is not None
    assert record.value == "ok"
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_secret_resolver_async_returns_provider_record() -> None:
    class AsyncOnlyProvider(SecretProvider):
        name = "async-only"

        def resolve(self, request: SecretRequest) -> SecretRecord | None:
            return None

        async def resolve_async(self, request: SecretRequest) -> SecretRecord | None:
            return SecretRecord(value="async", source=SecretSource.KWARGS, metadata={"requested": request.name})

    resolver = SecretResolver([AsyncOnlyProvider()])
    request = SecretRequest(name="value", scope=None, required=True, default=None)

    record = await resolver.resolve_async(request)

    assert record.value == "async"
    assert record.metadata == {"requested": "value"}


@pytest.mark.asyncio
async def test_secret_resolver_async_optional_without_default_returns_none() -> None:
    resolver = SecretResolver([])
    request = SecretRequest(name="missing", scope=None, required=False, default=None)

    record = await resolver.resolve_async(request)

    assert record.value is None
    assert record.metadata == {"resolver": "default", "async": True}


def test_secret_provider_base_configure_handles_settings() -> None:
    class ConfigProbeProvider(SecretProvider):
        name = "config-probe"

        def resolve(self, request: SecretRequest) -> SecretRecord | None:
            return None

    provider = ConfigProbeProvider()

    provider.configure(None)
    provider.configure({})
    provider.configure({"ignored": True})


def test_secret_resolver_exposes_name_property() -> None:
    resolver = SecretResolver([], name="accounts")

    assert resolver.name == "accounts"


def test_get_secret_resolver_with_custom_provider_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_settings: list[dict[str, Any] | None] = []

    class TrackingProvider(SecretProvider):
        name = "tracking"

        def __init__(self) -> None:
            self.resolved: list[SecretRequest] = []

        def resolve(self, request: SecretRequest) -> SecretRecord | None:
            self.resolved.append(request)
            return SecretRecord(value="ok", source=SecretSource.KWARGS, metadata={})

    def fake_get_provider(name: str, **_: Any) -> SecretProvider:
        assert name == "tracking"
        return TrackingProvider()

    def fake_configure_provider(provider: SecretProvider, settings: dict[str, Any] | None) -> SecretProvider:
        captured_settings.append(settings)
        provider.configure(settings)
        return provider

    monkeypatch.setattr(resolver_module, "get_provider", fake_get_provider)
    monkeypatch.setattr(resolver_module, "configure_provider", fake_configure_provider)

    resolver = get_secret_resolver(
        {
            "providers": [
                {
                    "name": "tracking",
                    "settings": {"prefix": "svc"},
                    "options": {"extra": True},
                }
            ]
        }
    )

    record = resolver.resolve(SecretRequest(name="value", scope=None, required=True, default=None))

    assert record.value == "ok"
    assert captured_settings == [{"prefix": "svc"}]


def test_get_secret_resolver_missing_provider_name_raises() -> None:
    with pytest.raises(ValueError):
        get_secret_resolver({"providers": [{}]})


def test_build_sops_provider_applies_alias_and_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_options: dict[str, Any] = {}
    captured_settings: list[dict[str, Any] | None] = []
    provider = DummyProvider(value="ignored")

    def fake_get_provider(name: str, **options: Any) -> SecretProvider:
        assert name == "sops"
        captured_options.update(options)
        return provider

    def fake_configure_provider(instance: SecretProvider, settings: dict[str, Any] | None) -> SecretProvider:
        captured_settings.append(settings)
        instance.configure(settings)
        return instance

    monkeypatch.setattr(resolver_module, "get_provider", fake_get_provider)
    monkeypatch.setattr(resolver_module, "configure_provider", fake_configure_provider)

    result = resolver_module._build_sops_provider(
        {
            "path": "secrets.enc",
            "format": "json",
            "settings": {"binary": "custom-sops"},
        }
    )

    assert result is provider
    assert captured_options == {"path": "secrets.enc", "document_format": "json"}
    assert captured_settings == [{"binary": "custom-sops"}]


def test_build_sops_provider_accepts_binary_option(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_options: dict[str, Any] = {}
    provider = DummyProvider(value="ignored")

    def fake_get_provider(name: str, **options: Any) -> SecretProvider:
        assert name == "sops"
        captured_options.update(options)
        return provider

    monkeypatch.setattr(resolver_module, "get_provider", fake_get_provider)

    result = resolver_module._build_sops_provider(
        {
            "path": "secrets.enc",
            "binary": "custom-sops",
        }
    )

    assert result is provider
    assert captured_options == {"path": "secrets.enc", "binary": "custom-sops"}


def test_resolve_secret_uses_global_config(monkeypatch: pytest.MonkeyPatch) -> None:
    class GlobalConfig:
        def __init__(self, data: dict[str, Any]) -> None:
            self.secrets = types.SimpleNamespace(to_dict=lambda: data)

    config = {"providers": [{"name": "dummy", "options": {"value": "from-config"}}]}

    monkeypatch.setattr(resolver_module, "get_config", lambda: GlobalConfig(config))

    record = resolve_secret("smtp.password")

    assert record.value == "from-config"


def test_resolve_secret_rejects_unexpected_kwargs() -> None:
    """Ensure resolve_secret raises when unsupported kwargs are provided."""

    with pytest.raises(TypeError) as excinfo:
        resolve_secret(
            "smtp.password",
            config={"providers": [{"name": "dummy-null"}]},
            unexpected=True,
        )

    assert "unexpected" in str(excinfo.value)
