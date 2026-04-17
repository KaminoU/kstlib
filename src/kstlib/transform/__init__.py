"""Generic bidirectional data transformation engine.

Chain primitives (decode, decompress, parse, patch, serialize, compress,
encode) declared in YAML. Domain-agnostic: knows nothing about SAS, Viya,
or any specific platform.

Quick Start:

    Programmatic::

        from kstlib.transform import TransformChain, TransformChainConfig, PrimitiveConfig

        chain = TransformChain(TransformChainConfig(
            name="decode",
            forward=(PrimitiveConfig(name="base64"),),
        ))
        decoded = chain.forward(b64_string)

    Config-driven::

        from kstlib.transform import load_transform_config, TransformChain

        config = load_transform_config()
        chain = TransformChain.from_config("sas_report", config)
        result = chain.transform(blob)

    Convenience function::

        from kstlib.transform import transform

        result = transform(blob, "patch_report")
"""

from kstlib.transform.chain import (
    PROTECTED_OUTER_PATHS,
    TransformChain,
    replace_outer_uris,
    transform,
)
from kstlib.transform.config import (
    PATCH_SCOPE_VALUES,
    ComposedPatchConfig,
    FilterConfig,
    PatchConfig,
    PrimitiveConfig,
    TargetedPatchConfig,
    TransformChainConfig,
    TransformConfig,
    load_transform_config,
)
from kstlib.transform.exceptions import (
    CallableError,
    CallableImportError,
    CompressError,
    DecodeError,
    DecompressError,
    EncodeError,
    ParseError,
    PatchError,
    PrimitiveError,
    SerializeError,
    TransformChainError,
    TransformConfigError,
    TransformError,
)
from kstlib.transform.primitives import (
    base64_decode,
    base64_encode,
    bytes_decode,
    bytes_encode,
    json_parse,
    json_serialize,
    xml_parse,
    xml_serialize,
    zlib_compress,
    zlib_decompress,
)

__all__ = [
    "PATCH_SCOPE_VALUES",
    "PROTECTED_OUTER_PATHS",
    "CallableError",
    "CallableImportError",
    "ComposedPatchConfig",
    "CompressError",
    "DecodeError",
    "DecompressError",
    "EncodeError",
    "FilterConfig",
    "ParseError",
    "PatchConfig",
    "PatchError",
    "PrimitiveConfig",
    "PrimitiveError",
    "SerializeError",
    "TargetedPatchConfig",
    "TransformChain",
    "TransformChainConfig",
    "TransformChainError",
    "TransformConfig",
    "TransformConfigError",
    "TransformError",
    "base64_decode",
    "base64_encode",
    "bytes_decode",
    "bytes_encode",
    "json_parse",
    "json_serialize",
    "load_transform_config",
    "replace_outer_uris",
    "transform",
    "xml_parse",
    "xml_serialize",
    "zlib_compress",
    "zlib_decompress",
]
