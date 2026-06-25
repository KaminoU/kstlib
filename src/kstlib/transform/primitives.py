"""Atomic transform primitives for kstlib.transform.

Pure functions with no state. Each takes data + PrimitiveConfig
and returns transformed data. Input validation is performed before
any allocation or processing (fail fast).
"""

from __future__ import annotations

import base64 as b64_module
import binascii
import copy
import json as json_module
import logging
import re
import zlib as zlib_module
from typing import Any
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as ET
from defusedxml.ElementTree import fromstring as _safe_xml_fromstring

from kstlib.transform.config import PrimitiveConfig
from kstlib.transform.exceptions import (
    CompressError,
    DecodeError,
    DecompressError,
    EncodeError,
    ParseError,
    SerializeError,
)
from kstlib.transform.validators import (
    MAX_DECOMPRESSED_SIZE,
    MAX_DECOMPRESSION_RATIO,
    MAX_INPUT_SIZE,
    MAX_JSON_SIZE,
    MAX_XML_SIZE,
)

log = logging.getLogger(__name__)

#: Pre-compiled pattern to strip non-base64-alphabet characters in lenient mode.
#: Allowed alphabet: A-Z, a-z, 0-9, +, /, =. Anything else is removed.
#: Compiled at module level (perf: avoid recompilation in hot path).
_NON_BASE64_PATTERN: re.Pattern[str] = re.compile(r"[^A-Za-z0-9+/=]")


# ============================================================================
# base64
# ============================================================================


def base64_decode(data: str, config: PrimitiveConfig) -> bytes:
    r"""Decode base64 string to bytes.

    Supports SAS Viya wire formats and other proprietary base64 variants
    via two opt-in options:

    - ``strip_prefix``: a literal string that, if present at the start
      of the input, is removed before decoding. Useful for SAS Viya
      report blobs which begin with ``"TRUE###"`` (the ``TRUE`` part
      decodes to the 3-byte SAS proprietary header and ``###`` is a
      separator that lenient base64 decoders skip).
    - ``strict``: when ``True`` (default), the underlying decoder runs
      with ``validate=True`` and rejects any character outside the
      base64 alphabet. When ``False``, non-alphabet characters are
      stripped before decoding (matches the de facto behavior of
      Python's stdlib ``base64.b64decode`` and most other tools).

    Args:
        data: Base64-encoded string. May include a configurable prefix
            and (in lenient mode) embedded whitespace or separators.
        config: Primitive config. Recognized options:

            * ``strip_prefix`` (str | None): literal prefix to remove
              before decoding. Default ``None``. Max 32 chars. If the
              input does not start with this prefix, the option is a
              no-op (does NOT raise) so the same chain can handle
              mixed blobs that sometimes carry the prefix.
            * ``strict`` (bool): when ``True`` (default) reject any
              non-alphabet character; when ``False`` strip them
              silently before decoding.

    Returns:
        Decoded bytes.

    Raises:
        DecodeError: If data is not a string, exceeds the input size
            limit, or fails to decode after the configured pre-processing.

    Examples:
        >>> base64_decode("SGVsbG8=", PrimitiveConfig(name="base64"))
        b'Hello'
        >>> # SAS Viya pattern: strip the proprietary "TRUE###" prefix
        >>> cfg = PrimitiveConfig(name="base64",
        ...     options={"strip_prefix": "TRUE###", "strict": False})
        >>> base64_decode("TRUE###SGVsbG8=", cfg)
        b'Hello'
        >>> # strip_prefix is a no-op when the input does not start with it
        >>> cfg2 = PrimitiveConfig(name="base64",
        ...     options={"strip_prefix": "TRUE###"})
        >>> base64_decode("SGVsbG8=", cfg2)
        b'Hello'
        >>> # Lenient mode strips embedded non-alphabet noise
        >>> cfg3 = PrimitiveConfig(name="base64", options={"strict": False})
        >>> base64_decode("SGVs###bG8=", cfg3)
        b'Hello'

    """
    if not isinstance(data, str):
        raise DecodeError(
            f"Expected str, got {type(data).__name__}",
            primitive_name="base64",
        )
    if len(data) > MAX_INPUT_SIZE:
        raise DecodeError(
            f"Input exceeds limit ({len(data):,} > {MAX_INPUT_SIZE:,})",
            primitive_name="base64",
        )

    # Track whether the original input was non-empty so we can detect
    # the case where pre-processing strips everything (e.g. all-noise input).
    # Empty input is still allowed (legacy behavior: returns b"").
    original_was_non_empty = bool(data)

    # Step 1: optional prefix strip (no-op if data does not start with it)
    strip_prefix = config.options.get("strip_prefix")
    if strip_prefix and data.startswith(strip_prefix):
        data = data[len(strip_prefix) :]

    # Step 2: optional lenient cleanup (strip non-alphabet chars)
    strict = config.options.get("strict", True)
    if not strict:
        data = _NON_BASE64_PATTERN.sub("", data)

    # Detect "all noise was stripped to nothing" only when caller passed
    # actual data (preserves the legacy b64decode("") -> b"" behavior).
    if not data and original_was_non_empty:
        raise DecodeError(
            "Empty base64 data after pre-processing",
            primitive_name="base64",
        )

    try:
        return b64_module.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise DecodeError(
            f"Invalid base64 data (length: {len(data)})",
            primitive_name="base64",
        ) from exc


