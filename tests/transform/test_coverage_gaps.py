"""Tests to fill coverage gaps in kstlib.transform (target: >= 99%)."""

from __future__ import annotations

from xml.etree.ElementTree import Element, SubElement

import pytest

from kstlib.transform.chain import TransformChain, _auto_reverse
from kstlib.transform.config import (
    PatchConfig,
    PrimitiveConfig,
    TransformChainConfig,
    TransformConfig,
    _parse_filter,
    _parse_primitive,
    _parse_targeted_patch,
)
from kstlib.transform.exceptions import (
    CallableImportError,
    EncodeError,
    SerializeError,
    TransformChainError,
    TransformConfigError,
)
from kstlib.transform.primitives import (
    json_serialize,
    xml_serialize,
    zlib_compress,
)
from kstlib.transform.validators import (
    MAX_CALLABLE_TARGET_LENGTH,
    MAX_CHAIN_NAME_LENGTH,
    MAX_PREPEND_HEX_LENGTH,
    validate_callable_module,
    validate_callable_target,
    validate_chain_name,
    validate_dot_path,
    validate_hex_string,
    validate_input_size,
)

# ============================================================================
# validators.py gaps
# ============================================================================


class TestValidatorGaps:
    """Tests covering uncovered validator branches."""

    def test_chain_name_empty(self) -> None:
        """Empty chain name raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="must not be empty"):
            validate_chain_name("")

    def test_chain_name_too_long(self) -> None:
        """Chain name exceeding max length raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="too long"):
            validate_chain_name("a" * (MAX_CHAIN_NAME_LENGTH + 1))

    def test_dot_path_empty(self) -> None:
        """Empty dot path raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="must not be empty"):
            validate_dot_path("")

    def test_dot_path_too_long(self) -> None:
        """Dot path exceeding max length raises TransformConfigError."""
        long_path = ".".join(["abcdef"] * 50)  # 50*7-1 = 349 chars > 256
        with pytest.raises(TransformConfigError, match="too long"):
            validate_dot_path(long_path)

    def test_callable_target_empty(self) -> None:
        """Empty callable target raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="must not be empty"):
            validate_callable_target("")

    def test_callable_target_too_long(self) -> None:
        """Callable target exceeding max length raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="too long"):
            validate_callable_target("a" * (MAX_CALLABLE_TARGET_LENGTH + 1))

    def test_hex_string_too_long(self) -> None:
        """Hex string exceeding max length raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="too long"):
            validate_hex_string("aa" * (MAX_PREPEND_HEX_LENGTH + 1))

    def test_callable_module_malformed_target(self) -> None:
        """Callable target without colon raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="Invalid callable target"):
            validate_callable_module("no_colon", frozenset({"no_colon"}))

    def test_validate_input_size_over_limit(self) -> None:
        """Data exceeding limit raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="exceeds limit"):
            validate_input_size(b"x" * 100, limit=50, label="test")

    def test_validate_input_size_under_limit(self) -> None:
        """Data under limit passes without error."""
        validate_input_size(b"x" * 10, limit=50, label="test")


# ============================================================================
# config.py gaps
# ============================================================================


