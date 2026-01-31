"""Tests for monitoring CSS styles and helpers."""

from __future__ import annotations

from kstlib.monitoring._styles import (
    STATUS_COLORS,
    STATUS_CSS_CLASSES,
    STATUS_TEXT_COLORS,
    get_css_classes,
    inline_badge_style,
)
from kstlib.monitoring.types import StatusLevel


class TestColorMappings:
    """Tests for color constant dictionaries."""

    def test_status_colors_has_all_levels(self) -> None:
        """STATUS_COLORS covers every StatusLevel."""
        for level in StatusLevel:
            assert level in STATUS_COLORS

    def test_status_text_colors_has_all_levels(self) -> None:
        """STATUS_TEXT_COLORS covers every StatusLevel."""
        for level in StatusLevel:
            assert level in STATUS_TEXT_COLORS

    def test_status_css_classes_has_all_levels(self) -> None:
        """STATUS_CSS_CLASSES covers every StatusLevel."""
        for level in StatusLevel:
            assert level in STATUS_CSS_CLASSES

    def test_ok_color(self) -> None:
        """OK level uses green."""
        assert STATUS_COLORS[StatusLevel.OK] == "#16A085"

    def test_warning_color(self) -> None:
        """WARNING level uses yellow."""
        assert STATUS_COLORS[StatusLevel.WARNING] == "#F1C40F"

    def test_error_color(self) -> None:
        """ERROR level uses red."""
        assert STATUS_COLORS[StatusLevel.ERROR] == "#E85A4F"

    def test_critical_color(self) -> None:
        """CRITICAL level uses dark red."""
        assert STATUS_COLORS[StatusLevel.CRITICAL] == "#c0392b"

    def test_css_class_names(self) -> None:
        """CSS class names follow status-<level> pattern."""
        assert STATUS_CSS_CLASSES[StatusLevel.OK] == "status-ok"
        assert STATUS_CSS_CLASSES[StatusLevel.WARNING] == "status-warning"
        assert STATUS_CSS_CLASSES[StatusLevel.ERROR] == "status-error"
        assert STATUS_CSS_CLASSES[StatusLevel.CRITICAL] == "status-critical"


class TestInlineBadgeStyle:
    """Tests for inline_badge_style helper."""

    def test_contains_background(self) -> None:
        """Inline style includes background color."""
        style = inline_badge_style(StatusLevel.OK)
        assert "background:#16A085" in style

    def test_contains_text_color(self) -> None:
        """Inline style includes text color."""
        style = inline_badge_style(StatusLevel.OK)
        assert "color:#ffffff" in style

    def test_contains_padding(self) -> None:
        """Inline style includes padding."""
        style = inline_badge_style(StatusLevel.ERROR)
        assert "padding:" in style

    def test_all_levels_produce_output(self) -> None:
        """All status levels produce non-empty style strings."""
        for level in StatusLevel:
            assert len(inline_badge_style(level)) > 0


class TestGetCssClasses:
    """Tests for get_css_classes helper."""

    def test_returns_style_tag(self) -> None:
        """Output is wrapped in <style> tags."""
        css = get_css_classes()
        assert css.startswith("<style>")
        assert css.endswith("</style>")

    def test_contains_all_status_classes(self) -> None:
        """Output includes CSS rules for all status levels."""
        css = get_css_classes()
        for cls in STATUS_CSS_CLASSES.values():
            assert f".{cls}" in css

    def test_contains_table_class(self) -> None:
        """Output includes monitor-table CSS rules."""
        css = get_css_classes()
        assert ".monitor-table" in css

    def test_contains_kv_class(self) -> None:
        """Output includes monitor-kv CSS rules."""
        css = get_css_classes()
        assert ".monitor-kv" in css

    def test_contains_metric_class(self) -> None:
        """Output includes monitor-metric CSS rules."""
        css = get_css_classes()
        assert ".monitor-metric" in css
