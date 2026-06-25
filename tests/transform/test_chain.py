"""Tests for kstlib.transform.chain (TransformChain engine)."""

from __future__ import annotations

import base64
import json
import zlib
from typing import Any

import pytest

from kstlib.transform.chain import (
    PROTECTED_OUTER_PATHS,
    TransformChain,
    _MAX_WALK_DEPTH,
    _auto_reverse,
    _matches_filter,
    replace_outer_uris,
    transform,
)
from kstlib.transform.config import (
    ComposedPatchConfig,
    FilterConfig,
    PatchConfig,
    PrimitiveConfig,
    TargetedPatchConfig,
    TransformChainConfig,
    TransformConfig,
)
from kstlib.transform.exceptions import (
    CallableError,
    CallableImportError,
    PatchError,
    TransformChainError,
    TransformConfigError,
)

# ============================================================================
# Auto-reverse
# ============================================================================


class TestAutoReverse:
    """Tests for _auto_reverse."""

    def test_base64_reverse(self) -> None:
        """base64 reverses to base64."""
        fwd = (PrimitiveConfig(name="base64"),)
        bwd = _auto_reverse(fwd)
        assert len(bwd) == 1
        assert bwd[0].name == "base64"

    def test_json_extract_reverses_to_wrap(self) -> None:
        """json with extract reverses to json with wrap."""
        fwd = (PrimitiveConfig(name="json", options={"extract": "a.b"}),)
        bwd = _auto_reverse(fwd)
        assert bwd[0].options.get("wrap") == "a.b"

    def test_zlib_with_skip_raises(self) -> None:
        """zlib with skip_bytes cannot be auto-reversed."""
        fwd = (PrimitiveConfig(name="zlib", options={"skip_bytes": 3}),)
        with pytest.raises(TransformConfigError, match="skip_bytes requires explicit backward"):
            _auto_reverse(fwd)

    def test_zlib_without_skip_reverses(self) -> None:
        """zlib without skip_bytes reverses to plain zlib."""
        fwd = (PrimitiveConfig(name="zlib"),)
        bwd = _auto_reverse(fwd)
        assert bwd[0].name == "zlib"

    def test_order_reversed(self) -> None:
        """Multi-primitive chain is reversed in order."""
        fwd = (
            PrimitiveConfig(name="base64"),
            PrimitiveConfig(name="zlib"),
            PrimitiveConfig(name="json"),
        )
        bwd = _auto_reverse(fwd)
        assert [p.name for p in bwd] == ["json", "zlib", "base64"]


# ============================================================================
# Forward / Backward
# ============================================================================


class TestForwardBackward:
    """Tests for forward and backward execution."""

    def test_single_base64_forward(self) -> None:
        """Single base64 forward decodes to bytes."""
        chain = TransformChain(
            TransformChainConfig(
                name="b64",
                forward=(PrimitiveConfig(name="base64"),),
            )
        )
        assert chain.forward("SGVsbG8=") == b"Hello"

    def test_single_base64_backward(self) -> None:
        """Single base64 backward encodes to string."""
        chain = TransformChain(
            TransformChainConfig(
                name="b64",
                forward=(PrimitiveConfig(name="base64"),),
            )
        )
        assert chain.backward(b"Hello") == "SGVsbG8="

    def test_multi_primitive_forward(self) -> None:
        """Multi-primitive chain: base64 -> zlib -> json."""
        payload = json.dumps({"key": "value"}).encode()
        compressed = zlib.compress(payload)
        b64 = base64.b64encode(compressed).decode()

        chain = TransformChain(
            TransformChainConfig(
                name="multi",
                forward=(
                    PrimitiveConfig(name="base64"),
                    PrimitiveConfig(name="zlib"),
                    PrimitiveConfig(name="json"),
                ),
            )
        )
        # chain.forward handles json specially: stores envelope, returns value
        result = chain.forward(b64)
        assert result == {"key": "value"}

    def test_sas_report_forward(self, sas_report_blob: str, sas_report_config: TransformConfig) -> None:
        """Full SAS report chain: b64 -> zlib(skip=3) -> json(extract) -> XML string."""
        chain = TransformChain.from_config("sas_report", sas_report_config)
        result = chain.forward(sas_report_blob)
        # Result should be the extracted transferableContent.content (XML string)
        assert isinstance(result, str)
        assert "SASReport" in result
        assert "CasResource" in result

    def test_sas_report_backward(self, sas_report_blob: str, sas_report_config: TransformConfig) -> None:
        """Full SAS report backward re-encodes to base64 with header."""
        chain = TransformChain.from_config("sas_report", sas_report_config)
        decoded = chain.forward(sas_report_blob)
        re_encoded = chain.backward(decoded)
        assert isinstance(re_encoded, str)
        # Verify it's valid base64
        raw = base64.b64decode(re_encoded)
        # Verify SAS header preserved
        assert raw[:3] == b"\x4d\x15\x04"
        # Verify decompressible
        decompressed = zlib.decompress(raw[3:])
        envelope = json.loads(decompressed)
        assert "transferableContent" in envelope


class TestFromConfig:
    """Tests for TransformChain.from_config."""

    def test_preset_inheritance(self, sas_report_config: TransformConfig) -> None:
        """Preset chain inherits forward/backward from parent."""
        chain = TransformChain.from_config("patch_test", sas_report_config)
        # patch_test uses sas_report as preset
        assert chain._config.forward == sas_report_config.chains["sas_report"].forward

    def test_unknown_chain_raises(self, minimal_config: TransformConfig) -> None:
        """Unknown chain name raises TransformChainError."""
        with pytest.raises(TransformChainError, match="not found"):
            TransformChain.from_config("nonexistent", minimal_config)


# ============================================================================
# Patch
# ============================================================================


