"""Input validation for kstlib.transform module.

Provides validation functions for transform configuration,
implementing deep defense against malformed or malicious input.
Reuses ``validate_callable_target`` pattern from pipeline module.
"""

from __future__ import annotations

import re

from kstlib.transform.exceptions import TransformConfigError
from kstlib.utils.validators import (
    CALLABLE_TARGET_PATTERN,
    MAX_CALLABLE_TARGET_LENGTH,
    _validate_callable_target_str,
)

# ============================================================================
# Constants - Hard Limits
# ============================================================================

#: Maximum input data size (100 MB).
MAX_INPUT_SIZE: int = 100 * 1024 * 1024

#: Maximum JSON payload size (50 MB).
MAX_JSON_SIZE: int = 50 * 1024 * 1024

#: Maximum XML payload size (50 MB).
MAX_XML_SIZE: int = 50 * 1024 * 1024

#: Maximum decompressed data size (200 MB).
MAX_DECOMPRESSED_SIZE: int = 200 * 1024 * 1024

#: Maximum decompression ratio (compressed * ratio = max decompressed).
MAX_DECOMPRESSION_RATIO: int = 100

#: Maximum mapping entries in a PatchConfig.
MAX_MAPPING_ENTRIES: int = 100

#: Maximum length of a single mapping key or value.
MAX_MAPPING_STRING_LENGTH: int = 4096

#: Maximum number of primitives in a forward or backward chain.
MAX_CHAIN_PRIMITIVES: int = 20

#: Maximum number of named chains in TransformConfig.
MAX_NAMED_CHAINS: int = 50

#: Maximum number of args passed to callable.
MAX_CALLABLE_ARGS: int = 20

#: Maximum length of a callable arg key.
MAX_ARG_KEY_LENGTH: int = 64

#: Callable execution timeout in seconds.
CALLABLE_TIMEOUT: float = 30.0

#: Maximum variable references per args dict.
MAX_VARIABLE_REFS: int = 20

#: Maximum zlib skip_bytes value.
MAX_SKIP_BYTES: int = 16

#: Maximum hex string length for prepend_bytes (16 bytes = 32 hex chars).
MAX_PREPEND_HEX_LENGTH: int = 32

#: Maximum dot-path length for json extract/wrap.
MAX_DOT_PATH_LENGTH: int = 256

#: Maximum primitive options count.
MAX_PRIMITIVE_OPTIONS: int = 10

#: Maximum encoding name length.
MAX_ENCODING_LENGTH: int = 32

#: Maximum length of a base64 prefix or strip_prefix marker.
MAX_PREFIX_LENGTH: int = 32

#: Minimum value for the zlib compression level option.
#: -1 means "use the Python zlib default level" (typically 6).
ZLIB_LEVEL_MIN: int = -1

#: Maximum value for the zlib compression level option.
#: 0 = no compression, 9 = maximum compression (slowest).
ZLIB_LEVEL_MAX: int = 9

#: Maximum number of global patches in a ComposedPatchConfig.
MAX_GLOBAL_PATCHES: int = 10

#: Maximum number of targeted patches in a ComposedPatchConfig.
MAX_TARGETED_PATCHES: int = 50

#: Maximum number of patch chain references per TargetedPatchConfig.
MAX_PATCHES_PER_TARGETED: int = 10

#: Maximum length of a glob pattern in FilterConfig.name.
MAX_GLOB_PATTERN_LENGTH: int = 256

#: Allowed values for FilterConfig.content_type.
ALLOWED_FILTER_TYPES: frozenset[str] = frozenset(
    {
        "report",
        "folder",
        "file",
        "*",
    }
)

# ============================================================================
# Patterns
# ============================================================================

#: Allowed primitive names.
ALLOWED_PRIMITIVES: frozenset[str] = frozenset(
    {
        "base64",
        "zlib",
        "json",
        "xml",
        "bytes",
        "split",
        "tr",
        "removeprefix",
        "removesuffix",
    }
)

#: Primitives that only support the forward direction (lossy extractors).
#: They have no backward implementation: they are rejected when declared
#: in an explicit ``backward`` chain and cannot be auto-reversed.
FORWARD_ONLY_PRIMITIVES: frozenset[str] = frozenset(
    {
        "split",
        "tr",
        "removeprefix",
        "removesuffix",
    }
)

