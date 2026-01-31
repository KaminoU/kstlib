"""Exceptions for the helpers module."""

from kstlib.config.exceptions import KstlibError


class TimeTriggerError(KstlibError):
    """Base exception for TimeTrigger errors."""


class InvalidModuloError(TimeTriggerError):
    """Raised when modulo string is invalid or out of bounds."""
