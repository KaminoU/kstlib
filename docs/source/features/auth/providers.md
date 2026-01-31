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
    print(f"Login failed: {e}")
except AuthError as e:
    print(f"Auth error: {e}")
```

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
