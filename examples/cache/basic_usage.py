"""Cache examples - demonstrating different caching strategies."""

from __future__ import annotations

import asyncio
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, ParamSpec, Protocol, TypeVar, cast, overload

from kstlib.cache import FileCacheStrategy, cache

P = ParamSpec("P")
R_co = TypeVar("R_co", covariant=True)


class CacheEnabledCallable(Protocol[P, R_co]):
    """Callable returned by the cache decorator with helper methods."""

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R_co:
        """Invoke the cached callable."""
        raise NotImplementedError

    def cache_info(self) -> dict[str, Any]:
        """Return cache metadata such as strategy and async flag."""
        raise NotImplementedError

    def cache_clear(self) -> None:
        """Clear cached entries for this callable."""
        raise NotImplementedError


class CacheDecorator(Protocol):
    """Typed protocol mirroring the cache decorator overloads."""

    @overload
    def __call__(self, func: Callable[P, R_co]) -> CacheEnabledCallable[P, R_co]: ...

    @overload
    def __call__(
        self,
        *,
        strategy: str | None = ...,
        ttl: int | None = ...,
        maxsize: int | None = ...,
        cache_dir: str | None = ...,
        check_mtime: bool | None = ...,
    ) -> Callable[[Callable[P, R_co]], CacheEnabledCallable[P, R_co]]: ...


typed_cache = cast(CacheDecorator, cache)


# Example 1: Basic TTL caching (default strategy)
@typed_cache
def expensive_computation(x: int, y: int) -> int:
    """Simulate expensive computation with 2-second delay."""
    print(f"  Computing {x} + {y}...")
    time.sleep(2)
    return x + y


# Example 2: Custom TTL duration
@typed_cache(ttl=5)  # Cache for 5 seconds
def fetch_user_data(user_id: int) -> dict[str, Any]:
    """Simulate API call to fetch user data."""
    print(f"  Fetching data for user {user_id} from API...")
    time.sleep(1)
    return {"id": user_id, "name": f"User_{user_id}", "active": True}


# Example 3: LRU cache for recursive functions
@typed_cache(strategy="lru", maxsize=100)
def fibonacci(n: int) -> int:
    """Calculate fibonacci number with LRU caching."""
    if n < 2:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)


# Example 4: Async function caching
@typed_cache(ttl=10)
async def async_fetch_data(url: str) -> str:
    """Simulate async API call."""
    print(f"  Async fetching from {url}...")
    await asyncio.sleep(1)
    return f"Data from {url}"


# Example 5: Cache with keyword arguments
@typed_cache(strategy="ttl", ttl=60)
def search_products(
    category: str,
    min_price: float = 0,
    max_price: float = 1000,
) -> list[dict[str, Any]]:
    """Search products with filters - demonstrates kwargs caching."""
    print(f"  Searching {category} products (${min_price}-${max_price})...")
    time.sleep(1)
    return [{"name": f"Product_{i}", "category": category, "price": min_price + i * 10} for i in range(3)]


# Example 7: File cache with mtime tracking
def file_cache_demo() -> None:
    """Showcase file-based caching with automatic mtime invalidation."""
    cache_root = Path(".cache_file_example")
    source_root = Path(".cache_file_example_sources")
    cache_root.mkdir(parents=True, exist_ok=True)
    source_root.mkdir(parents=True, exist_ok=True)

    strategy = FileCacheStrategy(cache_dir=str(cache_root), check_mtime=True, memory_max_entries=2)
    settings_file = source_root / "settings.txt"
    settings_file.write_text("api_key=initial\n", encoding="utf-8")

    def load_settings() -> str:
        """Read settings with file cache fallback to disk."""
        key = "settings"
        cached = strategy.get(key)
        if cached is not None:
            print("  Cache hit (memory or disk)")
            return cast(str, cached)

        print("  Cache miss -> reading file")
        content = settings_file.read_text(encoding="utf-8")
        strategy.set(key, content, source_path=settings_file)
        return content

    print("First read (populates cache)...")
    print(load_settings().strip())

    print("Second read (should hit cache)...")
    print(load_settings().strip() + " <- Cached!")

    print("Updating settings file to trigger mtime invalidation...")
    time.sleep(0.2)  # Ensure filesystem timestamp changes
    settings_file.write_text("api_key=rotated\n", encoding="utf-8")

    print("Third read (expect cache miss after update)...")
    print(load_settings().strip() + " <- Reloaded after mtime change")

    # Housekeeping for the example script
    strategy.clear()
    shutil.rmtree(cache_root, ignore_errors=True)
    shutil.rmtree(source_root, ignore_errors=True)