class TestMappingPatch:
    """Tests for mapping-based patching."""

    def test_string_mapping(self) -> None:
        """Simple string replacement mapping."""
        chain = TransformChain(
            TransformChainConfig(
                name="test",
                forward=(PrimitiveConfig(name="base64"),),
                patch=PatchConfig(replace={"old": "new"}),
            )
        )
        result = chain.patch("this is old text with old values")
        assert result == "this is new text with new values"

    def test_url_mapping(self) -> None:
        """URL hostname replacement in XML-like string."""
        chain = TransformChain(
            TransformChainConfig(
                name="test",
                forward=(PrimitiveConfig(name="base64"),),
                patch=PatchConfig(
                    replace={
                        "https://old-host.example.com/": "https://new-host.example.com/",
                    }
                ),
            )
        )
        data = '<WebContent url="https://old-host.example.com/SASJobExecution"/>'
        result = chain.patch(data)
        assert "new-host.example.com" in result
        assert "old-host.example.com" not in result

    def test_caslib_mapping(self) -> None:
        """CAS library replacement in XML string."""
        chain = TransformChain(
            TransformChainConfig(
                name="test",
                forward=(PrimitiveConfig(name="base64"),),
                patch=PatchConfig(replace={'library="CASUSER"': 'library="PROD_LIB"'}),
            )
        )
        data = '<CasResource server="cas" library="CASUSER" table="T1"/>'
        result = chain.patch(data)
        assert 'library="PROD_LIB"' in result

    def test_mapping_no_match(self) -> None:
        """Mapping with no matches returns data unchanged."""
        chain = TransformChain(
            TransformChainConfig(
                name="test",
                forward=(PrimitiveConfig(name="base64"),),
                patch=PatchConfig(replace={"nonexistent": "value"}),
            )
        )
        assert chain.patch("original") == "original"

    def test_mapping_on_non_string_raises(self) -> None:
        """Mapping on non-string/non-Element raises PatchError."""
        chain = TransformChain(
            TransformChainConfig(
                name="test",
                forward=(PrimitiveConfig(name="base64"),),
                patch=PatchConfig(replace={"a": "b"}),
            )
        )
        with pytest.raises(PatchError, match="Cannot apply replace"):
            chain.patch(42)


class TestCallablePatch:
    """Tests for callable-based patching."""

    def test_callable_import_error(self) -> None:
        """Non-existent callable raises CallableImportError."""
        chain = TransformChain(
            TransformChainConfig(
                name="test",
                forward=(PrimitiveConfig(name="base64"),),
                patch=PatchConfig(callable="nonexistent.module:func"),
            ),
            allowed_modules=frozenset({"nonexistent.module"}),
        )
        with pytest.raises(CallableImportError, match="Cannot import"):
            chain.patch("data")

    def test_callable_raises_wrapped(self) -> None:
        """Callable that raises is wrapped in CallableError."""
        chain = TransformChain(
            TransformChainConfig(
                name="test",
                forward=(PrimitiveConfig(name="base64"),),
                patch=PatchConfig(callable="json:loads"),  # will fail on non-JSON
            ),
            allowed_modules=frozenset({"json"}),
        )
        with pytest.raises(CallableError, match="failed"):
            chain.patch("not json")

    def test_callable_with_variable_args(self) -> None:
        """Callable args with {{variable}} are resolved from context."""
        chain = TransformChain(
            TransformChainConfig(
                name="test",
                forward=(PrimitiveConfig(name="base64"),),
                patch=PatchConfig(
                    callable="json:dumps",
                    args={"indent": "{{indent_level}}"},
                ),
            ),
            context={"indent_level": "2"},
            allowed_modules=frozenset({"json"}),
        )
        result = chain.patch({"a": 1})
        assert isinstance(result, str)

    def test_missing_variable_raises(self) -> None:
        """Missing variable in args raises TransformChainError."""
        chain = TransformChain(
            TransformChainConfig(
                name="test",
                forward=(PrimitiveConfig(name="base64"),),
                patch=PatchConfig(
                    callable="json:dumps",
                    args={"key": "{{missing}}"},
                ),
            ),
            context={},
            allowed_modules=frozenset({"json"}),
        )
        with pytest.raises(TransformChainError, match="not found in context"):
            chain.patch({"a": 1})


# ============================================================================
# Full transform round-trip
# ============================================================================


class TestTransformRoundTrip:
    """Tests for full forward -> patch -> backward round-trips."""

    def test_no_patch_round_trip(self, sas_report_blob: str, sas_report_config: TransformConfig) -> None:
        """Round-trip without patch preserves content."""
        chain = TransformChain.from_config("sas_report", sas_report_config)
        decoded = chain.forward(sas_report_blob)
        re_encoded = chain.backward(decoded)
        # Re-decode and verify
        raw = base64.b64decode(re_encoded)
        assert raw[:3] == b"\x4d\x15\x04"
        envelope = json.loads(zlib.decompress(raw[3:]))
        assert "SASReport" in envelope["transferableContent"]["content"]

    def test_patch_mapping_round_trip(self, sas_report_blob: str, sas_report_config: TransformConfig) -> None:
        """Round-trip with mapping patch modifies content correctly."""
        chain = TransformChain.from_config("patch_test", sas_report_config)
        result = chain.transform(sas_report_blob)
        # Decode result to verify patch applied
        raw = base64.b64decode(result)
        assert raw[:3] == b"\x4d\x15\x04"
        envelope = json.loads(zlib.decompress(raw[3:]))
        xml_content = envelope["transferableContent"]["content"]
        # Mapping should have replaced the URLs and caslib
        assert "new-host.example.com" in xml_content
        assert "old-host.example.com" not in xml_content
        assert 'library="PROD_LIB"' in xml_content
        assert 'library="CASUSER"' not in xml_content
        # Other content should be preserved
        assert "SASReport" in xml_content
        assert "SASJobExecution" in xml_content

    def test_idempotent_no_patch(self, sas_report_blob: str, sas_report_config: TransformConfig) -> None:
        """Transform without patch is idempotent (content preserved)."""
        chain = TransformChain.from_config("sas_report", sas_report_config)
        result1 = chain.transform(sas_report_blob)
        # Re-create chain (fresh context)
        chain2 = TransformChain.from_config("sas_report", sas_report_config)
        result2 = chain2.transform(result1)

        # Both should decode to same content
        def _decode(blob: str) -> str:
            raw = base64.b64decode(blob)
            env = json.loads(zlib.decompress(raw[3:]))
            result: str = env["transferableContent"]["content"]
            return result

        assert _decode(result1) == _decode(result2)


