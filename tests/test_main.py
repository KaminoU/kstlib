"""Tests for __main__ entry point.

These tests verify that the CLI can be invoked through python -m kstlib.
"""

import runpy
import subprocess
import sys
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

# pylint: disable=import-outside-toplevel


def test_main_module_invocation() -> None:
    """Test that `python -m kstlib` runs without errors."""
    import os

    # Force UTF-8 encoding for Rich/Typer output on Windows
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    result: CompletedProcess[bytes] = subprocess.run(
        [sys.executable, "-m", "kstlib", "--help"],
        capture_output=True,
        timeout=10,
        check=False,
        env=env,
    )
    # Decode with error handling for cross-platform compatibility
    stdout = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
    stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""

    # Provide helpful error message on failure
    assert result.returncode == 0, f"CLI failed: stdout={stdout!r}, stderr={stderr!r}"
    # Typer/Click may output to stdout or stderr depending on Python version
    combined_output = stdout + stderr
    assert "kstlib" in combined_output.lower(), f"Expected 'kstlib' in output: {combined_output!r}"


def test_main_function_import() -> None:
    """Test that main() function can be imported and is callable."""
    from kstlib.__main__ import main

    assert callable(main)


def test_main_function_calls_app() -> None:
    """Test that main() calls the CLI app."""
    with patch("kstlib.__main__.app") as mock_app:
        from kstlib.__main__ import main

        main()
        mock_app.assert_called_once()


def test_main_module_guard_executes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the __main__ guard invokes the CLI when run as a module."""
    import kstlib

    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_call(_self: object, *args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr("typer.main.Typer.__call__", fake_call)

    # Clear caches to avoid pollution from other tests
    kstlib._loaded.pop("app", None)
    sys.modules.pop("kstlib.__main__", None)
    sys.modules.pop("kstlib.cli", None)
    sys.modules.pop("kstlib.cli.app", None)
    sys.modules.pop("__main__", None)
    runpy.run_module("kstlib.__main__", run_name="__main__")

    assert calls == [((), {})]
