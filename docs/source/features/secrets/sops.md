# SOPS Setup

Advanced SOPS configuration for teams, custom key management, and troubleshooting.

## Auto-Decrypt in Config Loader

The kstlib config loader automatically decrypts SOPS files when included in your configuration.
Files with `.sops.yml`, `.sops.yaml`, `.sops.json`, or `.sops.toml` extensions are detected and
decrypted transparently.

### Basic Usage

```yaml
# kstlib.conf.yml
app: myapp
include: secrets.sops.yml  # Automatically decrypted!
```

```yaml
# secrets.sops.yml (encrypted with SOPS)
api_key: ENC[AES256_GCM,data:abc123...]
db:
  password: ENC[AES256_GCM,data:xyz789...]
```

When you load the config, secrets are decrypted on the fly:

```python
from kstlib.config import load_config

config = load_config()
print(config.api_key)      # "real_api_key_value" (decrypted)
print(config.db.password)  # "super_secret_password" (decrypted)
```

### Detection Methods

The loader uses two detection methods:

1. **By extension**: Files ending with `.sops.yml`, `.sops.yaml`, `.sops.json`, `.sops.toml`
2. **Warning on ENC values**: If a non-SOPS file contains `ENC[AES256_GCM,...]` values,
   a warning is logged suggesting to use a `.sops.*` extension

### Graceful Degradation

The loader degrades gracefully when SOPS is unavailable:

| Scenario | Behavior |
|----------|----------|
| SOPS not installed | Warning logged, file loaded as-is |
| Decryption fails | Warning logged, file loaded as-is |
| `sops_decrypt=False` | SOPS skipped entirely |

```python
# Disable SOPS decryption explicitly
config = load_config(sops_decrypt=False)
```

### Programmatic Access

For advanced use cases, the SOPS module is exposed directly:

```python
from kstlib.config import (
    is_sops_file,
    get_real_extension,
    has_encrypted_values,
    SopsDecryptor,
)
from pathlib import Path

# Check if a file is a SOPS file
is_sops_file(Path("secrets.sops.yml"))  # True

# Get real format extension
get_real_extension(Path("secrets.sops.yml"))  # ".yml"

# Find encrypted values in data
data = {"api_key": "ENC[AES256_GCM,data:xxx]", "host": "localhost"}
has_encrypted_values(data)  # ["api_key"]

# Direct decryption
decryptor = SopsDecryptor()
content = decryptor.decrypt_file(Path("secrets.sops.yml"))
```

### Cache Behavior

Decrypted content is cached using an LRU cache with mtime-based invalidation:

- Cache size: 64 entries by default (configurable via `secrets.sops.max_cache_entries`)
- Hard limit: 256 entries maximum
- Invalidation: Automatic when file mtime changes

```yaml
# kstlib.conf.yml - customize cache size
secrets:
  sops:
    max_cache_entries: 128
```

## Manual Setup

If you need more control (custom paths, KMS, GPG), follow these steps instead of `kstlib secrets init`.

### Generate your age key

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

# IMPORTANT: Tell SOPS where to find the key
$env:SOPS_AGE_KEY_FILE = "$env:APPDATA\sops\age\keys.txt"
# To make permanent:
# [Environment]::SetEnvironmentVariable("SOPS_AGE_KEY_FILE", "$env:APPDATA\sops\age\keys.txt", "User")

# Note your public key (starts with "age1...")
age-keygen -y "$env:APPDATA\sops\age\keys.txt"
# or Select-String "public key" "$env:APPDATA\sops\age\keys.txt"
```

:::

::::

```{important}
**What matters:**
- **Private key** -> Back up securely. Lose it = lose access to your secrets forever.
- **Encrypted `.sops.yml`** -> Commit to git. Contains secrets + decryption metadata.
- **Plaintext file** -> Destroy after encryption (`--shred`). Reconstructible from encrypted file.
- **`.sops.yaml` config** -> Nice to have, but metadata is embedded in encrypted files.
```

### Configure SOPS

Create a `.sops.yaml` file in your project root:

```yaml
creation_rules:
  - path_regex: .*\.(yml|yaml)$
    encrypted_regex: .*(?:sops|key|password|secret|token|credentials?).*
    age: age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    # Replace with YOUR age public key
```

## Encryption Rules

### encrypted_regex

Controls which keys get encrypted:

```yaml
# Default pattern (recommended)
encrypted_regex: .*(?:key|password|secret|token|credentials?).*
```

This encrypts any key containing:

- `key` (api_key, stripe_key)
- `password` (db_password)
- `secret` (client_secret)
- `token` (auth_token)
- `credential` or `credentials`

### What the encrypted file looks like

```yaml
mail:
    smtp:
        host: smtp.gmail.com              # NOT encrypted
        port: 587                          # NOT encrypted
        username: alice@example.com        # NOT encrypted
        password: ENC[AES256_GCM,...]      # ENCRYPTED (matches "password")