class TestTransformFunction:
    """Tests for module-level transform() function."""

    def test_with_explicit_config(self, sas_report_blob: str, sas_report_config: TransformConfig) -> None:
        """transform() with explicit config."""
        result = transform(sas_report_blob, "sas_report", config=sas_report_config)
        assert isinstance(result, str)
        # Should be valid base64
        raw = base64.b64decode(result)
        assert raw[:3] == b"\x4d\x15\x04"

    def test_unknown_chain_raises(self, minimal_config: TransformConfig) -> None:
        """transform() with unknown chain raises."""
        with pytest.raises(TransformChainError, match="not found"):
            transform("data", "nonexistent", config=minimal_config)


# ============================================================================
# _matches_filter helper
# ============================================================================


class TestMatchesFilter:
    """Tests for the _matches_filter helper."""

    def test_default_wildcard_matches_anything(self) -> None:
        """Default FilterConfig (all wildcards) matches any metadata."""
        assert _matches_filter({"content_type": "report", "name": "X"}, FilterConfig())
        assert _matches_filter({}, FilterConfig())

    def test_glob_match(self) -> None:
        """Glob name='R220_*' matches 'R220_SALES'."""
        flt = FilterConfig(name="R220_*")
        assert _matches_filter({"name": "R220_SALES"}, flt)

    def test_glob_no_match(self) -> None:
        """Glob name='R220_*' does not match 'REPORT_foo'."""
        flt = FilterConfig(name="R220_*")
        assert not _matches_filter({"name": "REPORT_foo"}, flt)

    def test_content_type_filter_blocks_other_type(self) -> None:
        """content_type='report' rejects folder objects."""
        flt = FilterConfig(content_type="report")
        assert not _matches_filter({"content_type": "folder", "name": "X"}, flt)

    def test_content_type_wildcard_accepts_anything(self) -> None:
        """content_type='*' accepts any object type."""
        flt = FilterConfig(content_type="*")
        assert _matches_filter({"content_type": "folder"}, flt)
        assert _matches_filter({"content_type": "report"}, flt)
        assert _matches_filter({"content_type": "anything"}, flt)

    def test_anded_fields(self) -> None:
        """All filter fields must match (ANDed)."""
        flt = FilterConfig(content_type="report", name="R220_*")
        # Both match
        assert _matches_filter({"content_type": "report", "name": "R220_X"}, flt)
        # Type mismatch
        assert not _matches_filter({"content_type": "folder", "name": "R220_X"}, flt)
        # Name mismatch
        assert not _matches_filter({"content_type": "report", "name": "REPORT_X"}, flt)

    def test_missing_metadata_keys(self) -> None:
        """Missing metadata keys default to empty string."""
        flt = FilterConfig(name="R220_*")
        assert not _matches_filter({}, flt)


# ============================================================================
# Composed patches - fixtures and helpers
# ============================================================================


def _make_composed_config() -> TransformConfig:
    """Build a TransformConfig with patch-only chains and an orchestrator."""
    return TransformConfig(
        chains={
            # Patch-only chains (no forward, just inline patches)
            "remap_host": TransformChainConfig(
                name="remap_host",
                patch=PatchConfig(
                    replace={"https://source/": "https://target/"},
                ),
            ),
            "remap_caslib_global": TransformChainConfig(
                name="remap_caslib_global",
                patch=PatchConfig(
                    replace={'library="CASUSER"': 'library="GLOBAL_LIB"'},
                ),
            ),
            "remap_caslib_r220": TransformChainConfig(
                name="remap_caslib_r220",
                patch=PatchConfig(
                    replace={'library="CASUSER"': 'library="R220_LIB"'},
                ),
            ),
            # Standalone "no-op" passthrough chain (used for forward/backward)
            "passthrough": TransformChainConfig(
                name="passthrough",
                forward=(PrimitiveConfig(name="bytes"),),
            ),
        }
    )


# ============================================================================
# Composed patch tests - TransformChain.patch with composed_patch
# ============================================================================


