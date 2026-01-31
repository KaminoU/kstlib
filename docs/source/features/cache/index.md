# Cache

Memoization decorator with TTL, LRU, and file-backed strategies. Auto-detects async functions.

## TL;DR

```python
from kstlib.cache import cache

@cache(ttl=300)
def expensive_computation(x: int) -> int:
    return x ** 2

result = expensive_computation(5)  # Computed
result = expensive_computation(5)  # Cached
```

## Key Features

- **Auto-detection**: Works with both sync and async functions
- **Multiple strategies**: TTL, LRU, and file-backed caching
- **Configuration-driven**: Settings from `kstlib.conf.yml` or per-call overrides
- **Cache management**: `cache_clear()` and `cache_info()` on wrapped functions

## Quick Start

```python
from kstlib.cache import cache

# 1. TTL-based caching (expires after 60 seconds)
@cache(ttl=60)
def get_weather(city: str) -> dict:
    return api.fetch_weather(city)

# 2. LRU caching (fixed-size, evicts oldest)
@cache(strategy="lru", maxsize=512)
def get_user(user_id: int) -> dict:
    return db.fetch_user(user_id)

# 3. File-backed caching (persistent across restarts)
@cache(strategy="file", cache_dir="/tmp/cache")
def load_data(path: str) -> dict:
    return parse_file(path)
```

## How It Works

The `@cache` decorator wraps your function and stores results keyed by arguments.

**Three strategies available:**

| Strategy | Expiration | Persistence | Use Case |
| - | - | - | - |
| `ttl` | Time-based | Memory only | API responses, volatile data |
| `lru` | Size-based | Memory only | Bounded memory, frequent lookups |
| `file` | Optional mtime | Disk | Large data, survives restarts |

**Async auto-detection**: The decorator inspects whether your function is async and creates the appropriate wrapper automatically.

```python
# Sync function -> sync wrapper
@cache(ttl=60)
def sync_fetch(x): ...

# Async function -> async wrapper (detected automatically)
@cache(ttl=60)
async def async_fetch(x): ...
```

**Cache key generation**: Arguments are hashed to create unique cache keys. For file-backed caching, the first positional argument can be used for mtime checks.

## Configuration

### In kstlib.conf.yml

```yaml
cache:
  default_strategy: ttl
  ttl:
    default_seconds: 600
    max_entries: 2048
  lru:
    maxsize: 1024
  file:
    cache_dir: ~/.cache/kstlib
    serializer: json  # json | pickle | auto
```

### Per-call overrides

```python
@cache(
    strategy="file",
    cache_dir="/tmp/kst-cache",
    serializer="auto",
)
def expensive_lookup(key: str) -> dict:
    return fetch_remote(key)
```

## Common Patterns

### API response caching

```python
@cache(ttl=300)  # 5-minute cache
def get_exchange_rate(pair: str) -> float:
    return api.fetch_rate(pair)
```

### Database query caching

```python
@cache(strategy="lru", maxsize=1024)
def get_user_profile(user_id: int) -> dict:
    return db.query("SELECT * FROM users WHERE id = %s", user_id)
```

### Config file with auto-invalidation

```python
@cache(strategy="file", check_mtime=True)
def read_config(path: Path) -> dict:
    return load_yaml(path)  # Re-reads if file changes
```

### Async trading data

```python
@cache(strategy="lru", maxsize=256)
async def fetch_order_book(symbol: str) -> dict:
    return await exchange.get_book(symbol)
```

### Cache management

```python
@cache(ttl=300)
def expensive_call(x: int) -> int:
    return x ** 2

# Clear all cached entries
expensive_call.cache_clear()

# Get cache statistics
info = expensive_call.cache_info()
print(f"Hits: {info.hits}, Misses: {info.misses}")
```

## Troubleshooting

### Cache not invalidating

**TTL strategy**: Entries only expire on access. If `ttl=60` and you access after 120s, it will recompute.

**File strategy with mtime**: Ensure `check_mtime=True` is set and the path argument is first.

```python
# Correct - path is first argument
@cache(strategy="file", check_mtime=True)
def read_file(path: Path, encoding: str = "utf-8") -> str: ...

# Wrong - path is not first, mtime check won't work
@cache(strategy="file", check_mtime=True)
def read_file(encoding: str, path: Path) -> str: ...
```

### Memory growing too large

Use LRU with a bounded `maxsize`:

```python
@cache(strategy="lru", maxsize=512)  # Max 512 entries
def bounded_cache(key: str) -> dict: ...
```

### Pickle security warning

```{warning}
Only use `pickle` or `auto` serializer when the cache is read/written on the same trusted host. Never deserialize untrusted cache files.
```

For safer serialization:

```python
@cache(strategy="file", serializer="json")  # Safe but limited types
def safe_cache(key: str) -> dict: ...
```

### File serializer compatibility

| Serializer | Pros | Cons |
| - | - | - |
| `json` | Safe, human-readable | Limited types (no datetime, set, etc.) |
| `pickle` | Any Python object | Security risk with untrusted data |
| `auto` | Best of both | Tries JSON first, falls back to pickle |

## API Reference

Full autodoc: {doc}`../../api/cache`

| Function | Description |
| - | - |
| `@cache(...)` | Decorator for memoization |
| `.cache_clear()` | Clear all cached entries |
| `.cache_info()` | Get hit/miss statistics |
