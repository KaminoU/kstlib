"""Custom exceptions raised by the secrets subsystem."""

__all__ = [
    "SecretDecryptionError",
    "SecretError",
    "SecretNotFoundError",
]


class SecretError(RuntimeError):
    """Base class for all secrets related errors."""


class SecretNotFoundError(SecretError):
    """Raised when no provider can supply a requested secret."""


class SecretDecryptionError(SecretError):
    """Raised when a secret payload cannot be decrypted."""