def main() -> None:
    """Run cache examples."""
    print("=" * 60)
    print("KSTLIB CACHE EXAMPLES")
    print("=" * 60)

    # Example 1: Basic TTL caching
    print("\n1. Basic TTL Cache (default strategy)")
    print("-" * 40)
    start = time.time()
    result1 = expensive_computation(10, 20)
    print(f"Result: {result1} (took {time.time() - start:.2f}s)")

    start = time.time()
    result2 = expensive_computation(10, 20)  # Should use cache
    print(f"Result: {result2} (took {time.time() - start:.2f}s) <- Cached!")

    # Example 2: Custom TTL
    print("\n2. Custom TTL (5 seconds)")
    print("-" * 40)
    user = fetch_user_data(123)
    print(f"User data: {user}")

    user = fetch_user_data(123)  # Cached
    print(f"User data: {user} <- Cached!")

    print("Waiting 6 seconds for cache to expire...")
    time.sleep(6)

    user = fetch_user_data(123)  # Cache expired, will fetch again
    print(f"User data: {user} <- Cache expired, fetched again!")

    # Example 3: LRU cache for fibonacci
    print("\n3. LRU Cache (recursive fibonacci)")
    print("-" * 40)
    start = time.time()
    fib_result = fibonacci(30)
    print(f"fibonacci(30) = {fib_result} (took {time.time() - start:.4f}s)")

    # Check cache info
    info = fibonacci.cache_info()
    print(f"Cache info: {info}")

    # Example 4: Async caching
    print("\n4. Async Function Caching")
    print("-" * 40)

    async def async_example() -> None:
        # First call
        start = time.time()
        data1 = await async_fetch_data("https://api.example.com/data")
        print(f"Result: {data1} (took {time.time() - start:.2f}s)")

        # Second call (cached)
        start = time.time()
        data2 = await async_fetch_data("https://api.example.com/data")
        print(f"Result: {data2} (took {time.time() - start:.2f}s) <- Cached!")

    asyncio.run(async_example())

    # Example 5: Kwargs caching
    print("\n5. Cache with Keyword Arguments")
    print("-" * 40)

    # Same effective call, different syntax
    products1 = search_products("electronics", min_price=100, max_price=500)
    print(f"Found {len(products1)} products")

    products2 = search_products("electronics", 100, 500)  # Should use cache
    print(f"Found {len(products2)} products <- Cached!")

    products3 = search_products("electronics", min_price=200, max_price=500)  # Different args
    print(f"Found {len(products3)} products <- New search (different args)")

    # Example 6: Cache clearing
    print("\n6. Cache Management (clear)")
    print("-" * 40)

    result = expensive_computation(5, 10)
    print(f"Computed: {result}")

    result = expensive_computation(5, 10)
    print(f"Cached: {result}")

    print("Clearing cache...")
    expensive_computation.cache_clear()

    result = expensive_computation(5, 10)
    print(f"After clear: {result} <- Computed again!")

    # Example 7: File cache demo
    print("\n7. File Cache with mtime Tracking")
    print("-" * 40)
    file_cache_demo()

    print("\n" + "=" * 60)
    print("Examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
