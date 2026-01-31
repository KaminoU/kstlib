"""Custom exceptions for the mail module."""

from __future__ import annotations


class MailError(Exception):
    """Base class for mail related errors."""


class MailValidationError(MailError):
    """Raised when provided mail data fails validation checks."""


class MailTransportError(MailError):
    """Raised when a transport backend cannot deliver a message."""


class MailConfigurationError(MailError):
    """Raised when the mail builder is missing required configuration."""


__all__ = [
    "MailConfigurationError",
    "MailError",
    "MailTransportError",
    "MailValidationError",
]
