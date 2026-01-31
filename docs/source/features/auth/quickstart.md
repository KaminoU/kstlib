# Quickstart

Get authenticated with an OIDC provider in 5 minutes.

## Prerequisites

- An OIDC provider (Keycloak, Auth0, Okta, Azure AD, Google, etc.)
- Client ID (and optionally client secret)
- SOPS configured for token encryption (see {doc}`/development/secrets-management`)

## 1. Configure Your Provider

Add the provider to your `kstlib.conf.yml`:

```yaml
auth:
  default_provider: "my-provider"
  token_storage: "sops"

  storage:
    sops:
      directory: "~/.config/kstlib/auth/tokens"

  providers:
    my-provider:
      type: "oidc"
      issuer: "https://your-idp.example.com/realms/main"
      client_id: "your-client-id"
      scopes: ["openid", "profile", "email"]
      pkce: true
```

```{tip}
With OIDC, you only need the `issuer` URL. Endpoints are auto-discovered from `{issuer}/.well-known/openid-configuration`.
```

## 2. Login via CLI

```bash
# Login with default provider
kstlib auth login

# Or specify the provider
kstlib auth login my-provider
```

This will:

1. Open your browser to the provider's login page
2. Wait for the OAuth callback
3. Exchange the code for tokens
4. Encrypt and store tokens with SOPS

```{note}
Use `--no-browser` if you need to copy the URL manually (e.g., SSH session).
```

## 3. Check Status

```bash
# Check if authenticated
kstlib auth status

# See user info
kstlib auth whoami
```

## 4. Use in Code

### Recommended: AuthSession

Use `AuthSession` for automatic token injection, refresh, and 401 retry:

```python
from kstlib.auth import OIDCProvider, AuthSession

provider = OIDCProvider.from_config("my-provider")

with AuthSession(provider) as session:
    response = session.get("https://api.example.com/resource")
    # Token injected automatically
    # Auto-refresh if expired
    # Retry on 401
```

Async version:

```python
async with AuthSession(provider) as session:
    response = await session.aget("https://api.example.com/resource")
```

### Alternative: Direct token access

If you need the raw token (e.g., for a different HTTP library):

```python
from kstlib.auth import OIDCProvider

provider = OIDCProvider.from_config("my-provider")
token = provider.get_token()  # Auto-refreshes if needed

import httpx
response = httpx.get(
    "https://api.example.com/resource",
    headers={"Authorization": f"Bearer {token.access_token}"}
)
```

```{tip}
`AuthSession` is the recommended approach. It handles token lifecycle automatically
and ensures proper session cleanup via context manager.
```

## 5. Logout

```bash
kstlib auth logout
```

## Try It Locally

A working example with local Keycloak is available in `examples/auth/`:

```bash
# 1. Start local Keycloak
cd infra
docker compose up -d keycloak

# 2. Run the example
cd examples/auth
kstlib auth login keycloak-dev

# Browser opens -> login with: testuser / testpass123

# 3. Verify
kstlib auth status
kstlib auth whoami
```

See `examples/auth/kstlib.conf.yml` for the complete configuration.

```{seealso}
{doc}`/development/infra/keycloak` for Keycloak setup details.
```

## Next Steps

- {doc}`configuration` - Full configuration reference
- {doc}`cli` - All CLI commands
- {doc}`token-storage` - Token security details
