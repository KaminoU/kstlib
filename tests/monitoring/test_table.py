"""Tests for MonitorTable render type."""

from __future__ import annotations

import pytest

from kstlib.monitoring.cell import StatusCell
from kstlib.monitoring.exceptions import RenderError
from kstlib.monitoring.table import MonitorTable
from kstlib.monitoring.types import Renderable


class TestMonitorTable:
    """Tests for MonitorTable."""

    def test_render_class_mode(self) -> None:
        """Class mode renders a <table> with CSS class."""
        t = MonitorTable(headers=["Service", "Status"])
        t.add_row(["API", "OK"])
        result = t.render()
        assert '<table class="monitor-table">' in result
        assert "<th>Service</th>" in result
        assert "<th>Status</th>" in result
        assert "<td>API</td>" in result
        assert "<td>OK</td>" in result

    def test_render_with_title(self) -> None:
        """Title is rendered as an <h3>."""
        t = MonitorTable(headers=["A"], title="Services")
        result = t.render()
        assert "<h3>Services</h3>" in result

    def test_render_without_title(self) -> None:
        """No <h3> when title is empty."""
        t = MonitorTable(headers=["A"])
        result = t.render()
        assert "<h3>" not in result

    def test_render_inline_mode(self) -> None:
        """Inline mode uses style attributes."""
        t = MonitorTable(headers=["Name"])
        t.add_row(["Test"])
        result = t.render(inline_css=True)
        assert '<table style="' in result
        assert "border-collapse" in result

    def test_inline_header_styling(self) -> None:
        """Inline mode applies header background and color."""
        t = MonitorTable(headers=["Col"])
        result = t.render(inline_css=True)
        assert "#2c3e50" in result  # header bg
        assert "#ffffff" in result  # header text

    def test_inline_stripe_rows(self) -> None:
        """Inline mode stripes even-index rows."""
        t = MonitorTable(headers=["V"])
        t.add_row(["a"])
        t.add_row(["b"])
        t.add_row(["c"])
        result = t.render(inline_css=True)
        assert "#f0f0f0" in result  # stripe bg

    def test_add_row_wrong_length(self) -> None:
        """Adding a row with wrong length raises RenderError."""
        t = MonitorTable(headers=["A", "B"])
        with pytest.raises(RenderError, match="2 headers"):
            t.add_row(["only-one"])

    def test_add_row_too_many(self) -> None:
        """Adding a row with too many cells raises RenderError."""
        t = MonitorTable(headers=["A"])
        with pytest.raises(RenderError):
            t.add_row(["one", "two"])

    def test_row_count(self) -> None:
        """row_count reflects number of added rows."""
        t = MonitorTable(headers=["A"])
        assert t.row_count == 0
        t.add_row(["1"])
        assert t.row_count == 1
        t.add_row(["2"])
        assert t.row_count == 2

    def test_status_cell_in_row(self, ok_cell: StatusCell) -> None:
        """StatusCell values in rows are rendered as badges."""
        t = MonitorTable(headers=["Service", "Status"])
        t.add_row(["API", ok_cell])
        result = t.render()
        assert 'class="status-ok"' in result
        assert "UP" in result

    def test_status_cell_inline(self, ok_cell: StatusCell) -> None:
        """StatusCell values use inline styles in inline mode."""
        t = MonitorTable(headers=["S"])
        t.add_row([ok_cell])
        result = t.render(inline_css=True)
        assert "#16A085" in result

    def test_html_escaping_header(self) -> None:
        """HTML in headers is escaped."""
        t = MonitorTable(headers=["<b>H</b>"])
        result = t.render()
        assert "&lt;b&gt;" in result

    def test_html_escaping_cell(self) -> None:
        """HTML in cell values is escaped."""
        t = MonitorTable(headers=["V"])
        t.add_row(["<script>"])
        result = t.render()
        assert "&lt;script&gt;" in result

    def test_html_escaping_title(self) -> None:
        """HTML in title is escaped."""
        t = MonitorTable(headers=["A"], title="<img src=x>")
        result = t.render()
        assert "&lt;img" in result

    def test_empty_table(self) -> None:
        """Table with no rows renders valid HTML."""
        t = MonitorTable(headers=["A", "B"])
        result = t.render()
        assert "<thead>" in result
        assert "<tbody></tbody>" in result

    def test_mutable(self) -> None:
        """MonitorTable is mutable (not frozen)."""
        t = MonitorTable(headers=["A"])
        t.title = "New Title"
        assert t.title == "New Title"

    def test_satisfies_renderable(self) -> None:
        """MonitorTable satisfies the Renderable protocol."""
        assert isinstance(MonitorTable(headers=["A"]), Renderable)

    def test_multiple_rows_structure(self) -> None:
        """Multiple rows produce correct <tr> structure."""
        t = MonitorTable(headers=["N"])
        t.add_row(["1"])
        t.add_row(["2"])
        result = t.render()
        assert result.count("<tr>") == 3  # 1 header + 2 data
        assert result.count("</tr>") == 3

    def test_inline_td_styling(self) -> None:
        """Inline mode applies border-bottom to td."""
        t = MonitorTable(headers=["A"])
        t.add_row(["v"])
        result = t.render(inline_css=True)
        assert "border-bottom" in result

    def test_numeric_cells(self) -> None:
        """Numeric cell values are converted to strings."""
        t = MonitorTable(headers=["Int", "Float"])
        t.add_row([42, 3.14])
        result = t.render()
        assert "<td>42</td>" in result
        assert "<td>3.14</td>" in result

    def test_html_escaping_header_inline(self) -> None:
        """HTML in headers is escaped in inline mode."""
        t = MonitorTable(headers=["<b>H</b>"])
        result = t.render(inline_css=True)
        assert "&lt;b&gt;" in result
