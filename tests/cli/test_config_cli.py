"""Integration tests for the `kstlib config` CLI commands."""

from __future__ import annotations

import json
import shutil
from importlib import resources
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from pytest import MonkeyPatch
from typer.testing import CliRunner

from kstlib.cli.app import app
from kstlib.config.export import ConfigExportResult
from kstlib.config.loader import CONFIG_FILENAME

# Mark all tests in this module as CLI tests (excluded from main tox runs)
# Run with: tox -e cli OR pytest -m cli
pytestmark = pytest.mark.cli

runner = CliRunner()


def _default_config_text() -> str:
    return resources.files("kstlib").joinpath(CONFIG_FILENAME).read_text(encoding="utf-8")


def _load_packaged_yaml() -> dict[str, Any]:
    data = yaml.safe_load(_default_config_text()) or {}
    return cast(dict[str, Any], data)


def _wrap_section(path: str, value: Any) -> Any:
    wrapped: Any = value
    for part in reversed(path.split(".")):
        wrapped = {part: wrapped}
    return wrapped


def test_export_default_config_to_directory(tmp_path: Path) -> None:
    """Export without a section writes the full YAML into the target directory."""

    result = runner.invoke(app, ["config", "export", "--out", str(tmp_path)])

    assert result.exit_code == 0

    exported_path = tmp_path / CONFIG_FILENAME
    assert exported_path.exists()
    assert exported_path.read_text(encoding="utf-8") == _default_config_text()


def test_export_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    """Existing files require --force to be overwritten."""

    target_dir = tmp_path / "out"
    target_dir.mkdir()
    destination = target_dir / CONFIG_FILENAME
    destination.write_text("placeholder", encoding="utf-8")

    result = runner.invoke(app, ["config", "export", "--out", str(target_dir)])

    assert result.exit_code == 1
    assert "Use --force to overwrite" in result.stdout
    assert destination.read_text(encoding="utf-8") == "placeholder"


def test_export_with_force_overwrites(tmp_path: Path) -> None:
    """Using --force overwrites existing files."""

    destination = tmp_path / CONFIG_FILENAME
    destination.write_text("placeholder", encoding="utf-8")

    result = runner.invoke(app, ["config", "export", "--out", str(destination), "--force"])

    assert result.exit_code == 0
    assert destination.read_text(encoding="utf-8") == _default_config_text()


def test_export_section_to_stdout() -> None:
    """Exporting a section to stdout returns YAML content."""

    result = runner.invoke(app, ["config", "export", "--section", "utilities.secure_delete", "--stdout"])

    assert result.exit_code == 0

    exported = yaml.safe_load(result.stdout)
    expected = _wrap_section("utilities.secure_delete", _load_packaged_yaml()["utilities"]["secure_delete"])
    assert exported == expected


def test_export_section_to_json(tmp_path: Path) -> None:
    """Exporting to a .json path serializes as JSON."""

    destination = tmp_path / "secure.json"

    result = runner.invoke(
        app,
        ["config", "export", "--section", "utilities.secure_delete", "--out", str(destination)],
    )

    assert result.exit_code == 0
    assert destination.exists()

    exported = json.loads(destination.read_text(encoding="utf-8"))
    expected = _wrap_section("utilities.secure_delete", _load_packaged_yaml()["utilities"]["secure_delete"])
    assert exported == expected


def test_export_section_missing_fails() -> None:
    """Requesting an unknown section fails with exit code 1."""

    result = runner.invoke(app, ["config", "export", "--section", "does.not.exist"])

    assert result.exit_code == 1
    assert "Section" in result.stdout


def test_export_section_expanduser(tmp_path: Path) -> None:
    """Paths with ~ are expanded before export."""

    home_base = Path.home() / ".kstlib-test-exports"
    target_dir = home_base / tmp_path.name
    target_dir.mkdir(parents=True, exist_ok=True)
    tilde_argument = Path("~") / ".kstlib-test-exports" / tmp_path.name

    try:
        result = runner.invoke(
            app,
            [
                "config",
                "export",
                "--section",
                "cache.ttl",
                "--out",
                str(tilde_argument),
            ],
        )

        assert result.exit_code == 0
        exported_path = target_dir / CONFIG_FILENAME
        assert exported_path.exists()

        exported = yaml.safe_load(exported_path.read_text(encoding="utf-8"))
        expected = _wrap_section("cache.ttl", _load_packaged_yaml()["cache"]["ttl"])
        assert exported == expected
    finally:
        shutil.rmtree(home_base, ignore_errors=True)


def test_export_full_config_to_json(tmp_path: Path) -> None:
    """Exporting the full config to JSON yields serializable data."""

    destination = tmp_path / "config.json"

    result = runner.invoke(app, ["config", "export", "--out", str(destination)])

    assert result.exit_code == 0
    exported = json.loads(destination.read_text(encoding="utf-8"))
    assert exported == _load_packaged_yaml()


def test_stdout_and_out_cannot_be_combined(tmp_path: Path) -> None:
    """Combining stdout with --out should fail."""

    result = runner.invoke(
        app,
        [
            "config",
            "export",
            "--section",
            "utilities",
            "--stdout",
            "--out",
            str(tmp_path / "dummy.yml"),
        ],
    )

    assert result.exit_code == 1
    assert "Cannot combine --stdout" in result.stdout


def test_export_stdout_empty_content_reports_error(monkeypatch: MonkeyPatch) -> None:
    """Stdout exports error when the backend returns empty content."""

    def _fake_export(_options: Any) -> ConfigExportResult:
        return ConfigExportResult(destination=None, content=None, format_name="yaml")

    monkeypatch.setattr("kstlib.cli.commands.config.export_configuration", _fake_export)

    result = runner.invoke(app, ["config", "export", "--stdout"])

    assert result.exit_code == 1
    assert "empty content" in result.stdout


def test_export_missing_destination_reports_error(monkeypatch: MonkeyPatch) -> None:
    """File exports error when the backend omits the destination."""

    def _fake_export(_options: Any) -> ConfigExportResult:
        return ConfigExportResult(destination=None, content=None, format_name="yaml")

    monkeypatch.setattr("kstlib.cli.commands.config.export_configuration", _fake_export)

    result = runner.invoke(app, ["config", "export"])

    assert result.exit_code == 1
    assert "missing destination file" in result.stdout
