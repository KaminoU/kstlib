"""SecretResolver orchestrates provider lookups."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from kstlib.config.loader import get_config
from kstlib.secrets.exceptions import SecretNotFoundError
from kstlib.secrets.models import SecretRecord, SecretRequest, SecretSource
from kstlib.secrets.providers import configure_provider, get_provider

if TYPE_CHECKING:
    from kstlib.secrets.providers.base import SecretProvider


class SecretResolver:
    """Resolve secrets by delegating to a sequence of providers.

    The resolver iterates through providers in order until one returns a value.
    If no provider can resolve the secret and no default is given, a
    ``SecretNotFoundError`` is raised (when ``required=True``).

    Example:
        >>> from kstlib.secrets.resolver import SecretResolver
        >>> from kstlib.secrets.providers import get_provider
        >>> from kstlib.secrets.models import SecretRequest
        >>> resolver = SecretResolver([get_provider("environment")], name="app")
        >>> # resolver.resolve(SecretRequest(name="API_KEY"))
    """

    def __init__(self, providers: Sequence[SecretProvider], *, name: str | None = None) -> None:
        """Initialise the resolver with a provider cascade.

        Args:
            providers: Ordered sequence of secret providers to query.
            name: Human-readable name for this resolver (used in error messages).
        """
        self._providers = list(providers)
        self._name = name or "default"

    @property
    def name(self) -> str:
        """Return the resolver name."""
        return self._name

    def resolve(self, request: SecretRequest) -> SecretRecord:
        """Resolve the secret using the configured provider cascade.

        Args:
            request: The secret request to resolve.

        Returns:
            A SecretRecord with the resolved value and metadata.

        Raises:
            SecretNotFoundError: If the secret is not found and required=True.
        """
        for provider in self._providers:
            record = provider.resolve(request)
            if record is not None:
                return record
        if request.default is not None:
            return self._default_record(request.default, is_async=False)
        if request.required:
            raise SecretNotFoundError(f"Secret '{request.name}' not found in resolver '{self._name}'")
        return self._default_record(None, is_async=False)

    async def resolve_async(self, request: SecretRequest) -> SecretRecord:
        """Async counterpart for ``resolve``.

        Args:
            request: The secret request to resolve.

        Returns:
            A SecretRecord with the resolved value and metadata.

        Raises:
            SecretNotFoundError: If the secret is not found and required=True.
        """
        for provider in self._providers:
            record = await provider.resolve_async(request)
            if record is not None:
                return record
        if request.default is not None:
            return self._default_record(request.default, is_async=True)
        if request.required:
            raise SecretNotFoundError(f"Secret '{request.name}' not found in resolver '{self._name}'")
        return self._default_record(None, is_async=True)

    def _default_record(self, value: Any, *, is_async: bool) -> SecretRecord:
        metadata: dict[str, Any] = {"resolver": self._name}
        if is_async:
            metadata["async"] = True
        return SecretRecord(value=value, source=SecretSource.DEFAULT, metadata=metadata)


def get_secret_resolver(
    config: Mapping[str, Any] | None = None,
    *,
    secrets: Mapping[str, Any] | None = None,
) -> SecretResolver:
    """Build a resolver from configuration mapping.

    When no explicit provider list is given, the default cascade is:
    ``(KwargsProvider if secrets) -> EnvironmentProvider -> KeyringProvider -> (SOPSProvider if configured)``.

    Args:
        config: Optional mapping with ``providers`` list and/or ``sops`` settings.
            When ``None``, uses the default provider chain.
        secrets: Optional mapping of secret overrides to inject via KwargsProvider.

    Returns:
        Configured ``SecretResolver`` instance.

    Example:
        >>> from kstlib.secrets.resolver import get_secret_resolver
        >>> resolver = get_secret_resolver()  # uses defaults
        >>> resolver.name
        'default'
    """
    config = config or {}
    providers: list[SecretProvider] = []

    # KwargsProvider always comes first (highest priority)
    if secrets:
        providers.append(get_provider("kwargs", secrets=secrets))

    provider_configs = config.get("providers", [])
    if not provider_configs:
        providers.extend([get_provider("environment"), get_provider("keyring")])
        sops_config = config.get("sops")
        if isinstance(sops_config, Mapping):
            providers.append(_build_sops_provider(sops_config))
    else:
        for provider_cfg in provider_configs:
            name = provider_cfg.get("name")
            if not name:
                raise ValueError("Provider configuration requires a 'name' field")
            settings = provider_cfg.get("settings")
            provider = get_provider(name, **(provider_cfg.get("options") or {}))
            providers.append(configure_provider(provider, settings))
    return SecretResolver(providers, name=config.get("name"))


def resolve_secret(
    name: str,
    *,
    config: Mapping[str, Any] | None = None,
    secrets: Mapping[str, Any] | None = None,
    **request_kwargs: Any,
) -> SecretRecord:
    """Resolve a secret by name using the global resolver cascade.

    Args:
        name: Identifier of the secret (``"smtp.password"`` for example).
        config: Optional configuration mapping describing providers. When not
            provided the function attempts to reuse the globally loaded config.
        secrets: Optional mapping of secret overrides. These take precedence
            over all other providers (useful for testing).
        request_kwargs: Additional keyword arguments forwarded to
            :class:`SecretRequest`. Supported keys are ``scope``, ``required``,
            ``default`` and ``metadata``.

    Returns:
        A ``SecretRecord`` describing the resolved secret and its provenance.

    Raises:
        SecretNotFoundError: If the secret is not found and required=True.
        TypeError: If unsupported keyword arguments are provided.

    Example:
        >>> from kstlib.secrets.resolver import resolve_secret
        >>> # Override for testing
        >>> record = resolve_secret("api.key", secrets={"api.key": "test-value"})
        >>> record.source
        <SecretSource.KWARGS: 'kwargs'>
    """
    if config is None:
        global_config = get_config()
        secrets_config = getattr(global_config, "secrets", None)
        config = secrets_config.to_dict() if secrets_config is not None else None

    allowed_keys = {"scope", "required", "default", "metadata"}
    unexpected = set(request_kwargs) - allowed_keys
    if unexpected:
        unexpected_list = ", ".join(sorted(unexpected))
        raise TypeError(f"Unsupported keyword arguments: {unexpected_list}")

    resolver = get_secret_resolver(config, secrets=secrets)
    scope = request_kwargs.get("scope")
    required = request_kwargs.get("required", True)
    default = request_kwargs.get("default")
    metadata = request_kwargs.get("metadata")
    request = SecretRequest(
        name=name,
        scope=scope,
        required=required,
        default=default,
        metadata=dict(metadata) if metadata else {},
    )
    return resolver.resolve(request)


def _build_sops_provider(config: Mapping[str, Any]) -> SecretProvider:
    """Instantiate a SOPS provider from a simple mapping."""
    option_keys = {"path", "binary", "document_format", "format"}
    raw_options = config.get("options")
    options = (
        {key: value for key, value in config.items() if key in option_keys}
        if raw_options is None
        else dict(raw_options)
    )
    if "format" in options and "document_format" not in options:
        options["document_format"] = options.pop("format")
    settings = config.get("settings")
    provider = get_provider("sops", **options)
    return configure_provider(provider, settings)


__all__ = ["SecretResolver", "get_secret_resolver"]
