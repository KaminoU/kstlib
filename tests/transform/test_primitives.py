"""Tests for kstlib.transform.primitives."""

from __future__ import annotations

import base64 as b64_module
import json
import logging
import zlib

import pytest

from kstlib.transform.config import PrimitiveConfig
from kstlib.transform.exceptions import (
    CompressError,
    DecodeError,
    DecompressError,
    EncodeError,
    ParseError,
    SerializeError,
)
from kstlib.transform.primitives import (
    base64_decode,
    base64_encode,
    bytes_decode,
    bytes_encode,
    json_parse,
    json_serialize,
    remove_prefix,
    remove_suffix,
    split_extract,
    tr_translate,
    xml_parse,
    xml_serialize,
    zlib_compress,
    zlib_decompress,
)

_CFG_B64 = PrimitiveConfig(name="base64")
_CFG_ZLIB = PrimitiveConfig(name="zlib")
_CFG_JSON = PrimitiveConfig(name="json")
_CFG_XML = PrimitiveConfig(name="xml")
_CFG_BYTES = PrimitiveConfig(name="bytes")


# ============================================================================
# base64
# ============================================================================


class TestBase64Decode:
    """Tests for base64_decode."""

    def test_decode_valid(self) -> None:
        """Decode a valid base64 string."""
        assert base64_decode("SGVsbG8=", _CFG_B64) == b"Hello"

    def test_decode_empty(self) -> None:
        """Decode empty string returns empty bytes."""
        assert base64_decode("", _CFG_B64) == b""

    def test_decode_invalid_base64(self) -> None:
        """Invalid base64 raises DecodeError."""
        with pytest.raises(DecodeError, match="Invalid base64"):
            base64_decode("not-valid-base64!!!", _CFG_B64)

    def test_decode_wrong_type_int(self) -> None:
        """Non-string input raises DecodeError."""
        with pytest.raises(DecodeError, match="Expected str"):
            base64_decode(42, _CFG_B64)  # type: ignore[arg-type]

    def test_decode_wrong_type_bytes(self) -> None:
        """Bytes input raises DecodeError (must be str)."""
        with pytest.raises(DecodeError, match="Expected str"):
            base64_decode(b"SGVsbG8=", _CFG_B64)  # type: ignore[arg-type]


class TestBase64Encode:
    """Tests for base64_encode."""

    def test_encode_bytes(self) -> None:
        """Encode bytes to base64 string."""
        assert base64_encode(b"Hello", _CFG_B64) == "SGVsbG8="

    def test_encode_empty(self) -> None:
        """Encode empty bytes returns empty string."""
        assert base64_encode(b"", _CFG_B64) == ""

    def test_encode_wrong_type_str(self) -> None:
        """String input raises EncodeError."""
        with pytest.raises(EncodeError, match="Expected bytes"):
            base64_encode("hello", _CFG_B64)  # type: ignore[arg-type]

    def test_round_trip(self) -> None:
        """Encode then decode is lossless."""
        original = b"Hello, World! \x00\xff"
        encoded = base64_encode(original, _CFG_B64)
        assert base64_decode(encoded, _CFG_B64) == original


# ============================================================================
# zlib
# ============================================================================


class TestZlibDecompress:
    """Tests for zlib_decompress."""

    def test_decompress_valid(self) -> None:
        """Decompress valid zlib data."""
        compressed = zlib.compress(b"Hello World")
        assert zlib_decompress(compressed, _CFG_ZLIB) == b"Hello World"

    def test_decompress_with_skip_bytes(self) -> None:
        """Decompress with skip_bytes strips header."""
        payload = zlib.compress(b"test data")
        data = b"ABC" + payload
        cfg = PrimitiveConfig(name="zlib", options={"skip_bytes": 3})
        assert zlib_decompress(data, cfg) == b"test data"

    def test_decompress_skip_exceeds_length(self) -> None:
        """skip_bytes > data length raises DecompressError."""
        cfg = PrimitiveConfig(name="zlib", options={"skip_bytes": 10})
        with pytest.raises(DecompressError, match=r"skip_bytes.*exceeds"):
            zlib_decompress(b"AB", cfg)

    def test_decompress_invalid_zlib(self) -> None:
        """Invalid zlib data raises DecompressError."""
        with pytest.raises(DecompressError, match="decompression failed"):
            zlib_decompress(b"not-zlib-data-at-all", _CFG_ZLIB)

    def test_decompress_wrong_type(self) -> None:
        """String input raises DecompressError."""
        with pytest.raises(DecompressError, match="Expected bytes"):
            zlib_decompress("hello", _CFG_ZLIB)  # type: ignore[arg-type]

    def test_decompress_zlib_bomb(self) -> None:
        """High decompression ratio raises DecompressError."""
        bomb = zlib.compress(b"\x00" * 10_000_000)
        with pytest.raises(DecompressError, match="ratio"):
            zlib_decompress(bomb, _CFG_ZLIB)


