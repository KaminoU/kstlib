"""Centralized colors and CSS helpers for monitoring HTML rendering.

All colors, CSS class names, and inline style strings are defined here
to ensure visual consistency across all render types.
"""

from __future__ import annotations

from kstlib.monitoring.types import StatusLevel

# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------

#: Mapping of status levels to their hex color codes.
STATUS_COLORS: dict[StatusLevel, str] = {
    StatusLevel.OK: "#16A085",
    StatusLevel.WARNING: "#F1C40F",
    StatusLevel.ERROR: "#E85A4F",
    StatusLevel.CRITICAL: "#c0392b",
}

#: Mapping of status levels to their text color (for contrast).
STATUS_TEXT_COLORS: dict[StatusLevel, str] = {
    StatusLevel.OK: "#ffffff",
    StatusLevel.WARNING: "#2c3e50",
    StatusLevel.ERROR: "#ffffff",
    StatusLevel.CRITICAL: "#ffffff",
}

# ---------------------------------------------------------------------------
# CSS class names
# ---------------------------------------------------------------------------

#: Mapping of status levels to their CSS class names.
STATUS_CSS_CLASSES: dict[StatusLevel, str] = {
    StatusLevel.OK: "status-ok",
    StatusLevel.WARNING: "status-warning",
    StatusLevel.ERROR: "status-error",
    StatusLevel.CRITICAL: "status-critical",
}

# ---------------------------------------------------------------------------
# Table styling constants
# ---------------------------------------------------------------------------

TABLE_BORDER_COLOR = "#ddd"
TABLE_HEADER_BG = "#2c3e50"
TABLE_HEADER_TEXT = "#ffffff"
TABLE_ROW_BG = "#ffffff"
TABLE_ROW_TEXT = "#2c3e50"
TABLE_STRIPE_BG = "#f0f0f0"
TABLE_FONT_FAMILY = "Consolas, Monaco, 'Courier New', monospace"

# ---------------------------------------------------------------------------
# Metric styling constants
# ---------------------------------------------------------------------------

METRIC_FONT_SIZE = "2.5em"
METRIC_LABEL_COLOR = "#7f8c8d"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def inline_badge_style(level: StatusLevel) -> str:
    """Return an inline CSS style string for a status badge.

    Args:
        level: The status severity level.

    Returns:
        CSS style string suitable for a ``style`` attribute.

    Examples:
        >>> from kstlib.monitoring._styles import inline_badge_style
        >>> from kstlib.monitoring.types import StatusLevel
        >>> "background" in inline_badge_style(StatusLevel.OK)
        True
    """
    bg = STATUS_COLORS[level]
    fg = STATUS_TEXT_COLORS[level]
    return f"background:{bg};color:{fg};padding:2px 8px;border-radius:4px;font-weight:bold;font-size:0.85em"


def get_css_classes() -> str:
    """Return a ``<style>`` block with all monitoring CSS classes.

    This should be included once in the ``<head>`` of an HTML document
    when using class-based rendering (``inline_css=False``).

    Returns:
        Complete ``<style>`` element as a string.

    Examples:
        >>> from kstlib.monitoring._styles import get_css_classes
        >>> css = get_css_classes()
        >>> "<style>" in css
        True
        >>> ".status-ok" in css
        True
    """
    rules: list[str] = []

    # Status badge classes
    for level in StatusLevel:
        cls = STATUS_CSS_CLASSES[level]
        bg = STATUS_COLORS[level]
        fg = STATUS_TEXT_COLORS[level]
        rules.append(
            f".{cls} {{"
            f" background:{bg}; color:{fg};"
            f" padding:2px 8px; border-radius:4px;"
            f" font-weight:bold; font-size:0.85em;"
            f" }}"
        )

    # Monitor table
    rules.append(
        f".monitor-table {{"
        f" border-collapse:collapse; width:100%; font-family:{TABLE_FONT_FAMILY};"
        f" background:{TABLE_ROW_BG}; color:{TABLE_ROW_TEXT};"
        f" }}"
    )
    rules.append(
        f".monitor-table th {{"
        f" background:{TABLE_HEADER_BG}; color:{TABLE_HEADER_TEXT};"
        f" padding:8px 12px; text-align:left;"
        f" }}"
    )
    rules.append(f".monitor-table td {{ padding:8px 12px; border-bottom:1px solid {TABLE_BORDER_COLOR}; }}")
    rules.append(f".monitor-table tr:nth-child(even) {{ background:{TABLE_STRIPE_BG}; }}")

    # Monitor KV
    rules.append(".monitor-kv { display:grid; grid-template-columns:auto 1fr; gap:4px 12px; }")
    rules.append(".monitor-kv dt { font-weight:bold; }")

    # Monitor metric
    rules.append(".monitor-metric { text-align:center; padding:12px; }")
    rules.append(f".monitor-metric .metric-value {{ font-size:{METRIC_FONT_SIZE}; font-weight:bold; }}")
    rules.append(f".monitor-metric .metric-label {{ color:{METRIC_LABEL_COLOR}; font-size:0.9em; }}")

    body = "\n".join(rules)
    return f"<style>\n{body}\n</style>"


__all__ = [
    "METRIC_FONT_SIZE",
    "METRIC_LABEL_COLOR",
    "STATUS_COLORS",
    "STATUS_CSS_CLASSES",
    "STATUS_TEXT_COLORS",
    "TABLE_BORDER_COLOR",
    "TABLE_FONT_FAMILY",
    "TABLE_HEADER_BG",
    "TABLE_HEADER_TEXT",
    "TABLE_ROW_BG",
    "TABLE_ROW_TEXT",
    "TABLE_STRIPE_BG",
    "get_css_classes",
    "inline_badge_style",
]
