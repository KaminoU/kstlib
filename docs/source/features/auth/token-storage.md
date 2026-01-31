# Token Storage

The auth module provides secure token storage backends to persist authentication across sessions.

```{note}
**Default location**: `~/.config/kstlib/auth/tokens/`

All storage backends (except `memory`) save tokens to this directory by default.
Token files are named `{provider_name}.token.json` (file) or `{provider_name}.token.sops.json` (sops).
```

## Storage Backends

| Backend | Persistence | Security | Use Case |
|---------|-------------|----------|----------|
| `memory` | None (process only) | N/A | Testing, short-lived scripts |
| `file` | Plain JSON on disk | Low | Dev/testing, SOPS unavailable |
| `sops` | Encrypted on disk | High | Production, CLI usage |

```{warning}
For production environments where token confidentiality is critical, use `sops` storage. The `file` backend stores tokens in plaintext and should only be used for development or when SOPS is not available.
```

## SOPS Storage (Recommended)

Tokens are encrypted using [SOPS](https://github.com/getsops/sops) with age, GPG, or AWS KMS.

### Configuration

```yaml
auth:
  token_storage: "sops"

  storage:
    sops:
      directory: "~/.config/kstlib/auth/tokens"
```

### How It Works

1. After successful login, tokens are serialized to JSON
2. JSON is encrypted with SOPS using your configured keys
3. Encrypted file is saved to `{directory}/{provider_name}.sops.json`
4. File permissions are set to `0400` (owner read-only)

### File Structure

```
~/.config/kstlib/auth/tokens/
├── corporate.sops.json    # Encrypted tokens for 'corporate' provider
├── github.sops.json       # Encrypted tokens for 'github' provider
└── dev.sops.json          # Encrypted tokens for 'dev' provider
```

### Encrypted File Example

```json
{
    "access_token": "ENC[AES256_GCM,data:...,iv:...,tag:...,type:str]",
    "refresh_token": "ENC[AES256_GCM,data:...,iv:...,tag:...,type:str]",
    "token_type": "bearer",
    "expires_at": "2026-01-03T15:30:00Z",
    "scope": ["openid", "profile", "email"],
    "sops": {
        "age": [
            {
                "recipient": "age1...",
                "enc": "..."
            }
        ],
        "lastmodified": "2026-01-03T14:00:00Z",
        "version": "3.8.1"
    }
}
```

### SOPS Quick Setup for Token Storage

Token files are stored in `~/.config/kstlib/auth/tokens/` with names like `provider.token.sops.json`.
SOPS needs a `.sops.yaml` configuration file to know how to encrypt these files.

```{important}
**Key point**: The `.sops.yaml` file must be placed where SOPS can find it when encrypting files in `~/.config/kstlib/auth/tokens/`.

SOPS searches for `.sops.yaml` in this order:
1. Current directory (where you run the command)
2. Parent directories up to root
3. **User home directory** (`~/.sops.yaml`) ← Recommended for token storage
```

#### Step 1: Generate an Age key (if not done)

::::{tab-set}

:::{tab-item} macOS / Linux
```bash
mkdir -p ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt
chmod 400 ~/.config/sops/age/keys.txt

# Note your public key (starts with "age1...")
grep "public key" ~/.config/sops/age/keys.txt
```
:::

:::{tab-item} Windows (PowerShell)
```powershell
New-Item -ItemType Directory -Force -Path "$env:APPDATA\sops\age"
age-keygen -o "$env:APPDATA\sops\age\keys.txt"

# Set environment variable (required on Windows)
[Environment]::SetEnvironmentVariable("SOPS_AGE_KEY_FILE", "$env:APPDATA\sops\age\keys.txt", "User")

# Note your public key
Select-String "public key" "$env:APPDATA\sops\age\keys.txt"
```
:::

::::

#### Step 2: Create `.sops.yaml` in your home directory

::::{tab-set}

:::{tab-item} macOS / Linux
```bash
cat > ~/.sops.yaml << 'EOF'
creation_rules:
  # Match token files in kstlib auth directory
  - path_regex: \.config/kstlib/auth/tokens/.*\.sops\.json$
    age: age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

  # Optional: match other SOPS files in your projects
  - path_regex: .*\.sops\.(yml|yaml|json)$
    age: age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
EOF
```
:::

:::{tab-item} Windows (PowerShell)
Create `%USERPROFILE%\.sops.yaml` with:
```yaml
creation_rules:
  # Match token files in kstlib auth directory
  - path_regex: \.config\\kstlib\\auth\\tokens\\.*\.sops\.json$
    age: age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

  # Optional: match other SOPS files
  - path_regex: .*\.sops\.(yml|yaml|json)$
    age: age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```
:::

::::

```{warning}
**Replace** `age1xxx...` with YOUR actual public key from Step 1!
```

#### Step 3: Verify setup

```bash
kstlib secrets doctor
```

Expected output:
```
✓ SOPS binary found
✓ age binary found
✓ Age key file exists
✓ .sops.yaml configuration found
✓ Can encrypt/decrypt test value
```

#### Common mistakes

| Problem | Symptom | Solution |
|---------|---------|----------|
| `.sops.yaml` in wrong location | `SOPS: no matching creation rule` | Move to `~/.sops.yaml` |
| Wrong `path_regex` | `SOPS: no matching creation rule` | Use pattern above that matches `.sops.json` |
| Missing Age key | `age: error: no identity` | Run Step 1 or set `SOPS_AGE_KEY_FILE` |
| Wrong public key in config | `age: error: no identity matched` | Update `.sops.yaml` with correct key |

## Memory Storage

In-memory storage for testing or short-lived processes.

```yaml
auth:
  token_storage: "memory"
```

```{warning}
**Memory storage does NOT persist across CLI commands!**

Each CLI invocation runs in a separate process. Tokens stored in memory are lost when the process exits.

Example of what **won't work**:
- `kstlib auth login my-provider`  → stores token in memory
- `kstlib auth status`             → new process, token is gone!

For CLI usage, use `file` (dev) or `sops` (production).
```

### Use Cases

- **Unit tests** (same process throughout test)
- **Long-running daemons** or API servers
- **Interactive Python sessions** (REPL)
- CI/CD pipelines with injected tokens (if token is passed via env/arg, not storage)

## File Storage

Plain JSON file storage for development or environments where SOPS is unavailable.

```yaml
auth:
  token_storage: "file"

  storage:
    file:
      directory: "~/.config/kstlib/auth/tokens"
```

```{warning}
Tokens are stored **unencrypted** on disk. A warning is logged on first use:
`FileTokenStorage: Tokens will be stored UNENCRYPTED at ...`
```

### File Structure

```
~/.config/kstlib/auth/tokens/
├── corporate.token.json    # Plaintext tokens for 'corporate' provider
├── github.token.json       # Plaintext tokens for 'github' provider
└── dev.token.json          # Plaintext tokens for 'dev' provider
```

### File Permissions

Files are created with restrictive permissions (`0600` - owner read/write only), but the content is not encrypted.

### Use Cases

- Local development without SOPS setup
- Docker containers where SOPS config is complex
- Testing persistence without encryption overhead
- Quick debugging of token flow

### When NOT to Use

- Production environments
- Shared machines
- When token leakage has significant impact

## Security Considerations

### Token Sensitivity

OAuth tokens are **sensitive credentials**:

| Token Type | Risk if Leaked |
|------------|----------------|
| Access Token | API access until expiration (usually 5-60 min) |
| Refresh Token | Long-term access (days/weeks), can mint new access tokens |
| ID Token | Contains user identity claims, PII |

### File Permissions

SOPS storage sets restrictive permissions:

```bash
$ ls -la ~/.config/kstlib/auth/tokens/
-r-------- 1 user user 2048 Jan  3 14:00 corporate.sops.json
```

- `0400` = owner read-only
- No group or world access
- File is locked during write operations

### Encryption at Rest

With SOPS, tokens are encrypted using:

| Backend | Key Location | Rotation |
|---------|--------------|----------|
| age | `~/.config/sops/age/keys.txt` | Manual |
| GPG | GPG keyring | Via GPG |
| AWS KMS | AWS | Automatic |

### Best Practices

1. **Use SOPS storage** for any persistent authentication
2. **Prefer short-lived tokens** (configure low expiration on IdP)
3. **Enable token refresh** so access tokens can be short-lived
4. **Rotate encryption keys** periodically
5. **Don't commit token files** (add to `.gitignore`)

## Programmatic Usage

### Using SOPS Storage

```python
from kstlib.auth.token import SOPSTokenStorage

storage = SOPSTokenStorage(
    directory="~/.config/kstlib/auth/tokens"
)

# Check if token exists
if storage.exists("corporate"):
    token = storage.load("corporate")
```

### Using File Storage

```python
from kstlib.auth.token import FileTokenStorage

storage = FileTokenStorage(
    directory="~/.config/kstlib/auth/tokens"
)

# Save, load, delete tokens
storage.save("my-provider", token)
token = storage.load("my-provider")
storage.delete("my-provider")
```

### Using Memory Storage

```python
from kstlib.auth.token import MemoryTokenStorage

storage = MemoryTokenStorage()
```

### Using the Factory Function

```python
from kstlib.auth.token import get_token_storage

# Create storage by type
memory = get_token_storage("memory")
file_storage = get_token_storage("file", directory="/tmp/tokens")
sops_storage = get_token_storage("sops", directory="/tmp/tokens")
```

### Custom Storage Backend

Implement `AbstractTokenStorage`:

```python
from kstlib.auth.token import AbstractTokenStorage, AuthToken

class MyCustomStorage(AbstractTokenStorage):
    def save(self, provider_name: str, token: AuthToken) -> None:
        # Save token
        ...

    def load(self, provider_name: str) -> AuthToken | None:
        # Load token, return None if not found
        ...

    def delete(self, provider_name: str) -> None:
        # Delete token
        ...

    def exists(self, provider_name: str) -> bool:
        # Check if token exists
        ...
```

## Troubleshooting

### "SOPS not configured"

```bash
$ kstlib auth login
Error: SOPS not configured. Run 'kstlib secrets doctor' for setup.
```

**Solution**: Configure SOPS with age or GPG keys. See {doc}`/development/secrets-management`.

### "Permission denied" on token file

```bash
$ kstlib auth login
Error: Permission denied: ~/.config/kstlib/auth/tokens/corporate.sops.json
```

**Solution**: SOPS token files are set to `0400` (read-only) after creation to prevent accidental modification. To overwrite an existing token, temporarily unlock the file:

```bash
chmod 600 ~/.config/kstlib/auth/tokens/corporate.sops.json
kstlib auth login --force
```

The file will be reset to `0400` after the operation.

### Token not persisting

If tokens aren't saved between sessions:

1. Check `token_storage` is set to `"sops"` (not `"memory"`)
2. Verify SOPS can encrypt: `echo "test: value" | sops -e /dev/stdin`
3. Check the storage directory exists and is writable
