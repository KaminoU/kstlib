# Cache Utilities

Public API for the caching layer, covering the decorator entry point and the strategies that back it. The
module keeps a consistent contract across sync and async callables, so you can cache coroutines and legacy
helpers without branching the implementation.

```{tip}
Pair this reference with {doc}`../features/cache/index` for the feature guide.
```

## Quick overview

- `cache` wraps any callable and auto-detects async functions so you do not need two decorators.
- Strategy selection follows the standard priority chain: keyword arguments > `kstlib.conf.yml` > presets.
- TTL, LRU, and file-backed strategies ship out of the box; custom strategies can extend `CacheStrategy`.
- Every wrapped function exposes `cache_clear()` and `cache_info()` helpers for test hygiene and observability.

## Configuration cascade

The decorator consults the loaded config each time it needs to spawn (or respawn) a strategy. A minimal config
block looks like:

```yaml
cache:
    default_strategy: ttl
    ttl:
        default_seconds: 600
        max_entries: 2048
```

You can override any of these knobs per call site:

```python
from kstlib.cache import cache

@cache(strategy="file", cache_dir="/tmp/kst-cache", serializer="auto")
def expensive_lookup(key: str) -> dict:
    return fetch_remote_payload(key)
```

---

## Decorator

### cache

```{eval-rst}
.. autofunction:: kstlib.cache.cache
   :noindex:
```

---

## Strategies

### CacheStrategy

```{eval-rst}
.. autoclass:: kstlib.cache.CacheStrategy
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

### TTLCacheStrategy

```{eval-rst}
.. autoclass:: kstlib.cache.TTLCacheStrategy
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

### LRUCacheStrategy

```{eval-rst}
.. autoclass:: kstlib.cache.LRUCacheStrategy
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

### FileCacheStrategy

```{eval-rst}
.. autoclass:: kstlib.cache.FileCacheStrategy
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

---

## Configuration Limits

### CacheLimits

```{eval-rst}
.. autoclass:: kstlib.limits.CacheLimits
   :members:
   :show-inheritance:
   :noindex:
```

### get_cache_limits

```{eval-rst}
.. autofunction:: kstlib.limits.get_cache_limits
   :noindex:
```
