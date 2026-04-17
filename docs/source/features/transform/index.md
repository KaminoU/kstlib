# Transform

Bidirectional data transformation engine for round-trip workflows
(decode, patch, re-encode) on nested binary blobs. Domain-agnostic:
the engine knows nothing about SAS, Viya, or any specific platform.

## TL;DR

```python
from kstlib.transform import transform

# Decode a base64+zlib+JSON+XML blob, patch a hostname inside the
# inner XML, and re-encode back to the exact same format
patched_blob = transform(
    blob_b64_string,
    chain_name="patch_report",
)
```

The chain definition lives in `kstlib.conf.yml`:

```yaml
transforms:
  chains:
    sas_report:
      forward:
        - base64
        - zlib:
            skip_bytes: 3
        - json:
            extract: "transferableContent.content"
      backward:
        - json:
            wrap: "transferableContent.content"
        - zlib:
            prepend_bytes: "4d1504"
        - base64

    patch_report:
      preset: sas_report
      patch:
        scope: blob
        replace:
          "https://old-host/": "https://new-host/"
```

## Concept: preset vs usage pattern

Transform chains follow a two-tier convention:

1. **Preset** : a reusable decode/encode chain. Define it once,
   reference it from multiple usage chains. A preset has a `forward:`
   block (and optionally `backward:`) but **no `patch:`**.
2. **Usage** : a chain that inherits the preset's encode/decode pipeline
   via `preset:` and adds its own `patch:` block (or
   `composed_patch:` for surgical workflows).

```yaml
chains:
  # PRESET: define once, reuse many times
  sas_report:
    forward: [base64, {zlib: {skip_bytes: 3}}, {json: {extract: "..."}}]
    backward: [{json: {wrap: "..."}}, {zlib: {prepend_bytes: "4d1504"}}, base64]

  # USAGE: inherit the preset, add a specific patch
  patch_dev:
    preset: sas_report
    patch:
      replace: {"prod-host": "dev-host"}

  patch_prod:
    preset: sas_report
    patch:
      replace: {"dev-host": "prod-host"}
```

This separation lets you maintain one decode/encode pipeline definition
across many environment-specific patches without duplication.

```{note}
Chained presets are not supported: a preset cannot itself reference
another preset via `preset:`. The validation enforces this at
config-load time.
```

## The 5 primitives

Each primitive is bidirectional. The `forward` direction decodes /
parses, the `backward` direction re-encodes / serializes.

### base64

```yaml
forward:
  - base64        # str (b64) -> bytes
backward:
  - base64        # bytes -> str (b64)
```

Pure RFC 4648 base64 encoding. Three options support proprietary
wire formats like SAS Viya report blobs:

| Option | Default | Purpose |
|---|---|---|
| `strict` | `true` | When `true`, reject any character outside the base64 alphabet (`A-Z`, `a-z`, `0-9`, `+`, `/`, `=`). When `false`, strip non-alphabet chars silently before decoding. |
| `strip_prefix` | `null` | Literal string removed from the start of the input before decoding. No-op if the input does not start with it (allows mixed blobs). Max 32 chars. |
| `prefix` | `null` | Literal string prepended to the base64 result on encode. Mirrors `strip_prefix` on the backward path. Max 32 chars. |

```yaml
# SAS Viya report blob: "TRUE###" prefix where ### is a non-alphabet
# separator that strict mode would reject.
forward:
  - base64:
      strict: false             # tolerate ### separator
      strip_prefix: "TRUE###"   # remove SAS marker before decode

backward:
  - base64:
      prefix: "TRUE###"         # re-add SAS marker after encode
```

The prefix `"TRUE"` is a clever trick: those 4 base64 chars decode to
exactly `M\x15\x04` (the SAS proprietary 3-byte header). The `###`
that follows is a separator that lenient base64 decoders skip. By
stripping `"TRUE###"` first and decoding the rest, you get the raw
zlib stream directly without needing `skip_bytes` on the next stage.

### bytes

