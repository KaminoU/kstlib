# Database

Async SQLite database module with connection pooling, SQLCipher encryption, and SOPS secret integration.

## TL;DR

```python
from kstlib.db import AsyncDatabase

# Simple in-memory database
async with AsyncDatabase(":memory:") as db:
    await db.execute("CREATE TABLE users (id INTEGER, name TEXT)")
    await db.execute("INSERT INTO users VALUES (?, ?)", (1, "alice"))
    row = await db.fetch_one("SELECT * FROM users WHERE id=?", (1,))
    print(row)  # (1, 'alice')

# Encrypted database with SOPS key management
# secrets.yml contains: { "database_key": "my-sqlcipher-passphrase" }
# The passphrase is used by SQLCipher to encrypt the entire .db file
db = AsyncDatabase(
    "app.db",
    cipher_sops="secrets.yml",      # SOPS-encrypted file with the passphrase
    cipher_sops_key="database_key"  # Key name inside the SOPS file
)
async with db:
    # All data in app.db is encrypted at rest via SQLCipher
    await db.execute("SELECT * FROM users")

# Connection pooling for high-concurrency
db = AsyncDatabase(
    "trading.db",
    pool_min=2,
    pool_max=20,
    pool_timeout=30.0
)
```

## Installation

SQLite async support is included by default. For SQLCipher encryption:

```bash
pip install kstlib[db-crypto]
```

**System dependencies for SQLCipher:**

| Platform | Command |
| - | - |
| Debian/Ubuntu | `sudo apt-get install libsqlcipher-dev` |
| macOS | `brew install sqlcipher` |
| Windows | Pre-built wheels included |

**Check availability:**

```python
from kstlib.db import is_sqlcipher_available

if is_sqlcipher_available():
    print("SQLCipher ready for encrypted databases")
else:
    print("Install: pip install kstlib[db-crypto]")
```

## Key Features

- **Async Interface**: Built on `aiosqlite` for non-blocking database operations
- **Connection Pooling**: Configurable pool with health checks and automatic retry
- **SQLCipher Encryption**: Transparent encryption at rest with SQLCipher
- **SOPS Integration**: Secure key management via SOPS-encrypted files
- **Transaction Support**: Automatic commit/rollback with context managers
- **WAL Mode**: Write-ahead logging enabled for better concurrency
- **Query Helpers**: Convenient methods for common patterns (fetch_one, fetch_all, etc.)

## Quick Start

### Basic Usage

```python
from kstlib.db import AsyncDatabase

async def main():
    async with AsyncDatabase(":memory:") as db:
        # Create table
        await db.execute("""
            CREATE TABLE products (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                price REAL
            )
        """)

        # Insert data
        await db.execute(
            "INSERT INTO products (name, price) VALUES (?, ?)",
            ("Widget", 9.99)
        )

        # Query data
        row = await db.fetch_one("SELECT * FROM products WHERE id=?", (1,))
        print(row)  # (1, 'Widget', 9.99)

        # Fetch all rows
        rows = await db.fetch_all("SELECT * FROM products")

        # Fetch single value
        count = await db.fetch_value("SELECT count(*) FROM products")
```

### Encrypted Database

```python
from kstlib.db import AsyncDatabase

# Option 1: Direct passphrase (not recommended for production)
db = AsyncDatabase("secure.db", cipher_key="my-secret-passphrase")

# Option 2: Environment variable
db = AsyncDatabase("secure.db", cipher_env="DB_ENCRYPTION_KEY")

# Option 3: SOPS file (recommended)
db = AsyncDatabase(
    "secure.db",
    cipher_sops="secrets.yml",
    cipher_sops_key="database_key"  # Key name in SOPS file
)
```

### Transactions

```python
from kstlib.db import AsyncDatabase

async with AsyncDatabase("app.db") as db:
    # Transaction with automatic commit/rollback
    async with db.transaction() as conn:
        await conn.execute("INSERT INTO accounts VALUES (?, ?)", (1, 1000))
        await conn.execute("INSERT INTO accounts VALUES (?, ?)", (2, 500))
        # Commits automatically if no exception
        # Rolls back if exception occurs
```

## How It Works

### Connection Pool Architecture

