# Authentication

Public API for `kstlib.auth`, providing a config-driven OAuth2/OIDC authentication layer. The module supports
Authorization Code flow with PKCE, automatic token refresh, and token storage via SOPS, file, or in-memory backends.

```{tip}
Pair this reference with {doc}`../features/auth/index` for the feature guide and quickstart examples.
```

## Quick overview

**Providers:**
- `OIDCProvider` - OpenID Connect provider with discovery and PKCE support
- `OAuth2Provider` - Generic OAuth2 provider for non-OIDC endpoints
- `AbstractAuthProvider` - Base class for custom provider implementations

**Session management:**
- `AuthSession` - Context manager wrapping `requests.Session` with automatic token injection and refresh

**Token storage:**
- `MemoryTokenStorage` - Ephemeral in-memory storage (development/testing)
- `FileTokenStorage` - Plain JSON file storage (unencrypted, for dev/non-SOPS environments)
- `SOPSTokenStorage` - Encrypted persistent storage using Mozilla SOPS
- `AbstractTokenStorage` - Base class for custom storage backends

**Token validation:**
- `TokenChecker` - 6-step JWT token verification with cryptographic proof
- `TokenCheckReport` - Complete validation report (header, payload, signature, claims)
- `ValidationStep` - Result of a single validation step

**Config helpers:**
- `OIDCProvider.from_config(name)` - Load provider from `kstlib.conf.yml`
- `get_provider_config(name)` - Retrieve raw provider configuration
- `list_configured_providers()` - List all configured provider names

---

## Providers

### OIDCProvider

```{eval-rst}
.. autoclass:: kstlib.auth.OIDCProvider
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

### OAuth2Provider

```{eval-rst}
.. autoclass:: kstlib.auth.OAuth2Provider
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

### AbstractAuthProvider

```{eval-rst}
.. autoclass:: kstlib.auth.providers.base.AbstractAuthProvider
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

---

## Session Management

### AuthSession

```{eval-rst}
.. autoclass:: kstlib.auth.AuthSession
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

---

## Token Storage

### SOPSTokenStorage

```{eval-rst}
.. autoclass:: kstlib.auth.token.SOPSTokenStorage
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

### FileTokenStorage

```{eval-rst}
.. autoclass:: kstlib.auth.token.FileTokenStorage
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

### MemoryTokenStorage

```{eval-rst}
.. autoclass:: kstlib.auth.token.MemoryTokenStorage
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

### AbstractTokenStorage

```{eval-rst}
.. autoclass:: kstlib.auth.token.AbstractTokenStorage
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

---

## Token Validation

Independent JWT token verification with cryptographic proof. Works with any RSA-signed JWT
(id_token or access_token) whose issuer exposes an OpenID Connect discovery endpoint. See the
{doc}`../features/auth/cli` feature guide for the full proof chain diagram and use cases.

### TokenChecker

```{eval-rst}
.. autoclass:: kstlib.auth.check.TokenChecker
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

### TokenCheckReport

```{eval-rst}
.. autoclass:: kstlib.auth.check.TokenCheckReport
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

### ValidationStep

```{eval-rst}
.. autoclass:: kstlib.auth.check.ValidationStep
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

---

## Models

### Token

```{eval-rst}
.. autoclass:: kstlib.auth.models.Token
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

---

## Config Helpers

### get_provider_config

```{eval-rst}
.. autofunction:: kstlib.auth.config.get_provider_config
   :noindex:
```

### list_configured_providers

```{eval-rst}
.. autofunction:: kstlib.auth.config.list_configured_providers
   :noindex:
```