class TestZlibCompress:
    """Tests for zlib_compress."""

    def test_compress_bytes(self) -> None:
        """Compress and verify roundtrip."""
        data = b"Hello World"
        compressed = zlib_compress(data, _CFG_ZLIB)
        assert zlib.decompress(compressed) == data

    def test_compress_with_prepend(self) -> None:
        """Compress with prepend_bytes adds header."""
        cfg = PrimitiveConfig(name="zlib", options={"prepend_bytes": "4d1504"})
        result = zlib_compress(b"test", cfg)
        assert result[:3] == b"\x4d\x15\x04"
        assert zlib.decompress(result[3:]) == b"test"

    def test_compress_wrong_type(self) -> None:
        """String input raises CompressError."""
        with pytest.raises(CompressError, match="Expected bytes"):
            zlib_compress("hello", _CFG_ZLIB)  # type: ignore[arg-type]

    def test_compress_invalid_hex_prepend(self) -> None:
        """Invalid hex prepend raises TransformConfigError at config time."""
        from kstlib.transform.exceptions import TransformConfigError

        with pytest.raises(TransformConfigError, match="prepend_bytes"):
            PrimitiveConfig(name="zlib", options={"prepend_bytes": "xyz"})

    def test_round_trip_no_header(self) -> None:
        """Compress then decompress is lossless without header."""
        original = b"Round trip test data with unicode: \xc3\xa9"
        compressed = zlib_compress(original, _CFG_ZLIB)
        assert zlib_decompress(compressed, _CFG_ZLIB) == original

    def test_round_trip_with_header(self) -> None:
        """Compress+prepend then skip+decompress is lossless."""
        original = b"SAS report content here"
        cfg_compress = PrimitiveConfig(name="zlib", options={"prepend_bytes": "4d1504"})
        cfg_decompress = PrimitiveConfig(name="zlib", options={"skip_bytes": 3})
        compressed = zlib_compress(original, cfg_compress)
        assert zlib_decompress(compressed, cfg_decompress) == original


# ============================================================================
# json
# ============================================================================


class TestJsonParse:
    """Tests for json_parse."""

    def test_parse_dict(self) -> None:
        """Parse a JSON object string."""
        val, env = json_parse('{"a": 1}', _CFG_JSON)
        assert val == {"a": 1}
        assert env is None

    def test_parse_bytes(self) -> None:
        """Parse JSON from bytes."""
        val, _env = json_parse(b'{"a": 1}', _CFG_JSON)
        assert val == {"a": 1}

    def test_parse_with_extract(self) -> None:
        """Extract nested field from parsed JSON."""
        cfg = PrimitiveConfig(name="json", options={"extract": "a.b"})
        val, env = json_parse('{"a": {"b": "found"}, "c": 99}', cfg)
        assert val == "found"
        assert env is not None
        assert env["c"] == 99

    def test_parse_extract_not_found(self) -> None:
        """Extract path not in data raises ParseError."""
        cfg = PrimitiveConfig(name="json", options={"extract": "x.y"})
        with pytest.raises(ParseError, match=r"Path 'x\.y' not found"):
            json_parse('{"a": 1}', cfg)

    def test_parse_invalid_json(self) -> None:
        """Invalid JSON raises ParseError."""
        with pytest.raises(ParseError, match="Invalid JSON"):
            json_parse("not json at all", _CFG_JSON)

    def test_parse_wrong_type(self) -> None:
        """Non-string/bytes input raises ParseError."""
        with pytest.raises(ParseError, match="Expected str or bytes"):
            json_parse(42, _CFG_JSON)  # type: ignore[arg-type]


