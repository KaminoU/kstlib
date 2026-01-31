"""Tests for the secrets doctor command config detection."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from kstlib.cli.commands.secrets.doctor import (
    _find_effective_sops_config,
    _format_config_source,
)

if TYPE_CHECKING:
    from pytest import MonkeyPatch


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
