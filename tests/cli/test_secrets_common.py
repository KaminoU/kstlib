"""Tests for secrets CLI common utilities."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from kstlib.cli.commands.secrets.common import find_sops_config

if TYPE_CHECKING:
    from pytest import MonkeyPatch


class TestFindSopsConfig:
    """Tests for find_sops_config function."""

    def test_finds_config_in_start_directory(self, tmp_path: Path) -> None:
        """Config in the start directory should be found."""
        config = tmp_path / ".sops.yaml"
        config.write_text("creation_rules:\n  - age: age1test\n")

        result = find_sops_config(tmp_path)

        assert result == config

    def test_finds_config_in_parent_directory(self, tmp_path: Path) -> None:
        """Config in a parent directory should be found."""
        config = tmp_path / ".sops.yaml"
        config.write_text("creation_rules:\n  - age: age1test\n")

        child = tmp_path / "subdir" / "nested"
        child.mkdir(parents=True)

        result = find_sops_config(child)

        assert result == config

    def test_finds_config_from_file_path(self, tmp_path: Path) -> None:
        """Config should be found when start_path is a file."""
        config = tmp_path / ".sops.yaml"
        config.write_text("creation_rules:\n  - age: age1test\n")

        source_file = tmp_path / "secrets.yml"
        source_file.write_text("password: secret123\n")

        result = find_sops_config(source_file)

        assert result == config

    def test_prefers_closer_config(self, tmp_path: Path) -> None:
        """Config closer to start_path should take precedence."""
        parent_config = tmp_path / ".sops.yaml"
        parent_config.write_text("creation_rules:\n  - age: age1parent\n")

        child = tmp_path / "project"
        child.mkdir()
        child_config = child / ".sops.yaml"
        child_config.write_text("creation_rules:\n  - kms: arn:aws:kms:...\n")

        result = find_sops_config(child)

        assert result == child_config

    def test_fallback_to_home_directory(self, tmp_path: Path) -> None:
        """Config in home directory should be used as fallback."""
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        home_config = home_dir / ".sops.yaml"
        home_config.write_text("creation_rules:\n  - age: age1home\n")

        search_dir = tmp_path / "project"
        search_dir.mkdir()

        # Track which files exist in our test setup
        test_files = {home_config}

        original_is_file = Path.is_file

        def mock_is_file(self: Path) -> bool:
            if self.name == ".sops.yaml":
                return self in test_files or self.resolve() in test_files
            return original_is_file(self)

        with (
            patch("kstlib.cli.commands.secrets.common.Path.home", return_value=home_dir),
            patch.object(Path, "is_file", mock_is_file),
        ):
            result = find_sops_config(search_dir)

        assert result == home_config

    def test_returns_none_when_not_found(self, tmp_path: Path) -> None:
        """None should be returned when no config exists."""
        home_dir = tmp_path / "home"
        home_dir.mkdir()

        search_dir = tmp_path / "project"
        search_dir.mkdir()

        # No test files exist
        test_files: set[Path] = set()

        original_is_file = Path.is_file

        def mock_is_file(self: Path) -> bool:
            if self.name == ".sops.yaml":
                return self in test_files or self.resolve() in test_files
            return original_is_file(self)

        with (
            patch("kstlib.cli.commands.secrets.common.Path.home", return_value=home_dir),
            patch.object(Path, "is_file", mock_is_file),
        ):
            result = find_sops_config(search_dir)

        assert result is None

    def test_uses_cwd_when_start_path_none(self, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
        """Current working directory should be used when start_path is None."""
        config = tmp_path / ".sops.yaml"
        config.write_text("creation_rules:\n  - age: age1test\n")

        monkeypatch.chdir(tmp_path)

        result = find_sops_config(None)

        assert result == config

    def test_ignores_directory_named_sops_yaml(self, tmp_path: Path) -> None:
        """Directory named .sops.yaml should not be returned."""
        fake_config = tmp_path / ".sops.yaml"
        fake_config.mkdir()

        home_dir = tmp_path / "home"
        home_dir.mkdir()

        # No real .sops.yaml files exist
        test_files: set[Path] = set()

        original_is_file = Path.is_file

        def mock_is_file(self: Path) -> bool:
            if self.name == ".sops.yaml":
                return self in test_files or self.resolve() in test_files
            return original_is_file(self)

        with (
            patch("kstlib.cli.commands.secrets.common.Path.home", return_value=home_dir),
            patch.object(Path, "is_file", mock_is_file),
        ):
            result = find_sops_config(tmp_path)

        assert result is None


__all__ = ["TestFindSopsConfig"]
