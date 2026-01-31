# Keycloak (OIDC/OAuth2)

[Keycloak](https://www.keycloak.org/) is an open-source identity provider for testing the auth module without external IdP accounts.

## Features

- **OIDC/OAuth2 compliant**: Full OpenID Connect implementation
- **Pre-configured realm**: Test users and clients ready to use
- **PKCE support**: Public client with S256 code challenge
- **Offline access**: Refresh token testing

## Quick Start

```bash
cd infra

# Start Keycloak only
docker compose up -d keycloak

# Wait for health check (about 30s on first start)
docker compose logs -f keycloak
```

Keycloak is ready when you see `Running the server in development mode`.

## Pre-configured Resources

The realm (`keycloak/realm-export.json`) is auto-imported on startup:

### Test Realm

| Setting | Value |
| - | - |
| Realm | `kstlib-test` |
| Display Name | KSTLib Test Realm |
| SSL Required | None (dev mode) |

### Test User

| Field | Value |
| - | - |
| Username | `testuser` |
| Password | `testpass123` |
| Email | `testuser@example.com` |
| Name | Test User |

### Clients

#### Public Client (PKCE)

For CLI/desktop apps using Authorization Code + PKCE flow:

| Setting | Value |
| - | - |
| Client ID | `kstlib-test-public` |
| Client Secret | None (public client) |
| PKCE Method | S256 |
| Redirect URIs | `http://127.0.0.1:8400/*`, `http://localhost:8400/*` |
| Scopes | openid, profile, email, offline_access |

#### Confidential Client

For server-to-server or testing client_secret flows:

| Setting | Value |
| - | - |
| Client ID | `kstlib-test-confidential` |
| Client Secret | `kstlib-test-secret` |
| Grant Types | Authorization Code, Client Credentials, Direct Access |
| Redirect URIs | `http://127.0.0.1:8400/*`, `http://localhost:8400/*` |
| Scopes | openid, profile, email, offline_access |

## Usage

### kstlib Configuration

Add a test provider to your config:

```yaml
# config.yml
auth:
  providers:
    keycloak-test:
      type: oidc
      discovery_url: http://localhost:8080/realms/kstlib-test/.well-known/openid-configuration
      client_id: kstlib-test-public
      # No client_secret for public clients
      scopes:
        - openid
        - profile
        - email
        - offline_access

  callback_server:
    port: 8400
```

### CLI Login

```bash
# Start Keycloak if not running
cd infra && docker compose up -d keycloak

# Login with kstlib CLI
kstlib auth login keycloak-test

# Check status
kstlib auth status keycloak-test

# Get user info
kstlib auth whoami keycloak-test
```

### Python Integration

```python
from kstlib.auth import OIDCProvider

provider = OIDCProvider(
    name="keycloak-test",
    discovery_url="http://localhost:8080/realms/kstlib-test/.well-known/openid-configuration",
    client_id="kstlib-test-public",
    scopes=["openid", "profile", "email"],
)

# Get authorization URL for browser
auth_url, state, code_verifier = provider.get_authorization_url_with_pkce()

# After callback with authorization code
token = provider.exchange_code(code, state, code_verifier)

# Get user info
userinfo = provider.get_userinfo()
print(f"Logged in as: {userinfo['name']}")
```

## OIDC vs OAuth2

**OIDC** (OpenID Connect) is OAuth2 + identity layer. The key difference:

- **OIDC**: Just provide `issuer` URL, all endpoints auto-discovered via `/.well-known/openid-configuration`
- **OAuth2**: Must configure each endpoint manually (`authorize_url`, `token_url`, etc.)

```{tip}
Test the discovery endpoint in your browser:
<http://localhost:8080/realms/kstlib-test/.well-known/openid-configuration>

This JSON contains all endpoints, supported scopes, signing algorithms, etc.
```

## Endpoints Reference

All endpoints are under the realm URL `http://localhost:8080/realms/kstlib-test`:

| Endpoint | Path | Description |
| - | - | - |
| Discovery | `/.well-known/openid-configuration` | OIDC auto-discovery (all config in JSON) |
| Authorization | `/protocol/openid-connect/auth` | User login page |
| Token | `/protocol/openid-connect/token` | Exchange code for tokens |
| UserInfo | `/protocol/openid-connect/userinfo` | Get user profile (requires access_token) |
| End Session | `/protocol/openid-connect/logout` | Logout endpoint |
| JWKS | `/protocol/openid-connect/certs` | Public keys for JWT verification |

## Admin Console

Access the Keycloak admin console:

- **URL**: <http://localhost:8080/admin>
- **Username**: `admin`
- **Password**: `admin`

From here you can:

- Create additional users
- Configure new clients
- Modify realm settings
- View active sessions

## Configuration

Environment variables in `.env`:

| Variable | Default | Description |
| - | - | - |
| `KEYCLOAK_PORT` | 8080 | HTTP port |

## CI/CD Integration

### GitHub Actions

```yaml
services:
  keycloak:
    image: quay.io/keycloak/keycloak:24.0
    ports:
      - 8080:8080
    env:
      KEYCLOAK_ADMIN: admin
      KEYCLOAK_ADMIN_PASSWORD: admin
    options: >-
      --health-cmd "exec 3<>/dev/tcp/localhost/8080"
      --health-interval 10s
      --health-timeout 5s
      --health-retries 10

steps:
  - name: Wait for Keycloak
    run: |
      timeout 60 bash -c 'until curl -sf http://localhost:8080/health/ready; do sleep 2; done'
```

### pytest Fixture

```python
import pytest
from kstlib.auth import OIDCProvider

@pytest.fixture
def keycloak_provider():
    """OIDC provider configured for local Keycloak."""
    return OIDCProvider(
        name="keycloak-test",
        discovery_url="http://localhost:8080/realms/kstlib-test/.well-known/openid-configuration",
        client_id="kstlib-test-public",
        scopes=["openid", "profile", "email"],
    )

@pytest.fixture
def keycloak_token(keycloak_provider):
    """Get a token using direct access grant (test only)."""
    # Note: Direct access only works with confidential client
    import httpx

    response = httpx.post(
        "http://localhost:8080/realms/kstlib-test/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "kstlib-test-confidential",
            "client_secret": "kstlib-test-secret",
            "username": "testuser",
            "password": "testpass123",
            "scope": "openid profile email",
        },
    )
    response.raise_for_status()
    return response.json()["access_token"]
```

## Troubleshooting

### Container won't start

```bash
# Check logs
docker compose logs keycloak

# Verify port is available
netstat -an | findstr 8080  # Windows
lsof -i :8080               # Linux/Mac
```

### Realm not imported

The realm is imported from `keycloak/realm-export.json` on first start. If the realm is missing:

```bash
# Full reset (deletes all data)
docker compose down -v
docker compose up -d keycloak
```

### Token exchange fails

1. Verify redirect URI matches exactly (including trailing slashes)
2. Check PKCE code_verifier is being sent for public clients
3. Ensure client_secret is provided for confidential clients

### CORS errors

The test realm is configured for `http://127.0.0.1:8400` and `http://localhost:8400`. If using a different port, update the client's Web Origins in the admin console.

## See Also

- {doc}`/features/auth/index` - Auth module documentation
- {doc}`/features/auth/quickstart` - Getting started with auth
- {doc}`/features/auth/providers` - Provider configuration
- [Keycloak Documentation](https://www.keycloak.org/documentation)
- [OpenID Connect Spec](https://openid.net/specs/openid-connect-core-1_0.html)
