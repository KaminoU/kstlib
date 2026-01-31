# Database

Public API for async SQLite database operations with connection pooling and SQLCipher encryption.
Provides a high-level interface for database operations with automatic connection management.

```{tip}
Pair this reference with {doc}`../features/db/index` for the feature guide.
```

## Quick overview

- `AsyncDatabase` provides the main entry point for database operations
- `ConnectionPool` manages connection lifecycle with health checks and retry
- `PoolStats` tracks pool usage statistics
- `is_sqlcipher_available()` checks if SQLCipher encryption is available
- Encryption keys can be sourced from passphrase, environment variable, or SOPS
- All operations are async-first with context manager support

## Configuration cascade

The module consults the loaded config for default values. A minimal config block:

```yaml
db:
  pool:
    min_size: 2
    max_size: 20
    acquire_timeout: 30.0
  retry:
    max_attempts: 3
    delay: 0.5
  cipher:
    enabled: false        # Opt-in SQLCipher encryption
    key_source: env       # env | sops | passphrase
    key_env: "KSTLIB_DB_KEY"
```

Override any of these per instance:

```python
from kstlib.db import AsyncDatabase

db = AsyncDatabase(
    "app.db",
    pool_min=5,
    pool_max=50,
    pool_timeout=60.0
)
```

## Usage patterns

### Basic database operations

```python
from kstlib.db import AsyncDatabase

async with AsyncDatabase(":memory:") as db:
    await db.execute("CREATE TABLE test (id INTEGER)")
    await db.execute("INSERT INTO test VALUES (?)", (1,))
    row = await db.fetch_one("SELECT * FROM test")
```

### Encrypted database with SOPS

```python
from kstlib.db import AsyncDatabase

db = AsyncDatabase(
    "secure.db",
    cipher_sops="secrets.yml",
    cipher_sops_key="database_key"
)
async with db:
    await db.execute("SELECT * FROM sensitive_data")
```

### Transaction with automatic rollback

```python
async with db.transaction() as conn:
    await conn.execute("INSERT INTO accounts VALUES (?, ?)", (1, 1000))
    await conn.execute("INSERT INTO accounts VALUES (?, ?)", (2, 500))
    # Commits on success, rolls back on exception
```

### Direct connection access

```python
async with db.connection() as conn:
    await conn.execute("PRAGMA optimize")
```

### Key resolution from various sources

```python
from kstlib.db import resolve_cipher_key

# From passphrase
key = resolve_cipher_key(passphrase="direct-key")

# From environment variable
key = resolve_cipher_key(env_var="DB_KEY")

# From SOPS file
key = resolve_cipher_key(sops_path="secrets.yml", sops_key="db_key")
```

## Module reference

```{eval-rst}
.. automodule:: kstlib.db
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```

## Database class

```{eval-rst}
.. automodule:: kstlib.db.database
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```

## Connection pool

```{eval-rst}
.. automodule:: kstlib.db.pool
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```

## Cipher utilities

```{eval-rst}
.. automodule:: kstlib.db.cipher
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```

## Async SQLCipher

```{eval-rst}
.. automodule:: kstlib.db.aiosqlcipher
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```

## Exceptions

```{eval-rst}
.. automodule:: kstlib.db.exceptions
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```