```text
     Application
         │
         ▼
 ┌───────────────┐
 │ AsyncDatabase │  High-level API
 └───────┬───────┘
         │
         ▼
┌────────────────┐
│ ConnectionPool │  Pool management
│   ○ ○ ○ ○ ○    │  (min_size to max_size connections)
└────────┬───────┘
         │
         ▼
 ┌───────────────┐
 │   aiosqlite   │  Async SQLite wrapper
 └───────┬───────┘
         │
         ▼
┌──────────────────┐
│ SQLite/SQLCipher │  Database engine
└──────────────────┘
```

### Pool Behavior

| Parameter | Default | Hard Limits | Description |
| - | - | - | - |
| `pool_min` | 1 | 0-10 | Minimum connections to maintain |
| `pool_max` | 10 | 1-100 | Maximum connections allowed |
| `pool_timeout` | 30.0 | 1.0-300.0 | Seconds to wait for available connection |
| `max_retries` | 3 | 1-10 | Retry attempts on connection failure |
| `retry_delay` | 0.5 | 0.1-60.0 | Seconds between retries |

### Connection Lifecycle

1. **Acquire**: Get connection from pool (or create new if under max)
2. **Health Check**: Verify connection is alive with `SELECT 1`
3. **Use**: Execute queries
4. **Release**: Return connection to pool for reuse

### Encryption Flow

```text
Key Resolution (priority order):
    1. cipher_key (direct passphrase)
    2. cipher_env (environment variable)
    3. cipher_sops (SOPS file)
           │
           ▼
┌─────────────────┐
│ resolve_cipher_ │
│      key()      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ apply_cipher_   │  PRAGMA key = '...'
│      key()      │
└────────┬────────┘
         │
         ▼
    Encrypted DB
```

## Configuration

### In kstlib.conf.yml

```yaml
db:
  pool:
    # Minimum connections to maintain in pool (0 = lazy pool, on-demand)
    # Hard limits enforced in code: min 0, max 10
    min_size: 1
    # Maximum connections allowed in pool
    # Hard limits enforced in code: min 1, max 100
    max_size: 10
    # Timeout for acquiring a connection (seconds)
    # Hard limits enforced in code: min 1.0, max 300.0 (5 minutes)
    acquire_timeout: 30.0
  retry:
    # Retry attempts on connection failure
    # Hard limits enforced in code: min 1, max 10
    max_attempts: 3
    # Delay between retries (seconds)
    # Hard limits enforced in code: min 0.1, max 60.0
    delay: 0.5

  # SQLCipher encryption (opt-in, requires: pip install kstlib[db-crypto])
  cipher:
    # Enable SQLCipher encryption (default: false)
    enabled: false
    # Key source: env | sops | passphrase
    key_source: env
    # Environment variable containing the encryption key
    key_env: "KSTLIB_DB_KEY"
    # SOPS configuration (when key_source: sops)
    sops_path: null
    sops_key: "db_key"
```

```{note}
All configuration values are enforced with hard limits in code for deep defense.
Values outside the allowed range are automatically clamped to the nearest bound.
```

### SOPS Secrets File

```yaml
# secrets.yml (encrypted with SOPS)
database_key: ENC[AES256_GCM,data:...,iv:...,tag:...]
api_token: ENC[AES256_GCM,data:...,iv:...,tag:...]
```

### Per-Instance Override

```python
db = AsyncDatabase(
    "app.db",
    pool_min=5,
    pool_max=50,
    pool_timeout=60.0,
    max_retries=5
)
```

## Common Patterns

### Trading Bot Database

```python
from kstlib.db import AsyncDatabase

class TradingDatabase:
    def __init__(self, db_path: str, sops_path: str):
        self.db = AsyncDatabase(
            db_path,
            cipher_sops=sops_path,
            pool_min=2,
            pool_max=10
        )

    async def connect(self):
        await self.db.connect()
        await self._init_schema()

    async def _init_schema(self):
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)

    async def record_trade(
        self, symbol: str, side: str, quantity: float, price: float
    ):
        from datetime import datetime, timezone

        await self.db.execute(
            "INSERT INTO trades (symbol, side, quantity, price, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (symbol, side, quantity, price, datetime.now(timezone.utc).isoformat())
        )

    async def get_recent_trades(self, limit: int = 100):
        return await self.db.fetch_all(
            "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        )

    async def close(self):
        await self.db.close()
```