class TestComposedPatch:
    """Tests for composed patch execution (global + targeted)."""

    def test_global_only_applied_to_all(self) -> None:
        """A global_patch is applied regardless of metadata."""
        config = _make_composed_config()
        # Inject orchestrator using only global_patches
        config = TransformConfig(
            chains={
                **config.chains,
                "orchestrator": TransformChainConfig(
                    name="orchestrator",
                    forward=(PrimitiveConfig(name="bytes"),),
                    composed_patch=ComposedPatchConfig(global_patches=("remap_host",)),
                ),
            }
        )
        chain = TransformChain.from_config("orchestrator", config)

        data = "url=https://source/path"
        # Without metadata: still applied (global ignores filters)
        assert chain.patch(data) == "url=https://target/path"
        # With metadata: same result
        assert chain.patch(data, metadata={"name": "anything"}) == "url=https://target/path"

    def test_targeted_only_applied_when_filter_matches(self) -> None:
        """A targeted_patch is only applied when its filter matches."""
        base = _make_composed_config()
        config = TransformConfig(
            chains={
                **base.chains,
                "orchestrator": TransformChainConfig(
                    name="orchestrator",
                    forward=(PrimitiveConfig(name="bytes"),),
                    composed_patch=ComposedPatchConfig(
                        targeted_patches=(
                            TargetedPatchConfig(
                                filter=FilterConfig(name="R220_*"),
                                patches=("remap_caslib_r220",),
                            ),
                        )
                    ),
                ),
            }
        )
        chain = TransformChain.from_config("orchestrator", config)
        data = '<CasResource library="CASUSER"/>'

        # Filter matches → patch applied
        result = chain.patch(data, metadata={"name": "R220_SALES"})
        assert 'library="R220_LIB"' in result

        # Filter does not match → unchanged
        result2 = chain.patch(data, metadata={"name": "REPORT_foo"})
        assert result2 == data

    def test_targeted_no_match_yields_no_change(self) -> None:
        """If no targeted filter matches, data is returned unchanged."""
        base = _make_composed_config()
        config = TransformConfig(
            chains={
                **base.chains,
                "orchestrator": TransformChainConfig(
                    name="orchestrator",
                    forward=(PrimitiveConfig(name="bytes"),),
                    composed_patch=ComposedPatchConfig(
                        targeted_patches=(
                            TargetedPatchConfig(
                                filter=FilterConfig(name="NEVER_*"),
                                patches=("remap_caslib_r220",),
                            ),
                        )
                    ),
                ),
            }
        )
        chain = TransformChain.from_config("orchestrator", config)
        data = '<CasResource library="CASUSER"/>'
        assert chain.patch(data, metadata={"name": "X"}) == data

    def test_global_then_targeted_order(self) -> None:
        """global_patches run before targeted_patches."""
        base = _make_composed_config()
        config = TransformConfig(
            chains={
                **base.chains,
                "orchestrator": TransformChainConfig(
                    name="orchestrator",
                    forward=(PrimitiveConfig(name="bytes"),),
                    composed_patch=ComposedPatchConfig(
                        global_patches=("remap_host",),
                        targeted_patches=(
                            TargetedPatchConfig(
                                filter=FilterConfig(name="R220_*"),
                                patches=("remap_caslib_r220",),
                            ),
                        ),
                    ),
                ),
            }
        )
        chain = TransformChain.from_config("orchestrator", config)

        data = 'url="https://source/" library="CASUSER"'
        result = chain.patch(data, metadata={"name": "R220_SALES"})
        assert "https://target/" in result
        assert 'library="R220_LIB"' in result

    def test_multiple_targeted_match_applied_in_order(self) -> None:
        """Both 'R220_*' and '*' filters match R220_FOO; both applied."""
        base = _make_composed_config()
        config = TransformConfig(
            chains={
                **base.chains,
                "orchestrator": TransformChainConfig(
                    name="orchestrator",
                    forward=(PrimitiveConfig(name="bytes"),),
                    composed_patch=ComposedPatchConfig(
                        targeted_patches=(
                            TargetedPatchConfig(
                                filter=FilterConfig(name="R220_*"),
                                patches=("remap_caslib_r220",),
                            ),
                            TargetedPatchConfig(
                                filter=FilterConfig(name="*"),
                                patches=("remap_caslib_global",),
                            ),
                        )
                    ),
                ),
            }
        )
        chain = TransformChain.from_config("orchestrator", config)
        data = '<CasResource library="CASUSER"/>'

        # Both filters match R220_FOO. Order: r220 first, global second.
        # Global maps "library=CASUSER" → "library=GLOBAL_LIB", but at that
        # point the string is already "library=R220_LIB", so global doesn't
        # match anything → final result is R220_LIB.
        result = chain.patch(data, metadata={"name": "R220_FOO"})
        assert 'library="R220_LIB"' in result

        # For REPORT_FOO, only the wildcard filter matches → GLOBAL_LIB
        result2 = chain.patch(data, metadata={"name": "REPORT_FOO"})
        assert 'library="GLOBAL_LIB"' in result2

    def test_last_wins_on_conflict(self) -> None:
        """When multiple patches mutate the same field, the last wins."""
        config = TransformConfig(
            chains={
                "set_a": TransformChainConfig(
                    name="set_a",
                    patch=PatchConfig(replace={"PLACEHOLDER": "VALUE_A"}),
                ),
                "set_b": TransformChainConfig(
                    name="set_b",
                    patch=PatchConfig(replace={"VALUE_A": "VALUE_B"}),
                ),
                "set_c": TransformChainConfig(
                    name="set_c",
                    patch=PatchConfig(replace={"VALUE_B": "VALUE_C"}),
                ),
                "orchestrator": TransformChainConfig(
                    name="orchestrator",
                    forward=(PrimitiveConfig(name="bytes"),),
                    composed_patch=ComposedPatchConfig(
                        global_patches=("set_a", "set_b", "set_c"),
                    ),
                ),
            }
        )
        chain = TransformChain.from_config("orchestrator", config)
        # Cascade: PLACEHOLDER → VALUE_A → VALUE_B → VALUE_C
        assert chain.patch("PLACEHOLDER") == "VALUE_C"

    def test_glob_pattern_match_r220(self) -> None:
        """Glob 'R220_*' matches 'R220_SALES' → patch applied."""
        config = TransformConfig(
            chains={
                "set_x": TransformChainConfig(
                    name="set_x",
                    patch=PatchConfig(replace={"X": "Y"}),
                ),
                "orchestrator": TransformChainConfig(
                    name="orchestrator",
                    forward=(PrimitiveConfig(name="bytes"),),
                    composed_patch=ComposedPatchConfig(
                        targeted_patches=(
                            TargetedPatchConfig(
                                filter=FilterConfig(name="R220_*"),
                                patches=("set_x",),
                            ),
                        )
                    ),
                ),
            }
        )
        chain = TransformChain.from_config("orchestrator", config)
        assert chain.patch("X", metadata={"name": "R220_SALES"}) == "Y"

    def test_glob_pattern_no_match(self) -> None:
        """Glob 'R220_*' does not match 'REPORT_foo' → patch skipped."""
        config = TransformConfig(
            chains={
                "set_x": TransformChainConfig(
                    name="set_x",
                    patch=PatchConfig(replace={"X": "Y"}),
                ),
                "orchestrator": TransformChainConfig(
                    name="orchestrator",
                    forward=(PrimitiveConfig(name="bytes"),),
                    composed_patch=ComposedPatchConfig(
                        targeted_patches=(
                            TargetedPatchConfig(
                                filter=FilterConfig(name="R220_*"),
                                patches=("set_x",),
                            ),
                        )
                    ),
                ),
            }
        )
        chain = TransformChain.from_config("orchestrator", config)
        assert chain.patch("X", metadata={"name": "REPORT_foo"}) == "X"

    def test_content_type_filter_blocks_folder(self) -> None:
        """content_type='report' rejects a folder object."""
        config = TransformConfig(
            chains={
                "set_x": TransformChainConfig(
                    name="set_x",
                    patch=PatchConfig(replace={"X": "Y"}),
                ),
                "orchestrator": TransformChainConfig(
                    name="orchestrator",
                    forward=(PrimitiveConfig(name="bytes"),),
                    composed_patch=ComposedPatchConfig(
                        targeted_patches=(
                            TargetedPatchConfig(
                                filter=FilterConfig(content_type="report"),
                                patches=("set_x",),
                            ),
                        )
                    ),
                ),
            }
        )
        chain = TransformChain.from_config("orchestrator", config)
        # Folder → not applied
        assert chain.patch("X", metadata={"content_type": "folder"}) == "X"
        # Report → applied
        assert chain.patch("X", metadata={"content_type": "report"}) == "Y"

    def test_content_type_wildcard_accepts_anything(self) -> None:
        """content_type='*' accepts any object type."""
        config = TransformConfig(
            chains={
                "set_x": TransformChainConfig(
                    name="set_x",
                    patch=PatchConfig(replace={"X": "Y"}),
                ),
                "orchestrator": TransformChainConfig(
                    name="orchestrator",
                    forward=(PrimitiveConfig(name="bytes"),),
                    composed_patch=ComposedPatchConfig(
                        targeted_patches=(
                            TargetedPatchConfig(
                                filter=FilterConfig(content_type="*"),
                                patches=("set_x",),
                            ),
                        )
                    ),
                ),
            }
        )
        chain = TransformChain.from_config("orchestrator", config)
        assert chain.patch("X", metadata={"content_type": "folder"}) == "Y"
        assert chain.patch("X", metadata={"content_type": "report"}) == "Y"
        assert chain.patch("X", metadata={}) == "Y"

    def test_unknown_global_chain_raises_at_config_time(self) -> None:
        """A global_patches reference to unknown chain raises at TransformConfig build."""
        with pytest.raises(TransformConfigError, match="unknown chain"):
            TransformConfig(
                chains={
                    "orchestrator": TransformChainConfig(
                        name="orchestrator",
                        forward=(PrimitiveConfig(name="bytes"),),
                        composed_patch=ComposedPatchConfig(global_patches=("ghost",)),
                    ),
                }
            )

    def test_unknown_targeted_chain_raises_at_config_time(self) -> None:
        """A targeted_patches reference to unknown chain raises at TransformConfig build."""
        with pytest.raises(TransformConfigError, match="unknown chain"):
            TransformConfig(
                chains={
                    "orchestrator": TransformChainConfig(
                        name="orchestrator",
                        forward=(PrimitiveConfig(name="bytes"),),
                        composed_patch=ComposedPatchConfig(
                            targeted_patches=(
                                TargetedPatchConfig(
                                    filter=FilterConfig(),
                                    patches=("ghost",),
                                ),
                            )
                        ),
                    ),
                }
            )

    def test_composed_patch_without_transform_config_raises(self) -> None:
        """Direct TransformChain() with composed_patch but no transform_config fails."""
        config = TransformChainConfig(
            name="orphan",
            forward=(PrimitiveConfig(name="bytes"),),
            composed_patch=ComposedPatchConfig(global_patches=("ghost",)),
        )
        with pytest.raises(TransformConfigError, match="requires a transform_config"):
            TransformChain(config)

    def test_patch_only_chain_instantiation(self) -> None:
        """A patch-only chain can be instantiated; forward/backward are no-ops."""
        cfg = TransformChainConfig(
            name="patch_only",
            patch=PatchConfig(replace={"a": "b"}),
        )
        chain = TransformChain(cfg)
        # forward/backward have no primitives → return data unchanged
        assert chain.forward("a") == "a"
        assert chain.backward("a") == "a"
        # patch is what matters
        assert chain.patch("a") == "b"

    def test_full_transform_round_trip_with_composed_patch(
        self,
        sas_report_blob: str,
    ) -> None:
        """End-to-end: composed_patch on a real SAS report blob."""
        config = TransformConfig(
            chains={
                "sas_report": TransformChainConfig(
                    name="sas_report",
                    forward=(
                        PrimitiveConfig(name="base64"),
                        PrimitiveConfig(name="zlib", options={"skip_bytes": 3}),
                        PrimitiveConfig(
                            name="json",
                            options={"extract": "transferableContent.content"},
                        ),
                    ),
                    backward=(
                        PrimitiveConfig(
                            name="json",
                            options={"wrap": "transferableContent.content"},
                        ),
                        PrimitiveConfig(
                            name="zlib",
                            options={"prepend_bytes": "4d1504"},
                        ),
                        PrimitiveConfig(name="base64"),
                    ),
                ),
                "remap_host": TransformChainConfig(
                    name="remap_host",
                    patch=PatchConfig(
                        replace={
                            "https://old-host.example.com/": "https://new-host.example.com/",
                        }
                    ),
                ),
                "remap_caslib_r220": TransformChainConfig(
                    name="remap_caslib_r220",
                    patch=PatchConfig(
                        replace={'library="CASUSER"': 'library="R220_LIB"'},
                    ),
                ),
                "remap_caslib_default": TransformChainConfig(
                    name="remap_caslib_default",
                    patch=PatchConfig(
                        replace={'library="CASUSER"': 'library="DEFAULT_LIB"'},
                    ),
                ),
                "patch_report": TransformChainConfig(
                    name="patch_report",
                    preset="sas_report",
                    composed_patch=ComposedPatchConfig(
                        global_patches=("remap_host",),
                        targeted_patches=(
                            TargetedPatchConfig(
                                filter=FilterConfig(name="R220_*"),
                                patches=("remap_caslib_r220",),
                            ),
                            TargetedPatchConfig(
                                filter=FilterConfig(name="*"),
                                patches=("remap_caslib_default",),
                            ),
                        ),
                    ),
                ),
            }
        )

        chain = TransformChain.from_config("patch_report", config)

        # R220 object → host remapped + R220_LIB caslib
        result_r220 = chain.transform(
            sas_report_blob,
            metadata={"content_type": "report", "name": "R220_SALES"},
        )
        raw = base64.b64decode(result_r220)
        envelope = json.loads(zlib.decompress(raw[3:]))
        xml = envelope["transferableContent"]["content"]
        assert "https://new-host.example.com/" in xml
        assert 'library="R220_LIB"' in xml

        # REPORT object → host remapped + DEFAULT_LIB caslib
        result_other = chain.transform(
            sas_report_blob,
            metadata={"content_type": "report", "name": "REPORT_FOO"},
        )
        raw = base64.b64decode(result_other)
        envelope = json.loads(zlib.decompress(raw[3:]))
        xml = envelope["transferableContent"]["content"]
        assert "https://new-host.example.com/" in xml
        assert 'library="DEFAULT_LIB"' in xml


