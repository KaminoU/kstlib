"""Tests for individual secret providers."""

from __future__ import annotations

# pylint: disable=missing-function-docstring,missing-class-docstring,unnecessary-lambda,protected-access
import types
from collections import OrderedDict
from pathlib import Path
from typing import Any

import pytest
import yaml

import kstlib.secrets.providers.keyring as keyring_module
from kstlib.secrets.exceptions import SecretDecryptionError
from kstlib.secrets.models import SecretRequest, SecretSource
from kstlib.secrets.providers import configure_provider, get_provider
from kstlib.secrets.providers.environment import EnvironmentProvider
from kstlib.secrets.providers.keyring import KeyringProvider
from kstlib.secrets.providers.sops import SOPSProvider


def test_environment_provider_resolves_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify EnvironmentProvider resolves a secret from the environment."""
    provider = EnvironmentProvider(prefix="APP_", delimiter="__")
    request = SecretRequest(name="api.token", scope="prod", required=True, default=None)
    monkeypatch.setenv("APP__PROD__API__TOKEN", "secret")

    record = provider.resolve(request)

    assert record is not None
    assert record.value == "secret"
    assert record.source is SecretSource.ENVIRONMENT
    assert record.metadata == {"env_key": "APP__PROD__API__TOKEN"}


def test_environment_provider_respects_configure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify configure() updates prefix and delimiter used for key construction."""
    provider = EnvironmentProvider()
    provider.configure(None)
    provider.configure({"prefix": "svc", "delimiter": "-"})
    request = SecretRequest(name="password", scope="billing", required=False, default=None)
    monkeypatch.setenv("SVC-BILLING-PASSWORD", "value")

    record = provider.resolve(request)

    assert record is not None
    assert record.metadata == {"env_key": "SVC-BILLING-PASSWORD"}


def test_environment_provider_returns_none_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify EnvironmentProvider returns None when the environment variable is absent."""
    provider = EnvironmentProvider(prefix="ENV_", delimiter="__")
    request = SecretRequest(name="missing", scope=None, required=False, default=None)

    monkeypatch.delenv("ENV__MISSING", raising=False)

    record = provider.resolve(request)

    assert record is None


def test_keyring_provider_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify KeyringProvider stores, resolves, and deletes a secret correctly."""
    storage: dict[tuple[str, str], str] = {}

    def get_password(service: str, username: str) -> str | None:
        return storage.get((service, username))

    def set_password(service: str, username: str, value: str) -> None:
        storage[(service, username)] = value

    def delete_password(service: str, username: str) -> None:
        storage.pop((service, username), None)

    fake_keyring = types.SimpleNamespace(
        get_password=get_password,
        set_password=set_password,
        delete_password=delete_password,
    )

    monkeypatch.setattr(keyring_module, "keyring_backend", fake_keyring)

    provider = KeyringProvider(service="kst")
    provider.configure(None)
    provider.configure({"service": "kstlib"})
    request = SecretRequest(name="token", scope="jobs", required=True, default=None)

    provider.store(request, "abc")
    record = provider.resolve(request)
    provider.delete(request)

    assert record is not None
    assert record.value == "abc"
    assert record.metadata == {"service": "kstlib", "username": "jobs:token"}
    assert not storage


def test_keyring_provider_handles_missing_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify KeyringProvider raises RuntimeError when no keyring backend is available."""
    monkeypatch.setattr(keyring_module, "keyring_backend", None)

    provider = KeyringProvider()
    request = SecretRequest(name="secret", scope=None, required=False, default=None)

    assert provider.resolve(request) is None
    with pytest.raises(RuntimeError):
        provider.store(request, "value")
    with pytest.raises(RuntimeError):
        provider.delete(request)


def test_keyring_provider_returns_none_when_value_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify KeyringProvider returns None when the backend holds no entry."""

    def get_password(*_: Any) -> None:
        return None

    fake_keyring = types.SimpleNamespace(
        get_password=get_password,
        set_password=lambda *_: None,
        delete_password=lambda *_: None,
    )

    monkeypatch.setattr(keyring_module, "keyring_backend", fake_keyring)

    provider = KeyringProvider(service="svc")
    request = SecretRequest(name="token", scope="ops", required=False, default=None)

    assert provider.resolve(request) is None


