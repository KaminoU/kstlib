# Cache Exceptions

The cache subsystem reuses existing Python exceptions rather than exposing a dedicated hierarchy.
Most errors surface from configuration lookups, serializer validation, or filesystem operations performed by `FileCacheStrategy`.
This page lists the hot paths so you can harden call sites even though there is no `kstlib.cache.exceptions` module yet.

## Common failure modes

- `ConfigFileNotFoundError` bubbles up from `kstlib.config.get_config()` whenever the cache decorator tries to merge user settings but the global config is absent.
- `ValueError` appears in several scenarios: invalid strategy names, unsupported serializers, or unsafe cache keys rejected by `FileCacheStrategy._validate_key()`.
- `json.JSONDecodeError` and `pickle.UnpicklingError` indicate corrupted on-disk payloads; both errors are caught internally and converted into cache invalidation, yet you may still want to watch logs for recurring corruption.
- `OSError` and `FileNotFoundError` can still leak if the filesystem becomes read-only or the process lacks permissions to create `.cache` directories.

The decorator aims to keep those exceptions descriptive, which is why the catalog documents them even before a proper namespace exists.

## Usage patterns

### Guarding strategy selection

```python
from kstlib.cache import cache

try:
    strategy = "ttl"
    if not kwargs.get("use_ttl"):
        strategy = "file"
    decorated = cache(strategy=strategy)(fetch_orders)
except ValueError as error:
    raise RuntimeError(f"Unsupported cache strategy: {error}") from error
```

### Monitoring file cache IO

```python
from json import JSONDecodeError
from kstlib.cache.strategies import FileCacheStrategy

file_cache = FileCacheStrategy(cache_dir=".cache", serializer="json")

try:
    result = file_cache.get("book:BTCUSDT")
except (JSONDecodeError, ValueError) as error:
    LOGGER.warning("Cache payload rejected", key="book:BTCUSDT", error=error)
    file_cache.clear()
```

Even when errors remain standard library types, treating them explicitly keeps the subsystem observable and paves the way for future `CacheError` classes.
