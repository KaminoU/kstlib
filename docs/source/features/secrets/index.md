# Secrets

Resolve credentials from multiple sources (env, keyring, SOPS) with automatic cascade and memory-safe access.

## TL;DR

```bash
# 1. Quick setup (generates age key + .sops.yaml config)
kstlib secrets init

# 2. Check everything is ready
kstlib secrets doctor

# 3. Encrypt your secrets
kstlib secrets encrypt secrets.yml --out secrets.sops.yml --shred
```

```python
# 4. Use in code (secure pattern)
from kstlib.secrets import resolve_secret, sensitive

record = resolve_secret("api.key")
with sensitive(record) as secret_value:
    call_api(api_key=secret_value)
# secret purged from memory
```

## Key Features

- **Multi-provider cascade**: env vars, keyring, SOPS files
- **Memory safety**: `sensitive()` context manager auto-purges secrets
- **SOPS integration**: Encrypted YAML/JSON with age, GPG, or KMS
- **CLI tools**: `init`, `doctor`, `encrypt`, `decrypt`, `shred`
- **Secure delete**: Overwrite files before deletion

## Quick Start

```bash
# 1. Install prerequisites
# Linux/macOS: brew install sops age
# Windows: scoop install sops; scoop bucket add extras && scoop install age

# 2. Initialize (creates age key + .sops.yaml)
kstlib secrets init

# 3. Create secrets file
cat > secrets.yml << 'EOF'
api:
  stripe_key: "sk_live_xxxxx"
  openai_key: "sk-xxxxx"
EOF

# 4. Encrypt and shred original
kstlib secrets encrypt secrets.yml --out secrets.sops.yml --shred
```

```python
# 5. Use in code
from kstlib.secrets import resolve_secret, sensitive

record = resolve_secret("api.stripe_key")
with sensitive(record) as key:
    stripe.api_key = key
```

## How It Works

When you call `resolve_secret("api.key")`, kstlib checks providers in order:

```text
kwargs → env → keyring → SOPS → default
   ↓       ↓       ↓        ↓        ↓
First match wins. If nothing found, raise or return default.
```

The `sensitive()` context manager provides memory-safe access:

```python
record = resolve_secret("api.key")
with sensitive(record) as secret_value:
    # Use secret_value here
    pass
# record.value is now None - secret purged from memory
```

See {doc}`providers` for detailed documentation on each provider.

## Configuration

### In kstlib.conf.yml

```yaml
secrets:
  sops:
    path: secrets.sops.yml    # default SOPS file
    binary: sops              # or full path

  keyring:
    service: kstlib           # keyring service name

  secure_delete:
    method: auto              # auto | command | overwrite
    passes: 3
    zero_last_pass: true
```

### Prerequisites

Install **sops** and **age**:

::::{tab-set}

:::{tab-item} Linux
See [SOPS releases](https://github.com/getsops/sops/releases) and [age releases](https://github.com/FiloSottile/age/releases).
:::

:::{tab-item} macOS (Homebrew)

```bash
brew install sops age
```

:::

:::{tab-item} Windows (Scoop)

```powershell
scoop install sops
scoop bucket add extras && scoop install age
```

:::

::::

For manual setup or advanced configuration (GPG, KMS), see {doc}`sops`.

## Common Patterns

### Encrypt and shred

```bash
# Recommended: encrypt then securely delete original
kstlib secrets encrypt secrets.yml --out secrets.sops.yml --shred
```

### Decrypt for inspection

```bash
# Print to stdout (safe for quick peek)
kstlib secrets decrypt secrets.sops.yml

# Edit in place (opens in $EDITOR, re-encrypts on save)
sops secrets.sops.yml
```

### Resolve with fallback

```python
record = resolve_secret("api.missing_key", required=False, default="fallback")
```

### Error handling

```python
from kstlib.secrets import (
    resolve_secret,
    sensitive,
    SecretNotFoundError,
    SecretDecryptionError,
)

try:
    record = resolve_secret("api.key", required=True)
    with sensitive(record) as secret_value:
        response = call_api(api_key=secret_value)
except SecretNotFoundError:
    logger.warning("API key not configured")
    response = call_api_anonymous()
except SecretDecryptionError:
    logger.error("Cannot decrypt secrets file")
    raise
```

### Quick Reference

| Task | Command |
| - | - |
| Quick setup | `kstlib secrets init` |
| Local setup | `kstlib secrets init --local` |
| Check setup | `kstlib secrets doctor` |
| Encrypt | `kstlib secrets encrypt FILE --out FILE.sops.yml` |
| Encrypt + shred | `kstlib secrets encrypt FILE --out FILE.sops.yml --shred` |
| Decrypt to stdout | `kstlib secrets decrypt FILE.sops.yml` |
| Decrypt to file | `kstlib secrets decrypt FILE.sops.yml --out FILE` |
| Edit in place | `sops FILE.sops.yml` |
| Secure delete | `kstlib secrets shred FILE` |

## Troubleshooting

### SecretNotFoundError

Secret key not found in any provider:

```python
# Fix: Check key path matches YAML structure
# secrets.sops.yml:
#   api:
#     stripe_key: "sk_xxx"
# Correct: resolve_secret("api.stripe_key")
# Wrong: resolve_secret("stripe_key")
```

### SecretDecryptionError

SOPS cannot decrypt the file:

```bash
# Check your key is available
kstlib secrets doctor

# Verify SOPS can decrypt
sops -d secrets.sops.yml
```

### "age: no identity found"

Age key file missing or wrong location:

```bash
# Linux/macOS
ls -la ~/.config/sops/age/keys.txt

# Windows
dir %APPDATA%\sops\age\keys.txt

# Regenerate if needed
kstlib secrets init
```

### Secure delete not working

Check the configured method:

```yaml
secrets:
  secure_delete:
    method: auto  # Try 'command' or 'overwrite' explicitly
```

## Security Notes

1. **Never log secrets** - kstlib redacts sensitive output, but be careful in your code
2. **Use `--shred`** - Securely delete plaintext files after encryption
3. **Restrict key permissions**:
   - Linux/macOS: `chmod 400 ~/.config/sops/age/keys.txt`
   - Windows: User-level NTFS permissions protect `%APPDATA%\sops\age\`
4. **Rotate regularly** - Both secret values and encryption keys
5. **Use `sensitive()`** - Minimize secret lifetime in memory

## Learn More

```{toctree}
:maxdepth: 1

providers
sops
```

## API Reference

Full autodoc: {doc}`../../api/secrets`

| Function | Description |
| - | - |
| `resolve_secret(name, ...)` | Resolve a secret from the provider cascade |
| `sensitive(record)` | Context manager for secure access with auto-purge |
| `get_secret_resolver()` | Get the global resolver instance |
| `SecretRecord` | Result object with `value`, `source`, metadata |
