# Secrets Workflow

Your daily cheat sheet for managing secrets with kstlib and SOPS.

## TL;DR (3 commands to get started)

```bash
# 1. Quick setup (generates age key + .sops.yaml config)
kstlib secrets init

# 2. Check everything is ready
kstlib secrets doctor

# 3. Encrypt your secrets
kstlib secrets encrypt secrets.yml --out secrets.sops.yml --shred
```

## Setup

### Prerequisites

Install **sops** and **age**. See {doc}`binary-dependencies` for platform-specific instructions.

### Quick setup

```bash
kstlib secrets init          # Global (home directory)
kstlib secrets init --local  # Project-local
```

Or follow the manual steps below for more control.

### Generate your age key (manual)

::::{tab-set}

:::{tab-item} macOS / Linux

```bash
# Create directory
mkdir -p ~/.config/sops/age

# Generate key pair
age-keygen -o ~/.config/sops/age/keys.txt

# Note your public key (starts with "age1...")
age-keygen -y ~/.config/sops/age/keys.txt
# or grep "public key" ~/.config/sops/age/keys.txt
```

:::

:::{tab-item} Windows (PowerShell)

```powershell
# Create directory
New-Item -ItemType Directory -Force -Path "$env:APPDATA\sops\age"

# Generate key pair
age-keygen -o "$env:APPDATA\sops\age\keys.txt"

# IMPORTANT: Tell SOPS where to find the key (add to your PowerShell profile)
$env:SOPS_AGE_KEY_FILE = "$env:APPDATA\sops\age\keys.txt"
# To make permanent: [Environment]::SetEnvironmentVariable("SOPS_AGE_KEY_FILE", "$env:APPDATA\sops\age\keys.txt", "User")

# Note your public key (starts with "age1...")
age-keygen -y "$env:APPDATA\sops\age\keys.txt"
# or Select-String "public key" "$env:APPDATA\sops\age\keys.txt"
```

:::

::::

```{important}
**What matters:**
- **Private key** → Back up securely. Lose it = lose access to your secrets forever.
- **Encrypted `.sops.yml`** → Commit to git. Contains secrets + decryption metadata.
- **Plaintext file** → Destroy after encryption (`--shred`). Reconstructible from encrypted file.
- **`.sops.yaml` config** → Nice to have, but metadata is embedded in encrypted files.

Default key locations:
- **Windows**: `%APPDATA%\sops\age\keys.txt`
- **macOS/Linux**: `~/.config/sops/age/keys.txt`
```

### Configure SOPS

Create a `.sops.yaml` file (project root or global):

| Location | Scope |
| -------- | ----- |
| `.sops.yaml` (project root) | This repo only |
| `~/.sops.yaml` (all platforms) | All projects |

```{note}
On Windows, `~/.sops.yaml` resolves to `C:\Users\<username>\.sops.yaml` (NOT `%APPDATA%`).
```

```yaml
# .sops.yaml
creation_rules:
  # Match any .sops.yml or .sops.yaml file
  - path_regex: .*\.(yml|yaml)$
    encrypted_regex: .*(?:sops|key|password|secret|token|credentials?).*
    age: age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    # Replace with YOUR age public key (from the generate step above)
```

### Verify setup

```bash
kstlib secrets doctor
```

All components should show `available`.

## Daily Usage

### Create a secrets file

Start with a plaintext template:

```yaml
# secrets.yml (destroy after encryption with --shred)
mail:
  smtp:
    host: smtp.gmail.com
    port: 587
    username: alice@example.com
    password: "my-secret-password"

api:
  stripe_key: "sk_live_xxxxx"
  openai_key: "sk-xxxxx"
  webhook_url: "https://..."

database:
  host: localhost
  port: 5432
  credentials:
    username: dbuser
    password: dbpass
```

### Encrypt

```bash
# Encrypt and keep the original
kstlib secrets encrypt secrets.yml --out secrets.sops.yml

# Encrypt and securely delete the original (recommended)
kstlib secrets encrypt secrets.yml --out secrets.sops.yml --shred
```

#### What the encrypted file looks like

```yaml
# secrets.sops.yml (safe to commit)
mail:
    smtp:
        host: smtp.gmail.com
        port: 587
        username: alice@example.com
        password: ENC[AES256_GCM,data:...,type:str]    # ENCRYPTED (matches "password")
api:
    stripe_key: ENC[AES256_GCM,data:...,type:str]      # ENCRYPTED (matches "key")
    openai_key: ENC[AES256_GCM,data:...,type:str]      # ENCRYPTED (matches "key")
    webhook_url: https://...                           # NOT encrypted
database:
    host: localhost
    port: 5432
    credentials:                                       # ⚠️ matches "credentials"
        username: ENC[AES256_GCM,data:...,type:str]   # ENCRYPTED (child of credentials)
        password: ENC[AES256_GCM,data:...,type:str]   # ENCRYPTED (matches "password")
sops:
    age:
        - recipient: age1zsnz8l28tjg9gcxe3rgt5pycvuzwvwnjz55840875v2aagwgsg5s7sgpp9
          enc: |
            -----BEGIN AGE ENCRYPTED FILE-----
            ...
            -----END AGE ENCRYPTED FILE-----
    encrypted_regex: .*(?:sops|key|password|secret|token|credentials?).*
    version: 3.11.0
```

