# Providers

kstlib provides two authentication providers: `OIDCProvider` for OpenID Connect and `OAuth2Provider` for standard OAuth2.

## Which Provider to Use?

| Provider | Use When |
|----------|----------|
| `OIDCProvider` | Your IdP supports OIDC discovery (most modern IdPs) |
| `OAuth2Provider` | Your IdP doesn't support OIDC (e.g., GitHub OAuth) |

```{tip}
**Use OIDC when possible**. It auto-discovers endpoints, validates tokens, and provides standardized user info.
```

## OIDCProvider

OpenID Connect provider with automatic endpoint discovery.

### Features

- Auto-discovers endpoints from `{issuer}/.well-known/openid-configuration`
- Validates ID tokens (signature, claims, expiration)
- Provides `get_userinfo()` for user profile data
- Supports PKCE (recommended)
- Caches discovery document (configurable TTL)

### Usage

```python
from kstlib.auth import OIDCProvider

# From configuration (recommended)
provider = OIDCProvider.from_config("corporate")

# Or programmatic
from kstlib.auth import AuthProviderConfig
from kstlib.auth.token import MemoryTokenStorage

provider = OIDCProvider(
    name="corporate",
    config=AuthProviderConfig(
        issuer="https://sso.company.com/realms/main",
        client_id="my-app",
        scopes=["openid", "profile", "email"],
        pkce=True,
    ),
    token_storage=MemoryTokenStorage(),
)
```

### Authorization Flow

```python
# 1. Get authorization URL (PKCE code_verifier stored internally when pkce=True)
auth_url, state = provider.get_authorization_url()

# 2. User authenticates in browser, callback receives code

# 3. Exchange code for tokens (uses internal code_verifier automatically)
token = provider.exchange_code(
    code="authorization_code_from_callback",
    state=state,
)

# 4. Access token is now stored, ID token validated automatically
print(f"Logged in! Token expires in {token.expires_in}s")
```

### Getting User Info

```python
# Fetch OIDC userinfo
userinfo = provider.get_userinfo()
print(f"Hello, {userinfo['name']}!")
print(f"Email: {userinfo['email']}")
```

### Token Validation

ID tokens are validated automatically during `exchange_code()`. The provider verifies:
- Signature using JWKS from the issuer
- Issuer (`iss`) matches the configured issuer
- Audience (`aud`) includes the client ID
- Token is not expired (`exp`)
- Token was issued recently (`iat`)

If validation fails, a warning is logged but the exchange continues. Check the logs for validation issues.

## OAuth2Provider

Standard OAuth2 provider for non-OIDC services.

### Features

- Manual endpoint configuration
- Authorization Code flow
- Optional PKCE support
- Token refresh (if refresh token provided)

### Usage

```python
from kstlib.auth import OAuth2Provider

# From configuration
provider = OAuth2Provider.from_config("github")

# Or programmatic
from kstlib.auth import AuthProviderConfig
from kstlib.auth.token import MemoryTokenStorage

provider = OAuth2Provider(
    name="github",
    config=AuthProviderConfig(
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        client_id="your-client-id",
        client_secret="your-client-secret",
        scopes=["read:user", "user:email"],
    ),
    token_storage=MemoryTokenStorage(),
)
```

### Authorization Flow

```python
# 1. Get authorization URL
auth_url, state = provider.get_authorization_url()

# 2. User authenticates, callback receives code

# 3. Exchange code for tokens
token = provider.exchange_code(
    code="authorization_code_from_callback",
    state=state,
)
```

## Common API

Both providers share a common interface:

### Properties

```python
# Check if user is authenticated
if provider.is_authenticated:
    print("Logged in!")

# Get provider name
print(provider.name)  # "corporate"

# Get flow type
print(provider.flow)  # AuthFlow.AUTHORIZATION_CODE
```

### Token Management

```python
# Get current token (auto-refreshes if needed)
token = provider.get_token()

# Get token without auto-refresh
token = provider.get_token(auto_refresh=False)

# Force token refresh
new_token = provider.refresh_token()

# Clear stored token
provider.clear_token()
```

### Token Object

```python
token = provider.get_token()

# Access token (for API calls)
token.access_token

# Token type (usually "Bearer")
token.token_type

# Expiration
token.expires_at      # datetime
token.expires_in      # seconds remaining
token.is_expired      # bool
token.should_refresh  # bool (< 5 min remaining)

# Refresh token (if available)
token.refresh_token
token.is_refreshable  # bool

# ID token (OIDC only)
token.id_token

# Scopes granted
token.scope  # ["openid", "profile", "email"]
```

## PKCE (Proof Key for Code Exchange)

PKCE adds security to the authorization flow by preventing authorization code interception attacks.

```{important}
**Always enable PKCE** when your provider supports it. It's required for public clients and recommended for all clients.
```

### How it works