api:
    stripe_key: ENC[AES256_GCM,...]        # ENCRYPTED (matches "key")
    webhook_url: https://...               # NOT encrypted
database:
    credentials:                           # matches "credentials"
        username: ENC[AES256_GCM,...]     # ENCRYPTED (child of matching parent)
        password: ENC[AES256_GCM,...]     # ENCRYPTED
```

```{warning}
When a **parent key** matches the regex (like `credentials`), **all children** are encrypted too.
Notice `database.credentials.username` is encrypted even though "username" alone doesn't match.
```

```{note}
The `ENC[...]` values change on every re-encryption (random nonces).
This is normal - `git diff` will show changes even if plaintext didn't change.
```

## Secret Rotation

### Rotate a secret value

1. Decrypt: `kstlib secrets decrypt secrets.sops.yml --out secrets.yml`
2. Edit `secrets.yml` with new values
3. Re-encrypt: `kstlib secrets encrypt secrets.yml --out secrets.sops.yml --force --shred`

### Rotate encryption keys

::::{tab-set}

:::{tab-item} macOS / Linux

```bash
# 1. Generate new key
age-keygen -o ~/.config/sops/age/keys-new.txt

# 2. Update .sops.yaml with the new public key (from output above)

# 3. Re-encrypt all files
sops updatekeys secrets.sops.yml

# 4. Replace old key file
mv ~/.config/sops/age/keys-new.txt ~/.config/sops/age/keys.txt
```

:::

:::{tab-item} Windows (PowerShell)

```powershell
# 1. Generate new key
age-keygen -o "$env:APPDATA\sops\age\keys-new.txt"

# 2. Update .sops.yaml with the new public key (from output above)

# 3. Re-encrypt all files
sops updatekeys secrets.sops.yml

# 4. Replace old key file
Move-Item "$env:APPDATA\sops\age\keys-new.txt" "$env:APPDATA\sops\age\keys.txt" -Force
```

:::

::::

### Adding team members

Add multiple age recipients to `.sops.yaml`:

```yaml
creation_rules:
  - path_regex: .*\.sops\.(yml|yaml)$
    age: >-
      age1alice...,
      age1bob...,
      age1charlie...
```

Then update existing files:

```bash
sops updatekeys secrets.sops.yml
```

## Alternative Key Types

### GPG

```yaml
creation_rules:
  - path_regex: .*\.sops\.(yml|yaml)$
    pgp: >-
      FINGERPRINT1,
      FINGERPRINT2
```

### AWS KMS

```yaml
creation_rules:
  - path_regex: .*\.sops\.(yml|yaml)$
    kms: arn:aws:kms:us-east-1:123456789:key/xxx
```

### Azure Key Vault

```yaml
creation_rules:
  - path_regex: .*\.sops\.(yml|yaml)$
    azure_keyvault: https://myvault.vault.azure.net/keys/mykey/version
```

### GCP KMS

```yaml
creation_rules:
  - path_regex: .*\.sops\.(yml|yaml)$
    gcp_kms: projects/myproject/locations/global/keyRings/myring/cryptoKeys/mykey
```

## Troubleshooting

### "SOPS binary not found"

::::{tab-set}

:::{tab-item} macOS / Linux

```bash
which sops  # Check if installed
```

:::

:::{tab-item} Windows (PowerShell)

```powershell
Get-Command sops  # Check if installed
```

:::

::::

### "No age key detected"

::::{tab-set}

:::{tab-item} macOS / Linux

```bash
# Verify key file exists
ls -la ~/.config/sops/age/keys.txt

# Set environment variable
export SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt

# Add to shell profile for persistence
echo 'export SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt' >> ~/.bashrc
```

:::

:::{tab-item} Windows (PowerShell)

```powershell
# Verify key file exists
Test-Path "$env:APPDATA\sops\age\keys.txt"

# Check current environment variable
$env:SOPS_AGE_KEY_FILE

# Set for current session
$env:SOPS_AGE_KEY_FILE = "$env:APPDATA\sops\age\keys.txt"

