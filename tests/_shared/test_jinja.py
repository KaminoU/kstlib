"""Tests for kstlib._shared.jinja helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from kstlib._shared.jinja import render_jinja, render_jinja_file


class TestRenderJinjaBasic:
    """Basic substitution behavior."""

    def test_simple_substitution(self) -> None:
        """Render `Hello {{ name }}` substitutes the value."""
        assert render_jinja("Hello {{ name }}", {"name": "Ada"}) == "Hello Ada"

    def test_int_substitution(self) -> None:
        """Numeric values are stringified by Jinja2 like Python str()."""
        assert render_jinja("Count: {{ count }}", {"count": 42}) == "Count: 42"

    def test_empty_context(self) -> None:
        """An empty context with no placeholders returns the source intact."""
        assert render_jinja("Hello world", {}) == "Hello world"


class TestRenderJinjaControlFlow:
    """Loops, conditions, and filters work end-to-end."""

    def test_for_loop(self) -> None:
        """{% for %} iterates over a list and emits per-item content."""
        out = render_jinja(
            "{% for x in items %}{{ x }},{% endfor %}",
            {"items": [1, 2, 3]},
        )
        assert out == "1,2,3,"

    def test_if_else_true_branch(self) -> None:
        """{% if %} renders the true branch when the condition holds."""
        assert render_jinja("{% if ok %}YES{% else %}NO{% endif %}", {"ok": True}) == "YES"

    def test_if_else_false_branch(self) -> None:
        """{% if %} renders the false branch when the condition fails."""
        assert render_jinja("{% if ok %}YES{% else %}NO{% endif %}", {"ok": False}) == "NO"

    def test_filter_upper(self) -> None:
        """The built-in `upper` filter applies."""
        assert render_jinja("{{ x | upper }}", {"x": "hello"}) == "HELLO"


class TestRenderJinjaUndefined:
    """ChainableUndefined: missing keys silently render empty."""

    def test_missing_key_renders_empty(self) -> None:
        """A missing top-level key renders as the empty string."""
        assert render_jinja("Hello {{ missing }}!", {}) == "Hello !"

    def test_chained_missing_attribute(self) -> None:
        """A chained missing attribute also renders empty."""
        assert render_jinja("{{ a.b.c }}", {}) == ""


class TestRenderJinjaAttributes:
    """Attribute access on real objects via the Jinja2 environment."""

    def test_object_attribute_access(self) -> None:
        """Templates can access object attributes via dot notation."""

        @dataclass
        class Item:
            name: str
            count: int

        out = render_jinja(
            "{{ item.name }}={{ item.count }}",
            {"item": Item(name="x", count=5)},
        )
        assert out == "x=5"


class TestRenderJinjaAutoescape:
    """Autoescape toggles HTML escaping for user-controlled content."""

    def test_autoescape_off_keeps_raw(self) -> None:
        """Default autoescape=False leaves angle brackets untouched."""
        assert render_jinja("{{ html }}", {"html": "<b>bold</b>"}) == "<b>bold</b>"

    def test_autoescape_on_escapes_html(self) -> None:
        """autoescape=True escapes HTML special chars in variables."""
        out = render_jinja("{{ html }}", {"html": "<b>bold</b>"}, autoescape=True)
        assert out == "&lt;b&gt;bold&lt;/b&gt;"


class TestRenderJinjaFile:
    """File-backed rendering reads from disk and renders the same way."""

    def test_render_jinja_file(self, tmp_path: Path) -> None:
        """render_jinja_file reads the file then renders the content."""
        template = tmp_path / "greet.j2"
        template.write_text("Hello {{ name }}!", encoding="utf-8")
        assert render_jinja_file(template, {"name": "Ada"}) == "Hello Ada!"

    def test_render_jinja_file_keeps_trailing_newline(self, tmp_path: Path) -> None:
        """The trailing newline of the template file is preserved."""
        template = tmp_path / "greet.j2"
        template.write_text("Hello {{ name }}!\n", encoding="utf-8")
        assert render_jinja_file(template, {"name": "Ada"}) == "Hello Ada!\n"
