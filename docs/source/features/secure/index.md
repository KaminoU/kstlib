# Secure

Filesystem guardrails for path validation, root pinning, and POSIX permission enforcement. `kstlib.secure` is the hardening layer that mail attachments, mail templates, monitoring outputs, and any user-controlled path go through before being touched. The goal is to catch obvious mistakes (directory traversal, drive escape on Windows, world-readable secret files) before they reach the operating system.

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