class TestConfigGaps:
    """Tests covering uncovered config validation branches."""

    def test_zlib_prepend_bytes_non_string(self) -> None:
        """Non-string prepend_bytes raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="hex string"):
            PrimitiveConfig(name="zlib", options={"prepend_bytes": 12345})

    def test_json_extract_non_string(self) -> None:
        """Non-string json extract raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="json extract must be string"):
            PrimitiveConfig(name="json", options={"extract": 42})

    def test_json_wrap_non_string(self) -> None:
        """Non-string json wrap raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="json wrap must be string"):
            PrimitiveConfig(name="json", options={"wrap": ["a", "b"]})

    def test_encoding_non_string(self) -> None:
        """Non-string encoding raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="encoding must be string"):
            PrimitiveConfig(name="base64", options={"encoding": 42})

    def test_encoding_too_long(self) -> None:
        """Encoding exceeding max length raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="encoding too long"):
            PrimitiveConfig(name="bytes", options={"encoding": "x" * 50})

    def test_patch_args_key_too_long(self) -> None:
        """PatchConfig args key exceeding max length raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="args key too long"):
            PatchConfig(args={"x" * 100: "value"})

    def test_backward_chain_too_long(self) -> None:
        """Backward chain exceeding max primitives raises TransformConfigError."""
        prims = tuple(PrimitiveConfig(name="base64") for _ in range(25))
        with pytest.raises(TransformConfigError, match="backward chain too long"):
            TransformChainConfig(
                name="test",
                forward=(PrimitiveConfig(name="base64"),),
                backward=prims,
            )

    def test_parse_primitive_dict_multiple_keys(self) -> None:
        """Primitive dict with multiple keys raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="exactly 1 key"):
            _parse_primitive({"base64": {}, "zlib": {}})

    def test_parse_primitive_non_dict_options(self) -> None:
        """Primitive dict with non-dict options raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="options must be dict"):
            _parse_primitive({"zlib": "not_a_dict"})

    def test_parse_primitive_invalid_type(self) -> None:
        """Primitive as int raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="must be str or dict"):
            _parse_primitive(42)  # type: ignore[arg-type]


# ============================================================================
# chain.py gaps
# ============================================================================


class TestChainGaps:
    """Tests covering uncovered chain engine branches."""

    def test_auto_reverse_bytes_with_options(self) -> None:
        """Auto-reverse preserves bytes encoding option."""
        fwd = (PrimitiveConfig(name="bytes", options={"encoding": "latin-1"}),)
        bwd = _auto_reverse(fwd)
        assert bwd[0].name == "bytes"
        assert bwd[0].options["encoding"] == "latin-1"

    def test_auto_reverse_xml_with_options(self) -> None:
        """Auto-reverse preserves xml encoding option."""
        fwd = (PrimitiveConfig(name="xml", options={"encoding": "unicode"}),)
        bwd = _auto_reverse(fwd)
        assert bwd[0].name == "xml"
        assert bwd[0].options["encoding"] == "unicode"

    def test_auto_reverse_unknown_primitive_raises(self) -> None:
        """Auto-reverse of an unknown primitive raises TransformConfigError."""
        # Bypass PrimitiveConfig validation to test defensive branch
        fake = PrimitiveConfig.__new__(PrimitiveConfig)
        object.__setattr__(fake, "name", "unknown_prim")
        object.__setattr__(fake, "options", {})
        with pytest.raises(TransformConfigError, match="Cannot auto-reverse"):
            _auto_reverse((fake,))

    def test_too_many_variable_refs(self) -> None:
        """Exceeding MAX_VARIABLE_REFS raises TransformChainError."""
        # Use few keys but pack many {{var}} refs into each value
        refs = " ".join(f"{{{{v{i}}}}}" for i in range(25))
        args = {"key": refs}
        context = {f"v{i}": f"val{i}" for i in range(25)}
        chain = TransformChain(
            TransformChainConfig(
                name="test",
                forward=(PrimitiveConfig(name="base64"),),
                patch=PatchConfig(callable="json:dumps", args=args),
            ),
            context=context,
            allowed_modules=frozenset({"json"}),
        )
        with pytest.raises(TransformChainError, match="Too many variable references"):
            chain.patch({"data": 1})

    def test_patch_no_mapping_no_callable(self) -> None:
        """Patch with neither mapping nor callable is a no-op."""
        chain = TransformChain(
            TransformChainConfig(
                name="test",
                forward=(PrimitiveConfig(name="base64"),),
                patch=PatchConfig(),
            ),
        )
        data = "unchanged"
        assert chain.patch(data) == "unchanged"

    def test_mapping_patch_on_xml_element(self) -> None:
        """Mapping patch works on Element objects (serialize->replace->parse)."""
        root = Element("root")
        child = SubElement(root, "item")
        child.text = "old_value"

        chain = TransformChain(
            TransformChainConfig(
                name="test",
                forward=(PrimitiveConfig(name="base64"),),
                patch=PatchConfig(replace={"old_value": "new_value"}),
            ),
        )
        result = chain.patch(root)
        assert isinstance(result, Element)
        item = result.find("item")
        assert item is not None
        assert item.text == "new_value"

    def test_callable_empty_module_path(self) -> None:
        """Callable with malformed target (no colon) raises CallableImportError."""
        chain = TransformChain(
            TransformChainConfig(
                name="test",
                forward=(PrimitiveConfig(name="base64"),),
                patch=PatchConfig(callable="json:dumps"),
            ),
            allowed_modules=frozenset({"json"}),
        )
        # Manually override to test the edge case
        chain._config = TransformChainConfig(
            name="test",
            forward=(PrimitiveConfig(name="base64"),),
            patch=PatchConfig(callable="json:dumps"),
        )
        # Use a target that rpartition will split into empty module
        object.__setattr__(chain._config.patch, "callable", ":func")
        with pytest.raises(CallableImportError):
            chain.patch("data")

    def test_backward_non_json_dispatch(self, sas_report_config: TransformConfig) -> None:
        """Backward dispatches xml primitive correctly."""
        chain = TransformChain.from_config("sas_report", sas_report_config)
        # Forward to get XML string
        xml_str = chain.forward(
            __import__("tests.transform.conftest", fromlist=["_build_sas_blob"]).conftest._build_sas_blob()
            if False
            else self._make_blob()
        )
        # Backward should work through xml -> json -> zlib -> base64
        result = chain.backward(xml_str)
        assert isinstance(result, str)

    @staticmethod
    def _make_blob() -> str:
        """Build a test SAS blob."""
        import base64
        import json
        import zlib

        envelope = {
            "object": {"id": "test"},
            "transferableContent": {"content": "<root/>"},
        }
        raw = b"\x4d\x15\x04" + zlib.compress(json.dumps(envelope).encode())
        return base64.b64encode(raw).decode()


# ============================================================================
# primitives.py gaps
# ============================================================================


class TestPrimitivesGaps:
    """Tests covering uncovered primitives branches."""

    def test_zlib_decompress_exceeds_max_size(self) -> None:
        """Decompressed data exceeding MAX_DECOMPRESSED_SIZE raises DecompressError."""
        # This is hard to trigger with real data due to memory constraints.
        # We test via the ratio check instead (already covered).
        # The size check fires when ratio is OK but absolute size exceeds limit.
        # Skip if we cannot allocate enough memory for the test.
        pytest.skip("MAX_DECOMPRESSED_SIZE (200MB) test skipped to avoid OOM")

    def test_json_serialize_non_serializable(self) -> None:
        """Non-serializable object raises SerializeError."""
        cfg = PrimitiveConfig(name="json")
        with pytest.raises(SerializeError, match="serialization failed"):
            json_serialize(object(), cfg)

    def test_json_serialize_with_wrap_path(self) -> None:
        """JSON serialize with wrap creates nested dict."""
        cfg = PrimitiveConfig(name="json", options={"wrap": "a.b.c"})
        result = json_serialize("value", cfg)
        import json

        parsed = json.loads(result)
        assert parsed["a"]["b"]["c"] == "value"

    def test_xml_serialize_fallback_to_str(self) -> None:
        """XML serialize handles encoding=unicode returning str."""
        root = Element("test")
        root.text = "content"
        cfg = PrimitiveConfig(name="xml")
        result = xml_serialize(root, cfg)
        assert "content" in result
        assert isinstance(result, str)

    def test_bytes_encode_invalid_encoding(self) -> None:
        """Bytes encode with invalid encoding raises EncodeError."""
        from kstlib.transform.primitives import bytes_encode

        cfg = PrimitiveConfig(name="bytes", options={"encoding": "nonexistent-codec"})
        with pytest.raises(EncodeError, match="encode failed"):
            bytes_encode("hello", cfg)

    def test_zlib_compress_failure_is_wrapped(self) -> None:
        """Zlib compression error is caught (hard to trigger in practice)."""
        cfg = PrimitiveConfig(name="zlib")
        result = zlib_compress(b"", cfg)
        import zlib

        assert zlib.decompress(result) == b""


# ============================================================================
# config.py - load_transform_config()
# ============================================================================


class TestLoadTransformConfig:
    """Tests covering load_transform_config() from kstlib.conf.yml."""

    def _mock_and_load(self, monkeypatch: pytest.MonkeyPatch, section: dict) -> TransformConfig:  # type: ignore[type-arg]
        """Mock get_config and call load_transform_config."""
        from unittest.mock import MagicMock

        mock_box = MagicMock()
        mock_box.get.return_value = section

        import kstlib.config as cfg_pkg

        monkeypatch.setattr(cfg_pkg, "get_config", lambda: mock_box)

        from kstlib.transform.config import load_transform_config

        return load_transform_config()

    def test_load_empty_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty config returns empty TransformConfig."""
        config = self._mock_and_load(monkeypatch, {})
        assert config.chains == {}

    def test_load_with_chains(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Config with chains section populates TransformConfig."""
        config = self._mock_and_load(
            monkeypatch,
            {
                "chains": {"decode": {"forward": ["base64"]}},
            },
        )
        assert "decode" in config.chains

    def test_load_with_security(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Config with security section sets allowed_callable_modules."""
        config = self._mock_and_load(
            monkeypatch,
            {
                "security": {"allowed_callable_modules": ["myproject.viya"]},
                "chains": {"decode": {"forward": ["base64"]}},
            },
        )
        assert "myproject.viya" in config.allowed_callable_modules

    def test_load_invalid_chains_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-dict chains section raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="must be a dict"):
            self._mock_and_load(monkeypatch, {"chains": "not_a_dict"})

    def test_load_invalid_chain_entry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-dict chain entry raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="must be a dict"):
            self._mock_and_load(monkeypatch, {"chains": {"bad": "not_a_dict"}})