```yaml
forward:
  - bytes         # bytes -> str (utf-8)
backward:
  - bytes         # str -> bytes (utf-8)
```

Used to bridge between binary and string-typed primitives. Accepts
an `encoding` option (default `utf-8`).

### zlib

```yaml
forward:
  - zlib          # compressed -> bytes
backward:
  - zlib          # bytes -> compressed
```

| Option | Default | Purpose |
|---|---|---|
| `skip_bytes` | `null` | Strip N leading bytes before decompression. Useful for legacy formats that prepend a header to the zlib stream. |
| `prepend_bytes` | `null` | Hex string prepended after compression. Mirror of `skip_bytes`. |
| `level` | `-1` | Compression level. `-1` means "Python default" (typically 6). Range `0` (no compression) to `9` (maximum). |

```yaml
# Maximum compression for the SAS Viya backward chain
backward:
  - zlib:
      level: 9        # smallest output, slowest
```

`skip_bytes` cannot be auto-reversed (the engine cannot guess what bytes
to re-prepend), so any chain that uses it must declare an explicit
`backward:` block with `prepend_bytes`.

```{tip}
Modern SAS Viya workflows should prefer the prefix-based approach
(see the `base64` primitive's `strip_prefix` / `prefix` options) over
the legacy `skip_bytes` / `prepend_bytes` pair. The prefix approach is
simpler, configurable from YAML alone, and avoids byte-counting math.
```

The decompressor enforces a hard ratio limit (max 100x expansion) and
an absolute size limit (200 MB) to prevent zlib bombs.

### json

```yaml
forward:
  - json          # str -> dict
backward:
  - json          # dict -> str (UTF-8)
```

Standard JSON parsing. Four options on the serialize side:

| Option | Default | Purpose |
|---|---|---|
| `extract` | `null` | Forward-only. Drill into a nested envelope (dot-notation path). |
| `wrap` | `null` | Backward-only. Restore the value into the envelope captured during forward. |
| `minify` | `false` | When `true`, output uses compact `separators=(",", ":")` (no whitespace). Useful before zlib compression (denser input compresses better). |
| `ensure_ascii` | `false` | When `true`, escape non-ASCII chars to `\uXXXX`. **kstlib default is `false`**, which diverges from Python stdlib (`true`) to preserve Unicode content (French, Japanese, etc.) without bloating the output. |

```{warning}
The kstlib `ensure_ascii` default is `false`, NOT `true` like Python
stdlib. This is an intentional divergence: SAS Viya report blobs
(and many other real-world payloads) contain accented characters
(`café`, `données`) that would otherwise be escaped to `caf\u00e9`
and roughly DOUBLE the JSON size before compression.
```

`extract` / `wrap` are useful for envelope-style payloads:

```yaml
forward:
  - json:
      extract: "transferableContent.content"   # Drill into the envelope

backward:
  - json:
      wrap: "transferableContent.content"      # Restore the envelope
```

The forward path stores the original envelope internally
(in `_ChainContext.json_envelopes`) so the backward path can rebuild
the exact same structure even when only the inner payload was patched.
This makes the round-trip lossless.

### xml

```yaml
forward:
  - xml           # str -> ElementTree.Element
backward:
  - xml           # Element -> str
```

Uses `defusedxml` if available (recommended for security). DOCTYPE
declarations are rejected by default to prevent XXE attacks and
billion-laughs expansion.

The patch stage operates directly on the XML string before re-parsing,
which is faster and more flexible than walking the Element tree.

## SAS Viya blob formats

SAS Viya transfer packages use **two distinct blob formats** depending
on the type of object being serialized. The transform engine ships
two ready-to-use presets, one for each format.

### Format A: report blobs (compressed binary)

Used for objects with a large textual payload (BIRD XML reports,
data sources, ...). The wire format is:

```
"TRUE###" + base64(zlib(JSON envelope))
```

- `"TRUE"` is 4 base64 characters that decode to `M\x15\x04`, the
  3-byte SAS proprietary header
- `"###"` is a SAS proprietary separator (NOT in the base64 alphabet,
  must be stripped before strict decoding)
