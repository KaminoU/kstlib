"""MonitorTable render type for tabular status displays.

A ``MonitorTable`` renders as an HTML ``<table>`` with striped rows,
styled headers, and support for ``StatusCell`` values within cells.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from kstlib.monitoring._styles import (
    TABLE_BORDER_COLOR,
    TABLE_FONT_FAMILY,
    TABLE_HEADER_BG,
    TABLE_HEADER_TEXT,
    TABLE_ROW_BG,
    TABLE_ROW_TEXT,
    TABLE_STRIPE_BG,
)
from kstlib.monitoring.cell import StatusCell
from kstlib.monitoring.exceptions import RenderError

if TYPE_CHECKING:
    from kstlib.monitoring.types import CellValue


@dataclass(slots=True)
class MonitorTable:
    """A table rendered as an HTML ``<table>`` with striped rows.

    This is the only mutable render type: rows are added via :meth:`add_row`.

    Attributes:
        headers: Column headers.
        title: Optional caption rendered above the table.

    Examples:
        >>> from kstlib.monitoring.table import MonitorTable
        >>> t = MonitorTable(headers=["Service", "Status"])
        >>> t.add_row(["API", "OK"])
        >>> "<table" in t.render()
        True
    """

    headers: list[str]
    title: str = ""
    _rows: list[list[CellValue | StatusCell]] = field(default_factory=list, init=False, repr=False)

    def add_row(self, row: list[CellValue | StatusCell]) -> None:
        """Append a row to the table.

        Args:
            row: List of cell values matching the number of headers.

        Raises:
            RenderError: If the row length does not match the header count.
        """
        if len(row) != len(self.headers):
            msg = f"Row has {len(row)} cells but table has {len(self.headers)} headers"
            raise RenderError(msg)
        self._rows.append(row)

    @property
    def row_count(self) -> int:
        """Return the number of data rows."""
        return len(self._rows)

    def _render_cell(self, cell: CellValue | StatusCell, *, inline_css: bool) -> str:
        """Render a single cell value as an HTML ``<td>`` element."""
        rendered = cell.render(inline_css=inline_css) if isinstance(cell, StatusCell) else html.escape(str(cell))
        if inline_css:
            td_style = f"padding:8px 12px;border-bottom:1px solid {TABLE_BORDER_COLOR}"
            return f'<td style="{td_style}">{rendered}</td>'
        return f"<td>{rendered}</td>"

    def _render_header(self, text: str, *, inline_css: bool) -> str:
        """Render a single header as an HTML ``<th>`` element."""
        escaped = html.escape(text)
        if inline_css:
            th_style = f"background:{TABLE_HEADER_BG};color:{TABLE_HEADER_TEXT};padding:8px 12px;text-align:left"
            return f'<th style="{th_style}">{escaped}</th>'
        return f"<th>{escaped}</th>"

    def render(self, *, inline_css: bool = False) -> str:
        """Render the table as an HTML ``<table>``.

        Args:
            inline_css: If True, use inline styles instead of CSS classes.

        Returns:
            HTML ``<table>`` string.
        """
        parts: list[str] = []

        if self.title:
            escaped_title = html.escape(self.title)
            parts.append(f"<h3>{escaped_title}</h3>")

        if inline_css:
            table_style = f"border-collapse:collapse;width:100%;font-family:{TABLE_FONT_FAMILY};background:{TABLE_ROW_BG};color:{TABLE_ROW_TEXT}"
            parts.append(f'<table style="{table_style}">')
        else:
            parts.append('<table class="monitor-table">')

        # Header row
        parts.append("<thead><tr>")
        parts.extend(self._render_header(h, inline_css=inline_css) for h in self.headers)
        parts.append("</tr></thead>")

        # Data rows
        parts.append("<tbody>")
        for idx, row in enumerate(self._rows):
            if inline_css and idx % 2 == 1:
                parts.append(f'<tr style="background:{TABLE_STRIPE_BG}">')
            else:
                parts.append("<tr>")
            parts.extend(self._render_cell(c, inline_css=inline_css) for c in row)
            parts.append("</tr>")
        parts.append("</tbody>")

        parts.append("</table>")
        return "".join(parts)


__all__ = [
    "MonitorTable",
]
