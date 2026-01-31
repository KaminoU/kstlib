# Secrets

Public API for the secrets subsystem, covering credential resolution across multiple providers such as kwargs,
configuration files, keyring backends, and SOPS encrypted payloads.

```{tip}
For usage guide and examples, see {doc}`../features/secrets/index`.
```

## Quick overview

- `resolve_secret(name)` is the main entry point for resolving a secret by name.
- `SecretResolver` orchestrates credential resolution across multiple providers.
- `sensitive` decorator marks functions whose return values should not be logged.
- Exceptions distinguish not-found (`SecretNotFoundError`) from decryption failures (`SecretDecryptionError`).

---

## Resolver

### resolve_secret

```{eval-rst}
.. autofunction:: kstlib.secrets.resolve_secret
   :noindex:
```

### get_secret_resolver

```{eval-rst}
.. autofunction:: kstlib.secrets.get_secret_resolver
   :noindex:
```

### SecretResolver

```{eval-rst}
.. autoclass:: kstlib.secrets.SecretResolver
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

---

## Models

### SecretRecord

```{eval-rst}
.. autoclass:: kstlib.secrets.SecretRecord
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

### SecretRequest

```{eval-rst}
.. autoclass:: kstlib.secrets.SecretRequest
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

### SecretSource

```{eval-rst}
.. autoclass:: kstlib.secrets.SecretSource
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

---

## Sensitive Decorator

### sensitive

```{eval-rst}
.. autofunction:: kstlib.secrets.sensitive
   :noindex:
```

### CachePurgeProtocol

```{eval-rst}
.. autoclass:: kstlib.secrets.CachePurgeProtocol
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

---

## Exceptions

### SecretError

```{eval-rst}
.. autoclass:: kstlib.secrets.SecretError
   :show-inheritance:
   :noindex:
```

### SecretNotFoundError

```{eval-rst}
.. autoclass:: kstlib.secrets.SecretNotFoundError
   :show-inheritance:
   :noindex:
```

### SecretDecryptionError

```{eval-rst}
.. autoclass:: kstlib.secrets.SecretDecryptionError
   :show-inheritance:
   :noindex:
```