# ============================================================================
# replace_outer_uris helper + PROTECTED_OUTER_PATHS
# ============================================================================


class TestReplaceOuterUris:
    """Tests for the standalone replace_outer_uris helper."""

    def test_simple_string_replacement(self) -> None:
        """A flat dict with a single string value gets patched."""
        obj = {"uri": "library=CASUSER"}
        n = replace_outer_uris(obj, {"CASUSER": "PUBLIC"})
        assert obj == {"uri": "library=PUBLIC"}
        assert n == 1

    def test_empty_replace_map_no_op(self) -> None:
        """An empty replace map returns 0 and does not mutate."""
        obj = {"uri": "library=CASUSER"}
        n = replace_outer_uris(obj, {})
        assert obj == {"uri": "library=CASUSER"}
        assert n == 0

    def test_no_matching_substring_returns_zero(self) -> None:
        """Strings without the substring are not counted."""
        obj = {"uri": "library=PROD_LIB"}
        n = replace_outer_uris(obj, {"CASUSER": "PUBLIC"})
        assert obj == {"uri": "library=PROD_LIB"}
        assert n == 0

    def test_nested_dict_and_list(self) -> None:
        """Nested structures are walked recursively."""
        obj = {
            "outer": {
                "inner": [
                    {"uri": "library=CASUSER"},
                    {"uri": "library=CASUSER"},
                ]
            }
        }
        n = replace_outer_uris(obj, {"CASUSER": "PUBLIC"})
        assert n == 2
        assert obj["outer"]["inner"][0]["uri"] == "library=PUBLIC"
        assert obj["outer"]["inner"][1]["uri"] == "library=PUBLIC"

    def test_multiple_replacements_per_string(self) -> None:
        """A single string with two patterns counts once but both apply."""
        obj = {"text": "foo and bar"}
        n = replace_outer_uris(obj, {"foo": "FOO", "bar": "BAR"})
        assert obj == {"text": "FOO and BAR"}
        assert n == 1

    def test_protected_xpath_not_touched(self) -> None:
        """The default PROTECTED_OUTER_PATHS protects connectors[*].hints.xpath."""
        obj: dict[str, Any] = {
            "connectors": [
                {
                    "uri": "library=CASUSER",
                    "hints": {
                        "xpath": "/foo/bar/CASUSER/baz",
                        "orig-uri": "library=CASUSER",
                    },
                }
            ]
        }
        n = replace_outer_uris(obj, {"CASUSER": "PUBLIC"})
        # uri AND orig-uri patched (both contain CASUSER), xpath untouched
        assert n == 2
        assert obj["connectors"][0]["uri"] == "library=PUBLIC"
        assert obj["connectors"][0]["hints"]["orig-uri"] == "library=PUBLIC"
        assert obj["connectors"][0]["hints"]["xpath"] == "/foo/bar/CASUSER/baz"

    def test_custom_protected_paths(self) -> None:
        """Caller can supply a custom protected_paths blacklist."""
        obj: dict[str, Any] = {"a": {"b": "CASUSER"}, "c": "CASUSER"}
        protected = frozenset({"a.b"})
        n = replace_outer_uris(obj, {"CASUSER": "PUBLIC"}, protected_paths=protected)
        assert n == 1
        assert obj["a"]["b"] == "CASUSER"  # protected
        assert obj["c"] == "PUBLIC"

    def test_custom_protected_paths_with_wildcard(self) -> None:
        """Custom protected_paths support [*] for any list index."""
        obj = {"items": [{"uri": "CASUSER", "tag": "CASUSER"}]}
        protected = frozenset({"items[*].tag"})
        n = replace_outer_uris(
            obj,
            {"CASUSER": "PUBLIC"},
            protected_paths=protected,
        )
        assert n == 1
        assert obj["items"][0]["uri"] == "PUBLIC"
        assert obj["items"][0]["tag"] == "CASUSER"  # protected

    def test_non_string_scalars_pass_through(self) -> None:
        """Ints, floats, bools, None are returned unchanged."""
        obj = {"x": 42, "y": 3.14, "z": True, "n": None, "s": "CASUSER"}
        n = replace_outer_uris(obj, {"CASUSER": "PUBLIC"})
        assert n == 1
        assert obj["x"] == 42
        assert obj["y"] == 3.14
        assert obj["z"] is True
        assert obj["n"] is None
        assert obj["s"] == "PUBLIC"

    def test_default_protected_paths_constant(self) -> None:
        """PROTECTED_OUTER_PATHS contains the SAS Viya xpath protection."""
        assert "connectors[*].hints.xpath" in PROTECTED_OUTER_PATHS


