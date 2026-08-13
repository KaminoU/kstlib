# Secure

`kstlib.secure` provides three families of hardening helpers: **filesystem guardrails** (path validation, root pinning, POSIX permission enforcement), **password hashing** (Argon2id), and **certificate metadata extraction** (bounded X.509 parsing). The guardrails are the hardening layer that mail attachments, mail templates, monitoring outputs, and any user-controlled path go through before being touched, catching obvious mistakes (directory traversal, drive escape on Windows, world-readable secret files) before they reach the operating system. The password hashing helpers let an application that is its own identity provider store and verify user credentials safely.

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

## Certificate metadata (X.509)

`parse_certificate` turns DER-encoded certificate bytes into a frozen `CertificateInfo`: validity window, signature and public key algorithms, key size, serial, SHA-256 fingerprint, and the CA flag. The input is treated as untrusted, so it is size-bounded before parsing and every failure surfaces as a typed exception.

```{tip}
For the API reference (`CertificateInfo`, `parse_certificate`, `MAX_CERTIFICATE_SIZE`) see
{doc}`../../api/secure`, and {doc}`../../api/exceptions/secure` for the exceptions.
```

### When to use

- **Use it to inventory and flag** certificates you already hold: expired, expiring soon, not yet valid, undersized key, weak signature hash, or a CA certificate sitting where no CA belongs.
- **Use it when the bytes come from somewhere you do not control**: a directory attribute, a JWKS `x5c` entry, an uploaded file. That is what the size bound and the typed failures are for.

### When NOT to use

- **It verifies no signature. None at all, including the certificate's own.** It reads metadata, it does not authenticate it. Anyone can forge a certificate carrying the subject, issuer, and dates of their choosing, and this function will report them faithfully. **The values it returns are not proof of identity.** Use them to inventory and to raise a flag, never to decide that a peer is who it claims to be. Whoever needs that guarantee has to validate the certificate chain, and this is not that function.
- **No chain building, no trust store, no revocation check** (CRL, OCSP), and **no network access of any kind**, including AIA fetching. That is a design constraint, not a missing feature: the function is meant to stay cheap and offline.
- **No verdict.** It reports that a certificate expires on a given date, never that it is "expiring soon". What counts as too soon, or as a key too short, depends on your policy, so the thresholds stay with you.

### TL;DR

```python
from datetime import datetime, timedelta, timezone

from kstlib.secure import CertificateError, parse_certificate

WEAK_HASHES = {"md5", "sha1"}
MIN_RSA_BITS = 2048
EXPIRY_WARNING = timedelta(days=30)


def review(der: bytes) -> list[str]:
    """Report what is wrong with a certificate. The thresholds are ours, not the library's."""
    try:
        info = parse_certificate(der)
    except CertificateError:
        return ["unreadable"]

    now = datetime.now(timezone.utc)
    findings = []
    if info.not_after < now:
        findings.append("expired")
    elif info.not_after - now < EXPIRY_WARNING:
        findings.append(f"expires on {info.not_after:%Y-%m-%d}")
    if info.not_before > now:
        findings.append("not yet valid")
    if info.signature_hash in WEAK_HASHES:
        findings.append(f"weak signature hash: {info.signature_hash}")
    # Guard on None first: a missing size means "not applicable", not "weak".
    if info.public_key_type == "rsa" and info.public_key_size is not None and info.public_key_size < MIN_RSA_BITS:
        findings.append(f"undersized RSA key: {info.public_key_size} bits")
    if info.is_ca:
        findings.append("CA certificate")
    return findings
```

### Reading the three `None` values

This is where a consumer is most likely to draw the wrong conclusion.

- **`public_key_size is None` means "not applicable", not "weak".** Nine of the twelve key types a certificate can carry (Ed25519, Ed448, the ML-DSA and ML-KEM families, X25519, X448) have no key size in the classic bit-length sense. Treating `None` as a small key would flag modern algorithms as deficient. Compare sizes only within a type that expresses one, as the example above does for RSA.
- **`signature_hash is None` is ambiguous by construction**, and it covers two very different cases: the algorithm has no separate hash step (Ed25519 signs the message directly), or the algorithm is not recognized by the installed backend. The discriminant is `signature_algorithm`: a readable label means the first case, a bare dotted OID means the second. That second case is not an error, it is what a certificate newer than your `cryptography` release looks like.
- **`subject_cn is None` or `issuer_cn is None`** means there is no usable common name. A certificate can legitimately carry none, identity being expressed through the subject alternative name extension instead.

### Which exception means what

The exception type answers "is it me or is it my data" before you read the message.

| You get | It means | Typical cause |
|---|---|---|
| `TypeError` | Your call is wrong | The payload is not bytes-like |
| `ValueError` | Your call is wrong | `max_size` is zero or negative |
| `CertificateTooLargeError` | The payload is at fault | The blob is over the bound |
| `InvalidCertificateError` | The payload is at fault | Not a usable DER certificate |

Both payload failures inherit from `CertificateError`, itself both a `KstlibError` and a `ValueError`, so `except CertificateError` catches every data problem in one clause while still letting you separate an oversized blob from a corrupt one when that distinction matters.

### `is_ca` when the extension is absent

`is_ca` is a plain `bool`, and it is `False` both when `BasicConstraints` says so and when the extension is missing entirely. That is not a lost distinction: RFC 5280 section 4.2.1.9 gives the two cases the same consequence in a single sentence, stating that a key whose certificate lacks the extension, **or** carries it without asserting `cA`, must not be used to verify certificate signatures. The same specification also requires conforming CAs to include the extension in every CA certificate, so a compliant CA always carries it.

A tri-state would also be a trap on a security path: `if info.is_ca is False` silently skips a `None`, and the failure mode is under-detection with no error and no trace.

### Security behavior

- **Bounded input**: payloads over `MAX_CERTIFICATE_SIZE` (64 KiB) are rejected before parsing. A common certificate is 1 to 2 KB, and the largest realistic one, carrying a post-quantum key and a long subject alternative name list, stays around 10 KB.
- **Per-call override, no configuration key**: pass `max_size=` to raise or lower the bound for one call. There is deliberately **no YAML setting** for it, so do not go looking for one: the bound belongs to the call site that knows what it is reading.
- **Offline by construction**: no socket is ever opened, so the function cannot hang on a slow endpoint or leak the fact that you are inspecting a given certificate.
- **Rejections are logged**: every refusal emits a `WARNING [SECURITY]` carrying sizes and reasons only, never certificate content.
