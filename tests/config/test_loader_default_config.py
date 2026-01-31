"""Tests for loading the fallback configuration bundled with the package."""

# pylint: disable=protected-access  # Accessing internals for focused regression tests.

from __future__ import annotations

import builtins
import importlib
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

import kstlib.config.loader as loader_module

LoadDefaultConfigFn = Callable[[], dict[str, Any]]
TomlLoaderFn = Callable[[Path], dict[str, Any]]


def test_load_default_config_reads_packaged_file() -> None:
    """The fallback loader should read the conf shipped in ``src/kstlib``."""
    module = importlib.reload(loader_module)
    try:
        config_path = Path("src/kstlib/kstlib.conf.yml").resolve()
        assert config_path.is_file(), "Missing packaged default configuration"

        load_default_config = cast(LoadDefaultConfigFn, module._load_default_config)
        data = load_default_config()
        assert isinstance(data, dict)
        # Ensure a known key from the sample config is present.
        assert data.get("logger", {}) != {}
    finally:
        importlib.reload(loader_module)


def test_load_toml_file_raises_without_tomli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """If ``tomli`` is missing, the TOML loader must raise ``ConfigFormatError``."""
    original_import = builtins.__import__

    def fake_import(
        name: str,
        globals_dict: dict[str, Any] | None = None,
        locals_dict: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == "tomli":
            raise ImportError("tomli intentionally missing for test")
        return original_import(name, globals_dict, locals_dict, fromlist, level)

    monkeypatch.delitem(sys.modules, "tomli", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)

    module = importlib.reload(loader_module)
    sample = tmp_path / "simple.toml"
    sample.write_text("key = 'value'", encoding="utf-8")

    try:
        config_format_error = cast(type[Exception], module.ConfigFormatError)
        load_toml_file = cast(TomlLoaderFn, module._load_toml_file)

        with pytest.raises(config_format_error):
            load_toml_file(sample)
    finally:
        monkeypatch.undo()
        importlib.reload(loader_module)
        sample.unlink(missing_ok=True)
