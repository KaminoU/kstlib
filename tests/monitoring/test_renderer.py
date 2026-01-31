"""Tests for kstlib.monitoring.renderer module."""

from __future__ import annotations

import html
from dataclasses import dataclass

import pytest
from jinja2 import Environment
from markupsafe import Markup

from kstlib.monitoring._styles import get_css_classes
from kstlib.monitoring.cell import StatusCell
from kstlib.monitoring.renderer import create_environment, render_html, render_template
from kstlib.monitoring.types import StatusLevel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FakeRenderable:
    """Minimal Renderable for testing."""

    content: str

    def render(self, *, inline_css: bool = False) -> str:
        """Render fake content."""
        if inline_css:
            return f'<b style="color:red">{self.content}</b>'
        return f'<b class="fake">{self.content}</b>'


# ---------------------------------------------------------------------------
# TestRenderHtml
# ---------------------------------------------------------------------------


class TestRenderHtml:
    """Tests for render_html filter."""

    def test_renderable_class_mode(self) -> None:
        """Renderable objects dispatch to .render() in class mode."""
        obj = _FakeRenderable("hello")
        result = render_html(obj)
        assert result == '<b class="fake">hello</b>'

    def test_renderable_inline_mode(self) -> None:
        """Renderable objects dispatch to .render(inline_css=True)."""
        obj = _FakeRenderable("hello")
        result = render_html(obj, inline_css=True)
        assert result == '<b style="color:red">hello</b>'

    def test_status_cell(self, ok_cell: StatusCell) -> None:
        """StatusCell is recognized as Renderable and dispatched."""
        result = render_html(ok_cell)
        assert "status-ok" in result
        assert "UP" in result

    def test_string_escaped(self) -> None:
        """Plain strings are HTML-escaped."""
        result = render_html("<b>bold</b>")
        assert result == "&lt;b&gt;bold&lt;/b&gt;"

    def test_int_escaped(self) -> None:
        """Integers are converted to string."""
        result = render_html(42)
        assert result == "42"

    def test_float_escaped(self) -> None:
        """Floats are converted to string."""
        result = render_html(3.14)
        assert result == "3.14"

    def test_bool_escaped(self) -> None:
        """Booleans are converted to string."""
        result = render_html(True)
        assert result == "True"

    def test_none_escaped(self) -> None:
        """None is converted to 'None' string."""
        result = render_html(None)
        assert result == "None"

    def test_returns_markup(self) -> None:
        """Return type is always jinja2.Markup."""
        assert isinstance(render_html("hello"), Markup)
        assert isinstance(render_html(_FakeRenderable("x")), Markup)

    def test_xss_script_tag(self) -> None:
        """Script tags are escaped in string values."""
        result = render_html("<script>alert('xss')</script>")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_xss_img_onerror(self) -> None:
        """Image onerror payloads are escaped."""
        result = render_html('<img src=x onerror="alert(1)">')
        assert "<img" not in result
        assert "&lt;img" in result

    def test_xss_svg_onload(self) -> None:
        """SVG onload payloads are escaped."""
        result = render_html("<svg/onload=alert(1)>")
        assert "<svg" not in result

    def test_ampersand_escaped(self) -> None:
        """Ampersands are properly escaped."""
        result = render_html("a&b")
        assert result == "a&amp;b"


# ---------------------------------------------------------------------------
# TestCreateEnvironment
# ---------------------------------------------------------------------------