#: Pattern for valid chain names.
CHAIN_NAME_PATTERN: re.Pattern[str] = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")

#: Maximum chain name length.
MAX_CHAIN_NAME_LENGTH: int = 64

#: Pattern for valid dot-notation paths (e.g. "transferableContent.content").
DOT_PATH_PATTERN: re.Pattern[str] = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*$")

#: Pattern for {{variable}} references.
VARIABLE_PATTERN: re.Pattern[str] = re.compile(r"\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}")


# ============================================================================
# Validation Functions
# ============================================================================


def validate_chain_name(name: str) -> str:
    """Validate a transform chain name.

    Args:
        name: Chain name to validate.

    Returns:
        The validated name.

    Raises:
        TransformConfigError: If name is invalid.

    """
    if not name:
        raise TransformConfigError("Chain name must not be empty")
    if len(name) > MAX_CHAIN_NAME_LENGTH:
        raise TransformConfigError(f"Chain name too long: {len(name)} > {MAX_CHAIN_NAME_LENGTH}")
    if not CHAIN_NAME_PATTERN.match(name):
        raise TransformConfigError(f"Invalid chain name: {name!r}. Must match {CHAIN_NAME_PATTERN.pattern}")
    return name


def validate_primitive_name(name: str) -> str:
    """Validate a primitive name.

    Args:
        name: Primitive name to validate.

    Returns:
        The validated name.

    Raises:
        TransformConfigError: If name is not in allowed set.

    """
    if name not in ALLOWED_PRIMITIVES:
        raise TransformConfigError(f"Unknown primitive: {name!r}. Allowed: {sorted(ALLOWED_PRIMITIVES)}")
    return name


def validate_dot_path(path: str, *, label: str = "path") -> str:
    """Validate a dot-notation path (e.g. "transferableContent.content").

    Args:
        path: Dot-notation path to validate.
        label: Label for error messages (e.g. "extract", "wrap").

    Returns:
        The validated path.

    Raises:
        TransformConfigError: If path is invalid.

    """
    if not path:
        raise TransformConfigError(f"{label} must not be empty")
    if len(path) > MAX_DOT_PATH_LENGTH:
        raise TransformConfigError(f"{label} too long: {len(path)} > {MAX_DOT_PATH_LENGTH}")
    if not DOT_PATH_PATTERN.match(path):
        raise TransformConfigError(f"Invalid {label}: {path!r}. Must match {DOT_PATH_PATTERN.pattern}")
    return path


def validate_callable_target(target: str) -> str:
    """Validate a callable target string (module.path:function_name).

    Args:
        target: Callable target to validate.

    Returns:
        The validated target.

    Raises:
        TransformConfigError: If target is invalid.

    """
    try:
        _validate_callable_target_str(target)
    except ValueError as exc:
        raise TransformConfigError(str(exc)) from exc
    return target


def validate_hex_string(value: str, *, label: str = "hex") -> bytes:
    """Validate and decode a hex string.

    Args:
        value: Hex string to validate (e.g. "4d1504").
        label: Label for error messages.

    Returns:
        Decoded bytes.

    Raises:
        TransformConfigError: If hex string is invalid.

    """
    if len(value) > MAX_PREPEND_HEX_LENGTH:
        raise TransformConfigError(f"{label} too long: {len(value)} > {MAX_PREPEND_HEX_LENGTH}")
    try:
        return bytes.fromhex(value)
    except ValueError as exc:
        raise TransformConfigError(f"Invalid {label}: {value!r} ({exc})") from exc


def validate_callable_module(
    target: str,
    allowed_modules: frozenset[str],
) -> None:
    """Validate that a callable's module is in the allowed whitelist.

    Args:
        target: Callable target (module.path:function_name).
        allowed_modules: Set of allowed module prefixes.

    Raises:
        TransformConfigError: If module is not in allowed list.

    """
    module_path = target.rpartition(":")[0]
    if not module_path:
        raise TransformConfigError(f"Invalid callable target: {target!r}")

    for allowed in allowed_modules:
        if module_path == allowed or module_path.startswith(f"{allowed}."):
            return

    raise TransformConfigError(
        f"Callable module '{module_path}' is not in allowed_callable_modules. "
        f"Add it to transforms.security.allowed_callable_modules in kstlib.conf.yml."
    )