class TestJsonSerialize:
    """Tests for json_serialize."""

    def test_serialize_dict(self) -> None:
        """Serialize a dict to JSON string."""
        result = json_serialize({"a": 1}, _CFG_JSON)
        assert result == '{"a": 1}'

    def test_serialize_with_wrap_and_envelope(self) -> None:
        """Wrap value back into original envelope (lossless)."""
        cfg = PrimitiveConfig(name="json", options={"wrap": "a.b"})
        original = {"a": {"b": "old_value"}, "c": 99}
        result = json_serialize("new_value", cfg, envelope=original)
        import json

        parsed = json.loads(result)
        assert parsed["a"]["b"] == "new_value"
        assert parsed["c"] == 99

    def test_serialize_with_wrap_no_envelope(self) -> None:
        """Wrap without envelope builds minimal dict."""
        cfg = PrimitiveConfig(name="json", options={"wrap": "a.b"})
        result = json_serialize("value", cfg)
        import json

        parsed = json.loads(result)
        assert parsed["a"]["b"] == "value"

    def test_round_trip_with_extract_wrap(self) -> None:
        """Parse+extract then serialize+wrap is lossless."""
        original = '{"outer": {"inner": "data"}, "sibling": 42}'
        cfg_parse = PrimitiveConfig(name="json", options={"extract": "outer.inner"})
        cfg_ser = PrimitiveConfig(name="json", options={"wrap": "outer.inner"})

        val, env = json_parse(original, cfg_parse)
        assert val == "data"
        result = json_serialize(val, cfg_ser, envelope=env)
        import json

        assert json.loads(result) == json.loads(original)


# ============================================================================
# xml
# ============================================================================


class TestXmlParse:
    """Tests for xml_parse."""

    def test_parse_valid(self) -> None:
        """Parse valid XML string."""
        root = xml_parse("<root><a>1</a></root>", _CFG_XML)
        assert root.tag == "root"
        assert root.find("a") is not None

    def test_parse_with_namespace(self) -> None:
        """Parse XML with namespace."""
        xml = '<SASReport xmlns="http://www.sas.com/bird">content</SASReport>'
        root = xml_parse(xml, _CFG_XML)
        assert "SASReport" in root.tag

    def test_parse_invalid_xml(self) -> None:
        """Invalid XML raises ParseError."""
        with pytest.raises(ParseError, match="Invalid XML"):
            xml_parse("not xml at all", _CFG_XML)

    def test_parse_wrong_type(self) -> None:
        """Non-string input raises ParseError."""
        with pytest.raises(ParseError, match="Expected str"):
            xml_parse(42, _CFG_XML)  # type: ignore[arg-type]


class TestXmlSerialize:
    """Tests for xml_serialize."""

    def test_serialize_element(self) -> None:
        """Serialize an Element to XML string."""
        from xml.etree.ElementTree import Element

        root = Element("root")
        result = xml_serialize(root, _CFG_XML)
        assert "<root" in result

    def test_serialize_wrong_type(self) -> None:
        """Non-Element input raises SerializeError."""
        with pytest.raises(SerializeError, match="Expected Element"):
            xml_serialize("not an element", _CFG_XML)  # type: ignore[arg-type]

    def test_round_trip(self) -> None:
        """Parse then serialize preserves structure."""
        original = '<root><child attr="val">text</child></root>'
        root = xml_parse(original, _CFG_XML)
        result = xml_serialize(root, _CFG_XML)
        assert "child" in result
        assert "val" in result
        assert "text" in result


# ============================================================================
# bytes
# ============================================================================


class TestBytesDecode:
    """Tests for bytes_decode."""

    def test_decode_utf8(self) -> None:
        """Decode UTF-8 bytes to string."""
        assert bytes_decode(b"Hello", _CFG_BYTES) == "Hello"

    def test_decode_latin1(self) -> None:
        """Decode with explicit encoding."""
        cfg = PrimitiveConfig(name="bytes", options={"encoding": "latin-1"})
        assert bytes_decode(b"\xe9", cfg) == "\xe9"

    def test_decode_invalid_utf8(self) -> None:
        """Invalid UTF-8 raises DecodeError."""
        with pytest.raises(DecodeError, match="decode failed"):
            bytes_decode(b"\xff\xfe", _CFG_BYTES)

    def test_decode_wrong_type(self) -> None:
        """String input raises DecodeError."""
        with pytest.raises(DecodeError, match="Expected bytes"):
            bytes_decode("hello", _CFG_BYTES)  # type: ignore[arg-type]


class TestBytesEncode:
    """Tests for bytes_encode."""

    def test_encode_string(self) -> None:
        """Encode string to UTF-8 bytes."""
        assert bytes_encode("Hello", _CFG_BYTES) == b"Hello"

    def test_encode_wrong_type(self) -> None:
        """Non-string input raises EncodeError."""
        with pytest.raises(EncodeError, match="Expected str"):
            bytes_encode(42, _CFG_BYTES)  # type: ignore[arg-type]

    def test_round_trip(self) -> None:
        """Encode then decode is lossless."""
        original = "Hello with accents: cafe\u0301"
        encoded = bytes_encode(original, _CFG_BYTES)
        assert bytes_decode(encoded, _CFG_BYTES) == original


# ============================================================================
# Phase 1: new YAML options for base64, json, zlib
# ============================================================================


