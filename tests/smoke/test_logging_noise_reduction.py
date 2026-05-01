"""Smoke regression : RAPI config-load output stays bounded at TRACE.

Earlier versions of ``load_rapi_config()`` could emit on the order of
6000 log records on a moderately-sized config (one DEBUG per endpoint,
per header expansion, per default merge step). The current contract
puts the heavy diagnostic stream on TRACE behind
``kstlib.rapi.config`` and ends the load with a single user-facing
INFO synthesis. This smoke asserts the contract still holds: a
synthetic 30-endpoint load stays well below 200 records even when the
entire ``kstlib`` hierarchy is captured at TRACE.

If the budget tips over, the most likely cause is a regression on the
``kstlib.rapi.config`` logger that promoted per-endpoint trace lines
back to DEBUG/INFO.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest

from kstlib.rapi.config import load_rapi_config

# 30 endpoints + a handful of structural DEBUG/INFO comfortably fit in
# this budget; the pre-seed baseline was ~6000 records for the same load.
_NOISE_BUDGET = 200
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

    Saves and restores the kstlib root logger's level / propagate flag so
    other tests resume on a clean slate.
    """
    collector = _RecordCollector()
    kstlib_logger = logging.getLogger("kstlib")
    saved_level = kstlib_logger.level
    saved_propagate = kstlib_logger.propagate
    kstlib_logger.setLevel(5)  # TRACE_LEVEL
    kstlib_logger.propagate = False
    kstlib_logger.addHandler(collector)
    try:
        yield collector
    finally:
        kstlib_logger.removeHandler(collector)
        kstlib_logger.setLevel(saved_level)
        kstlib_logger.propagate = saved_propagate


def _build_synthetic_rapi_config(n_endpoints: int) -> dict[str, Any]:
    """Build a synthetic kstlib config exposing N endpoints under one API."""
    endpoints: dict[str, dict[str, Any]] = {
        f"ep_{i:02d}": {"path": f"/synthetic/{i}", "method": "GET"} for i in range(n_endpoints)
    }
    return {
        "rapi": {
            "api": {
                "synthetic": {
                    "base_url": "https://synthetic.example.com",
                    "endpoints": endpoints,
                }
            }
        }
    }


def test_load_rapi_config_stays_under_noise_budget(
    kstlib_log_collector: _RecordCollector,
) -> None:
    """A synthetic 30-endpoint load stays well under the noise budget at TRACE."""
    cfg = _build_synthetic_rapi_config(_N_ENDPOINTS)

    with patch("kstlib.config.get_config", return_value=cfg):
        manager = load_rapi_config()

    # Sanity: the load actually succeeded with the expected shape
    assert set(manager.apis) == {"synthetic"}
    assert len(manager.apis["synthetic"].endpoints) == _N_ENDPOINTS

    n_records = len(kstlib_log_collector.records)
    assert n_records < _NOISE_BUDGET, (
        f"Logging noise regression: {n_records} records emitted during a "
        f"{_N_ENDPOINTS}-endpoint load (budget: {_NOISE_BUDGET}). The "
        "per-endpoint trace lines on kstlib.rapi.config likely regressed "
        "to DEBUG or INFO; they should stay at TRACE."
    )
