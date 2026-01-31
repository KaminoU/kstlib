r"""MonitorImage render type for embedded images.

A ``MonitorImage`` renders as an HTML ``<img>`` tag with a base64-encoded
``data:`` URI, suitable for embedding logos and icons in email templates
where external image references are typically blocked.

Examples:
    >>> from kstlib.monitoring.image import MonitorImage
    >>> img = MonitorImage(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50, alt="Logo")
    >>> "data:image/png;base64," in img.render()
    True
"""

from __future__ import annotations

import base64
import html
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from kstlib.monitoring.exceptions import RenderError

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Image format detection and limits
# ---------------------------------------------------------------------------

#: Maximum allowed image size in bytes (512 KB).
IMAGE_MAX_BYTES: int = 512 * 1024

#: Supported image MIME types with their magic byte signatures.
#: Each entry maps a MIME type to a tuple of possible magic byte prefixes.
_MAGIC_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "image/webp": (b"RIFF",),  # RIFF....WEBP (bytes 8-11 checked separately)
    "image/svg+xml": (),  # detected by text heuristic, not magic bytes
}

#: Allowed MIME types for images.
ALLOWED_MIME_TYPES: frozenset[str] = frozenset(_MAGIC_SIGNATURES)

#: Pattern matching dangerous SVG content (script tags, event handlers).
_SVG_DANGEROUS_PATTERN: re.Pattern[str] = re.compile(
    r"<script|on\w+\s*=",
    re.IGNORECASE,
)


def _detect_mime_type(data: bytes) -> str | None:
    """Detect image MIME type from magic bytes.

    Args:
        data: Raw image bytes (at least the first 12 bytes).

    Returns:
        MIME type string if recognized, or None.
    """
    for mime, signatures in _MAGIC_SIGNATURES.items():
        for sig in signatures:
            if data.startswith(sig):
                if mime == "image/webp" and data[8:12] != b"WEBP":
                    continue
                return mime

    # SVG heuristic: XML-like text containing <svg
    if len(data) > 4 and data[:4] != b"\x00\x00\x00\x00":
        try:
            head = data[:1024].decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return None
        if "<svg" in head.lower():
            return "image/svg+xml"

    return None


def _validate_svg(data: bytes) -> None:
    """Validate SVG content for dangerous patterns.

    Args:
        data: Raw SVG bytes.

    Raises:
        RenderError: If dangerous content is detected.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        msg = "SVG content is not valid UTF-8"
        raise RenderError(msg)  # noqa: B904 - intentional chain break for clean message
    if _SVG_DANGEROUS_PATTERN.search(text):
        msg = "SVG contains dangerous content (script or event handler)"
        raise RenderError(msg)


# ---------------------------------------------------------------------------
# MonitorImage
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MonitorImage:
    r"""An image rendered as an HTML ``<img>`` with a base64 data URI.

    The image data can be provided directly as ``bytes`` or loaded from
    a file ``path``. Exactly one of ``data`` or ``path`` must be given.

    Attributes:
        data: Raw image bytes. Mutually exclusive with ``path``.
        path: Path to an image file. Mutually exclusive with ``data``.
        alt: Alt text for the ``<img>`` tag (always HTML-escaped).
        width: Optional width attribute (pixels).
        height: Optional height attribute (pixels).

    Raises:
        RenderError: If both or neither of ``data``/``path`` are given,
            the image exceeds size limits, or the format is unsupported.

    Examples:
        >>> from kstlib.monitoring.image import MonitorImage
        >>> img = MonitorImage(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50, alt="Logo")
        >>> "<img" in img.render()
        True
    """

    data: bytes | None = None
    path: Path | None = None
    alt: str = ""
    width: int | None = None
    height: int | None = None

    def __post_init__(self) -> None:
        """Validate inputs at construction time."""
        if self.data is not None and self.path is not None:
            msg = "Provide either data or path, not both"
            raise RenderError(msg)
        if self.data is None and self.path is None:
            msg = "Provide either data or path"
            raise RenderError(msg)
        if self.width is not None and self.width <= 0:
            msg = f"width must be positive, got {self.width}"
            raise RenderError(msg)
        if self.height is not None and self.height <= 0:
            msg = f"height must be positive, got {self.height}"
            raise RenderError(msg)

    def _load_data(self) -> bytes:
        """Load and validate image bytes."""
        if self.data is not None:
            raw = self.data
        else:
            assert self.path is not None  # guaranteed by __post_init__
            if not self.path.is_file():
                msg = f"Image file not found: {self.path}"
                raise RenderError(msg)
            raw = self.path.read_bytes()

        if len(raw) > IMAGE_MAX_BYTES:
            size_kb = len(raw) // 1024
            limit_kb = IMAGE_MAX_BYTES // 1024
            msg = f"Image too large: {size_kb} KB (limit: {limit_kb} KB)"
            raise RenderError(msg)

        if len(raw) < 4:
            msg = "Image data too small to be valid"
            raise RenderError(msg)

        return raw

    def render(self, *, inline_css: bool = False) -> str:
        """Render the image as an HTML ``<img>`` with a data URI.

        The ``inline_css`` parameter is accepted for protocol conformance
        but has no effect on image rendering (images are always inline).

        Args:
            inline_css: Accepted for Renderable protocol compatibility.

        Returns:
            HTML ``<img>`` string with base64 data URI.

        Raises:
            RenderError: If the image cannot be loaded, exceeds size
                limits, has an unsupported format, or (for SVG) contains
                dangerous content.
        """
        _ = inline_css  # accepted for Renderable protocol, no effect on images
        raw = self._load_data()
        mime = _detect_mime_type(raw)
        if mime is None:
            msg = "Unsupported image format (allowed: PNG, JPEG, GIF, WebP, SVG)"
            raise RenderError(msg)
        if mime not in ALLOWED_MIME_TYPES:
            msg = f"Image type {mime} is not allowed"
            raise RenderError(msg)
        if mime == "image/svg+xml":
            _validate_svg(raw)

        b64 = base64.b64encode(raw).decode("ascii")
        escaped_alt = html.escape(self.alt)

        attrs = [f'src="data:{mime};base64,{b64}"', f'alt="{escaped_alt}"']
        if self.width is not None:
            attrs.append(f'width="{self.width}"')
        if self.height is not None:
            attrs.append(f'height="{self.height}"')

        return f"<img {' '.join(attrs)}>"


__all__ = [
    "ALLOWED_MIME_TYPES",
    "IMAGE_MAX_BYTES",
    "MonitorImage",
]
