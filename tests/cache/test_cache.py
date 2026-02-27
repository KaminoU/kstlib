"""Typed unit tests for the cache module."""

# pylint: disable=missing-function-docstring,missing-class-docstring,protected-access

from __future__ import annotations

import asyncio
import io
import os
import pickle
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, ParamSpec, Protocol, TypeVar, cast, overload

import pytest
from pytest import MonkeyPatch

from kstlib.cache import FileCacheStrategy, LRUCacheStrategy, TTLCacheStrategy, cache
from kstlib.cache import decorator as cache_decorator
from kstlib.cache import strategies as strategies_module
from kstlib.cache.strategies import CacheStrategy
from kstlib.config.exceptions import ConfigFileNotFoundError


class CachedCallable(Protocol):
    """Protocol describing helpers exposed by cached callables."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Invoke the cached callable with positional and keyword arguments."""
        ...

    def cache_info(self) -> dict[str, Any]:
        """Return cache statistics as a dictionary."""
        ...

    def cache_clear(self) -> None:
        """Evict all entries from the cache."""
        ...


class AsyncCachedCallable(CachedCallable, Protocol):
    """Protocol for cached async callables."""

    def __call__(self, *args: Any, **kwargs: Any) -> Awaitable[Any]:
        """Invoke the async cached callable and return an awaitable."""
        ...


P = ParamSpec("P")
R = TypeVar("R")


class CacheDecorator(Protocol):
    """Protocol describing the cache decorator overloads for typing."""

    @overload
    def __call__(self, func: Callable[P, R]) -> Callable[P, R]: ...

    @overload
    def __call__(
        self,
        *,
        strategy: str | None = ...,
        ttl: int | None = ...,
        maxsize: int | None = ...,
        cache_dir: str | None = ...,
        check_mtime: bool | None = ...,
        serializer: str | None = ...,
    ) -> Callable[[Callable[P, R]], Callable[P, R]]: ...


typed_cache = cast(CacheDecorator, cache)


class TestTTLCacheStrategy:
    """Behavioural tests for the TTL strategy."""

    def test_basic_get_set(self) -> None:
        """Store and retrieve a value using the TTL strategy."""
        strategy = TTLCacheStrategy(ttl=10)
        strategy.set("key1", "value1")
        assert strategy.get("key1") == "value1"

    def test_expiration(self) -> None:
        """Verify that entries are evicted after the TTL elapses."""
        strategy = TTLCacheStrategy(ttl=1)
        strategy.set("key1", "value1")
        assert strategy.get("key1") == "value1"
        time.sleep(1.1)
        assert strategy.get("key1") is None

    def test_max_entries(self) -> None:
        """Oldest entry is evicted when max_entries limit is reached."""
        strategy = TTLCacheStrategy(ttl=100, max_entries=2)
        strategy.set("key1", "value1")
        strategy.set("key2", "value2")
        strategy.set("key3", "value3")
        assert strategy.get("key1") is None
        assert strategy.get("key2") == "value2"
        assert strategy.get("key3") == "value3"

    def test_clear(self) -> None:
        """Confirm that clear() removes all TTL cache entries."""
        strategy = TTLCacheStrategy()
        strategy.set("a", 1)
        strategy.set("b", 2)
        strategy.clear()
        assert strategy.get("a") is None
        assert strategy.get("b") is None


class TestLRUCacheStrategy:
    """Behavioural tests for the LRU strategy."""

    def test_basic_get_set(self) -> None:
        """Store and retrieve a value using the LRU strategy."""
        strategy = LRUCacheStrategy(maxsize=4)
        strategy.set("item", 123)
        assert strategy.get("item") == 123

    def test_lru_eviction(self) -> None:
        """Least recently used entry is evicted when capacity is exceeded."""
        strategy = LRUCacheStrategy(maxsize=2)
        strategy.set("one", 1)
        strategy.set("two", 2)
        assert strategy.get("one") == 1
        strategy.set("three", 3)
        assert strategy.get("one") == 1
        assert strategy.get("two") is None
        assert strategy.get("three") == 3

    def test_update_moves_to_end(self) -> None:
        """Updating an existing entry refreshes its LRU position."""
        strategy = LRUCacheStrategy(maxsize=2)
        strategy.set("one", 1)
        strategy.set("two", 2)
        strategy.set("one", 42)
        strategy.set("three", 3)
        assert strategy.get("one") == 42
        assert strategy.get("two") is None
        assert strategy.get("three") == 3

    def test_clear(self) -> None:
        """Confirm that clear() removes all LRU cache entries."""
        strategy = LRUCacheStrategy()
        strategy.set("item", "value")
        strategy.clear()
        assert strategy.get("item") is None