- The remainder is base64-encoded zlib-compressed JSON envelope
  containing the inner payload (e.g. BIRD XML)

The clever bit: stripping `"TRUE###"` and then base64-decoding the
rest yields a raw zlib stream directly, with no additional `skip_bytes`
needed. This is **Approach A** and matches the actual SAS wire format
bit-for-bit.

### Format B: metadata blobs (plain JSON)

Used for small metadata objects (folders, files, ACLs, ...). The
wire format is much simpler:

```
base64(JSON document)
```

No prefix, no compression, no proprietary header. Just plain
base64-encoded JSON.

### The two presets

```yaml
transforms:
  chains:

    # PRESET: sas_report (Format A - compressed binary)
    sas_report:
      forward:
        - base64:
            strict: false             # tolerate ### separator
            strip_prefix: "TRUE###"   # strip SAS marker
        - zlib                        # no skip_bytes - Approach A
        - json:
            extract: "transferableContent.content"
      backward:
        - json:
            wrap: "transferableContent.content"
            minify: true              # compact before compression
            ensure_ascii: false       # preserve French/Unicode
        - zlib:
            level: 9                  # max compression
        - base64:
            prefix: "TRUE###"         # re-add SAS marker

    # PRESET: sas_metadata (Format B - plain JSON)
    sas_metadata:
      forward:
        - base64:
            strict: true              # pure base64, no SAS noise
        - json
      backward:
        - json:
            minify: true              # smaller output
            ensure_ascii: false       # preserve Unicode
        - base64
```

### Cross-format dispatch in user code

The transform engine itself does not auto-detect which format applies
to a given blob. The caller (a pipeline step or a Python script that
iterates the package) is responsible for picking the right preset
based on `transferObject.summary.type`:

```python
import json
from kstlib.transform import TransformChain, load_transform_config

config = load_transform_config()
report_chain = TransformChain.from_config("sas_report", config)
metadata_chain = TransformChain.from_config("sas_metadata", config)

with open("MyPackage.json") as f:
    pkg = json.load(f)

for detail in pkg["transferDetails"]:
    to = detail["transferObject"]
    obj_type = to.get("summary", {}).get("type")
    chain = report_chain if obj_type == "report" else metadata_chain
    to["content"] = chain.transform(to["content"])

with open("MyPackage_patched.json", "w") as f:
    json.dump(pkg, f, separators=(",", ":"), ensure_ascii=False)
```

```{note}
The `"TRUE###"` prefix is fully configurable. If SAS changes their
proprietary marker tomorrow (e.g. to `"TRUE|||"` or anything else),
you only need to update the YAML strings - no code change required.
This is the whole point of having `strip_prefix` and `prefix` as
data-driven YAML options instead of hardcoded constants.
```

## Forward / patch / backward

Every transform chain follows the same three-stage pipeline:

```
INPUT  -> [forward primitives] -> decoded data -> [patch] -> patched data -> [backward primitives] -> OUTPUT
```

A chain that does not declare a `patch` simply round-trips the data
through forward and backward (useful for verifying the integrity of
the encode/decode pipeline itself). A chain that does not declare a
`backward` block uses **auto-reverse** (see below).

## Auto-reverse rules

When a chain declares only `forward:` (no `backward:`), the engine
generates the backward chain by reversing the forward primitives in
order and swapping primitive options where needed:

| Forward primitive | Auto-reverse |
|-------------------|--------------|
| `base64` | `base64` |
| `bytes` | `bytes` (with same encoding) |
| `xml` | `xml` |
| `zlib` (no skip_bytes) | `zlib` |
| `zlib` with `skip_bytes` | **error** (cannot guess prepend_bytes) |
| `json` (no extract) | `json` |
| `json` with `extract: "a.b"` | `json` with `wrap: "a.b"` |

### The zlib skip_bytes exception

```yaml
# This chain WILL FAIL at config-load time
chains:
  bad_chain:
    forward:
      - base64
      - zlib:
          skip_bytes: 3      # Cannot auto-reverse: needs explicit prepend_bytes
```

