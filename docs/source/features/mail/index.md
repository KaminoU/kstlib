# Mail

Email composition with templates, attachments, and filesystem guardrails.

## TL;DR

```python
from kstlib.mail import MailBuilder

message = (
    MailBuilder()
    .sender("alerts@example.com")
    .to("ops@example.com")
    .subject("Alert: System Status")
    .message("Plain text fallback", content_type="plain")
    .message("<p>HTML body</p>")
    .build()
)
```

## Key Features

- **Fluent API**: Chain methods for clean email composition
- **Dual content**: HTML and plain text bodies
- **Templates**: Jinja2 template rendering with placeholders
- **Attachments**: File attachments and inline images
- **Guardrails**: Filesystem sandboxing for templates and attachments
- **Transports**: SMTP delivery (more planned)

## Quick Start

```python
from kstlib.mail import MailBuilder

# 1. Simple email
message = (
    MailBuilder()
    .sender("sender@example.com")
    .to("recipient@example.com")
    .subject("Hello")
    .message("This is the email body")
    .build()
)

# 2. With HTML and plain text
message = (
    MailBuilder()
    .sender("alerts@example.com")
    .to("team@example.com")
    .subject("Weekly Report")
    .message("Plain text version", content_type="plain")
    .message("<h1>Weekly Report</h1><p>Details here...</p>")
    .build()
)

# 3. Send via SMTP
from kstlib.mail.transports.smtp import SMTPTransport

smtp = SMTPTransport(host="smtp.example.com", port=587)
MailBuilder().transport(smtp).sender("...").to("...").message("...").send()
```

## How It Works

### Message Building

`MailBuilder` uses a fluent API to construct emails step by step:

```python
builder = MailBuilder()
builder.sender("from@example.com")   # Set sender
builder.to("to@example.com")         # Add recipient (can call multiple times)
builder.subject("Subject line")      # Set subject
builder.message("Body content")      # Add body (plain or HTML)
builder.build()                      # Returns EmailMessage object
```

### Templates

Jinja2 templates for reusable content:

```python
message = (
    MailBuilder()
    .sender("noreply@example.com")
    .to("user@example.com")
    .subject("Welcome!")
    .message(
        template="welcome.html",
        placeholders={"username": "Alice", "activation_url": "https://..."},
    )
    .build()
)
```

```html
<!-- templates/welcome.html -->
<h1>Welcome, {{ username }}!</h1>
<p>Click <a href="{{ activation_url }}">here</a> to activate.</p>
```

### Attachments

```python
# File attachments
builder.attachment("reports/monthly.pdf")
builder.attachment("reports/data.xlsx")

# Inline images (for HTML emails)
builder.message('<img src="cid:logo">')
builder.inline("assets/logo.png", cid="logo")
```

### Filesystem Guardrails

Guardrails ensure templates and attachments stay within allowed directories, preventing path traversal attacks:

```python
from kstlib.mail import MailBuilder, MailFilesystemGuards

# Default guards from config
builder = MailBuilder()

# Custom guards
guards = MailFilesystemGuards.from_sources(
    roots=MailGuardRootsOverrides(
        attachments=Path("/srv/mail/attachments"),
        templates=Path("/srv/mail/templates"),
    )
)
builder = MailBuilder(filesystem=guards)
```

## Configuration

### In kstlib.conf.yml

```yaml
mail:
  filesystem:
    attachments_root: /srv/app/mail/attachments
    inline_root: /srv/app/mail/inline
    templates_root: /srv/app/mail/templates
    allow_external_attachments: false
    allow_external_templates: false
```

### SMTP Transport

```python
from kstlib.mail.transports.smtp import SMTPTransport, SMTPCredentials

# Basic SMTP
smtp = SMTPTransport(host="smtp.example.com", port=587)

# With authentication
smtp = SMTPTransport(
    host="smtp.example.com",
    port=587,
    credentials=SMTPCredentials(username="alerts", password="secret"),
)

# SSL (port 465)
smtp = SMTPTransport(host="smtp.example.com", port=465, use_ssl=True)

# STARTTLS (port 587)
smtp = SMTPTransport(host="smtp.example.com", port=587, use_starttls=True)
```

## Common Patterns

### Alert notification

```python
(
    MailBuilder()
    .transport(smtp)
    .sender("alerts@example.com")
    .to("ops@example.com")
    .subject("Alert: High CPU Usage")
    .message("Server cpu-1 is at 95% utilization.")
    .send()
)
```

### Report with attachments

```python
(
    MailBuilder()
    .transport(smtp)
    .sender("reports@example.com")
    .to("finance@example.com")
    .subject("Monthly Report")
    .message("Please find the report attached.")
    .attachment("reports/monthly.pdf")
    .attachment("reports/data.xlsx")
    .send()
)
```

### Newsletter with inline images

```python
(
    MailBuilder()
    .transport(smtp)
    .sender("marketing@example.com")
    .to("subscribers@example.com")
    .subject("Newsletter")
    .message('<h1>Hello!</h1><img src="cid:logo">')
    .inline("assets/logo.png", cid="logo")
    .send()
)
```

### Multiple recipients

Methods `.to()`, `.cc()`, and `.bcc()` accept multiple addresses as arguments.
Invalid addresses raise `MailValidationError` immediately.

```python
(
    MailBuilder()
    .sender("system@example.com")
    .to("user1@example.com", "Michel <user2@example.com>", "user3@example.com")
    .cc("manager@example.com", "team-lead@example.com")
    .bcc("archive@example.com")
    .subject("Team Update")
    .message("Content here")
    .build()
)
```

