"""Provider registry utilities for the secrets subsystem."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from kstlib.secrets.providers.base import ProviderFactory, SecretProvider
from kstlib.utils.lazy import lazy_factory

if TYPE_CHECKING:
    from collections.abc import Mapping

_REGISTRY: dict[str, ProviderFactory] = {}


def register_provider(name: str, factory: ProviderFactory) -> None:
    """Register a provider factory under the given name."""
    _REGISTRY[name] = factory


def get_provider(name: str, **kwargs: Any) -> SecretProvider:
    """Instantiate a provider by name."""
    try:
        factory = _REGISTRY[name]
    except KeyError as exc:  # pragma: no cover - defensive branch
        raise ValueError(f"Unknown secret provider '{name}'") from exc
    return factory(**kwargs)


def configure_provider(provider: SecretProvider, settings: Mapping[str, Any] | None) -> SecretProvider:
    """Apply provider-specific configuration and return the provider."""
    provider.configure(settings)
    return provider


__all__ = [
    "ProviderFactory",
    "SecretProvider",
    "configure_provider",
    "get_provider",
    "register_provider",
]


# --- Lazy-loaded provider factories ---
# Providers are only imported when their factory is called, not at module load.
# Body is replaced by the decorator; type: ignore[empty-body] silences mypy.


@lazy_factory("kstlib.secrets.providers.kwargs", "KwargsProvider")
def _kwargs_factory(**_kwargs: Any) -> SecretProvider:  # type: ignore[empty-body]
    ...  # pragma: no cover - body replaced by decorator


@lazy_factory("kstlib.secrets.providers.environment", "EnvironmentProvider")
def _environment_factory(**_kwargs: Any) -> SecretProvider:  # type: ignore[empty-body]
    ...  # pragma: no cover - body replaced by decorator


@lazy_factory("kstlib.secrets.providers.keyring", "KeyringProvider")
def _keyring_factory(**_kwargs: Any) -> SecretProvider:  # type: ignore[empty-body]
    ...  # pragma: no cover - body replaced by decorator


@lazy_factory("kstlib.secrets.providers.sops", "SOPSProvider")
def _sops_factory(**_kwargs: Any) -> SecretProvider:  # type: ignore[empty-body]
    ...  # pragma: no cover - body replaced by decorator


@lazy_factory("kstlib.secrets.providers.kms", "KMSProvider")
def _kms_factory(**_kwargs: Any) -> SecretProvider:  # type: ignore[empty-body]
    ...  # pragma: no cover - body replaced by decorator


register_provider("kwargs", _kwargs_factory)
register_provider("environment", _environment_factory)
register_provider("keyring", _keyring_factory)
register_provider("sops", _sops_factory)
register_provider("kms", _kms_factory)
