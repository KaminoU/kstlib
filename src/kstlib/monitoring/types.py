"""Core types for the kstlib.monitoring module.

Defines ``StatusLevel`` enum, ``Renderable`` protocol, and ``CellValue`` alias.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Protocol, runtime_checkable


class StatusLevel(IntEnum):
    """Severity level for monitoring status indicators.

    Values are ordered by severity so comparisons work naturally:
    ``StatusLevel.OK < StatusLevel.WARNING < StatusLevel.ERROR``.

    Attributes:
        OK: Normal operation (#16A085 green).
        WARNING: Degraded but functional (#F1C40F yellow).
        ERROR: Service failure (#E85A4F red).
        CRITICAL: Critical failure requiring immediate action (#c0392b dark red).
    """

    OK = 10
    WARNING = 20
    ERROR = 30
    CRITICAL = 40


@runtime_checkable
class Renderable(Protocol):
    """Protocol for objects that can render themselves as HTML."""

    def render(self, *, inline_css: bool = False) -> str:
        """Render this object as an HTML string.

        Args:
            inline_css: If True, embed styles as inline ``style`` attributes
                instead of CSS class references. Useful for email rendering.

        Returns:
            HTML string representation.
        """
        ...  # pragma: no cover


#: Type alias for values accepted in monitoring cells.
#: Covers primitive scalar types that can appear in tables, KV pairs, and lists.
CellValue = str | int | float | bool

__all__ = [
    "CellValue",
    "Renderable",
    "StatusLevel",
]
