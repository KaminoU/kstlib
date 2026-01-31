# Secure Guardrails

Public helpers for filesystem guardrails. `kstlib.secure` exposes `GuardPolicy` presets and the
`PathGuardrails` utility so mail templates, attachments, and other file-based assets stay confined to trusted
directories.

```{tip}
See {doc}`../features/utils/secure_delete` for the feature guide.
```

## Quick overview

- `STRICT_POLICY` enforces root auto-creation, forbids external paths, and validates POSIX permissions (≤
  `0o700`).
- `RELAXED_POLICY` still pins everything to the root but skips permission enforcement so it fits
  sandboxed/Windows-friendly scenarios.
- `PathGuardrails` resolves relative or absolute inputs, normalises them via `Path.resolve()`, and raises
  `PathSecurityError` whenever a path escapes the root, points to the wrong type, or resides on a different drive
  (Windows).
- `relax()` clones an existing guardrail with a modified `allow_external` flag, which helps when you need to
  temporarily opt into external paths for migrations.

## Configuration snippet

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

Downstream modules instantiate guardrails using these settings so every file operation inherits the same
hardening behavior.

## Usage patterns

### Guarding template directories

```python
from pathlib import Path
from kstlib.secure import PathGuardrails, STRICT_POLICY

guard = PathGuardrails(Path("~/kstlib/templates"), policy=STRICT_POLICY)
template = guard.resolve_file("mailers/welcome.html")
```

### Relaxing external access temporarily

```python
from kstlib.secure import PathGuardrails

guard = PathGuardrails("/srv/kstlib", policy=STRICT_POLICY)
external_guard = guard.relax(allow_external=True)
external_guard.resolve_file("/opt/legacy/template.html")  # raises if file is missing
```

### End-to-end guardrail demo

```{literalinclude} ../../../examples/secure/guardrails_demo.py
:language: python
:linenos:
:caption: examples/secure/guardrails_demo.py
```

## Module reference

```{eval-rst}
.. automodule:: kstlib.secure
	:members:
	:undoc-members:
	:show-inheritance:
	:noindex:
```
