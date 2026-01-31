"""Tests for MonitorKV render type."""

from __future__ import annotations

from kstlib.monitoring.cell import StatusCell
from kstlib.monitoring.kv import MonitorKV
from kstlib.monitoring.types import Renderable


class TestMonitorKV:
    """Tests for MonitorKV."""

    def test_render_class_mode(self) -> None:
        """Class mode renders a <dl> with CSS class."""
        kv = MonitorKV({"Host": "srv-01", "Port": 8080})
        result = kv.render()
        assert '<dl class="monitor-kv">' in result
        assert "<dt>Host</dt>" in result
        assert "<dd>srv-01</dd>" in result
        assert "<dd>8080</dd>" in result

    def test_render_with_title(self) -> None:
        """Title is rendered as an <h3>."""
        kv = MonitorKV({"Key": "val"}, title="Server Info")
        result = kv.render()
        assert "<h3>Server Info</h3>" in result

    def test_render_without_title(self) -> None:
        """No <h3> when title is empty."""
        kv = MonitorKV({"Key": "val"})
        result = kv.render()
        assert "<h3>" not in result

    def test_render_inline_mode(self) -> None:
        """Inline mode uses style attributes on <dl>."""
        kv = MonitorKV({"Host": "srv-01"})
        result = kv.render(inline_css=True)
        assert '<dl style="' in result
        assert "display:grid" in result

    def test_inline_dt_has_bold(self) -> None:
        """Inline mode renders bold <dt> elements."""
        kv = MonitorKV({"Key": "val"})
        result = kv.render(inline_css=True)
        assert 'style="font-weight:bold"' in result

    def test_status_cell_value(self, ok_cell: StatusCell) -> None:
        """StatusCell values are rendered as badges."""
        kv = MonitorKV({"Status": ok_cell})
        result = kv.render()
        assert 'class="status-ok"' in result
        assert "UP" in result

    def test_status_cell_inline(self, ok_cell: StatusCell) -> None:
        """StatusCell values use inline styles in inline mode."""
        kv = MonitorKV({"Status": ok_cell})
        result = kv.render(inline_css=True)
        assert "#16A085" in result

    def test_html_escaping_key(self) -> None:
        """HTML in keys is escaped."""
        kv = MonitorKV({"<b>Key</b>": "val"})
        result = kv.render()
        assert "&lt;b&gt;" in result

    def test_html_escaping_value(self) -> None:
        """HTML in string values is escaped."""
        kv = MonitorKV({"Key": "<script>"})
        result = kv.render()
        assert "&lt;script&gt;" in result

    def test_frozen(self) -> None:
        """MonitorKV is immutable."""
        kv = MonitorKV({"a": "b"})
        import pytest

        with pytest.raises(AttributeError):
            kv.title = "new"  # type: ignore[misc]

    def test_satisfies_renderable(self) -> None:
        """MonitorKV satisfies the Renderable protocol."""
        assert isinstance(MonitorKV({}), Renderable)

    def test_multiple_items_order(self) -> None:
        """Items are rendered in insertion order."""
        kv = MonitorKV({"A": 1, "B": 2, "C": 3})
        result = kv.render()
        a_pos = result.index("<dt>A</dt>")
        b_pos = result.index("<dt>B</dt>")
        c_pos = result.index("<dt>C</dt>")
        assert a_pos < b_pos < c_pos

    def test_html_escaping_title(self) -> None:
        """HTML in title is escaped."""
        kv = MonitorKV({"a": "b"}, title="<h1>XSS</h1>")
        result = kv.render()
        assert "&lt;h1&gt;" in result

    def test_numeric_values(self) -> None:
        """Numeric values are converted to strings."""
        kv = MonitorKV({"Int": 42, "Float": 3.14, "Bool": True})
        result = kv.render()
        assert "<dd>42</dd>" in result
        assert "<dd>3.14</dd>" in result
        assert "<dd>True</dd>" in result