class TestBase64StripPrefix:
    """base64_decode strip_prefix option (SAS Viya use case)."""

    def test_strip_prefix_present(self) -> None:
        """Prefix is stripped before decode when present."""
        cfg = PrimitiveConfig(
            name="base64",
            options={"strip_prefix": "TRUE###", "strict": False},
        )
        assert base64_decode("TRUE###SGVsbG8=", cfg) == b"Hello"

    def test_strip_prefix_absent_is_noop(self) -> None:
        """No-op when input does not start with prefix (does NOT raise)."""
        cfg = PrimitiveConfig(
            name="base64",
            options={"strip_prefix": "TRUE###"},
        )
        assert base64_decode("SGVsbG8=", cfg) == b"Hello"

    def test_strip_prefix_partial_match_no_strip(self) -> None:
        """Partial prefix match is not stripped."""
        cfg = PrimitiveConfig(
            name="base64",
            options={"strip_prefix": "TRUE###", "strict": False},
        )
        # "TRUE" alone is the start but not the full "TRUE###" prefix.
        # Lenient mode strips "TRU" as non-alphabet would not, but TRUE alone
        # matches alphabet so it stays. Decoded as if no prefix.
        result = base64_decode("TRUESGVsbG8=", cfg)
        # TRUE decodes to M\x15\x04, then SGVsbG8= = "Hello"
        assert result == b"\x4d\x15\x04Hello"


class TestBase64Strict:
    """base64_decode strict option."""

    def test_strict_default_rejects_non_alphabet(self) -> None:
        """Default strict=True rejects non-alphabet chars."""
        cfg = PrimitiveConfig(name="base64")
        with pytest.raises(DecodeError, match="Invalid base64"):
            base64_decode("SGVs###bG8=", cfg)

    def test_strict_false_strips_separators(self) -> None:
        """strict=False silently strips non-alphabet chars."""
        cfg = PrimitiveConfig(name="base64", options={"strict": False})
        assert base64_decode("SGVs###bG8=", cfg) == b"Hello"

    def test_strict_false_strips_whitespace(self) -> None:
        """Lenient mode strips spaces, tabs, newlines."""
        cfg = PrimitiveConfig(name="base64", options={"strict": False})
        assert base64_decode("SGVs bG8=", cfg) == b"Hello"
        assert base64_decode("SGVs\tbG8=", cfg) == b"Hello"

    def test_empty_after_preprocessing_raises(self) -> None:
        """All-noise input becomes empty after lenient strip and raises."""
        cfg = PrimitiveConfig(name="base64", options={"strict": False})
        with pytest.raises(DecodeError, match="Empty base64 data"):
            base64_decode("###@@@", cfg)


class TestBase64EncodePrefix:
    """base64_encode prefix option."""

    def test_encode_with_prefix(self) -> None:
        """Prefix is reattached after encoding."""
        cfg = PrimitiveConfig(name="base64", options={"prefix": "TRUE###"})
        assert base64_encode(b"Hello", cfg) == "TRUE###SGVsbG8="

    def test_encode_no_prefix(self) -> None:
        """No prefix when option is absent."""
        cfg = PrimitiveConfig(name="base64")
        assert base64_encode(b"Hello", cfg) == "SGVsbG8="

    def test_round_trip_prefix_strip(self) -> None:
        """encode(prefix) + decode(strip_prefix) is lossless."""
        encode_cfg = PrimitiveConfig(name="base64", options={"prefix": "TRUE###"})
        decode_cfg = PrimitiveConfig(
            name="base64",
            options={"strip_prefix": "TRUE###", "strict": False},
        )
        original = b"Hello, World!"
        encoded = base64_encode(original, encode_cfg)
        assert encoded.startswith("TRUE###")
        assert base64_decode(encoded, decode_cfg) == original


class TestBase64SasRealBlob:
    """End-to-end check on a realistic SAS-style blob (Approach A)."""

    def test_real_sas_blob_round_trip(self) -> None:
        """Build a TRUE###-prefixed blob, decode it, re-encode it bit-perfect."""
        # Build a synthetic SAS-style blob:
        #   prefix "TRUE###" (TRUE encodes to 3-byte SAS header) + base64(zlib(json))
        envelope = {"object": {"id": "x"}, "transferableContent": {"content": "<Report/>"}}
        json_bytes = json.dumps(envelope).encode("utf-8")
        zlib_bytes = zlib.compress(json_bytes)
        synthetic_blob = "TRUE###" + b64_module.b64encode(zlib_bytes).decode("ascii")

        # Forward: strip TRUE### + lenient + zlib decompress + json parse
        decode_cfg = PrimitiveConfig(
            name="base64",
            options={"strip_prefix": "TRUE###", "strict": False},
        )
        decoded_zlib = base64_decode(synthetic_blob, decode_cfg)
        # The result is DIRECTLY a zlib stream (no SAS header bytes prefixing it)
        assert decoded_zlib[:2] == b"\x78\x9c"  # zlib magic
        decompressed = zlib.decompress(decoded_zlib)
        assert json.loads(decompressed) == envelope

        # Backward: encode with the same prefix, verify bit-perfect round trip
        encode_cfg = PrimitiveConfig(name="base64", options={"prefix": "TRUE###"})
        re_encoded = base64_encode(decoded_zlib, encode_cfg)
        assert re_encoded == synthetic_blob


