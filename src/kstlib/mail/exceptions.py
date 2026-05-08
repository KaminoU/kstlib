"""Custom exceptions for the mail module."""

from __future__ import annotations

from kstlib.config.exceptions import KstlibError


class MailError(KstlibError):
    """Base class for mail related errors."""


class MailValidationError(MailError):
    """Raised when provided mail data fails validation checks."""


class MailTransportError(MailError):
    """Raised when a transport backend cannot deliver a message."""


class MailConfigurationError(MailError):
    """Raised when the mail builder is missing required configuration."""


class MailThrottledError(MailError):
    """Raised when the mail throttle bucket is empty and on_exceed is 'raise'.

    Carries the throttle parameters in the message to help the caller
    decide on a backoff strategy. The throttle is config-driven via
    ``mail.throttle.*`` and acts as an anti-spam kill switch.

    See Also:
        :class:`kstlib.mail.MailThrottle`

    """


__all__ = [
    "MailConfigurationError",
    "MailError",
    "MailThrottledError",
    "MailTransportError",
    "MailValidationError",
]
