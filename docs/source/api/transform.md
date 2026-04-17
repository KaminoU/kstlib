# Bidirectional Data Transformation

Generic transformation engine that chains primitives (decode,
decompress, parse, patch, serialize, compress, encode) declared in
YAML. Domain-agnostic: knows nothing about SAS, Viya, or any specific
platform.

## Overview

The `transform` module provides a **declarative pipeline** for
round-trip data transformations. The typical use case is decoding a
nested binary blob (e.g. base64 + zlib + JSON envelope + XML payload),
patching the inner content, and re-encoding back to the exact same
format so the result can be re-uploaded to the source system.

```python
from kstlib.transform import TransformChain, TransformChainConfig, PrimitiveConfig, PatchConfig

chain = TransformChain(
    TransformChainConfig(
        name="decode_report",
        forward=(
            PrimitiveConfig(name="base64"),
            PrimitiveConfig(name="zlib", options={"skip_bytes": 3}),
            PrimitiveConfig(name="json", options={"extract": "transferableContent.content"}),
        ),
        backward=(
            PrimitiveConfig(name="json", options={"wrap": "transferableContent.content"}),
            PrimitiveConfig(name="zlib", options={"prepend_bytes": "4d1504"}),
            PrimitiveConfig(name="base64"),
        ),
        patch=PatchConfig(replace={"old-host.example.com": "new-host.example.com"}),
    )
)

# Full round-trip: forward + patch + backward
patched_blob = chain.transform(blob_b64_string)
```

**Benefits:**

- **Single source of truth**: chain definitions live in YAML, not
  scattered in code
- **Lossless round-trip**: JSON envelopes are preserved during patching
- **Composable**: presets can be reused and overridden with custom patches
- **Hardened**: zlib bomb protection, XML security, callable whitelist,
  size limits

## Primitives

The transform engine ships with 5 built-in primitives. Each one is
bidirectional (forward + backward) and can be chained in any order.

| Primitive | Forward | Backward | Common options |
|-----------|---------|----------|----------------|
| `base64` | str -> bytes | bytes -> str | `strict`, `strip_prefix`, `prefix` |
| `bytes` | bytes -> str | str -> bytes | `encoding` (default `utf-8`) |
| `zlib` | compressed -> bytes | bytes -> compressed | `skip_bytes`, `prepend_bytes`, `level` |
| `json` | str -> dict | dict -> str | `extract`, `wrap` (dot-notation) |
| `xml` | str -> Element | Element -> str | `encoding` |

### zlib special options

The `zlib` primitive supports two options to handle SAS-style proprietary
headers prepended before the actual zlib stream:

```yaml
# Forward: skip the first 3 bytes (proprietary header)
- zlib:
    skip_bytes: 3

# Backward: re-prepend the same 3 bytes (hex-encoded)
- zlib:
    prepend_bytes: "4d1504"   # M\x15\x04
```

`skip_bytes` cannot be auto-reversed, so a chain that uses it must
declare an explicit `backward:` block with `prepend_bytes`.

### json extract/wrap for envelope-style payloads

The `json` primitive lets you drill into a nested envelope on the
forward path and reconstruct it on the backward path:

```yaml
forward:
  - base64
  - zlib
  - json:
      extract: "transferableContent.content"   # Drill into the envelope

backward:
  - json:
      wrap: "transferableContent.content"      # Restore the envelope
  - zlib
  - base64
```

The original envelope is stored internally during forward execution
(in `_ChainContext.json_envelopes`) and restored on backward, ensuring
the round-trip is lossless even when only the inner payload was patched.

## Configuration

### In kstlib.conf.yml

Define chains in your main configuration file under `transforms:`:

```yaml
transforms:
  security:
    allowed_callable_modules:
      - myproject.transforms

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
      preset: sas_report      # inherit forward + backward from sas_report
      patch:
        scope: blob           # blob | outer | all (default: blob)
        replace:
          "https://old-host.example.com/": "https://new-host.example.com/"
          'library="CASUSER"': 'library="PUBLIC"'
```

### Preset inheritance

A chain can inherit forward + backward from another chain via `preset:`.
The child overrides only `patch` (or `composed_patch`):

```yaml
chains:
  sas_report:
    forward: [...]
    backward: [...]

  patch_report:
    preset: sas_report      # forward + backward inherited
    patch:
      scope: blob
      replace:
        "old": "new"
```

