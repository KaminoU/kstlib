"""Tests for the secrets doctor command config detection."""

from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess
from typing import TYPE_CHECKING
from unittest.mock import patch

import typer
import pytest

from kstlib.cli.commands.secrets.doctor import (
    _build_backend_mismatch_hint,
    _create_sops_config_gpg,
    _find_effective_sops_config,
    _format_config_source,
    _get_gpg_fingerprint,
    _resolve_init_backend,
    _scan_available_backends,
)

import importlib

if TYPE_CHECKING:
    from pytest import MonkeyPatch

doctor_mod = importlib.import_module("kstlib.cli.commands.secrets.doctor")


class TestFindEffectiveSopsConfig:
    """Tests for _find_effective_sops_config function."""

    def test_env_variable_takes_priority(self, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
        """SOPS_CONFIG env var should take highest priority."""
        # Create config in env location
        env_config = tmp_path / "env-config" / ".sops.yaml"
        env_config.parent.mkdir(parents=True)
        env_config.write_text("creation_rules:\n  - age: age1envkey123\n")

        # Create config in home (should be ignored)
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        home_config = home_dir / ".sops.yaml"
        home_config.write_text("creation_rules:\n  - age: age1homekey123\n")

        monkeypatch.setenv("SOPS_CONFIG", str(env_config))
        monkeypatch.chdir(tmp_path)

        with patch("pathlib.Path.home", return_value=home_dir):
            config_path, source = _find_effective_sops_config()

        assert config_path == env_config
        assert source == "env"

    def test_env_variable_missing_file_returns_none(self, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
        """SOPS_CONFIG pointing to missing file should return none."""
        monkeypatch.setenv("SOPS_CONFIG", str(tmp_path / "nonexistent.yaml"))
        monkeypatch.chdir(tmp_path)

        config_path, source = _find_effective_sops_config()

        assert config_path is None
        assert source == "none"

    def test_local_directory_found_by_walking_up(self, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
        """Config in parent directory should be found by walking up."""
        # Create project structure: project/.sops.yaml, project/subdir/
        project_dir = tmp_path / "project"
        subdir = project_dir / "subdir" / "deep"
        subdir.mkdir(parents=True)

        local_config = project_dir / ".sops.yaml"
        local_config.write_text("creation_rules:\n  - age: age1localkey123\n")

        # Home is elsewhere (not in the walk path)
        home_dir = tmp_path / "home"
        home_dir.mkdir()

        monkeypatch.delenv("SOPS_CONFIG", raising=False)
        monkeypatch.chdir(subdir)

        with patch("pathlib.Path.home", return_value=home_dir):
            config_path, source = _find_effective_sops_config()

        assert config_path == local_config
        assert source == "local"

    def test_home_directory_config_labeled_as_home(self, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
        """Config in HOME should be labeled as 'home' not 'local'."""
        # Create home with config
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        home_config = home_dir / ".sops.yaml"
        home_config.write_text("creation_rules:\n  - age: age1homekey123\n")

        # Create subdir inside home (simulates walking up reaching HOME)
        subdir = home_dir / "projects" / "myproject"
        subdir.mkdir(parents=True)

        monkeypatch.delenv("SOPS_CONFIG", raising=False)
        monkeypatch.chdir(subdir)

        with patch("pathlib.Path.home", return_value=home_dir):
            config_path, source = _find_effective_sops_config()

        assert config_path is not None
        assert config_path.resolve() == home_config.resolve()
        assert source == "home"  # NOT "local"!

    def test_home_fallback_when_no_local_config(self, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
        """Home config should be used as fallback when no local config found."""
        # Create home with config
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        home_config = home_dir / ".sops.yaml"
        home_config.write_text("creation_rules:\n  - age: age1homekey123\n")

        # Work dir INSIDE home (to avoid walking up to real ~/.sops.yaml)
        # The test verifies fallback to home_config when no .sops.yaml in parent dirs
        work_dir = home_dir / "work" / "other"
        work_dir.mkdir(parents=True)

        monkeypatch.delenv("SOPS_CONFIG", raising=False)
        monkeypatch.chdir(work_dir)

        with patch("pathlib.Path.home", return_value=home_dir):
            config_path, source = _find_effective_sops_config()

        # Since work_dir is inside home_dir, walking up will find home_config
        assert config_path is not None
        assert config_path.resolve() == home_config.resolve()
        assert source == "home"

    @pytest.mark.skipif(
        (Path.home() / ".sops.yaml").exists(),
        reason="Test cannot run when ~/.sops.yaml exists (walk up finds it)",
    )
    def test_no_config_found_returns_none(self, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
        """No config anywhere should return none."""
        # This test verifies behavior when no .sops.yaml exists anywhere.
        # It's skipped if the user has a real ~/.sops.yaml because the
        # walk-up algorithm will find it before reaching the mocked home.

        # Create isolated home dir without .sops.yaml
        home_dir = tmp_path / "fakehome"
        home_dir.mkdir()

        # Work dir inside fake home (no .sops.yaml anywhere in this tree)
        work_dir = home_dir / "work"
        work_dir.mkdir()

        monkeypatch.delenv("SOPS_CONFIG", raising=False)
        monkeypatch.chdir(work_dir)

        with patch("pathlib.Path.home", return_value=home_dir):
            config_path, source = _find_effective_sops_config()

        # Walking up from work_dir reaches home_dir, but no .sops.yaml there
        # Fallback to home_dir/.sops.yaml also doesn't exist
        assert config_path is None
        assert source == "none"


class TestFormatConfigSource:
    """Tests for _format_config_source function."""

    def test_env_source(self) -> None:
        """Env source should have descriptive label."""
        assert _format_config_source("env") == "SOPS_CONFIG env var"

    def test_local_source(self) -> None:
        """Local source should have descriptive label."""
        result = _format_config_source("local")
        assert "local" in result.lower()
        assert "cwd" in result.lower()

    def test_home_source(self) -> None:
        """Home source should have descriptive label."""
        result = _format_config_source("home")
        assert "home" in result.lower()
        assert "~" in result or ".sops.yaml" in result

    def test_none_source(self) -> None:
        """None source should indicate not found."""
        assert _format_config_source("none") == "not found"

    def test_unknown_source_returns_as_is(self) -> None:
        """Unknown source should be returned as-is."""
        assert _format_config_source("custom") == "custom"


class TestScanAvailableBackends:
    """Tests for _scan_available_backends function."""

    def test_detects_age_when_binary_present(self, monkeypatch: MonkeyPatch) -> None:
        """Detects age backend when age-keygen binary is found."""

        def fake_which(name: str) -> str | None:
            return "/usr/bin/age-keygen" if name == "age-keygen" else None

        monkeypatch.setattr(doctor_mod.shutil, "which", fake_which)
        monkeypatch.setattr(doctor_mod.importlib, "import_module", lambda n: (_ for _ in ()).throw(ImportError()))

        result = _scan_available_backends()

        assert result == ["age"]

    def test_detects_gpg_when_binary_present(self, monkeypatch: MonkeyPatch) -> None:
        """Detects gpg backend when gpg binary is found."""

        def fake_which(name: str) -> str | None:
            return "/usr/bin/gpg" if name == "gpg" else None

        monkeypatch.setattr(doctor_mod.shutil, "which", fake_which)
        monkeypatch.setattr(doctor_mod.importlib, "import_module", lambda n: (_ for _ in ()).throw(ImportError()))

        result = _scan_available_backends()

        assert result == ["gpg"]

    def test_detects_gpg2_when_gpg2_present(self, monkeypatch: MonkeyPatch) -> None:
        """Detects gpg backend when only gpg2 binary is found."""

        def fake_which(name: str) -> str | None:
            return "/usr/bin/gpg2" if name == "gpg2" else None

        monkeypatch.setattr(doctor_mod.shutil, "which", fake_which)
        monkeypatch.setattr(doctor_mod.importlib, "import_module", lambda n: (_ for _ in ()).throw(ImportError()))

        result = _scan_available_backends()

        assert result == ["gpg"]

    def test_detects_kms_when_boto3_installed(self, monkeypatch: MonkeyPatch) -> None:
        """Detects kms backend when boto3 is importable."""
        from types import SimpleNamespace

        monkeypatch.setattr(doctor_mod.shutil, "which", lambda _: None)
        monkeypatch.setattr(doctor_mod.importlib, "import_module", lambda n: SimpleNamespace(__version__="1.34.0"))

        result = _scan_available_backends()

        assert result == ["kms"]

    def test_returns_empty_when_nothing_available(self, monkeypatch: MonkeyPatch) -> None:
        """Returns empty list when no backends are available."""
        monkeypatch.setattr(doctor_mod.shutil, "which", lambda _: None)
        monkeypatch.setattr(doctor_mod.importlib, "import_module", lambda n: (_ for _ in ()).throw(ImportError()))

        result = _scan_available_backends()

        assert result == []

    def test_detects_multiple_backends(self, monkeypatch: MonkeyPatch) -> None:
        """Detects all backends when all are available."""
        from types import SimpleNamespace

        def fake_which(name: str) -> str | None:
            return f"/usr/bin/{name}" if name in ("age-keygen", "gpg") else None

        monkeypatch.setattr(doctor_mod.shutil, "which", fake_which)
        monkeypatch.setattr(doctor_mod.importlib, "import_module", lambda n: SimpleNamespace(__version__="1.34.0"))

        result = _scan_available_backends()

        assert result == ["age", "gpg", "kms"]


class TestResolveInitBackend:
    """Tests for _resolve_init_backend function."""

    def test_explicit_age_when_available(self, monkeypatch: MonkeyPatch) -> None:
        """Returns 'age' when explicitly requested and available."""
        monkeypatch.setattr(doctor_mod, "_scan_available_backends", lambda: ["age", "gpg"])

        assert _resolve_init_backend("age") == "age"

    def test_explicit_gpg_when_available(self, monkeypatch: MonkeyPatch) -> None:
        """Returns 'gpg' when explicitly requested and available."""
        monkeypatch.setattr(doctor_mod, "_scan_available_backends", lambda: ["age", "gpg"])

        assert _resolve_init_backend("gpg") == "gpg"

    def test_explicit_age_when_missing_errors(self, monkeypatch: MonkeyPatch) -> None:
        """Exits with error when age is requested but not available."""
        monkeypatch.setattr(doctor_mod, "_scan_available_backends", lambda: ["gpg"])

        with pytest.raises(typer.Exit):
            _resolve_init_backend("age")

    def test_explicit_invalid_backend_errors(self, monkeypatch: MonkeyPatch) -> None:
        """Exits with error when an invalid backend is requested."""
        with pytest.raises(typer.Exit):
            _resolve_init_backend("invalid")

    def test_auto_prefers_age(self, monkeypatch: MonkeyPatch) -> None:
        """Auto-detection prefers age over gpg when both are available."""
        monkeypatch.setattr(doctor_mod, "_scan_available_backends", lambda: ["age", "gpg"])

        assert _resolve_init_backend(None) == "age"

    def test_auto_falls_back_to_gpg(self, monkeypatch: MonkeyPatch) -> None:
        """Auto-detection falls back to gpg when age is not available."""
        monkeypatch.setattr(doctor_mod, "_scan_available_backends", lambda: ["gpg"])

        assert _resolve_init_backend(None) == "gpg"

    def test_auto_nothing_available_errors(self, monkeypatch: MonkeyPatch) -> None:
        """Exits with error when no backends are available."""
        monkeypatch.setattr(doctor_mod, "_scan_available_backends", lambda: [])

        with pytest.raises(typer.Exit):
            _resolve_init_backend(None)

    def test_explicit_backend_case_insensitive(self, monkeypatch: MonkeyPatch) -> None:
        """Accepts uppercase backend names."""
        monkeypatch.setattr(doctor_mod, "_scan_available_backends", lambda: ["age"])

        assert _resolve_init_backend("AGE") == "age"


class TestGetGpgFingerprint:
    """Tests for _get_gpg_fingerprint function."""

    def test_returns_fingerprint(self, monkeypatch: MonkeyPatch) -> None:
        """Returns the fingerprint from gpg --list-secret-keys --with-colons output."""
        gpg_output = (
            "sec:-:4096:1:ABCDEF1234567890:1700000000:::-:::scESC::::::23::0:\n"
            "fpr:::::::::AABBCCDD11223344556677889900AABBCCDD1122:\n"
            "uid:-::::1700000000::HASH::Test User <test@example.com>::::::::::0:\n"
        )
        monkeypatch.setattr(doctor_mod.shutil, "which", lambda name: "/usr/bin/gpg" if name == "gpg" else None)
        monkeypatch.setattr(
            doctor_mod,
            "run",
            lambda *a, **k: CompletedProcess([], 0, stdout=gpg_output, stderr=""),
        )

        result = _get_gpg_fingerprint()

        assert result == "AABBCCDD11223344556677889900AABBCCDD1122"

    def test_no_keys_errors(self, monkeypatch: MonkeyPatch) -> None:
        """Exits with error when no secret keys are found."""
        monkeypatch.setattr(doctor_mod.shutil, "which", lambda name: "/usr/bin/gpg" if name == "gpg" else None)
        monkeypatch.setattr(
            doctor_mod,
            "run",
            lambda *a, **k: CompletedProcess([], 0, stdout="", stderr=""),
        )

        with pytest.raises(typer.Exit):
            _get_gpg_fingerprint()

    def test_gpg_not_found_errors(self, monkeypatch: MonkeyPatch) -> None:
        """Exits with error when gpg binary is not found."""
        monkeypatch.setattr(doctor_mod.shutil, "which", lambda _: None)

        with pytest.raises(typer.Exit):
            _get_gpg_fingerprint()

    def test_gpg_command_failure_errors(self, monkeypatch: MonkeyPatch) -> None:
        """Exits with error when gpg command fails."""
        monkeypatch.setattr(doctor_mod.shutil, "which", lambda name: "/usr/bin/gpg" if name == "gpg" else None)
        monkeypatch.setattr(
            doctor_mod,
            "run",
            lambda *a, **k: CompletedProcess([], 2, stdout="", stderr="error"),
        )

        with pytest.raises(typer.Exit):
            _get_gpg_fingerprint()


class TestCreateSopsConfigGpg:
    """Tests for _create_sops_config_gpg function."""

    def test_creates_gpg_config(self, tmp_path: Path) -> None:
        """Creates a .sops.yaml file with pgp fingerprint."""
        config_path = tmp_path / ".sops.yaml"
        fingerprint = "AABBCCDD11223344556677889900AABBCCDD1122"

        result = _create_sops_config_gpg(config_path, fingerprint)

        assert result is True
        content = config_path.read_text(encoding="utf-8")
        assert f"pgp: {fingerprint}" in content
        assert "encrypted_regex" in content
        assert "creation_rules" in content

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        """Creates parent directories if they do not exist."""
        config_path = tmp_path / "deep" / "nested" / ".sops.yaml"
        fingerprint = "AABBCCDD11223344556677889900AABBCCDD1122"

        result = _create_sops_config_gpg(config_path, fingerprint)

        assert result is True
        assert config_path.exists()


class TestBuildBackendMismatchHint:
    """Tests for _build_backend_mismatch_hint function."""

    def test_hint_when_age_configured_gpg_available(self) -> None:
        """Provides hint when age is configured but only gpg is available."""
        hint = _build_backend_mismatch_hint(configured=["age"], available=["gpg"])

        assert hint is not None
        assert "gpg" in hint
        assert "kstlib secrets init --backend gpg" in hint

    def test_no_hint_when_configured_is_available(self) -> None:
        """No hint when configured backend is available."""
        hint = _build_backend_mismatch_hint(configured=["age"], available=["age", "gpg"])

        assert hint is None

    def test_no_hint_when_no_alternatives(self) -> None:
        """No hint when no usable alternatives are available."""
        hint = _build_backend_mismatch_hint(configured=["age"], available=[])

        assert hint is None

    def test_no_hint_when_nothing_configured(self) -> None:
        """No hint when nothing is configured."""
        hint = _build_backend_mismatch_hint(configured=[], available=["gpg"])

        assert hint is None

    def test_hint_when_gpg_configured_age_available(self) -> None:
        """Provides hint when gpg is configured but only age is available."""
        hint = _build_backend_mismatch_hint(configured=["gpg"], available=["age"])

        assert hint is not None
        assert "age" in hint
        assert "kstlib secrets init --backend age" in hint
