"""Lazy loading utilities for deferred module imports."""

from __future__ import annotations

import importlib
from functools import wraps
from typing import TYPE_CHECKING, Any, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Callable

T = TypeVar("T")


def lazy_factory(module_path: str, class_name: str) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator for lazy loading of classes in factory functions.

    Defers the import of the specified class until the factory is actually called,
    reducing startup time when the factory is registered but not used.

    Args:
        module_path: Full dotted path to the module containing the class.
        class_name: Name of the class to import from the module.

    Returns:
        A decorator that wraps the factory function with lazy import behavior.

    Example:
        >>> @lazy_factory("kstlib.secrets.providers.sops", "SOPSProvider")
        ... def _sops_factory(**kwargs):
        ...     ...  # Body is ignored, class is instantiated automatically
        >>>
        >>> # SOPSProvider is only imported when _sops_factory() is called
        >>> provider = _sops_factory(path="secrets.sops.yml")
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(**kwargs: Any) -> T:
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
            return cast("T", cls(**kwargs))

        return wrapper

    return decorator


__all__ = ["lazy_factory"]