def test_sops_provider_resolve_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify SOPSProvider decrypts and resolves a nested JSON secret."""
    payload = '{"smtp": {"password": "hunter2"}}'
    secret_file = tmp_path / "secrets.enc"
    secret_file.write_text("encrypted")

    monkeypatch.setattr(
        "kstlib.secrets.providers.sops.shutil.which",
        lambda binary: "/usr/bin/sops" if binary == "sops" else None,
    )

    class DummyProcess:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = payload
            self.stderr = ""

    calls: list[list[str]] = []

    def fake_run(command: list[str], **_: Any) -> DummyProcess:
        calls.append(command)
        return DummyProcess()

    monkeypatch.setattr("kstlib.secrets.providers.sops.subprocess_run", fake_run)

    provider = SOPSProvider(path=secret_file)
    request = SecretRequest(name="smtp.password", scope=None, required=True, default=None)

    record_first = provider.resolve(request)
    record_second = provider.resolve(request)

    assert record_first is not None and record_second is not None
    assert record_first.value == "hunter2"
    assert record_first.metadata["path"] == str(secret_file)
    assert record_first.metadata["binary"] == "sops"
    assert calls == [["/usr/bin/sops", "--decrypt", str(secret_file)]]


def test_sops_provider_sequence_key_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify SOPSProvider resolves a value using an explicit key_path list."""
    secret_file = tmp_path / "secrets.yml"
    secret_file.write_text("ignored")

    monkeypatch.setattr("kstlib.secrets.providers.sops.shutil.which", lambda _: "/usr/bin/sops")

    class DummyProcess:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = "production:\n  database:\n    password: example"
            self.stderr = ""

    def run_process(*_: Any, **__: Any) -> DummyProcess:
        return DummyProcess()

    monkeypatch.setattr("kstlib.secrets.providers.sops.subprocess_run", run_process)

    provider = SOPSProvider(path=secret_file, document_format="yaml")
    request = SecretRequest(
        name="ignored",
        scope=None,
        required=False,
        default=None,
        metadata={"key_path": ["production", "database", "password"]},
    )

    record = provider.resolve(request)

    assert record is not None
    assert record.value == "example"
    assert record.source is SecretSource.SOPS


def test_sops_provider_overrides_via_configure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify configure() overrides path, binary, and format on SOPSProvider."""
    secret_file = tmp_path / "overrides.enc"
    secret_file.write_text("ignored")

    monkeypatch.setattr("kstlib.secrets.providers.sops.shutil.which", lambda _: "/custom/bin/sops")

    class DummyProcess:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = "plain text"
            self.stderr = ""

    def run_process(*_: Any, **__: Any) -> DummyProcess:
        return DummyProcess()

    monkeypatch.setattr("kstlib.secrets.providers.sops.subprocess_run", run_process)

    provider = SOPSProvider()
    provider.configure({"path": secret_file, "binary": "custom-sops", "format": "text"})
    request = SecretRequest(
        name="anything",
        scope=None,
        required=False,
        default=None,
        metadata={"key_path": []},
    )

    record = provider.resolve(request)

    assert record is not None
    assert record.value == "plain text"
    assert record.metadata["binary"] == "custom-sops"


def test_sops_provider_raises_when_binary_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Raise SecretDecryptionError when the sops binary cannot be found."""
    secret_file = tmp_path / "missing"
    secret_file.write_text("ignored")

    monkeypatch.setattr("kstlib.secrets.providers.sops.shutil.which", lambda _: None)

    provider = SOPSProvider(path=secret_file)
    request = SecretRequest(name="value", scope=None, required=True, default=None)

    with pytest.raises(SecretDecryptionError):
        provider.resolve(request)


def test_sops_provider_resolve_returns_none_without_path() -> None:
    """Verify SOPSProvider returns None when no file path is configured."""
    provider = SOPSProvider()
    request = SecretRequest(name="smtp.password", scope=None, required=False, default=None)

    assert provider.resolve(request) is None


def test_sops_provider_configure_noop_when_missing_settings(tmp_path: Path) -> None:
    """Verify configure() with None or empty dict leaves existing settings intact."""
    provider = SOPSProvider(path=tmp_path / "a.enc", binary="custom", document_format="json")

    provider.configure(None)
    provider.configure({})

    assert provider._path == Path(tmp_path / "a.enc")
    assert provider._binary == "custom"
    assert provider._document_format == "json"


