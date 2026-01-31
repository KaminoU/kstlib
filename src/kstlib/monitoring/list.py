"""MonitorList render type for ordered and unordered lists.

A ``MonitorList`` renders as an HTML ``<ul>`` or ``<ol>`` element,
suitable for event logs, alert lists, and step-by-step status reports.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import TYPE_CHECKING

from kstlib.monitoring.cell import StatusCell

if TYPE_CHECKING:
    from kstlib.monitoring.types import CellValue


@dataclass(frozen=True, slots=True)
class MonitorList:
    """A list rendered as an HTML ``<ul>`` or ``<ol>``.

    Items can be plain scalars or ``StatusCell`` objects for colored badges.

    Attributes:
        items: Sequence of list items.
        ordered: If True, render as ``<ol>``; otherwise ``<ul>``.
        title: Optional heading rendered above the list.

    Examples:
        >>> from kstlib.monitoring.list import MonitorList
        >>> ml = MonitorList(["Event A", "Event B"])
        >>> "<ul>" in ml.render()
        True
    """

    items: list[CellValue | StatusCell]
    ordered: bool = False
    title: str = ""

    def render(self, *, inline_css: bool = False) -> str:
        """Render the list as an HTML ``<ul>`` or ``<ol>``.

        Args:
            inline_css: If True, use inline styles instead of CSS classes.

        Returns:
            HTML list string, optionally preceded by an ``<h3>`` title.
        """
        parts: list[str] = []

        if self.title:
            escaped_title = html.escape(self.title)
            parts.append(f"<h3>{escaped_title}</h3>")

        tag = "ol" if self.ordered else "ul"
        parts.append(f"<{tag}>")

        for item in self.items:
            rendered = item.render(inline_css=inline_css) if isinstance(item, StatusCell) else html.escape(str(item))
            parts.append(f"<li>{rendered}</li>")

        parts.append(f"</{tag}>")
        return "".join(parts)


__all__ = [
    "MonitorList",
]
