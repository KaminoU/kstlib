# Secure Exceptions

`PathGuardrails` and higher-level wrappers (mail guardrails, future storage helpers) raise
`PathSecurityError` whenever filesystem access breaches the configured policies. Keep this exception handy when
integrating guardrails so you can differentiate between OS-level errors and policy violations.

## Exception Hierarchy

```
KstlibError
├── PathSecurityError              # filesystem guardrails (also inherits RuntimeError)
└── PasswordError                  # password hashing (also inherits RuntimeError)
    └── InvalidPasswordHashError   # stored hash is corrupt or not a valid Argon2 hash
```

```{note}
Guardrails never bypass the operating system. They provide a consistent policy layer (auto-create roots,
permission checks, traversal detection), but you still need to provision secure directories and ACLs yourself.
```

## Quick overview

- `PathSecurityError` inherits from `RuntimeError` and signals traversal attempts, wrong file types, or
  permissions that exceed the allowed mask defined by the active `GuardPolicy`.
- `PasswordError` (under `KstlibError`, also a `RuntimeError`) signals a password hashing failure: the
  optional `argon2-cffi` backend is not installed, the password is not `str`/`bytes`, it exceeds
  `MAX_PASSWORD_LENGTH`, or the backend itself failed.
- `InvalidPasswordHashError` (under `PasswordError`) is raised when a stored value is not a valid Argon2
  hash. Note that `verify_password` returns `False` on a wrong password and raises
  `InvalidPasswordHashError` only when the stored hash itself is corrupt or malformed.

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

### Verifying a password safely

```python
from kstlib.secure import InvalidPasswordHashError, verify_password

try:
    ok = verify_password(submitted_password, stored_hash)
except InvalidPasswordHashError:
    # The stored hash is corrupt or not an Argon2 hash: treat as an integrity
    # error, never as a successful login.
    ok = False

if not ok:
    reject()
```

## Exception reference

```{eval-rst}
.. autoexception:: kstlib.secure.fs.PathSecurityError
    :members:
    :show-inheritance:

.. autoexception:: kstlib.secure.passwords.PasswordError
    :members:
    :show-inheritance:

.. autoexception:: kstlib.secure.passwords.InvalidPasswordHashError
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