class TestCreateEnvironment:
    """Tests for create_environment factory."""

    def test_render_filter_present(self) -> None:
        """Environment has the 'render' filter registered."""
        env = create_environment()
        assert "render" in env.filters

    def test_render_filter_is_render_html(self) -> None:
        """The 'render' filter is bound to render_html."""
        env = create_environment()
        assert env.filters["render"] is render_html

    def test_autoescape_enabled_by_default(self) -> None:
        """Autoescape is True by default."""
        env = create_environment()
        assert env.autoescape is True

    def test_autoescape_override(self) -> None:
        """Autoescape can be overridden via kwargs."""
        env = create_environment(autoescape=False)
        assert env.autoescape is False

    def test_kwargs_forwarded(self) -> None:
        """Extra kwargs are forwarded to jinja2.Environment."""
        env = create_environment(trim_blocks=True, lstrip_blocks=True)
        assert env.trim_blocks is True
        assert env.lstrip_blocks is True

    def test_returns_environment(self) -> None:
        """Return type is jinja2.Environment."""
        env = create_environment()
        assert isinstance(env, Environment)

    def test_template_e2e_with_renderable(self) -> None:
        """End-to-end: template renders a Renderable via the filter."""
        env = create_environment()
        tpl = env.from_string("<p>{{ cell | render }}</p>")
        cell = StatusCell("OK", StatusLevel.OK)
        result = tpl.render(cell=cell)
        assert '<span class="status-ok">OK</span>' in result

    def test_template_e2e_escapes_string(self) -> None:
        """End-to-end: plain string in template is escaped by filter."""
        env = create_environment()
        tpl = env.from_string("{{ val | render }}")
        result = tpl.render(val="<b>hi</b>")
        assert "&lt;b&gt;hi&lt;/b&gt;" in result

    def test_autoescape_escapes_raw_var(self) -> None:
        """Autoescape escapes raw variables not passed through filter."""
        env = create_environment()
        tpl = env.from_string("{{ raw }}")
        result = tpl.render(raw="<b>hi</b>")
        assert "&lt;b&gt;hi&lt;/b&gt;" in result


# ---------------------------------------------------------------------------
# TestRenderTemplate
# ---------------------------------------------------------------------------


class TestRenderTemplate:
    """Tests for render_template helper."""

    def test_basic_render(self) -> None:
        """Simple template renders with context."""
        result = render_template("Hello {{ name }}", {"name": "World"})
        assert "Hello World" in result

    def test_css_block_prepended_by_default(self) -> None:
        """CSS <style> block is prepended when inline_css=False."""
        result = render_template("<p>test</p>", {})
        assert result.startswith("<style>")
        assert "<p>test</p>" in result

    def test_no_css_block_when_inline(self) -> None:
        """No <style> block when inline_css=True."""
        result = render_template("<p>test</p>", {}, inline_css=True)
        assert "<style>" not in result
        assert result == "<p>test</p>"

    def test_css_matches_get_css_classes(self) -> None:
        """Prepended CSS block matches get_css_classes() output."""
        result = render_template("<p>ok</p>", {})
        css = get_css_classes()
        assert result.startswith(css)

    def test_renderable_in_template(self) -> None:
        """Renderable objects work with the render filter in templates."""
        cell = StatusCell("UP", StatusLevel.OK)
        result = render_template("{{ cell | render }}", {"cell": cell}, inline_css=True)
        assert "status-ok" in result
        assert "UP" in result

    def test_renderable_inline_in_template(self) -> None:
        """Render filter with inline_css=True via template syntax."""
        cell = StatusCell("UP", StatusLevel.OK)
        result = render_template(
            "{{ cell | render(inline_css=True) }}",
            {"cell": cell},
            inline_css=True,
        )
        assert "style=" in result
        assert "#16A085" in result

    def test_context_none(self) -> None:
        """None context is treated as empty dict."""
        result = render_template("static", None, inline_css=True)
        assert result == "static"

    def test_context_default(self) -> None:
        """Default context (no arg) works."""
        result = render_template("static", inline_css=True)
        assert result == "static"

    def test_source_type_error(self) -> None:
        """Non-string source raises TypeError."""
        with pytest.raises(TypeError, match="source must be str"):
            render_template(123, {})  # type: ignore[arg-type]

    def test_source_bytes_rejected(self) -> None:
        """Bytes source raises TypeError."""
        with pytest.raises(TypeError, match="source must be str"):
            render_template(b"<p>hi</p>", {})  # type: ignore[arg-type]

    def test_context_type_error(self) -> None:
        """Non-dict context raises TypeError."""
        with pytest.raises(TypeError, match="context must be dict"):
            render_template("hi", [1, 2])  # type: ignore[arg-type]

    def test_context_list_rejected(self) -> None:
        """List context raises TypeError."""
        with pytest.raises(TypeError, match="context must be dict"):
            render_template("hi", ["a"])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# TestRendererSecurity
