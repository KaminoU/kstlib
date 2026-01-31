# Providers

kstlib resolves secrets through a cascade of providers. Each provider is checked in order until a value is found.

```text
kwargs → env → keyring → SOPS → default
```

## Overview

::::{tab-set}

:::{tab-item} kwargs
**Source:** Direct injection via `secrets` parameter

**Security:** Plaintext in memory (caller-controlled)

**Use case:** Testing, temporary overrides

```python
record = resolve_secret(
    "api.key",
    secrets={"api.key": "test-value"},
)
# record.value == "test-value"
# record.source == SecretSource.KWARGS
```

```{tip}
Kwargs take precedence over all other providers. Use this for unit tests
or temporary overrides without modifying environment or config.
```

:::

:::{tab-item} env

**Source:** Environment variables

**Security:** Plaintext in process memory (visible via `env`, `/proc`)

**Use case:** CI/CD, containers, runtime injection

```python
import os

os.environ["KSTLIB__API__KEY"] = "sk-xxx"

record = resolve_secret("api.key")
# record.value == "sk-xxx"
# record.source == SecretSource.ENVIRONMENT
```

```{note}
Format: `KSTLIB__<NAME>` with `__` as separator and uppercase.
`api.key` -> `KSTLIB__API__KEY`
```

:::

:::{tab-item} keyring

**Source:** System keychain (macOS Keychain, Windows Credential Manager, Linux Secret Service)

**Security:** Encrypted by OS (AES-256, DPAPI)

**Use case:** Desktop apps, persistent local secrets

```python
import keyring

# Store once
keyring.set_password("kstlib", "api.key", "sk-xxx")

# kstlib finds it automatically
record = resolve_secret("api.key")
# record.value == "sk-xxx"
# record.source == SecretSource.KEYRING
```

:::

:::{tab-item} sops

**Source:** SOPS-encrypted files (`.sops.yml`)

**Security:** Encrypted at rest (age/GPG/KMS), safe to commit to git

**Use case:** Git-tracked secrets, team sharing

```yaml
# secrets.sops.yml
api:
  key: ENC[AES256_GCM,data:...,type:str]
```

```python
record = resolve_secret("api.key")
# record.value == "sk-xxx" (decrypted)
# record.source == SecretSource.SOPS
```

```{tip}
Use `kstlib secrets init` to set up SOPS quickly.
```

:::

:::{tab-item} default

**Source:** Fallback value passed to `resolve_secret()`

**Security:** Plaintext in code (never use for real secrets)

**Use case:** Development defaults, optional secrets

```python
record = resolve_secret(
    "api.key",
    required=False,
    default="dev-key-for-testing",
)
# record.value == "dev-key-for-testing"
# record.source == SecretSource.DEFAULT
```

```{warning}
Only used when no provider returns a value AND `required=False`.
```

:::

::::

## Kwargs (Direct Injection)

Pass secrets directly to `resolve_secret()` for testing or temporary overrides:

```python
from kstlib.secrets import resolve_secret, SecretSource

record = resolve_secret(
    "api.key",
    secrets={"api.key": "test-value"},
)
# record.value == "test-value"
# record.source == SecretSource.KWARGS
```

### Nested keys

Use dot notation in the secrets dict:

```python
record = resolve_secret(
    "database.credentials.password",
    secrets={"database.credentials.password": "secret123"},
)
```

### Multiple secrets

```python
test_secrets = {
    "api.key": "test-key",
    "database.password": "test-pass",
    "smtp.credentials": "test-creds",
}

api_key = resolve_secret("api.key", secrets=test_secrets)
db_pass = resolve_secret("database.password", secrets=test_secrets)
```

## Environment Variables

Maps dotted paths to uppercase env vars with configurable prefix:

```python
# "mail.smtp.password" looks for (in order):
#   KSTLIB__MAIL__SMTP__PASSWORD (with prefix)
#   MAIL_SMTP_PASSWORD (without prefix)

import os
os.environ["KSTLIB__MAIL__SMTP__PASSWORD"] = "secret"

record = resolve_secret("mail.smtp.password")
# record.source == SecretSource.ENVIRONMENT
```

### Naming convention

| Secret path | Environment variable |
| - | - |
| `api.key` | `KSTLIB__API__KEY` |
| `database.password` | `KSTLIB__DATABASE__PASSWORD` |
| `smtp.auth.token` | `KSTLIB__SMTP__AUTH__TOKEN` |

### Custom prefix

Configure in `kstlib.conf.yml` under providers settings:

