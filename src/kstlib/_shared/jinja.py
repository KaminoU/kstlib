"""Shared Jinja2 rendering helpers for kstlib internal modules.

Provides a thin wrapper around :class:`jinja2.Environment` with kstlib's
default policy:

- :class:`jinja2.ChainableUndefined`: missing variables resolve to empty
  string (and dotted access on them keeps returning empty), preserving
  graceful behavior for templates with optional fields.
- ``keep_trailing_newline=True``: file templates retain their trailing
  newline if any.
- ``autoescape=False`` by default: kstlib mail templates are authored by
  the application developer, not by end users, so the caller controls
  escaping. Pass ``autoescape=True`` for HTML/XML user-facing content.

These helpers live under ``kstlib._shared`` because they are reused by
several internal subpackages (``mail``, future migrations of
``monitoring``). Import via the full path:

    from kstlib._shared.jinja import render_jinja, render_jinja_file
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import jinja2

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


def render_jinja(
    source: str,
    context: Mapping[str, Any],
    *,
    autoescape: bool = False,
) -> str:
    """Render a Jinja2 template string with the provided context.

    Args:
        source: Jinja2 template source as a string.
        context: Mapping of variables exposed to the template.
        autoescape: When True, autoescape HTML/XML special characters.
            Default False; kstlib mail templates are author-controlled.

    Returns:
        The rendered template as a string.

    Examples:
        >>> from kstlib._shared.jinja import render_jinja
        >>> render_jinja("Hello {{ name }}", {"name": "Ada"})
        'Hello Ada'
        >>> render_jinja("{{ missing }}", {})
        ''

    """
    env = jinja2.Environment(
        autoescape=autoescape,
        undefined=jinja2.ChainableUndefined,
        keep_trailing_newline=True,
    )
    return env.from_string(source).render(**dict(context))


def render_jinja_file(
    path: Path,
    context: Mapping[str, Any],
    *,
    autoescape: bool = False,
    encoding: str = "utf-8",
) -> str:
    """Render a Jinja2 template file with the provided context.

    Reads the file at ``path`` with the requested encoding and renders
    it via :func:`render_jinja`.

    Args:
        path: Path to the Jinja2 template file.
        context: Mapping of variables exposed to the template.
        autoescape: When True, autoescape HTML/XML special characters.
        encoding: Text encoding used to read the template file.

    Returns:
        The rendered template as a string.

    """
    return render_jinja(path.read_text(encoding=encoding), context, autoescape=autoescape)


__all__ = ["render_jinja", "render_jinja_file"]