1. Provider generates a random `code_verifier` and stores it internally
2. Provider sends `code_challenge` (hash of verifier) with auth request
3. Provider sends `code_verifier` automatically with token exchange
4. Server verifies the challenge matches

All PKCE handling is automatic when `pkce=True` in your configuration.

### Enabling PKCE

```yaml
# In configuration
providers:
  corporate:
    type: "oidc"
    issuer: "https://sso.company.com"
    client_id: "my-app"
    pkce: true  # Enable PKCE
```

```python
# Programmatically
config = AuthProviderConfig(
    issuer="https://sso.company.com",
    client_id="my-app",
    pkce=True,
)
```

### PKCE Authorization Flow

```python
# PKCE is handled automatically when pkce=True in config
auth_url, state = provider.get_authorization_url()

# The code_verifier is stored internally and used automatically
token = provider.exchange_code(code=code, state=state)

# Or provide explicit code_verifier if needed (advanced use)
token = provider.exchange_code(
    code=code,
    state=state,
    code_verifier="your_custom_verifier",  # Optional override
)
```

## Error Handling

```python
from kstlib.auth.errors import (
    AuthError,           # Base class
    ConfigurationError,  # Invalid config
    TokenExchangeError,  # Code exchange failed
    TokenRefreshError,   # Refresh failed
    TokenValidationError,  # Token validation failed
)

try:
    token = provider.exchange_code(code=code, state=state)
except TokenExchangeError as e:
    if e.status_code is not None:
        # The provider answered an HTTP error status (4xx/5xx)
        print(f"Provider rejected the exchange: {e.error_code} (HTTP {e.status_code})")
    elif e.error_code is not None:
        # Local pre-network guard (state_mismatch, pkce_missing): restart the flow
        print(f"Login flow error: {e.error_code}")
    else:
        # Transport failure: the provider could not be reached
        print(f"Provider unreachable: {e}")
    if e.retryable:
        print("Transient failure, retrying may succeed")
except AuthError as e:
    print(f"Auth error: {e}")
```

See [Auth Exceptions](../../api/exceptions/auth.md) for the full contract
behind `status_code`, `error_code` and `retryable`.

## CLI vs Server-Side Consumption

`kstlib.auth` is CLI-first: one user, one process, and the provider instance
carries the per-flow state (CSRF `state`, PKCE verifier) between
`get_authorization_url()` and `exchange_code()`. A server-side application
(a multi-user web service) is different by construction: login and callback
are separate concurrent HTTP requests, so per-flow state cannot live on the
provider instance. Use the server-side profile in that case:

| Concern | CLI flow (default) | Server-side flow |
|---------|--------------------|------------------|
| State / PKCE generation | provider instance | your application, per flow |
| CSRF state validation | `exchange_code(code, state)` | your pending store, before calling kstlib |
| Exchange call | `exchange_code(code, state)` | `exchange_code_stateless(code, code_verifier=...)` |
| Token persistence | provider token storage | **yours, per user** (kstlib does not persist it) |
| `redirect_uri` | loopback (`127.0.0.1`) | public HTTPS endpoint + `server_side: true` |

```python
# Server-side callback handler (state already validated by your app)
flow = pending_flows.pop(state)        # your per-flow store
token = provider.exchange_code_stateless(
    code=code,
    code_verifier=flow.code_verifier,  # your PKCE verifier for this flow
)
store_token_for_user(user, token)      # your per-user persistence
```

Key points:

- `exchange_code_stateless()` raises the same structured `TokenExchangeError`
  contract as `exchange_code()` (`status_code`, `error_code`, `retryable`),
  including the `pkce_missing` local guard when PKCE is enabled and no
  verifier is passed.
- The returned token is **not** saved to the provider token storage: storage
  is keyed by provider name, not by end user, so persisting there would let
  concurrent users overwrite each other's tokens.
- `server_side: true` in the provider config suppresses the
  `[SECURITY] redirect_uri host ... is not localhost` warning: a public
  callback endpoint is the nominal server configuration, not an anomaly.
  CLI flows keep the warning (default `false`).
- OIDC `nonce`: kstlib generates a nonce in its own authorization URL for
  provider-side replay hardening, but does not verify the `nonce` claim in
  the returned ID token. Server-side consumers build their own authorization
  URL, so strict nonce verification (if required) is theirs, via the
  `claims["nonce"]` of the ID token.

## Tested Providers

The following identity providers have been tested:

| Provider | Type | PKCE | Notes |
|----------|------|------|-------|
| Keycloak | OIDC | Yes | Fully tested |
| Auth0 | OIDC | Yes | Should work |
| Okta | OIDC | Yes | Should work |
| Azure AD | OIDC | Yes | Should work |
| Google | OIDC | Yes | Should work |
| GitHub | OAuth2 | No | OAuth2 only, no OIDC |

```{note}
"Should work" means the provider follows standards but hasn't been integration tested. Please report any issues.
```
