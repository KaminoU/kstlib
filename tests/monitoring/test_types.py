"""Tests for monitoring core types."""

from __future__ import annotations

from kstlib.monitoring.types import CellValue, Renderable, StatusLevel


class TestStatusLevel:
    """Tests for StatusLevel enum."""

    def test_ok_value(self) -> None:
        """StatusLevel.OK has value 10."""
        assert StatusLevel.OK.value == 10

    def test_warning_value(self) -> None:
        """StatusLevel.WARNING has value 20."""
        assert StatusLevel.WARNING.value == 20

    def test_error_value(self) -> None:
        """StatusLevel.ERROR has value 30."""
        assert StatusLevel.ERROR.value == 30

    def test_critical_value(self) -> None:
        """StatusLevel.CRITICAL has value 40."""
        assert StatusLevel.CRITICAL.value == 40

    def test_ordering(self) -> None:
        """Status levels are ordered by severity."""
        assert StatusLevel.OK < StatusLevel.WARNING < StatusLevel.ERROR < StatusLevel.CRITICAL

    def test_all_members(self) -> None:
        """StatusLevel has exactly four members."""
        assert len(StatusLevel) == 4

    def test_is_int(self) -> None:
        """StatusLevel values are integers."""
        assert isinstance(StatusLevel.OK, int)


class TestRenderable:
    """Tests for Renderable protocol."""

    def test_protocol_with_valid_class(self) -> None:
        """Class with render method satisfies Renderable protocol."""

        class Good:
            def render(self, *, inline_css: bool = False) -> str:
                return "<div></div>"

        assert isinstance(Good(), Renderable)

    def test_protocol_rejects_missing_method(self) -> None:
        """Class without render method does not satisfy Renderable."""

        class Bad:
            pass

        assert not isinstance(Bad(), Renderable)


class TestCellValue:
    """Tests for CellValue type alias."""

    def test_alias_exists(self) -> None:
        """CellValue type alias is importable."""
        assert CellValue is not None
