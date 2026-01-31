"""Tests for kstlib package initialization.

These tests verify that the package can be imported correctly and that
all public APIs are accessible.
"""

import importlib
import sys
from typing import Any

import pytest

# pylint: disable=import-outside-toplevel


def test_package_imports() -> None:
    """Test that all public APIs can be imported from kstlib."""
    from kstlib import (
        ConfigLoader,
        LogManager,
        clear_config,
        get_config,
        load_config,
        load_from_env,
        load_from_file,
        require_config,
    )
    from kstlib.meta import __version__

    # Verify imports are not None
    assert ConfigLoader is not None
    assert LogManager is not None
    assert __version__ is not None
    assert clear_config is not None
    assert get_config is not None
    assert load_config is not None
    assert load_from_env is not None
    assert load_from_file is not None
    assert require_config is not None


def test_version_format() -> None:
    """Test that __version__ has the correct format."""
    from kstlib.meta import __version__

    assert isinstance(__version__, str)
    # Version format: X.Y.Z or X.Y.Z.devN
    parts = __version__.split(".")
    assert len(parts) >= 3
    assert parts[0].isdigit()
    assert parts[1].isdigit()


def test_all_exports() -> None:
    """Test that __all__ contains expected exports."""
    import kstlib

    assert hasattr(kstlib, "__all__")
    # Check core exports
    assert "ConfigLoader" in kstlib.__all__
    assert "LogManager" in kstlib.__all__
    assert "load_config" in kstlib.__all__
    assert "get_config" in kstlib.__all__
    assert "clear_config" in kstlib.__all__
    assert "require_config" in kstlib.__all__
    assert "load_from_file" in kstlib.__all__
    assert "load_from_env" in kstlib.__all__


def test_exception_imports() -> None:
    """Test that exception classes can be imported."""
    from kstlib import (
        ConfigCircularIncludeError,
        ConfigError,
        ConfigFileNotFoundError,
        ConfigFormatError,
        ConfigNotLoadedError,
        KstlibError,
    )

    # Verify they are exception classes
    assert issubclass(KstlibError, Exception)
    assert issubclass(ConfigError, KstlibError)
    assert issubclass(ConfigNotLoadedError, ConfigError)
    assert issubclass(ConfigFileNotFoundError, ConfigError)
    assert issubclass(ConfigFormatError, ConfigError)
    assert issubclass(ConfigCircularIncludeError, ConfigError)


def test_cli_app_import() -> None:
    """Test that CLI app can be imported."""
    import kstlib

    # Clear caches to ensure fresh import (avoids pollution from other tests)
    kstlib._loaded.pop("app", None)
    sys.modules.pop("kstlib.cli", None)
    sys.modules.pop("kstlib.cli.app", None)

    # Re-access the app through lazy loading
    app = kstlib.app

    assert callable(app)


def test_traceback_install_respects_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure Rich traceback installation honours the KSTLIB_TRACEBACK flag."""

    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fake_install(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr("rich.traceback.install", fake_install)

    monkeypatch.setenv("KSTLIB_TRACEBACK", "0")
    sys.modules.pop("kstlib", None)
    importlib.import_module("kstlib")
    assert not calls

    monkeypatch.setenv("KSTLIB_TRACEBACK", "1")
    sys.modules.pop("kstlib", None)
    importlib.import_module("kstlib")
    assert len(calls) == 1

    sys.modules.pop("kstlib", None)


def test_install_rich_traceback_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that install_rich_traceback is idempotent (only installs once)."""
    import kstlib

    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fake_install(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr("rich.traceback.install", fake_install)

    # Reset the installed flag
    kstlib._traceback_installed = False

    # First call should install
    kstlib.install_rich_traceback()
    assert len(calls) == 1

    # Second call should be a no-op (early return)
    kstlib.install_rich_traceback()
    assert len(calls) == 1  # Still 1, not 2

    # Reset for other tests
    kstlib._traceback_installed = False


def test_cache_submodule_lazy_load() -> None:
    """Test that cache submodule is lazily loaded correctly."""
    import kstlib

    # Clear the cache to force re-load
    kstlib._loaded.pop("cache", None)

    # Access cache attribute
    cache = kstlib.cache
    assert cache is not None
    # Verify it's the cache decorator, not the module
    assert callable(cache)


def test_getattr_unknown_attribute_raises() -> None:
    """Test that accessing unknown attribute raises AttributeError."""
    import kstlib

    with pytest.raises(AttributeError, match="module 'kstlib' has no attribute 'nonexistent_attr'"):
        _ = kstlib.nonexistent_attr


def test_lazy_import_uses_cache() -> None:
    """Test that lazy imports are cached after first access."""
    import kstlib

    # Clear and reload
    kstlib._loaded.pop("ConfigLoader", None)

    # First access loads it
    loader1 = kstlib.ConfigLoader

    # Second access should come from cache
    loader2 = kstlib.ConfigLoader

    assert loader1 is loader2
    assert "ConfigLoader" in kstlib._loaded


def test_submodules_lazy_load() -> None:
    """Test that submodules (mail, secrets, ui) are lazily loaded."""
    import kstlib

    # Clear cache to force re-load
    kstlib._loaded.pop("mail", None)
    kstlib._loaded.pop("secrets", None)
    kstlib._loaded.pop("ui", None)

    # Access submodules
    mail_mod = kstlib.mail
    secrets_mod = kstlib.secrets
    ui_mod = kstlib.ui

    # Verify they are modules
    assert hasattr(mail_mod, "__name__")
    assert hasattr(secrets_mod, "__name__")
    assert hasattr(ui_mod, "__name__")

    # Verify they are cached
    assert "mail" in kstlib._loaded
    assert "secrets" in kstlib._loaded
    assert "ui" in kstlib._loaded


def test_lazy_import_error_handling_for_config_not_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that ConfigNotLoadedError import error returns None gracefully."""
    import kstlib

    # Clear cache
    kstlib._loaded.pop("ConfigNotLoadedError", None)

    # Mock importlib to raise ImportError for ConfigNotLoadedError
    original_import = importlib.import_module

    def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "kstlib.config.exceptions":
            raise ImportError("Simulated minimal install")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", mock_import)

    # Should return None instead of raising
    result = kstlib.__getattr__("ConfigNotLoadedError")
    assert result is None
    assert kstlib._loaded["ConfigNotLoadedError"] is None


def test_lazy_import_error_raises_for_other_attrs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that ImportError is raised for non-ConfigNotLoadedError attributes."""
    import kstlib

    # Clear cache
    kstlib._loaded.pop("LogManager", None)

    # Mock importlib to raise ImportError
    original_import = importlib.import_module

    def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "kstlib.logging":
            raise ImportError("Simulated import error")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", mock_import)

    # Should raise ImportError for LogManager
    with pytest.raises(ImportError, match="Simulated import error"):
        _ = kstlib.__getattr__("LogManager")
