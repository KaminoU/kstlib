"""MonitorKV render type for key-value pair display.

A ``MonitorKV`` renders as an HTML ``<dl>`` definition list with a
two-column grid layout, suitable for status summaries and stat panels.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import TYPE_CHECKING

from kstlib.monitoring.cell import StatusCell

if TYPE_CHECKING:
    from kstlib.monitoring.types import CellValue


@dataclass(frozen=True, slots=True)
class MonitorKV:
    """A key-value grid rendered as an HTML ``<dl>``.

    Values can be plain scalars or ``StatusCell`` objects for colored badges.

    Attributes:
        items: Ordered mapping of keys to values.
        title: Optional heading rendered above the list.

    Examples:
        >>> from kstlib.monitoring.kv import MonitorKV
        >>> kv = MonitorKV({"Host": "srv-01", "Port": 8080})
        >>> "<dl" in kv.render()
        True
    """

    items: dict[str, CellValue | StatusCell]
    title: str = ""

    def render(self, *, inline_css: bool = False) -> str:
        """Render the key-value pairs as an HTML ``<dl>``.

        Args:
            inline_css: If True, use inline styles instead of CSS classes.

        Returns:
            HTML ``<dl>`` string, optionally preceded by an ``<h3>`` title.
        """
        parts: list[str] = []

        if self.title:
            escaped_title = html.escape(self.title)
            parts.append(f"<h3>{escaped_title}</h3>")

        if inline_css:
            style = "display:grid;grid-template-columns:auto 1fr;gap:4px 12px"
            parts.append(f'<dl style="{style}">')
        else:
            parts.append('<dl class="monitor-kv">')

        for key, value in self.items.items():
            escaped_key = html.escape(str(key))
            if inline_css:
                parts.append(f'<dt style="font-weight:bold">{escaped_key}</dt>')
            else:
                parts.append(f"<dt>{escaped_key}</dt>")

            if isinstance(value, StatusCell):
                rendered_value = value.render(inline_css=inline_css)
            else:
                rendered_value = html.escape(str(value))
            parts.append(f"<dd>{rendered_value}</dd>")

        parts.append("</dl>")
        return "".join(parts)


__all__ = [
    "MonitorKV",
]
