"""Jinja2 rendering integration for monitoring render types.

Provides a Jinja2 filter ``render`` that dispatches to ``Renderable.render()``
for monitoring objects, and HTML-escapes primitives. Includes a pre-configured
environment factory and a standalone template rendering helper.

Examples:
    Render a template with monitoring objects:

    >>> from kstlib.monitoring.renderer import render_template
    >>> from kstlib.monitoring.cell import StatusCell
    >>> from kstlib.monitoring.types import StatusLevel
    >>> cell = StatusCell("UP", StatusLevel.OK)
    >>> html = render_template("<p>{{ s | render }}</p>", {"s": cell})
    >>> "status-ok" in html
    True
"""

from __future__ import annotations

import html as _html
from typing import Any

from jinja2 import Environment
from markupsafe import Markup

from kstlib.monitoring._styles import get_css_classes
from kstlib.monitoring.types import Renderable


def render_html(value: Any, inline_css: bool = False) -> Markup:
    """Jinja2 filter that renders a value as safe HTML.

    When *value* implements :class:`~kstlib.monitoring.types.Renderable`,
    its ``.render()`` method is called. Otherwise the value is converted
    to a string and HTML-escaped.

    Register this filter under the name ``render`` on a Jinja2 environment
    so templates can use ``{{ data | render }}``.

    Args:
        value: Any value to render. ``Renderable`` objects are dispatched
            to their own ``render()`` method; everything else is escaped.
        inline_css: Forwarded to ``Renderable.render(inline_css=...)``.

    Returns:
        A :class:`jinja2.Markup` instance (marked safe to prevent
        double-escaping by Jinja2 autoescape).

    Examples:
        >>> from kstlib.monitoring.renderer import render_html
        >>> str(render_html("<b>bold</b>"))
        '&lt;b&gt;bold&lt;/b&gt;'
    """
    if isinstance(value, Renderable):
        return Markup(value.render(inline_css=inline_css))  # noqa: S704
    return Markup(_html.escape(str(value)))  # noqa: S704


def create_environment(**kwargs: Any) -> Environment:
    """Create a Jinja2 :class:`~jinja2.Environment` with monitoring filters.

    The returned environment has:

    - ``autoescape=True`` by default (overridable via *kwargs*).
    - The ``render`` filter bound to :func:`render_html`.

    Args:
        **kwargs: Forwarded to :class:`jinja2.Environment`. Common
            options include ``loader``, ``autoescape``, ``trim_blocks``.

    Returns:
        A configured :class:`jinja2.Environment`.

    Examples:
        >>> from kstlib.monitoring.renderer import create_environment
        >>> env = create_environment()
        >>> "render" in env.filters
        True
    """
    kwargs.setdefault("autoescape", True)
    env = Environment(**kwargs)  # noqa: S701
    env.filters["render"] = render_html
    return env


def render_template(
    source: str,
    context: dict[str, Any] | None = None,
    *,
    inline_css: bool = False,
) -> str:
    """Render a Jinja2 template string with monitoring support.

    This is a high-level convenience function that creates a temporary
    environment, compiles *source* as a template, and renders it with
    *context*.

    When ``inline_css=False`` (default), the CSS class definitions from
    :func:`~kstlib.monitoring._styles.get_css_classes` are prepended to
    the output so that class-based rendering works out of the box.

    Args:
        source: Jinja2 template source string.
        context: Template variables. ``None`` is treated as an empty dict.
        inline_css: If ``True``, skip the ``<style>`` block prepend.
            Useful when styles are inlined into each element.

    Returns:
        Rendered HTML string.

    Raises:
        TypeError: If *source* is not a ``str`` or *context* is not
            a ``dict`` (or ``None``).

    Examples:
        >>> from kstlib.monitoring.renderer import render_template
        >>> render_template("Hello {{ name }}", {"name": "World"}, inline_css=True)
        'Hello World'
    """
    if not isinstance(source, str):
        raise TypeError(f"source must be str, got {type(source).__name__}")
    if context is not None and not isinstance(context, dict):
        raise TypeError(f"context must be dict or None, got {type(context).__name__}")

    env = create_environment()
    template = env.from_string(source)
    rendered = template.render(**(context or {}))

    if inline_css:
        return rendered
    return get_css_classes() + "\n" + rendered


__all__ = [
    "create_environment",
    "render_html",
    "render_template",
]