### Bulk Insert with Transaction

```python
async with AsyncDatabase("data.db") as db:
    async with db.transaction() as conn:
        await conn.executemany(
            "INSERT INTO records (key, value) VALUES (?, ?)",
            [(f"key_{i}", i * 10) for i in range(1000)]
        )
```

### Multiple Databases

```python
from kstlib.db import AsyncDatabase

class MultiDB:
    def __init__(self):
        self.users_db = AsyncDatabase("users.db")
        self.trades_db = AsyncDatabase("trades.db", cipher_env="TRADES_KEY")
        self.cache_db = AsyncDatabase(":memory:")

    async def connect_all(self):
        await self.users_db.connect()
        await self.trades_db.connect()
        await self.cache_db.connect()

    async def close_all(self):
        await self.users_db.close()
        await self.trades_db.close()
        await self.cache_db.close()
```

### Connection Pool Monitoring

```python
from kstlib.db import AsyncDatabase

db = AsyncDatabase("app.db", pool_min=2, pool_max=10)

async with db:
    # Check pool statistics
    stats = db.stats
    print(f"Total connections: {stats.total_connections}")
    print(f"Active: {stats.active_connections}")
    print(f"Idle: {stats.idle_connections}")
    print(f"Acquired: {stats.total_acquired}")
    print(f"Released: {stats.total_released}")
    print(f"Timeouts: {stats.total_timeouts}")
    print(f"Errors: {stats.total_errors}")
```

### Direct Connection Access

```python
async with AsyncDatabase("app.db") as db:
    # When you need raw connection access
    async with db.connection() as conn:
        await conn.execute("PRAGMA optimize")
        await conn.execute("VACUUM")
```

## Troubleshooting

### Database file is locked

**Cause**: Another process has exclusive lock or WAL checkpoint pending.

**Solution**: Enable WAL mode (enabled by default) or close other connections:

```python
# WAL is enabled automatically, but you can force checkpoint
async with db.connection() as conn:
    await conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
```

### Pool exhausted timeout

**Cause**: All connections in use and pool at max capacity.

**Solution**: Increase pool size or reduce connection hold time:

```python
db = AsyncDatabase(
    "app.db",
    pool_max=50,          # Increase max connections
    pool_timeout=60.0     # Increase wait timeout
)
```

### Encryption key mismatch

**Cause**: Wrong key used to open existing encrypted database.

**Solution**: Verify key source is correct:

```python
# Check if database is encrypted
db = AsyncDatabase("app.db", cipher_key="my-key")
print(f"Encrypted: {db.is_encrypted}")
```

### SOPS key not found

**Cause**: Key name not present in SOPS file.

**Solution**: Verify the key name matches:

```python
# SOPS file contains: { "db_key": "secret" }
db = AsyncDatabase(
    "app.db",
    cipher_sops="secrets.yml",
    cipher_sops_key="db_key"  # Must match key in SOPS file
)
```

### Connection health check fails

**Cause**: Connection dropped or database file moved/deleted.

**Solution**: Pool automatically handles this by discarding dead connections and creating new ones. Check stats for error count:

```python
if db.stats.total_errors > 10:
    print("High error rate - check database health")
```

## API Reference

Full autodoc: {doc}`../../api/db`

| Class | Description |
| - | - |
| `AsyncDatabase` | High-level async database interface |
| `ConnectionPool` | Connection pool with health checks |
| `PoolStats` | Pool statistics dataclass |

| Function | Description |
| - | - |
| `is_sqlcipher_available` | Check if SQLCipher is installed |
| `resolve_cipher_key` | Resolve encryption key from various sources |
| `apply_cipher_key` | Apply SQLCipher key to connection (low-level) |

| Exception | Description |
| - | - |
| `DatabaseError` | Base exception for database operations |
| `ConnectionError` | Connection establishment failed |
| `EncryptionError` | Encryption/decryption failed |
| `PoolExhaustedError` | No connections available in pool |
| `TransactionError` | Transaction commit/rollback failed |
