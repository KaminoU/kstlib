# Mail Exceptions

Mail helpers rely on a focused hierarchy rooted at `MailError`.
Each subclass narrows the failure domain so you can tell validation issues apart from transport or configuration gaps.
Import everything from `kstlib.mail.exceptions` to keep guards close to the rest of the mail API.

## Exception Hierarchy

```
MailError
├── MailValidationError      # Invalid recipients, attachments
├── MailTransportError       # SMTP/transport delivery failure
└── MailConfigurationError   # Missing headers, secrets, templates
```

```{note}
Filesystem guardrails never bypass the operating system. They provide a consistent abstraction for attachment,
inline, and template paths, but you still need to provision directories and permissions at the OS level.
```

## Quick overview

- `MailError` is the catch-all when you need to terminate a workflow regardless of the root cause.
- `MailValidationError` reports missing recipients, malformed addresses, unsupported attachments, or guardrail
	violations detected by `MailBuilder` and `MailFilesystemGuards`.
- `MailTransportError` surfaces when the active backend (filesystem spool, SMTP, future providers) rejects or
	times out a delivery attempt.
- `MailConfigurationError` is raised when required headers, secrets, or templates are missing at build time.

## Usage patterns

### Building messages defensively

```python
from kstlib.mail import MailBuilder
from kstlib.mail.exceptions import MailConfigurationError, MailValidationError

builder = MailBuilder()

try:
    builder.set_sender("alerts@example.com")
    builder.add_recipient("ops@example.com")
    builder.set_subject("Heartbeat failed")
    message = builder.build()
except MailConfigurationError as error:
    raise SystemExit(f"Missing mail configuration: {error}") from error
except MailValidationError as error:
    LOGGER.warning("Mail rejected by validators", error=error)
```

### Handling transport fallbacks

```python
from kstlib.mail.transports.smtp import SMTPTransport, SMTPCredentials
from kstlib.mail.exceptions import MailTransportError

transport = SMTPTransport(
    host="smtp.example.com",
    credentials=SMTPCredentials(username="alerts", password="secret"),
)

try:
    transport.send(message)
except MailTransportError:
    backup = SMTPTransport(host="smtp-backup.example.com")
    backup.send(message)
```

## Module reference

```{eval-rst}
.. automodule:: kstlib.mail.exceptions
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```