def base64_encode(data: bytes, config: PrimitiveConfig) -> str:
    """Encode bytes to base64 string with an optional literal prefix.

    The ``prefix`` option allows reattaching a proprietary marker after
    encoding, mirroring ``base64_decode``'s ``strip_prefix`` on the
    forward path. The typical SAS Viya use case is ``"TRUE###"``: the
    forward chain strips it before decoding, the backward chain
    re-prepends it after encoding so the wire format is preserved
    bit-for-bit.

    Args:
        data: Raw bytes to encode.
        config: Primitive config. Recognized options:

            * ``prefix`` (str | None): literal string prepended to the
              base64 result. Default ``None``. Max 32 chars.

    Returns:
        Base64-encoded string, optionally prefixed.

    Raises:
        EncodeError: If data is not bytes.

    Examples:
        >>> base64_encode(b"Hello", PrimitiveConfig(name="base64"))
        'SGVsbG8='
        >>> # Reattach the SAS Viya proprietary prefix
        >>> cfg = PrimitiveConfig(name="base64", options={"prefix": "TRUE###"})
        >>> base64_encode(b"Hello", cfg)
        'TRUE###SGVsbG8='

    """
    if not isinstance(data, bytes):
        raise EncodeError(
            f"Expected bytes, got {type(data).__name__}",
            primitive_name="base64",
        )
    encoded = b64_module.b64encode(data).decode("ascii")
    prefix: str | None = config.options.get("prefix")
    if prefix:
        return f"{prefix}{encoded}"
    return encoded


# ============================================================================
# zlib
# ============================================================================


def zlib_decompress(data: bytes, config: PrimitiveConfig) -> bytes:
    """Decompress zlib data with optional header skip.

    Args:
        data: Compressed bytes (possibly with prefix header).
        config: Options: skip_bytes (int) strips N leading bytes.

    Returns:
        Decompressed bytes.

    Raises:
        DecompressError: If decompression fails or input invalid.

    Examples:
        >>> import zlib
        >>> compressed = zlib.compress(b"Hello")
        >>> zlib_decompress(compressed, PrimitiveConfig(name="zlib"))
        b'Hello'

    """
    if not isinstance(data, bytes):
        raise DecompressError(
            f"Expected bytes, got {type(data).__name__}",
            primitive_name="zlib",
        )

    skip_bytes: int = config.options.get("skip_bytes", 0)

    if skip_bytes > len(data):
        raise DecompressError(
            f"skip_bytes ({skip_bytes}) exceeds data length ({len(data)})",
            primitive_name="zlib",
        )

    payload = data[skip_bytes:]

    try:
        result = zlib_module.decompress(payload)
    except zlib_module.error as exc:
        raise DecompressError(
            f"zlib decompression failed (input: {len(payload):,} bytes)",
            primitive_name="zlib",
        ) from exc

    # Zlib bomb protection
    if len(result) > MAX_DECOMPRESSED_SIZE:
        raise DecompressError(
            f"Decompressed size ({len(result):,}) exceeds limit ({MAX_DECOMPRESSED_SIZE:,})",
            primitive_name="zlib",
        )

    compressed_size = max(len(payload), 1)
    ratio = len(result) / compressed_size
    if ratio > MAX_DECOMPRESSION_RATIO:
        raise DecompressError(
            f"Decompression ratio {ratio:.1f} exceeds limit ({MAX_DECOMPRESSION_RATIO})",
            primitive_name="zlib",
        )

    return result


