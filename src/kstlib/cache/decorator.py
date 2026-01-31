"""Caching decorator with config-based strategy selection.

Provides @cache decorator with automatic async/sync detection
and configuration priority chain.
"""

# pylint: disable=too-many-arguments

import functools
import inspect
from collections.abc import Callable
from typing import Any, TypeVar, overload

from kstlib.cache.strategies import (
    CacheStrategy,
    FileCacheStrategy,
    LRUCacheStrategy,
    TTLCacheStrategy,
)
from kstlib.config import get_config
from kstlib.config.exceptions import ConfigFileNotFoundError

F = TypeVar("F", bound=Callable[..., Any])


def _get_cache_config() -> dict[str, Any]:
    """Get cache configuration from kstlib config.

    Returns:
        Cache configuration dict with defaults
    """
    try:
        config = get_config()
        if hasattr(config, "cache"):
            return dict(config.cache)
    except (AttributeError, ImportError, ConfigFileNotFoundError):
        # Config not available or cache section missing
        pass

    # Fallback defaults
    return {
        "default_strategy": "ttl",
        "ttl": {"default_seconds": 300, "max_entries": 1000, "cleanup_interval": 60},
        "lru": {"maxsize": 128, "typed": False},
        "file": {"enabled": True, "cache_dir": ".cache", "check_mtime": True, "serializer": "json"},
        "async_support": {"enabled": True, "executor_workers": 4},
    }


def _create_strategy(
    strategy: str | None = None,
    *,
    ttl: int | None = None,
    maxsize: int | None = None,
    cache_dir: str | None = None,
    check_mtime: bool | None = None,
    serializer: str | None = None,
) -> CacheStrategy:
    """Create cache strategy based on parameters and config.

    Args:
        strategy: Strategy name ('ttl', 'lru', 'file')
        ttl: TTL in seconds (for TTL strategy)
        maxsize: Max cache size (for LRU strategy)
        cache_dir: Cache directory (for file strategy)
        check_mtime: Check file mtime (for file strategy)
        serializer: Serializer name for the file strategy ('json', 'pickle', 'auto')

    Returns:
        Configured cache strategy instance
    """
    config = _get_cache_config()

    # Determine strategy (argument > config)
    strategy_name = strategy or config.get("default_strategy", "ttl")

    if strategy_name == "ttl":
        ttl_config = config.get("ttl", {})
        return TTLCacheStrategy(
            ttl=ttl or ttl_config.get("default_seconds", 300),
            max_entries=ttl_config.get("max_entries", 1000),
            cleanup_interval=ttl_config.get("cleanup_interval", 60),
        )

    if strategy_name == "lru":
        lru_config = config.get("lru", {})
        return LRUCacheStrategy(
            maxsize=maxsize or lru_config.get("maxsize", 128),
            typed=lru_config.get("typed", False),
        )

    if strategy_name == "file":
        file_config = config.get("file", {})
        return FileCacheStrategy(
            cache_dir=cache_dir or file_config.get("cache_dir", ".cache"),
            check_mtime=check_mtime if check_mtime is not None else file_config.get("check_mtime", True),
            serializer=serializer or file_config.get("serializer", "json"),
        )

    # Fallback to TTL
    return TTLCacheStrategy()


@overload
def cache(func: F) -> F: ...


@overload
def cache(
    *,
    strategy: str | None = None,
    ttl: int | None = None,
    maxsize: int | None = None,
    cache_dir: str | None = None,
    check_mtime: bool | None = None,
    serializer: str | None = None,
) -> Callable[[F], F]: ...


def cache(
    func: F | None = None,
    *,
    strategy: str | None = None,
    ttl: int | None = None,
    maxsize: int | None = None,
    cache_dir: str | None = None,
    check_mtime: bool | None = None,
    serializer: str | None = None,
) -> F | Callable[[F], F]:
    """Cache decorator with automatic async/sync detection.

    Supports multiple caching strategies configured via kstlib.conf.yml
    or decorator arguments. Automatically detects async functions and
    handles them appropriately.

    Args:
        func: Function to cache (when used without parentheses)
        strategy: Cache strategy ('ttl', 'lru', 'file')
        ttl: Time to live in seconds (TTL strategy)
        maxsize: Maximum cache size (LRU strategy)
        cache_dir: Cache directory path (file strategy)
        check_mtime: Check file modification time (file strategy)
        serializer: Serialization format for file strategy ('json', 'pickle', 'auto')

    Returns:
        Decorated function with caching

    Examples:
        Basic usage (uses config defaults):

        >>> @cache
        ... def double(x: int) -> int:
        ...     return x * 2
        >>> double(5)
        10
        >>> double(5)  # Returns cached value
        10

        With explicit TTL strategy:

        >>> @cache(strategy="ttl", ttl=60)
        ... def compute(n: int) -> int:
        ...     return n * n
        >>> compute(4)
        16

        LRU cache for recursive functions:

        >>> @cache(strategy="lru", maxsize=128)
        ... def fibonacci(n: int) -> int:
        ...     if n < 2:
        ...         return n
        ...     return fibonacci(n - 1) + fibonacci(n - 2)
        >>> fibonacci(10)
        55

        Cache management methods:

        >>> double.cache_info()
        {'strategy': 'ttl', 'is_async': False}
        >>> double.cache_clear()  # Clear cached values
    """

    def decorator(f: F) -> F:
        # Create strategy instance
        cache_strategy = _create_strategy(
            strategy=strategy,
            ttl=ttl,
            maxsize=maxsize,
            cache_dir=cache_dir,
            check_mtime=check_mtime,
            serializer=serializer,
        )

        # Check if function is async
        is_async = inspect.iscoroutinefunction(f)

        if is_async:
            # Async wrapper
            @functools.wraps(f)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                # Generate cache key
                cache_key = cache_strategy.make_key(f, args, kwargs)

                # Check cache
                cached_value = cache_strategy.get(cache_key)
                if cached_value is not None:
                    return cached_value

                # Call async function
                result = await f(*args, **kwargs)

                # Store in cache
                cache_strategy.set(cache_key, result)

                return result

            # Add cache management methods
            async_wrapper.cache_clear = cache_strategy.clear  # type: ignore[attr-defined]

            def _async_cache_info() -> dict[str, Any]:
                return {"strategy": strategy or "ttl", "is_async": True}

            async_wrapper.cache_info = _async_cache_info  # type: ignore[attr-defined]

            return async_wrapper  # type: ignore[return-value]

        # Sync wrapper
        @functools.wraps(f)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            # Generate cache key
            cache_key = cache_strategy.make_key(f, args, kwargs)

            # Check cache
            cached_value = cache_strategy.get(cache_key)
            if cached_value is not None:
                return cached_value

            # Call function
            result = f(*args, **kwargs)

            # Store in cache
            cache_strategy.set(cache_key, result)

            return result

        # Add cache management methods
        sync_wrapper.cache_clear = cache_strategy.clear  # type: ignore[attr-defined]

        def _sync_cache_info() -> dict[str, Any]:
            return {"strategy": strategy or "ttl", "is_async": False}

        sync_wrapper.cache_info = _sync_cache_info  # type: ignore[attr-defined]

        return sync_wrapper  # type: ignore[return-value]

    # Handle both @cache and @cache(...) syntax
    if func is not None:
        return decorator(func)

    return decorator
