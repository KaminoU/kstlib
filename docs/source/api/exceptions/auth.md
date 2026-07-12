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
- `DiscoveryError` surfaces when OIDC auto-discovery fails. Its `status_code`
  attribute tells whether the provider answered an HTTP error (`int`) or could
  not be reached at all (`None`).
- `TokenExpiredError` indicates the access token has expired and refresh is needed.
- `TokenRefreshError` is raised when refresh token exchange fails (revoked, expired
  refresh token). Its `retryable` attribute is `True` when retrying may succeed
  (transport failure or provider 5xx).
- `TokenExchangeError` is raised when the authorization code exchange fails. Its
  `status_code`, `error_code` and `retryable` attributes encode where the exchange
  failed (see the pattern below).
- `CallbackServerError` occurs when the local OAuth callback server cannot start (port in use).

## Usage patterns

### Distinguishing provider rejection from transport failure

A user-facing error page (or a log line) should not claim "the identity
provider could not be reached" when the provider was reached and answered a
4xx. `TokenExchangeError` and `DiscoveryError` carry a structural
discriminant so consumers never have to parse messages:

- `status_code is not None`: the provider was reached and answered this HTTP
  error status. On exchange, `error_code` is then guaranteed non-None (the
  OAuth2 `error` code, or `"unknown"` when the body is unreadable).
- `status_code is None` with `error_code` set (exchange only): a local
  pre-network guard rejected the exchange before any request was sent
  (`"state_mismatch"`, `"pkce_missing"`). Restart the authorization flow.
- Both `None`: transport failure, the provider was never reached.

```python
from kstlib.auth.errors import TokenExchangeError

try:
    token = provider.exchange_code(code=code, state=state)
except TokenExchangeError as e:
    if e.status_code is not None:
        # The provider answered an error status (4xx/5xx).
        message = f"The identity provider rejected the login: {e.error_code}"
    elif e.error_code is not None:
        # Local guard, no request was sent: restart the flow.
        message = "The login flow must be restarted"
    else:
        # No HTTP response: DNS failure, connection refused, timeout.
        message = "The identity provider could not be reached"
    if e.retryable:
        message += " (temporary, retrying may succeed)"
```

The same discriminant applies to discovery:

```python
from kstlib.auth.errors import DiscoveryError

try:
    provider.discover()
except DiscoveryError as e:
    if e.status_code is not None:
        logger.error("Provider answered HTTP %d to discovery", e.status_code)
    else:
        logger.error("Provider unreachable during discovery: %s", e.reason)
```

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
