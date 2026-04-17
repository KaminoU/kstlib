"""Specialized exceptions raised by the kstlib.transform module.

Exception hierarchy::

    KstlibError
        TransformError (base for all transform errors)
            TransformConfigError (invalid configuration, also ValueError)
            TransformChainError (chain execution failed)
                PrimitiveError (single primitive failed)
                    DecodeError (base64_decode / bytes_decode)
                    DecompressError (zlib_decompress)
                    ParseError (json_parse / xml_parse)
                    PatchError (patch stage)
                    SerializeError (json_serialize / xml_serialize)
                    CompressError (zlib_compress)
                    EncodeError (base64_encode / bytes_encode)
                CallableImportError (callable not found)
                CallableError (callable raised)
"""

from __future__ import annotations

from kstlib.config.exceptions import KstlibError


class TransformError(KstlibError):
    """Base exception for all transform module errors."""


class TransformConfigError(TransformError, ValueError):
    """Transform configuration is invalid.

    Raised when the transform chain or primitive configuration contains
    invalid values, missing required fields, or constraint violations.
    """


class TransformChainError(TransformError):
    """Transform chain execution failed.

    Attributes:
        chain_name: Name of the chain that failed.

    """

    def __init__(self, message: str, *, chain_name: str | None = None) -> None:
        """Initialize TransformChainError.

        Args:
            message: Human-readable error message.
            chain_name: Name of the chain that failed.

        """
        prefix = f"Chain '{chain_name}': " if chain_name else ""
        super().__init__(f"{prefix}{message}")
        self.chain_name = chain_name


class PrimitiveError(TransformChainError):
    """A single transform primitive failed.

    Attributes:
        primitive_name: Name of the primitive that failed.

    """

    def __init__(
        self,
        message: str,
        *,
        primitive_name: str | None = None,
        chain_name: str | None = None,
    ) -> None:
        """Initialize PrimitiveError.

        Args:
            message: Human-readable error message.
            primitive_name: Name of the primitive that failed.
            chain_name: Name of the chain that was running.

        """
        prefix = f"[{primitive_name}] " if primitive_name else ""
        super().__init__(f"{prefix}{message}", chain_name=chain_name)
        self.primitive_name = primitive_name


class DecodeError(PrimitiveError):
    """Base64 or bytes decoding failed."""


class DecompressError(PrimitiveError):
    """Zlib decompression failed."""


class ParseError(PrimitiveError):
    """JSON or XML parsing failed."""


class PatchError(PrimitiveError):
    """Patch stage failed."""


class SerializeError(PrimitiveError):
    """JSON or XML serialization failed."""


class CompressError(PrimitiveError):
    """Zlib compression failed."""


class EncodeError(PrimitiveError):
    """Base64 or bytes encoding failed."""


class CallableImportError(TransformChainError):
    """Callable target could not be imported.

    Attributes:
        target: The import target string that failed.

    """

    def __init__(
        self,
        target: str,
        *,
        chain_name: str | None = None,
    ) -> None:
        """Initialize CallableImportError.

        Args:
            target: The import target string (e.g. "module.path:function").
            chain_name: Name of the chain that was running.

        """
        super().__init__(f"Cannot import callable '{target}'", chain_name=chain_name)
        self.target = target


class CallableError(TransformChainError):
    """Callable raised an exception during execution.

    Attributes:
        target: The callable target string.

    """

    def __init__(
        self,
        target: str,
        reason: str,
        *,
        chain_name: str | None = None,
    ) -> None:
        """Initialize CallableError.

        Args:
            target: The callable target string.
            reason: Description of the error.
            chain_name: Name of the chain that was running.

        """
        super().__init__(
            f"Callable '{target}' failed: {reason}",
            chain_name=chain_name,
        )
        self.target = target


__all__ = [
    "CallableError",
    "CallableImportError",
    "CompressError",
    "DecodeError",
    "DecompressError",
    "EncodeError",
    "ParseError",
    "PatchError",
    "PrimitiveError",
    "SerializeError",
    "TransformChainError",
    "TransformConfigError",
    "TransformError",
]
