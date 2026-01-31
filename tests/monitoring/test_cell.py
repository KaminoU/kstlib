"""Tests for StatusCell render type."""

from __future__ import annotations

from kstlib.monitoring.cell import StatusCell
from kstlib.monitoring.types import Renderable, StatusLevel


class TestStatusCell:
    """Tests for StatusCell."""

    def test_render_class_mode(self, ok_cell: StatusCell) -> None:
        """Class mode renders a <span> with CSS class."""
        result = ok_cell.render()
        assert result == '<span class="status-ok">UP</span>'

    def test_render_inline_mode(self, ok_cell: StatusCell) -> None:
        """Inline mode renders a <span> with style attribute."""
        result = ok_cell.render(inline_css=True)
        assert "<span style=" in result
        assert "UP</span>" in result
        assert "#16A085" in result

    def test_warning_class(self, warning_cell: StatusCell) -> None:
        """Warning cell uses status-warning class."""
        result = warning_cell.render()
        assert 'class="status-warning"' in result
        assert "DEGRADED" in result

    def test_error_class(self, error_cell: StatusCell) -> None:
        """Error cell uses status-error class."""
        result = error_cell.render()
        assert 'class="status-error"' in result

    def test_critical_class(self, critical_cell: StatusCell) -> None:
        """Critical cell uses status-critical class."""
        result = critical_cell.render()
        assert 'class="status-critical"' in result

    def test_html_escaping(self) -> None:
        """HTML special characters in label are escaped."""
        cell = StatusCell("<script>alert('xss')</script>", StatusLevel.OK)
        result = cell.render()
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_html_escaping_inline(self) -> None:
        """HTML special characters are escaped in inline mode too."""
        cell = StatusCell("a&b", StatusLevel.ERROR)
        result = cell.render(inline_css=True)
        assert "a&amp;b" in result

    def test_frozen(self) -> None:
        """StatusCell is immutable."""
        cell = StatusCell("UP", StatusLevel.OK)
        import pytest

        with pytest.raises(AttributeError):
            cell.label = "DOWN"  # type: ignore[misc]

    def test_satisfies_renderable(self, ok_cell: StatusCell) -> None:
        """StatusCell satisfies the Renderable protocol."""
        assert isinstance(ok_cell, Renderable)

    def test_all_levels_inline(self) -> None:
        """All status levels produce valid inline output."""
        for level in StatusLevel:
            cell = StatusCell("TEST", level)
            result = cell.render(inline_css=True)
            assert "<span" in result
            assert "TEST</span>" in result
