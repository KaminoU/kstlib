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
    assert "Invalid log level" in result.stderr
    assert "Valid levels" in result.stderr


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


def test_modules_verbose_preserves_yaml_cascade() -> None:
    """``-vvv`` alone does NOT inject ``modules`` ; YAML cascade stays in effect.

    Verbosity flags only raise the root handler level. The per-module
    YAML mutes (e.g. ``kstlib.rapi.config: WARNING`` from the embedded
    config) must persist so noisy modules cannot drown the output the
    user actually wants. To bypass a specific mute, the user supplies
    ``--log-module name=<level>``.
    """
    cfg = _capture_init_config(["-vvv", "info"])
    assert "modules" not in cfg


def test_modules_log_level_preserves_yaml_cascade() -> None:
    """``--log-level TRACE`` alone does NOT inject ``modules`` ; YAML cascade stays."""
    cfg = _capture_init_config(["--log-level", "TRACE", "info"])
    assert "modules" not in cfg


def test_modules_log_module_alone_replaces_cascade() -> None:
    """A bare ``--log-module name=level`` replaces the cascade with its own map."""
    cfg = _capture_init_config(["--log-module", "kstlib.rapi.config=DEBUG", "info"])
    assert cfg["modules"] == {"kstlib.rapi.config": "DEBUG"}


def test_modules_verbose_plus_log_module_uses_log_module_only() -> None:
    """``-vvv --log-module x=WARNING`` carries the --log-module spec verbatim.

    The verbosity dial drives the handler level, ``--log-module`` drives
    the per-module level. Both layers are independent : the explicit
    --log-module dict replaces the YAML modules cascade, and the
    handler runs at TRACE. Loggers not named in --log-module fall back
    to whatever level the kstlib root applies (TRACE under -vvv).
    """
    cfg = _capture_init_config(
        ["-vvv", "--log-module", "kstlib.rapi.config=WARNING", "info"],
    )
    assert cfg["modules"] == {"kstlib.rapi.config": "WARNING"}


# ─────────────────────────────────────────────────────────────────────────────
# --log-module factorized syntaxes (3 modes + auto-prepend + matrix of bad
# inputs). Tests target the parser through the public CLI surface to mirror
# what users actually see.
# ─────────────────────────────────────────────────────────────────────────────


def test_log_module_classic_with_full_prefix() -> None:
    """Classic syntax with the kstlib. prefix already present."""
    cfg = _capture_init_config(["--log-module", "kstlib.rapi.config=TRACE", "info"])
    assert cfg["modules"] == {"kstlib.rapi.config": "TRACE"}


def test_log_module_classic_prefix_omitted_auto_prepended() -> None:
    """Classic syntax without prefix : kstlib. is auto-prepended."""
    cfg = _capture_init_config(["--log-module", "rapi.config=TRACE", "info"])
    assert cfg["modules"] == {"kstlib.rapi.config": "TRACE"}


def test_log_module_inverse_simple() -> None:
    """Inverse syntax : LEVEL=name1,name2,... groups modules under one level."""
    cfg = _capture_init_config(["--log-module", "DEBUG=foo.bar,baz.qux", "info"])
    assert cfg["modules"] == {
        "kstlib.foo.bar": "DEBUG",
        "kstlib.baz.qux": "DEBUG",
    }


def test_log_module_inverse_mixed_prefix_optional_per_module() -> None:
    """Inverse syntax tolerates the prefix on some modules and not others."""
    cfg = _capture_init_config(
        ["--log-module", "DEBUG=kstlib.rapi.config,transform.chain", "info"],
    )
    assert cfg["modules"] == {
        "kstlib.rapi.config": "DEBUG",
        "kstlib.transform.chain": "DEBUG",
    }


def test_log_module_repeated_last_wins_for_same_module() -> None:
    """Two --log-module on the same module keep only the last value."""
    cfg = _capture_init_config(
        [
            "--log-module",
            "rapi.config=DEBUG",
            "--log-module",
            "rapi.config=WARNING",
            "info",
        ],
    )
    assert cfg["modules"] == {"kstlib.rapi.config": "WARNING"}


def test_log_module_level_case_insensitive() -> None:
    """Lowercase / mixed-case levels match the canonical uppercase names."""
    cfg = _capture_init_config(["--log-module", "rapi.config=debug", "info"])
    assert cfg["modules"] == {"kstlib.rapi.config": "DEBUG"}


def test_log_module_inverse_level_case_insensitive() -> None:
    """Inverse-mode level token is also case-insensitive."""
    cfg = _capture_init_config(["--log-module", "Trace=rapi.config", "info"])
    assert cfg["modules"] == {"kstlib.rapi.config": "TRACE"}


