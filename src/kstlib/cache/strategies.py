"""Cache strategy implementations.

Provides different caching strategies with unified interface:
- TTL (Time-To-Live): Cache with expiration time
- LRU (Least Recently Used): Cache with size limit
- File: Cache with file modification time tracking (JSON-backed by default)
"""

from __future__ import annotations

import hashlib
import inspect
import io
import json
import logging
import pickle
import time
import warnings
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar, cast

from kstlib.limits import CacheLimits, get_cache_limits
from kstlib.utils.formatting import format_bytes

logger = logging.getLogger(__name__)

_CACHE_FORMAT_VERSION = "kstlib:file-cache:v1"
_SUPPORTED_SERIALIZERS: set[str] = {"json", "pickle", "auto"}
_PICKLE_SAFE_BUILTINS: set[str] = {
    "dict",
    "list",
    "set",
    "tuple",
    "str",
    "int",
    "float",
    "bool",
    "bytes",
    "NoneType",
}


class _RestrictedUnpickler(pickle.Unpickler):
    """Unpickler that only allows basic builtins used by legacy cache entries."""

    def find_class(self, module: str, name: str) -> Any:
        if module == "builtins" and name in _PICKLE_SAFE_BUILTINS:
            return super().find_class(module, name)
        raise ValueError(f"Disallowed pickle global: {module}.{name}")


F = TypeVar("F", bound=Callable[..., Any])


class CacheStrategy(ABC):
    """Abstract base class for cache strategies.

    All cache strategies must implement get() and set() methods
    to store and retrieve cached values.
    """

    @abstractmethod
    def get(self, key: str) -> Any | None:
        """Retrieve value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """

    @abstractmethod
    def set(self, key: str, value: Any) -> None:
        """Store value in cache.

        Args:
            key: Cache key
            value: Value to cache
        """

    @abstractmethod
    def clear(self) -> None:
        """Clear all cached values."""

    @staticmethod
    def make_key(func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
        """Generate cache key from function and arguments.

        Normalizes function calls by binding arguments to signature,
        ensuring that process(1, 2) and process(1, 2, c=0) produce
        the same cache key when c has default value 0.

        Args:
            func: Function being cached
            args: Positional arguments
            kwargs: Keyword arguments

        Returns:
            Hash-based cache key
        """
        # Include function module and name
        key_parts = [func.__module__, func.__qualname__]

        # Bind arguments to function signature to normalize
        try:
            sig = inspect.signature(func)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()  # Apply default values

            # Use normalized bound arguments
            for name, value in bound.arguments.items():
                key_parts.append(f"{name}={value}")

        except (TypeError, ValueError):  # Binding can fail for some callables
            # Fallback to simple key generation if binding fails
            key_parts.extend(f"arg:{arg}" for arg in args)
            key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))

        # Generate hash for consistent key
        key_str = "|".join(str(part) for part in key_parts)
        return hashlib.sha256(key_str.encode()).hexdigest()


class TTLCacheStrategy(CacheStrategy):
    """Time-To-Live cache strategy.

    Caches values with expiration time. Expired entries are removed
    automatically during cleanup or access.

    Args:
        ttl: Time to live in seconds
        max_entries: Maximum number of cache entries
        cleanup_interval: Seconds between cleanup runs

    Examples:
        >>> cache = TTLCacheStrategy(ttl=300, max_entries=1000)
        >>> cache.set("key1", "value1")
        >>> cache.get("key1")
        'value1'
    """

    def __init__(
        self,
        ttl: int = 300,
        max_entries: int = 1000,
        cleanup_interval: int = 60,
    ) -> None:
        """Initialize TTL cache strategy."""
        self.ttl = ttl
        self.max_entries = max_entries
        self.cleanup_interval = cleanup_interval
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._last_cleanup = time.time()

    def get(self, key: str) -> Any | None:
        """Retrieve value from cache if not expired.

        Args:
            key: Cache key

        Returns:
            Cached value or None if expired/not found
        """
        self._maybe_cleanup()

        if key not in self._cache:
            return None

        value, expiry = self._cache[key]

        # Check expiration
        if time.time() > expiry:
            del self._cache[key]
            return None

        return value

    def set(self, key: str, value: Any) -> None:
        """Store value in cache with TTL.

        Args:
            key: Cache key
            value: Value to cache
        """
        # If key exists, remove it first to update order
        if key in self._cache:
            del self._cache[key]

        # Enforce max entries with O(1) FIFO eviction
        while len(self._cache) >= self.max_entries:
            self._cache.popitem(last=False)

        expiry = time.time() + self.ttl
        self._cache[key] = (value, expiry)

    def clear(self) -> None:
        """Clear all cached values."""
        self._cache.clear()
        self._last_cleanup = time.time()

    def _maybe_cleanup(self) -> None:
        """Run cleanup if interval exceeded."""
        now = time.time()
        if now - self._last_cleanup > self.cleanup_interval:
            self._cleanup()
            self._last_cleanup = now

    def _cleanup(self) -> None:
        """Remove expired entries."""
        now = time.time()
        expired_keys = [key for key, (_, expiry) in self._cache.items() if now > expiry]
        for key in expired_keys:
            del self._cache[key]


