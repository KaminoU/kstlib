"""Outer wrapper patch demo: scope: blob vs outer vs all.

Demonstrates the three values of `PatchConfig.scope` on a synthetic
SAS Viya transferObject. Each scope is exercised in isolation so the
output makes the difference obvious.

The synthetic wrapper has both:
  - the encoded BIRD XML blob in `wrapper["content"]`, decoded by
    the sas_report preset
  - a JSON connectors[] array next to it, which lives OUTSIDE the
    blob and contains a CASUSER reference in two places (.uri and
    .hints.orig-uri) plus a PROTECTED xpath that points to the
    BIRD content and must NEVER be touched.

Three chains are exercised:

  1. patch_report      scope: blob   patches BIRD XML inside the blob
  2. patch_report_full scope: all    patches blob AND outer connectors
  3. (inline)          scope: outer  patches the outer wrapper only

The fourth section runs replace_outer_uris directly without a chain
to show the helper as a standalone utility for caller code.

Usage:
    cd examples/transform
    python 04_outer_patch.py
"""

from __future__ import annotations

import base64
import json
import zlib
from typing import Any

from kstlib.config import load_config
from kstlib.transform import (
    PatchConfig,
    PrimitiveConfig,
    PROTECTED_OUTER_PATHS,
    TransformChain,
    TransformChainConfig,
    load_transform_config,
    replace_outer_uris,
)


def _build_blob() -> str:
    """Build a synthetic SAS Viya report blob (Approach A - TRUE### prefix)."""
    inner_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Report name="demo">\n'
        '  <DataSource url="https://old-host.res.private/data" />\n'
        '  <CasResource library="CASUSER" table="MYDATA" />\n'
        "</Report>\n"
    )
    envelope = {
        "object": {"id": "demo-uuid", "name": "demo_report"},
        "transferableContent": {"content": inner_xml},
    }
    json_bytes = json.dumps(envelope).encode("utf-8")
    compressed = zlib.compress(json_bytes)
    return "TRUE###" + base64.b64encode(compressed).decode("ascii")


def _build_wrapper(blob: str) -> dict[str, Any]:
    """Build a minimal SAS Viya transferObject-like wrapper.

    Includes the blob plus a connectors[] array with the typical
    triple: live uri, hints.orig-uri (traceability copy), and
    hints.xpath (PROTECTED - must never be touched). The URI uses
    the ``library=CASUSER`` query-string style to match the
    patch_report_full replace map.
    """
    return {
        "summary": {"name": "demo_report", "type": "report"},
        "content": blob,
        "connectors": [
            {
                "uri": "cas-shared-default;library=CASUSER;table=MYDATA",
                "hints": {
                    "orig-uri": "cas-shared-default;library=CASUSER;table=MYDATA",
                    "xpath": "/Report/CasResource[@library='CASUSER']",
                },
            }
        ],
    }


def _decode_inner_xml(blob: str) -> str:
    """Extract the inner XML from a blob (for inspection)."""
    if blob.startswith("TRUE###"):
        blob = blob[len("TRUE###") :]
    raw = base64.b64decode(blob)
    envelope = json.loads(zlib.decompress(raw))
    content: str = envelope["transferableContent"]["content"]
    return content


def _print_state(label: str, blob: str, wrapper: dict[str, Any]) -> None:
    """Print the BIRD XML inside the blob and the outer connector fields."""
    print(f"--- {label} ---")
    xml = _decode_inner_xml(blob)
    for line in xml.strip().splitlines():
        if "url=" in line or "library=" in line:
            print(f"  blob xml:    {line.strip()}")
    connector = wrapper["connectors"][0]
    print(f"  outer uri:   {connector['uri']}")
    print(f"  outer orig:  {connector['hints']['orig-uri']}")
    print(f"  PROT xpath:  {connector['hints']['xpath']}")
    print()


def _section(title: str) -> None:
    print("=" * 70)
    print(title)
    print("=" * 70)
    print()


