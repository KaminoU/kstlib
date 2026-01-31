"""Shared fixtures for resilience tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


class TimeStub:
    """Controllable time source for deterministic tests.

    Allows tests to control the passage of time without actual delays.
    """

    def __init__(self) -> None:
        """Initialize with time at 0."""
        self.current: float = 0.0

    def time(self) -> float:
        """Return the current stubbed time."""
        return self.current

    def sleep(self, seconds: float) -> None:
        """Advance time by the given seconds (no actual sleep)."""
        self.current += seconds

    def monotonic(self) -> float:
        """Return current time (alias for time())."""
        return self.current


@pytest.fixture
def time_stub(monkeypatch: pytest.MonkeyPatch) -> TimeStub:
    """Provide a controllable time stub.

    Patches time.time, time.sleep, and time.monotonic.
    """
    stub = TimeStub()
    monkeypatch.setattr("time.time", stub.time)
    monkeypatch.setattr("time.sleep", stub.sleep)
    monkeypatch.setattr("time.monotonic", stub.monotonic)
    return stub


@pytest.fixture
def heartbeat_file(tmp_path: Path) -> Path:
    """Provide a temporary path for heartbeat state file."""
    return tmp_path / "heartbeat.json"
