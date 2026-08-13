# Secure Exceptions

Each helper in `kstlib.secure` raises its own family of exceptions, all descending from `KstlibError`. A single
clause therefore catches everything the module can produce, while each family base lets you narrow down to one
concern when that is what you need. The hierarchy and the overview below list them.

## Exception Hierarchy

```
KstlibError
├── PathSecurityError              # filesystem guardrails (also inherits RuntimeError)
├── PasswordError                  # password hashing (also inherits RuntimeError)
│   └── InvalidPasswordHashError   # stored hash is corrupt or not a valid Argon2 hash
└── CertificateError               # certificate parsing (also inherits ValueError)
    ├── CertificateTooLargeError   # payload over the accepted size bound
    └── InvalidCertificateError    # not a usable DER-encoded certificate
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
- `CertificateError` (under `KstlibError`, also a `ValueError`) is the base for every payload problem
  raised by `parse_certificate`. Catching it covers both failure modes at once, while a wrong call
  contract raises a builtin instead: `TypeError` for a payload that is not bytes-like, `ValueError` for a
  non-positive `max_size`. So the exception type already says whether the caller or the data is at fault.
- `CertificateTooLargeError` (under `CertificateError`) signals a payload above the accepted bound,
  `MAX_CERTIFICATE_SIZE` by default and overridable per call. The check runs before any parsing.
- `InvalidCertificateError` (under `CertificateError`) signals a payload that is not a usable
  DER-encoded certificate: malformed or truncated encoding, trailing bytes, an extension that cannot be
  read, or a serial number that is not positive.

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

### Telling a rejected certificate apart from a broken call

```python
from kstlib.secure import CertificateTooLargeError, InvalidCertificateError, parse_certificate

try:
    info = parse_certificate(der_bytes)
except CertificateTooLargeError:
    # The entry is over the bound: report it and move on, the rest of the
    # inventory is still worth producing.
    skip("certificate too large")
except InvalidCertificateError:
    skip("certificate unreadable")
# TypeError and a bare ValueError are deliberately not caught here: they mean
# the call itself is wrong, and that is a bug to fix, not data to skip.
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

.. autoexception:: kstlib.secure.certificates.CertificateError
    :members:
    :show-inheritance:

.. autoexception:: kstlib.secure.certificates.CertificateTooLargeError
    :members:
    :show-inheritance:

.. autoexception:: kstlib.secure.certificates.InvalidCertificateError
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
