# Mail Subsystem

Mail helpers cover the entire pipeline: composing messages with `MailBuilder`, constraining filesystem access,
and delivering payloads via transports such as SMTP. Use this reference to wire the pieces together without
spelunking the implementation.

```{tip}
Pair this reference with {doc}`../features/mail/index` for the feature guide.
```

## Quick overview

- `MailBuilder` validates addresses, merges HTML/plain bodies, and exposes a fluent API for attachments.
- `MailFilesystemGuards` wraps `PathGuardrails` so templates, attachments, and inline assets stay within allowed
	roots.
- `MailTransport` defines the delivery contract; `SMTPTransport` is the first concrete backend and filesystem
	export transport is planned next.
- Exceptions distinguish validation (`MailValidationError`), configuration (`MailConfigurationError`), and
	delivery failures (`MailTransportError`).

## Builder workflow

Instantiate a builder, set the addressing headers, choose plain or HTML bodies, and call `build()` to obtain an
`EmailMessage`. The builder keeps validators in play for every step so you catch issues before hitting the
transport layer.

```python
from kstlib.mail import MailBuilder

message = (
    MailBuilder()
    .sender("alerts@example.com")
    .to("ops@example.com")
    .subject("Heartbeat failed")
    .message("Plain fallback", content_type="plain")
    .message("<p>HTML body</p>")
    .build()
)
```

`build()` only assembles the MIME payload. Call `send()` (after assigning a `MailTransport`) when you want the
builder to dispatch via SMTP or other transports.

## Templates and placeholders

Use `message(template=..., placeholders=...)` to render HTML or plain content from reusable files. Guardrails
ensure template paths live under approved directories, but you still control the OS-level permissions on those
folders.

```{literalinclude} ../../../examples/mail/html_template.py
:language: python
:linenos:
:caption: examples/mail/html_template.py
```

Inline resources require an HTML body and a `cid` that matches the `img src="cid:..."` reference. Attachments and
inline paths flow through the guardrails so test environments can keep relaxed policies while production stays
strict.

```{literalinclude} ../../../examples/mail/attachments_inline.py
:language: python
:linenos:
:caption: examples/mail/attachments_inline.py
```

## Filesystem guardrails

`MailFilesystemGuards.default()` loads configuration from `kstlib.conf.yml` (if available) and provisions
`PathGuardrails` for attachments, inline assets, and templates. Override roots or policies per builder by
instantiating your own guard object:

```python
from pathlib import Path
from kstlib.mail import MailBuilder, MailFilesystemGuards

guards = MailFilesystemGuards.relaxed_for_testing(Path("/tmp/mail"))
builder = MailBuilder(filesystem=guards)
```

The guardrails never replace OS-level permissions; they simply provide a consistent abstraction to catch obvious
mistakes (directory traversal, missing roots) before interacting with the transport layer.

---

## Builder

### MailBuilder

```{eval-rst}
.. autoclass:: kstlib.mail.MailBuilder
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

### NotifyResult

```{eval-rst}
.. autoclass:: kstlib.mail.NotifyResult
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

---

## Filesystem

### MailFilesystemGuards

```{eval-rst}
.. autoclass:: kstlib.mail.MailFilesystemGuards
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

---

## Transports

### MailTransport

```{eval-rst}
.. autoclass:: kstlib.mail.MailTransport
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

### AsyncMailTransport

```{eval-rst}
.. autoclass:: kstlib.mail.AsyncMailTransport
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

### AsyncTransportWrapper

```{eval-rst}
.. autoclass:: kstlib.mail.AsyncTransportWrapper
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

### SMTPTransport

```{eval-rst}
.. autoclass:: kstlib.mail.transports.smtp.SMTPTransport
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

### SMTPCredentials

```{eval-rst}
.. autoclass:: kstlib.mail.transports.smtp.SMTPCredentials
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

---

## Exceptions

### MailError

```{eval-rst}
.. autoclass:: kstlib.mail.MailError
   :show-inheritance:
   :noindex:
```

### MailValidationError

```{eval-rst}
.. autoclass:: kstlib.mail.MailValidationError
   :show-inheritance:
   :noindex:
```

### MailConfigurationError

```{eval-rst}
.. autoclass:: kstlib.mail.MailConfigurationError
   :show-inheritance:
   :noindex:
```

### MailTransportError

```{eval-rst}
.. autoclass:: kstlib.mail.MailTransportError
   :show-inheritance:
   :noindex:
```