Fix: declare an explicit `backward:` block with `prepend_bytes`:

```yaml
chains:
  good_chain:
    forward:
      - base64
      - zlib:
          skip_bytes: 3
    backward:
      - zlib:
          prepend_bytes: "4d1504"
      - base64
```

## Patches: replace vs callable

A `patch:` block applies between forward and backward. It is **mutually
exclusive** between two modes:

### Mode 1: replace (string substitution)

Simple key/value substitution applied to the decoded data (after the
forward chain). Works on strings and on serialized XML.

```yaml
patch:
  scope: blob                          # default - patch decoded data
  replace:
    "https://old-host/": "https://new-host/"
    'library="CASUSER"': 'library="PUBLIC"'
```

The replace map is applied in dict iteration order. There is no regex
support (use `callable` for regex needs). The engine enforces a
maximum of 100 entries per replace map, and 4096 chars per key/value.

```{note}
**Deprecated alias**: the field name `mapping:` is still accepted as a
deprecated alias for `replace:`. Setting `mapping:` emits a
`DeprecationWarning` and is silently copied to `replace:`. Migrate
existing configs to `replace:`.
```

### Mode 2: callable

For complex patches (regex, lookup tables, conditional logic, external
state), use a Python callable:

```yaml
patch:
  scope: blob
  callable: myproject.transforms:patch_function
  args:
    target_host: "{{target_host}}"     # Resolved from chain context
    cas_mapping: "{{cas_mapping}}"     # Resolved from chain context
```

The callable target follows the `module.path:function_name` convention.
The function is called as `func(decoded_data, **resolved_args)` and
must return the patched data.

`{{variable}}` references in `args` are resolved against the chain's
`context` dict at execution time, allowing dynamic values to be
injected from a pipeline step or any caller.

```{important}
External callables must be whitelisted in
`transforms.security.allowed_callable_modules`. A callable whose
module is not in the whitelist raises `TransformConfigError` at
config-load time, before any transformation runs.
```

## Patch scope: blob | outer | all

The `scope:` field controls **where** a `replace:` patch applies.

| | `scope: blob` (default) | `scope: outer` | `scope: all` |
|---|---|---|---|
| Decoded data (e.g. BIRD XML) | applied | not applied | applied |
| Outer wrapper (`metadata['outer']`) | not applied | applied | applied |
| `connectors[*].hints.xpath` | n/a | PROTECTED, never patched | PROTECTED, never patched |

`scope: blob` is the default and preserves the historical behavior:
the replace map is applied to the data decoded by the forward chain.

`scope: outer` and `scope: all` mutate a JSON wrapper passed by the
caller via the existing `metadata=` kwarg on `chain.transform()` /
`chain.patch()`. The wrapper lives **outside** the encoded blob:
think of `connectors[].uri` and `connectors[].hints.orig-uri` in a
SAS Viya `transferObject` document. Use these scopes when you need
to patch fields that the forward chain never touches.

```yaml
chains:
  patch_report_full:
    preset: sas_report
    patch:
      scope: all                       # patch BIRD XML AND outer wrapper
      replace:
        'library="CASUSER"': 'library="PUBLIC"'   # BIRD XML form
        'library=CASUSER':   'library=PUBLIC'      # connector URI form
        "https://old-host":  "https://new-host"
```

```python
import json
from kstlib.transform import TransformChain, load_transform_config

config = load_transform_config()
chain = TransformChain.from_config("patch_report_full", config)

wrapper = json.loads(transfer_object_json)
blob = wrapper["content"]
new_blob = chain.transform(blob, metadata={"outer": wrapper})
wrapper["content"] = new_blob
# wrapper is mutated in place by replace_outer_uris
```

If `scope:` is `outer` or `all` and `metadata['outer']` is missing,
the patch raises `PatchError` at execution time.

### Protected outer paths (xpath safety)

`replace_outer_uris` is the helper that powers `scope: outer` and
`scope: all`. It walks the wrapper recursively and applies the
replace map to every string value, **except** strings whose path
matches a `PROTECTED_OUTER_PATHS` entry.