class LRUCacheStrategy(CacheStrategy):
    """Least Recently Used cache strategy.

    Wraps functools.lru_cache for compatibility with CacheStrategy interface.

    Args:
        maxsize: Maximum cache size
        typed: If True, cache different types separately

    Examples:
        >>> cache = LRUCacheStrategy(maxsize=128)
        >>> cache.set("key1", "value1")
        >>> cache.get("key1")
        'value1'
    """

    def __init__(self, maxsize: int = 128, typed: bool = False) -> None:
        """Initialize LRU cache strategy."""
        self.maxsize = maxsize
        self.typed = typed
        self._store: OrderedDict[str, Any] = OrderedDict()

    def get(self, key: str) -> Any | None:
        """Retrieve value from cache and update access order.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found
        """
        if key not in self._store:
            return None

        self._store.move_to_end(key)
        return self._store[key]

    def set(self, key: str, value: Any) -> None:
        """Store value in cache with LRU eviction.

        Args:
            key: Cache key
            value: Value to cache
        """
        # If key exists, update and move to end
        if key in self._store:
            self._store[key] = value
            self._store.move_to_end(key)
            return

        # Evict LRU if at maxsize
        if len(self._store) >= self.maxsize:
            self._store.popitem(last=False)

        # Add new entry
        self._store[key] = value

    def clear(self) -> None:
        """Clear all cached values."""
        self._store.clear()