class TestJsonSerializeMinify:
    """json_serialize minify option."""

    def test_minify_true(self) -> None:
        """Minified output has no spaces after , or :."""
        cfg = PrimitiveConfig(name="json", options={"minify": True})
        assert json_serialize({"a": 1, "b": 2}, cfg) == '{"a":1,"b":2}'

    def test_minify_false_default(self) -> None:
        """Default uses Python json default separators (with spaces)."""
        cfg = PrimitiveConfig(name="json")
        assert json_serialize({"a": 1, "b": 2}, cfg) == '{"a": 1, "b": 2}'


class TestJsonSerializeEnsureAscii:
    """json_serialize ensure_ascii option (default False = preserve Unicode)."""

    def test_ensure_ascii_default_false(self) -> None:
        """Default preserves Unicode chars verbatim."""
        cfg = PrimitiveConfig(name="json")
        result = json_serialize({"k": "café"}, cfg)
        assert result == '{"k": "café"}'
        assert "café" in result

    def test_ensure_ascii_true(self) -> None:
        """ensure_ascii=True escapes non-ASCII to \\uXXXX."""
        cfg = PrimitiveConfig(name="json", options={"ensure_ascii": True})
        result = json_serialize({"k": "café"}, cfg)
        assert result == r'{"k": "caf\u00e9"}'

    def test_minify_and_ensure_ascii_false_together(self) -> None:
        """minify + Unicode preservation work together (the SAS use case)."""
        cfg = PrimitiveConfig(
            name="json",
            options={"minify": True, "ensure_ascii": False},
        )
        result = json_serialize({"k": "café", "n": 1}, cfg)
        assert result == '{"k":"café","n":1}'


class TestZlibCompressLevel:
    """zlib_compress level option."""

    def test_level_default_minus_one(self) -> None:
        """level=-1 uses Python default level (typically 6)."""
        cfg = PrimitiveConfig(name="zlib", options={"level": -1})
        data = b"Hello World " * 100
        result = zlib_compress(data, cfg)
        assert zlib.decompress(result) == data

    def test_level_9_max_compression(self) -> None:
        """level=9 produces a smaller output than level=1 for compressible data."""
        compressible = b"AAAA" * 1000
        cfg_low = PrimitiveConfig(name="zlib", options={"level": 1})
        cfg_high = PrimitiveConfig(name="zlib", options={"level": 9})
        small = zlib_compress(compressible, cfg_high)
        big = zlib_compress(compressible, cfg_low)
        assert len(small) <= len(big)
        assert zlib.decompress(small) == compressible

    def test_level_0_no_compression(self) -> None:
        """level=0 stores data uncompressed (still in zlib container)."""
        cfg = PrimitiveConfig(name="zlib", options={"level": 0})
        data = b"plain text"
        result = zlib_compress(data, cfg)
        assert zlib.decompress(result) == data
        # Uncompressed wraps with minimal overhead, output is roughly same size
        assert len(result) >= len(data)

    def test_level_round_trip(self) -> None:
        """compress(level=N) + decompress is lossless for any valid level."""
        data = b"Lossless integrity check " * 50
        for level in (-1, 0, 1, 6, 9):
            cfg = PrimitiveConfig(name="zlib", options={"level": level})
            assert zlib.decompress(zlib_compress(data, cfg)) == data


# ============================================================================
# H5: coverage gaps - primitives.py to 95%
# ============================================================================