The default blacklist contains one path:

```python
PROTECTED_OUTER_PATHS = frozenset({
    "connectors[*].hints.xpath",
})
```

| Path syntax | Meaning |
|---|---|
| `dict.key` | Match a dict key literally. |
| `[*]` | Match any list index (wildcard). |
| `dict.key[*].sub.key` | Mix of literal keys and list wildcards. |

The `connectors[*].hints.xpath` blacklist exists because SAS Viya
stores BIRD XPath pointers there. Patching these strings would break
the wrapper-to-content coherence and silently corrupt the report.

```{warning}
**`connectors[*].hints.xpath` is ALWAYS protected.** Even with
`scope: all`, even with custom replace maps, it is never modified.
```

You can extend or replace the blacklist by passing a custom
`protected_paths` to `replace_outer_uris` directly:

```python
from kstlib.transform import replace_outer_uris

n = replace_outer_uris(
    wrapper,
    {"old": "new"},
    protected_paths=frozenset({"my.field", "items[*].immutable"}),
)
```

The function returns the number of strings that were modified.

## Composed patches: surgical multi-object workflows

Plain `patch:` applies to **every** object in a workflow. When a
package contains many objects (e.g. 200 reports) and each needs a
different replace map, use `composed_patch:` instead.

A composed patch references **other chains** by name and applies their
`patch` block conditionally. Two layers exist:

- `global_patches`: applied to **every** object regardless of metadata
- `targeted_patches`: applied only when the object metadata matches a filter

```yaml
chains:
  # "Patch-only" reusable building blocks (no forward/backward)
  remap_host:
    patch:
      replace:
        "https://source.res.private/": "https://target.res.private/"

  remap_caslib_global:
    patch:
      replace:
        'library="CASUSER"': 'library="PROD_GLOBAL_LIB"'

  remap_caslib_r220:
    patch:
      replace:
        'library="CASUSER"': 'library="R220_DEDICATED_LIB"'

  # The orchestrator: inherits forward/backward from sas_report,
  # composes the building blocks via global_patches + targeted_patches
  patch_report_composed:
    preset: sas_report

    global_patches:
      - remap_host             # Applied to EVERY object

    targeted_patches:
      - filter:
          content_type: report
          name: "R220_*"
        patches:
          - remap_caslib_r220

      - filter:
          content_type: report
          name: "*"            # Fallback for other reports
        patches:
          - remap_caslib_global
```

### Cascade: last applied wins (inverse of CSS)

```{warning}
**Cascade is by declaration order, NOT by filter specificity.** This is
the **inverse of CSS**.

Order your `targeted_patches` from **most general to most specific**.
The last applied patch overwrites earlier ones on conflict.
```

Concrete example with the config above:

```python
from kstlib.transform import transform

# Object 1: matches both R220_* and the "*" fallback
result_r220 = transform(
    blob_b64,
    "patch_report_composed",
    metadata={"content_type": "report", "name": "R220_ASTRO"},
)
# Apply order: remap_host -> remap_caslib_r220 -> remap_caslib_global
# Final caslib: PROD_GLOBAL_LIB (the wildcard fallback wins because
# it is declared LAST in targeted_patches)

# Object 2: matches only the "*" fallback
result_orion = transform(
    blob_b64,
    "patch_report_composed",
    metadata={"content_type": "report", "name": "ORION_FOO"},
)
# Apply order: remap_host -> remap_caslib_global
# Final caslib: PROD_GLOBAL_LIB
```

If you want R220 reports to keep their dedicated caslib, **declare the
specific filter LAST** so it wins:

```yaml
targeted_patches:
  - filter: {name: "*"}             # General first (will be overridden)
    patches: [remap_caslib_global]

  - filter: {name: "R220_*"}        # Specific last (final winner for R220)
    patches: [remap_caslib_r220]
```

This ordering convention is intentional: it mirrors the kstlib config
cascade philosophy (`kwargs > user config > preset > defaults`) where
the most explicit override always wins.