def validate_filter_type(content_type: str) -> str:
    """Validate a FilterConfig content_type value.

    Args:
        content_type: Content type string to validate.

    Returns:
        The validated content type.

    Raises:
        TransformConfigError: If content_type is not in allowed set.

    """
    if content_type not in ALLOWED_FILTER_TYPES:
        raise TransformConfigError(
            f"Invalid filter content_type: {content_type!r}. Allowed: {sorted(ALLOWED_FILTER_TYPES)}"
        )
    return content_type


def validate_glob_pattern(pattern: str, *, label: str = "glob pattern") -> str:
    """Validate a glob pattern used in FilterConfig.name.

    Rejects empty strings, oversized patterns, and control characters.
    Does not validate glob syntax itself (fnmatch is permissive).

    Args:
        pattern: Glob pattern to validate.
        label: Label for error messages.

    Returns:
        The validated pattern.

    Raises:
        TransformConfigError: If pattern is invalid.

    """
    if not pattern:
        raise TransformConfigError(f"{label} must not be empty")
    if len(pattern) > MAX_GLOB_PATTERN_LENGTH:
        raise TransformConfigError(f"{label} too long: {len(pattern)} > {MAX_GLOB_PATTERN_LENGTH}")
    if any(ord(c) < 0x20 for c in pattern):
        raise TransformConfigError(f"{label} contains control characters: {pattern!r}")
    return pattern


def validate_input_size(data: bytes | str, *, limit: int, label: str) -> None:
    """Validate input data size against a limit.

    Args:
        data: Input data (bytes or str).
        limit: Maximum allowed size.
        label: Label for error messages.

    Raises:
        TransformConfigError: If data exceeds limit.

    """
    size = len(data)
    if size > limit:
        raise TransformConfigError(f"{label} input exceeds limit ({size:,} > {limit:,} bytes)")


__all__ = [
    "ALLOWED_FILTER_TYPES",
    "ALLOWED_PRIMITIVES",
    "CALLABLE_TARGET_PATTERN",
    "CALLABLE_TIMEOUT",
    "CHAIN_NAME_PATTERN",
    "DOT_PATH_PATTERN",
    "FORWARD_ONLY_PRIMITIVES",
    "MAX_ARG_KEY_LENGTH",
    "MAX_CALLABLE_ARGS",
    "MAX_CALLABLE_TARGET_LENGTH",
    "MAX_CHAIN_NAME_LENGTH",
    "MAX_CHAIN_PRIMITIVES",
    "MAX_DECOMPRESSED_SIZE",
    "MAX_DECOMPRESSION_RATIO",
    "MAX_DOT_PATH_LENGTH",
    "MAX_ENCODING_LENGTH",
    "MAX_GLOBAL_PATCHES",
    "MAX_GLOB_PATTERN_LENGTH",
    "MAX_INPUT_SIZE",
    "MAX_JSON_SIZE",
    "MAX_MAPPING_ENTRIES",
    "MAX_MAPPING_STRING_LENGTH",
    "MAX_NAMED_CHAINS",
    "MAX_PATCHES_PER_TARGETED",
    "MAX_PREFIX_LENGTH",
    "MAX_PREPEND_HEX_LENGTH",
    "MAX_PRIMITIVE_OPTIONS",
    "MAX_SKIP_BYTES",
    "MAX_TARGETED_PATCHES",
    "MAX_VARIABLE_REFS",
    "MAX_XML_SIZE",
    "VARIABLE_PATTERN",
    "ZLIB_LEVEL_MAX",
    "ZLIB_LEVEL_MIN",
    "validate_callable_module",
    "validate_callable_target",
    "validate_chain_name",
    "validate_dot_path",
    "validate_filter_type",
    "validate_glob_pattern",
    "validate_hex_string",
    "validate_input_size",
    "validate_primitive_name",
]