# ============================================================================
# PatchConfig scope dispatch (blob | outer | all)
# ============================================================================


class TestReplaceScopeBlob:
    """scope='blob' (default): patches the decoded data only."""

    def test_blob_scope_default_behavior(self) -> None:
        """The default scope still patches the blob data, leaving outer alone."""
        chain = TransformChain(
            TransformChainConfig(
                name="test",
                forward=(PrimitiveConfig(name="bytes"),),
                patch=PatchConfig(replace={"CASUSER": "PUBLIC"}),
            )
        )
        outer = {"uri": "library=CASUSER"}
        result = chain.patch("library=CASUSER", metadata={"outer": outer})
        assert result == "library=PUBLIC"
        # outer is NOT touched in blob scope
        assert outer == {"uri": "library=CASUSER"}


class TestReplaceScopeOuter:
    """scope='outer': mutates metadata['outer'], leaves data unchanged."""

    def test_outer_scope_mutates_outer_only(self) -> None:
        """Outer scope patches the wrapper, returns data unchanged."""
        chain = TransformChain(
            TransformChainConfig(
                name="test",
                forward=(PrimitiveConfig(name="bytes"),),
                patch=PatchConfig(
                    replace={"CASUSER": "PUBLIC"},
                    scope="outer",
                ),
            )
        )
        outer = {"uri": "library=CASUSER"}
        result = chain.patch("library=CASUSER", metadata={"outer": outer})
        # blob is unchanged
        assert result == "library=CASUSER"
        # outer is mutated
        assert outer == {"uri": "library=PUBLIC"}

    def test_outer_scope_missing_outer_raises(self) -> None:
        """Outer scope without metadata['outer'] raises PatchError."""
        chain = TransformChain(
            TransformChainConfig(
                name="test",
                forward=(PrimitiveConfig(name="bytes"),),
                patch=PatchConfig(
                    replace={"a": "b"},
                    scope="outer",
                ),
            )
        )
        with pytest.raises(PatchError, match="requires.*metadata"):
            chain.patch("data")

    def test_outer_scope_missing_outer_key_raises(self) -> None:
        """Outer scope with metadata but missing 'outer' key raises."""
        chain = TransformChain(
            TransformChainConfig(
                name="test",
                forward=(PrimitiveConfig(name="bytes"),),
                patch=PatchConfig(replace={"a": "b"}, scope="outer"),
            )
        )
        with pytest.raises(PatchError, match="requires.*metadata"):
            chain.patch("data", metadata={"name": "foo"})


