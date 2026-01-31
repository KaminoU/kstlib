# Authentication

OAuth2 and OpenID Connect authentication for Python applications. Validate your OAuth/OIDC configuration via CLI before integrating into your code. Tokens are stored securely using {doc}`../secrets/index` (SOPS encryption with age/GPG/KMS).

```{note}
This module focuses on **authentication validation and token acquisition**. It does not include
a REST client wrapper. Once authenticated, use the obtained tokens with your preferred HTTP
library (httpx, requests, etc.).
```

```{toctree}
:maxdepth: 2
:hidden:

quickstart
configuration
providers
cli
token-storage
```

## TL;DR

```python
from kstlib.auth import OIDCProvider, AuthSession

provider = OIDCProvider.from_config("corporate")

# Recommended: AuthSession with automatic token handling
with AuthSession(provider) as session:
    response = session.get("https://api.company.com/data")
```

```bash
# CLI login
kstlib auth login corporate
kstlib auth status
kstlib auth whoami
```

## Key Features

- **Config-driven**: Define providers in `kstlib.conf.yml`, instantiate with one line
- **Auto-discovery**: OIDC providers automatically fetch endpoints from issuer
- **PKCE by default**: Secure authorization flow without client secrets
- **SOPS token storage**: Tokens encrypted via {doc}`../secrets/index` (age/GPG/KMS)
- **CLI included**: `kstlib auth login|logout|status|token|whoami|providers`
- **Token refresh**: Automatic refresh before expiration

## Quick Start

```yaml
# kstlib.conf.yml
auth:
  default_provider: corporate
  providers:
    corporate:
      type: oidc
      issuer: https://sso.company.com/realms/main
      client_id: my-app
      pkce: true
```

```bash
# Login via browser
kstlib auth login corporate

# Check status
kstlib auth status
```

```python
from kstlib.auth import OIDCProvider

provider = OIDCProvider.from_config("corporate")
token = provider.get_token()
headers = {"Authorization": f"Bearer {token.access_token}"}
```

## How It Works

### Supported Protocols

| Protocol | Status | Description |
|----------|--------|-------------|
| **OAuth2** | Supported | Authorization Code flow with manual endpoint configuration |
| **OIDC** | Supported | OpenID Connect with auto-discovery (`.well-known/openid-configuration`) |
| **PKCE** | Supported | Proof Key for Code Exchange (recommended for all flows) |

### Authentication Flow

```
1. Provider generates authorization URL with PKCE challenge
2. User authenticates in browser
3. Callback receives authorization code
4. Provider exchanges code for tokens (auto uses PKCE verifier)
5. Tokens stored securely (SOPS, file, or memory)
6. Token auto-refreshed before expiration
```

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     kstlib.auth                             │
├─────────────────────────────────────────────────────────────┤
│  Providers          │  Storage           │  CLI             │
│  ├─ OAuth2Provider  │  ├─ MemoryStorage  │  ├─ login        │
│  └─ OIDCProvider    │  ├─ FileStorage    │  ├─ logout       │
│                     │  └─ SOPSStorage    │                  │
│                     │                    │  ├─ status       │
│  Models             │  Config            │  ├─ token        │
│  ├─ Token           │  └─ auth: section  │  ├─ whoami       │
│  └─ AuthFlow        │     in conf.yml    │  └─ providers    │
└─────────────────────────────────────────────────────────────┘
```

## Configuration

### Basic OIDC provider

```yaml
auth:
  providers:
    corporate:
      type: oidc
      issuer: https://sso.company.com/realms/main
      client_id: my-app
      scopes: [openid, profile, email]
      pkce: true
```

### OAuth2 provider (manual endpoints)

```yaml
auth:
  providers:
    github:
      type: oauth2
      authorize_url: https://github.com/login/oauth/authorize
      token_url: https://github.com/login/oauth/access_token
      client_id: your-client-id
      client_secret: your-client-secret
      scopes: [read:user, user:email]
```

### Token storage

```yaml
auth:
  token_storage: sops  # or "file" or "memory"
  sops:
    path: ~/.config/kstlib/tokens.sops.yml
```

See {doc}`configuration` for complete options.

## Common Patterns

### Authenticated API requests

```python
from kstlib.auth import OIDCProvider, AuthSession

provider = OIDCProvider.from_config("corporate")

with AuthSession(provider) as session:
    response = session.get("https://api.company.com/data")
    # Token injected automatically, auto-refresh on expiration
```

### Login flow in CLI app

```python
from kstlib.auth import OIDCProvider

provider = OIDCProvider.from_config("corporate")

if not provider.is_authenticated:
    provider.login()  # Opens browser, waits for callback

userinfo = provider.get_userinfo()
print(f"Welcome, {userinfo['name']}!")
```

### Multiple providers

```python
from kstlib.auth import OIDCProvider, OAuth2Provider, AuthSession

corporate = OIDCProvider.from_config("corporate")
github = OAuth2Provider.from_config("github")

# Use different sessions for different services
with AuthSession(corporate) as corp_session:
    corp_response = corp_session.get("https://api.company.com/data")

with AuthSession(github) as gh_session:
    gh_response = gh_session.get("https://api.github.com/user")
```

## Troubleshooting

### "Not authenticated"

User needs to log in:

```bash
kstlib auth login corporate
```

### Token expired

Tokens should auto-refresh. If not:

```python
token = provider.get_token(auto_refresh=True)  # Force refresh check
# or
provider.refresh_token()  # Explicit refresh
```

### PKCE errors

Ensure PKCE is enabled consistently:

```yaml
auth:
  providers:
    corporate:
      pkce: true  # Must match IdP configuration
```

### Discovery failed

Check issuer URL has `/.well-known/openid-configuration`:

```bash
curl https://sso.company.com/realms/main/.well-known/openid-configuration
```

## Out of Scope

The following protocols are **not supported**:

| Protocol | Reason |
|----------|--------|
| SAML 2.0 | XML-based enterprise legacy protocol |
| Kerberos | Active Directory / on-premise authentication |
| LDAP | Directory-based authentication |
| Basic Auth | Insecure, no token management needed |

## Next Steps

- {doc}`quickstart` - Get authenticated in 5 minutes
- {doc}`configuration` - Configure providers in `kstlib.conf.yml`
- {doc}`providers` - OAuth2 vs OIDC provider details
- {doc}`cli` - Command-line interface reference
- {doc}`token-storage` - Secure token storage with SOPS

## API Reference

Full autodoc: {doc}`../../api/auth`

| Class | Description |
| - | - |
| `OIDCProvider` | OpenID Connect with auto-discovery |
| `OAuth2Provider` | Manual OAuth2 configuration |
| `Token` | Token object with access/refresh/id tokens |
| `AuthSession` | HTTP session (httpx) with auto token injection and refresh |
