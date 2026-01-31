"""Tests for the monitoring exception hierarchy."""

from __future__ import annotations

import pytest

from kstlib.config.exceptions import KstlibError
from kstlib.monitoring.exceptions import MonitoringError, RenderError


class TestMonitoringError:
    """Tests for MonitoringError."""

    def test_inherits_from_kstlib_error(self) -> None:
        """MonitoringError is a subclass of KstlibError."""
        assert issubclass(MonitoringError, KstlibError)

    def test_catchable_as_kstlib_error(self) -> None:
        """MonitoringError can be caught as KstlibError."""
        with pytest.raises(KstlibError):
            raise MonitoringError("test")

    def test_message_preserved(self) -> None:
        """MonitoringError preserves the error message."""
        err = MonitoringError("something went wrong")
        assert str(err) == "something went wrong"


class TestRenderError:
    """Tests for RenderError."""

    def test_inherits_from_monitoring_error(self) -> None:
        """RenderError is a subclass of MonitoringError."""
        assert issubclass(RenderError, MonitoringError)

    def test_inherits_from_value_error(self) -> None:
        """RenderError is a subclass of ValueError."""
        assert issubclass(RenderError, ValueError)

    def test_catchable_as_value_error(self) -> None:
        """RenderError can be caught as ValueError."""
        with pytest.raises(ValueError):
            raise RenderError("bad render")

    def test_catchable_as_kstlib_error(self) -> None:
        """RenderError can be caught as KstlibError."""
        with pytest.raises(KstlibError):
            raise RenderError("bad render")

    def test_message_preserved(self) -> None:
        """RenderError preserves the error message."""
        err = RenderError("row mismatch")
        assert str(err) == "row mismatch"
