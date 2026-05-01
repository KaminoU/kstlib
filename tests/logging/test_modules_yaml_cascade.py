"""Tests for kstlib.logging.modules YAML cascade and CLI override."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import patch

import pytest
from box import Box

from kstlib.logging.manager import LogManager


def _make_global_config(
    *,
    kstlib_modules: dict[str, str] | None = None,
    preset_modules: dict[str, str] | None = None,
    preset_name: str = "dev",
) -> Box:
    """Build a minimal global config with optional modules sections."""
    raw: dict[str, Any] = {"logger": {"presets": {preset_name: {}}}}
    if kstlib_modules is not None:
        raw["kstlib"] = {"logging": {"modules": kstlib_modules}}
    if preset_modules is not None:
        raw["logger"]["presets"][preset_name]["modules"] = preset_modules
    return Box(raw, default_box=True)


class TestResolveModuleLevels:
    """Pure resolution logic (no logger side effects)."""

    def test_default_no_modules_returns_empty(self) -> None:
        """No global, no preset, no explicit -> empty mapping."""
        with patch("kstlib.logging.manager.get_config", side_effect=FileNotFoundError):
            assert LogManager._resolve_module_levels(None, None) == {}

    def test_global_only(self) -> None:
        """Only kstlib.logging.modules set -> all returned."""
        cfg = _make_global_config(kstlib_modules={"kstlib.rapi": "WARNING"})
        with patch("kstlib.logging.manager.get_config", return_value=cfg):
            result = LogManager._resolve_module_levels(None, None)
        assert result == {"kstlib.rapi": "WARNING"}

    def test_preset_only(self) -> None:
        """Only logger.presets.<active>.modules set -> applied when preset matches."""
        cfg = _make_global_config(preset_modules={"kstlib.transform": "DEBUG"}, preset_name="dev")
        with patch("kstlib.logging.manager.get_config", return_value=cfg):
            result = LogManager._resolve_module_levels(None, "dev")
        assert result == {"kstlib.transform": "DEBUG"}

    def test_preset_only_ignored_without_active_preset(self) -> None:
        """Preset entries are ignored when no preset is active."""
        cfg = _make_global_config(preset_modules={"kstlib.transform": "DEBUG"}, preset_name="dev")
        with patch("kstlib.logging.manager.get_config", return_value=cfg):
            result = LogManager._resolve_module_levels(None, None)
        assert result == {}

    def test_preset_overrides_global_on_shared_key(self) -> None:
        """Preset wins on conflict, global keeps its unique keys."""
        cfg = _make_global_config(
            kstlib_modules={"kstlib.rapi.config": "WARNING", "kstlib.transform": "DEBUG"},
            preset_modules={"kstlib.rapi.config": "TRACE"},
            preset_name="dev",
        )
        with patch("kstlib.logging.manager.get_config", return_value=cfg):
            result = LogManager._resolve_module_levels(None, "dev")
        assert result == {"kstlib.rapi.config": "TRACE", "kstlib.transform": "DEBUG"}

    def test_explicit_config_replaces_yaml_entirely(self) -> None:
        """Explicit modules in config kwarg replace ALL YAML layers (CLI override)."""
        cfg = _make_global_config(
            kstlib_modules={"kstlib.rapi": "WARNING"},
            preset_modules={"kstlib.transform": "DEBUG"},
            preset_name="dev",
        )
        with patch("kstlib.logging.manager.get_config", return_value=cfg):
            result = LogManager._resolve_module_levels({"modules": {"kstlib.cli": "TRACE"}}, "dev")
        assert result == {"kstlib.cli": "TRACE"}

    def test_explicit_empty_modules_kwarg_returns_empty(self) -> None:
        """Explicit empty modules dict drops everything (intentional kill switch)."""
        cfg = _make_global_config(kstlib_modules={"kstlib.rapi": "WARNING"})
        with patch("kstlib.logging.manager.get_config", return_value=cfg):
            result = LogManager._resolve_module_levels({"modules": {}}, None)
        assert result == {}

    def test_explicit_modules_none_is_kill_switch(self) -> None:
        """``config={"modules": None}`` is an explicit kill switch, not a fall-back.

        The presence of the ``modules`` key (even with ``None`` value) signals
        the caller wants to override the YAML cascade. ``None`` then means
        "no per-module config at all" rather than "use whatever is in YAML".
        Callers who want the YAML must omit the key entirely.
        """
        cfg = _make_global_config(kstlib_modules={"kstlib.rapi": "WARNING"})
        with patch("kstlib.logging.manager.get_config", return_value=cfg):
            result = LogManager._resolve_module_levels({"modules": None}, None)
        assert result == {}

    def test_config_without_modules_key_falls_back_to_yaml(self) -> None:
        """A config dict that does NOT mention ``modules`` triggers the YAML cascade."""
        cfg = _make_global_config(kstlib_modules={"kstlib.rapi": "WARNING"})
        with patch("kstlib.logging.manager.get_config", return_value=cfg):
            result = LogManager._resolve_module_levels({"console": {"level": "DEBUG"}}, None)
        assert result == {"kstlib.rapi": "WARNING"}


class TestApplyModuleLevels:
    """Side-effect application: setLevel + warnings on invalid entries."""

    def test_no_modules_is_noop(self) -> None:
        """Empty mapping does not call setLevel on anything."""
        mgr = LogManager(name="kstlib_test_noop", preset=None, register=False)
        mgr._module_levels = {}
        # Should not raise; no observable effect
        mgr._apply_module_levels()

    def test_apply_sets_logger_level(self) -> None:
        """Valid entry triggers logging.getLogger(name).setLevel(level)."""
        mgr = LogManager(name="kstlib_test_apply", preset=None, register=False)
        mgr._module_levels = {"kstlib.test_apply_target": "DEBUG"}
        mgr._apply_module_levels()
        assert logging.getLogger("kstlib.test_apply_target").level == logging.DEBUG

    def test_apply_handles_trace_and_success(self) -> None:
        """TRACE and SUCCESS custom levels are accepted."""
        mgr = LogManager(name="kstlib_test_levels", preset=None, register=False)
        mgr._module_levels = {
            "kstlib.test_trace_target": "TRACE",
            "kstlib.test_success_target": "SUCCESS",
        }
        mgr._apply_module_levels()
        assert logging.getLogger("kstlib.test_trace_target").level == 5
        assert logging.getLogger("kstlib.test_success_target").level == 25

    def test_invalid_logger_name_skipped(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Logger name not starting with 'kstlib.' is rejected with [SECURITY] WARNING."""
        mgr = LogManager(name="kstlib_test_invalid_name", preset=None, register=False)
        mgr._module_levels = {"myapp.foo": "DEBUG"}
        target = logging.getLogger("myapp.foo")
        target.setLevel(logging.NOTSET)

        caplog.set_level(logging.WARNING, logger="kstlib_logging_internal")
        mgr._apply_module_levels()

        # Target was not modified
        assert target.level == logging.NOTSET
        # WARNING [SECURITY] was emitted on the internal logger
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("[SECURITY]" in r.getMessage() and "myapp.foo" in r.getMessage() for r in warnings)

    def test_invalid_level_skipped(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Unknown level name is rejected with WARNING and the entry is skipped."""
        mgr = LogManager(name="kstlib_test_invalid_level", preset=None, register=False)
        mgr._module_levels = {"kstlib.test_bad_level_target": "VERBOSE"}
        target = logging.getLogger("kstlib.test_bad_level_target")
        target.setLevel(logging.NOTSET)

        caplog.set_level(logging.WARNING, logger="kstlib_logging_internal")
        mgr._apply_module_levels()

        assert target.level == logging.NOTSET
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("VERBOSE" in r.getMessage() for r in warnings)

    def test_partial_invalid_does_not_block_valid(self) -> None:
        """A bad entry is skipped without aborting the rest."""
        mgr = LogManager(name="kstlib_test_partial", preset=None, register=False)
        mgr._module_levels = {
            "kstlib.test_partial_ok": "WARNING",
            "myapp.bad_prefix": "DEBUG",
            "kstlib.test_partial_bad_level": "VERBOSE",
            "kstlib.test_partial_ok2": "ERROR",
        }
        mgr._apply_module_levels()

        assert logging.getLogger("kstlib.test_partial_ok").level == logging.WARNING
        assert logging.getLogger("kstlib.test_partial_ok2").level == logging.ERROR

    def test_level_name_case_insensitive(self) -> None:
        """Level matching tolerates lowercase / mixed case input."""
        mgr = LogManager(name="kstlib_test_case", preset=None, register=False)
        mgr._module_levels = {
            "kstlib.test_case_lower": "debug",
            "kstlib.test_case_mixed": "Warning",
        }
        mgr._apply_module_levels()
        assert logging.getLogger("kstlib.test_case_lower").level == logging.DEBUG
        assert logging.getLogger("kstlib.test_case_mixed").level == logging.WARNING


class TestEndToEndRegister:
    """register=True path applies module levels after the root injection."""

    def test_register_applies_yaml_modules(self) -> None:
        """LogManager(register=True) consumes the YAML cascade and calls setLevel."""
        cfg = _make_global_config(
            kstlib_modules={"kstlib.test_e2e_global": "WARNING"},
            preset_modules={"kstlib.test_e2e_preset": "TRACE"},
            preset_name="prod",
        )
        with patch("kstlib.logging.manager.get_config", return_value=cfg):
            LogManager(name="kstlib", preset="prod", register=True)

        assert logging.getLogger("kstlib.test_e2e_global").level == logging.WARNING
        assert logging.getLogger("kstlib.test_e2e_preset").level == 5  # TRACE

    def test_register_with_explicit_modules_replaces_yaml(self) -> None:
        """An explicit ``config={"modules": ...}`` (CLI path) bypasses the YAML.

        Two complementary assertions :
          1. The resolved ``_module_levels`` only contains the CLI keys
             (no leak from kstlib.logging.modules nor preset.modules)
          2. The CLI-targeted logger gets the requested level

        The state of the YAML-targeted loggers is NOT asserted: ``register=True``
        propagates ``TRACE_LEVEL`` to every pre-existing ``kstlib.*`` logger as
        a side effect, which would interfere with a direct level check.
        """
        cfg = _make_global_config(
            kstlib_modules={"kstlib.test_e2e_yaml": "WARNING"},
            preset_modules={"kstlib.test_e2e_yaml_preset": "DEBUG"},
            preset_name="dev",
        )
        with patch("kstlib.logging.manager.get_config", return_value=cfg):
            mgr = LogManager(
                name="kstlib",
                preset="dev",
                config={"modules": {"kstlib.test_e2e_cli": "ERROR"}},
                register=True,
            )

        assert mgr._module_levels == {"kstlib.test_e2e_cli": "ERROR"}
        assert logging.getLogger("kstlib.test_e2e_cli").level == logging.ERROR
