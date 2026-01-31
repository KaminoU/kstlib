"""Shared fixtures for monitoring tests."""

from __future__ import annotations

import pytest

from kstlib.monitoring.cell import StatusCell
from kstlib.monitoring.types import StatusLevel


@pytest.fixture()
def ok_cell() -> StatusCell:
    """StatusCell with OK level."""
    return StatusCell("UP", StatusLevel.OK)


@pytest.fixture()
def warning_cell() -> StatusCell:
    """StatusCell with WARNING level."""
    return StatusCell("DEGRADED", StatusLevel.WARNING)


@pytest.fixture()
def error_cell() -> StatusCell:
    """StatusCell with ERROR level."""
    return StatusCell("DOWN", StatusLevel.ERROR)


@pytest.fixture()
def critical_cell() -> StatusCell:
    """StatusCell with CRITICAL level."""
    return StatusCell("FAILURE", StatusLevel.CRITICAL)