def test_sops_provider_uses_metadata_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify SOPSProvider picks up the file path from request metadata."""
    payload = '{"api": {"token": "value"}}'
    secrets_file = tmp_path / "metadata.enc"
    secrets_file.write_text("encrypted")

    monkeypatch.setattr("kstlib.secrets.providers.sops.shutil.which", lambda _: "/usr/bin/sops")

    class DummyProcess:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = payload
            self.stderr = ""

    calls: list[list[str]] = []

    def run_process(command: list[str], **_: Any) -> DummyProcess:
        calls.append(command)
        return DummyProcess()

    monkeypatch.setattr("kstlib.secrets.providers.sops.subprocess_run", run_process)

    provider = SOPSProvider()
    request = SecretRequest(
        name="api.token",
        scope=None,
        required=True,
        default=None,
        metadata={"path": secrets_file},
    )

    record = provider.resolve(request)

    assert record is not None
    assert record.value == "value"
    assert calls == [["/usr/bin/sops", "--decrypt", str(secrets_file)]]


def test_sops_provider_handles_command_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Handle SOPS command failure with redacted error logging."""
    secrets_file = tmp_path / "broken.enc"
    secrets_file.write_text("encrypted")

    monkeypatch.setattr("kstlib.secrets.providers.sops.shutil.which", lambda _: "/usr/bin/sops")

    class DummyProcess:
        def __init__(self) -> None:
            self.returncode = 1
            self.stdout = ""
            self.stderr = "arn:aws:kms:us-east-1:123456789012:key/abc"

    monkeypatch.setattr("kstlib.secrets.providers.sops.subprocess_run", lambda *_, **__: DummyProcess())

    provider = SOPSProvider(path=secrets_file)
    request = SecretRequest(name="api.token", scope=None, required=True, default=None)

    caplog.set_level("DEBUG")

    with pytest.raises(SecretDecryptionError) as excinfo:
        provider.resolve(request)

    message = str(excinfo.value)
    assert "arn:aws" not in message
    assert secrets_file.name in message
    assert any("[REDACTED]" in record.message for record in caplog.records)


def test_sops_provider_auto_falls_back_to_yaml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Fall back to YAML parsing when format is auto-detected."""
    secrets_file = tmp_path / "data.enc"
    secrets_file.write_text("encrypted")

    monkeypatch.setattr("kstlib.secrets.providers.sops.shutil.which", lambda _: "/usr/bin/sops")

    yaml_payload = "service:\n  token: abc"

    class DummyProcess:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = yaml_payload
            self.stderr = ""

    monkeypatch.setattr("kstlib.secrets.providers.sops.subprocess_run", lambda *_, **__: DummyProcess())

    provider = SOPSProvider(path=secrets_file)
    request = SecretRequest(name="service.token", scope=None, required=True, default=None)

    record = provider.resolve(request)

    assert record is not None
    assert record.value == "abc"


def test_sops_provider_yaml_format(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Parse YAML-formatted SOPS output correctly."""
    secrets_file = tmp_path / "yaml.enc"
    secrets_file.write_text("encrypted")

    monkeypatch.setattr("kstlib.secrets.providers.sops.shutil.which", lambda _: "/usr/bin/sops")

    yaml_payload = "service:\n  token: def"
    called: dict[str, Any] = {}

    class DummyProcess:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = yaml_payload
            self.stderr = ""

    monkeypatch.setattr("kstlib.secrets.providers.sops.subprocess_run", lambda *_, **__: DummyProcess())

    def fake_safe_load(payload: str) -> Any:
        called["payload"] = payload
        return {"service": {"token": "def"}}

    monkeypatch.setattr("kstlib.secrets.providers.sops.yaml.safe_load", fake_safe_load)

    provider = SOPSProvider(path=secrets_file, document_format="yaml")
    request = SecretRequest(name="service.token", scope=None, required=True, default=None)

    record = provider.resolve(request)

    assert record is not None
    assert record.value == "def"
    assert called["payload"] == yaml_payload


