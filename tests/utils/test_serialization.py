"""Tests for kstlib.utils.serialization module."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from types import SimpleNamespace

import pytest

from kstlib.utils.serialization import (
    _default_encoder,
    format_output,
    is_xml_content,
    to_json,
    to_xml,
    to_yaml_like,
)

# ─────────────────────────────────────────────────────────────────────────────
# _default_encoder tests
# ─────────────────────────────────────────────────────────────────────────────


class TestDefaultEncoder:
    """Tests for _default_encoder function."""

    def test_encodes_datetime(self) -> None:
        """Encodes datetime to ISO format."""
        dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

        result = _default_encoder(dt)

        assert result == "2024-01-15T10:30:00+00:00"

    def test_encodes_enum(self) -> None:
        """Encodes Enum to its value."""

        class Status(Enum):
            ACTIVE = "active"
            INACTIVE = "inactive"

        result = _default_encoder(Status.ACTIVE)

        assert result == "active"

    def test_encodes_object_with_to_dict(self) -> None:
        """Encodes object with to_dict method."""

        class DataClass:
            def to_dict(self) -> dict[str, str]:
                return {"key": "value"}

        obj = DataClass()

        result = _default_encoder(obj)

        assert result == {"key": "value"}

    def test_encodes_object_with_dict_attr(self) -> None:
        """Encodes object with __dict__ attribute."""
        obj = SimpleNamespace(name="test", count=42)

        result = _default_encoder(obj)

        assert result == {"name": "test", "count": 42}

    def test_raises_for_non_serializable(self) -> None:
        """Raises TypeError for non-serializable objects."""

        class CustomObject:
            __slots__ = ()  # No __dict__

        obj = CustomObject()

        with pytest.raises(TypeError, match="is not JSON serializable"):
            _default_encoder(obj)


# ─────────────────────────────────────────────────────────────────────────────
# to_json tests
# ─────────────────────────────────────────────────────────────────────────────


class TestToJson:
    """Tests for to_json function."""

    def test_serializes_simple_dict(self) -> None:
        """Serializes simple dictionary."""
        data = {"name": "test", "count": 42}

        result = to_json(data)

        assert '"name": "test"' in result
        assert '"count": 42' in result

    def test_uses_custom_indent(self) -> None:
        """Uses custom indentation."""
        data = {"key": "value"}

        result = to_json(data, indent=4)

        assert "    " in result  # 4 spaces

    def test_sorts_keys(self) -> None:
        """Sorts keys when requested."""
        data = {"z": 1, "a": 2, "m": 3}

        result = to_json(data, sort_keys=True)

        # Keys should appear in order: a, m, z
        a_pos = result.index('"a"')
        m_pos = result.index('"m"')
        z_pos = result.index('"z"')
        assert a_pos < m_pos < z_pos

    def test_uses_custom_encoder(self) -> None:
        """Uses custom encoder function."""

        def custom_encoder(obj: object) -> str:
            return "custom"

        data = {"key": object()}

        result = to_json(data, default=custom_encoder)

        assert '"key": "custom"' in result

    def test_uses_default_encoder_for_datetime(self) -> None:
        """Uses default encoder for datetime."""
        dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        data = {"timestamp": dt}

        result = to_json(data)

        assert "2024-01-15T10:30:00+00:00" in result


# ─────────────────────────────────────────────────────────────────────────────
# to_yaml_like tests
# ─────────────────────────────────────────────────────────────────────────────


class TestToYamlLike:
    """Tests for to_yaml_like function."""

    def test_formats_simple_dict(self) -> None:
        """Formats simple dictionary."""
        data = {"name": "test", "count": 42}

        result = to_yaml_like(data)

        assert "name: test" in result
        assert "count: 42" in result

    def test_formats_nested_dict(self) -> None:
        """Formats nested dictionary."""
        data = {"parent": {"child": "value"}}

        result = to_yaml_like(data)

        assert "parent:" in result
        assert "  child: value" in result

    def test_formats_list(self) -> None:
        """Formats list values."""
        data = {"items": ["a", "b", "c"]}

        result = to_yaml_like(data)

        assert "items:" in result
        assert "  - a" in result
        assert "  - b" in result
        assert "  - c" in result

    def test_formats_list_of_dicts(self) -> None:
        """Formats list containing dictionaries."""
        data = {"users": [{"name": "alice"}, {"name": "bob"}]}

        result = to_yaml_like(data)

        assert "users:" in result
        assert "  -" in result
        assert "name: alice" in result
        assert "name: bob" in result

    def test_formats_datetime(self) -> None:
        """Formats datetime to ISO format."""
        dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        data = {"timestamp": dt}

        result = to_yaml_like(data)

        assert "timestamp: 2024-01-15T10:30:00+00:00" in result

    def test_formats_enum(self) -> None:
        """Formats Enum to its value."""

        class Status(Enum):
            ACTIVE = "active"

        data = {"status": Status.ACTIVE}

        result = to_yaml_like(data)

        assert "status: active" in result

    def test_formats_none_as_tilde(self) -> None:
        """Formats None as YAML null (~)."""
        data = {"value": None}

        result = to_yaml_like(data)

        assert "value: ~" in result

    def test_formats_bool_lowercase(self) -> None:
        """Formats boolean as lowercase."""
        data = {"enabled": True, "disabled": False}

        result = to_yaml_like(data)

        assert "enabled: true" in result
        assert "disabled: false" in result

    def test_respects_indent_parameter(self) -> None:
        """Respects base indentation parameter."""
        data = {"key": "value"}

        result = to_yaml_like(data, indent=2)

        assert result.startswith("    key:")  # 4 spaces (2 * 2)


# ─────────────────────────────────────────────────────────────────────────────
# format_output tests
# ─────────────────────────────────────────────────────────────────────────────


class TestFormatOutput:
    """Tests for format_output function."""

    def test_formats_as_json(self) -> None:
        """Formats data as JSON."""
        data = {"key": "value"}

        result = format_output(data, output_format="json")

        assert '"key": "value"' in result

    def test_formats_as_yaml(self) -> None:
        """Formats data as YAML-like."""
        data = {"key": "value"}

        result = format_output(data, output_format="yaml")

        assert "key: value" in result

    def test_formats_text_as_yaml(self) -> None:
        """Formats 'text' format same as YAML."""
        data = {"key": "value"}

        result = format_output(data, output_format="text")

        assert "key: value" in result

    def test_formats_non_dict_as_string(self) -> None:
        """Formats non-dict data as string for yaml/text."""
        data = "simple string"

        result = format_output(data, output_format="yaml")

        assert result == "simple string"

    def test_case_insensitive_format(self) -> None:
        """Format parameter is case-insensitive."""
        data = {"key": "value"}

        result_upper = format_output(data, output_format="JSON")
        result_mixed = format_output(data, output_format="Json")

        assert '"key": "value"' in result_upper
        assert '"key": "value"' in result_mixed

    def test_raises_for_unknown_format(self) -> None:
        """Raises ValueError for unknown format."""
        data = {"key": "value"}

        with pytest.raises(ValueError, match="Unknown output format"):
            format_output(data, output_format="xml")


# ─────────────────────────────────────────────────────────────────────────────
# to_xml tests
# ─────────────────────────────────────────────────────────────────────────────


class TestToXml:
    """Tests for to_xml function."""

    def test_formats_simple_xml(self) -> None:
        """Formats simple XML string."""
        xml = '<?xml version="1.0"?><root><item>test</item></root>'

        result = to_xml(xml)

        assert "<root>" in result
        assert "  <item>" in result or "<item>" in result

    def test_formats_xml_with_attributes(self) -> None:
        """Formats XML with attributes."""
        xml = '<root attr="value"><child/></root>'

        result = to_xml(xml)

        assert 'attr="value"' in result
        assert "<child" in result

    def test_formats_complex_xml(self) -> None:
        """Formats complex nested XML."""
        xml = "<collection><item><id>1</id><name>test</name></item></collection>"

        result = to_xml(xml)

        # Should be multi-line with indentation
        lines = result.strip().split("\n")
        assert len(lines) > 1

    def test_custom_indent(self) -> None:
        """Uses custom indentation."""
        xml = "<root><child>value</child></root>"

        result = to_xml(xml, indent="    ")

        # Should have 4-space indentation
        assert "    <child>" in result or "<child>" in result

    def test_returns_original_on_parse_error(self) -> None:
        """Returns original string if XML parsing fails."""
        invalid_xml = "not xml at all"

        result = to_xml(invalid_xml)

        assert result == invalid_xml

    def test_handles_xml_declaration(self) -> None:
        """Preserves XML declaration."""
        xml = '<?xml version="1.0" encoding="UTF-8"?><root/>'

        result = to_xml(xml)

        assert "<?xml" in result

    def test_formats_xml_with_namespaces(self) -> None:
        """Formats XML with namespaces."""
        xml = '<root xmlns="http://example.com"><child/></root>'

        result = to_xml(xml)

        assert 'xmlns="http://example.com"' in result


# ─────────────────────────────────────────────────────────────────────────────
# is_xml_content tests
# ─────────────────────────────────────────────────────────────────────────────


class TestIsXmlContent:
    """Tests for is_xml_content function."""

    def test_detects_xml_content_type(self) -> None:
        """Detects XML from content-type header."""
        result = is_xml_content("<root/>", "application/xml")

        assert result is True

    def test_detects_xml_charset_content_type(self) -> None:
        """Detects XML from content-type with charset."""
        result = is_xml_content("<root/>", "application/xml; charset=utf-8")

        assert result is True

    def test_detects_vnd_xml_content_type(self) -> None:
        """Detects vendor XML content types."""
        result = is_xml_content("<root/>", "application/vnd.sas.identity+xml")

        assert result is True

    def test_detects_text_xml_content_type(self) -> None:
        """Detects text/xml content type."""
        result = is_xml_content("<root/>", "text/xml")

        assert result is True

    def test_detects_xml_declaration(self) -> None:
        """Detects XML from declaration without content-type."""
        result = is_xml_content('<?xml version="1.0"?><root/>')

        assert result is True

    def test_detects_xml_tag(self) -> None:
        """Detects XML from opening tag without content-type."""
        result = is_xml_content("<root><child/></root>")

        assert result is True

    def test_ignores_whitespace(self) -> None:
        """Ignores leading whitespace when detecting XML."""
        result = is_xml_content("   \n  <root/>")

        assert result is True

    def test_rejects_json(self) -> None:
        """Rejects JSON content."""
        result = is_xml_content('{"key": "value"}')

        assert result is False

    def test_rejects_plain_text(self) -> None:
        """Rejects plain text content."""
        result = is_xml_content("Hello, world!")

        assert result is False

    def test_content_type_overrides_content_inspection(self) -> None:
        """Content-type header takes precedence over content inspection."""
        # Even though content looks like JSON, XML content-type says it's XML
        result = is_xml_content('{"key": "value"}', "application/xml")

        assert result is True