```yaml
secrets:
  providers:
    - name: environment
      settings:
        prefix: "MYAPP"      # MYAPP__API__KEY instead of KSTLIB__API__KEY
        delimiter: "__"       # Separator between path segments
```

## Keyring

Uses the system's secure credential storage:

```python
import keyring

# Store a secret (one-time setup)
keyring.set_password("kstlib", "api.stripe_key", "sk_live_xxx")

# kstlib will find it automatically
record = resolve_secret("api.stripe_key")
# record.source == SecretSource.KEYRING
```

### Platform backends

| Platform | Backend | Storage |
| - | - | - |
| Linux | Secret Service | GNOME Keyring / KWallet |
| macOS | Keychain | `~/Library/Keychains/` |
| Windows | Credential Manager | Windows Credential Store |

### Service name

Configure the keyring service name in `kstlib.conf.yml`:

```yaml
secrets:
  providers:
    - name: keyring
      settings:
        service: "myapp"  # default: kstlib
```

### Managing secrets manually

::::{tab-set}

:::{tab-item} Linux

```bash
# Write a secret (GNOME Keyring / Secret Service)
secret-tool store --label="kstlib api.key" service kstlib username api.key

# Read a secret
secret-tool lookup service kstlib username api.key

# Delete a secret
secret-tool clear service kstlib username api.key
```

:::

:::{tab-item} macOS

```bash
# Write a secret
security add-generic-password -s kstlib -a api.key -w "sk-xxx"

# Read a secret
security find-generic-password -s kstlib -a api.key -w

# Delete a secret
security delete-generic-password -s kstlib -a api.key
```

:::

:::{tab-item} Windows (PowerShell)

**Setup** (one-time):

```powershell
# Install SecretManagement + CredMan extension (uses Windows Credential Manager)
Install-Module Microsoft.PowerShell.SecretManagement -Scope CurrentUser
Install-Module SecretManagement.JustinGrote.CredMan -Scope CurrentUser

# Register the vault
Register-SecretVault -Name 'CredMan' -ModuleName 'SecretManagement.JustinGrote.CredMan'
```

**Usage**:

```powershell
# Write a secret
Set-Secret -Name 'kstlib:api.key' -Secret 'sk-xxx' -Vault CredMan

# Read a secret
Get-Secret -Name 'kstlib:api.key' -Vault CredMan -AsPlainText

# List secrets
Get-SecretInfo -Vault CredMan | Where-Object Name -like 'kstlib:*'

# Delete a secret
Remove-Secret -Name 'kstlib:api.key' -Vault CredMan
```

```{note}
The `CredMan` vault uses Windows Credential Manager, the same backend as Python's `keyring`.
Secrets are interoperable between PowerShell and Python.
```

:::

::::

```{tip}
For programmatic access, use Python's `keyring` library directly:
`python
import keyring
keyring.set_password("kstlib", "api.key", "sk-xxx")  # Write
keyring.get_password("kstlib", "api.key")            # Read
`
```

## SOPS

Decrypts on-demand with intelligent caching:

- **LRU cache**: Decrypted documents cached (default: 16 entries)
- **Mtime tracking**: Cache invalidates when file changes
- **Format auto-detection**: JSON, YAML, or raw text

### Configuration

```yaml
secrets:
  sops:
    path: secrets.sops.yml    # default file to search
    binary: sops              # or full path: /usr/local/bin/sops
    cache_size: 16            # LRU cache entries
```

### Multiple SOPS files

```python
# Use a specific file
record = resolve_secret("api.key", sops_path="production.sops.yml")
```

### What gets encrypted

SOPS uses `encrypted_regex` to determine which keys to encrypt:

```yaml
# .sops.yaml
creation_rules:
  - path_regex: .*\.sops\.(yml|yaml)$
    encrypted_regex: .*(?:key|password|secret|token|credentials?).*
    age: age1xxx...
```

```{warning}
When a **parent key** matches the regex (like `credentials`), **all children** are encrypted too.
```

For detailed SOPS setup, see {doc}`sops`.

## Provider Priority

You can customize the provider order:

```python
from kstlib.secrets import resolve_secret

# Skip kwargs, check env first
record = resolve_secret("api.key", skip_providers=["kwargs"])

# Only check specific providers
record = resolve_secret("api.key", providers=["env", "sops"])
```

## Lazy Loading

Providers are lazily loaded to minimize startup time. The `keyring` provider (83ms import time) is only loaded when first accessed.

See {doc}`../../development/performance` for details.
