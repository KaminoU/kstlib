"""Composed patch demo: global + targeted with filter cascade.

Demonstrates how composed_patch applies different patches to different
objects in a multi-object workflow. Three synthetic objects are
processed by the same chain:

  - R220_foo    (matches the R220_* targeted filter)
  - ORION_bar  (matches only the wildcard fallback)
  - OTHER_baz   (matches only the wildcard fallback)

The chain `patch_production` (defined in kstlib.conf.yml) applies:

  1. global_patches:
     - patch_report                    (blob patch on ALL reports)

  2. targeted_patches (declaration order):
     - filter name=R220_*: patch_report_full   (scope: all - blob + outer)
     - filter name=*:      patch_report        (scope: blob - blob only)

Because patch_report_full uses scope: all, the demo passes a synthetic
outer JSON wrapper via metadata['outer'] for every object. Only the
R220_* object actually triggers patch_report_full, so only its outer
wrapper is mutated by replace_outer_uris. The other two objects flow
through patch_report (blob only) and their outer wrapper is left
untouched.

It also illustrates a subtle but important point about replace-based
patches: the "last applied wins" rule of composed patches only fires
when multiple patches share a common source pattern. With distinct
sources, an earlier patch can effectively shield its result from
later patches because the later source no longer exists in the
already-transformed data.

Usage:
    cd examples/transform
    python 03_composed_patch.py
"""

from __future__ import annotations

import base64
import copy
import json
import zlib
from typing import Any

from kstlib.config import load_config
from kstlib.transform import TransformChain, load_transform_config


def _build_blob_for(name: str) -> str:
    """Build a synthetic SAS Viya report blob (Approach A - TRUE### prefix).

    Matches the sas_report preset wire format:
        "TRUE###" + base64(zlib(json envelope))
    """
    inner_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<Report name="{name}">\n'
        '  <DataSource url="https://old-host.res.private/data" />\n'
        '  <CasResource library="CASUSER" table="MYDATA" />\n'
        "</Report>\n"
    )
    envelope = {
        "object": {"id": f"{name}-uuid", "name": name},
        "transferableContent": {"content": inner_xml},
    }
    json_bytes = json.dumps(envelope).encode("utf-8")
    compressed = zlib.compress(json_bytes)
    return "TRUE###" + base64.b64encode(compressed).decode("ascii")


def _build_synthetic_wrapper(name: str, blob: str) -> dict[str, Any]:
    """Build a minimal SAS Viya transferObject-like wrapper.

    Mirrors the shape of a real SAS Viya transferObject just enough to
    exercise replace_outer_uris on the connectors[].uri and
    connectors[].hints.orig-uri fields. The URI uses the
    ``library=CASUSER`` query-string style so the patch_report_full
    replace map can match it. The xpath inside hints is set to a
    string containing the literal "CASUSER" so the demo can confirm
    that PROTECTED_OUTER_PATHS leaves it untouched.
    """
    return {
        "summary": {"name": name, "type": "report"},
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
    """Extract the inner XML from a transformed blob (for inspection)."""
    # Strip TRUE### prefix (Approach A)
    if blob.startswith("TRUE###"):
        blob = blob[len("TRUE###") :]
    raw = base64.b64decode(blob)
    envelope = json.loads(zlib.decompress(raw))
    content: str = envelope["transferableContent"]["content"]
    return content


def _summarize_blob(label: str, blob: str) -> None:
    """Print the inner XML of a blob with a label."""
    xml = _decode_inner_xml(blob)
    print(f"--- {label} (blob / BIRD XML) ---")
    for line in xml.strip().splitlines():
        if "url=" in line or "library=" in line:
            print(f"  {line.strip()}")


def _summarize_outer(label: str, wrapper: dict[str, Any]) -> None:
    """Print the connector URIs and the protected xpath."""
    print(f"--- {label} (outer wrapper) ---")
    connector = wrapper["connectors"][0]
    print(f"  uri:           {connector['uri']}")
    print(f"  orig-uri:      {connector['hints']['orig-uri']}")
    print(f"  xpath (PROT):  {connector['hints']['xpath']}")
    print()


def main() -> None:
    """Run the composed_patch cascade demo."""
    load_config()
    config = load_transform_config()

    chain = TransformChain.from_config("patch_production", config)
    composed = chain._config.composed_patch
    assert composed is not None, "expected composed_patch on patch_production"
    print(f"Chain '{chain._config.name}' loaded.")
    print("  preset (forward + backward): inherited from sas_report")
    print(f"  global_patches: {list(composed.global_patches)}")
    print(f"  targeted_patches: {len(composed.targeted_patches)} entries")
    print()

    # Three synthetic objects with different names. Same input data,
    # different metadata -> different patches applied.
    objects = [
        ("R220_foo",   {"content_type": "report", "name": "R220_foo"}),
        ("ORION_bar", {"content_type": "report", "name": "ORION_bar"}),
        ("OTHER_baz",  {"content_type": "report", "name": "OTHER_baz"}),
    ]

    print("=== Applying patch_production to 3 objects ===")
    print()
    for name, metadata in objects:
        blob = _build_blob_for(name)
        wrapper = _build_synthetic_wrapper(name, blob)

        _summarize_blob(f"{name}: BEFORE", blob)
        _summarize_outer(f"{name}: BEFORE", wrapper)

        # Pass the wrapper via metadata['outer'] so scope: all in
        # patch_report_full can mutate connectors[].uri /
        # hints.orig-uri when the R220 filter matches. Use a deep
        # copy so each iteration starts from a fresh wrapper.
        result_blob = chain.transform(
            blob,
            metadata={**metadata, "outer": copy.deepcopy(wrapper)},
        )
        _summarize_blob(f"{name}: AFTER", result_blob)

        # Re-run with the live wrapper to capture the in-place mutation
        # for printing. (The previous call mutated the deepcopy.)
        live_wrapper = _build_synthetic_wrapper(name, blob)
        chain.transform(
            blob,
            metadata={**metadata, "outer": live_wrapper},
        )
        _summarize_outer(f"{name}: AFTER", live_wrapper)

    print("=== Cascade explanation ===")
    print()
    print("All 3 objects had their host rewritten and CASUSER -> PUBLIC")
    print("inside the BIRD XML via the global patch_report layer (scope: blob).")
    print()
    print("Only R220_foo additionally matched the targeted patch_report_full")
    print("layer (scope: all), which mutated the outer wrapper:")
    print("  - connectors[].uri:           CASUSER -> PUBLIC")
    print("  - connectors[].hints.orig-uri: CASUSER -> PUBLIC")
    print("  - connectors[].hints.xpath:    PROTECTED, never modified")
    print()
    print("ORION_bar and OTHER_baz only matched the wildcard fallback")
    print("(patch_report, scope: blob), so their outer wrappers are intact.")
    print()
    print("Important nuance: with replace-based patches, 'last applied wins'")
    print("is only true when both patches share an identical source string.")
    print("When the first patch transforms the data such that the second")
    print("patch's source can no longer match, the first patch's result")
    print("survives. To force a strict overwrite cascade, use callable-based")
    print("patches (which always execute their full logic regardless of")
    print("prior state).")


if __name__ == "__main__":
    main()
