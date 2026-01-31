"""Data models used by the secrets resolver."""

from __future__ import annotations

import typing
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping, MutableMapping
else:  # pragma: no cover - runtime aliases for typing constructs
    Mapping = typing.Mapping
    MutableMapping = typing.MutableMapping


class SecretSource(str, Enum):
    """Enumerates the possible origins for a resolved secret."""

    KWARGS = "kwargs"
    ENVIRONMENT = "environment"
    KEYRING = "keyring"
    SOPS = "sops"
    KMS = "kms"
    DEFAULT = "default"


@dataclass(slots=True)
class SecretRequest:
    """Describes a secret lookup request.

    Attributes:
        name: Identifier of the secret (e.g. "smtp.password").
        scope: Optional scope that providers can exploit for namespacing.
        required: Whether the resolver must raise if the secret is missing.
        default: Optional fallback value when the secret is not required.
        metadata: Arbitrary provider hints (e.g. keyring namespace).
    """

    name: str
    scope: str | None = None
    required: bool = True
    default: Any | None = None
    metadata: MutableMapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SecretRecord:
    """Represents the value returned by the resolver.

    Attributes:
        value: The secret itself.
        source: The origin of the secret.
        metadata: Provider specific metadata (e.g. timestamp, path, ttl).
    """

    value: Any
    source: SecretSource
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["SecretRecord", "SecretRequest", "SecretSource"]