def main() -> None:
    """Run the scope demo."""
    load_config()
    config = load_transform_config()
    print(f"PROTECTED_OUTER_PATHS = {sorted(PROTECTED_OUTER_PATHS)}")
    print()

    # ----------------------------------------------------------------
    # Section 1: scope: blob (default)
    # patch_report decodes the blob, patches the BIRD XML, re-encodes.
    # The outer wrapper is left untouched even if metadata['outer'] is
    # passed (because scope: blob does not look at it).
    # ----------------------------------------------------------------
    _section("1. scope: blob - patch_report (BIRD XML only)")
    blob = _build_blob()
    wrapper = _build_wrapper(blob)
    _print_state("BEFORE", blob, wrapper)

    chain_blob = TransformChain.from_config("patch_report", config)
    new_blob = chain_blob.transform(blob, metadata={"outer": wrapper})
    wrapper["content"] = new_blob

    _print_state("AFTER (blob patched, outer untouched)", new_blob, wrapper)
    assert "PUBLIC" in _decode_inner_xml(new_blob)
    assert "CASUSER" in wrapper["connectors"][0]["uri"]  # outer not touched

    # ----------------------------------------------------------------
    # Section 2: scope: all - patch_report_full
    # Same chain but scope: all also runs replace_outer_uris on the
    # outer wrapper. connectors[].uri and hints.orig-uri get patched;
    # hints.xpath is protected.
    # ----------------------------------------------------------------
    _section("2. scope: all - patch_report_full (BIRD XML + outer wrapper)")
    blob = _build_blob()
    wrapper = _build_wrapper(blob)
    _print_state("BEFORE", blob, wrapper)

    chain_all = TransformChain.from_config("patch_report_full", config)
    new_blob = chain_all.transform(blob, metadata={"outer": wrapper})
    wrapper["content"] = new_blob

    _print_state("AFTER (blob + outer patched, xpath PROTECTED)", new_blob, wrapper)
    assert "PUBLIC" in _decode_inner_xml(new_blob)
    assert "PUBLIC" in wrapper["connectors"][0]["uri"]
    assert "PUBLIC" in wrapper["connectors"][0]["hints"]["orig-uri"]
    assert "CASUSER" in wrapper["connectors"][0]["hints"]["xpath"]  # PROTECTED

    # ----------------------------------------------------------------
    # Section 3: scope: outer (inline programmatic chain)
    # Builds a chain in code with scope: outer and calls .patch()
    # directly. scope: outer is a side-effect-only patch on the
    # outer wrapper, so we use chain.patch() to demonstrate the
    # mutation in isolation. The blob argument flows through
    # untouched (scope: outer does not look at it).
    # ----------------------------------------------------------------
    _section("3. scope: outer - inline chain (outer wrapper only)")
    blob = _build_blob()
    wrapper = _build_wrapper(blob)
    _print_state("BEFORE", blob, wrapper)

    outer_only_chain = TransformChain(
        TransformChainConfig(
            name="patch_outer_only",
            forward=(PrimitiveConfig(name="bytes"),),
            patch=PatchConfig(
                scope="outer",
                replace={
                    "library=CASUSER": "library=PUBLIC",
                },
            ),
        )
    )
    # Call .patch() directly. scope: outer doesn't touch the data
    # argument, so the blob string passes through unchanged.
    same_blob = outer_only_chain.patch(blob, metadata={"outer": wrapper})

    _print_state("AFTER (outer patched, blob unchanged)", same_blob, wrapper)
    # Blob is unchanged because scope: outer does not touch the data
    assert same_blob == blob  # bit-for-bit identical
    assert "CASUSER" in _decode_inner_xml(same_blob)  # blob NOT patched
    assert "PUBLIC" in wrapper["connectors"][0]["uri"]  # outer IS patched
    assert "CASUSER" in wrapper["connectors"][0]["hints"]["xpath"]  # PROTECTED

    # ----------------------------------------------------------------
    # Section 4: replace_outer_uris standalone helper
    # Use the helper directly without any chain. Useful for caller
    # code that already has a wrapper in memory and wants to apply
    # arbitrary substitutions while keeping xpath protection.
    # ----------------------------------------------------------------
    _section("4. replace_outer_uris standalone helper")
    wrapper = _build_wrapper(_build_blob())
    print("BEFORE:")
    print(f"  uri:   {wrapper['connectors'][0]['uri']}")
    print(f"  orig:  {wrapper['connectors'][0]['hints']['orig-uri']}")
    print(f"  xpath: {wrapper['connectors'][0]['hints']['xpath']}")
    print()

    n = replace_outer_uris(
        wrapper,
        {"CASUSER": "PUBLIC"},
    )
    print(f"replace_outer_uris returned {n} (number of strings modified)")
    print()
    print("AFTER:")
    print(f"  uri:   {wrapper['connectors'][0]['uri']}")
    print(f"  orig:  {wrapper['connectors'][0]['hints']['orig-uri']}")
    print(f"  xpath: {wrapper['connectors'][0]['hints']['xpath']}  <- PROTECTED")
    print()

    # Custom protected_paths: protect a different field
    _section("5. Custom protected_paths blacklist")
    custom_wrapper = {
        "items": [
            {"name": "CASUSER_table", "tag": "CASUSER_tag"},
            {"name": "CASUSER_other", "tag": "CASUSER_other_tag"},
        ]
    }
    print("BEFORE:")
    print(json.dumps(custom_wrapper, indent=2))
    print()

    # Protect items[*].tag from being patched
    n = replace_outer_uris(
        custom_wrapper,
        {"CASUSER": "PUBLIC"},
        protected_paths=frozenset({"items[*].tag"}),
    )
    print(f"replace_outer_uris returned {n} (only .name fields, .tag protected)")
    print()
    print("AFTER:")
    print(json.dumps(custom_wrapper, indent=2))
    print()

    print("All assertions passed.")


if __name__ == "__main__":
    main()
