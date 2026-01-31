"""Tests for text helper utilities."""

from __future__ import annotations

from kstlib.utils import replace_placeholders


class TestReplacePlaceholders:
    """Behavioural coverage for ``replace_placeholders``."""

    def test_replaces_known_placeholders(self) -> None:
        """Replace placeholders found in kwargs."""
        template = "Hello {{ name }}!"
        rendered = replace_placeholders(template, name="Ada")
        assert rendered == "Hello Ada!"

    def test_uses_mapping_and_kwargs(self) -> None:
        """Allow mapping values to coexist with kwargs."""
        template = "{{ greeting }} {{ name }}"
        rendered = replace_placeholders(template, {"greeting": "Hi"}, name="Grace")
        assert rendered == "Hi Grace"

    def test_leaves_unknown_placeholders_intact(self) -> None:
        """Leave unknown placeholders untouched."""
        template = "Value: {{ known }} {{ unknown }}"
        rendered = replace_placeholders(template, known=42)
        assert rendered == "Value: 42 {{ unknown }}"

    def test_converts_none_to_empty_string(self) -> None:
        """Flip None values to empty strings."""
        template = "{{ maybe }}"
        rendered = replace_placeholders(template, maybe=None)
        assert rendered == ""

    def test_accepts_non_string_values(self) -> None:
        """Coerce non-string values via str()."""
        template = "{{ count }} items"
        rendered = replace_placeholders(template, count=3)
        assert rendered == "3 items"

    def test_non_primitive_values_render_as_object(self) -> None:
        """Protect against arbitrary object rendering."""

        class Secret:
            """A class with a sensitive string representation."""

            def __str__(self) -> str:
                return "should-not-leak"

        rendered = replace_placeholders("Result: {{ secret }}", secret=Secret())
        assert rendered == "Result: [object]"
