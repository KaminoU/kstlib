"""Tests for MonitorMetric render type."""

from __future__ import annotations

from kstlib.monitoring.metric import MonitorMetric
from kstlib.monitoring.types import Renderable, StatusLevel


class TestMonitorMetric:
    """Tests for MonitorMetric."""

    def test_render_class_mode(self) -> None:
        """Class mode renders a div with CSS classes."""
        m = MonitorMetric(42)
        result = m.render()
        assert '<div class="monitor-metric">' in result
        assert '<div class="metric-value">42</div>' in result

    def test_render_with_label(self) -> None:
        """Label is rendered as a metric-label div."""
        m = MonitorMetric(99.9, label="Uptime")
        result = m.render()
        assert '<div class="metric-label">Uptime</div>' in result

    def test_render_without_label(self) -> None:
        """No label div when label is empty."""
        m = MonitorMetric(100)
        result = m.render()
        assert "metric-label" not in result

    def test_render_with_unit(self) -> None:
        """Unit is appended to the value."""
        m = MonitorMetric(99.9, unit="%")
        result = m.render()
        assert "99.9%" in result

    def test_render_inline_mode(self) -> None:
        """Inline mode uses style attributes."""
        m = MonitorMetric(42, label="Count", level=StatusLevel.WARNING)
        result = m.render(inline_css=True)
        assert 'style="' in result
        assert "42" in result
        assert "Count" in result
        assert "#F1C40F" in result

    def test_render_inline_without_label(self) -> None:
        """Inline mode without label omits the label div."""
        m = MonitorMetric(10)
        result = m.render(inline_css=True)
        assert "10" in result
        # Should not have label-specific styling
        assert "0.9em" not in result

    def test_render_inline_with_unit(self) -> None:
        """Inline mode includes unit in display."""
        m = MonitorMetric(50, unit="ms")
        result = m.render(inline_css=True)
        assert "50ms" in result

    def test_html_escaping_value(self) -> None:
        """HTML in value is escaped."""
        m = MonitorMetric("<b>bold</b>")
        result = m.render()
        assert "&lt;b&gt;" in result

    def test_html_escaping_label(self) -> None:
        """HTML in label is escaped."""
        m = MonitorMetric(1, label="<em>test</em>")
        result = m.render()
        assert "&lt;em&gt;" in result

    def test_html_escaping_unit(self) -> None:
        """HTML in unit is escaped."""
        m = MonitorMetric(1, unit="<x>")
        result = m.render()
        assert "&lt;x&gt;" in result

    def test_html_escaping_label_inline(self) -> None:
        """HTML in label is escaped in inline mode."""
        m = MonitorMetric(1, label="<script>")
        result = m.render(inline_css=True)
        assert "&lt;script&gt;" in result

    def test_frozen(self) -> None:
        """MonitorMetric is immutable."""
        m = MonitorMetric(42)
        import pytest

        with pytest.raises(AttributeError):
            m.value = 99  # type: ignore[misc]

    def test_satisfies_renderable(self) -> None:
        """MonitorMetric satisfies the Renderable protocol."""
        assert isinstance(MonitorMetric(1), Renderable)

    def test_bool_value(self) -> None:
        """Boolean values are rendered as strings."""
        m = MonitorMetric(True)
        result = m.render()
        assert "True" in result

    def test_default_level_is_ok(self) -> None:
        """Default level is OK."""
        m = MonitorMetric(1)
        assert m.level is StatusLevel.OK
