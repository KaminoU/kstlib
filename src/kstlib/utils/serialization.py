"""Serialization utilities for JSON, YAML, and XML output.

This module provides consistent serialization helpers used across kstlib,
particularly for CLI output formatting.

Example:
    >>> from kstlib.utils.serialization import to_json, to_xml
    >>> data = {"name": "test", "count": 42}
    >>> print(to_json(data))
    {
      "name": "test",
      "count": 42
    }
    >>> xml = '<?xml version="1.0"?><root><item>test</item></root>'
    >>> print(to_xml(xml))  # doctest: +NORMALIZE_WHITESPACE
    <?xml version="1.0" ?>
    <root>
      <item>test</item>
    </root>
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any
from xml.dom import minidom

if TYPE_CHECKING:
    from collections.abc import Callable


def _default_encoder(obj: Any) -> Any:
    """Default JSON encoder for complex types.

    Handles:
    - datetime objects (ISO format)
    - Enum values
    - Objects with __dict__ attribute
    - Objects with to_dict() method

    Args:
        obj: Object to encode.

    Returns:
        JSON-serializable representation.

    Raises:
        TypeError: If object is not serializable.
    """
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    msg = f"Object of type {type(obj).__name__} is not JSON serializable"
    raise TypeError(msg)


def to_json(
    data: Any,
    *,
    indent: int = 2,
    sort_keys: bool = False,
    default: Callable[[Any], Any] | None = None,
) -> str:
    r"""Serialize data to JSON string.

    Args:
        data: Data to serialize.
        indent: Indentation level (default: 2).
        sort_keys: Sort dictionary keys (default: False).
        default: Custom encoder function (default: built-in handler).

    Returns:
        JSON string.

    Example:
        >>> to_json({"key": "value"})
        '{\n  "key": "value"\n}'
    """
    encoder = default if default is not None else _default_encoder
    return json.dumps(data, indent=indent, sort_keys=sort_keys, default=encoder)


def to_xml(
    xml_string: str,
    *,
    indent: str = "  ",
) -> str:
    """Pretty-print an XML string.

    Uses xml.dom.minidom for formatting. Falls back to original string
    if parsing fails.

    Args:
        xml_string: Raw XML string to format.
        indent: Indentation string (default: 2 spaces).

    Returns:
        Formatted XML string with proper indentation.

    Example:
        >>> xml = '<?xml version="1.0"?><root><item>test</item></root>'
        >>> formatted = to_xml(xml)
        >>> '<root>' in formatted and '  <item>' in formatted
        True
    """
    try:
        # S318: Safe here - only used for display formatting, not for processing untrusted data
        dom = minidom.parseString(xml_string.encode("utf-8"))  # noqa: S318
        # toprettyxml adds extra blank lines, clean them up
        pretty = dom.toprettyxml(indent=indent)
        # Remove extra blank lines that minidom creates
        lines = [line for line in pretty.split("\n") if line.strip()]
        return "\n".join(lines)
    except Exception:
        # If parsing fails, return original string
        return xml_string


def is_xml_content(content: str, content_type: str | None = None) -> bool:
    """Check if content is XML based on content-type header or content inspection.

    Args:
        content: The content string to check.
        content_type: Optional Content-Type header value.

    Returns:
        True if content appears to be XML.

    Example:
        >>> is_xml_content('<root/>', 'application/xml')
        True
        >>> is_xml_content('<?xml version="1.0"?><root/>')
        True
        >>> is_xml_content('{"key": "value"}')
        False
    """
    # Check content-type header first
    if content_type:
        ct_lower = content_type.lower()
        if "xml" in ct_lower:
            return True

    # Fallback: check content starts with XML markers
    stripped = content.strip()
    return stripped.startswith(("<?xml", "<"))


def to_yaml_like(data: dict[str, Any], *, indent: int = 0) -> str:
    """Format dictionary as YAML-like readable output.

    This is a simplified formatter for CLI output, not full YAML.
    Handles nested dicts, lists, and converts timestamps to ISO format.

    Args:
        data: Dictionary to format.
        indent: Base indentation level.

    Returns:
        YAML-like formatted string.

    Example:
        >>> print(to_yaml_like({"name": "test", "items": ["a", "b"]}))
        name: test
        items:
          - a
          - b
    """
    lines: list[str] = []
    prefix = "  " * indent

    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{prefix}{key}:")
            lines.append(to_yaml_like(value, indent=indent + 1))
        elif isinstance(value, list):
            lines.append(f"{prefix}{key}:")
            for item in value:
                if isinstance(item, dict):
                    # Nested dict in list
                    lines.append(f"{prefix}  -")
                    lines.append(to_yaml_like(item, indent=indent + 2))
                else:
                    lines.append(f"{prefix}  - {item}")
        elif isinstance(value, datetime):
            lines.append(f"{prefix}{key}: {value.isoformat()}")
        elif isinstance(value, Enum):
            lines.append(f"{prefix}{key}: {value.value}")
        elif value is None:
            lines.append(f"{prefix}{key}: ~")
        elif isinstance(value, bool):
            lines.append(f"{prefix}{key}: {str(value).lower()}")
        else:
            lines.append(f"{prefix}{key}: {value}")

    return "\n".join(lines)


def format_output(
    data: Any,
    *,
    output_format: str = "yaml",
) -> str:
    """Format data for CLI output.

    Args:
        data: Data to format.
        output_format: Output format - "json" or "yaml" (default: "yaml").

    Returns:
        Formatted string ready for display.

    Raises:
        ValueError: If output_format is not recognized.

    Example:
        >>> print(format_output({"key": "value"}, output_format="json"))
        {
          "key": "value"
        }
    """
    fmt = output_format.lower()

    if fmt == "json":
        return to_json(data)
    if fmt in ("yaml", "text"):
        if isinstance(data, dict):
            return to_yaml_like(data)
        return str(data)

    msg = f"Unknown output format: {output_format}. Use 'json' or 'yaml'."
    raise ValueError(msg)


__all__ = [
    "format_output",
    "is_xml_content",
    "to_json",
    "to_xml",
    "to_yaml_like",
]
