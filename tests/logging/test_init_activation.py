"""Tests for init_logging dual-object fix and get_logger lazy auto-init.

Covers the FEAT/logging-internal-activation feature set:
- Config-driven opt-in auto-init via kstlib.logging.enabled
- Silent fallback on config errors
- Fallback to 'prod' preset with stderr notice on invalid preset name
- LogManager registration in logging.Logger.manager.loggerDict (fixes the
  dual-object bug where logging.getLogger("kstlib") used to return a plain
  Logger instead of the LogManager)
- No double-init when init_logging is called multiple times
"""

from __future__ import annotations

import io
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from box import Box

import kstlib.logging as logging_pkg
from kstlib.logging import (
    LogManager,
    get_logger,
    init_logging,
    list_available_presets,
)
from kstlib.logging import manager as manager_module


def _reset_kstlib_hierarchy() -> None:
    """Reset the kstlib logger hierarchy without breaking parent pointers.

    Remove the "kstlib" entry so a subsequent init_logging can re-register
    a fresh LogManager, and neutralize existing "kstlib.*" child loggers by
    clearing their handlers and levels. Popping the children would leave
    grandchildren with dangling parent pointers created during previous
    tests, which then fail to propagate under pytest's caplog fixture.
    """
    logging.Logger.manager.loggerDict.pop("kstlib", None)
    for name, entry in list(logging.Logger.manager.loggerDict.items()):
        if not name.startswith("kstlib."):
            continue
        if isinstance(entry, logging.Logger):
            entry.handlers.clear()
            entry.setLevel(logging.NOTSET)
            entry.propagate = True
            entry.disabled = False


@pytest.fixture(autouse=True)
def _reset_root_logger() -> Iterator[None]:
    """Reset module-level singleton and Python manager entry between tests."""
    logging_pkg._root_logger = None
    logging_pkg._preset_warning_emitted = False
    _reset_kstlib_hierarchy()
    yield
    logging_pkg._root_logger = None
    logging_pkg._preset_warning_emitted = False
    _reset_kstlib_hierarchy()


def _make_fake_config(kstlib_section: dict[str, Any] | None) -> Box:
    """Build a Box config that exposes a kstlib section via .get()."""
    payload: dict[str, Any] = {}
    if kstlib_section is not None:
        payload["kstlib"] = kstlib_section
    # default_box=True so missing keys do not raise on access
    return Box(payload, default_box=True, default_box_attr=None)


# ============================================================================
# get_logger lazy auto-init
# ============================================================================


def test_auto_init_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_logger triggers init_logging when kstlib.logging.enabled is true."""
    fake = _make_fake_config({"logging": {"enabled": True, "preset": "dev"}})
    monkeypatch.setattr("kstlib.config.get_config", lambda: fake)

    assert logging_pkg._root_logger is None
    get_logger("kstlib.test_auto_init")
    # _root_logger is typed LogManager | None, so narrowing to not-None is
    # enough; an extra isinstance() would trip mypy --warn-unreachable.
    assert logging_pkg._root_logger is not None


def test_auto_init_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_logger does nothing when no kstlib.logging section is present."""
    fake = _make_fake_config(None)
    monkeypatch.setattr("kstlib.config.get_config", lambda: fake)

    assert logging_pkg._root_logger is None
    get_logger("kstlib.test_disabled")
    assert logging_pkg._root_logger is None


def test_auto_init_disabled_when_flag_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """kstlib.logging.enabled=false must not trigger auto-init."""
    fake = _make_fake_config({"logging": {"enabled": False, "preset": "dev"}})
    monkeypatch.setattr("kstlib.config.get_config", lambda: fake)

    get_logger("kstlib.test_flag_false")
    assert logging_pkg._root_logger is None


def test_auto_init_silent_on_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any exception raised by get_config() is swallowed silently."""

    def _boom() -> Box:
        raise RuntimeError("config file unreadable")

    monkeypatch.setattr("kstlib.config.get_config", _boom)

    # Must NOT raise
    logger = get_logger("kstlib.test_silent_error")
    assert logger is not None
    assert logging_pkg._root_logger is None


def test_auto_init_fallback_on_invalid_preset(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Unknown preset falls back to 'prod' and prints a stderr notice."""
    fake = _make_fake_config({"logging": {"enabled": True, "preset": "does_not_exist"}})
    monkeypatch.setattr("kstlib.config.get_config", lambda: fake)

    get_logger("kstlib.test_invalid_preset")

    captured = capsys.readouterr()
    assert "kstlib logging" in captured.err
    assert "does_not_exist" in captured.err
    assert "falling back to 'prod'" in captured.err
    assert logging_pkg._root_logger is not None


