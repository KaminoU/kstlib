"""Keyring-backed provider."""

from __future__ import annotations

import typing
from typing import TYPE_CHECKING, Any

from kstlib.secrets.models import SecretRecord, SecretRequest, SecretSource
from kstlib.secrets.providers.base import SecretProvider

if TYPE_CHECKING:
    from collections.abc import Mapping
else:  # pragma: no cover - runtime alias for typing constructs
    Mapping = typing.Mapping

# pylint: disable=invalid-name
keyring_backend: Any | None
try:  # pragma: no cover - optional dependency
    import keyring as keyring_module  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - fallback when keyring absent
    keyring_backend = None
else:
    keyring_backend = keyring_module


class KeyringProvider(SecretProvider):
    """Retrieve secrets from the system keyring."""

    name = "keyring"

    def __init__(self, *, service: str = "kstlib") -> None:
        """Instantiate the provider with an optional service namespace."""
        self._service = service

    def configure(self, settings: Mapping[str, Any] | None = None) -> None:
        """Load configuration overrides into the provider.

        Args:
            settings: Optional mapping with a ``service`` key overriding the
                default keyring service name.
        """
        if not settings:
            return
        self._service = settings.get("service", self._service)

    def resolve(self, request: SecretRequest) -> SecretRecord | None:
        """Retrieve a secret from the backing keyring.

        Args:
            request: Secret lookup description provided by the resolver.

        Returns:
            A populated ``SecretRecord`` when the secret exists, otherwise
            ``None`` to signal a miss.
        """
        if keyring_backend is None:
            return None
        username = self._username_for(request)
        value = keyring_backend.get_password(self._service, username)
        if value is None:
            return None
        metadata = {"service": self._service, "username": username}
        return SecretRecord(value=value, source=SecretSource.KEYRING, metadata=metadata)

    def store(self, request: SecretRequest, value: str) -> None:
        """Persist a secret to the keyring backend.

        Args:
            request: Secret descriptor used to derive a keyring username.
            value: Plaintext secret that should be stored.

        Raises:
            RuntimeError: If the optional ``keyring`` dependency is missing.
        """
        if keyring_backend is None:
            raise RuntimeError("keyring package is not available")
        username = self._username_for(request)
        keyring_backend.set_password(self._service, username, value)

    def delete(self, request: SecretRequest) -> None:
        """Remove a secret from the keyring backend.

        Args:
            request: Secret descriptor used to derive a keyring username.

        Raises:
            RuntimeError: If the optional ``keyring`` dependency is missing.
        """
        if keyring_backend is None:
            raise RuntimeError("keyring package is not available")
        username = self._username_for(request)
        keyring_backend.delete_password(self._service, username)

    def _username_for(self, request: SecretRequest) -> str:
        """Compute a stable username for the keyring entry.

        Args:
            request: Secret descriptor providing scope and name details.

        Returns:
            The composed username used for keyring operations.
        """
        scope = request.scope or "default"
        return f"{scope}:{request.name}"


__all__ = ["KeyringProvider"]
