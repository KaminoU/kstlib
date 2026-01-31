"""Cache module for kstlib.

Provides flexible caching decorators with multiple strategies:
- TTL (Time-To-Live) based caching
- LRU (Least Recently Used) caching
- File-based caching with mtime invalidation
- Full async/await support

Examples:
    Basic usage with default TTL strategy::

        from kstlib.cache import cache

        @cache
        def expensive_function(x: int) -> int:
            return x * 2

    Async function caching::

        @cache(ttl=60)
        async def fetch_data(url: str) -> dict:
            # Automatically detects async and handles appropriately
            return await http_get(url)

    LRU strategy::

        @cache(strategy="lru", maxsize=256)
        def compute_fibonacci(n: int) -> int:
            if n < 2:
                return n
            return compute_fibonacci(n-1) + compute_fibonacci(n-2)

    File-based caching with mtime checking::

        @cache(strategy="file", check_mtime=True)
        def load_config(path: str) -> dict:
            # Cache invalidates automatically if file modified
            return parse_yaml(path)
"""

from kstlib.cache.decorator import cache
from kstlib.cache.strategies import CacheStrategy, FileCacheStrategy, LRUCacheStrategy, TTLCacheStrategy

__all__ = [
    "CacheStrategy",
    "FileCacheStrategy",
    "LRUCacheStrategy",
    "TTLCacheStrategy",
    "cache",
]