class FileCacheStrategy(CacheStrategy):
    """File-based cache with mtime checking.

    Caches function results based on file modification time and persists
    values on disk using JSON serialization by default. A pickle-based
    fallback can be enabled explicitly for trusted environments or
    automatically by using the ``"auto"`` serializer.

    Args:
        cache_dir: Directory for cache files.
        check_mtime: If True, invalidate cache on file modification.
        serializer: Serialization format (``"json"`` | ``"pickle"`` | ``"auto"``).
        memory_max_entries: Max entries to retain in memory cache.
        limits: Optional CacheLimits for config-driven size limits.

    Examples:
        >>> cache = FileCacheStrategy(cache_dir=".cache", check_mtime=True)
        >>> # Cache will invalidate if the source file changes
    """

    #: Default maximum entries for in-memory cache layer.
    DEFAULT_MEMORY_MAX_ENTRIES = 256

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(
        self,
        cache_dir: str = ".cache",
        check_mtime: bool = True,
        serializer: str = "json",
        memory_max_entries: int | None = DEFAULT_MEMORY_MAX_ENTRIES,
        limits: CacheLimits | None = None,
    ) -> None:
        """Initialize file cache strategy."""
        self.cache_dir = Path(cache_dir)
        self.check_mtime = check_mtime
        if serializer not in _SUPPORTED_SERIALIZERS:
            raise ValueError(f"Unsupported serializer '{serializer}'. Supported: {_SUPPORTED_SERIALIZERS}.")
        if serializer == "pickle":
            warnings.warn(
                "pickle serializer is deprecated since v1.56.0 due to security concerns. "
                "Use 'json' (default) or 'auto' for legacy compatibility. "
                "pickle support will be removed in v2.0.0.",
                DeprecationWarning,
                stacklevel=2,
            )
        self.serializer = serializer
        # None means unbounded memory cache; explicit values must be >= 1
        if memory_max_entries is not None and memory_max_entries < 1:
            raise ValueError("memory_max_entries must be at least 1")
        self.memory_max_entries = memory_max_entries
        self._limits = limits or get_cache_limits()
        self._memory_cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()

        # Create cache directory with proper permissions
        self.cache_dir.mkdir(parents=True, exist_ok=True, mode=0o755)

    def get(self, key: str) -> Any | None:
        """Retrieve value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/invalid
        """
        self._validate_key(key)
        # Check file cache for mtime validation
        cache_file = self.cache_dir / f"{key}.cache"
        if not cache_file.exists():
            # Not in file cache, check memory cache
            if key in self._memory_cache:
                value, _ = self._memory_cache.pop(key)
                self._store_in_memory(key, value)
                return value
            return None

        try:
            # Validate file size before reading to prevent OOM
            file_size = cache_file.stat().st_size
            if file_size > self._limits.max_file_size:
                logger.warning(
                    "Cache file %s exceeds size limit (%s > %s)",
                    key,
                    format_bytes(file_size),
                    self._limits.max_file_size_display,
                )
                cache_file.unlink(missing_ok=True)
                return None
            raw_data = cache_file.read_bytes()
            cached_data = self._deserialize_payload(raw_data)
        except (
            FileNotFoundError,
            OSError,
            ValueError,
            pickle.UnpicklingError,
            json.JSONDecodeError,
            KeyError,
            EOFError,
        ):
            # Corrupted or missing cache file, remove it
            cache_file.unlink(missing_ok=True)
            self._memory_cache.pop(key, None)
            return None
        value = cached_data["value"]

        # Check mtime if enabled
        if self.check_mtime and "source_mtime" in cached_data:
            source_path = Path(cached_data.get("source_path", ""))
            if source_path.exists():
                current_mtime = source_path.stat().st_mtime
                if current_mtime > cached_data["source_mtime"]:
                    # Source modified, invalidate both caches
                    cache_file.unlink()
                    self._memory_cache.pop(key, None)
                    return None
        # Store in memory cache for faster subsequent access
        self._store_in_memory(key, value)
        return value

    def set(self, key: str, value: Any, source_path: Path | None = None) -> None:
        """Store value in cache.

        Args:
            key: Cache key
            value: Value to cache
            source_path: Optional source file path for mtime tracking
        """
        self._validate_key(key)
        # Store in memory cache
        self._store_in_memory(key, value)

        # Store in file cache
        cache_file = self.cache_dir / f"{key}.cache"

        cached_data: dict[str, Any] = {"value": value}

        # Add mtime if source path provided
        if source_path and source_path.exists():
            cached_data["source_path"] = str(source_path)
            cached_data["source_mtime"] = source_path.stat().st_mtime

        try:
            encoded = self._serialize_payload(cached_data)
        except (pickle.PicklingError, TypeError, ValueError) as exc:
            cache_file.unlink(missing_ok=True)
            if self.serializer == "json":
                logger.debug(
                    "Skipping disk cache for key %s: value not JSON serializable (%s)",
                    key,
                    exc,
                )
                return
            return

        try:
            cache_file.write_bytes(encoded)
        except (OSError, pickle.PicklingError):
            # Failed to write cache, continue without it (disk full, permission error, etc.)
            cache_file.unlink(missing_ok=True)

    def clear(self) -> None:
        """Clear all cached values."""
        self._memory_cache.clear()

        # Remove cache files
        for cache_file in self.cache_dir.glob("*.cache"):
            cache_file.unlink(missing_ok=True)

    def _store_in_memory(self, key: str, value: Any) -> None:
        """Write a value to the in-memory cache with LRU eviction."""
        self._memory_cache[key] = (value, time.time())
        self._memory_cache.move_to_end(key)
        # Skip eviction when memory_max_entries is None (unbounded)
        if self.memory_max_entries is not None:
            while len(self._memory_cache) > self.memory_max_entries:
                self._memory_cache.popitem(last=False)

    def _serialize_payload(self, payload: dict[str, Any]) -> bytes:
        """Serialize cached payload according to the configured serializer."""
        if self.serializer == "json":
            return self._serialize_json(payload)
        if self.serializer == "pickle":
            return pickle.dumps(payload)
        if self.serializer == "auto":
            try:
                return self._serialize_json(payload)
            except (TypeError, ValueError):
                return pickle.dumps(payload)
        raise ValueError(f"Unknown serializer '{self.serializer}'")

    def _serialize_json(self, payload: dict[str, Any]) -> bytes:
        wrapped = {"_format": _CACHE_FORMAT_VERSION, "payload": payload}
        return json.dumps(wrapped, default=self._json_default).encode("utf-8")

    @staticmethod
    def _validate_key(key: str) -> None:
        """Ensure the cache key cannot escape the cache directory."""
        if (".." in key) or ("/" in key) or ("\\" in key):
            raise ValueError(f"Invalid cache key contains path traversal characters: {key!r}")

    @staticmethod
    def _json_default(value: Any) -> Any:
        if isinstance(value, Path):
            return str(value)
        raise TypeError(f"Object of type {type(value)!r} is not JSON serializable")

    def _deserialize_payload(self, data: bytes) -> dict[str, Any]:
        """Deserialize payload, attempting JSON first and falling back to pickle."""
        if not data:
            raise ValueError("Empty cache payload")

        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return self._load_legacy_pickle(data)

        try:
            payload: Any = json.loads(text)
        except json.JSONDecodeError:
            return self._load_legacy_pickle(data)

        if isinstance(payload, dict) and payload.get("_format") == _CACHE_FORMAT_VERSION:
            payload = payload["payload"]

        if not isinstance(payload, dict):
            raise TypeError("Invalid cache payload structure")

        return payload

    @staticmethod
    def _load_legacy_pickle(data: bytes) -> dict[str, Any]:
        """Load trusted legacy pickle payloads used before JSON became default."""
        buffer = io.BytesIO(data)
        payload = _RestrictedUnpickler(buffer).load()
        return cast("dict[str, Any]", payload)