# Set permanently (User level)
[Environment]::SetEnvironmentVariable("SOPS_AGE_KEY_FILE", "$env:APPDATA\sops\age\keys.txt", "User")
```

:::

::::

### "Failed to decrypt"

1. **Wrong key**: File was encrypted with a different age key
2. **Corrupted file**: `.sops.yml` was manually edited incorrectly
3. **Missing config**: SOPS cannot find `.sops.yaml`

```bash
# Check which keys were used to encrypt
sops --show-metadata secrets.sops.yml
```

### "Error unmarshalling file: yaml: found character that cannot start any token"

SOPS parses YAML before encryption. This error means your plaintext file has invalid YAML syntax.

**Common causes:**

```text
# BAD - @ cannot start an unquoted value
email_from: @resend.dev

# GOOD - quote special characters
email_from: "@resend.dev"
email_from: "user@resend.dev"
```

```yaml
# BAD - # starts a comment
api_key: abc#123

# GOOD - quote values with special characters
api_key: "abc#123"
```

**YAML reserved characters** that need quoting at value start: `@`, `` ` ``, `#`, `|`, `>`, `[`, `]`, `{`, `}`, `&`, `*`, `!`, `%`

**Tip**: When in doubt, quote your string values.

### Filename collision with kstlib.conf.yml

Do **not** name your secrets file `kstlib.conf.yml`. The kstlib CLI auto-loads any file matching this pattern as its configuration, causing initialization errors before SOPS commands run.

```bash
# BAD - triggers config loader collision
kstlib secrets encrypt kstlib.conf.yml

# GOOD - use a different name
kstlib secrets encrypt secrets.yml
kstlib secrets encrypt mail.conf.yml
kstlib secrets encrypt credentials.yml
```

### ".sops.yaml not found" or encryption uses wrong key

SOPS searches for `.sops.yaml` in this exact order:

1. **`SOPS_CONFIG`** environment variable (if set)
2. **Walk up from cwd** - starting from current directory, walks up to filesystem root
3. **`~/.sops.yaml`** (home directory) - same location on all platforms

```
C:\Users\alice\                     # HOME directory (~)
├── .sops.yaml                      # Fallback if nothing found above
└── Projects\
    └── myproject\
        ├── .sops.yaml              # Found if running from myproject/ or below
        ├── examples\
        │   └── mail\
        │       └── secrets.yml     # kstlib secrets encrypt uses myproject/.sops.yaml
        └── tmp\
            └── .sops.yaml          # Only found if running from tmp/
```

```{important}
**Windows users**: SOPS config (`.sops.yaml`) goes in your **home directory** (`C:\Users\<you>\.sops.yaml`),
NOT in `%APPDATA%`. The age **key file** (`keys.txt`) goes in `%APPDATA%\sops\age\`.

| File | Location |
|------|----------|
| Age key | `%APPDATA%\sops\age\keys.txt` |
| SOPS config | `~\.sops.yaml` (e.g., `C:\Users\alice\.sops.yaml`) |
```

**Solutions:**

1. Run `kstlib secrets doctor` to see exactly which config SOPS will use
2. Place `.sops.yaml` at project root (recommended for team projects)
3. Or use `--config` flag: `sops --config /path/to/.sops.yaml encrypt ...`
4. Or set `SOPS_CONFIG` environment variable

### "MAC mismatch"

The file was modified after encryption. Re-encrypt from a clean plaintext:

```bash
# If you have the original plaintext
kstlib secrets encrypt secrets.yml --out secrets.sops.yml --force

# If you only have the corrupted encrypted file, restore from git
git checkout secrets.sops.yml
```

### Run full diagnostics

```bash
kstlib secrets doctor
```

This checks:

- SOPS binary installed and in PATH
- `.sops.yaml` config: shows exact location and source (env/local/home)
- Age keys in config: displays which public keys will be used for encryption
- age-keygen binary installed
- Age private key file exists and displays corresponding public key
- **Key consistency**: warns if your private key doesn't match the config's public keys
- GPG keys (alternative to age)
- AWS credentials (for KMS)
- Keyring backend

```{tip}
If encryption works but decryption fails, run `kstlib secrets doctor` to check for key mismatches.
The doctor will show you exactly which config SOPS is using and whether your keys are consistent.
```

## Best Practices

1. **One key per environment**: dev, staging, prod each get their own age key
2. **Key backup**: Store private keys in a secure vault (1Password, Bitwarden, etc.)
3. **Minimal permissions**: Only grant decrypt access to those who need it
4. **Audit trail**: Use git history to track who changed secrets when
5. **Rotate regularly**: Keys every 90 days, secrets when staff leave

## See Also

- [SOPS documentation](https://github.com/getsops/sops)
- [age documentation](https://github.com/FiloSottile/age)
- {doc}`index` - Secrets overview
- {doc}`providers` - All secret providers
