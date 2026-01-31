# Secrets Management

How kstlib handles secrets under the hood.

## The Cascade

When you call `secrets.resolve_secret("api.key")`, kstlib checks providers in order:

```text
kwargs → env vars → keyring → SOPS → default
   ↓         ↓          ↓        ↓        ↓
 First match wins. If nothing found, raise or return default.
```

| Provider | Source | Use case |
| --- | --- | --- |
| `kwargs` | Passed directly to `resolve_secret()` | Testing, overrides |
| `env` | Environment variables | CI/CD, containers |
| `keyring` | System keychain (macOS Keychain, Windows Credential Manager, etc.) | Desktop apps |
| `sops` | SOPS-encrypted files | Git-tracked secrets |
| `default` | Fallback value | Development defaults |

## Configuration

Configure the resolver in `kstlib.conf.yml`:

```yaml
secrets:
  # Default SOPS file path (optional)
  sops:
    path: secrets.sops.yml
    binary: sops  # or full path

  # Keyring service name (optional)
  keyring:
    service: kstlib

  # Secure delete settings (for --shred)
  secure_delete:
    method: auto      # auto | command | overwrite
    passes: 3
    zero_last_pass: true
```

## Providers in Detail

### Environment Variables

The env provider maps dotted paths to uppercase env vars:

```python
# "mail.smtp.password" looks for:
#   MAIL_SMTP_PASSWORD
#   KSTLIB_MAIL_SMTP_PASSWORD (with prefix)

import os
os.environ["MAIL_SMTP_PASSWORD"] = "secret"

record = secrets.resolve_secret("mail.smtp.password")
# record.source == SecretSource.ENV
```

### Keyring

Uses the system's secure credential storage:

```python
import keyring

# Store a secret
keyring.set_password("kstlib", "api.stripe_key", "sk_live_xxx")

# kstlib will find it
record = secrets.resolve_secret("api.stripe_key")
# record.source == SecretSource.KEYRING
```

### SOPS

The SOPS provider decrypts on-demand and caches results:

```python
# Default: looks for secrets.sops.yml in current directory
record = secrets.resolve_secret("mail.smtp.password")

# Or specify the file
record = secrets.resolve_secret(
    "mail.smtp.password",
    metadata={"path": "config/prod.sops.yml"},
)
```

Features:

- **LRU cache**: Decrypted documents are cached (default: 16 entries)
- **Mtime tracking**: Cache invalidates when file changes
- **Format auto-detection**: JSON, YAML, or raw text

## SecretResolver API

For advanced use cases, work with the resolver directly:

```python
from kstlib.secrets import get_secret_resolver, SecretRequest

resolver = get_secret_resolver()

# Configure providers
resolver.configure({
    "sops": {"path": "my-secrets.sops.yml"},
    "keyring": {"service": "myapp"},
})

# Resolve with full control
request = SecretRequest(
    name="database.password",
    scope="production",
    required=True,
    metadata={"key_path": "db.prod.password"},
)
record = resolver.resolve(request)
```

## The `sensitive` Context Manager

Secrets should live in memory as briefly as possible:

```python
from kstlib.secrets import resolve_secret, sensitive

# Step 1: Resolve to get a SecretRecord
record = resolve_secret("api.key")

# Step 2: Use sensitive() to auto-purge after use
with sensitive(record) as secret_value:
    response = call_api(api_key=secret_value)
# record.value is now None - secret purged from memory
```

This is especially important for:

- Long-running services
- Multi-tenant applications
- Security-critical operations

## Error Handling

### Recommended: with `sensitive()` (secure)

Combine the context manager with exception handling for both security and robustness:

```python
from kstlib.secrets import (
    resolve_secret,
    sensitive,
    SecretNotFoundError,
    SecretDecryptionError,
)

try:
    record = resolve_secret("api.key", required=True)
    with sensitive(record) as secret_value:
        response = call_api(api_key=secret_value)
    # record.value is now None
except SecretNotFoundError:
    # No provider could resolve the secret
    logger.warning("API key not configured, using fallback")
    response = call_api_anonymous()
except SecretDecryptionError:
    # SOPS decryption failed (wrong key, corrupted file, etc.)
    logger.error("Cannot decrypt secrets file")
    raise
# Secret purged from memory regardless of success/failure
```

### Basic approach (use with caution)

```{warning}
The approach below leaves the secret in the resolver cache until explicitly purged or the process exits.
Prefer the `sensitive()` context manager above for production code.
```

```python
from kstlib.secrets import (
    SecretNotFoundError,
    SecretDecryptionError,
    resolve_secret,
)

try:
    record = resolve_secret("missing.key", required=True)
except SecretNotFoundError:
    # No provider could resolve the secret
    pass
except SecretDecryptionError:
    # SOPS decryption failed (wrong key, corrupted file, etc.)
    pass
```

## Security Notes

1. **Never log secrets**: kstlib redacts sensitive output, but be careful in your code
2. **Use `--shred`**: Securely delete plaintext files after encryption
3. **Restrict key permissions**: `chmod 400 ~/.config/sops/age/keys.txt` (read-only) since the key never needs rewriting
4. **Rotate regularly**: Both secret values and encryption keys
5. **Use `sensitive()`**: Minimize secret lifetime in memory