### Filter syntax

A filter combines two fields, ANDed together:

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `content_type` | string | `"*"` (any) | Exact match against `metadata["content_type"]` |
| `name` | string (glob) | `"*"` (any) | `fnmatch` glob against `metadata["name"]` |

```yaml
- filter:
    content_type: report      # Exact: must equal "report"
    name: "R220_*"            # Glob: prefix match
  patches: [remap_caslib_r220]
```

The metadata dict is provided by the caller via the `metadata=`
keyword argument on `transform()` or `chain.transform()`. The transform
engine never reads metadata from the data itself: the caller is
responsible for extracting `content_type` and `name` from whatever
schema they use (e.g. `transferDetails[].transferObject.summary` in
the SAS Viya Transfer API).

```{note}
A `targeted_patches` entry with no filter (or with all wildcards)
matches every object and behaves like an additional `global_patches`
entry. The advantage of using `targeted_patches` with a `"*"` filter
over `global_patches` is **ordering control**: targeted_patches always
run AFTER global_patches.
```

### Patch-only chains

A chain that has only `patch` (no `forward`, no `preset`) is a
"patch-only" chain. It exists solely to be referenced from another
chain's `composed_patch.global_patches` or
`composed_patch.targeted_patches[*].patches`.

```yaml
chains:
  remap_host:
    # No forward, no preset, no backward. Just a patch building block.
    patch:
      replace:
        "https://source/": "https://target/"
```

Calling `TransformChain.transform()` directly on a patch-only chain
works as identity (`forward()` and `backward()` are no-ops because
the primitive list is empty), but it is not the intended use case.

## Security

### Callable whitelist

```yaml
transforms:
  security:
    allowed_callable_modules:
      - myproject.transforms
      - myproject.viya.patches
```

Only callables whose module path matches an entry in this list (or is
a sub-module of one) are allowed. The default is an empty whitelist,
which means **no external callables can be invoked**.

A callable target whose module is not whitelisted raises
`TransformConfigError` at config-load time, before any transformation
runs. Replace-based patches are not affected by the whitelist.

### Hard limits

| Parameter | Default | Hard Max |
|-----------|---------|----------|
| Input data size | 100 MB | 100 MB |
| JSON payload size | 50 MB | 50 MB |
| XML payload size | 50 MB | 50 MB |
| Decompressed size | 200 MB | 200 MB |
| Decompression ratio | 100x | 100x |
| Replace entries per patch | 100 | 100 |
| Replace key/value length | 4096 chars | 4096 chars |
| Named chains | 50 | 50 |
| Forward / backward chain length | 20 primitives | 20 primitives |
| Global patches per composition | 10 | 10 |
| Targeted patches per composition | 50 | 50 |
| Patches per targeted entry | 10 | 10 |
| Glob pattern length | 256 chars | 256 chars |

### Zlib bomb protection

The `zlib_decompress` primitive enforces both an absolute decompressed
size limit (200 MB) and a maximum decompression ratio (100x). A zlib
stream that expands beyond either threshold raises `DecompressError`
immediately, before allocating the full output buffer.

### XML security

The `xml_parse` primitive uses `defusedxml` if available (recommended).
DOCTYPE declarations are rejected by default to prevent XXE attacks
and billion-laughs entity expansion.

If `defusedxml` is not installed, the engine falls back to the stdlib
`xml.etree.ElementTree` parser with explicit DOCTYPE rejection layered
on top.

## YAML config reference

Complete schema with comments. All fields are optional unless marked
**required**:

```yaml
transforms:
  # Security: callable whitelist (default: empty = no callables allowed)
  security:
    allowed_callable_modules:
      - myproject.transforms       # Module path prefix

  # Named chain definitions
  chains:

    # Example 1: full chain with explicit forward + backward + patch
    my_chain:                      # **required** - chain name
      forward:                     # **required** unless preset is set
        - base64                   # Primitive name (string form)
        - zlib:                    # Primitive with options (dict form)
            skip_bytes: 3
        - json:
            extract: "path.to.field"
      backward:                    # Optional (auto-reversed if absent)
        - json:
            wrap: "path.to.field"
        - zlib:
            prepend_bytes: "4d1504"
        - base64
      patch:                       # Optional (no patching if absent)
        scope: blob                # blob | outer | all (default: blob)
        replace:                   # Mutually exclusive with callable
          "old": "new"
        callable: mod.path:fn      # Mutually exclusive with replace
        args:
          key: "{{var}}"           # Resolved from chain context

    # Example 2: chain that inherits a preset
    my_usage:
      preset: my_chain             # Mutually exclusive with forward
      patch:                       # Override the preset's patch
        scope: blob
        replace:
          "foo": "bar"

    # Example 3: chain with composed patch (mutually exclusive with patch)
    my_composed:
      preset: my_chain
      global_patches:              # List of chain names
        - other_chain_a

      targeted_patches:            # Conditional patches
        - filter:
            content_type: report
            name: "R220_*"
          patches:
            - other_chain_b
```

## Python API

### Convenience function

```python
from kstlib.transform import transform

# Loads config from kstlib.conf.yml automatically
result = transform(blob_b64, "patch_report")

# With metadata for composed_patch filter matching
result = transform(
    blob_b64,
    "patch_report_composed",
    metadata={"content_type": "report", "name": "R220_ASTRO"},
)
```

### Client instance

```python
from kstlib.transform import TransformChain, load_transform_config

config = load_transform_config()
chain = TransformChain.from_config("patch_report", config)

# Forward only
decoded = chain.forward(blob_b64)

# Patch only (operates on the already-decoded data)
patched = chain.patch(decoded)

# Backward only (must be called after forward to restore envelopes)
re_encoded = chain.backward(patched)

# Full round-trip
result = chain.transform(blob_b64)
```

### Programmatic construction

```python
from kstlib.transform import (
    TransformChain,
    TransformChainConfig,
    PrimitiveConfig,
    PatchConfig,
)

chain = TransformChain(
    TransformChainConfig(
        name="my_chain",
        forward=(
            PrimitiveConfig(name="base64"),
            PrimitiveConfig(name="zlib"),
            PrimitiveConfig(name="json"),
        ),
        patch=PatchConfig(replace={"foo": "bar"}),
    )
)

result = chain.transform(blob_b64_string)
```

## Integration with kstlib.pipeline

The transform engine integrates cleanly with `kstlib.pipeline` via the
`CallableStep`. A pipeline step can invoke `kstlib.transform.transform`
directly:

```yaml
pipelines:
  patch-and-upload:
    steps:
      - name: load
        type: shell
        command: "kstlib rapi download --out blob.json"

      - name: patch
        type: callable
        callable: kstlib.transform:transform
        args:
          - "{{blob_b64}}"           # Loaded from previous step
          - "patch_report"           # Chain name

      - name: upload
        type: shell
        command: "kstlib rapi upload --body @result.json"
```

For composed patches, pass `metadata=` as a kwarg via the callable
args (the syntax depends on your pipeline step setup).

## Examples

See `examples/transform/` for runnable demos:

- **`01_round_trip.py`** : programmatic chain construction with synthetic
  data, full forward + patch + backward, integrity verification
- **`02_config_driven.py`** : load a chain from `kstlib.conf.yml` and
  apply it via `TransformChain.from_config()`
- **`03_composed_patch.py`** : 3 synthetic objects (R220_foo, ORION_bar,
  OTHER_baz) demonstrating the global + targeted cascade with explicit
  before/after output, and `scope: all` mutating the outer wrapper for
  the R220 case
- **`04_outer_patch.py`** : the three `scope:` values (`blob`, `outer`,
  `all`) exercised in isolation on a synthetic SAS Viya transferObject,
  plus the `replace_outer_uris` standalone helper and a custom
  `protected_paths` blacklist

```{tip}
For complete API documentation including all classes, functions, and
exceptions, see {doc}`../../api/transform`.
```