class TestPrimitivesCoverageGaps:
    """Tests covering uncovered branches in primitives.py."""

    def test_zlib_compress_with_valid_prepend_hex(self) -> None:
        """Valid prepend_bytes hex is prepended to compressed output."""
        cfg = PrimitiveConfig(name="zlib", options={"prepend_bytes": "4d1504"})
        result = zlib_compress(b"hello", cfg)
        assert result[:3] == b"\x4d\x15\x04"
        assert zlib.decompress(result[3:]) == b"hello"

    def test_zlib_compress_non_bytes_raises(self) -> None:
        """Non-bytes input to zlib_compress raises CompressError."""
        cfg = PrimitiveConfig(name="zlib")
        with pytest.raises(CompressError, match="Expected bytes"):
            zlib_compress("string", cfg)  # type: ignore[arg-type]

    def test_xml_parse_external_entity_rejected(self) -> None:
        """External entity in DOCTYPE is rejected by defusedxml (XXE protection)."""
        malicious = '<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><root>&xxe;</root>'
        with pytest.raises(ParseError, match="Invalid XML"):
            xml_parse(malicious, PrimitiveConfig(name="xml"))

    def test_xml_parse_billion_laughs_rejected(self) -> None:
        """Recursive entity expansion (billion laughs) is rejected by defusedxml."""
        malicious = (
            "<!DOCTYPE lolz ["
            '<!ENTITY lol "lol">'
            '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
            "]><lolz>&lol2;</lolz>"
        )
        with pytest.raises(ParseError, match="Invalid XML"):
            xml_parse(malicious, PrimitiveConfig(name="xml"))

    def test_xml_serialize_bad_encoding_raises(self) -> None:
        """xml_serialize with invalid encoding raises SerializeError."""
        from xml.etree.ElementTree import Element

        root = Element("test")
        cfg = PrimitiveConfig(name="xml", options={"encoding": "nonexistent"})
        with pytest.raises(SerializeError, match="serialization failed"):
            xml_serialize(root, cfg)


# ============================================================================
# split (forward-only string extractor)
# ============================================================================