```{warning}
Notice that `database.credentials.username` is encrypted even though "username" doesn't match the regex.
When a **parent key** matches (like `credentials`), **all children** are encrypted too.
To avoid this, restructure your YAML or adjust `encrypted_regex`.
```

```{note}
The `ENC[...]` values change on every re-encryption (random nonces).
This is normal - `git diff` will show changes even if the plaintext didn't change.
```

### Decrypt (view)

```bash
# Print to stdout (safe for quick peek)
kstlib secrets decrypt secrets.sops.yml

# Write to file (careful!)
kstlib secrets decrypt secrets.sops.yml --out secrets.yml
```

### Edit encrypted file

```bash
# Opens in $EDITOR with decrypted content, re-encrypts on save
sops secrets.sops.yml
```

### Use in code

```python
from kstlib import secrets

# Simple: get a secret by dotted path
record = secrets.resolve_secret("mail.smtp.password")
print(record.value)  # "my-secret-password"
print(record.source)  # SecretSource.SOPS

# With fallback
record = secrets.resolve_secret(
    "api.missing_key",
    required=False,
    default="fallback-value",
)
```

### Secure context manager

Minimize how long secrets stay in memory:

```python
from kstlib.secrets import resolve_secret, sensitive

record = resolve_secret("mail.smtp.password")
with sensitive(record) as secret_value:
    send_email(password=secret_value)
# record.value is now None - secret purged from memory
```

## Secret Rotation

### Rotate a secret value

1. Decrypt to plaintext:

   ```bash
   kstlib secrets decrypt secrets.sops.yml --out secrets.yml
   ```

2. Edit `secrets.yml` with new values

3. Re-encrypt and shred:

   ```bash
   kstlib secrets encrypt secrets.yml --out secrets.sops.yml --force --shred
   ```

### Rotate encryption keys

When you need to change the age key (compromised, employee left, etc.):

1. Generate new key:

   ```bash
   age-keygen -o ~/.config/sops/age/keys-new.txt
   ```

2. Update `.sops.yaml` with the new public key

3. Re-encrypt all files:

   ```bash
   # Decrypt with old key, re-encrypt with new
   sops updatekeys secrets.sops.yml
   ```

4. Replace old key file:

   ```bash
   mv ~/.config/sops/age/keys-new.txt ~/.config/sops/age/keys.txt
   ```

## Troubleshooting

### "SOPS binary not found"

```bash
# Check if sops is installed
which sops

# If missing, install it (see Prerequisites above)
```

### "No age key detected"

```bash
# Verify key file exists
ls -la ~/.config/sops/age/keys.txt

# Or set environment variable
export SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt
```

### "Failed to decrypt"

Common causes:

1. **Wrong key**: The file was encrypted with a different age key
2. **Corrupted file**: The .sops.yml file was manually edited incorrectly
3. **Missing .sops.yaml**: SOPS cannot find the configuration

```bash
# Check which keys were used to encrypt
sops --show-metadata secrets.sops.yml
```

### "Permission denied" on key file

```bash
# Key file should be read-only by you (no write needed)
chmod 400 ~/.config/sops/age/keys.txt
```

### Run full diagnostics

```bash
kstlib secrets doctor
```

This checks: sops binary, age-keygen, age key file, keyring backend, and kstlib configuration.

## Quick Reference

| Task | Command |
| ---- | ------- |
| Quick setup | `kstlib secrets init` |
| Local setup | `kstlib secrets init --local` |
| Check setup | `kstlib secrets doctor` |
| Encrypt | `kstlib secrets encrypt FILE --out FILE.sops.yml` |
| Encrypt + delete original | `kstlib secrets encrypt FILE --out FILE.sops.yml --shred` |
| Decrypt to stdout | `kstlib secrets decrypt FILE.sops.yml` |
| Decrypt to file | `kstlib secrets decrypt FILE.sops.yml --out FILE` |
| Edit in place | `sops FILE.sops.yml` |
| Secure delete | `kstlib secrets shred FILE` |

## Files to .gitignore

```text
# .gitignore additions

# Never commit plaintext secrets
secrets.yml
*.secret
*.cleartext

# Keep encrypted versions
!*.sops.yml
!*.sops.yaml
```
