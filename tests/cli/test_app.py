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


# ─────────────────────────────────────────────────────────────────────────────
# --log-module + verbosity cascade reset (Layer 4 of the modules cascade)
# ─────────────────────────────────────────────────────────────────────────────


def _capture_init_config(args: list[str]) -> dict[str, object]:
    """Run the CLI with ``args`` and capture the dict passed to ``init_logging``.

    Patching targets the Typer callback's own globals dict rather than
    ``sys.modules["kstlib.cli.app"]`` because ``test_cli_module_guard_executes``
    pops the module from ``sys.modules`` before re-running it under
    ``__main__``. After that test the module dict referenced by the
    callback's closure is detached from the import system, so a normal
    ``monkeypatch.setattr`` on the path string can no longer find it.
    """
    registered = app.registered_callback
    assert registered is not None, "Typer root callback unexpectedly missing"
    callback = registered.callback
    assert callback is not None, "Typer root callback unexpectedly missing"
    callback_globals = callback.__globals__

    captured: dict[str, object] = {}

    def _stub(*, config: dict[str, object] | None = None, **_: object) -> object:
        captured.update(config or {})

        class _StubLogger:
            def debug(self, *_a: object, **_k: object) -> None:
                pass

        return _StubLogger()

    original = callback_globals["init_logging"]
    callback_globals["init_logging"] = _stub
    try:
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.stdout
    finally:
        callback_globals["init_logging"] = original
    return captured


def test_modules_default_no_flag_falls_through_to_yaml_cascade() -> None:
    """No verbosity flag and no --log-module : init_config has no 'modules' key.

    The absence of the key is the signal that the YAML cascade should
    apply. Resolving the cascade is LogManager's job; the CLI must not
    pre-fill ``modules`` when the user did not ask for any override.
    """
    cfg = _capture_init_config(["info"])
    assert "modules" not in cfg


def test_modules_verbose_resets_cascade_to_empty() -> None:
    """``-vvv`` alone resets the YAML modules cascade to ``{}``.

    The user intent ('show me everything') is incompatible with a hidden
    YAML mute. Setting ``modules: {}`` on the explicit init_config is the
    documented kill switch that bypasses the YAML.
    """
    cfg = _capture_init_config(["-vvv", "info"])
    assert cfg["modules"] == {}


def test_modules_log_level_resets_cascade_to_empty() -> None:
    """``--log-level TRACE`` alone resets the YAML modules cascade to ``{}``."""
    cfg = _capture_init_config(["--log-level", "TRACE", "info"])
    assert cfg["modules"] == {}


def test_modules_log_module_alone_replaces_cascade() -> None:
    """A bare ``--log-module name=level`` replaces the cascade with its own map."""
    cfg = _capture_init_config(["--log-module", "kstlib.rapi.config=DEBUG", "info"])
    assert cfg["modules"] == {"kstlib.rapi.config": "DEBUG"}


def test_modules_verbose_plus_log_module_log_module_wins() -> None:
    """``-vvv --log-module x=WARNING`` keeps the user's --log-module spec.

    The verbosity dial reset is suppressed because the user gave a more
    precise specification with --log-module. Other modules will inherit
    TRACE through the kstlib root, but the explicitly named module is
    pinned to the user's choice.
    """
    cfg = _capture_init_config(
        ["-vvv", "--log-module", "kstlib.rapi.config=WARNING", "info"],
    )
    assert cfg["modules"] == {"kstlib.rapi.config": "WARNING"}
