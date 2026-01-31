"""Text manipulation helpers."""

from __future__ import annotations

import importlib
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping
else:  # pragma: no cover - runtime alias for delayed evaluation
    Mapping = importlib.import_module("collections.abc").Mapping

_PLACEHOLDER_PATTERN = re.compile(r"{{\s*(?P<key>[\w.\-]+)\s*}}")


def replace_placeholders(template: str, values: Mapping[str, Any] | None = None, /, **kwargs: Any) -> str:
    """Replace ``{{ placeholder }}`` tokens within *template*.

    Args:
        template: Raw template string containing placeholder patterns.
        values: Optional mapping used to look up replacement values. When provided,
            it is merged with the keyword arguments, giving precedence to the latter.
        **kwargs: Additional placeholder values.

    Returns:
        Rendered template with matching placeholders substituted by their string
        representation. Missing placeholders are left untouched to simplify
        incremental rendering.

    Examples:
        >>> replace_placeholders("Hello {{ name }}!", name="Ada")
        'Hello Ada!'

    """
    combined: dict[str, Any] = {}
    if values:
        combined.update(dict(values))
    if kwargs:
        combined.update(kwargs)

    def _replace(match: re.Match[str]) -> str:
        key = match.group("key")
        if key not in combined:
            return match.group(0)
        value = combined[key]
        if value is None:
            return ""
        if isinstance(value, str | int | float | bool):
            return str(value)
        return "[object]"

    return _PLACEHOLDER_PATTERN.sub(_replace, template)


__all__ = ["replace_placeholders"]
