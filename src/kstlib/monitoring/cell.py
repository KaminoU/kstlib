"""StatusCell render type for colored status badges.

A ``StatusCell`` renders as a ``<span>`` badge with color coding based on
the severity level (OK, WARNING, ERROR, CRITICAL).
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import TYPE_CHECKING

from kstlib.monitoring._styles import STATUS_CSS_CLASSES, inline_badge_style

if TYPE_CHECKING:
    from kstlib.monitoring.types import StatusLevel


@dataclass(frozen=True, slots=True)
class StatusCell:
    """A colored status badge rendered as an HTML ``<span>``.

    Attributes:
        label: Display text for the badge (e.g. "UP", "DOWN", "DEGRADED").
        level: Severity level controlling badge color.

    Examples:
        >>> from kstlib.monitoring.cell import StatusCell
        >>> from kstlib.monitoring.types import StatusLevel
        >>> cell = StatusCell("UP", StatusLevel.OK)
        >>> "<span" in cell.render()
        True
    """

    label: str
    level: StatusLevel

    def render(self, *, inline_css: bool = False) -> str:
        """Render the status badge as an HTML ``<span>``.

        Args:
            inline_css: If True, use inline styles instead of CSS classes.

        Returns:
            HTML ``<span>`` string.
        """
        escaped = html.escape(self.label)
        if inline_css:
            style = inline_badge_style(self.level)
            return f'<span style="{style}">{escaped}</span>'
        cls = STATUS_CSS_CLASSES[self.level]
        return f'<span class="{cls}">{escaped}</span>'


__all__ = [
    "StatusCell",
]