class TestReplaceScopeAll:
    """scope='all': patches both the blob and the outer wrapper."""

    def test_all_scope_patches_both(self) -> None:
        """All scope mutates outer AND patches the blob data."""
        chain = TransformChain(
            TransformChainConfig(
                name="test",
                forward=(PrimitiveConfig(name="bytes"),),
                patch=PatchConfig(
                    replace={"CASUSER": "PUBLIC"},
                    scope="all",
                ),
            )
        )
        outer = {"uri": "library=CASUSER"}
        result = chain.patch("library=CASUSER", metadata={"outer": outer})
        assert result == "library=PUBLIC"
        assert outer == {"uri": "library=PUBLIC"}

    def test_all_scope_missing_outer_raises(self) -> None:
        """All scope without metadata['outer'] raises PatchError."""
        chain = TransformChain(
            TransformChainConfig(
                name="test",
                forward=(PrimitiveConfig(name="bytes"),),
                patch=PatchConfig(
                    replace={"a": "b"},
                    scope="all",
                ),
            )
        )
        with pytest.raises(PatchError, match="requires.*metadata"):
            chain.patch("data")

    def test_all_scope_xpath_protection(self) -> None:
        """All scope respects PROTECTED_OUTER_PATHS for the outer wrapper."""
        chain = TransformChain(
            TransformChainConfig(
                name="test",
                forward=(PrimitiveConfig(name="bytes"),),
                patch=PatchConfig(
                    replace={"CASUSER": "PUBLIC"},
                    scope="all",
                ),
            )
        )
        outer: dict[str, Any] = {
            "connectors": [
                {
                    "uri": "library=CASUSER",
                    "hints": {
                        "xpath": "/CASUSER/path",
                        "orig-uri": "library=CASUSER",
                    },
                }
            ]
        }
        result = chain.patch("blob with CASUSER", metadata={"outer": outer})
        assert result == "blob with PUBLIC"
        assert outer["connectors"][0]["uri"] == "library=PUBLIC"
        assert outer["connectors"][0]["hints"]["orig-uri"] == "library=PUBLIC"
        # xpath is NEVER touched
        assert outer["connectors"][0]["hints"]["xpath"] == "/CASUSER/path"


# ============================================================================
# C2 regression: composed_patch on Element avoids repeated XML roundtrips
# ============================================================================


class TestComposedPatchXmlPerf:
    """C2: composed_patch on Element data serializes/parses only once."""

    def test_composed_patch_element_single_roundtrip(self) -> None:
        """10 patches on an Element call xml_parse at most twice (once in + once out)."""
        from unittest.mock import patch as mock_patch
        from xml.etree.ElementTree import Element, SubElement

        root = Element("root")
        child = SubElement(root, "item")
        child.text = "A0 A1 A2 A3 A4 A5 A6 A7 A8 A9"

        # Build 10 patch-only chains
        chains: dict[str, TransformChainConfig] = {}
        for i in range(10):
            chains[f"patch_{i}"] = TransformChainConfig(
                name=f"patch_{i}",
                patch=PatchConfig(replace={f"A{i}": f"B{i}"}),
            )
        chains["orchestrator"] = TransformChainConfig(
            name="orchestrator",
            forward=(PrimitiveConfig(name="bytes"),),
            composed_patch=ComposedPatchConfig(
                global_patches=tuple(f"patch_{i}" for i in range(10)),
            ),
        )
        config = TransformConfig(chains=chains)
        chain = TransformChain.from_config("orchestrator", config)

        # Count xml_parse calls
        from kstlib.transform import primitives as prim_mod

        original_xml_parse = prim_mod.xml_parse
        call_count = [0]

        def counting_xml_parse(data: str, cfg: PrimitiveConfig) -> Element:
            """Count xml_parse calls."""
            call_count[0] += 1
            return original_xml_parse(data, cfg)

        with mock_patch.object(prim_mod, "xml_parse", side_effect=counting_xml_parse):
            # Also patch the import in chain module
            import kstlib.transform.chain as chain_mod

            with mock_patch.object(chain_mod, "xml_parse", side_effect=counting_xml_parse):
                result = chain.patch(root)

        # Should be exactly 1 parse (the final re-parse in _apply_composed_patch)
        # NOT 10 parses (one per patch)
        assert call_count[0] <= 2, f"xml_parse called {call_count[0]} times, expected <= 2"
        assert isinstance(result, Element)
        item = result.find("item")
        assert item is not None
        assert all(f"B{i}" in (item.text or "") for i in range(10))


# ============================================================================
# H1 regression: _walk_node recursion depth guard
# ============================================================================


class TestWalkNodeDepthGuard:
    """H1: _walk_node rejects deeply nested structures."""

    def test_depth_exceeds_limit_raises_patch_error(self) -> None:
        """Nesting deeper than _MAX_WALK_DEPTH raises PatchError."""
        # Build a nested dict that exceeds the depth limit
        obj: dict[str, Any] = {"value": "CASUSER"}
        current = obj
        for _ in range(_MAX_WALK_DEPTH + 5):
            child: dict[str, Any] = {"value": "CASUSER"}
            current["child"] = child
            current = child

        with pytest.raises(PatchError, match="recursion depth"):
            replace_outer_uris(obj, {"CASUSER": "PUBLIC"})

    def test_moderate_depth_accepted(self) -> None:
        """Nesting within limit works correctly."""
        obj: dict[str, Any] = {"value": "CASUSER"}
        current = obj
        for _ in range(10):
            child: dict[str, Any] = {"value": "CASUSER"}
            current["child"] = child
            current = child

        n = replace_outer_uris(obj, {"CASUSER": "PUBLIC"})
        assert n == 11  # 10 children + 1 root