def zlib_compress(data: bytes, config: PrimitiveConfig) -> bytes:
    """Compress data with zlib, optionally prepending a header.

    Args:
        data: Raw bytes to compress.
        config: Primitive config. Recognized options:

            * ``prepend_bytes`` (str | None): hex string prepended
              before the compressed bytes. Default ``None``.
            * ``level`` (int): compression level passed to
              ``zlib.compress``. Range -1 to 9, where -1 means "use
              the Python zlib default level" (typically 6), 0 means
              no compression, and 9 means maximum compression.
              Default -1. Higher values produce smaller output but
              are slower.

    Returns:
        Compressed bytes with optional header prefix.

    Raises:
        CompressError: If compression fails or prepend_bytes hex is invalid.

    Examples:
        >>> result = zlib_compress(b"Hello", PrimitiveConfig(name="zlib"))
        >>> import zlib
        >>> zlib.decompress(result)
        b'Hello'
        >>> # Maximum compression level
        >>> cfg = PrimitiveConfig(name="zlib", options={"level": 9})
        >>> result9 = zlib_compress(b"Hello world " * 100, cfg)
        >>> zlib.decompress(result9) == b"Hello world " * 100
        True

    """
    if not isinstance(data, bytes):
        raise CompressError(
            f"Expected bytes, got {type(data).__name__}",
            primitive_name="zlib",
        )

    prepend_hex: str = config.options.get("prepend_bytes", "")
    level: int = config.options.get("level", -1)

    try:
        compressed = zlib_module.compress(data, level)
    except zlib_module.error as exc:
        raise CompressError(
            f"zlib compression failed (input: {len(data):,} bytes)",
            primitive_name="zlib",
        ) from exc

    if prepend_hex:
        try:
            header = bytes.fromhex(prepend_hex)
        except ValueError as exc:
            raise CompressError(
                f"Invalid prepend_bytes hex: {prepend_hex!r}",
                primitive_name="zlib",
            ) from exc
        return header + compressed

    return compressed


# ============================================================================
# json
# ============================================================================


def _extract_by_path(data: Any, path: str) -> Any:
    """Extract a value from nested dicts using dot-notation path.

    Args:
        data: Parsed JSON (dict).
        path: Dot-separated path (e.g. "transferableContent.content").

    Returns:
        Extracted value.

    Raises:
        ParseError: If path not found.

    """
    current = data
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            raise ParseError(
                f"Path '{path}' not found in parsed data",
                primitive_name="json",
            )
        current = current[segment]
    return current


def _wrap_by_path(value: Any, path: str, envelope: dict[str, Any] | None) -> dict[str, Any]:
    """Wrap a value into a nested dict at the given dot-notation path.

    If envelope is provided, replaces only the path in the envelope
    (lossless round-trip). Otherwise builds a minimal dict.

    Args:
        value: Value to wrap.
        path: Dot-separated path.
        envelope: Original envelope dict for lossless restoration.

    Returns:
        Dict with value placed at path.

    """
    if envelope is not None:
        restored = copy.deepcopy(envelope)
        segments = path.split(".")
        current: dict[str, Any] = restored
        for segment in segments[:-1]:
            current = current[segment]
        current[segments[-1]] = value
        return restored

    # Build minimal path
    segments = path.split(".")
    result: dict[str, Any] = {}
    current = result
    for segment in segments[:-1]:
        child: dict[str, Any] = {}
        current[segment] = child
        current = child
    current[segments[-1]] = value
    return result


