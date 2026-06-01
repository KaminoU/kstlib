# Secure

`kstlib.secure` provides two families of hardening helpers: **filesystem guardrails** (path validation, root pinning, POSIX permission enforcement) and **password hashing** (Argon2id). The guardrails are the hardening layer that mail attachments, mail templates, monitoring outputs, and any user-controlled path go through before being touched, catching obvious mistakes (directory traversal, drive escape on Windows, world-readable secret files) before they reach the operating system. The password hashing helpers let an application that is its own identity provider store and verify user credentials safely.

```{tip}
For the API reference of the underlying classes (`PathGuardrails`, `GuardPolicy`, `PathSecurityError`,
`STRICT_POLICY`, `RELAXED_POLICY`, ...), see {doc}`../../api/secure`.
```

## TL;DR

```python
from pathlib import Path
from kstlib.secure import PathGuardrails, STRICT_POLICY

guard = PathGuardrails(Path("~/kstlib/templates"), policy=STRICT_POLICY)

# Resolves "mailers/welcome.html" relative to the root, blocks any escape attempt
template = guard.resolve_file("mailers/welcome.html")

# Raises PathSecurityError: outside the root tree
template = guard.resolve_file("../../etc/passwd")
```

## Key Features

- **Root pinning**: every path resolves under a configured root. Anything that escapes (relative `..` traversal, absolute paths to other directories, alternate drives on Windows) raises `PathSecurityError`.
- **Two policies out of the box**:
  - `STRICT_POLICY`: auto-creates the root, forbids external paths, validates POSIX permissions (max `0o700` by default).
  - `RELAXED_POLICY`: still pins to the root but skips permission enforcement, suitable for sandboxed/Windows environments.
- **Permission validation**: `STRICT_POLICY` rejects directories that are world-readable or group-readable when secrets/templates live there.
- **Type-aware resolution**: `resolve_file()` rejects directories, `resolve_dir()` rejects regular files, with a clear `PathSecurityError` message.
- **Temporary relax**: `guard.relax(allow_external=True)` clones the guard with external access allowed for migrations or one-off operations.

## Configuration snippet

`PathGuardrails` is wired into the mail subsystem via `kstlib.conf.yml`:

```yaml
mail:
    filesystem:
        attachments_root: "~/.cache/kstlib/mail/attachments"
        inline_root: "~/.cache/kstlib/mail/inline"
        templates_root: "~/.cache/kstlib/mail/templates"
        allow_external_attachments: false
        allow_external_templates: false
        auto_create_roots: true
        enforce_permissions: true
        max_permission_octal: 448  # 0o700
```

## Usage patterns

### Strict policy with auto-creation

```python
from pathlib import Path
from kstlib.secure import PathGuardrails, STRICT_POLICY

guard = PathGuardrails(Path("/srv/kstlib/templates"), policy=STRICT_POLICY)
guard.ensure_root()  # creates the directory if missing, validates permissions
```

### Relaxing for legacy migration

```python
from kstlib.secure import PathGuardrails, STRICT_POLICY

guard = PathGuardrails("/srv/kstlib", policy=STRICT_POLICY)
external_guard = guard.relax(allow_external=True)
external_guard.resolve_file("/opt/legacy/template.html")  # OK once
```

```{note}
Filesystem guardrails never replace OS-level permissions. They provide a consistent abstraction across
modules so misconfigurations are caught early, but you still need to provision directories and set
permissions correctly at the OS level.
```

## Password hashing (Argon2id)

Hash and verify local user passwords with Argon2id, the OWASP top recommendation for password storage. The backend is the optional `argon2-cffi` dependency:

```bash
pip install kstlib[passwords]
```

```{tip}
For the API reference (functions, cost constants, and the `PasswordError` /
`InvalidPasswordHashError` exceptions), see {doc}`../../api/secure` and
{doc}`../../api/exceptions/secure`.
```

### When to use

- **Use it** to store and verify passwords for users **your application authenticates itself** (the app is the identity provider).
- **Do not use it** for OAuth2/OIDC login flows: use {doc}`../auth/index` instead.
- **Do not use it** to store recoverable secrets: a password hash is one-way and cannot be decrypted. To encrypt and retrieve secrets, use {doc}`../secrets/index`.

### TL;DR

```python
from kstlib.secure import hash_password, verify_password, needs_rehash

# At registration: hash once, persist the returned PHC string.
stored = hash_password(user_password)

# At login: verify the candidate, then opportunistically upgrade the stored
# hash if the cost policy has since been strengthened.
if verify_password(submitted_password, stored):
    if needs_rehash(stored):
        stored = hash_password(submitted_password)  # persist the upgraded hash
    grant_access()
else:
    reject()
```

`verify_password` returns `False` for a wrong password (it never raises on a mismatch). It raises `InvalidPasswordHashError` only when `stored_hash` is corrupt or not a valid Argon2 hash.

### Why Argon2id

Argon2id won the 2015 Password Hashing Competition and is the OWASP first choice: it is memory-hard, which makes large-scale GPU/ASIC cracking expensive. The built-in defaults follow the RFC 9106 low-memory profile (`time_cost=3`, `memory_cost=65536` KiB = 64 MiB, `parallelism=4`), which already tracks the OWASP recommendation.

### Tuning the cost (optional)

The defaults are safe out of the box. To tune the cost, override them once in `kstlib.conf.yml`:

```yaml
secure:
    passwords:
        time_cost: 4         # iterations (floor: 2)
        memory_cost: 131072  # KiB, here 128 MiB (floor: 19456 = 19 MiB)
        parallelism: 4       # parallel lanes (floor: 1)
        hash_len: 32         # derived hash length in bytes (floor: 16)
        salt_len: 16         # random salt length in bytes (floor: 16)
```

Resolution follows the cascade `kwargs > config > defaults`. The three cost knobs (`time_cost`, `memory_cost`, `parallelism`) can also be overridden per call as keyword arguments to `hash_password`. Output sizing (`hash_len`, `salt_len`) is **config-only**: it must stay consistent across all stored hashes, so it is deliberately not a per-call argument.

### Security behavior

- **Never logged**: passwords and hashes are never written to the logs, even at `TRACE`.
- **Floors, not failures**: any cost parameter resolved below its security floor is clamped up to the floor and a `WARNING [SECURITY]` is logged (never silently dropped, never raised). The floors are the OWASP minimum baseline (19 MiB / `t=2`); the defaults sit well above them, so the floor only blocks a deliberate downgrade.
- **Anti-DoS**: passwords longer than `MAX_PASSWORD_LENGTH` (4096 bytes) are rejected. `hash_password` raises `PasswordError`; `verify_password` returns `False`.