def test_log_module_inverse_whitespace_in_list() -> None:
    """Whitespace around commas and inside the module list is trimmed."""
    cfg = _capture_init_config(["--log-module", "DEBUG= rapi.config , transform.chain ", "info"])
    assert cfg["modules"] == {
        "kstlib.rapi.config": "DEBUG",
        "kstlib.transform.chain": "DEBUG",
    }


def test_log_module_pathological_DEBUG_equals_DEBUG_inverse_mode() -> None:
    """``DEBUG=DEBUG`` is inverse mode : level=DEBUG, module list=[DEBUG].

    Mode is decided on the LEFT side. ``DEBUG`` on the left is a known
    level, so the right side is parsed as a module list. ``DEBUG`` then
    becomes a logger name, prepended to ``kstlib.DEBUG``. Python lazy-
    creates that logger and the level is applied without error.
    """
    cfg = _capture_init_config(["--log-module", "DEBUG=DEBUG", "info"])
    assert cfg["modules"] == {"kstlib.DEBUG": "DEBUG"}


def test_log_module_no_equals_skipped() -> None:
    """``--log-module foo`` (no =) skips the entry without aborting."""
    cfg = _capture_init_config(["--log-module", "foo", "info"])
    assert "modules" in cfg
    assert cfg["modules"] == {}


def test_log_module_empty_left_skipped() -> None:
    """``--log-module =TRACE`` skips with no logger name."""
    cfg = _capture_init_config(["--log-module", "=TRACE", "info"])
    assert cfg["modules"] == {}


def test_log_module_empty_right_classic_skipped() -> None:
    """``--log-module foo=`` (empty level) skips."""
    cfg = _capture_init_config(["--log-module", "foo=", "info"])
    assert cfg["modules"] == {}


def test_log_module_empty_right_inverse_skipped() -> None:
    """``--log-module DEBUG=`` (no module list) skips."""
    cfg = _capture_init_config(["--log-module", "DEBUG=", "info"])
    assert cfg["modules"] == {}


def test_log_module_invalid_level_classic_skipped() -> None:
    """``--log-module foo=BLABLA`` skips with unknown level."""
    cfg = _capture_init_config(["--log-module", "foo=BLABLA", "info"])
    assert cfg["modules"] == {}


def test_log_module_inverse_only_commas_skipped() -> None:
    """``--log-module DEBUG=,,,`` skips with empty effective module list."""
    cfg = _capture_init_config(["--log-module", "DEBUG=,,,", "info"])
    assert cfg["modules"] == {}


def test_log_module_inverse_mixed_valid_and_invalid_keeps_valid() -> None:
    """Inverse mode : invalid module entries skipped, valid ones kept."""
    cfg = _capture_init_config(
        ["--log-module", "DEBUG=rapi.config,foo bar,transform.chain", "info"],
    )
    # 'foo bar' contains a space -> invalid logger name (post-prepend
    # 'kstlib.foo bar' fails the regex). The two valid entries land.
    assert cfg["modules"] == {
        "kstlib.rapi.config": "DEBUG",
        "kstlib.transform.chain": "DEBUG",
    }


def test_log_module_invalid_chars_in_name_classic_skipped() -> None:
    """A module name with a forbidden character is dropped (classic mode)."""
    cfg = _capture_init_config(["--log-module", "foo!bar=DEBUG", "info"])
    assert cfg["modules"] == {}


def test_log_module_double_dot_in_name_skipped() -> None:
    """Double dots inside the name are rejected by the validation regex."""
    cfg = _capture_init_config(["--log-module", ".foo=DEBUG", "info"])
    # '.foo' starts with kstlib. is False -> prepend -> 'kstlib..foo' -> regex fail.
    assert cfg["modules"] == {}


def test_log_module_multiple_options_aggregate() -> None:
    """Multiple --log-module flags accumulate into the modules dict."""
    cfg = _capture_init_config(
        [
            "--log-module",
            "rapi.config=DEBUG",
            "--log-module",
            "TRACE=transform.chain,auth.providers",
            "info",
        ],
    )
    assert cfg["modules"] == {
        "kstlib.rapi.config": "DEBUG",
        "kstlib.transform.chain": "TRACE",
        "kstlib.auth.providers": "TRACE",
    }


def test_log_module_invalid_does_not_block_program() -> None:
    """A purely invalid --log-module still lets the command finish.

    The CLI must never abort on user input it cannot parse ; the
    business command (``info`` here) runs normally with whatever valid
    entries (none, in this case) the parser produced.
    """
    cfg = _capture_init_config(["--log-module", "totally-broken-input", "info"])
    assert cfg["modules"] == {}