def json_parse(
    data: str | bytes,
    config: PrimitiveConfig,
) -> tuple[Any, dict[str, Any] | None]:
    """Parse JSON string, optionally extracting a nested field.

    Returns a tuple of (value, envelope). If extract is used, envelope
    contains the original parsed dict for lossless backward restoration.
    If no extract, envelope is None.

    Args:
        data: JSON string or bytes.
        config: Options: extract (dot path).

    Returns:
        Tuple of (extracted_or_full_value, original_envelope_or_None).

    Raises:
        ParseError: If JSON parsing fails or extract path not found.

    Examples:
        >>> val, env = json_parse('{"a": 1}', PrimitiveConfig(name="json"))
        >>> val
        {'a': 1}

    """
    if not isinstance(data, str | bytes):
        raise ParseError(
            f"Expected str or bytes, got {type(data).__name__}",
            primitive_name="json",
        )

    size = len(data)
    if size > MAX_JSON_SIZE:
        raise ParseError(
            f"JSON input exceeds limit ({size:,} > {MAX_JSON_SIZE:,})",
            primitive_name="json",
        )

    try:
        parsed = json_module.loads(data)
    except (json_module.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ParseError(
            f"Invalid JSON (input length: {size:,})",
            primitive_name="json",
        ) from exc

    extract_path = config.options.get("extract")
    if extract_path:
        extracted = _extract_by_path(parsed, extract_path)
        return extracted, parsed

    return parsed, None


def json_serialize(
    data: Any,
    config: PrimitiveConfig,
    *,
    envelope: dict[str, Any] | None = None,
) -> str:
    r"""Serialize Python object to JSON string.

    If wrap path and envelope are provided, restores the value into
    the original envelope structure (lossless round-trip).

    Args:
        data: Python object to serialize.
        config: Primitive config. Recognized options:

            * ``wrap`` (str | None): dot-notation path used together
              with ``envelope`` to restore the value inside its
              original envelope structure. Default ``None``.
            * ``minify`` (bool): when ``True``, output uses compact
              ``separators=(",", ":")`` (no whitespace). When ``False``
              (default), uses Python's default separators
              ``(", ", ": ")``. Useful before zlib compression
              (denser input compresses better).
            * ``ensure_ascii`` (bool): when ``True``, escape every
              non-ASCII character as ``\\uXXXX``. When ``False``
              (default, **diverges from Python stdlib which is True**),
              non-ASCII characters are emitted verbatim. The kstlib
              default is ``False`` to preserve Unicode content
              (French, Japanese, etc.) without bloating the output.
        envelope: Original envelope for lossless restoration when
            ``wrap`` is set.

    Returns:
        JSON string.

    Raises:
        SerializeError: If serialization fails.

    Examples:
        >>> json_serialize({"a": 1}, PrimitiveConfig(name="json"))
        '{"a": 1}'
        >>> # Minified output (no spaces after , and :)
        >>> cfg = PrimitiveConfig(name="json", options={"minify": True})
        >>> json_serialize({"a": 1, "b": 2}, cfg)
        '{"a":1,"b":2}'
        >>> # Preserve Unicode content (default behavior)
        >>> json_serialize({"k": "café"}, PrimitiveConfig(name="json"))
        '{"k": "café"}'
        >>> # Force ASCII escapes
        >>> cfg2 = PrimitiveConfig(name="json", options={"ensure_ascii": True})
        >>> json_serialize({"k": "café"}, cfg2)
        '{"k": "caf\\u00e9"}'

    """
    wrap_path = config.options.get("wrap")
    minify = config.options.get("minify", False)
    ensure_ascii = config.options.get("ensure_ascii", False)

    separators = (",", ":") if minify else None

    try:
        target = _wrap_by_path(data, wrap_path, envelope) if wrap_path else data
        return json_module.dumps(
            target,
            ensure_ascii=ensure_ascii,
            separators=separators,
        )
    except (TypeError, ValueError) as exc:
        raise SerializeError(
            f"JSON serialization failed: {type(data).__name__}",
            primitive_name="json",
        ) from exc


# ============================================================================
# xml
# ============================================================================


def xml_parse(data: str, config: PrimitiveConfig) -> Element:
    """Parse XML string to ElementTree Element.

    Uses defusedxml.ElementTree.fromstring for XXE protection. defusedxml
    raises EntitiesForbidden, DTDForbidden, or ExternalReferenceForbidden
    on malicious payloads; all are wrapped in a ParseError here.

    Args:
        data: XML string.
        config: Primitive config.

    Returns:
        ElementTree root Element.

    Raises:
        ParseError: If XML parsing fails or input is unsafe.

    Examples:
        >>> root = xml_parse("<root><a>1</a></root>", PrimitiveConfig(name="xml"))
        >>> root.tag
        'root'

    """
    if not isinstance(data, str):
        raise ParseError(
            f"Expected str, got {type(data).__name__}",
            primitive_name="xml",
        )

    if len(data) > MAX_XML_SIZE:
        raise ParseError(
            f"XML input exceeds limit ({len(data):,} > {MAX_XML_SIZE:,})",
            primitive_name="xml",
        )

    try:
        result: Element = _safe_xml_fromstring(data)
        return result
    except Exception as exc:
        raise ParseError(
            f"Invalid XML (input length: {len(data):,})",
            primitive_name="xml",
        ) from exc


def xml_serialize(data: Element, config: PrimitiveConfig) -> str:
    """Serialize ElementTree Element to XML string.

    Args:
        data: ElementTree root Element.
        config: Primitive config.

    Returns:
        XML string.

    Raises:
        SerializeError: If serialization fails.

    Examples:
        >>> from xml.etree.ElementTree import Element
        >>> root = Element("root")
        >>> xml_serialize(root, PrimitiveConfig(name="xml"))
        '<root />'

    """
    if not isinstance(data, Element):
        raise SerializeError(
            f"Expected Element, got {type(data).__name__}",
            primitive_name="xml",
        )

    encoding = config.options.get("encoding", "unicode")

    try:
        result = ET.tostring(data, encoding=encoding)
        if not isinstance(result, str):  # pragma: no cover - non-text encoding yields bytes
            result = str(result, "utf-8")
        return result
    except (TypeError, LookupError) as exc:
        raise SerializeError(
            "XML serialization failed",
            primitive_name="xml",
        ) from exc


# ============================================================================
# bytes
# ============================================================================


def bytes_decode(data: bytes, config: PrimitiveConfig) -> str:
    """Decode bytes to string.

    Args:
        data: Raw bytes.
        config: Options: encoding (default utf-8).

    Returns:
        Decoded string.

    Raises:
        DecodeError: If decoding fails.

    Examples:
        >>> bytes_decode(b"Hello", PrimitiveConfig(name="bytes"))
        'Hello'

    """
    if not isinstance(data, bytes):
        raise DecodeError(
            f"Expected bytes, got {type(data).__name__}",
            primitive_name="bytes",
        )
    encoding = config.options.get("encoding", "utf-8")
    try:
        return data.decode(encoding)
    except (UnicodeDecodeError, LookupError) as exc:
        raise DecodeError(
            f"bytes decode failed with encoding '{encoding}' (input: {len(data):,} bytes)",
            primitive_name="bytes",
        ) from exc


def bytes_encode(data: str, config: PrimitiveConfig) -> bytes:
    """Encode string to bytes.

    Args:
        data: String to encode.
        config: Options: encoding (default utf-8).

    Returns:
        Encoded bytes.

    Raises:
        EncodeError: If encoding fails.

    Examples:
        >>> bytes_encode("Hello", PrimitiveConfig(name="bytes"))
        b'Hello'

    """
    if not isinstance(data, str):
        raise EncodeError(
            f"Expected str, got {type(data).__name__}",
            primitive_name="bytes",
        )
    encoding = config.options.get("encoding", "utf-8")
    try:
        return data.encode(encoding)
    except (UnicodeEncodeError, LookupError) as exc:
        raise EncodeError(
            f"bytes encode failed with encoding '{encoding}'",
            primitive_name="bytes",
        ) from exc


# ============================================================================
# string extractors (forward-only)
# ============================================================================


def _validate_string_input(data: object, *, primitive_name: str) -> str:
    """Validate and harden a string input for the string primitives.

    Shared by the forward-only string extractors (split, and future tr /
    removeprefix / removesuffix). Rejects non-string input, oversized
    input, and embedded null bytes before any processing (fail fast).

    Args:
        data: Candidate input. Must be a string.
        primitive_name: Name of the calling primitive, used in errors.

    Returns:
        The validated string (unchanged).

    Raises:
        ParseError: If data is not a string, exceeds the input size
            limit, or contains a null byte.

    """
    if not isinstance(data, str):
        raise ParseError(
            f"Expected str, got {type(data).__name__}",
            primitive_name=primitive_name,
        )
    if len(data) > MAX_INPUT_SIZE:
        log.warning(
            "[SECURITY] %s input exceeds limit (%d > %d bytes), rejected",
            primitive_name,
            len(data),
            MAX_INPUT_SIZE,
        )
        raise ParseError(
            f"Input exceeds limit ({len(data):,} > {MAX_INPUT_SIZE:,})",
            primitive_name=primitive_name,
        )
    if "\x00" in data:
        log.warning("[SECURITY] %s input contains a null byte, rejected", primitive_name)
        raise ParseError("Input contains a null byte", primitive_name=primitive_name)
    return data


def split_extract(data: str, config: PrimitiveConfig) -> str | list[str]:
    r"""Split a string by a literal separator and extract segment(s).

    Forward-only string extractor. The separator is treated literally
    (no regex). Options are read from ``config.options``:

    - ``sep`` (str, required): the literal separator. Validated at config
      time (must be a non-empty string).
    - ``index`` (int | None): which segment to return. ``None`` (default)
      returns the full list of segments; an integer returns that single
      segment (0-based, negatives count from the end: ``-1`` is the last).
    - ``maxsplit`` (int): forwarded to ``str.split``. Default ``-1`` (no
      limit).
    - ``keep_empty`` (bool): when ``False`` (default), empty segments are
      filtered out *before* indexing, which is path-friendly (a leading
      separator does not produce an empty first segment). This
      **diverges from** ``str.split``, which keeps empty segments. Set to
      ``True`` to keep them.

    Args:
        data: Input string to split.
        config: Primitive config carrying the options described above.

    Returns:
        The selected segment (``str``) when ``index`` is set, otherwise
        the list of segments (``list[str]``).

    Raises:
        ParseError: If the input is not a string, exceeds the size limit,
            contains a null byte, or ``index`` is out of range.

    Examples:
        >>> cfg = PrimitiveConfig(name="split", options={"sep": "/", "index": -1})
        >>> split_extract("/reports/reports/abc", cfg)
        'abc'
        >>> split_extract("a/b/c", PrimitiveConfig(name="split", options={"sep": "/"}))
        ['a', 'b', 'c']

    """
    text = _validate_string_input(data, primitive_name="split")

    sep: str = config.options["sep"]
    maxsplit: int = config.options.get("maxsplit", -1)
    keep_empty: bool = config.options.get("keep_empty", False)
    index: int | None = config.options.get("index")

    segments = text.split(sep, maxsplit)
    if not keep_empty:
        segments = [segment for segment in segments if segment]

    if index is None:
        return segments

    try:
        return segments[index]
    except IndexError:
        raise ParseError(
            f"split index {index} out of range ({len(segments)} segment(s))",
            primitive_name="split",
        ) from None


def tr_translate(data: str, config: PrimitiveConfig) -> str:
    r"""Translate or delete characters in a string (character level).

    Forward-only string transformer operating character by character,
    like the Unix ``tr`` command. This is distinct from the substring
    ``replace`` of the patch stage: ``tr`` works on individual
    characters. Exactly one of the following options must be set (enforced
    at config time by :class:`~kstlib.transform.config.PrimitiveConfig`):

    - ``delete`` (str): every character in this set is removed from the
      input.
    - ``map`` (dict[str, str]): a single-character to single-character
      translation table applied to the input.

    Args:
        data: Input string to translate.
        config: Primitive config carrying the ``delete`` or ``map`` option.

    Returns:
        The translated string.

    Raises:
        ParseError: If the input is not a string, exceeds the input size
            limit, or contains a null byte.

    Examples:
        >>> tr_translate("a\nb\n", PrimitiveConfig(name="tr", options={"delete": "\n"}))
        'ab'
        >>> tr_translate("aaa", PrimitiveConfig(name="tr", options={"map": {"a": "b"}}))
        'bbb'

    """
    text = _validate_string_input(data, primitive_name="tr")

    delete: str | None = config.options.get("delete")
    if delete is not None:
        return text.translate(str.maketrans("", "", delete))

    mapping: dict[str, str | int | None] = config.options["map"]
    return text.translate(str.maketrans(mapping))


def remove_prefix(data: str, config: PrimitiveConfig) -> str:
    """Strip a known literal prefix from the start of a string.

    Forward-only string extractor wrapping :meth:`str.removeprefix`. The
    ``prefix`` option (required, validated at config time) is removed from
    the input only when the input starts with it; otherwise the string is
    returned unchanged (no error). This mirrors the standard-library
    semantics and lets the same chain handle mixed inputs that sometimes
    carry the prefix.

    Args:
        data: Input string to strip.
        config: Primitive config carrying the required ``prefix`` option.

    Returns:
        The input with ``prefix`` removed from its start, or the input
        unchanged when it does not start with ``prefix``.

    Raises:
        ParseError: If the input is not a string, exceeds the input size
            limit, or contains a null byte.

    Examples:
        >>> cfg = PrimitiveConfig(name="removeprefix", options={"prefix": "reports/"})
        >>> remove_prefix("reports/xxx", cfg)
        'xxx'
        >>> # No-op when the input does not start with the prefix
        >>> remove_prefix("other/xxx", cfg)
        'other/xxx'

    """
    text = _validate_string_input(data, primitive_name="removeprefix")
    prefix: str = config.options["prefix"]
    return text.removeprefix(prefix)


def remove_suffix(data: str, config: PrimitiveConfig) -> str:
    """Strip a known literal suffix from the end of a string.

    Forward-only string extractor wrapping :meth:`str.removesuffix`. The
    ``suffix`` option (required, validated at config time) is removed from
    the input only when the input ends with it; otherwise the string is
    returned unchanged (no error). This mirrors the standard-library
    semantics and lets the same chain handle mixed inputs that sometimes
    carry the suffix.

    Args:
        data: Input string to strip.
        config: Primitive config carrying the required ``suffix`` option.

    Returns:
        The input with ``suffix`` removed from its end, or the input
        unchanged when it does not end with ``suffix``.

    Raises:
        ParseError: If the input is not a string, exceeds the input size
            limit, or contains a null byte.

    Examples:
        >>> cfg = PrimitiveConfig(name="removesuffix", options={"suffix": ".json"})
        >>> remove_suffix("data.json", cfg)
        'data'
        >>> # No-op when the input does not end with the suffix
        >>> remove_suffix("data.yml", cfg)
        'data.yml'

    """
    text = _validate_string_input(data, primitive_name="removesuffix")
    suffix: str = config.options["suffix"]
    return text.removesuffix(suffix)


# ============================================================================
# Registry
# ============================================================================

#: Forward primitive dispatch table.
FORWARD_DISPATCH: dict[str, Any] = {
    "base64": base64_decode,
    "zlib": zlib_decompress,
    "json": json_parse,
    "xml": xml_parse,
    "bytes": bytes_decode,
    "split": split_extract,
    "tr": tr_translate,
    "removeprefix": remove_prefix,
    "removesuffix": remove_suffix,
}

#: Backward primitive dispatch table.
BACKWARD_DISPATCH: dict[str, Any] = {
    "base64": base64_encode,
    "zlib": zlib_compress,
    "json": json_serialize,
    "xml": xml_serialize,
    "bytes": bytes_encode,
}


__all__ = [
    "BACKWARD_DISPATCH",
    "FORWARD_DISPATCH",
    "base64_decode",
    "base64_encode",
    "bytes_decode",
    "bytes_encode",
    "json_parse",
    "json_serialize",
    "remove_prefix",
    "remove_suffix",
    "split_extract",
    "tr_translate",
    "xml_parse",
    "xml_serialize",
    "zlib_compress",
    "zlib_decompress",
]