# ---------------------------------------------------------------------------

XSS_PAYLOADS = [
    "<script>alert('xss')</script>",
    '<img src=x onerror="alert(1)">',
    "<svg/onload=alert(1)>",
    '"><script>alert(1)</script>',
    "javascript:alert(1)",
    '<iframe src="javascript:alert(1)">',
    '<body onload="alert(1)">',
    '<input onfocus="alert(1)" autofocus>',
]


class TestRendererSecurity:
    """Security-focused tests for the renderer module."""

    @pytest.mark.parametrize("payload", XSS_PAYLOADS)
    def test_xss_render_html(self, payload: str) -> None:
        """XSS payloads are escaped by render_html (no executable HTML)."""
        result = str(render_html(payload))
        # Angle brackets must be escaped so browsers cannot parse tags
        assert "<" not in result
        assert ">" not in result
        assert html.escape(payload) == result

    @pytest.mark.parametrize("payload", XSS_PAYLOADS)
    def test_xss_in_template(self, payload: str) -> None:
        """XSS payloads in template context are escaped by autoescape."""
        result = render_template("{{ val }}", {"val": payload}, inline_css=True)
        assert "<script" not in result.lower()

    def test_ssti_value_not_evaluated(self) -> None:
        """Template syntax in a value is not evaluated (SSTI prevention)."""
        result = render_template(
            "{{ val }}",
            {"val": "{{ 7*7 }}"},
            inline_css=True,
        )
        # The value should be escaped, not evaluated to "49"
        assert "49" not in result
        assert "7*7" in result

    def test_double_escape_prevention(self) -> None:
        """Renderable HTML is not double-escaped by autoescape."""
        cell = StatusCell("OK", StatusLevel.OK)
        result = render_template("{{ cell | render }}", {"cell": cell}, inline_css=True)
        # Should contain actual HTML, not escaped HTML
        assert "<span" in result
        assert "&lt;span" not in result

    def test_autoescape_bypass_attempt(self) -> None:
        """Raw string without Markup is still escaped by autoescape."""
        result = render_template("{{ val }}", {"val": "<b>raw</b>"}, inline_css=True)
        assert "&lt;b&gt;raw&lt;/b&gt;" in result
        assert "<b>raw</b>" not in result

    def test_context_pollution_class(self) -> None:
        """__class__ in context does not leak Python internals."""
        result = render_template(
            "{{ __class__ }}",
            {"__class__": "injected"},
            inline_css=True,
        )
        # Should render the string value, not Python's __class__
        assert "injected" in result

    def test_context_pollution_globals(self) -> None:
        """__globals__ in context key is safe."""
        result = render_template(
            "{{ __globals__ }}",
            {"__globals__": "safe"},
            inline_css=True,
        )
        assert "safe" in result

    def test_attribute_access_escaped(self) -> None:
        """Dunder attribute output is HTML-escaped by autoescape."""
        result = render_template(
            "{{ ''.__class__ }}",
            {},
            inline_css=True,
        )
        # Autoescape ensures angle brackets are escaped
        assert "<class" not in result
        assert "&lt;class" in result

    def test_filter_immutability(self) -> None:
        """render_html does not modify its argument."""
        obj = _FakeRenderable("test")
        original_content = obj.content
        render_html(obj)
        render_html(obj, inline_css=True)
        assert obj.content == original_content

    def test_render_filter_no_side_effects(self) -> None:
        """Multiple calls to render_html produce identical results."""
        obj = _FakeRenderable("test")
        r1 = render_html(obj)
        r2 = render_html(obj)
        assert r1 == r2
