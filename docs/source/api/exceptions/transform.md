# Transform Exceptions

Exceptions for the bidirectional data transformation engine: chain
configuration, primitive execution, patching, and external callable
invocation.

## Exception hierarchy

```
TransformError (base)
├── TransformConfigError       # Invalid chain or primitive configuration
└── TransformChainError        # Chain execution failed
    ├── PrimitiveError         # A single primitive failed
    │   ├── DecodeError        # base64_decode / bytes_decode
    │   ├── DecompressError    # zlib_decompress (also bomb protection)
    │   ├── ParseError         # json_parse / xml_parse
    │   ├── PatchError         # Patch stage (mapping or callable)
    │   ├── SerializeError     # json_serialize / xml_serialize
    │   ├── CompressError      # zlib_compress
    │   └── EncodeError        # base64_encode / bytes_encode
    ├── CallableImportError    # Callable target cannot be imported
    └── CallableError          # Callable raised at execution
```

`TransformConfigError` also inherits from the standard library
`ValueError`, so callers can catch it via either base class.

## Common failure modes

- `TransformConfigError` is raised when a chain definition is invalid
  (unknown primitive, wrong type, missing required fields, mutually
  exclusive options set together, callable module not in the
  whitelist, server reference unknown). Always raised at config-load
  time, not at first invocation.
- `DecompressError` covers both standard zlib failures and the bomb
  protection trip (max ratio or absolute size exceeded).
- `ParseError` is raised for malformed JSON or XML input. The XML
  parser also rejects DOCTYPE declarations to prevent XXE attacks.
- `PatchError` indicates a problem during the patch stage, typically
  a mapping miss on a non-string field or a type mismatch.
- `CallableImportError` is raised when the callable target cannot be
  resolved (module not found, function not in module, or module not
  in the `transforms.security.allowed_callable_modules` whitelist).
- `CallableError` wraps any exception raised by an external callable
  during execution, preserving the original exception via `__cause__`.

## Usage patterns

### Handling chain configuration errors

```python
from kstlib.transform import load_transform_config
from kstlib.transform.exceptions import TransformConfigError

try:
    config = load_transform_config()
except TransformConfigError as e:
    logger.error(f"Invalid transforms config: {e}")
    # Common causes:
    # - Unknown primitive name
    # - zlib skip_bytes without explicit backward
    # - mapping AND callable both set on the same patch
    # - callable module not in allowed_callable_modules whitelist
    # - composed_patch references an unknown chain
```

### Handling decompression bombs

```python
from kstlib.transform import transform
from kstlib.transform.exceptions import DecompressError

try:
    result = transform(suspicious_blob, "decode_chain")
except DecompressError as e:
    logger.warning(f"Decompression aborted: {e}")
    # Either the absolute decompressed size or the ratio limit was hit.
    # Default limits: 200 MB absolute, 100x ratio.
```

### Handling external callable failures

```python
from kstlib.transform import transform
from kstlib.transform.exceptions import (
    CallableImportError,
    CallableError,
    TransformChainError,
)

try:
    result = transform(blob, "patch_dynamic")
except CallableImportError as e:
    logger.error(f"Callable cannot be imported: {e}")
    # Check that the module path is correct AND that it is whitelisted
    # in transforms.security.allowed_callable_modules.
except CallableError as e:
    logger.error(f"Callable raised: {e}")
    logger.error(f"Original error: {e.__cause__}")
    # The wrapped exception is available via __cause__.
```

### Safe wrapper pattern

```python
from kstlib.transform import transform
from kstlib.transform.exceptions import TransformError

def safe_transform(blob: str, chain_name: str, **kwargs) -> str | None:
    """Apply a transform chain with comprehensive error handling."""
    try:
        return transform(blob, chain_name, **kwargs)
    except TransformError as e:
        logger.error(f"Transform '{chain_name}' failed: {e}")
        return None
```

## API reference

```{eval-rst}
.. automodule:: kstlib.transform.exceptions
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```