class TestSplitExtract:
    """Tests for split_extract."""

    def test_index_last_segment(self) -> None:
        """index=-1 returns the last non-empty segment (driving use case)."""
        cfg = PrimitiveConfig(name="split", options={"sep": "/", "index": -1})
        assert split_extract("/reports/reports/xxx", cfg) == "xxx"

    def test_index_first_segment(self) -> None:
        """index=0 returns the first non-empty segment."""
        cfg = PrimitiveConfig(name="split", options={"sep": "/", "index": 0})
        assert split_extract("/reports/reports/xxx", cfg) == "reports"

    def test_no_index_returns_list(self) -> None:
        """Omitting index returns the full list of non-empty segments."""
        cfg = PrimitiveConfig(name="split", options={"sep": "/"})
        assert split_extract("/reports/reports/xxx", cfg) == ["reports", "reports", "xxx"]

    def test_keep_empty_true_list(self) -> None:
        """keep_empty=True preserves empty segments (matches str.split)."""
        cfg = PrimitiveConfig(name="split", options={"sep": "/", "keep_empty": True})
        assert split_extract("/a/b", cfg) == ["", "a", "b"]

    def test_keep_empty_true_index(self) -> None:
        """keep_empty=True with index reaches the empty leading segment."""
        cfg = PrimitiveConfig(name="split", options={"sep": "/", "keep_empty": True, "index": 0})
        assert split_extract("/a/b", cfg) == ""

    def test_sep_absent_single_segment(self) -> None:
        """Separator absent from input yields a single-segment list."""
        cfg = PrimitiveConfig(name="split", options={"sep": "/"})
        assert split_extract("noslash", cfg) == ["noslash"]

    def test_sep_absent_index_zero(self) -> None:
        """Separator absent, index=0 returns the whole string."""
        cfg = PrimitiveConfig(name="split", options={"sep": "/", "index": 0})
        assert split_extract("noslash", cfg) == "noslash"

    def test_maxsplit(self) -> None:
        """maxsplit limits the number of splits."""
        cfg = PrimitiveConfig(name="split", options={"sep": "/", "maxsplit": 1})
        assert split_extract("a/b/c/d", cfg) == ["a", "b/c/d"]

    def test_negative_index_middle(self) -> None:
        """Negative index addresses segments from the end."""
        cfg = PrimitiveConfig(name="split", options={"sep": "/", "index": -2})
        assert split_extract("a/b/c", cfg) == "b"

    def test_multichar_separator(self) -> None:
        """A multi-character separator is treated literally."""
        cfg = PrimitiveConfig(name="split", options={"sep": "::", "index": -1})
        assert split_extract("a::b::c", cfg) == "c"

    def test_empty_input_no_index(self) -> None:
        """Empty input without index returns an empty list."""
        cfg = PrimitiveConfig(name="split", options={"sep": "/"})
        assert split_extract("", cfg) == []

    def test_empty_input_with_index_raises(self) -> None:
        """Empty input with index raises ParseError (out of range)."""
        cfg = PrimitiveConfig(name="split", options={"sep": "/", "index": 0})
        with pytest.raises(ParseError, match="out of range"):
            split_extract("", cfg)

    def test_index_out_of_range_raises(self) -> None:
        """Index beyond the segment count raises ParseError."""
        cfg = PrimitiveConfig(name="split", options={"sep": "/", "index": 5})
        with pytest.raises(ParseError, match="out of range"):
            split_extract("a/b", cfg)

    def test_wrong_type_raises(self) -> None:
        """Non-string input raises ParseError."""
        cfg = PrimitiveConfig(name="split", options={"sep": "/"})
        with pytest.raises(ParseError, match="Expected str"):
            split_extract(42, cfg)  # type: ignore[arg-type]

    def test_null_byte_rejected(self, caplog: pytest.LogCaptureFixture) -> None:
        """Null byte in input raises ParseError with a [SECURITY] log."""
        cfg = PrimitiveConfig(name="split", options={"sep": "/"})
        with caplog.at_level(logging.WARNING, logger="kstlib.transform.primitives"):
            with pytest.raises(ParseError, match="null byte"):
                split_extract("a/b\x00c", cfg)
        assert "[SECURITY]" in caplog.text

    def test_oversized_input_rejected(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        """Input exceeding the size cap raises ParseError with a [SECURITY] log."""
        monkeypatch.setattr("kstlib.transform.primitives.MAX_INPUT_SIZE", 8)
        cfg = PrimitiveConfig(name="split", options={"sep": "/"})
        with caplog.at_level(logging.WARNING, logger="kstlib.transform.primitives"):
            with pytest.raises(ParseError, match="exceeds limit"):
                split_extract("123456789", cfg)
        assert "[SECURITY]" in caplog.text


class TestTrTranslate:
    """Tests for tr_translate (character-level translate/delete)."""

    def test_delete_chars(self) -> None:
        """delete removes every listed character."""
        cfg = PrimitiveConfig(name="tr", options={"delete": "\n"})
        assert tr_translate("a\nb\n", cfg) == "ab"

    def test_delete_multiple_chars(self) -> None:
        """delete removes all characters in the set."""
        cfg = PrimitiveConfig(name="tr", options={"delete": "\r\n\t"})
        assert tr_translate("a\rb\nc\td", cfg) == "abcd"

    def test_delete_absent_chars_noop(self) -> None:
        """delete leaves the string unchanged when no listed char is present."""
        cfg = PrimitiveConfig(name="tr", options={"delete": "z"})
        assert tr_translate("abc", cfg) == "abc"

    def test_map_translates(self) -> None:
        """map translates each character via the table."""
        cfg = PrimitiveConfig(name="tr", options={"map": {"a": "b"}})
        assert tr_translate("aaa", cfg) == "bbb"

    def test_map_multiple_entries(self) -> None:
        """map applies a multi-entry single-character table."""
        cfg = PrimitiveConfig(name="tr", options={"map": {"a": "x", "b": "y"}})
        assert tr_translate("abab", cfg) == "xyxy"

    def test_wrong_type_raises(self) -> None:
        """Non-string input raises ParseError."""
        cfg = PrimitiveConfig(name="tr", options={"delete": "\n"})
        with pytest.raises(ParseError, match="Expected str"):
            tr_translate(42, cfg)  # type: ignore[arg-type]

    def test_null_byte_rejected(self, caplog: pytest.LogCaptureFixture) -> None:
        """Null byte in input raises ParseError with a [SECURITY] log."""
        cfg = PrimitiveConfig(name="tr", options={"delete": "x"})
        with caplog.at_level(logging.WARNING, logger="kstlib.transform.primitives"):
            with pytest.raises(ParseError, match="null byte"):
                tr_translate("a\x00b", cfg)
        assert "[SECURITY]" in caplog.text

    def test_oversized_input_rejected(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        """Input exceeding the size cap raises ParseError with a [SECURITY] log."""
        monkeypatch.setattr("kstlib.transform.primitives.MAX_INPUT_SIZE", 8)
        cfg = PrimitiveConfig(name="tr", options={"delete": "x"})
        with caplog.at_level(logging.WARNING, logger="kstlib.transform.primitives"):
            with pytest.raises(ParseError, match="exceeds limit"):
                tr_translate("123456789", cfg)
        assert "[SECURITY]" in caplog.text


class TestRemovePrefix:
    """Tests for remove_prefix (strip a known leading affix)."""

    def test_strips_known_prefix(self) -> None:
        """A leading prefix present in the input is removed (driving use case)."""
        cfg = PrimitiveConfig(name="removeprefix", options={"prefix": "reports/"})
        assert remove_prefix("reports/xxx", cfg) == "xxx"

    def test_prefix_absent_unchanged(self) -> None:
        """Input not starting with the prefix is returned unchanged (str.removeprefix)."""
        cfg = PrimitiveConfig(name="removeprefix", options={"prefix": "reports/"})
        assert remove_prefix("other/xxx", cfg) == "other/xxx"

    def test_only_leading_occurrence_removed(self) -> None:
        """Only the single leading occurrence is stripped, not later ones."""
        cfg = PrimitiveConfig(name="removeprefix", options={"prefix": "reports/"})
        assert remove_prefix("reports/reports/xxx", cfg) == "reports/xxx"

    def test_empty_prefix_noop(self) -> None:
        """An empty prefix is a no-op and leaves the string unchanged."""
        cfg = PrimitiveConfig(name="removeprefix", options={"prefix": ""})
        assert remove_prefix("abc", cfg) == "abc"

    def test_wrong_type_raises(self) -> None:
        """Non-string input raises ParseError."""
        cfg = PrimitiveConfig(name="removeprefix", options={"prefix": "x"})
        with pytest.raises(ParseError, match="Expected str"):
            remove_prefix(42, cfg)  # type: ignore[arg-type]

    def test_null_byte_rejected(self, caplog: pytest.LogCaptureFixture) -> None:
        """Null byte in input raises ParseError with a [SECURITY] log."""
        cfg = PrimitiveConfig(name="removeprefix", options={"prefix": "x"})
        with caplog.at_level(logging.WARNING, logger="kstlib.transform.primitives"):
            with pytest.raises(ParseError, match="null byte"):
                remove_prefix("a\x00b", cfg)
        assert "[SECURITY]" in caplog.text

    def test_oversized_input_rejected(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        """Input exceeding the size cap raises ParseError with a [SECURITY] log."""
        monkeypatch.setattr("kstlib.transform.primitives.MAX_INPUT_SIZE", 8)
        cfg = PrimitiveConfig(name="removeprefix", options={"prefix": "x"})
        with caplog.at_level(logging.WARNING, logger="kstlib.transform.primitives"):
            with pytest.raises(ParseError, match="exceeds limit"):
                remove_prefix("123456789", cfg)
        assert "[SECURITY]" in caplog.text


class TestRemoveSuffix:
    """Tests for remove_suffix (strip a known trailing affix)."""

    def test_strips_known_suffix(self) -> None:
        """A trailing suffix present in the input is removed (driving use case)."""
        cfg = PrimitiveConfig(name="removesuffix", options={"suffix": ".json"})
        assert remove_suffix("data.json", cfg) == "data"

    def test_suffix_absent_unchanged(self) -> None:
        """Input not ending with the suffix is returned unchanged (str.removesuffix)."""
        cfg = PrimitiveConfig(name="removesuffix", options={"suffix": ".json"})
        assert remove_suffix("data.yml", cfg) == "data.yml"

    def test_only_trailing_occurrence_removed(self) -> None:
        """Only the single trailing occurrence is stripped, not earlier ones."""
        cfg = PrimitiveConfig(name="removesuffix", options={"suffix": ".json"})
        assert remove_suffix("a.json.json", cfg) == "a.json"

    def test_empty_suffix_noop(self) -> None:
        """An empty suffix is a no-op and leaves the string unchanged."""
        cfg = PrimitiveConfig(name="removesuffix", options={"suffix": ""})
        assert remove_suffix("abc", cfg) == "abc"

    def test_wrong_type_raises(self) -> None:
        """Non-string input raises ParseError."""
        cfg = PrimitiveConfig(name="removesuffix", options={"suffix": "x"})
        with pytest.raises(ParseError, match="Expected str"):
            remove_suffix(42, cfg)  # type: ignore[arg-type]

    def test_null_byte_rejected(self, caplog: pytest.LogCaptureFixture) -> None:
        """Null byte in input raises ParseError with a [SECURITY] log."""
        cfg = PrimitiveConfig(name="removesuffix", options={"suffix": "x"})
        with caplog.at_level(logging.WARNING, logger="kstlib.transform.primitives"):
            with pytest.raises(ParseError, match="null byte"):
                remove_suffix("a\x00b", cfg)
        assert "[SECURITY]" in caplog.text

    def test_oversized_input_rejected(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        """Input exceeding the size cap raises ParseError with a [SECURITY] log."""
        monkeypatch.setattr("kstlib.transform.primitives.MAX_INPUT_SIZE", 8)
        cfg = PrimitiveConfig(name="removesuffix", options={"suffix": "x"})
        with caplog.at_level(logging.WARNING, logger="kstlib.transform.primitives"):
            with pytest.raises(ParseError, match="exceeds limit"):
                remove_suffix("123456789", cfg)
        assert "[SECURITY]" in caplog.text
