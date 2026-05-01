"""Smoke regression : ``kstlib.logging.modules`` cascade silences a noisy module.

Validates the end-to-end YAML cascade against a real noisy caller
(``kstlib.rapi.config``). With ``modules: {kstlib.rapi.config: WARNING}``
set in the global config, the per-load TRACE/DEBUG/INFO stream produced
by ``load_rapi_config()`` collapses to zero records on the
``kstlib.rapi.config`` logger, even though TRACE is still active on the
rest of the ``kstlib`` hierarchy.

Together with ``test_logging_noise_reduction.py`` this proves users can
either lean on the global seeds (already quiet by default) or surgically
silence a sub-package without touching code, both via YAML alone.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest

from kstlib.logging.manager import LogManager
from kstlib.rapi.config import load_rapi_config

_N_ENDPOINTS = 30


class _RecordCollector(logging.Handler):
    """Minimal handler that keeps every record it sees."""

    def __init__(self) -> None:
        super().__init__(level=logging.NOTSET)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Store the record verbatim for later assertion."""
        self.records.append(record)


@pytest.fixture
def kstlib_log_collector() -> Iterator[_RecordCollector]:
    """Capture every ``kstlib.*`` log record at TRACE level.

    Also saves and restores the per-module level on
    ``kstlib.rapi.config`` so the kill-switch override does not leak to
    sibling tests.
    """
    collector = _RecordCollector()
    kstlib_logger = logging.getLogger("kstlib")
    target_logger = logging.getLogger("kstlib.rapi.config")

    saved_kstlib_level = kstlib_logger.level
    saved_kstlib_propagate = kstlib_logger.propagate
    saved_target_level = target_logger.level

    kstlib_logger.setLevel(5)  # TRACE_LEVEL
    kstlib_logger.propagate = False
    kstlib_logger.addHandler(collector)
    try:
        yield collector
    finally:
        kstlib_logger.removeHandler(collector)
        kstlib_logger.setLevel(saved_kstlib_level)
        kstlib_logger.propagate = saved_kstlib_propagate
        target_logger.setLevel(saved_target_level)


def _build_synthetic_config_with_kill_switch(n_endpoints: int) -> dict[str, Any]:
    """Build a synthetic config that pins ``kstlib.rapi.config`` at WARNING."""
    endpoints: dict[str, dict[str, Any]] = {
        f"ep_{i:02d}": {"path": f"/synthetic/{i}", "method": "GET"} for i in range(n_endpoints)
    }
    return {
        "kstlib": {
            "logging": {
                "modules": {"kstlib.rapi.config": "WARNING"},
            }
        },
        "rapi": {
            "api": {
                "synthetic": {
                    "base_url": "https://synthetic.example.com",
                    "endpoints": endpoints,
                }
            }
        },
    }


def test_modules_yaml_kill_switch_silences_rapi_config(
    kstlib_log_collector: _RecordCollector,
) -> None:
    """``modules: {kstlib.rapi.config: WARNING}`` zeroes the load chatter.

    Two assertions: (1) the YAML cascade resolves to the expected mapping
    and applies it via ``setLevel`` ; (2) ``load_rapi_config()`` then
    emits no DEBUG/INFO/TRACE record on the ``kstlib.rapi.config``
    logger. Sibling kstlib loggers retain TRACE so the test stays
    sensitive to leaks if a future seed accidentally bypasses the
    per-module level.
    """
    cfg = _build_synthetic_config_with_kill_switch(_N_ENDPOINTS)

    # Step 1 : exercise the YAML cascade end-to-end
    with patch("kstlib.logging.manager.get_config", return_value=cfg):
        resolved = LogManager._resolve_module_levels(None, None)
    assert resolved == {"kstlib.rapi.config": "WARNING"}

    mgr = LogManager(name="kstlib_smoke_kill_switch", preset=None, register=False)
    mgr._module_levels = resolved
    mgr._apply_module_levels()
    assert logging.getLogger("kstlib.rapi.config").level == logging.WARNING

    # Step 2 : noise on kstlib.rapi.config must be silenced under load
    with patch("kstlib.config.get_config", return_value=cfg):
        manager = load_rapi_config()

    # Sanity : the load itself completed correctly
    assert set(manager.apis) == {"synthetic"}
    assert len(manager.apis["synthetic"].endpoints) == _N_ENDPOINTS

    rapi_config_records = [r for r in kstlib_log_collector.records if r.name == "kstlib.rapi.config"]
    leaked_below_warning = [r for r in rapi_config_records if r.levelno < logging.WARNING]
    assert not leaked_below_warning, (
        f"Kill-switch failure: {len(leaked_below_warning)} sub-WARNING record(s) "
        f"escaped from kstlib.rapi.config despite WARNING setLevel. "
        f"First leak: {leaked_below_warning[0].levelname} "
        f"{leaked_below_warning[0].getMessage()!r}"
    )
