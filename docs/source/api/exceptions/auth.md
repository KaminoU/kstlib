# Auth Exceptions

Exceptions for the authentication module: OAuth2/OIDC providers, tokens, and session management.

## Exception hierarchy

```
AuthError (base)
├── ConfigurationError        # Invalid auth configuration
├── ProviderNotFoundError     # Provider not in config
├── DiscoveryError            # OIDC discovery failed
├── TokenError
│   ├── TokenExpiredError     # Token has expired
│   ├── TokenRefreshError     # Refresh token failed
│   ├── TokenExchangeError    # Code exchange failed
│   ├── TokenValidationError  # Token validation failed
│   └── TokenStorageError     # Token storage operation failed
├── AuthorizationError        # Authorization flow failed
├── CallbackServerError       # OAuth callback server issue
└── PreflightError            # Preflight checks failed
```

## Common failure modes

- `ProviderNotFoundError` is raised when requesting a provider not defined in `kstlib.conf.yml`.
- `DiscoveryError` surfaces when OIDC auto-discovery fails (network error, invalid issuer URL).
- `TokenExpiredError` indicates the access token has expired and refresh is needed.
- `TokenRefreshError` is raised when refresh token exchange fails (revoked, expired refresh token).
- `CallbackServerError` occurs when the local OAuth callback server cannot start (port in use).

## Usage patterns

### Handling token expiry

```python
from kstlib.auth import AuthSession
from kstlib.auth.errors import TokenExpiredError, TokenRefreshError

session = AuthSession(provider="keycloak")

try:
    token = session.get_valid_token()
except TokenExpiredError:
    try:
        token = session.refresh()
    except TokenRefreshError:
        # Refresh failed - need full re-auth
        token = session.login()
```

### Safe provider lookup

```python
from kstlib.auth.config import get_provider_config
from kstlib.auth.errors import ProviderNotFoundError

try:
    config = get_provider_config("my-provider")
except ProviderNotFoundError:
    logger.error("Provider not configured")
    config = get_provider_config("default")
```

### Handling callback server issues

```python
from kstlib.auth import AuthSession
from kstlib.auth.errors import CallbackServerError

try:
    session.login()
except CallbackServerError as e:
    logger.error(f"Callback server failed: {e}")
    print("Try closing other applications using port 8400")
```

## API reference

```{eval-rst}
.. automodule:: kstlib.auth.errors
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```