class TestFileCacheStrategy:
    """Tests for the file-backed cache strategy."""

    def test_basic_get_set(self, tmp_path: Path) -> None:
        """Store and retrieve a value using the file-backed strategy."""
        strategy = FileCacheStrategy(cache_dir=str(tmp_path))
        strategy.set("key", "value")
        assert strategy.get("key") == "value"

    def test_persistence(self, tmp_path: Path) -> None:
        """Cached value survives across separate strategy instances."""
        cache_dir = tmp_path / ".cache"
        FileCacheStrategy(cache_dir=str(cache_dir)).set("key", "value")
        assert FileCacheStrategy(cache_dir=str(cache_dir)).get("key") == "value"

    def test_mtime_invalidation(self, tmp_path: Path) -> None:
        """Modified source file invalidates the cached entry."""
        cache_dir = tmp_path / ".cache"
        source = tmp_path / "source.txt"
        source.write_text("initial")
        strategy = FileCacheStrategy(cache_dir=str(cache_dir), check_mtime=True)
        strategy.set("key", "value", source_path=source)
        assert strategy.get("key") == "value"

        time.sleep(0.05)
        source.write_text("changed")
        os.utime(source, None)
        assert strategy.get("key") is None

    def test_clear(self, tmp_path: Path) -> None:
        """Confirm that clear() removes all file-backed cache entries."""
        strategy = FileCacheStrategy(cache_dir=str(tmp_path))
        strategy.set("x", 1)
        strategy.set("y", 2)
        strategy.clear()
        assert strategy.get("x") is None
        assert strategy.get("y") is None

    def test_corrupted_cache_file(self, tmp_path: Path) -> None:
        """Corrupted cache file is discarded and None is returned."""
        strategy = FileCacheStrategy(cache_dir=str(tmp_path))
        cache_file = tmp_path / "bad.cache"
        cache_file.write_bytes(b"not pickle data")
        assert strategy.get("bad") is None
        assert not cache_file.exists()

    def test_file_strategy_memory_fallback(self, tmp_path: Path) -> None:
        """In-memory fallback serves cached value when disk file is gone."""
        strategy = FileCacheStrategy(cache_dir=str(tmp_path))
        strategy.set("memory", "value")
        cache_file = tmp_path / "memory.cache"
        if cache_file.exists():
            cache_file.unlink()
        assert strategy.get("memory") == "value"

    def test_file_strategy_handles_corrupted_file(self, tmp_path: Path) -> None:
        """Corrupted cache file is deleted and None is returned on get."""
        strategy = FileCacheStrategy(cache_dir=str(tmp_path))
        key = "corrupted"
        file_path = tmp_path / f"{key}.cache"
        file_path.write_bytes(b"broken data")
        assert strategy.get(key) is None
        assert not file_path.exists()

    def test_file_strategy_json_unserializable(self, tmp_path: Path) -> None:
        """Non-JSON-serializable values fall back to in-memory cache only."""
        strategy = FileCacheStrategy(cache_dir=str(tmp_path))

        class NotSerializable:
            pass

        strategy.set("nonjson", NotSerializable())
        assert not (tmp_path / "nonjson.cache").exists()
        assert "nonjson" in strategy._memory_cache  # pylint: disable=protected-access

    def test_file_strategy_pickle_fallback(self, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
        """Failed pickle serialization falls back to in-memory cache."""
        with pytest.warns(DeprecationWarning, match="pickle serializer is deprecated"):
            strategy = FileCacheStrategy(cache_dir=str(tmp_path), serializer="pickle")

        def fail_dumps(*_args: Any, **_kwargs: Any) -> bytes:
            raise pickle.PicklingError("cannot serialize")

        strategies_any = cast(Any, strategies_module)
        monkeypatch.setattr(strategies_any.pickle, "dumps", fail_dumps)
        strategy.set("unpickleable", "value")
        assert not (tmp_path / "unpickleable.cache").exists()
        assert "unpickleable" in strategy._memory_cache  # pylint: disable=protected-access

    def test_file_strategy_loads_legacy_pickle(self, tmp_path: Path) -> None:
        """Legacy pickle cache files are loaded and their value extracted."""
        strategy = FileCacheStrategy(cache_dir=str(tmp_path))
        key = "legacy"
        cache_file = tmp_path / f"{key}.cache"
        cache_file.write_bytes(pickle.dumps({"value": "old"}))
        assert strategy.get(key) == "old"

    def test_memory_cache_eviction(self, tmp_path: Path) -> None:
        """Oldest in-memory entry is evicted when memory_max_entries is reached."""
        strategy = FileCacheStrategy(cache_dir=str(tmp_path), memory_max_entries=1)
        strategy.set("alpha", "a")
        strategy.set("beta", "b")
        assert list(strategy._memory_cache.keys()) == ["beta"]  # pylint: disable=protected-access

    def test_memory_cache_reload_respects_limit(self, tmp_path: Path) -> None:
        """Disk reload into memory respects the memory_max_entries limit."""
        strategy = FileCacheStrategy(cache_dir=str(tmp_path), memory_max_entries=1)
        strategy.set("persisted", "value")
        # Clear in-memory cache to force disk reload
        strategy._memory_cache.clear()  # pylint: disable=protected-access
        assert strategy.get("persisted") == "value"
        assert list(strategy._memory_cache.keys()) == ["persisted"]  # pylint: disable=protected-access

    def test_memory_cache_unbounded(self, tmp_path: Path) -> None:
        """All entries are retained when memory_max_entries is None."""
        strategy = FileCacheStrategy(cache_dir=str(tmp_path), memory_max_entries=None)
        strategy.set("alpha", "a")
        strategy.set("beta", "b")
        # No eviction when memory cache is unbounded
        assert list(strategy._memory_cache.keys()) == ["alpha", "beta"]  # pylint: disable=protected-access


class TestCacheDecorator:
    """Integration tests for the public cache decorator."""

    def test_basic_caching(self) -> None:
        """Decorated function is only called once for the same arguments."""
        call_count = 0

        @typed_cache
        def expensive(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x * 2

        cached_expensive = cast(CachedCallable, expensive)

        assert cached_expensive(5) == 10
        assert call_count == 1
        assert cached_expensive(5) == 10
        assert call_count == 1

    def test_ttl_strategy(self) -> None:
        """TTL-backed decorator re-calls function after expiry."""
        call_count = 0

        @typed_cache(strategy="ttl", ttl=1)
        def get_data(key: str) -> str:
            nonlocal call_count
            call_count += 1
            return f"data_{key}"

        cached_get_data = cast(CachedCallable, get_data)

        assert cached_get_data("test") == "data_test"
        assert call_count == 1
        assert cached_get_data("test") == "data_test"
        assert call_count == 1
        time.sleep(1.1)
        assert cached_get_data("test") == "data_test"
        assert call_count == 2

    def test_lru_strategy(self) -> None:
        """Verify LRU-backed decorator reports correct strategy metadata."""

        @typed_cache(strategy="lru", maxsize=2)
        def fibonacci(n: int) -> int:
            if n < 2:
                return n
            return fibonacci(n - 1) + fibonacci(n - 2)

        cached_fibonacci = cast(CachedCallable, fibonacci)
        info = cached_fibonacci.cache_info()
        assert info["strategy"] == "lru"
        assert info["is_async"] is False
        assert cached_fibonacci(5) == 5

    @pytest.mark.asyncio
    async def test_async_caching(self) -> None:
        """Verify async functions are cached correctly across awaits."""
        call_count = 0

        @typed_cache(ttl=10)
        async def async_fetch(url: str) -> str:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.01)
            return f"data_from_{url}"

        cached_async_fetch = cast(AsyncCachedCallable, async_fetch)

        assert await cached_async_fetch("http://example.com") == "data_from_http://example.com"
        assert call_count == 1
        assert await cached_async_fetch("http://example.com") == "data_from_http://example.com"
        assert call_count == 1

        info = cached_async_fetch.cache_info()
        assert info["strategy"] == "ttl"
        assert info["is_async"] is True

    def test_cache_clear(self) -> None:
        """Verify cache_clear() forces subsequent calls to re-invoke the function."""
        call_count = 0

        @typed_cache
        def get_value(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x

        cached_get_value = cast(CachedCallable, get_value)
        assert cached_get_value(1) == 1
        assert cached_get_value(2) == 2
        assert call_count == 2
        cached_get_value.cache_clear()
        assert cached_get_value(1) == 1
        assert cached_get_value(2) == 2
        assert call_count == 4

    def test_kwargs_caching(self) -> None:
        """Verify equivalent kwargs signatures share the same cache entry."""
        call_count = 0

        @typed_cache
        def process(a: int, b: int, c: int = 0) -> int:
            nonlocal call_count
            call_count += 1
            return a + b + c

        cached_process = cast(CachedCallable, process)

        assert cached_process(1, 2) == 3
        assert call_count == 1
        assert cached_process(1, 2, 0) == 3
        assert call_count == 1
        assert cached_process(1, b=2) == 3
        assert call_count == 1
        assert cached_process(1, 2, c=5) == 8
        assert call_count == 2

    def test_config_fallback(self, monkeypatch: MonkeyPatch) -> None:
        """Verify cache works when config file is not found."""

        def mock_get_config() -> Any:
            raise ConfigFileNotFoundError("No config found")

        monkeypatch.setattr(cache_decorator, "get_config", mock_get_config)

        @typed_cache
        def compute(x: int) -> int:
            return x * 2

        cached_compute = cast(CachedCallable, compute)

        assert cached_compute(5) == 10
        assert cached_compute(5) == 10

    def test_signature_binding_fallback(self) -> None:
        """Verify make_key falls back gracefully when binding kwargs with **kwargs."""

        def func(x: Any, **_kwargs: Any) -> Any:
            return x

        key = CacheStrategy.make_key(func, ([1, 2],), {"payload": {"nested": "value"}})
        assert isinstance(key, str)
        assert key

    def test_make_key_bind_failure(self) -> None:
        """Verify make_key produces a valid key even when signature binding fails."""

        def func(required: int) -> int:
            return required

        key = CacheStrategy.make_key(func, (), {"required": 1, "extra": 2})
        assert isinstance(key, str)
        assert key

    def test_ttl_cleanup_removes_expired_entries(self, monkeypatch: MonkeyPatch) -> None:
        """Verify TTL cleanup removes stale cache entries after interval elapses."""

        class TimeStub:
            def __init__(self) -> None:
                self.current = 0.0

            def time(self) -> float:
                return self.current

        time_stub = TimeStub()
        strategies_any = cast(Any, strategies_module)
        monkeypatch.setattr(strategies_any.time, "time", time_stub.time)

        strategy = strategies_module.TTLCacheStrategy(ttl=2, cleanup_interval=1)
        strategy.set("key", "value")
        time_stub.current = 3.0
        assert strategy.get("key") is None
        assert "key" not in strategy._cache  # pylint: disable=protected-access

    def test_file_strategy_memory_fallback(self, tmp_path: Path) -> None:
        """Verify in-memory fallback serves value when disk file is gone."""
        strategy = FileCacheStrategy(cache_dir=str(tmp_path))
        strategy.set("present", "value")
        cache_file = tmp_path / "present.cache"
        if cache_file.exists():
            cache_file.unlink()
        assert strategy.get("present") == "value"

    def test_get_cache_config_with_cache_section(self, monkeypatch: MonkeyPatch) -> None:
        """Verify _get_cache_config extracts settings from cache config section."""

        class DummyConfig:
            def __init__(self) -> None:
                self.cache = {
                    "default_strategy": "lru",
                    "lru": {"maxsize": 42, "typed": True},
                }

        def build_dummy_config() -> DummyConfig:
            return DummyConfig()

        monkeypatch.setattr(cache_decorator, "get_config", build_dummy_config)
        config = cache_decorator._get_cache_config()  # pylint: disable=protected-access
        assert config["default_strategy"] == "lru"
        assert config["lru"]["maxsize"] == 42
        assert config["lru"]["typed"] is True

    def test_create_strategy_file_uses_config_defaults(self, monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
        """Verify file strategy is created with cache_dir from config defaults."""
        cache_dir = tmp_path / "custom-cache"

        def config_factory() -> dict[str, Any]:
            return {
                "default_strategy": "ttl",
                "file": {"cache_dir": str(cache_dir), "check_mtime": False},
            }

        monkeypatch.setattr(cache_decorator, "_get_cache_config", config_factory)  # pylint: disable=protected-access

        strategy = cache_decorator._create_strategy(strategy="file")  # pylint: disable=protected-access
        assert isinstance(strategy, FileCacheStrategy)
        assert strategy.cache_dir == cache_dir
        assert strategy.check_mtime is False

    def test_create_strategy_unknown_falls_back_to_ttl(self, monkeypatch: MonkeyPatch) -> None:
        """Verify unknown strategy name falls back to TTL strategy."""

        def empty_config() -> dict[str, Any]:
            return {}

        monkeypatch.setattr(cache_decorator, "_get_cache_config", empty_config)  # pylint: disable=protected-access
        strategy = cache_decorator._create_strategy(strategy="missing")  # pylint: disable=protected-access
        assert isinstance(strategy, TTLCacheStrategy)


class TestCacheInternals:
    """Regression tests covering internal helpers and error branches."""

    def test_restricted_unpickler_allows_basic_builtins(self) -> None:
        """Ensure whitelisted builtins can be resolved safely."""

        unpickler = strategies_module._RestrictedUnpickler(io.BytesIO(b""))
        assert unpickler.find_class("builtins", "dict") is dict

    def test_restricted_unpickler_blocks_untrusted_globals(self) -> None:
        """Ensure non-whitelisted globals trigger a ValueError."""

        unpickler = strategies_module._RestrictedUnpickler(io.BytesIO(b""))
        with pytest.raises(ValueError):
            unpickler.find_class("os", "system")

    def test_file_strategy_rejects_unknown_serializer(self) -> None:
        """Unsupported serializer names must raise immediately."""

        with pytest.raises(ValueError):
            FileCacheStrategy(serializer="yaml")

    def test_file_strategy_handles_write_failures(self, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
        """Disk write failures should not leave cache artifacts behind."""

        strategy = FileCacheStrategy(cache_dir=str(tmp_path))
        cache_file = tmp_path / "fail.cache"

        def fail_write_bytes(_self: Path, _data: bytes) -> None:  # pragma: no cover - helper
            raise OSError("disk full")

        monkeypatch.setattr(Path, "write_bytes", fail_write_bytes, raising=False)
        strategy.set("fail", "value")
        assert not cache_file.exists()

    def test_auto_serializer_falls_back_to_pickle(self, tmp_path: Path) -> None:
        """Auto serializer should pickle payloads that JSON cannot handle."""

        strategy = FileCacheStrategy(cache_dir=str(tmp_path), serializer="auto")
        payload = {"value": {"numbers": {1, 2}}}
        encoded = strategy._serialize_payload(payload)  # pylint: disable=protected-access
        assert pickle.loads(encoded) == payload

    def test_serialize_payload_rejects_unknown_serializer(self, tmp_path: Path) -> None:
        """Manual serializer mutations should raise ValueError."""

        strategy = FileCacheStrategy(cache_dir=str(tmp_path))
        strategy.serializer = "unknown"
        with pytest.raises(ValueError):
            strategy._serialize_payload({"value": 42})  # pylint: disable=protected-access

    def test_validate_key_rejects_path_traversal(self) -> None:
        """Cache keys with traversal characters must raise ValueError."""

        with pytest.raises(ValueError):
            FileCacheStrategy._validate_key("../secrets")  # pylint: disable=protected-access

    def test_json_default_serializes_path_objects(self) -> None:
        """Path objects should serialize as strings for JSON payloads."""

        sample_path = Path("data/file.txt")
        result = FileCacheStrategy._json_default(sample_path)  # pylint: disable=protected-access
        assert result == str(sample_path)

    def test_deserialize_payload_rejects_empty_data(self, tmp_path: Path) -> None:
        """Empty payloads must raise ValueError during deserialization."""

        strategy = FileCacheStrategy(cache_dir=str(tmp_path))
        with pytest.raises(ValueError):
            strategy._deserialize_payload(b"")  # pylint: disable=protected-access

    def test_deserialize_payload_requires_mapping(self, tmp_path: Path) -> None:
        """Non-mapping JSON payloads should raise TypeError."""

        strategy = FileCacheStrategy(cache_dir=str(tmp_path))
        with pytest.raises(TypeError):
            strategy._deserialize_payload(b"[]")  # pylint: disable=protected-access
