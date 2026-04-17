"""Programmatic round-trip transform example.

Demonstrates a full forward + patch + backward pipeline built without
any YAML config. Uses synthetic data so the script is self-contained
and runnable standalone.

Pipeline: base64 -> zlib -> json (extract inner XML) -> patch -> reverse

Usage:
    python examples/transform/01_round_trip.py
"""

from __future__ import annotations

import base64
import json
import zlib

from kstlib.transform import (
    PatchConfig,
    PrimitiveConfig,
    TransformChain,
    TransformChainConfig,
)


def _build_synthetic_blob() -> str:
    """Build a synthetic SAS-style report blob for the demo.

    Structure: base64( zlib( json envelope { transferableContent: { content: <inner xml> } } ) )

    The inner XML contains a hostname and a CAS library reference that
    we will patch in the round-trip below.
    """
    inner_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Report name="demo">\n'
        '  <DataSource url="https://source-host.example.com/data" />\n'
        '  <CasResource library="DEV_LIB" table="MYDATA" />\n'
        "</Report>\n"
    )
    envelope = {
        "object": {"id": "demo-uuid", "name": "demo_report"},
        "transferableContent": {"content": inner_xml},
    }
    json_bytes = json.dumps(envelope).encode("utf-8")
    compressed = zlib.compress(json_bytes)
    return base64.b64encode(compressed).decode("ascii")


def main() -> None:
    """Run the round-trip demo."""
    # 1. Build a synthetic input blob
    original_blob = _build_synthetic_blob()
    print(f"Input blob size: {len(original_blob)} chars (base64)")
    print(f"Input blob head: {original_blob[:60]}...")
    print()

    # 2. Build the transform chain programmatically.
    #    Note: zlib has no skip_bytes here, so the chain can use auto-reverse
    #    (no explicit backward block needed).
    chain = TransformChain(
        TransformChainConfig(
            name="demo_round_trip",
            forward=(
                PrimitiveConfig(name="base64"),
                PrimitiveConfig(name="zlib"),
                PrimitiveConfig(
                    name="json",
                    options={"extract": "transferableContent.content"},
                ),
            ),
            patch=PatchConfig(
                replace={
                    "https://source-host.example.com/": "https://target-host.example.com/",
                    'library="DEV_LIB"': 'library="PROD_LIB"',
                },
            ),
        )
    )

    # 3. Forward only: decode the blob to the inner XML string
    decoded = chain.forward(original_blob)
    print("Decoded inner XML:")
    print(decoded)
    print()

    # 4. Patch only: apply the string replace to the decoded XML
    patched = chain.patch(decoded)
    print("Patched inner XML:")
    print(patched)
    print()

    # 5. Backward only: re-encode the patched XML back to a base64 blob.
    #    The chain restores the JSON envelope automatically because the
    #    extract path was stored in the chain context during forward.
    re_encoded = chain.backward(patched)
    print(f"Re-encoded blob size: {len(re_encoded)} chars")
    print(f"Re-encoded blob head: {re_encoded[:60]}...")
    print()

    # 6. Round-trip integrity check: re-decode the patched blob and
    #    verify the patches actually landed in the wire format.
    raw = base64.b64decode(re_encoded)
    envelope = json.loads(zlib.decompress(raw))
    final_xml = envelope["transferableContent"]["content"]

    print("Final inner XML (after re-decode):")
    print(final_xml)
    print()

    # Assertions: this is what makes the demo a self-checking test.
    assert "https://target-host.example.com/" in final_xml, "host patch missing"
    assert "https://source-host.example.com/" not in final_xml, "old host still present"
    assert 'library="PROD_LIB"' in final_xml, "caslib patch missing"
    assert 'library="DEV_LIB"' not in final_xml, "old caslib still present"
    print("Round-trip integrity verified.")

    # 7. Convenience: TransformChain.transform() does forward + patch +
    #    backward in one call.
    print()
    print("--- Same result via chain.transform() one-shot call ---")
    one_shot = chain.transform(original_blob)
    assert one_shot == re_encoded, "one-shot transform diverged from manual round-trip"
    print(f"One-shot result: {len(one_shot)} chars (matches manual round-trip)")


if __name__ == "__main__":
    main()