Chained presets are not supported (a preset cannot itself reference
another preset). The validation enforces this at config-load time.

### Patches: replace vs callable

A `PatchConfig` is mutually exclusive between `replace:` and `callable:`:

```yaml
# Option 1: simple string substitution
patch:
  scope: blob
  replace:
    "old-value": "new-value"
    'library="CASUSER"': 'library="PUBLIC"'

# Option 2: external Python callable
patch:
  scope: blob
  callable: myproject.transforms:patch_function
  args:
    target_host: "{{target_host}}"   # Resolved from pipeline context
    cas_mapping: "{{cas_mapping}}"
```

The `scope:` field is one of `blob` (default), `outer`, or `all`.
See {doc}`../features/transform/index` for the full scope semantics
table and `replace_outer_uris` helper.

```{note}
**Deprecated alias**: the field name `mapping:` is still accepted as
a deprecated alias for `replace:` and emits a `DeprecationWarning`
when used. Migrate existing configs to `replace:`.
```

The `callable` target follows the `module.path:function_name` convention.
Allowed callable modules must be whitelisted in
`transforms.security.allowed_callable_modules`.

`{{variable}}` references in `args` are resolved against the chain's
context dict, allowing dynamic values to be injected from a pipeline
step or any caller.

### Composed patches: surgical multi-object workflows

When a transformation needs to apply different patches to different
objects (e.g. some reports need a specific caslib while others need
the generic one), use `composed_patch` instead of an inline `patch`:

```yaml
chains:
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

  patch_report_composed:
    preset: sas_report

    global_patches:
      - remap_host             # Applied to every object

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

```{warning}
**Cascade is by declaration order, NOT by filter specificity.** This is
the **inverse of CSS**. Order your `targeted_patches` from most general
to most specific because the last applied patch wins on conflict.
```

A "patch-only" chain (one with only `patch` and no `forward`/`preset`)
is allowed and is designed to be referenced from a `composed_patch`.
While it *can* be instantiated and invoked directly, its primary use
case is as a named patch target for composed patch orchestration.

See {doc}`../features/transform/index` for the full decision matrix and
runtime behavior.

## Python API

### Quick Functions

```python
from kstlib.transform import transform, load_transform_config

# Convenience function: loads config from kstlib.conf.yml and applies
result = transform(blob_b64, "patch_report")

# Pass metadata for composed_patch filter matching
result = transform(
    blob_b64,
    "patch_report_composed",
    metadata={"content_type": "report", "name": "R220_ASTRO"},
)
```

### Client Instance

```python
from kstlib.transform import TransformChain, load_transform_config

config = load_transform_config()

# Build a chain from a named config entry (resolves preset inheritance)
chain = TransformChain.from_config("patch_report", config)

# Forward only
decoded = chain.forward(blob_b64)

# Backward only (must be called after forward to restore envelopes)
re_encoded = chain.backward(decoded)

# Full round-trip
patched = chain.transform(blob_b64)

# With composed_patch metadata
patched = chain.transform(
    blob_b64,
    metadata={"content_type": "report", "name": "R220_ASTRO"},
)
```

### Programmatic Construction

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
            PrimitiveConfig(name="json"),
        ),
        patch=PatchConfig(replace={"foo": "bar"}),
    )
)

result = chain.transform(blob_b64_string)
```

## Security and Hard Limits

The transform engine implements deep defense against malformed or
malicious input.

### Callable whitelist

External callables can only be invoked if their module is listed in
`transforms.security.allowed_callable_modules`:

```yaml
transforms:
  security:
    allowed_callable_modules:
      - myproject.transforms
      - myproject.viya.patches
```

A callable target whose module is not in the whitelist raises
`TransformConfigError` at config-load time, before any transformation
runs.

### Size limits

| Limit | Default | Hard Max |
|-------|---------|----------|
| Input data size | 100 MB | 100 MB |
| JSON payload size | 50 MB | 50 MB |
| XML payload size | 50 MB | 50 MB |
| Decompressed size | 200 MB | 200 MB |
| Decompression ratio | 100x | 100x |
| Mapping entries per patch | 100 | 100 |
| Named chains | 50 | 50 |
| Global patches per composition | 10 | 10 |
| Targeted patches per composition | 50 | 50 |
| Patches per targeted entry | 10 | 10 |

