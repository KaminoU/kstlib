# Auth Module Examples

Working examples for the kstlib authentication module with local Keycloak.

Demonstrates:

- **OIDC auto-discovery** vs **OIDC hybrid** vs **OAuth2 manual** configuration
- **Include directive** for modular provider configs
- **Token storage** options (SOPS, file, memory)

## Prerequisites

1. Start local Keycloak:

   ```bash
   cd infra
   docker compose up -d keycloak
   ```

2. Wait for Keycloak to be ready (~30s on first start):

   ```bash
   docker compose logs -f keycloak
   # Wait for "Running the server in development mode"
   ```

## Directory Structure

```text
examples/auth/
├── kstlib.conf.yml                  # Main config (includes providers)
├── token_check.py                   # JWT validation with cryptographic proof (Python)
├── token_check.ps1                  # JWT validation with raw RSA math (PowerShell)
├── oauth2_google.py                 # OAuth2 with kstlib.auth (production approach)
├── oauth2_manual_google.py          # Manual OAuth2 flow (httpx only, educational)
├── providers/
│   ├── oidc-keycloak-dev.yml        # OIDC auto-discovery + SOPS
│   ├── oidc-hybrid-keycloak.yml     # OIDC hybrid mode + file
│   └── oauth2-keycloak-dev.yml      # OAuth2 manual + file
├── tokens/                          # SOPS-encrypted token storage
│   └── .sops.yaml                   # SOPS creation rules
└── README.md
```

## Quick Test

```bash
cd examples/auth

# Test OIDC auto-discovery (requires SOPS setup)
kstlib auth login oidc-keycloak-dev
# Browser opens -> login with: testuser / testpass123

# Test OIDC hybrid mode (file storage, no SOPS needed)
kstlib auth login oidc-hybrid-keycloak

# Test OAuth2 manual (file storage)
kstlib auth login oauth2-keycloak-dev

# Check status
kstlib auth status

# Get user info
kstlib auth whoami
```

## Token Validation Example

Demonstrates JWT token validation with cryptographic proof. Three approaches:

| Approach | Method | Use Case |
| -------- | ------ | -------- |
| `python token_check.py` | kstlib `TokenChecker` | Production (one class, one call) |
| `python token_check.py --manual` | httpx + cryptography | Educational (every step explicit) |
| `.\token_check.ps1` | PowerShell + .NET raw RSA | Zero-dependency proof (Windows native) |

```bash
cd examples/auth

# Login first
kstlib auth login oidc-keycloak-dev
# Browser opens -> login with: testuser / testpass123

# Validate with kstlib
python token_check.py

# Validate step-by-step (manual approach)
python token_check.py --manual --verbose

# Validate an explicit JWT
python token_check.py --token "eyJhbGci..." --manual

# CLI shortcut (same validation, Rich output)
kstlib auth check oidc-keycloak-dev --verbose

# PowerShell: raw RSA math, prints both hashes for visual proof
.\token_check.ps1
```

All approaches perform the same core verification:

1. **Decode** JWT structure (header.payload.signature)
2. **Discover** issuer endpoints (`.well-known/openid-configuration`)
3. **Fetch** JWKS (public keys from `jwks_uri`)
4. **Match** key by `kid` (Key ID from JWT header)
5. **Verify** RSA signature: `DECRYPT(public_key, signature) == SHA-256/512(header.payload)`
6. **Validate** claims (issuer, audience, expiration)

The PowerShell example goes one step further: it prints both hashes side by side,
making the mathematical proof visually undeniable.

The result is a mathematical fact, not an opinion. Any third party can reproduce the verification.

## Provider Comparison

| Feature | OIDC Auto | OIDC Hybrid | OAuth2 Manual |
| ------- | --------- | ----------- | ------------- |
| Provider name | `oidc-keycloak-dev` | `oidc-hybrid-keycloak` | `oauth2-keycloak-dev` |
| Discovery mode | Auto | Hybrid | None |
| Configuration | `issuer` only | `issuer` + overrides | All endpoints manual |
| Auto-discovery | Yes | Yes (+ explicit overrides) | No |
| Client Type | Public (PKCE) | Public (PKCE) | Confidential (secret) |
| Token storage | **SOPS** (encrypted) | **file** (plaintext) | **file** (plaintext) |
| ID Token | Yes (JWT verified) | Yes (JWT verified) | No |

## Token Storage Options

