"""Environment variable provider."""

from __future__ import annotations

import os
import typing
from typing import TYPE_CHECKING, Any

from kstlib.secrets.models import SecretRecord, SecretRequest, SecretSource
from kstlib.secrets.providers.base import SecretProvider

if TYPE_CHECKING:
    from collections.abc import Mapping
else:  # pragma: no cover - runtime alias for typing constructs
    Mapping = typing.Mapping


class EnvironmentProvider(SecretProvider):
    """Resolve secrets from process environment variables."""

    name = "environment"

    def __init__(self, *, prefix: str = "KSTLIB_", delimiter: str = "__") -> None:
        """Configure the provider prefix and delimiter."""
        self._prefix = prefix
        self._delimiter = delimiter

    def configure(self, settings: Mapping[str, Any] | None = None) -> None:
        """Apply settings overrides coming from configuration files.

        Args:
            settings: Optional mapping that may provide ``prefix`` or
                ``delimiter`` keys overriding the defaults.
        """
        if not settings:
            return
        self._prefix = settings.get("prefix", self._prefix)
        self._delimiter = settings.get("delimiter", self._delimiter)

    def resolve(self, request: SecretRequest) -> SecretRecord | None:
        """Resolve a secret using the environment cascade.

        Args:
            request: Secret descriptor describing scope and key.

        Returns:
            A ``SecretRecord`` populated from the environment when present,
            otherwise ``None``.
        """
        env_key = self._build_env_key(request)
        value = os.getenv(env_key)
        if value is None:
            return None
        return SecretRecord(value=value, source=SecretSource.ENVIRONMENT, metadata={"env_key": env_key})

    def _build_env_key(self, request: SecretRequest) -> str:
        """Construct the canonical environment variable name for a request."""
        parts: list[str] = [self._prefix.rstrip(self._delimiter)]
        if request.scope:
            parts.append(request.scope)
        parts.append(request.name)
        env_key = self._delimiter.join(part.upper().replace(".", self._delimiter) for part in parts if part)
        return env_key


__all__ = ["EnvironmentProvider"]
