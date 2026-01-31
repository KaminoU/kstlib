"""MonitorMetric render type for hero number display.

A ``MonitorMetric`` renders as a ``<div>`` with a large value and an
optional label, suitable for KPI dashboards (P&L, uptime, etc.).
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import TYPE_CHECKING

from kstlib.monitoring._styles import (
    METRIC_FONT_SIZE,
    METRIC_LABEL_COLOR,
    STATUS_COLORS,
)
from kstlib.monitoring.types import StatusLevel

if TYPE_CHECKING:
    from kstlib.monitoring.types import CellValue


@dataclass(frozen=True, slots=True)
class MonitorMetric:
    """A hero-number metric rendered as an HTML ``<div>``.

    Attributes:
        value: The metric value to display prominently.
        label: Optional descriptive label shown below the value.
        level: Severity level controlling the value color.
        unit: Optional unit suffix appended to the value (e.g. "%", "ms").

    Examples:
        >>> from kstlib.monitoring.metric import MonitorMetric
        >>> from kstlib.monitoring.types import StatusLevel
        >>> m = MonitorMetric(99.9, label="Uptime", level=StatusLevel.OK, unit="%")
        >>> "99.9" in m.render()
        True
    """

    value: CellValue
    label: str = ""
    level: StatusLevel = StatusLevel.OK
    unit: str = ""

    def render(self, *, inline_css: bool = False) -> str:
        """Render the metric as an HTML ``<div>``.

        Args:
            inline_css: If True, use inline styles instead of CSS classes.

        Returns:
            HTML ``<div>`` string.
        """
        escaped_val = html.escape(str(self.value))
        escaped_unit = html.escape(self.unit)
        display = f"{escaped_val}{escaped_unit}" if self.unit else escaped_val

        if inline_css:
            color = STATUS_COLORS[self.level]
            wrapper_style = "text-align:center;padding:12px"
            value_style = f"font-size:{METRIC_FONT_SIZE};font-weight:bold;color:{color}"
            parts = [
                f'<div style="{wrapper_style}">',
                f'<div style="{value_style}">{display}</div>',
            ]
            if self.label:
                label_style = f"color:{METRIC_LABEL_COLOR};font-size:0.9em"
                escaped_label = html.escape(self.label)
                parts.append(f'<div style="{label_style}">{escaped_label}</div>')
            parts.append("</div>")
            return "".join(parts)

        parts = [
            '<div class="monitor-metric">',
            f'<div class="metric-value">{display}</div>',
        ]
        if self.label:
            escaped_label = html.escape(self.label)
            parts.append(f'<div class="metric-label">{escaped_label}</div>')
        parts.append("</div>")
        return "".join(parts)


__all__ = [
    "MonitorMetric",
]
