"""Tests for kstlib.monitoring.image module."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from kstlib.monitoring.exceptions import RenderError
from kstlib.monitoring.image import (
    ALLOWED_MIME_TYPES,
    IMAGE_MAX_BYTES,
    MonitorImage,
    _detect_mime_type,
    _validate_svg,
)

# ---------------------------------------------------------------------------
# Minimal valid image payloads (headers only, not real images)
# ---------------------------------------------------------------------------

PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
JPEG_HEADER = b"\xff\xd8\xff\xe0" + b"\x00" * 50
GIF87_HEADER = b"GIF87a" + b"\x00" * 50
GIF89_HEADER = b"GIF89a" + b"\x00" * 50
WEBP_HEADER = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 50
SVG_CONTENT = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>'


# ---------------------------------------------------------------------------
# TestDetectMimeType
# ---------------------------------------------------------------------------


class TestDetectMimeType:
    """Tests for magic byte detection."""

    def test_png(self) -> None:
        """PNG magic bytes detected."""
        assert _detect_mime_type(PNG_HEADER) == "image/png"

    def test_jpeg(self) -> None:
        """JPEG magic bytes detected."""
        assert _detect_mime_type(JPEG_HEADER) == "image/jpeg"

    def test_gif87a(self) -> None:
        """GIF87a magic bytes detected."""
        assert _detect_mime_type(GIF87_HEADER) == "image/gif"

    def test_gif89a(self) -> None:
        """GIF89a magic bytes detected."""
        assert _detect_mime_type(GIF89_HEADER) == "image/gif"

    def test_webp(self) -> None:
        """WebP magic bytes detected (RIFF + WEBP)."""
        assert _detect_mime_type(WEBP_HEADER) == "image/webp"

    def test_webp_riff_not_webp(self) -> None:
        """RIFF without WEBP marker is not detected as WebP."""
        fake_riff = b"RIFF\x00\x00\x00\x00AVI " + b"\x00" * 50
        assert _detect_mime_type(fake_riff) != "image/webp"

    def test_svg(self) -> None:
        """SVG detected by text heuristic."""
        assert _detect_mime_type(SVG_CONTENT) == "image/svg+xml"

    def test_svg_with_xml_prolog(self) -> None:
        """SVG with XML declaration detected."""
        data = b'<?xml version="1.0"?><svg></svg>'
        assert _detect_mime_type(data) == "image/svg+xml"

    def test_unknown_format(self) -> None:
        """Unknown bytes return None."""
        assert _detect_mime_type(b"\x00\x01\x02\x03" * 10) is None

    def test_too_short(self) -> None:
        """Very short data returns None."""
        assert _detect_mime_type(b"\x89P") is None

    def test_binary_not_svg(self) -> None:
        """Binary data without SVG tag is not detected as SVG."""
        assert _detect_mime_type(b"\x01\x02\x03\x04\x05" * 10) is None


# ---------------------------------------------------------------------------
# TestValidateSvg
# ---------------------------------------------------------------------------


class TestValidateSvg:
    """Tests for SVG safety validation."""

    def test_clean_svg_passes(self) -> None:
        """Clean SVG passes validation."""
        _validate_svg(SVG_CONTENT)  # no exception

    def test_script_tag_rejected(self) -> None:
        """SVG with <script> tag is rejected."""
        data = b"<svg><script>alert(1)</script></svg>"
        with pytest.raises(RenderError, match="dangerous content"):
            _validate_svg(data)

    def test_script_tag_case_insensitive(self) -> None:
        """SVG script detection is case-insensitive."""
        data = b"<svg><SCRIPT>alert(1)</SCRIPT></svg>"
        with pytest.raises(RenderError, match="dangerous content"):
            _validate_svg(data)

    def test_onclick_rejected(self) -> None:
        """SVG with onclick handler is rejected."""
        data = b'<svg onclick="alert(1)"></svg>'
        with pytest.raises(RenderError, match="dangerous content"):
            _validate_svg(data)

    def test_onload_rejected(self) -> None:
        """SVG with onload handler is rejected."""
        data = b'<svg onload="alert(1)"></svg>'
        with pytest.raises(RenderError, match="dangerous content"):
            _validate_svg(data)

    def test_onerror_rejected(self) -> None:
        """SVG with onerror handler is rejected."""
        data = b'<svg><image onerror="alert(1)"/></svg>'
        with pytest.raises(RenderError, match="dangerous content"):
            _validate_svg(data)

    def test_invalid_utf8_rejected(self) -> None:
        """SVG with invalid UTF-8 is rejected."""
        data = b"<svg>\xff\xfe</svg>"
        with pytest.raises(RenderError, match="not valid UTF-8"):
            _validate_svg(data)


# ---------------------------------------------------------------------------
# TestMonitorImage - Construction
# ---------------------------------------------------------------------------


class TestMonitorImageConstruction:
    """Tests for MonitorImage construction validation."""

    def test_data_only(self) -> None:
        """Construction with data only succeeds."""
        img = MonitorImage(data=PNG_HEADER, alt="test")
        assert img.data == PNG_HEADER

    def test_path_only(self, tmp_path: Path) -> None:
        """Construction with path only succeeds."""
        p = tmp_path / "logo.png"
        p.write_bytes(PNG_HEADER)
        img = MonitorImage(path=p, alt="test")
        assert img.path == p

    def test_both_data_and_path_rejected(self, tmp_path: Path) -> None:
        """Providing both data and path raises RenderError."""
        p = tmp_path / "logo.png"
        p.write_bytes(PNG_HEADER)
        with pytest.raises(RenderError, match="not both"):
            MonitorImage(data=PNG_HEADER, path=p)

    def test_neither_data_nor_path_rejected(self) -> None:
        """Providing neither data nor path raises RenderError."""
        with pytest.raises(RenderError, match="Provide either"):
            MonitorImage()

    def test_negative_width_rejected(self) -> None:
        """Negative width raises RenderError."""
        with pytest.raises(RenderError, match="width must be positive"):
            MonitorImage(data=PNG_HEADER, width=-1)

    def test_zero_width_rejected(self) -> None:
        """Zero width raises RenderError."""
        with pytest.raises(RenderError, match="width must be positive"):
            MonitorImage(data=PNG_HEADER, width=0)

    def test_negative_height_rejected(self) -> None:
        """Negative height raises RenderError."""
        with pytest.raises(RenderError, match="height must be positive"):
            MonitorImage(data=PNG_HEADER, height=-1)


# ---------------------------------------------------------------------------
# TestMonitorImage - Rendering
# ---------------------------------------------------------------------------


class TestMonitorImageRender:
    """Tests for MonitorImage.render() output."""

    def test_png_render(self) -> None:
        """PNG renders as base64 data URI."""
        img = MonitorImage(data=PNG_HEADER, alt="Logo")
        result = img.render()
        assert result.startswith("<img ")
        assert "data:image/png;base64," in result
        assert 'alt="Logo"' in result

    def test_jpeg_render(self) -> None:
        """JPEG renders as base64 data URI."""
        img = MonitorImage(data=JPEG_HEADER, alt="Photo")
        result = img.render()
        assert "data:image/jpeg;base64," in result

    def test_gif_render(self) -> None:
        """GIF renders as base64 data URI."""
        img = MonitorImage(data=GIF89_HEADER, alt="Anim")
        result = img.render()
        assert "data:image/gif;base64," in result

    def test_webp_render(self) -> None:
        """WebP renders as base64 data URI."""
        img = MonitorImage(data=WEBP_HEADER, alt="Modern")
        result = img.render()
        assert "data:image/webp;base64," in result

    def test_svg_render(self) -> None:
        """Clean SVG renders as base64 data URI."""
        img = MonitorImage(data=SVG_CONTENT, alt="Icon")
        result = img.render()
        assert "data:image/svg+xml;base64," in result

    def test_base64_is_valid(self) -> None:
        """Embedded base64 can be decoded back to original data."""
        img = MonitorImage(data=PNG_HEADER, alt="Test")
        result = img.render()
        b64_start = result.index("base64,") + len("base64,")
        b64_end = result.index('"', b64_start)
        decoded = base64.b64decode(result[b64_start:b64_end])
        assert decoded == PNG_HEADER

    def test_width_attribute(self) -> None:
        """Width attribute rendered when specified."""
        img = MonitorImage(data=PNG_HEADER, alt="", width=200)
        result = img.render()
        assert 'width="200"' in result

    def test_height_attribute(self) -> None:
        """Height attribute rendered when specified."""
        img = MonitorImage(data=PNG_HEADER, alt="", height=100)
        result = img.render()
        assert 'height="100"' in result

    def test_width_and_height(self) -> None:
        """Both width and height rendered when specified."""
        img = MonitorImage(data=PNG_HEADER, alt="", width=200, height=100)
        result = img.render()
        assert 'width="200"' in result
        assert 'height="100"' in result

    def test_no_width_height_by_default(self) -> None:
        """No width/height attributes when not specified."""
        img = MonitorImage(data=PNG_HEADER, alt="")
        result = img.render()
        assert "width=" not in result
        assert "height=" not in result

    def test_alt_html_escaped(self) -> None:
        """Alt text is HTML-escaped."""
        img = MonitorImage(data=PNG_HEADER, alt='<script>"xss"</script>')
        result = img.render()
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_inline_css_accepted(self) -> None:
        """inline_css parameter accepted for protocol compatibility."""
        img = MonitorImage(data=PNG_HEADER, alt="")
        result_default = img.render()
        result_inline = img.render(inline_css=True)
        assert result_default == result_inline

    def test_from_file(self, tmp_path: Path) -> None:
        """Render from file path works."""
        p = tmp_path / "logo.png"
        p.write_bytes(PNG_HEADER)
        img = MonitorImage(path=p, alt="File logo")
        result = img.render()
        assert "data:image/png;base64," in result
        assert 'alt="File logo"' in result


# ---------------------------------------------------------------------------
# TestMonitorImage - Deep Defense
# ---------------------------------------------------------------------------


class TestMonitorImageSecurity:
    """Security and validation tests."""

    def test_file_not_found(self) -> None:
        """Missing file raises RenderError."""
        img = MonitorImage(path=Path("/nonexistent/logo.png"), alt="")
        with pytest.raises(RenderError, match="not found"):
            img.render()

    def test_size_limit_exceeded(self) -> None:
        """Image exceeding size limit raises RenderError."""
        big_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * (IMAGE_MAX_BYTES + 1)
        img = MonitorImage(data=big_data, alt="")
        with pytest.raises(RenderError, match="too large"):
            img.render()

    def test_size_at_limit_ok(self) -> None:
        """Image exactly at size limit is accepted."""
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * (IMAGE_MAX_BYTES - 8)
        img = MonitorImage(data=data, alt="")
        result = img.render()
        assert "data:image/png;base64," in result

    def test_too_small_data(self) -> None:
        """Data smaller than 4 bytes raises RenderError."""
        img = MonitorImage(data=b"\x89P", alt="")
        with pytest.raises(RenderError, match="too small"):
            img.render()

    def test_unsupported_format(self) -> None:
        """Unknown image format raises RenderError."""
        img = MonitorImage(data=b"\x00\x01\x02\x03\x04\x05" * 10, alt="")
        with pytest.raises(RenderError, match="Unsupported image format"):
            img.render()

    def test_svg_with_script_rejected(self) -> None:
        """SVG with script tag rejected at render time."""
        data = b"<svg><script>alert(1)</script></svg>"
        img = MonitorImage(data=data, alt="")
        with pytest.raises(RenderError, match="dangerous content"):
            img.render()

    def test_svg_with_event_handler_rejected(self) -> None:
        """SVG with event handler rejected at render time."""
        data = b'<svg onload="alert(1)"></svg>'
        img = MonitorImage(data=data, alt="")
        with pytest.raises(RenderError, match="dangerous content"):
            img.render()

    def test_allowed_mime_types_frozen(self) -> None:
        """ALLOWED_MIME_TYPES is a frozenset (immutable)."""
        assert isinstance(ALLOWED_MIME_TYPES, frozenset)

    def test_max_bytes_is_512kb(self) -> None:
        """Hard limit is 512 KB."""
        assert IMAGE_MAX_BYTES == 512 * 1024


# ---------------------------------------------------------------------------
# TestMonitorImage - Jinja Integration
# ---------------------------------------------------------------------------


class TestMonitorImageJinja:
    """Integration with the Jinja2 renderer."""

    def test_render_filter(self) -> None:
        """MonitorImage works with render_html filter."""
        from kstlib.monitoring.renderer import render_html

        img = MonitorImage(data=PNG_HEADER, alt="Logo")
        result = str(render_html(img))
        assert "<img " in result
        assert "data:image/png;base64," in result

    def test_in_template(self) -> None:
        """MonitorImage works inside render_template."""
        from kstlib.monitoring.renderer import render_template

        img = MonitorImage(data=PNG_HEADER, alt="Logo")
        result = render_template(
            "<div>{{ logo | render }}</div>",
            {"logo": img},
            inline_css=True,
        )
        assert "<img " in result
        assert 'alt="Logo"' in result
