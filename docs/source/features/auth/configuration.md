# Configuration

The auth module is configured via the `auth:` section in `kstlib.conf.yml`.

## Full Configuration Reference

```yaml
auth:
  # Default provider used when none is specified
  default_provider: "corporate"

  # Token storage backend: "memory", "file", or "sops"
  # memory = in-process only (lost on exit)
  # file = plain JSON on disk (dev/testing only)
  # sops = encrypted on disk (persistent, secure)
  token_storage: "sops"

  # OIDC discovery cache TTL (seconds)
  # How long to cache .well-known/openid-configuration
  discovery_ttl: 3600

  # OAuth callback server settings
  callback_server:
    host: "127.0.0.1"    # Bind address (localhost only for security)
    port: 8400           # Port for OAuth redirect
    timeout: 120         # Max seconds to wait for callback

  # Storage backend configuration
  storage:
    file:
      # Directory for plaintext token files (dev only!)
      # Each provider gets: {directory}/{provider_name}.token.json
      directory: "~/.config/kstlib/auth/tokens"

    sops:
      # Directory for encrypted token files
      # Each provider gets: {directory}/{provider_name}.sops.json
      directory: "~/.config/kstlib/auth/tokens"

  # Provider definitions
  providers:
    my-provider:
      # ... see Provider Configuration below
```

## Provider Configuration

### OIDC Provider (Recommended)

```yaml
providers:
  corporate:
    type: "oidc"                    # or "openid", "openidconnect"
    issuer: "https://sso.company.com/realms/main"
    client_id: "my-app"
    client_secret: "optional-secret"  # Can use sops:// URI
    scopes: ["openid", "profile", "email"]
    pkce: true                      # Default: true (RFC 7636)
    token_storage: "sops"           # Provider-specific storage
    discovery_ttl: 3600             # Override global TTL
```

| Field | Required | Description |
|-------|----------|-------------|
| `type` | Yes | `"oidc"`, `"openid"`, or `"openidconnect"` |
| `issuer` | Yes | OIDC issuer URL (discovery endpoint base) |
| `client_id` | Yes | OAuth client identifier |
| `client_secret` | No | Client secret (for confidential clients) |
| `scopes` | No | OAuth scopes to request (default: `["openid", "profile", "email"]`) |
| `pkce` | No | Enable PKCE (default: `true`, RFC 7636) |
| `token_storage` | No | Provider-specific storage: `memory`, `file`, or `sops` |
| `discovery_ttl` | No | Per-provider discovery cache TTL |

### OAuth2 Provider (Manual Endpoints)

For providers that don't support OIDC discovery:

```yaml
providers:
  github:
    type: "oauth2"                  # or "oauth"
    authorize_url: "https://github.com/login/oauth/authorize"
    token_url: "https://github.com/login/oauth/access_token"
    client_id: "your-github-client-id"
    client_secret: "sops://secrets/auth.yaml#github.client_secret"
    scopes: ["read:user", "user:email"]
    redirect_uri: "http://127.0.0.1:8400/callback"
    token_storage: "file"           # Provider-specific storage
```

| Field | Required | Description |
|-------|----------|-------------|
| `type` | Yes | `"oauth2"` or `"oauth"` |
| `authorize_url` | Yes | Authorization endpoint |
| `token_url` | Yes | Token exchange endpoint |
| `client_id` | Yes | OAuth client identifier |
| `client_secret` | No | Client secret |
| `scopes` | No | OAuth scopes to request |
| `redirect_uri` | No | Override callback URL |
| `pkce` | No | Enable PKCE if supported (default: `true`) |
| `token_storage` | No | Provider-specific storage: `memory`, `file`, or `sops` |

## Endpoint Configuration Reference

When configuring endpoints manually (OAuth2 or OIDC hybrid mode), use these keys:

| kstlib Config Key | OIDC Discovery Name | Also Accepts | Description |
|-------------------|---------------------|--------------|-------------|
| `authorize_url` | `authorization_endpoint` | Both | Authorization endpoint (user login) |
| `token_url` | `token_endpoint` | Both | Token exchange endpoint |
| `userinfo_url` | `userinfo_endpoint` | Both | UserInfo endpoint (get user claims) |
| `revoke_url` | `revocation_endpoint` | Both | Token revocation endpoint (RFC 7009) |
| `jwks_uri` | `jwks_uri` | - | JSON Web Key Set for JWT validation |
| `end_session_endpoint` | `end_session_endpoint` | - | OIDC logout endpoint (browser redirect) |

```{note}
Both naming conventions are accepted. Use `authorize_url` (short) or `authorization_endpoint` (OIDC standard) - they are equivalent.
```

**Example - Full manual configuration:**

