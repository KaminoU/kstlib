"""Kwargs-based provider for direct secret injection."""

from __future__ import annotations

import typing
from typing import TYPE_CHECKING, Any

from kstlib.secrets.models import SecretRecord, SecretRequest, SecretSource
from kstlib.secrets.providers.base import SecretProvider

if TYPE_CHECKING:
    from collections.abc import Mapping
else:  # pragma: no cover - runtime alias for typing constructs
    Mapping = typing.Mapping


class KwargsProvider(SecretProvider):
    """Resolve secrets from explicitly provided keyword arguments.

    This provider is useful for testing and temporary overrides. Secrets
    passed via kwargs take precedence over all other providers.

    Example:
        >>> from kstlib.secrets.providers.kwargs import KwargsProvider
        >>> provider = KwargsProvider({"api.key": "test-key"})
        >>> from kstlib.secrets.models import SecretRequest
        >>> record = provider.resolve(SecretRequest(name="api.key"))
        >>> record.value
        'test-key'
    """

    name = "kwargs"

    def __init__(self, secrets: Mapping[str, Any] | None = None) -> None:
        """Initialize with an optional mapping of secret names to values.

        Args:
            secrets: Mapping of dotted secret names to their values.
        """
        self._secrets: dict[str, Any] = dict(secrets) if secrets else {}

    def configure(self, settings: Mapping[str, Any] | None = None) -> None:
        """Apply settings overrides (merges additional secrets).

        Args:
            settings: Optional mapping that may provide additional secrets
                under the ``secrets`` key.
        """
        if not settings:
            return
        additional = settings.get("secrets")
        if isinstance(additional, Mapping):
            self._secrets.update(additional)

    def resolve(self, request: SecretRequest) -> SecretRecord | None:
        """Resolve a secret from the provided kwargs.

        Args:
            request: Secret descriptor with the name to look up.

        Returns:
            A ``SecretRecord`` if the secret is found, otherwise ``None``.
        """
        value = self._secrets.get(request.name)
        if value is None:
            return None
        return SecretRecord(
            value=value,
            source=SecretSource.KWARGS,
            metadata={"provider": "kwargs"},
        )

    def set(self, name: str, value: Any) -> None:
        """Add or update a secret at runtime.

        Args:
            name: The dotted secret name (e.g., "api.key").
            value: The secret value.
        """
        self._secrets[name] = value

    def remove(self, name: str) -> bool:
        """Remove a secret by name.

        Args:
            name: The dotted secret name to remove.

        Returns:
            True if the secret was removed, False if it didn't exist.
        """
        if name in self._secrets:
            del self._secrets[name]
            return True
        return False

    def clear(self) -> None:
        """Remove all secrets from this provider."""
        self._secrets.clear()


__all__ = ["KwargsProvider"]
