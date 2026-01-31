"""Provider base classes and registry helpers."""

from __future__ import annotations

# pylint: disable=unnecessary-ellipsis,too-few-public-methods
import asyncio
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping

    from kstlib.secrets.models import SecretRecord, SecretRequest


class SecretProvider(ABC):
    """Abstract provider responsible for retrieving secrets from a backend."""

    name: str = "provider"

    @abstractmethod
    def resolve(self, request: SecretRequest) -> SecretRecord | None:
        """Retrieve the secret synchronously.

        Args:
            request: Details about the requested secret.

        Returns:
            A ``SecretRecord`` if the provider can handle the request, otherwise
            ``None``.
        """

    async def resolve_async(self, request: SecretRequest) -> SecretRecord | None:
        """Async-friendly hook.

        Providers may override this method when native async support is
        available. The default implementation delegates to ``resolve`` using
        ``asyncio.to_thread`` to avoid blocking the event loop.
        """
        return await asyncio.to_thread(self.resolve, request)

    def configure(self, settings: Mapping[str, Any] | None = None) -> None:
        """Apply provider specific configuration settings.

        Subclasses can override to handle provider-level configuration. The
        default implementation ignores the settings.
        """
        if not settings:
            return
        _ = settings


class ProviderFactory(Protocol):
    """Protocol describing callables that build providers."""

    def __call__(self, **kwargs: Any) -> SecretProvider:  # pragma: no cover - protocol definition
        """Return a configured provider instance."""
        ...
