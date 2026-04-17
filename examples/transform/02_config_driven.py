"""Config-driven transform example.

Loads a chain from kstlib.conf.yml via load_transform_config() and
TransformChain.from_config(), then applies it to a synthetic blob.

The relevant chain in kstlib.conf.yml is `patch_report`, which inherits
the encode/decode pipeline from the `sas_report` preset and overrides
only the patch block. It uses scope: blob (the default) to patch only
the decoded BIRD XML inside the blob.

Usage:
    cd examples/transform
    python 02_config_driven.py
"""

from __future__ import annotations

import base64
import json
import zlib

from kstlib.config import load_config
from kstlib.transform import TransformChain, load_transform_config


def _build_synthetic_blob() -> str:
    """Build a synthetic SAS Viya report blob (Approach A - TRUE### prefix).

    Matches the wire format expected by the `sas_report` preset in
    kstlib.conf.yml:

        "TRUE###" + base64(zlib(json envelope))

    where "TRUE" is 4 base64 chars that decode to the SAS proprietary
    3-byte header M\\x15\\x04, and "###" is the SAS separator.
    """
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


def _decode_for_inspection(blob: str) -> str:
    """Decode a blob the same way the chain does, to inspect the result."""
    # Strip TRUE### prefix (Approach A: the prefix encodes the SAS header)
    if blob.startswith("TRUE###"):
        blob = blob[len("TRUE###") :]
    raw = base64.b64decode(blob)
    envelope = json.loads(zlib.decompress(raw))
    content: str = envelope["transferableContent"]["content"]
    return content


def main() -> None:
    """Run the config-driven demo."""
    # Load kstlib.conf.yml from the current directory.
    # Run the script with `cd examples/transform` first to pick up the
    # local config (otherwise it falls back to the user / system config).
    load_config()

    # Load the transforms section into a TransformConfig dataclass tree.
    config = load_transform_config()
    print(f"Loaded {len(config.chains)} chains from kstlib.conf.yml:")
    for name in sorted(config.chains):
        print(f"  - {name}")
    print()

    # Build a usable TransformChain from a named entry. The from_config
    # call resolves preset inheritance automatically: patch_report
    # inherits the forward + backward chain from sas_report and adds
    # its own patch block on top.
    chain = TransformChain.from_config("patch_report", config)
    patch_cfg = chain._config.patch
    assert patch_cfg is not None
    print(f"Chain '{chain._config.name}' resolved.")
    print(f"  forward primitives:  {[p.name for p in chain._config.forward]}")
    print(f"  backward primitives: {[p.name for p in chain._backward]}")
    print(f"  patch scope:         {patch_cfg.scope}")
    print(f"  patch replace:       {patch_cfg.replace}")
    print()

    # Build a synthetic blob and run the full transform.
    blob = _build_synthetic_blob()
    print(f"Input blob size: {len(blob)} chars")
    print()

    print("--- Original inner XML (before patching) ---")
    print(_decode_for_inspection(blob))

    # One-shot transform: forward + patch + backward
    result = chain.transform(blob)
    print(f"Transform output: {len(result)} chars")
    print()

    print("--- Patched inner XML (after round-trip) ---")
    patched_xml = _decode_for_inspection(result)
    print(patched_xml)

    # Self-checking assertions
    assert "https://new-host.res.private" in patched_xml, "host patch missing"
    assert "https://old-host.res.private" not in patched_xml, "old host still present"
    assert 'library="PUBLIC"' in patched_xml, "caslib patch missing"
    assert 'library="CASUSER"' not in patched_xml, "old caslib still present"
    print("Config-driven transform verified.")


if __name__ == "__main__":
    main()