def test_auto_init_default_preset_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing preset key defaults to 'prod' without stderr output."""
    fake = _make_fake_config({"logging": {"enabled": True}})
    monkeypatch.setattr("kstlib.config.get_config", lambda: fake)

    get_logger("kstlib.test_default_preset")
    assert logging_pkg._root_logger is not None


# ============================================================================
# init_logging dual-object fix
# ============================================================================


def test_init_logging_registers_in_manager() -> None:
    """logging.getLogger('kstlib') returns the same LogManager instance."""
    root = init_logging(preset="dev")

    std_logger = logging.getLogger("kstlib")
    assert std_logger is root
    assert isinstance(std_logger, LogManager)
    # propagate stays True: library loggers must let the host aggregate
    # records at root (also keeps pytest caplog working).
    assert std_logger.propagate is True
    assert std_logger.parent is logging.root


def test_child_loggers_propagate_to_logmanager() -> None:
    """A fresh child logger created after init_logging reaches the LogManager."""
    root = init_logging(preset="dev")

    # Use a unique, never-before-seen name so _fixupParents runs fresh
    # against the current loggerDict and pins the parent to `root`.
    unique = f"kstlib.test_child_{id(root)}"
    child = logging.getLogger(unique)
    current: logging.Logger | None = child
    chain: list[logging.Logger] = []
    while current is not None:
        chain.append(current)
        current = current.parent
    assert root in chain


def test_no_double_init() -> None:
    """Calling init_logging twice does not accumulate handlers."""
    first = init_logging(preset="dev")
    first_handler_count = len(first.handlers)

    second = init_logging(preset="dev")
    # LogManager is recreated but the registered kstlib entry is replaced,
    # so logging.getLogger("kstlib") now points at `second`, and the
    # handler set is bounded by _setup_handlers()'s explicit clear().
    assert logging.getLogger("kstlib") is second
    assert len(second.handlers) == first_handler_count


# ============================================================================
# list_available_presets
# ============================================================================


def test_list_available_presets_includes_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Built-in presets are always present even when config has none."""
    fake = _make_fake_config(None)
    monkeypatch.setattr(manager_module, "get_config", lambda: fake)

    names = list_available_presets()
    for required in ("dev", "prod", "debug"):
        assert required in names


def test_list_available_presets_merges_user_presets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Presets from logger.presets in config are merged with built-ins."""
    fake = Box(
        {"logger": {"presets": {"corporate": {"output": "file"}}}},
        default_box=True,
    )
    monkeypatch.setattr(manager_module, "get_config", lambda: fake)

    names = list_available_presets()
    assert "corporate" in names
    assert "prod" in names  # built-in still there


def test_list_available_presets_silent_on_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Config read failures fall back to built-in presets without raising."""

    def _boom() -> Box:
        raise OSError("disk error")

    monkeypatch.setattr(manager_module, "get_config", _boom)

    names = list_available_presets()
    assert "prod" in names
    assert "dev" in names


# ============================================================================
# Edge: unsupported object shapes must not crash _auto_init_from_config
# ============================================================================


def test_auto_init_swallows_non_box_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_config returning an object without .get still does not raise."""

    class Weird:
        """Object with no .get method to exercise the hasattr fallback."""

    monkeypatch.setattr("kstlib.config.get_config", lambda: Weird())

    logger = get_logger("kstlib.test_weird")
    assert logger is not None
    assert logging_pkg._root_logger is None


def test_auto_init_stream_redirection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stderr notice uses sys.stderr at call time (not cached reference)."""
    fake = _make_fake_config({"logging": {"enabled": True, "preset": "bogus"}})
    monkeypatch.setattr("kstlib.config.get_config", lambda: fake)

    buf = io.StringIO()
    monkeypatch.setattr("sys.stderr", buf)

    get_logger("kstlib.test_stream")
    assert "bogus" in buf.getvalue()
    assert "falling back to 'prod'" in buf.getvalue()


def test_auto_init_no_logging_subsection(monkeypatch: pytest.MonkeyPatch) -> None:
    """kstlib section present but without a logging subsection is a no-op."""
    fake = _make_fake_config({"other_feature": {"enabled": True}})
    monkeypatch.setattr("kstlib.config.get_config", lambda: fake)

    get_logger("kstlib.test_no_sub")
    assert logging_pkg._root_logger is None


def test_auto_init_swallows_inner_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """An exception raised inside the enabled branch is also swallowed."""
    fake = _make_fake_config({"logging": {"enabled": True, "preset": "dev"}})
    monkeypatch.setattr("kstlib.config.get_config", lambda: fake)

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("LogManager exploded")

    # Patch the LogManager referenced by kstlib.logging so the auto-init
    # cascade fails inside the try block. get_logger must swallow it.
    monkeypatch.setattr(logging_pkg, "LogManager", _boom)

    # Must NOT raise and must not leave a half-initialized state
    logger = get_logger("kstlib.test_inner_boom")
    assert logger is not None
    assert logging_pkg._root_logger is None


# ============================================================================
# init_logging: level propagation to pre-existing children + .trace / .success
# ============================================================================


def test_init_logging_propagates_level_to_preexisting_children() -> None:
    """Child loggers created BEFORE init_logging get their level updated."""
    # Create a child logger first
    pre_existing = logging.getLogger("kstlib.preexisting.child")
    pre_existing.setLevel(logging.WARNING)  # Arbitrary non-TRACE level

    init_logging(preset="dev")

    # Same child should now be at TRACE level
    assert pre_existing.level == manager_module.TRACE_LEVEL