| Storage | Persistence | Encryption | Use Case |
| ------- | ----------- | ---------- | -------- |
| `sops` | Yes | Yes (age/gpg/kms) | **Production** |
| `file` | Yes | No (plaintext) | **Development** (no SOPS setup) |
| `memory` | No | N/A | **Tests only** (in-process) |

> **Warning**: `memory` storage does NOT persist across CLI commands!
> Each CLI invocation is a separate process. Use `file` or `sops` for CLI.

## Endpoint Configuration Reference

When configuring endpoints manually, use these keys:

| kstlib Config Key | OIDC Discovery Name | Description |
|-------------------|---------------------|-------------|
| `authorize_url` | `authorization_endpoint` | Authorization endpoint (user login) |
| `token_url` | `token_endpoint` | Token exchange endpoint |
| `userinfo_url` | `userinfo_endpoint` | UserInfo endpoint |
| `revoke_url` | `revocation_endpoint` | Token revocation (RFC 7009) |
| `jwks_uri` | `jwks_uri` | JSON Web Key Set |
| `end_session_endpoint` | `end_session_endpoint` | OIDC browser logout |

> **Note**: Both naming conventions are accepted (`authorize_url` or `authorization_endpoint`).

## OIDC Discovery Modes

### Auto (default)

Provide only `issuer`. All endpoints fetched from `{issuer}/.well-known/openid-configuration`.

```yaml
type: "oidc"
issuer: "http://localhost:8080/realms/kstlib-test"
client_id: "my-app"
```

### Hybrid

Provide `issuer` + explicit endpoint overrides. Discovery runs, but explicit values win.

Use case: IDP with buggy discovery or custom logout endpoint.

```yaml
type: "oidc"
issuer: "http://localhost:8080/realms/kstlib-test"
client_id: "my-app"
end_session_endpoint: "https://custom-logout.example.com/logout"  # Override
```

> **Validation trick**: The `oidc-hybrid-keycloak` example uses a **fake** revoke endpoint.
> Run `kstlib auth logout oidc-hybrid-keycloak --revoke` to test.
> If revoke fails (404), it proves the override mechanism works.
> If revoke succeeds, the override was ignored (bug).

### Manual

No `issuer`. All endpoints must be explicitly configured (like OAuth2).

```yaml
type: "oidc"
authorize_url: "https://..."
token_url: "https://..."
jwks_uri: "https://..."  # Required for JWT validation
client_id: "my-app"
```

## Test Credentials

| Field | Value |
| ----- | ----- |
| Username | `testuser` |
| Password | `testpass123` |
| Email | `testuser@example.com` |

## OIDC Discovery Endpoint

Test the discovery endpoint in your browser:

```text
http://localhost:8080/realms/kstlib-test/.well-known/openid-configuration
```

This JSON contains all endpoints, supported scopes, signing algorithms, etc.

## Google OAuth2 Examples

Two examples demonstrating the same OAuth2 flow with different approaches:

| Example | Lines | Approach | Use Case |
|---------|-------|----------|----------|
| `oauth2_google.py` | ~60 | kstlib.auth | Production |
| `oauth2_manual_google.py` | ~400 | httpx direct | Educational |

**Setup (both examples):**

1. Configure Google OAuth2 credentials in Google Cloud Console
2. Add `http://localhost:8400/callback` to authorized redirect URIs
3. Credentials are in `../mail/mail.conf.sops.yml` (included via config)

### oauth2_google.py (Production)

Uses kstlib.auth abstractions. Clean, concise, with TRACE logging for debugging.

```bash
cd examples/auth

# Normal usage
python oauth2_google.py your-email@gmail.com

# With TRACE logging to see HTTP details
python oauth2_google.py your-email@gmail.com --trace
```

### oauth2_manual_google.py (Educational)

Shows OAuth2 "under the hood" with explicit HTTP calls. No kstlib.auth wrappers.

```bash
cd examples/auth
python oauth2_manual_google.py your-email@gmail.com
```

**What you learn:**

- Exactly what HTTP requests OAuth2 requires
- State parameter for CSRF protection
- Token response structure
- Refresh token mechanism
- SOPS-encrypted token storage

**Both examples:**

1. Check for cached SOPS-encrypted token
2. Refresh if expired (using refresh_token)
3. Full browser flow if no token
4. Save token to SOPS
5. Send test email via Gmail API

## See Also

- [Auth Module Documentation](../../docs/source/features/auth/index.md)
- [Token Storage Guide](../../docs/source/features/auth/token-storage.md)
- [Keycloak Infrastructure](../../docs/source/development/infra/keycloak.md)
- [Config Includes Example](../config/02_includes.py)
