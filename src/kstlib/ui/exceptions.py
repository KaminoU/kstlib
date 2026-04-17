"""Specialised exceptions raised by the ``kstlib.ui`` helpers."""

from __future__ import annotations

from kstlib.config.exceptions import KstlibError

__all__ = [
    "PanelRenderingError",
    "SpinnerError",
    "TableRenderingError",
]


class PanelRenderingError(KstlibError, RuntimeError):
    """Raised when building a Rich panel fails.

    The error captures situations where the ``PanelManager`` cannot resolve
    the requested preset, where override values are invalid, or when the
    payload cannot be converted into a Rich renderable.
    """


class TableRenderingError(KstlibError, RuntimeError):
    """Raised when building a Rich table fails."""


class SpinnerError(KstlibError, RuntimeError):
    """Raised when the spinner encounters an error."""