def test_trace_method_patched_on_logger_class() -> None:
    """Logger.trace is installed on the base class after init_logging."""
    init_logging(preset="dev")

    child = logging.getLogger("kstlib.test_trace_method")
    child.setLevel(manager_module.TRACE_LEVEL)

    # Call the patched method to exercise its body
    child.trace("trace message for coverage")  # type: ignore[attr-defined]


def test_success_method_patched_on_logger_class() -> None:
    """Logger.success is installed on the base class after init_logging."""
    init_logging(preset="dev")

    child = logging.getLogger("kstlib.test_success_method")
    child.setLevel(manager_module.SUCCESS_LEVEL)

    child.success("success message for coverage")  # type: ignore[attr-defined]


# ============================================================================
# get_logger(None) branches
# ============================================================================


def test_get_logger_none_returns_root_after_init() -> None:
    """get_logger() with no name returns the LogManager when available."""
    root = init_logging(preset="dev")
    assert get_logger() is root


def test_get_logger_none_without_init_returns_standard_logger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_logger() without init falls back to standard Logger named 'kstlib'."""
    # Make auto-init a no-op (disabled)
    fake = _make_fake_config(None)
    monkeypatch.setattr("kstlib.config.get_config", lambda: fake)

    logger = get_logger()
    assert logger is not None
    assert logger.name == "kstlib"
    assert logging_pkg._root_logger is None


# ============================================================================
# LogManager register parameter
# ============================================================================


def test_logmanager_register_false_isolated() -> None:
    """LogManager(register=False) stays isolated from logging.getLogger.

    The default ``register=False`` must not touch the Python logging manager,
    so ``logging.getLogger("kstlib")`` returns a standard Logger, not this
    LogManager instance. This is what makes the isolated form safe for tests.
    """
    local = LogManager(name="kstlib", preset="dev")  # register defaults to False

    std_logger = logging.getLogger("kstlib")
    assert std_logger is not local
    # The standard logger entry is a plain logging.Logger (or missing entirely)
    entry = logging.Logger.manager.loggerDict.get("kstlib")
    assert entry is not local


def test_logmanager_register_true_bootstrap() -> None:
    """LogManager(register=True) registers itself as the global kstlib root."""
    bootstrap = LogManager(name="kstlib", preset="dev", register=True)

    std_logger = logging.getLogger("kstlib")
    assert std_logger is bootstrap
    assert isinstance(std_logger, LogManager)
    assert std_logger.parent is logging.root


def test_logmanager_register_patches_child_loggers() -> None:
    """register=True patches .trace and .success on the base Logger class."""
    LogManager(name="kstlib", preset="dev", register=True)

    child = logging.getLogger("kstlib.test_register_patch")
    assert hasattr(child, "trace")
    assert hasattr(child, "success")
    child.setLevel(manager_module.TRACE_LEVEL)

    # Call the patched methods to exercise their bodies
    child.trace("trace via child")
    child.success("success via child")


def test_init_logging_is_wrapper() -> None:
    """init_logging(preset=...) is an alias of LogManager(register=True)."""
    root = init_logging(preset="dev")

    assert isinstance(root, LogManager)
    # Same identity contract: logging.getLogger('kstlib') must be that instance
    assert logging.getLogger("kstlib") is root
    assert logging_pkg._root_logger is root


def test_auto_init_invalid_preset_warning_once(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The invalid-preset stderr notice is written at most once per process."""
    fake = _make_fake_config({"logging": {"enabled": True, "preset": "nope"}})
    monkeypatch.setattr("kstlib.config.get_config", lambda: fake)

    # First call emits the warning and initializes with the 'prod' fallback
    get_logger("kstlib.test_warn_once_first")
    first = capsys.readouterr().err
    assert "nope" in first
    assert "falling back to 'prod'" in first
    assert logging_pkg._preset_warning_emitted is True

    # Reset _root_logger so auto-init runs again, but keep the flag set
    logging_pkg._root_logger = None

    # Second call: flag is still set, so no stderr output this time
    get_logger("kstlib.test_warn_once_second")
    second = capsys.readouterr().err
    assert second == ""


def test_auto_init_calls_logmanager_directly(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_logger auto-init builds LogManager(register=True) without init_logging."""
    fake = _make_fake_config({"logging": {"enabled": True, "preset": "dev"}})
    monkeypatch.setattr("kstlib.config.get_config", lambda: fake)

    # Poison init_logging to prove get_logger doesn't call it. If the old
    # implementation still routed through init_logging, this would blow up
    # the auto-init path, and since auto-init swallows exceptions,
    # _root_logger would stay None. With the new direct path, _root_logger
    # becomes a LogManager and logging.getLogger('kstlib') points at it.
    def _boom(*_a: Any, **_kw: Any) -> None:
        raise RuntimeError("init_logging must not be called by get_logger")

    monkeypatch.setattr(logging_pkg, "init_logging", _boom)

    get_logger("kstlib.test_direct_path")
    assert isinstance(logging_pkg._root_logger, LogManager)
    assert logging.getLogger("kstlib") is logging_pkg._root_logger
