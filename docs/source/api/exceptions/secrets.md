# Secrets Exceptions

The secrets subsystem exposes a concise trio rooted at `SecretError`.
Providers and resolvers coerce their failures into these shapes so you can keep retry logic deterministic across local config, keyring backends, and encrypted payloads.

## Exception Hierarchy

```
SecretError
├── SecretNotFoundError      # Secret not found in any provider
└── SecretDecryptionError    # Decryption failed (bad key, corrupted)
```

## Quick overview

- `SecretError` is the umbrella exception you can catch around entire resolver pipelines.
- `SecretNotFoundError` tells you that every provider was queried but none returned a value.
- `SecretDecryptionError` indicates the payload was located yet could not be decrypted (bad key, mismatch between SOPS profiles, corrupted blob).

## Usage patterns

### Falling back to default credentials

```python
from kstlib.secrets import resolve_secret
from kstlib.secrets.exceptions import SecretNotFoundError

try:
    api_key = resolve_secret("rest.api_key")
except SecretNotFoundError:
    api_key = os.environ.get("FALLBACK_API_KEY")
    if api_key is None:
        raise SystemExit("Missing API key, aborting")
```

### Surfacing decrypt errors explicitly

```python
from kstlib.secrets import get_secret_resolver
from kstlib.secrets.exceptions import SecretDecryptionError

resolver = get_secret_resolver()

try:
    resolver.resolve("vault.trade_key")
except SecretDecryptionError as error:
    LOGGER.error("Secret payload rejected", secret="vault.trade_key", error=error)
    raise
```

## Module reference

```{eval-rst}
.. automodule:: kstlib.secrets.exceptions
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```
