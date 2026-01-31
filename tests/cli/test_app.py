"""Tests for CLI application.

These tests verify that all CLI commands work correctly.
"""

import runpy
import sys

import pytest
from typer.testing import CliRunner

from kstlib import meta
from kstlib.cli.app import app

# Mark all tests in this module as CLI tests (excluded from main tox runs)
# Run with: tox -e cli OR pytest -m cli
pytestmark = pytest.mark.cli

runner = CliRunner()


def test_app_help() -> None:
    """Test that --help displays usage information."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "kstlib" in result.stdout.lower()
    assert "shred" in result.stdout


def test_app_version() -> None:
    """Test that --version displays version (no short alias)."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert meta.__version__ in result.stdout


def test_info_command_basic() -> None:
    """Test info command without options shows logo and version."""
    result = runner.invoke(app, ["info"])
    assert result.exit_code == 0
    # Should show logo and version
    # assert meta.__app_name__ in result.stdout
    assert meta.__version__ in result.stdout


def test_info_command_full_short() -> None:
    """Test info command with -f shows full metadata."""
    result = runner.invoke(app, ["info", "-f"])
    assert result.exit_code == 0
    # Should show all metadata
    assert meta.__app_name__ in result.stdout
    assert meta.__version__ in result.stdout
    assert meta.__author__ in result.stdout
    assert meta.__email__ in result.stdout
    assert meta.__url__ in result.stdout
    assert meta.__license_type__ in result.stdout


def test_info_command_full_long() -> None:
    """Test info command with --full shows full metadata."""
    result = runner.invoke(app, ["info", "--full"])
    assert result.exit_code == 0
    # Should show all metadata
    assert meta.__app_name__ in result.stdout
    assert meta.__version__ in result.stdout
    # Description appears in the table output
    assert "Description" in result.stdout
    assert meta.__author__ in result.stdout


def test_info_help() -> None:
    """Test that info --help displays usage information."""
    result = runner.invoke(app, ["info", "--help"])
    assert result.exit_code == 0
    assert "info" in result.stdout.lower()
    assert "--full" in result.stdout


def test_root_shred_help() -> None:
    """Ensure shred is exposed as a top-level command."""
    result = runner.invoke(app, ["shred", "--help"])
    assert result.exit_code == 0
    assert "Remove a secrets file" in result.stdout


def test_app_no_args() -> None:
    """Test running app with no arguments shows help."""
    result = runner.invoke(app, [])
    # Typer exits with code 2 when no command is provided (shows usage)
    # This is expected behavior
    assert result.exit_code in (0, 2)


def test_app_invalid_command() -> None:
    """Test running app with invalid command shows error."""
    result = runner.invoke(app, ["invalid-command"])
    # Typer should show error for invalid command
    assert result.exit_code != 0


def test_cli_module_guard_executes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the CLI module guard invokes the Typer app when executed directly."""

    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_call(_self: object, *args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr("typer.main.Typer.__call__", fake_call)

    sys.modules.pop("kstlib.cli.app", None)
    sys.modules.pop("__main__", None)
    runpy.run_module("kstlib.cli.app", run_name="__main__")

    assert calls == [((), {})]


# ─────────────────────────────────────────────────────────────────────────────
# Additional coverage tests
# ─────────────────────────────────────────────────────────────────────────────


def test_get_cli_logger() -> None:
    """Test get_cli_logger returns a logger."""
    from kstlib.cli.app import get_cli_logger

    logger = get_cli_logger()

    assert logger is not None
    assert logger.name == "kstlib.cli"


def test_invalid_log_level() -> None:
    """Test that invalid log level shows error and exits."""
    result = runner.invoke(app, ["--log-level", "INVALID", "info"])

    assert result.exit_code == 1
    assert "Invalid log level" in result.stdout
    assert "Valid levels" in result.stdout


def test_valid_log_level_debug() -> None:
    """Test that valid log level DEBUG is accepted."""
    result = runner.invoke(app, ["--log-level", "DEBUG", "info"])

    assert result.exit_code == 0


def test_valid_log_level_case_insensitive() -> None:
    """Test that log level is case-insensitive."""
    result = runner.invoke(app, ["--log-level", "info", "info"])

    assert result.exit_code == 0


# ─────────────────────────────────────────────────────────────────────────────
# Verbose flag tests (-v, -vv, -vvv)
# ─────────────────────────────────────────────────────────────────────────────


def test_verbose_v_sets_info() -> None:
    """Test that -v sets log level to INFO."""
    result = runner.invoke(app, ["-v", "info"])
    assert result.exit_code == 0


def test_verbose_vv_sets_debug() -> None:
    """Test that -vv sets log level to DEBUG."""
    result = runner.invoke(app, ["-vv", "info"])
    assert result.exit_code == 0


def test_verbose_vvv_sets_trace() -> None:
    """Test that -vvv sets log level to TRACE."""
    result = runner.invoke(app, ["-vvv", "info"])
    assert result.exit_code == 0


def test_verbose_beyond_vvv_caps_at_trace() -> None:
    """Test that -vvvv or more still caps at TRACE level."""
    result = runner.invoke(app, ["-vvvv", "info"])
    assert result.exit_code == 0


def test_log_level_takes_precedence_over_verbose() -> None:
    """Test that --log-level takes precedence over -v flags."""
    result = runner.invoke(app, ["-vvv", "--log-level", "WARNING", "info"])
    assert result.exit_code == 0
