# CLI Reference

The `kstlib auth` command group provides authentication management from the command line.

## Commands Overview

| Command | Description |
| - | - |
| `kstlib auth login` | Authenticate with a provider |
| `kstlib auth logout` | Clear stored tokens |
| `kstlib auth status` | Check authentication status |
| `kstlib auth token` | Print access token |
| `kstlib auth whoami` | Show user information |
| `kstlib auth providers` | List configured providers |

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
