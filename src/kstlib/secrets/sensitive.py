"""Helpers that minimise the footprint of decrypted secrets.

The :func:`sensitive` context manager temporarily exposes a secret value and
then attempts to scrub it from memory, clear provider caches, and drop any
remaining references.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

if TYPE_CHECKING:
    from kstlib.secrets.models import SecretRecord

logger = logging.getLogger(__name__)

LegacyPurge = Callable[[], None]


class CachePurgeProtocol(Protocol):  # pylint: disable=too-few-public-methods
    """Protocol implemented by providers exposing a cache purge hook."""

    def purge_cache(self, *, path: str | Path | None = None) -> None:  # pragma: no cover - protocol stub
        """Clear cached decrypted material."""


@contextmanager
def sensitive(
    record: SecretRecord,
    *,
    providers: Sequence[CachePurgeProtocol] | None = None,
) -> Iterator[Any]:
    """Temporarily expose a secret and scrub it afterwards.

    The context manager yields the secret value so it can be used within the
    protected block. On exit it attempts to overwrite mutable buffers in place,
    clears provider caches when available, and replaces the value stored in the
    :class:`SecretRecord` with ``None`` to break lingering references.

    Example:
        >>> from kstlib.secrets.models import SecretRecord, SecretSource
        >>> from kstlib.secrets.sensitive import sensitive
        >>> record = SecretRecord(value=bytearray(b"api-token"), source=SecretSource.SOPS)
        >>> with sensitive(record) as secret:
        ...     secret[:3] = b"***"  # handle the secret
        >>> record.value is None
        True

    Args:
        record: Secret wrapped in a :class:`SecretRecord`.
        providers: Optional providers whose caches should be purged after use.

    Yields:
        The decrypted secret value.
    """
    try:
        yield record.value
    finally:
        _scrub_value(record.value)
        record.value = None
        metadata = record.metadata if isinstance(record.metadata, Mapping) else {}
        _purge_providers(providers, metadata=metadata)


def _scrub_value(value: Any) -> None:
    """Best-effort scrubbing for mutable buffers."""
    if value is None:
        return
    if isinstance(value, bytearray):
        value[:] = b"\x00" * len(value)
        return
    if isinstance(value, memoryview):
        if not value.readonly:
            value[:] = b"\x00" * len(value)
        value.release()
        return
    if hasattr(value, "clear") and hasattr(value, "__setitem__"):
        try:
            length = len(value)
        except TypeError:  # pragma: no cover - objects without __len__
            length = 0
        for index in range(length):
            if _try_assign(value, index, 0):
                continue
            _try_assign(value, index, None)
        with suppress(AttributeError, TypeError, ValueError):
            value.clear()


def _purge_providers(
    providers: Sequence[CachePurgeProtocol] | None,
    *,
    metadata: Mapping[str, Any] | None,
) -> None:
    """Invoke cache purge hooks for the supplied providers."""
    if not providers:
        return
    path_hint: str | Path | None = None
    if metadata:
        candidate = metadata.get("path")
        if isinstance(candidate, str | Path):
            path_hint = candidate

    for provider in providers:
        purge = getattr(provider, "purge_cache", None)
        if not callable(purge):
            continue
        try:
            purge(path=path_hint)
        except TypeError:
            legacy_purge = cast("LegacyPurge", purge)
            legacy_purge()
        except (AttributeError, OSError, RuntimeError, ValueError) as error:  # pragma: no cover - defensive logging
            logger.debug("Provider cache purge failed for %s", provider, exc_info=error)


def _try_assign(target: Any, index: int, replacement: Any) -> bool:
    """Attempt to assign ``replacement`` at ``index`` and report success."""
    try:
        target[index] = replacement
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return False
    return True


__all__ = ["CachePurgeProtocol", "sensitive"]
