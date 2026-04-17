"""Validation utilities used across kstlib."""

from __future__ import annotations

import importlib
import re
from dataclasses import dataclass
from email.utils import formataddr, parseaddr
from typing import TYPE_CHECKING

from kstlib.config.exceptions import KstlibError

if TYPE_CHECKING:
    from collections.abc import Iterable
else:  # pragma: no cover - runtime alias for delayed evaluation
    Iterable = importlib.import_module("collections.abc").Iterable

_EMAIL_PATTERN = re.compile(r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")

LOCAL_PART_MAX_LENGTH = 64
DOMAIN_MAX_LENGTH = 255
LABEL_MAX_LENGTH = 63
MIN_LABEL_COUNT = 2
MIN_TLD_LENGTH = 2

#: Shared pattern for callable targets (``module.path:function_name``).
#: Used by :mod:`kstlib.pipeline.validators` and
#: :mod:`kstlib.transform.validators`. Keep in sync with both modules.
CALLABLE_TARGET_PATTERN: re.Pattern[str] = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.]*:[a-zA-Z_][a-zA-Z0-9_]*$")

#: Maximum callable target length (bytes).
MAX_CALLABLE_TARGET_LENGTH: int = 256


class ValidationError(KstlibError, ValueError):
    """Raised when user supplied values fail validation."""


def _validate_callable_target_str(target: str) -> None:
    """Validate a callable target string.

    Shared by pipeline and transform modules; each caller wraps the
    raised ``ValueError`` in its module-specific exception type.

    Args:
        target: Callable target in the form ``module.path:function_name``.

    Raises:
        ValueError: If the target is empty, exceeds the length limit, or
            does not match :data:`CALLABLE_TARGET_PATTERN`.

    """
    if not target:
        raise ValueError("Callable target must not be empty")
    if len(target) > MAX_CALLABLE_TARGET_LENGTH:
        raise ValueError(f"Callable target too long: {len(target)} > {MAX_CALLABLE_TARGET_LENGTH}")
    if not CALLABLE_TARGET_PATTERN.match(target):
        raise ValueError(f"Invalid callable target: {target!r}. Expected format: module.path:function_name")


@dataclass(frozen=True, slots=True)
class EmailAddress:
    """Normalized representation of an email address."""

    name: str
    address: str

    @property
    def formatted(self) -> str:
        """Return ``"Name <email@domain>"`` if a display name is present."""
        if not self.name:
            return self.address
        sanitized = self.name.replace("\r", " ").replace("\n", " ").strip()
        if not sanitized:
            return self.address
        sanitized = sanitized.replace('"', "'")
        return formataddr((sanitized, self.address))


def parse_email_address(value: str) -> EmailAddress:
    """Parse *value* into a validated :class:`EmailAddress`.

    Args:
        value: Raw email string, optionally containing a display name.

    Returns:
        A normalized :class:`EmailAddress` instance.

    Raises:
        ValidationError: If the string does not contain a valid address.

    Examples:
        >>> parse_email_address("Ada Lovelace <ADA@example.COM>").formatted
        'Ada Lovelace <ada@example.com>'
        >>> parse_email_address("foo@bar")
        Traceback (most recent call last):
        ...
        kstlib.utils.validators.ValidationError: Invalid email address: 'foo@bar'

    """
    if not value:
        raise ValidationError("Email address cannot be empty")

    name, address = parseaddr(value)
    address = address.strip().lower()

    if name:
        start = value.find("<")
        end = value.rfind(">")
        candidate = value[start + 1 : end].strip() if start != -1 and end != -1 and end > start else address
    else:
        candidate = value.strip()

    if candidate.lower() != address:
        raise ValidationError(f"Invalid email address: {value!r}")

    if not _EMAIL_PATTERN.match(address):
        raise ValidationError(f"Invalid email address: {value!r}")

    local_part, _, domain_part = address.partition("@")
    if len(local_part) == 0 or len(local_part) > LOCAL_PART_MAX_LENGTH:
        raise ValidationError(f"Invalid email address: {value!r}")

    if len(domain_part) == 0 or len(domain_part) > DOMAIN_MAX_LENGTH:
        raise ValidationError(f"Invalid email address: {value!r}")

    labels = domain_part.split(".")
    if len(labels) < MIN_LABEL_COUNT or any(len(label) == 0 or len(label) > LABEL_MAX_LENGTH for label in labels):
        raise ValidationError(f"Invalid email address: {value!r}")

    if len(labels[-1]) < MIN_TLD_LENGTH:
        raise ValidationError(f"Invalid email address: {value!r}")

    name = name.strip()
    return EmailAddress(name=name, address=address)


def normalize_address_list(values: Iterable[str]) -> list[EmailAddress]:
    """Validate and normalize a sequence of email addresses.

    Examples:
        >>> normalize_address_list([
        ...     "Ada Lovelace <ada@example.com>",
        ...     "grace@example.net",
        ... ])  # doctest: +NORMALIZE_WHITESPACE
        [EmailAddress(name='Ada Lovelace', address='ada@example.com'),
         EmailAddress(name='', address='grace@example.net')]

    """
    return [parse_email_address(value) for value in values]


__all__ = [
    "EmailAddress",
    "ValidationError",
    "normalize_address_list",
    "parse_email_address",
]
