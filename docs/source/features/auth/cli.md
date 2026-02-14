# CLI Reference

The `kstlib auth` command group provides authentication management from the command line.

## Commands Overview

| Command | Description |
| - | - |
| `kstlib auth check` | Validate a JWT token with cryptographic proof |
| `kstlib auth login` | Authenticate with a provider |
| `kstlib auth logout` | Clear stored tokens |
| `kstlib auth status` | Check authentication status |
| `kstlib auth token` | Print access token |
| `kstlib auth whoami` | Show user information |
| `kstlib auth providers` | List configured providers |

## check

Validate a JWT token with cryptographic proof. Performs a full 6-step verification chain
against the issuer's published keys, providing independently verifiable evidence that a token
is valid and spec-compliant. Works with any RSA-signed JWT (id_token or access_token) whose
issuer exposes an OpenID Connect discovery endpoint.

```bash
kstlib auth check [PROVIDER] [OPTIONS]
```

### Why This Exists

Some systems only support RS256 and reject tokens signed with stronger algorithms like RS512.
Instead of reporting their own limitation, they blame the Identity Provider configuration.
`kstlib auth check` provides **irrefutable cryptographic proof** that the token is valid,
shifting the burden of proof where it belongs.

### Cryptographic Proof Chain

The verification follows the exact same process defined by the
[OpenID Connect Discovery](https://openid.net/specs/openid-connect-discovery-1_0.html) specification.
Any third party can reproduce these steps independently and reach the same conclusion.

```
  Identity Provider (IDP)                         kstlib auth check
  ========================                        ====================

  1. IDP signs token                              4. Fetch discovery document
     with PRIVATE key                                GET {issuer}/.well-known/openid-configuration
         │                                                 │
         ▼                                                 ▼
  ┌─────────────┐                                 5. Fetch JWKS (public keys)
  │  JWT Token  │─ ─ ─ given to user ─ ─ ─ ─ ─►     GET {jwks_uri}
  │  header.    │                                          │
  │  payload.   │                                          ▼
  │  signature  │                                 6. Match key by kid,
  └─────────────┘                                    convert JWK to PEM
                                                           │
  2. IDP publishes PUBLIC key                              ▼
     at JWKS endpoint                             7. Verify signature
         │                                           a. DECRYPT(public_key, signature)
  ┌──────▼──────────────────┐                             = recovered_hash
  │ /.well-known/           │                        b. SHA-512(header.payload)
  │   openid-configuration  │                             = computed_hash
  │                         │                        c. recovered == computed? YES
  │ ─► jwks_uri ──────────┐ │                              │
  └───────────────────────┘ │                              ▼
                            │                     8. Validate claims
  ┌─────────────────────────▼                       iss == expected issuer?
  │ /jwks                   │                       aud == expected audience?
  │  { keys: [              │                       exp > now - 5min?
  │    { kid, kty, n, e }   │                       iat < now + 5min?
  │  ]}                     │                              │
  └─────────────────────────┘                              ▼
                                                  ┌───────────────┐
  3. ANYONE can fetch these ◄─ ─ ─ same keys ─ ─  │   VALID or    │
     public keys and verify                       │   INVALID     │
                                                  └───────────────┘
```

**The proof is irrefutable because:**

1. The public key is published by the IDP itself at a well-known URL
2. RSA signature verification is a mathematical operation: either the signature matches the public key or it does not
3. There is no interpretation, no configuration, no ambiguity
4. Any party with network access to the IDP's discovery endpoint can reproduce the exact same verification
5. If `kstlib auth check` says VALID, then `DECRYPT(public_key, signature) == SHA-512(header.payload)`, and no system can legitimately claim otherwise

```{note}
The verification uses the **same public keys** and **same algorithm** that any spec-compliant
system (Keycloak, Azure AD, Okta, Auth0) uses. If the token passes this check, the token is
valid per the JWT (RFC 7519) and OpenID Connect specifications. A system that rejects it has
a limitation, not a reason.
```

### Issuer vs JWKS Server (Delegated Trust)

A common objection is: *"The issuer URL and the JWKS server are different hosts, so the token
is invalid."* This is incorrect. The OIDC Discovery specification
([OpenID Connect Discovery 1.0](https://openid.net/specs/openid-connect-discovery-1_0.html))
explicitly allows the `jwks_uri` to point to any URL. The issuer **declares** which server
hosts its public keys via the discovery document.

```
 Issuer (iss claim)          JWKS Server
 https://auth.corp.com       https://keys.corp.com
         │                            ▲
         │                            │
         ▼                            │
 GET /.well-known/openid-configuration
 {                                    │
   "issuer": "https://auth.corp.com", │
   "jwks_uri": "https://keys.corp.com/jwks"  ◄── explicit delegation
 }

 The issuer DECLARES: "my public keys are at keys.corp.com"
 This is the SAME trust model as SSL/TLS certificate chains.
```

The chain of trust is:

1. The token `iss` claim says `https://auth.corp.com`
2. The discovery document at `https://auth.corp.com/.well-known/openid-configuration` declares `jwks_uri`
3. The JWKS at that URI contains the public key matching the token's `kid`
4. The signature verifies against that public key

Whether the JWKS is hosted on the same server, a CDN, a dedicated key server, or a cloud HSM is
an infrastructure decision. The trust chain is intact because the issuer **explicitly published**
the JWKS location in its own discovery document.

Claiming that "issuer != JWKS host" invalidates a token is like claiming that an SSL certificate
signed by DigiCert is invalid because DigiCert is not the website owner. That is exactly how
delegated trust works.

### Arguments

| Argument | Description |
| - | - |
| `PROVIDER` | Provider name from config (optional, uses default) |

### Options

| Option | Description |
| - | - |
| `--token` | JWT string to validate directly (bypasses cached token) |
| `--verbose`, `-v` | Show full JWT header, payload, PEM key, and step details |
| `--json`, `-j` | Output as JSON for automation |
| `--access-token` | Validate the access token instead of the id_token |

```{tip}
`--token` does not have a `-t` shortcut to avoid conflict with the global `--timeout` option.
```

### Token Source Priority

When no `--token` is provided, `check` reads from the provider's cached tokens:

1. `id_token` (preferred, contains identity claims)
2. `access_token` (fallback if no id_token available)
3. `--access-token` flag forces access token validation

### Exit Codes

| Code | Meaning |
| - | - |
| 0 | Token is cryptographically valid |
| 1 | Token is invalid (bad signature, expired, wrong issuer, etc.) |
| 2 | System error (network failure, missing dependencies, etc.) |

### Examples

```bash
# Validate cached token for default provider
kstlib auth check

# Validate cached token for specific provider
kstlib auth check corporate

# Validate an explicit JWT string
kstlib auth check --token "eyJhbGciOiJSUzUxMiIs..."

# Full verbose output (header, payload, PEM key, discovery doc)
kstlib auth check corporate --verbose

# JSON output for CI/CD pipelines
kstlib auth check corporate --json

# Validate access token instead of id_token
kstlib auth check corporate --access-token

# Script: exit code check
kstlib auth check --token "$TOKEN" --json && echo "VALID" || echo "INVALID"
```

### Output (Normal Mode)

```text
╭────────────────── Token VALID ──────────────────╮
│ Token Type     id_token                         │
│ Algorithm      RS512                            │
│ Key ID (kid)   rsa-signing-key                  │
│ Key Fingerprint SHA256:a1b2c3d4e5f6...          │
│ Issuer         https://sso.company.com/realms/  │
│ Audience       my-app                           │
│ Subject        a1b2c3d4-5678-90ab-cdef          │
│ Expires        58m 30s remaining                │
╰─────────────────────────────────────────────────╯

  ✓ decode_structure: JWT has 3 parts, header and payload decoded
  ✓ discover_issuer: OIDC discovery successful
  ✓ fetch_jwks: JWKS fetched, 2 keys available
  ✓ extract_public_key: Public key extracted (RSA 4096-bit)
  ✓ verify_signature: Signature valid (RS512)
  ✓ validate_claims: All claims valid

╭──────────── Verification Instructions ──────────────╮
│ Third parties can independently verify this token:  │
│ 1. Fetch discovery: GET https://sso.company.com/... │
│ 2. Fetch JWKS: GET https://sso.company.com/jwks     │
│ 3. Verify signature with kid='rsa-signing-key'      │
│ 4. Check claims: iss, aud, exp                      │
╰─────────────────────────────────────────────────────╯
```

### Output (JSON Mode)

```bash
kstlib auth check --token "eyJ..." --json
```

```json
{
  "valid": true,
  "token_type": "id_token",
  "signature_algorithm": "RS512",
  "key_id": "rsa-signing-key",
  "key_fingerprint": "a1b2c3d4e5f6...",
  "discovery_url": "https://sso.company.com/.well-known/openid-configuration",
  "jwks_uri": "https://sso.company.com/jwks",
  "header": {"alg": "RS512", "kid": "rsa-signing-key", "typ": "JWT"},
  "payload": {"iss": "https://sso.company.com/", "sub": "user123", "aud": "my-app", "exp": 1700000000},
  "steps": [
    {"name": "decode_structure", "passed": true, "message": "..."},
    {"name": "verify_signature", "passed": true, "message": "..."}
  ],
  "error": null
}
```

### Use Case: RS512 Algorithm Dispute

Some platforms only support RS256 for JWT signature verification. When a corporate IDP signs
tokens with RS512, these systems report "invalid token signature" instead of acknowledging
their algorithm limitation. Their support teams may also argue that the issuer URL differs
from the JWKS host, which is a valid OIDC configuration (see above).

`kstlib auth check` resolves both arguments with verifiable evidence:

```bash
# 1. Login with corporate IDP (RS512 tokens)
kstlib auth login corporate

# 2. Generate cryptographic proof
kstlib auth check corporate --verbose

# 3. Export proof as JSON for the support ticket
kstlib auth check corporate --json > token-validation-proof.json
```

The verbose output proves:

| Field | Value | What it proves |
| - | - | - |
| Algorithm | RS512 | Token uses RS512, not RS256 |
| Signature | VALID | Mathematically verified against IDP's public key |
| Discovery URL | `https://auth.corp.com/.well-known/...` | Issuer publishes its own key location |
| JWKS URI | `https://keys.corp.com/jwks` | JWKS host declared by the issuer itself |
| Key ID (kid) | Matches token header | The exact key used to sign this token |
| Claims | iss, aud, exp all valid | Token is not expired, correct audience |

**Conclusion:** The token IS valid per the JWT and OpenID Connect specifications. The consuming
system rejects it because it does not implement RS512, not because the token or the IDP
configuration is invalid. The issuer/JWKS host difference is standard delegated trust, not a
misconfiguration.

### Manual Verification (Without kstlib)

The entire verification can be performed manually with standard tools (`curl`, `python`, `openssl`).
This section serves as a step-by-step procedure that any third party can follow independently.

#### Step 1: Decode the JWT

A JWT is three base64url-encoded parts separated by dots: `HEADER.PAYLOAD.SIGNATURE`

```bash
# Given a token (e.g. from browser DevTools, a token endpoint, or kstlib auth token -q)
TOKEN="eyJhbGciOiJSUzUxMiIsImtpZCI6InJzYS1zaWduaW5nLWtleSJ9.eyJpc3MiOi..."

# Decode header (first part)
echo "$TOKEN" | cut -d. -f1 | base64 -d 2>/dev/null | python -m json.tool
```

```json
{
    "alg": "RS512",
    "kid": "rsa-signing-key",
    "typ": "JWT"
}
```

```bash
# Decode payload (second part)
echo "$TOKEN" | cut -d. -f2 | base64 -d 2>/dev/null | python -m json.tool
```

```json
{
    "iss": "https://auth.corp.com/realms/main",
    "sub": "a1b2c3d4-5678-90ab",
    "aud": "my-app",
    "exp": 1700000000
}
```

Key information from the header:
- `alg`: the signing algorithm (RS256, RS512, etc.) - **the server decides this, not the client**
- `kid`: which key was used to sign (Key ID)

#### Step 2: Fetch the issuer's public keys

The issuer (`iss` claim) publishes its keys via the OpenID Connect discovery mechanism.

```bash
# 1. Fetch discovery document
ISSUER="https://auth.corp.com/realms/main"
curl -s "$ISSUER/.well-known/openid-configuration" | python -m json.tool
```

```json
{
    "issuer": "https://auth.corp.com/realms/main",
    "jwks_uri": "https://keys.corp.com/realms/main/protocol/openid-connect/certs",
    "id_token_signing_alg_values_supported": ["RS256", "RS512"]
}
```

```bash
# 2. Fetch JWKS (the actual public keys)
JWKS_URI="https://keys.corp.com/realms/main/protocol/openid-connect/certs"
curl -s "$JWKS_URI" | python -m json.tool
```

```json
{
    "keys": [
        {
            "kid": "rsa-signing-key",
            "kty": "RSA",
            "alg": "RS512",
            "n": "0vx7agoebGc...",
            "e": "AQAB"
        }
    ]
}
```

```{important}
The `jwks_uri` may point to a **different host** than the issuer. This is by design.
The issuer explicitly declares where its keys are hosted via its own discovery document.
This is delegated trust, the same principle as SSL certificate chains.
The client has no authority to reject this delegation.
```

#### Step 3: Match the key and verify the signature

Match the `kid` from the JWT header with the corresponding key in the JWKS, then verify:

```python
# verify_token.py - standalone verification script
import base64, json, hashlib
from cryptography.hazmat.primitives.asymmetric import padding, utils
from cryptography.hazmat.primitives import hashes
from authlib.jose import JsonWebKey

# 1. Split the token
token = "eyJhbGci..."
header_b64, payload_b64, signature_b64 = token.split(".")

# 2. Load the public key from JWKS (fetched in step 2)
jwk_data = {"kid": "rsa-signing-key", "kty": "RSA", "n": "...", "e": "AQAB"}
public_key = JsonWebKey.import_key(jwk_data).get_public_key()

# 3. The signed data is header + "." + payload (as-is, base64url encoded)
signed_data = f"{header_b64}.{payload_b64}".encode("ascii")

# 4. Decode the signature
sig_bytes = base64.urlsafe_b64decode(signature_b64 + "==")

# 5. Verify: the public key "decrypts" the signature to recover the hash,
#    then compares it with SHA-512(signed_data)
header = json.loads(base64.urlsafe_b64decode(header_b64 + "=="))
hash_alg = hashes.SHA512() if header["alg"] == "RS512" else hashes.SHA256()

public_key.verify(
    sig_bytes,
    signed_data,
    padding.PKCS1v15(),
    hash_alg,
)
# If no exception is raised, the signature is VALID.
# This is a mathematical fact, not an opinion.
```

#### What this proves

```
IDP signed:
  1. hash = SHA-512(header.payload)
  2. signature = ENCRYPT(private_key, hash)             --> only the IDP can do this

We verify:
  1. recovered_hash = DECRYPT(public_key, signature)    --> anyone can do this
  2. computed_hash  = SHA-512(header.payload)           --> same algorithm as IDP
  3. recovered_hash == computed_hash ?  --> YES = VALID, the IDP signed this token

Same data, same algorithm, same key pair.
The signature is mathematically valid. There is no interpretation.
```

**If a system rejects this token**, the possible explanations are:

| Symptom | Actual cause |
| - | - |
| "Invalid signature" | The system does not support the algorithm (e.g. RS512) |
| "Unknown issuer" | The system is not configured to trust this issuer |
| "Invalid key" | The system refuses keys from a different host than the issuer |

None of these are token problems. They are **client limitations**.

```{note}
**Who decides the security parameters?**

The Authorization Server (IDP) is the authority. It decides:

- Which algorithms to use for signing (`id_token_signing_alg_values_supported`)
- Where to host its public keys (`jwks_uri`)
- What claims to include in the token

The client (Relying Party) adapts to what the server advertises, not the other way around.
This is the same model as TLS: the server proposes its cipher suites, the client picks one
it supports. A client that only supports TLS 1.0 cannot blame the server for requiring TLS 1.3.
```

---

## login

Authenticate with an OAuth2/OIDC provider.

```bash
kstlib auth login [PROVIDER] [OPTIONS]
```

### Arguments

| Argument | Description |
| - | - |
| `PROVIDER` | Provider name from config (optional, uses default) |

### Options

| Option | Description |
| - | - |
| `--quiet`, `-q` | Minimal output |
| `--timeout` | Callback timeout in seconds (default: 120) |
| `--no-browser` | Print URL instead of opening browser |
| `--manual`, `-m` | Manual mode: no callback server, paste code from redirect URL |
| `--force`, `-f` | Re-authenticate even if already logged in |

### Examples

```bash
# Login with default provider
kstlib auth login

# Login with specific provider
kstlib auth login corporate

# Login without opening browser (for SSH sessions)
kstlib auth login --no-browser

# Manual mode for corporate environments (port 443, smart card, etc.)
kstlib auth login --manual

# Force re-authentication
kstlib auth login --force

# Custom timeout for slow networks
kstlib auth login --timeout 300
```

### What Happens

**Standard mode** (default):

1. Opens your browser to the provider's login page
2. Starts a local callback server (default: `http://127.0.0.1:8400/callback`)
3. Waits for the OAuth redirect with authorization code
4. Exchanges the code for access/refresh tokens
5. Encrypts and stores tokens with SOPS

**Manual mode** (`--manual`):

1. Displays the authorization URL to copy
2. You open the URL in a browser (on any machine)
3. After authentication, the browser redirects to a URL with `?code=...`
4. You paste that URL (or just the code) back into kstlib
5. kstlib exchanges the code for tokens

```{tip}
Use `--manual` when the callback server cannot bind (port 443, corporate firewalls) or when authenticating requires a smart card on a different machine.
```

### Manual Mode Example

```text
$ kstlib auth login --manual corporate

╭─────────────── Manual Login ───────────────╮
│ 1. Copy the URL below and open it          │
│ 2. Complete the authentication             │
│ 3. Copy the redirect URL from your browser │
│ 4. Paste it below                          │
╰────────────────────────────────────────────╯

Authorization URL:
https://sso.corp.com/oauth2/authorize?response_type=code&client_id=...

After authentication, paste the redirect URL or code:
(paste URL or code): https://callback.corp.com?code=abc123&state=xyz

Exchanging authorization code for token...
╭──── OK ────╮
│ Successfully authenticated with corporate. │
╰────────────╯
```

## logout

Clear stored tokens for a provider.

```bash
kstlib auth logout [PROVIDER] [OPTIONS]
```

### Options

| Option | Description |
| - | - |
| `--quiet`, `-q` | Minimal output |

### Examples

```bash
# Logout from default provider
kstlib auth logout

# Logout from specific provider
kstlib auth logout corporate
```

## status

Check authentication status for a provider.

```bash
kstlib auth status [PROVIDER] [OPTIONS]
```

### Options

| Option | Description |
| - | - |
| `--quiet`, `-q` | Single-line output |

### Examples

```bash
# Check default provider status
kstlib auth status

# Check specific provider
kstlib auth status corporate

# Quiet mode for scripts
kstlib auth status -q
```

### Output

```text
╭─────────────────── Auth Status ───────────────────╮
│ Provider     corporate                            │
│ Status       Valid                                │
│ Token Type   bearer                               │
│ Expires At   2026-01-03 15:30:00 UTC              │
│ Expires In   1h 23m                               │
│ Refreshable  Yes                                  │
│ Scopes       openid profile email                 │
╰───────────────────────────────────────────────────╯
```

## token

Print the current access token (for use with other tools).

```bash
kstlib auth token [PROVIDER] [OPTIONS]
```

### Options

| Option | Description |
| - | - |
| `--quiet`, `-q` | Token only, no formatting |

### Examples

```bash
# Print token for default provider
kstlib auth token

# Use with curl
curl -H "Authorization: Bearer $(kstlib auth token -q)" https://api.example.com

# Use with httpie
http https://api.example.com "Authorization: Bearer $(kstlib auth token -q)"
```

```{warning}
The token is printed to stdout. Be careful not to log it or expose it in shell history.
```

## whoami

Show user information from the OIDC userinfo endpoint.

```bash
kstlib auth whoami [PROVIDER] [OPTIONS]
```

### Options

| Option | Description |
| - | - |
| `--quiet`, `-q` | Show name and email only |
| `--raw` | Output raw JSON response |

### Examples

```bash
# Show user info
kstlib auth whoami

# Quiet mode
kstlib auth whoami -q
# Output: John Doe <john@example.com>

# Raw JSON for scripting
kstlib auth whoami --raw
```

### Output

```text
╭────────────── User Info (corporate) ──────────────╮
│ Subject    a1b2c3d4-5678-90ab-cdef-1234567890ab   │
│ Name       John Doe                               │
│ Username   johnd                                  │
│ Email      john.doe@company.com                   │
│ Email Verified  Yes                               │
│ Groups     admin, developers                      │
╰───────────────────────────────────────────────────╯
```

```{note}
`whoami` only works with OIDC providers that expose a userinfo endpoint. OAuth2 providers (like GitHub) don't support this command.
```

## providers

List all configured authentication providers.

```bash
kstlib auth providers [OPTIONS]
```

### Options

| Option | Description |
| - | - |
| `--quiet`, `-q` | Names only, one per line |

### Examples

```bash
# List all providers
kstlib auth providers

# Quiet mode for scripting
kstlib auth providers -q
```

### Output

```text
╭───────────────── Auth Providers ─────────────────╮
│ Name         Type   Issuer                       │
├──────────────────────────────────────────────────┤
│ corporate    oidc   https://sso.company.com      │
│ dev          oidc   http://localhost:8080        │
│ github       oauth2 (manual endpoints)           │
╰──────────────────────────────────────────────────╯

Default provider: corporate
```

## Exit Codes

| Code | Meaning |
| - | - |
| 0 | Success |
| 1 | General error |
| 2 | Authentication required (not logged in) |
| 3 | Configuration error |

## Scripting Examples

### Check if authenticated

```bash
if kstlib auth status -q >/dev/null 2>&1; then
    echo "Authenticated"
else
    echo "Not authenticated"
fi
```

### Auto-login if needed

```bash
kstlib auth status -q || kstlib auth login
```

### Get token for API call

```bash
TOKEN=$(kstlib auth token -q)
curl -H "Authorization: Bearer $TOKEN" https://api.example.com/data
```

### Loop through providers

```bash
for provider in $(kstlib auth providers -q); do
    echo "Status for $provider:"
    kstlib auth status "$provider"
done
```
