"""Custom exceptions raised by the secrets subsystem."""

from __future__ import annotations

__all__ = [
    "SecretDecryptionError",
    "SecretError",
    "SecretNotFoundError",
]

from kstlib.config.exceptions import KstlibError


class SecretError(KstlibError, RuntimeError):
    """Base class for all secrets related errors."""


class SecretNotFoundError(SecretError):
    """Raised when no provider can supply a requested secret."""


class SecretDecryptionError(SecretError):
    """Raised when a secret payload cannot be decrypted."""