# ============================================================================
# H4 regression: additional_protected_paths additive parameter
# ============================================================================


class TestAdditionalProtectedPaths:
    """H4: additional_protected_paths is additive to defaults."""

    def test_additional_paths_merged_with_defaults(self) -> None:
        """additional_protected_paths adds to protected_paths, does not replace."""
        obj: dict[str, Any] = {
            "connectors": [{"uri": "CASUSER", "hints": {"xpath": "/CASUSER"}}],
            "extra": {"secret": "CASUSER"},
        }
        n = replace_outer_uris(
            obj,
            {"CASUSER": "PUBLIC"},
            additional_protected_paths=frozenset({"extra.secret"}),
        )
        # uri patched (not protected), xpath protected by default, extra.secret protected additively
        assert n == 1
        assert obj["connectors"][0]["uri"] == "PUBLIC"
        assert obj["connectors"][0]["hints"]["xpath"] == "/CASUSER"
        assert obj["extra"]["secret"] == "CASUSER"

    def test_no_additional_paths_uses_defaults_only(self) -> None:
        """Without additional_protected_paths, only defaults apply."""
        obj: dict[str, Any] = {
            "connectors": [{"uri": "CASUSER", "hints": {"xpath": "/CASUSER"}}],
            "extra": {"secret": "CASUSER"},
        }
        n = replace_outer_uris(obj, {"CASUSER": "PUBLIC"})
        assert n == 2  # uri + extra.secret both patched
        assert obj["extra"]["secret"] == "PUBLIC"
        assert obj["connectors"][0]["hints"]["xpath"] == "/CASUSER"  # still protected


# ============================================================================
# split (forward-only extractor)
# ============================================================================


class TestSplitForwardOnly:
    """Tests for the forward-only split primitive in a chain."""

    def test_auto_reverse_raises(self) -> None:
        """A split forward primitive cannot be auto-reversed."""
        fwd = (PrimitiveConfig(name="split", options={"sep": "/", "index": -1}),)
        with pytest.raises(TransformConfigError, match="auto-reverse"):
            _auto_reverse(fwd)

    def test_construct_without_backward_succeeds(self) -> None:
        """A forward-only chain builds without backward (auto-reverse skipped)."""
        config = TransformChainConfig(
            name="extract",
            forward=(PrimitiveConfig(name="split", options={"sep": "/", "index": -1}),),
        )
        chain = TransformChain(config)
        assert chain.forward("/reports/reports/xxx") == "xxx"

    def test_forward_with_empty_backward(self) -> None:
        """split runs in forward when an explicit empty backward opts out."""
        config = TransformChainConfig(
            name="extract",
            forward=(PrimitiveConfig(name="split", options={"sep": "/", "index": -1}),),
            backward=(),
        )
        chain = TransformChain(config)
        assert chain.forward("/reports/reports/xxx") == "xxx"

    def test_backward_on_forward_only_raises(self) -> None:
        """Calling backward on a forward-only chain raises a clear error."""
        config = TransformChainConfig(
            name="extract",
            forward=(PrimitiveConfig(name="split", options={"sep": "/", "index": -1}),),
        )
        chain = TransformChain(config)
        with pytest.raises(TransformConfigError, match="forward-only"):
            chain.backward("xxx")

    def test_transform_extracts_from_config(self) -> None:
        """A forward-only chain is usable end-to-end via from_config/transform."""
        config = TransformConfig(
            chains={
                "extract": TransformChainConfig(
                    name="extract",
                    forward=(PrimitiveConfig(name="split", options={"sep": "/", "index": -1}),),
                )
            }
        )
        assert transform("/reports/reports/xxx", "extract", config) == "xxx"

    def test_transform_applies_patch_to_extracted_value(self) -> None:
        """A patch on a forward-only chain applies to the extracted value (no silent drop)."""
        config = TransformChainConfig(
            name="extract",
            forward=(PrimitiveConfig(name="split", options={"sep": "/", "index": -1}),),
            patch=PatchConfig(replace={"xxx": "yyy"}),
        )
        chain = TransformChain(config)
        assert chain.transform("/reports/reports/xxx") == "yyy"

    def test_non_forward_only_still_eager_auto_reverse(self) -> None:
        """Non-forward-only chains keep eager auto-reverse (zlib skip_bytes raises at construction)."""
        config = TransformChainConfig(
            name="roundtrip",
            forward=(PrimitiveConfig(name="zlib", options={"skip_bytes": 2}),),
        )
        with pytest.raises(TransformConfigError, match="skip_bytes requires explicit backward"):
            TransformChain(config)


class TestTrForwardOnly:
    """tr inherits the forward-only chain mechanism (C1.5), no chain.py change."""

    def test_forward_only_from_config(self) -> None:
        """A tr chain builds without backward, forward works, backward raises."""
        config = TransformChainConfig(
            name="strip",
            forward=(PrimitiveConfig(name="tr", options={"delete": "\n"}),),
        )
        chain = TransformChain(config)
        assert chain.forward("a\nb\n") == "ab"
        with pytest.raises(TransformConfigError, match="forward-only"):
            chain.backward("ab")


class TestRemovePrefixForwardOnly:
    """removeprefix inherits the forward-only chain mechanism (C1.5), no chain.py change."""

    def test_forward_only_from_config(self) -> None:
        """A removeprefix chain builds without backward, forward works, backward raises."""
        config = TransformChainConfig(
            name="strip",
            forward=(PrimitiveConfig(name="removeprefix", options={"prefix": "reports/"}),),
        )
        chain = TransformChain(config)
        assert chain.forward("reports/abc") == "abc"
        with pytest.raises(TransformConfigError, match="forward-only"):
            chain.backward("abc")


class TestRemoveSuffixForwardOnly:
    """removesuffix inherits the forward-only chain mechanism (C1.5), no chain.py change."""

    def test_forward_only_from_config(self) -> None:
        """A removesuffix chain builds without backward, forward works, backward raises."""
        config = TransformChainConfig(
            name="strip",
            forward=(PrimitiveConfig(name="removesuffix", options={"suffix": ".json"}),),
        )
        chain = TransformChain(config)
        assert chain.forward("data.json") == "data"
        with pytest.raises(TransformConfigError, match="forward-only"):
            chain.backward("data")
