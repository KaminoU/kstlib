"""Tests for MonitorList render type."""

from __future__ import annotations

from kstlib.monitoring.cell import StatusCell
from kstlib.monitoring.list import MonitorList
from kstlib.monitoring.types import Renderable


class TestMonitorList:
    """Tests for MonitorList."""

    def test_render_unordered(self) -> None:
        """Default renders as <ul>."""
        ml = MonitorList(["Item A", "Item B"])
        result = ml.render()
        assert "<ul>" in result
        assert "</ul>" in result
        assert "<li>Item A</li>" in result
        assert "<li>Item B</li>" in result

    def test_render_ordered(self) -> None:
        """Ordered list renders as <ol>."""
        ml = MonitorList(["Step 1", "Step 2"], ordered=True)
        result = ml.render()
        assert "<ol>" in result
        assert "</ol>" in result

    def test_render_with_title(self) -> None:
        """Title is rendered as an <h3>."""
        ml = MonitorList(["A"], title="Events")
        result = ml.render()
        assert "<h3>Events</h3>" in result

    def test_render_without_title(self) -> None:
        """No <h3> when title is empty."""
        ml = MonitorList(["A"])
        result = ml.render()
        assert "<h3>" not in result

    def test_status_cell_items(self, ok_cell: StatusCell) -> None:
        """StatusCell items are rendered as badges."""
        ml = MonitorList([ok_cell, "plain"])
        result = ml.render()
        assert 'class="status-ok"' in result
        assert "<li>plain</li>" in result

    def test_status_cell_inline(self, ok_cell: StatusCell) -> None:
        """StatusCell items use inline styles in inline mode."""
        ml = MonitorList([ok_cell])
        result = ml.render(inline_css=True)
        assert "#16A085" in result

    def test_html_escaping(self) -> None:
        """HTML in items is escaped."""
        ml = MonitorList(["<script>alert('xss')</script>"])
        result = ml.render()
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_html_escaping_title(self) -> None:
        """HTML in title is escaped."""
        ml = MonitorList(["a"], title="<b>XSS</b>")
        result = ml.render()
        assert "&lt;b&gt;" in result

    def test_frozen(self) -> None:
        """MonitorList is immutable."""
        ml = MonitorList(["a"])
        import pytest

        with pytest.raises(AttributeError):
            ml.ordered = True  # type: ignore[misc]

    def test_satisfies_renderable(self) -> None:
        """MonitorList satisfies the Renderable protocol."""
        assert isinstance(MonitorList([]), Renderable)

    def test_empty_list(self) -> None:
        """Empty list renders valid HTML."""
        ml = MonitorList([])
        result = ml.render()
        assert result == "<ul></ul>"

    def test_numeric_items(self) -> None:
        """Numeric items are converted to strings."""
        ml = MonitorList([1, 2.5, True])
        result = ml.render()
        assert "<li>1</li>" in result
        assert "<li>2.5</li>" in result
        assert "<li>True</li>" in result

    def test_inline_mode_no_classes(self) -> None:
        """Inline mode does not add CSS classes to list elements."""
        ml = MonitorList(["A", "B"])
        result = ml.render(inline_css=True)
        # Standard ul/ol, no class needed on the list itself
        assert "<ul>" in result