### Zlib bomb protection

The `zlib_decompress` primitive enforces both an absolute decompressed
size limit and a maximum decompression ratio. A zlib stream that
expands beyond either threshold raises `DecompressError` immediately.

### XML security

The `xml_parse` primitive uses `defusedxml` if available (recommended).
DOCTYPE declarations are rejected by default to prevent XXE attacks
and billion-laughs expansion.

## Integration with kstlib.pipeline

The transform engine integrates cleanly with `kstlib.pipeline` via the
`CallableStep`. A pipeline step can invoke `kstlib.transform.transform`
with the chain name as the first argument and pass the loaded data as
a callable arg:

```yaml
pipelines:
  patch-and-upload:
    steps:
      - name: patch
        type: callable
        callable: kstlib.transform:transform
        args:
          - "{{loaded_blob}}"
          - "patch_report"

      - name: upload
        type: shell
        command: "kstlib rapi upload --body @result.json"
```

## API Reference

### Chain

```{eval-rst}
.. autoclass:: kstlib.transform.TransformChain
   :members:
   :show-inheritance:

.. autofunction:: kstlib.transform.transform

.. autofunction:: kstlib.transform.replace_outer_uris
```

### Constants

```{eval-rst}
.. autodata:: kstlib.transform.PATCH_SCOPE_VALUES

.. autodata:: kstlib.transform.PROTECTED_OUTER_PATHS
```

### Configuration

```{eval-rst}
.. autoclass:: kstlib.transform.TransformConfig
   :members:
   :show-inheritance:
   :no-index:

.. autoclass:: kstlib.transform.TransformChainConfig
   :members:
   :show-inheritance:
   :no-index:

.. autoclass:: kstlib.transform.PrimitiveConfig
   :members:
   :show-inheritance:
   :no-index:

.. autoclass:: kstlib.transform.PatchConfig
   :members:
   :show-inheritance:
   :no-index:

.. autoclass:: kstlib.transform.FilterConfig
   :members:
   :show-inheritance:
   :no-index:

.. autoclass:: kstlib.transform.TargetedPatchConfig
   :members:
   :show-inheritance:
   :no-index:

.. autoclass:: kstlib.transform.ComposedPatchConfig
   :members:
   :show-inheritance:
   :no-index:

.. autofunction:: kstlib.transform.load_transform_config
```

### Primitives

```{eval-rst}
.. autofunction:: kstlib.transform.base64_decode

.. autofunction:: kstlib.transform.base64_encode

.. autofunction:: kstlib.transform.bytes_decode

.. autofunction:: kstlib.transform.bytes_encode

.. autofunction:: kstlib.transform.zlib_compress

.. autofunction:: kstlib.transform.zlib_decompress

.. autofunction:: kstlib.transform.json_parse

.. autofunction:: kstlib.transform.json_serialize

.. autofunction:: kstlib.transform.xml_parse

.. autofunction:: kstlib.transform.xml_serialize
```

### Exceptions

```{eval-rst}
.. autoexception:: kstlib.transform.TransformError
   :members:
   :show-inheritance:

.. autoexception:: kstlib.transform.TransformConfigError
   :members:
   :show-inheritance:

.. autoexception:: kstlib.transform.TransformChainError
   :members:
   :show-inheritance:

.. autoexception:: kstlib.transform.PrimitiveError
   :members:
   :show-inheritance:

.. autoexception:: kstlib.transform.DecodeError
   :members:
   :show-inheritance:

.. autoexception:: kstlib.transform.DecompressError
   :members:
   :show-inheritance:

.. autoexception:: kstlib.transform.ParseError
   :members:
   :show-inheritance:

.. autoexception:: kstlib.transform.PatchError
   :members:
   :show-inheritance:

.. autoexception:: kstlib.transform.SerializeError
   :members:
   :show-inheritance:

.. autoexception:: kstlib.transform.CompressError
   :members:
   :show-inheritance:

.. autoexception:: kstlib.transform.EncodeError
   :members:
   :show-inheritance:

.. autoexception:: kstlib.transform.CallableError
   :members:
   :show-inheritance:

.. autoexception:: kstlib.transform.CallableImportError
   :members:
   :show-inheritance:
```
