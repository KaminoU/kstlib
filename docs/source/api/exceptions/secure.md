# Secure Exceptions

`PathGuardrails` and higher-level wrappers (mail guardrails, future storage helpers) raise
`PathSecurityError` whenever filesystem access breaches the configured policies. Keep this exception handy when
integrating guardrails so you can differentiate between OS-level errors and policy violations.

## Exception Hierarchy

```
RuntimeError
└── PathSecurityError    # Path traversal or policy violation
```

```{note}
Guardrails never bypass the operating system. They provide a consistent policy layer (auto-create roots,
permission checks, traversal detection), but you still need to provision secure directories and ACLs yourself.
```

## Quick overview

- `PathSecurityError` inherits from `RuntimeError` and signals traversal attempts, wrong file types, or
  permissions that exceed the allowed mask defined by the active `GuardPolicy`.

## Usage patterns

### Resolving safe files

```python
from pathlib import Path
from kstlib.secure import PathGuardrails, PathSecurityError, STRICT_POLICY

guard = PathGuardrails(Path("~/.cache/kstlib"), policy=STRICT_POLICY)

try:
    template = guard.resolve_file("templates/newsletter.html")
except PathSecurityError as error:
    LOGGER.error("Blocked unsafe path", error=error)
```

### Handling traversal attempts

```python
from kstlib.secure import PathGuardrails, PathSecurityError, RELAXED_POLICY

guard = PathGuardrails("/srv/kstlib", policy=RELAXED_POLICY)

try:
    guard.resolve_file("../etc/passwd")
except PathSecurityError:
    print("Traversal prevented by guardrails")
```

## Exception reference

```{eval-rst}
.. autoexception:: kstlib.secure.fs.PathSecurityError
    :members:
    :show-inheritance:
```

## Module reference

```{eval-rst}
.. automodule:: kstlib.secure.fs
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```