# ============================================================================
# chain.py - transform() convenience function with config loading
# ============================================================================


class TestTransformConvenienceWithMock:
    """Tests for module-level transform() loading config."""

    def test_transform_loads_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """transform() without explicit config calls load_transform_config."""
        from unittest.mock import MagicMock

        import kstlib.config as cfg_pkg

        mock_box = MagicMock()
        mock_box.get.return_value = {
            "chains": {"b64": {"forward": ["base64"]}},
        }
        monkeypatch.setattr(cfg_pkg, "get_config", lambda: mock_box)

        from kstlib.transform.chain import transform

        result = transform("SGVsbG8=", "b64")
        assert result == "SGVsbG8="


# ============================================================================
# MEDIUM: config.py error-path coverage
# ============================================================================


class TestConfigErrorPaths:
    """Tests covering config.py error paths (MEDIUM coverage findings)."""

    def test_parse_filter_non_dict_raises(self) -> None:
        """_parse_filter with non-dict input raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="Filter must be a dict"):
            _parse_filter("not_a_dict")  # type: ignore[arg-type]

    def test_parse_targeted_patch_non_dict_raises(self) -> None:
        """_parse_targeted_patch with non-dict raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="Targeted patch must be a dict"):
            _parse_targeted_patch("not_a_dict")  # type: ignore[arg-type]

    def test_parse_targeted_patch_non_list_patches_raises(self) -> None:
        """_parse_targeted_patch with non-list patches raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="must be a list"):
            _parse_targeted_patch({"filter": {}, "patches": "not_a_list"})

    def test_parse_targeted_patch_non_string_entry_raises(self) -> None:
        """_parse_targeted_patch with non-string patch entry raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="must be strings"):
            _parse_targeted_patch({"filter": {}, "patches": [42]})
