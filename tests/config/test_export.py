"""Unit tests for the configuration export helpers."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from kstlib.config.export import (
    ConfigExportError,
    ConfigExportOptions,
    _serialize_data,
    _write_text,
    export_configuration,
)


def _prepare_packaged_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, payload: dict[str, Any]) -> Path:
    """Create a temporary packaged configuration and patch the importlib resources."""

    config_path = tmp_path / "kstlib.conf.yml"
    config_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    class DummyResources:
        """Minimal stub replicating ``importlib.resources`` traversal."""

        def __init__(self, path: Path) -> None:
            self._path = path

        def joinpath(self, _: str) -> Path:
            """Return the fixed configuration path regardless of the requested name."""

            return self._path

    @contextmanager
    def fake_as_file(candidate: Path) -> Iterator[Path]:
        """Yield the candidate path directly (no copy necessary)."""

        yield candidate

    monkeypatch.setattr("kstlib.config.export.resources.files", lambda *_: DummyResources(config_path))
    monkeypatch.setattr("kstlib.config.export.resources.as_file", fake_as_file)

    return config_path


def test_export_configuration_missing_packaged_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Ensure packaged configuration lookup raises when the resource is absent."""
    missing_path = tmp_path / "missing.yml"

    class DummyFiles:
        """Fixture providing a predictable package path for testing."""

        def __init__(self, path: Path) -> None:
            self._path = path

        def joinpath(self, _: str) -> Path:
            """Return the predetermined missing path."""
            return self._path

    @contextmanager
    def fake_as_file(candidate: Path) -> Iterator[Path]:
        yield candidate

    def fake_files(*_: object) -> DummyFiles:
        return DummyFiles(missing_path)

    monkeypatch.setattr("kstlib.config.export.resources.files", fake_files)
    monkeypatch.setattr("kstlib.config.export.resources.as_file", fake_as_file)

    with pytest.raises(ConfigExportError, match=r"Packaged configuration file is missing\."):
        export_configuration(ConfigExportOptions())


def test_export_full_config_stdout_returns_content() -> None:
    """Verify exporting to stdout returns an in-memory YAML payload."""
    result = export_configuration(ConfigExportOptions(stdout=True))

    assert result.destination is None
    assert result.format_name == "yaml"
    assert result.content


def test_export_unknown_extension_defaults_to_yaml(tmp_path: Path) -> None:
    """Fallback to ``.yaml`` when the destination lacks a known suffix."""
    destination = tmp_path / "custom.conf"

    result = export_configuration(ConfigExportOptions(out_path=destination))

    assert result.destination is not None
    assert result.destination.suffix == ".yaml"
    assert result.destination.read_text(encoding="utf-8")


def test_serialize_data_ini_handles_nested_structures() -> None:
    """Flatten nested mappings when serialising to INI format."""
    data = {
        "section": {
            "flag": True,
            "numbers": [1, 2, 3],
            "inner": {"threshold": 0.8},
        },
        "other": 42,
    }

    serialized = _serialize_data(data, "ini")

    assert "[section]" in serialized
    assert "numbers[0]" in serialized
    assert "inner.threshold" in serialized
    assert "[other]" in serialized


def test_serialize_data_ini_requires_mapping() -> None:
    """Reject non-mapping payloads for INI serialisation."""
    with pytest.raises(ConfigExportError, match=r"INI export requires dictionary data\."):
        _serialize_data(["value"], "ini")


def test_serialize_data_toml_requires_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail gracefully when the optional ``tomli-w`` dependency is missing."""
    monkeypatch.setattr("kstlib.config.export._TOMLI_W", None)

    with pytest.raises(ConfigExportError, match="tomli-w"):
        _serialize_data({"key": "value"}, "toml")


def test_serialize_data_rejects_unknown_format() -> None:
    """Raise an error for unsupported export formats."""
    with pytest.raises(ConfigExportError, match="Unsupported output format"):
        _serialize_data({}, "unsupported")


def test_write_text_refuses_overwrite_without_force(tmp_path: Path) -> None:
    """Disallow file overwrite unless ``force`` is explicitly enabled."""
    destination = tmp_path / "config.yml"
    destination.write_text("existing", encoding="utf-8")

    with pytest.raises(ConfigExportError, match="Use --force to overwrite"):
        _write_text("new-content", destination, force=False)


def test_export_section_stdout_wraps_requested_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Ensure section exports keep the dotted path hierarchy when dumping to stdout."""

    payload = {
        "ui": {
            "tables": {
                "defaults": {
                    "table": {"title": "Base"},
                    "columns": [{"header": "Key"}],
                }
            }
        },
        "service": {"host": "localhost"},
    }
    _prepare_packaged_config(monkeypatch, tmp_path, payload)

    result = export_configuration(ConfigExportOptions(section="ui.tables.defaults", stdout=True))

    assert result.format_name == "yaml"
    assert result.destination is None
    exported = yaml.safe_load(result.content or "")
    ui_payload = cast(dict[str, Any], payload["ui"])
    tables_payload = cast(dict[str, Any], ui_payload["tables"])
    defaults_payload = tables_payload["defaults"]
    assert exported == {"ui": {"tables": {"defaults": defaults_payload}}}


def test_export_section_writes_json_subset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Write the selected configuration subset to disk using JSON serialization."""

    payload = {
        "service": {
            "endpoints": [
                {"name": "alpha", "url": "https://example"},
                {"name": "beta", "url": "https://beta"},
            ]
        },
        "ui": {"tables": {"defaults": {"table": {"title": "Base"}}}},
    }
    _prepare_packaged_config(monkeypatch, tmp_path, payload)

    destination = tmp_path / "subset.json"
    result = export_configuration(ConfigExportOptions(section="service", out_path=destination))

    assert result.destination == destination
    exported = json.loads(destination.read_text(encoding="utf-8"))
    assert exported == {"service": payload["service"]}


def test_export_full_config_copies_yaml_when_format_matches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify that YAML destinations trigger a direct file copy for the full config export."""

    payload = {"app": {"feature": {"enabled": True}}}
    config_path = _prepare_packaged_config(monkeypatch, tmp_path, payload)
    destination = tmp_path / "mirror.yaml"

    result = export_configuration(ConfigExportOptions(out_path=destination))

    assert result.destination == destination
    assert destination.read_text(encoding="utf-8") == config_path.read_text(encoding="utf-8")


def test_export_full_config_transcodes_to_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Ensure non-YAML outputs serialise the entire configuration payload."""

    payload = {"service": {"host": "127.0.0.1", "port": 9000}}
    _prepare_packaged_config(monkeypatch, tmp_path, payload)
    destination = tmp_path / "config.json"

    result = export_configuration(ConfigExportOptions(out_path=destination))

    assert result.format_name == "json"
    exported = json.loads(destination.read_text(encoding="utf-8"))
    assert exported == payload


def test_export_configuration_missing_section_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Raise a descriptive error when the requested section path cannot be resolved."""

    payload = {"service": {"host": "localhost"}}
    _prepare_packaged_config(monkeypatch, tmp_path, payload)

    with pytest.raises(ConfigExportError, match=r"Section 'missing.path' not found"):
        export_configuration(ConfigExportOptions(section="missing.path"))
