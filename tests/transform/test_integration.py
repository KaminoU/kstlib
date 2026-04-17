"""Integration tests for kstlib.transform."""

from __future__ import annotations

import base64
import json
import zlib

from kstlib.transform.chain import TransformChain
from kstlib.transform.config import (
    TransformConfig,
    _parse_chain,
    _parse_primitive,
)


class TestConfigParsing:
    """Tests for YAML config parsing functions."""

    def test_parse_primitive_string(self) -> None:
        """Parse primitive from plain string."""
        cfg = _parse_primitive("base64")
        assert cfg.name == "base64"
        assert cfg.options == {}

    def test_parse_primitive_dict(self) -> None:
        """Parse primitive from dict with options."""
        cfg = _parse_primitive({"zlib": {"skip_bytes": 3}})
        assert cfg.name == "zlib"
        assert cfg.options["skip_bytes"] == 3

    def test_parse_primitive_dict_null_options(self) -> None:
        """Parse primitive dict with null options."""
        cfg = _parse_primitive({"xml": None})
        assert cfg.name == "xml"
        assert cfg.options == {}

    def test_parse_chain_minimal(self) -> None:
        """Parse minimal chain from dict."""
        raw = {"forward": ["base64"]}
        cfg = _parse_chain("test", raw)
        assert cfg.name == "test"
        assert len(cfg.forward) == 1

    def test_parse_chain_with_preset(self) -> None:
        """Parse chain with preset reference."""
        raw = {"preset": "parent", "patch": {"replace": {"a": "b"}}}
        cfg = _parse_chain("child", raw)
        assert cfg.preset == "parent"
        assert cfg.patch is not None

    def test_parse_chain_full(self) -> None:
        """Parse full chain with forward, backward, and patch."""
        raw = {
            "forward": [
                "base64",
                {"zlib": {"skip_bytes": 3}},
                {"json": {"extract": "tc.content"}},
            ],
            "backward": [
                {"json": {"wrap": "tc.content"}},
                {"zlib": {"prepend_bytes": "4d1504"}},
                "base64",
            ],
            "patch": {
                "replace": {"old": "new"},
            },
        }
        cfg = _parse_chain("full", raw)
        assert len(cfg.forward) == 3
        assert cfg.backward is not None
        assert len(cfg.backward) == 3
        assert cfg.patch is not None
        assert cfg.patch.replace == {"old": "new"}


class TestFullRoundTripIntegrity:
    """Tests proving data integrity across full round-trips."""

    def test_round_trip_preserves_xml(self, sas_report_blob: str, sas_report_config: TransformConfig) -> None:
        """Forward -> backward preserves XML structure."""
        chain = TransformChain.from_config("sas_report", sas_report_config)
        xml_decoded = chain.forward(sas_report_blob)
        re_encoded = chain.backward(xml_decoded)

        # Decode original
        raw_orig = base64.b64decode(sas_report_blob)
        env_orig = json.loads(zlib.decompress(raw_orig[3:]))
        xml_orig = env_orig["transferableContent"]["content"]

        # Decode result
        raw_result = base64.b64decode(re_encoded)
        env_result = json.loads(zlib.decompress(raw_result[3:]))
        xml_result = env_result["transferableContent"]["content"]

        assert xml_orig == xml_result

    def test_round_trip_preserves_envelope_siblings(
        self,
        sas_report_blob: str,
        sas_report_config: TransformConfig,
    ) -> None:
        """Forward(extract) -> backward(wrap) preserves sibling fields in envelope."""
        chain = TransformChain.from_config("sas_report", sas_report_config)
        decoded = chain.forward(sas_report_blob)
        re_encoded = chain.backward(decoded)

        raw = base64.b64decode(re_encoded)
        envelope = json.loads(zlib.decompress(raw[3:]))

        # object metadata should be preserved
        assert envelope["object"]["id"] == "test-report-uuid"
        assert envelope["object"]["name"] == "test_report"
        assert envelope["object"]["createdBy"] == "TESTUSER"

    def test_sas_header_preserved(self, sas_report_blob: str, sas_report_config: TransformConfig) -> None:
        r"""The M\x15\x04 SAS header is preserved after round-trip."""
        chain = TransformChain.from_config("sas_report", sas_report_config)
        result = chain.transform(sas_report_blob)
        raw = base64.b64decode(result)
        assert raw[:3] == b"\x4d\x15\x04"

    def test_patch_only_modifies_targeted_content(
        self,
        sas_report_blob: str,
        sas_report_config: TransformConfig,
    ) -> None:
        """Mapping patch modifies URLs but preserves everything else."""
        chain = TransformChain.from_config("patch_test", sas_report_config)
        result = chain.transform(sas_report_blob)

        raw = base64.b64decode(result)
        envelope = json.loads(zlib.decompress(raw[3:]))
        xml = envelope["transferableContent"]["content"]

        # Patched
        assert "new-host.example.com" in xml
        assert 'library="PROD_LIB"' in xml

        # Preserved
        assert "SASReport" in xml
        assert "DataSources" in xml
        assert 'table="MYDATA"' in xml
        assert 'server="cas-shared-default"' in xml


class TestMemoryCleanup:
    """Tests verifying no state leaks between transform calls."""

    def test_chain_context_reset_on_forward(self, sas_report_blob: str, sas_report_config: TransformConfig) -> None:
        """_ChainContext is reset on each forward call."""
        chain = TransformChain.from_config("sas_report", sas_report_config)
        chain.forward(sas_report_blob)
        # Second forward should reset context
        chain.forward(sas_report_blob)
        # No assertion needed - if context leaked, backward would fail
        result = chain.backward(chain.forward(sas_report_blob))
        assert isinstance(result, str)

    def test_no_state_between_chains(self, sas_report_blob: str, sas_report_config: TransformConfig) -> None:
        """Different chain instances share no state."""
        chain1 = TransformChain.from_config("sas_report", sas_report_config)
        chain2 = TransformChain.from_config("sas_report", sas_report_config)
        r1 = chain1.transform(sas_report_blob)
        r2 = chain2.transform(sas_report_blob)

        def _decode(blob: str) -> str:
            raw = base64.b64decode(blob)
            env = json.loads(zlib.decompress(raw[3:]))
            result: str = env["transferableContent"]["content"]
            return result

        assert _decode(r1) == _decode(r2)
