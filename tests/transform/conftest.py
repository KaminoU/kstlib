"""Shared fixtures for kstlib.transform tests."""

from __future__ import annotations

import base64
import json
import zlib
from typing import Any

import pytest

from kstlib.transform.config import (
    PatchConfig,
    PrimitiveConfig,
    TransformChainConfig,
    TransformConfig,
)

# ============================================================================
# SAS report blob fixtures
# ============================================================================

_SAS_HEADER = b"\x4d\x15\x04"

_SAMPLE_BIRD_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<SASReport xmlns="http://www.sas.com/sasreportmodel/bird-4.2.4"'
    ' label="test_report" createdLocale="en">\n'
    "\t<DataSources>\n"
    '\t\t<DataSource label="MYDATA" type="relational" name="ds7">\n'
    '\t\t\t<CasResource server="cas-shared-default"'
    ' library="CASUSER" table="MYDATA" locale="en"/>\n'
    "\t\t</DataSource>\n"
    "\t</DataSources>\n"
    "\t<VisualElements>\n"
    '\t\t<WebContent url="https://old-host.example.com/SASJobExecution/'
    '?_program=%2FProjects%2FMyJob" name="ve1"/>\n'
    "\t</VisualElements>\n"
    "</SASReport>"
)

_SAMPLE_ENVELOPE: dict[str, Any] = {
    "object": {
        "id": "test-report-uuid",
        "name": "test_report",
        "createdBy": "TESTUSER",
        "version": 1,
    },
    "transferableContent": {
        "content": _SAMPLE_BIRD_XML,
    },
}


def _build_sas_blob(envelope: dict[str, Any] | None = None) -> str:
    """Build a base64-encoded SAS report blob from an envelope dict."""
    env = envelope or _SAMPLE_ENVELOPE
    json_bytes = json.dumps(env, ensure_ascii=False).encode("utf-8")
    compressed = zlib.compress(json_bytes)
    raw = _SAS_HEADER + compressed
    return base64.b64encode(raw).decode("ascii")


@pytest.fixture()
def sample_bird_xml() -> str:
    """Sample BIRD XML string with CasResource and WebContent."""
    return _SAMPLE_BIRD_XML


@pytest.fixture()
def sample_envelope() -> dict[str, Any]:
    """Sample JSON envelope wrapping BIRD XML."""
    return dict(_SAMPLE_ENVELOPE)


@pytest.fixture()
def sas_report_blob() -> str:
    """Real-format base64 SAS report blob (header + zlib + JSON + BIRD XML)."""
    return _build_sas_blob()


@pytest.fixture()
def sas_report_config() -> TransformConfig:
    """TransformConfig with sas_report and patch_test chains."""
    return TransformConfig(
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
            "patch_test": TransformChainConfig(
                name="patch_test",
                preset="sas_report",
                patch=PatchConfig(
                    replace={
                        "https://old-host.example.com/": "https://new-host.example.com/",
                        'library="CASUSER"': 'library="PROD_LIB"',
                    },
                ),
            ),
        },
    )


@pytest.fixture()
def minimal_config() -> TransformConfig:
    """Minimal TransformConfig with a single base64 chain."""
    return TransformConfig(
        chains={
            "b64_only": TransformChainConfig(
                name="b64_only",
                forward=(PrimitiveConfig(name="base64"),),
            ),
        },
    )