```yaml
providers:
  exotic-idp:
    type: "oidc"
    client_id: "my-app"
    # All endpoints explicit (no discovery)
    authorize_url: "https://idp.example.com/oauth/authorize"
    token_url: "https://idp.example.com/oauth/token"
    userinfo_url: "https://idp.example.com/oauth/userinfo"
    revoke_url: "https://idp.example.com/oauth/revoke"
    jwks_uri: "https://idp.example.com/.well-known/jwks.json"
    end_session_endpoint: "https://idp.example.com/oauth/logout"
    scopes: ["openid", "profile", "email"]
    pkce: true
```

## SSL/TLS Configuration

For corporate environments with internal PKI or self-signed certificates:

```yaml
providers:
  corporate:
    type: "oidc"
    issuer: "https://sso.corp.internal"
    client_id: "my-app"

    # Option 1: Use custom CA bundle (recommended)
    ssl_ca_bundle: "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem"

    # Option 2: Disable verification (development only!)
    # ssl_verify: false
```

| Field | Default | Description |
|-------|---------|-------------|
| `ssl_verify` | `true` | Enable SSL certificate verification |
| `ssl_ca_bundle` | `null` | Path to custom CA bundle file (PEM format) |

```{warning}
Setting `ssl_verify: false` disables all certificate validation.
This exposes you to man-in-the-middle attacks.
Use only for local development with self-signed certificates.
```

```{note}
If both `ssl_ca_bundle` and `ssl_verify: false` are set, the CA bundle takes precedence.
This is intentional: specifying a CA bundle implies you want verification with that bundle.
```

```{tip}
**Finding your CA bundle:**

**Linux (RHEL/CentOS):**
```bash
/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem
```

**Linux (Debian/Ubuntu):**
```bash
/etc/ssl/certs/ca-certificates.crt
```

**macOS:**
```bash
/etc/ssl/cert.pem
# Or export from Keychain
```

**Windows:**
```
# Export from certmgr.msc or use:
certutil -generateSSTFromWU roots.sst
```

**Environment variable alternative:**
```bash
export SSL_CERT_FILE=/path/to/ca-bundle.pem
kstlib auth login
```
```

## Secrets in Configuration

Client secrets can be stored securely using SOPS URIs:

```yaml
providers:
  corporate:
    type: "oidc"
    issuer: "https://sso.company.com"
    client_id: "my-app"
    # Secret resolved from SOPS-encrypted file
    client_secret: "sops://secrets/auth.yaml#corporate.client_secret"
```

The URI format is:
```
sops://path/to/file.yaml#key.path
```

See {doc}`/features/secrets/index` for SOPS configuration.

## Environment Variable Overrides

Configuration values can be overridden via environment variables:

```bash
# Override default provider
export KSTLIB__AUTH__DEFAULT_PROVIDER="dev-provider"

# Override callback port
export KSTLIB__AUTH__CALLBACK_SERVER__PORT="9000"
```

Pattern: `KSTLIB__SECTION__KEY` (double underscore as separator).

## Callback Server

The callback server listens for OAuth redirects during the authorization flow.

```yaml
callback_server:
  host: "127.0.0.1"    # MUST be localhost for security
  port: 8400           # Default port
  timeout: 120         # Login timeout in seconds
```

```{warning}
The callback server should **always** bind to `127.0.0.1` (localhost). Binding to `0.0.0.0` exposes the callback to the network, which is a security risk.
```

### Configuring Your Provider

Register the redirect URI with your identity provider:

```
http://127.0.0.1:8400/callback
```

Or if using a custom port:
```
http://127.0.0.1:{port}/callback
```

## Multiple Providers

You can configure multiple providers and switch between them:

```yaml
providers:
  dev:
    type: "oidc"
    issuer: "http://localhost:8080/realms/dev"
    client_id: "dev-client"
    pkce: true

  staging:
    type: "oidc"
    issuer: "https://staging-sso.company.com/realms/main"
    client_id: "staging-client"
    client_secret: "sops://secrets/auth.yaml#staging.secret"
    pkce: true

  production:
    type: "oidc"
    issuer: "https://sso.company.com/realms/main"
    client_id: "prod-client"
    client_secret: "sops://secrets/auth.yaml#production.secret"
    pkce: true
```

```bash
# Login to specific provider
kstlib auth login dev
kstlib auth login production

# List configured providers
kstlib auth providers
```

## Programmatic Configuration

You can also configure providers programmatically:

```python
from kstlib.auth import OIDCProvider, AuthProviderConfig
from kstlib.auth.token import MemoryTokenStorage

config = AuthProviderConfig(
    issuer="https://sso.company.com/realms/main",
    client_id="my-app",
    scopes=["openid", "profile", "email"],
    pkce=True,
)

provider = OIDCProvider(
    name="corporate",
    config=config,
    token_storage=MemoryTokenStorage(),
)
```

See {doc}`providers` for API details.