def test_sops_provider_json_format(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Parse JSON-formatted SOPS output correctly."""
    secrets_file = tmp_path / "json.enc"
    secrets_file.write_text("encrypted")

    monkeypatch.setattr("kstlib.secrets.providers.sops.shutil.which", lambda _: "/usr/bin/sops")

    json_payload = '{"service": {"token": "ghi"}}'

    class DummyProcess:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = json_payload
            self.stderr = ""

    monkeypatch.setattr("kstlib.secrets.providers.sops.subprocess_run", lambda *_, **__: DummyProcess())

    provider = SOPSProvider(path=secrets_file, document_format="json")
    request = SecretRequest(name="service.token", scope=None, required=True, default=None)

    record = provider.resolve(request)

    assert record is not None
    assert record.value == "ghi"


def test_sops_provider_text_format_passthrough(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Pass through raw text output without parsing."""
    secrets_file = tmp_path / "plain.enc"
    secrets_file.write_text("encrypted")

    monkeypatch.setattr("kstlib.secrets.providers.sops.shutil.which", lambda _: "/usr/bin/sops")

    class DummyProcess:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = "plain-text"
            self.stderr = ""

    monkeypatch.setattr("kstlib.secrets.providers.sops.subprocess_run", lambda *_, **__: DummyProcess())

    provider = SOPSProvider(path=secrets_file, document_format="text")
    request = SecretRequest(
        name="anything",
        scope=None,
        required=True,
        default=None,
        metadata={"key_path": []},
    )

    record = provider.resolve(request)

    assert record is not None
    assert record.value == "plain-text"


def test_sops_provider_raises_when_parsing_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Raise error when SOPS output cannot be parsed."""
    secrets_file = tmp_path / "invalid.enc"
    secrets_file.write_text("encrypted")

    monkeypatch.setattr("kstlib.secrets.providers.sops.shutil.which", lambda _: "/usr/bin/sops")

    class DummyProcess:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = "not: yaml"
            self.stderr = ""

    def fail_safe_load(*_: Any, **__: Any) -> None:
        raise yaml.YAMLError("invalid")

    monkeypatch.setattr("kstlib.secrets.providers.sops.subprocess_run", lambda *_, **__: DummyProcess())
    monkeypatch.setattr("kstlib.secrets.providers.sops.yaml.safe_load", fail_safe_load)

    provider = SOPSProvider(path=secrets_file)
    request = SecretRequest(name="anything", scope=None, required=True, default=None)

    with pytest.raises(SecretDecryptionError):
        provider.resolve(request)


def test_sops_provider_yaml_parse_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Raise error on invalid YAML output from SOPS."""
    secrets_file = tmp_path / "invalid-yaml.enc"
    secrets_file.write_text("encrypted")

    monkeypatch.setattr("kstlib.secrets.providers.sops.shutil.which", lambda _: "/usr/bin/sops")

    class DummyProcess:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = "broken"
            self.stderr = ""

    def fail_safe_load(*_: Any, **__: Any) -> None:
        raise yaml.YAMLError("invalid")

    monkeypatch.setattr("kstlib.secrets.providers.sops.subprocess_run", lambda *_, **__: DummyProcess())
    monkeypatch.setattr("kstlib.secrets.providers.sops.yaml.safe_load", fail_safe_load)

    provider = SOPSProvider(path=secrets_file, document_format="yaml")
    request = SecretRequest(name="anything", scope=None, required=True, default=None)

    with pytest.raises(SecretDecryptionError):
        provider.resolve(request)


def test_sops_provider_returns_none_when_key_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Return None when requested key is missing from SOPS output."""
    secrets_file = tmp_path / "missing.enc"
    secrets_file.write_text("encrypted")

    monkeypatch.setattr("kstlib.secrets.providers.sops.shutil.which", lambda _: "/usr/bin/sops")

    class DummyProcess:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = '{"api": {"token": "abc"}}'
            self.stderr = ""

    monkeypatch.setattr("kstlib.secrets.providers.sops.subprocess_run", lambda *_, **__: DummyProcess())

    provider = SOPSProvider(path=secrets_file)
    request = SecretRequest(name="api.password", scope=None, required=False, default=None)

    assert provider.resolve(request) is None


def test_sops_provider_redacts_sensitive_output() -> None:
    """Redact AWS ARNs, access keys, and file paths from error output."""
    message = "arn:aws:kms:us-east-1:123456789012:key/abc AKIA1234567890ABCDEF /home/user/secret"

    redacted = SOPSProvider._redact_sensitive_output(message)

    assert "arn:aws" not in redacted
    assert "AKIA" not in redacted
    assert "user/secret" not in redacted
    assert redacted.count("[REDACTED]") == 3


def test_sops_provider_purge_cache_variants(tmp_path: Path) -> None:
    """Purge cache entries for both direct and resolved paths."""
    provider = SOPSProvider()
    direct_path = tmp_path / "direct.enc"
    resolved_path = tmp_path / "resolved.enc"
    direct_path.write_text("a")
    resolved_path.write_text("b")

    provider._cache = OrderedDict({direct_path: (direct_path.stat().st_mtime, {"value": 1})})
    provider.purge_cache()
    assert not provider._cache

    provider._cache = OrderedDict({direct_path: (direct_path.stat().st_mtime, {"value": 2})})
    provider.purge_cache(path=str(direct_path))
    assert not provider._cache

    provider._cache = OrderedDict({resolved_path.resolve(): (resolved_path.stat().st_mtime, {"value": 3})})
    alias_dir = tmp_path / "alias"
    alias_dir.mkdir()
    alias_path = alias_dir / ".." / resolved_path.name
    provider.purge_cache(path=str(alias_path))
    assert not provider._cache


def test_environment_provider_builds_key_without_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    """Build environment variable key without scope prefix."""
    provider = EnvironmentProvider(prefix="kstlib_", delimiter="__")
    request = SecretRequest(name="db.password", scope=None, required=False, default=None)
    monkeypatch.setenv("KSTLIB__DB__PASSWORD", "value")

    record = provider.resolve(request)

    assert record is not None
    assert record.value == "value"
    assert record.metadata == {"env_key": "KSTLIB__DB__PASSWORD"}


def test_get_provider_returns_registered_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Return a configured provider instance from the registry."""
    env_provider = get_provider("environment", prefix="app_", delimiter="__")
    request = SecretRequest(name="token", scope="ops", required=True, default=None)
    monkeypatch.setenv("APP__OPS__TOKEN", "abc")

    record = env_provider.resolve(request)

    keyring_provider = get_provider("keyring")
    sops_provider = get_provider("sops")

    assert isinstance(env_provider, EnvironmentProvider)
    assert isinstance(keyring_provider, KeyringProvider)
    assert isinstance(sops_provider, SOPSProvider)
    assert record is not None
    assert record.value == "abc"


def test_configure_provider_returns_same_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Return the same provider instance after configuration update."""
    provider = EnvironmentProvider()
    configured = configure_provider(provider, {"prefix": "svc_", "delimiter": "__"})
    request = SecretRequest(name="api.key", scope="jobs", required=False, default=None)
    monkeypatch.setenv("SVC__JOBS__API__KEY", "secret")

    record = configured.resolve(request)

    assert configured is provider
    assert record is not None
    assert record.value == "secret"


def test_sops_provider_configure_max_cache_entries_with_hard_limit(tmp_path: Path) -> None:
    """Configure respects the hard limit for max_cache_entries."""
    from kstlib.limits import HARD_MAX_SOPS_CACHE_ENTRIES

    provider = SOPSProvider(path=tmp_path / "secrets.enc")

    # Try to configure with a value exceeding the hard limit
    provider.configure({"max_cache_entries": HARD_MAX_SOPS_CACHE_ENTRIES + 100})

    # Should be capped to the hard limit
    assert provider._max_cache_entries == HARD_MAX_SOPS_CACHE_ENTRIES


def test_sops_provider_lru_cache_eviction(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Cache evicts oldest entries when exceeding max_cache_entries."""
    # Create multiple secrets files
    files = []
    for i in range(5):
        f = tmp_path / f"secrets{i}.enc"
        f.write_text("encrypted")
        files.append(f)

    monkeypatch.setattr("kstlib.secrets.providers.sops.shutil.which", lambda _: "/usr/bin/sops")

    call_count = [0]

    class DummyProcess:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = f'{{"key": "value{call_count[0]}"}}'
            call_count[0] += 1
            self.stderr = ""

    monkeypatch.setattr("kstlib.secrets.providers.sops.subprocess_run", lambda *_, **__: DummyProcess())

    # Create provider with small cache
    provider = SOPSProvider()
    provider._max_cache_entries = 2

    # Access multiple files to trigger eviction
    for f in files:
        request = SecretRequest(
            name="key",
            scope=None,
            required=False,
            default=None,
            metadata={"path": str(f)},
        )
        provider.resolve(request)

    # Cache should only contain the last 2 entries
    assert len(provider._cache) == 2

    # Most recent files should be in cache
    cache_paths = list(provider._cache.keys())
    assert files[-1] in cache_paths or files[-1].resolve() in cache_paths
    assert files[-2] in cache_paths or files[-2].resolve() in cache_paths