### Relaxed guards for testing

```python
guards = MailFilesystemGuards.relaxed_for_testing(Path("/tmp/mail"))
builder = MailBuilder(filesystem=guards)
```

## @mail.notify() Decorator

Automatically send email notifications when a function completes. Perfect for ETL pipelines, scheduled jobs, or any operation that needs monitoring.

### Basic Usage

```python
from kstlib.mail import MailBuilder
from kstlib.mail.transports import SMTPTransport

transport = SMTPTransport(host="smtp.example.com", port=587)
mail = (
    MailBuilder(transport=transport)
    .sender("bot@example.com")
    .to("admin@example.com")
    .subject("ETL Pipeline")
)

@mail.notify
def extract_data() -> dict[str, int]:
    """Extract data from source."""
    return {"rows": 1000, "columns": 15}

# On success: sends "[OK] ETL Pipeline - extract_data"
# On failure: sends "[FAILED] ETL Pipeline - extract_data" with traceback
result = extract_data()
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `subject` | Builder's subject | Override the base subject for this function |
| `on_error_only` | `False` | Only send notification on failure |
| `include_return` | `False` | Include return value in email body |
| `include_traceback` | `True` | Include traceback in failure emails |

### Alert Only on Failure

```python
@mail.notify(on_error_only=True)
def quiet_job() -> str:
    """Silent on success, alerts on failure."""
    return "done"
```

### Include Return Value

```python
@mail.notify(include_return=True)
def compute_stats() -> dict[str, float]:
    """Return value will appear in email body."""
    return {"accuracy": 0.95, "loss": 0.05}
```

### Custom Subject per Function

```python
@mail.notify(subject="Step 1 - Extract")
def step1() -> None: ...

@mail.notify(subject="Step 2 - Transform")
def step2() -> None: ...

@mail.notify(subject="Step 3 - Load")
def step3() -> None: ...
```

### Async Support

The decorator works with both sync and async functions:

```python
@mail.notify
async def async_fetch() -> list[dict]:
    """Async functions work the same way."""
    async with httpx.AsyncClient() as client:
        response = await client.get("https://api.example.com/data")
        return response.json()
```

### NotifyResult Dataclass

The notification system uses `NotifyResult` to track execution:

```python
from kstlib.mail import NotifyResult

# NotifyResult contains:
# - function_name: str
# - success: bool
# - started_at: datetime
# - ended_at: datetime
# - duration_ms: float
# - return_value: Any (if include_return=True)
# - exception: BaseException | None
# - traceback_str: str | None
```

```{seealso}
Run [notify_decorator.py](https://github.com/KaminoU/kstlib/blob/main/examples/mail/notify_decorator.py) for complete working examples using Ethereal Email.
```

## Debugging SMTP Connections

When troubleshooting email delivery issues, enable TRACE-level logging to see
detailed SMTP session information:

```python
from kstlib.logging import LogManager

# Enable TRACE level for detailed SMTP diagnostics
log = LogManager(config={"console": {"level": "TRACE"}})

# Then send your email - TRACE logs will show SMTP session details
```

With TRACE enabled, you will see:

- **Connection details**: Host, port, connection timing
- **EHLO exchange**: Server capabilities (STARTTLS, AUTH methods, SIZE limits)
- **STARTTLS negotiation**: TLS version, cipher suite, certificate info
- **Authentication flow**: AUTH method used (credentials redacted)
- **Message envelope**: MAIL FROM, RCPT TO commands

This is useful for diagnosing:

- TLS/SSL handshake failures
- Authentication errors
- Server capability mismatches
- Firewall or network issues

```{seealso}
Run [smtp_trace.py](https://github.com/KaminoU/kstlib/blob/main/examples/mail/smtp_trace.py) for a complete working example with visual output.
```

## Troubleshooting

### MailValidationError: Invalid email address

Check that all email addresses are properly formatted:

```python
from kstlib.mail import MailBuilder
from kstlib.exceptions import MailValidationError

try:
    builder.to("invalid-email").build()
except MailValidationError as e:
    print(f"Invalid: {e}")
```

### MailConfigurationError: No transport configured

A transport is required for `send()`. Either set it explicitly or configure defaults:

```python
# Explicit transport
builder.transport(smtp).send()

# Or set during construction
builder = MailBuilder(transport=smtp)
builder.send()
```

### MailTransportError: SMTP connection failed

Check host, port, and credentials:

```python
from kstlib.exceptions import MailTransportError

try:
    builder.send()
except MailTransportError as e:
    print(f"SMTP error: {e}")
    # Check: host reachable? port open? credentials correct?
```

### Path outside allowed root

Filesystem guardrails block access to files outside configured roots:

```python
# This will fail if /etc/passwd is outside attachments_root
builder.attachment("/etc/passwd")  # Raises exception

# Fix: Use only files within configured roots
builder.attachment("allowed_file.pdf")
```

## API Reference

Full autodoc: {doc}`../../api/mail`

| Class | Description |
| - | - |
| `MailBuilder` | Fluent email builder with `@notify` decorator |
| `NotifyResult` | Dataclass with function execution results |
| `MailFilesystemGuards` | Path sandboxing for templates/attachments |
| `SMTPTransport` | SMTP delivery backend |
| `SMTPCredentials` | SMTP authentication dataclass |
