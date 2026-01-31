# DB Exceptions

Exceptions for the async database module: connection pooling, transactions, and SQLCipher encryption.

## Exception hierarchy

```
DatabaseError (base)
├── ConnectionError      # Connection establishment failed
├── EncryptionError      # Cipher key resolution or application failed
├── PoolExhaustedError   # No connections available in pool
└── TransactionError     # Transaction commit/rollback failed
```

## Common failure modes

- `ConnectionError` is raised when the pool cannot establish a connection after retrying (network issue, database file missing, or pool closed).
- `EncryptionError` surfaces when cipher key resolution fails (missing environment variable, invalid SOPS file, or wrong passphrase).
- `PoolExhaustedError` indicates all pool connections are in use and the acquire timeout has expired.
- `TransactionError` wraps any exception that occurs within a `db.transaction()` block after rollback.

## Usage patterns

### Handling pool exhaustion

```python
from kstlib.db import AsyncDatabase
from kstlib.db.exceptions import PoolExhaustedError

db = AsyncDatabase("app.db", pool_max=5, pool_timeout=10.0)

try:
    async with db.connection() as conn:
        await conn.execute("SELECT * FROM large_table")
except PoolExhaustedError:
    logger.warning("Connection pool exhausted, consider increasing pool_max")
    # Retry with backoff or queue the request
```

### Safe encryption setup

```python
from kstlib.db import AsyncDatabase
from kstlib.db.exceptions import EncryptionError

try:
    db = AsyncDatabase(
        "secure.db",
        cipher_sops="secrets.yml",
        cipher_sops_key="database_key"
    )
except EncryptionError as e:
    logger.error(f"Encryption setup failed: {e}")
    # Fallback to unencrypted or abort
```

### Transaction error handling

```python
from kstlib.db import AsyncDatabase
from kstlib.db.exceptions import TransactionError

async with AsyncDatabase("app.db") as db:
    try:
        async with db.transaction() as conn:
            await conn.execute("INSERT INTO accounts VALUES (?, ?)", (1, 1000))
            await conn.execute("INSERT INTO accounts VALUES (?, ?)", (2, 500))
    except TransactionError as e:
        logger.error(f"Transaction failed and rolled back: {e}")
        # Handle rollback notification
```

### Connection retry exhaustion

```python
from kstlib.db import AsyncDatabase
from kstlib.db.exceptions import ConnectionError

db = AsyncDatabase("remote.db", max_retries=3, retry_delay=1.0)

try:
    await db.connect()
except ConnectionError as e:
    logger.error(f"Database unreachable after retries: {e}")
    # Trigger alert or failover
```

## API reference

```{eval-rst}
.. automodule:: kstlib.db.exceptions
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```
