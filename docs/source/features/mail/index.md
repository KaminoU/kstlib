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
- **Transports**: SMTP, AWS SES, Resend, Gmail API

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
  # Named transport preset auto-resolved when MailBuilder() is called
  # without transport= or preset=. Leave null to force callers to pick.
  default: corporate

  # Named presets referenced by MailBuilder(preset="name") or by mail.default.
  # Each entry declares a "transport" field (smtp or resend) plus backend-
  # specific parameters.
  presets:
    corporate:
      transport: smtp
      host: smtp-secure.corp.local
      port: 25
      login: svc_user
      password: "secret"
      starttls: false
      ssl: false
      timeout: 30

    transactional:
      transport: resend
      api_key: re_xxxxxxxxxxxxx
      timeout: 30

    local:
      transport: smtp
      host: localhost
      port: 1025
      starttls: false

  filesystem:
    attachments_root: /srv/app/mail/attachments
    inline_root: /srv/app/mail/inline
    templates_root: /srv/app/mail/templates
    allow_external_attachments: false
    allow_external_templates: false
```

### Config-driven usage vs. direct transport

`MailBuilder` supports two complementary construction modes. The priority
cascade is ``transport=`` kwarg, then ``preset=`` kwarg, then
``mail.default`` in config, then ``None``.

```python
from kstlib.mail import MailBuilder
from kstlib.mail.transports.smtp import SMTPTransport

# 1. Explicit transport (backward compatible, useful for one-off instances)
smtp = SMTPTransport(host="smtp.example.com", port=587)
MailBuilder(transport=smtp).sender("...").to("...").send()

# 2. Named preset (reads mail.presets.<name> from kstlib.conf.yml)
MailBuilder(preset="corporate").sender("...").to("...").send()

# 3. Default preset (reads mail.default from kstlib.conf.yml)
MailBuilder().sender("...").to("...").send()
```

Preset resolution fails fast with `MailConfigurationError` when the name
is unknown, the transport field is missing, or a required backend field
(e.g. SMTP host, Resend api_key) is absent.

### Preset fields

| Field     | Transport | Required | Default | Description          |
|-----------|-----------|----------|---------|----------------------|
| transport | all       | yes      | -       | smtp or resend       |
| host      | smtp      | yes      | -       | SMTP server hostname |
| port      | smtp      | no       | 587     | SMTP port            |
| login     | smtp      | no       | -       | SMTP username        |
| password  | smtp      | no       | -       | SMTP password        |
| starttls  | smtp      | no       | true    | Enable STARTTLS      |
| ssl       | smtp      | no       | false   | Use SSL/TLS directly |
| timeout   | smtp      | no       | null    | Connection timeout   |
| api_key   | resend    | yes      | -       | Resend API key       |
| timeout   | resend    | no       | 30.0    | Request timeout      |

### AWS SES Transport

Send emails via AWS Simple Email Service using raw MIME. Requires the `ses` extra:

```bash
pip install "kstlib[ses]"
```

```python
from kstlib.mail.transports import SesTransport

# Using the default credential chain (recommended on EC2 / ECS / Lambda)
ses = SesTransport(region="eu-west-3")

# With explicit credentials
ses = SesTransport(
    region="us-east-1",
    aws_access_key_id="AKIA...",
    aws_secret_access_key="secret...",
)

# Send
MailBuilder().transport(ses).sender("alerts@example.com").to("ops@example.com").message("Hello").send()
```

`SesTransport` passes the full MIME message to `send_raw_email`, so HTML,
attachments, and all headers are preserved without conversion.

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

(mail-preset-envelope-defaults)=

### Preset envelope defaults

A `mail.preset` may declare a `defaults:` subsection to pre-fill envelope
fields that do not change between messages. The current scope is
**intentionally narrow**: only `sender` and `reply_to` are supported.
Anything declared under another key is logged once as a WARNING and
ignored, so old YAML files keep working when kstlib later adds new
supported keys.

```{warning}
**Do NOT pre-fill `to`, `cc`, or `bcc`.** This is refused by design.
Pre-filling recipients in a preset means that a caller who forgets to
set `.to(...)` would silently send to the preset's audience. The feature
is deliberately scoped to the sender-side envelope fields where the
identity is service-owned and stable (typically a service mailbox).
```

#### Cascade

| Priority | Source | Applies when |
| - | - | - |
| 1 | `.sender(value)` / `.reply_to(value)` on the builder | User-provided, always wins |
| 2 | `mail.presets.<name>.defaults.sender` / `.reply_to` | A preset is resolved (either `preset=` kwarg or `mail.default`) |
| 3 | Nothing | The builder starts with `None` / empty - existing behaviour |

#### YAML example

```yaml
mail:
  default: corporate
  presets:
    corporate:
      transport: smtp
      host: smtp-secure.corp.local
      port: 25
      starttls: true
      login: svc_mail
      password: "..."
      defaults:
        sender: "Service Notifications <notify@corp.local>"
        reply_to: "Service Notifications <notify@corp.local>"
```

#### Python usage

```python
from kstlib.mail import MailBuilder

# Sender and reply_to come from the preset, no need to retype them:
(
    MailBuilder(preset="corporate")
    .to("oncall@corp.local")
    .subject("Heartbeat KO")
    .message("Service did not check in at 09:00.")
    .send()
)

# Explicit override wins, preset default is ignored:
(
    MailBuilder(preset="corporate")
    .sender("Incident Bot <incidents@corp.local>")
    .to("oncall@corp.local")
    .subject("Manual alert")
    .message("...")
    .send()
)

# Same behaviour when mail.default resolves to "corporate":
MailBuilder().to("oncall@corp.local").subject("...").message("...").send()
```

#### Behaviour notes

- **`MailBuilder(transport=custom_transport)` short-circuits the preset
  logic entirely.** An explicit transport means the caller is not going
  through a preset at all, so no envelope defaults are applied - mirror
  of the transport resolution rule.
- **Invalid email formats surface at init time** via `MailValidationError`.
  Non-string values (a YAML list where a string was expected, for
  example) surface via `MailConfigurationError`. Both fail fast rather
  than at `.send()` time.
- **Forward compatibility**: unsupported keys inside `defaults` are
  logged once per builder instance as `WARNING` in `kstlib.mail.builder`
  and ignored.

(mail-ssl-tls-configuration)=

### SSL / TLS configuration

SMTP presets resolve their SSL context through a **4-level cascade**. Each
of the two keys (`ssl_verify`, `ssl_ca_bundle`) is resolved independently,
so a preset can disable verification while a higher level still provides
a CA bundle, and vice versa.

#### Priority (highest to lowest)

| Level | Source | Keys |
| - | - | - |
| 1 | Preset section | `mail.presets.<name>.ssl_verify`, `.ssl_ca_bundle` |
| 2 | Mail-scoped | `mail.ssl.verify`, `mail.ssl.ca_bundle` |
| 3 | Root-global | `ssl.verify`, `ssl.ca_bundle` |
| 4 | Python default | `True`, `None` |

```{note}
When both `ssl_ca_bundle` and `ssl_verify=false` are resolved, the CA
bundle wins. Providing a bundle expresses intent to verify against that
bundle, so the context keeps `verify_mode=CERT_REQUIRED` and
`check_hostname=True`. To fully disable verification, leave
`ssl_ca_bundle` unset at every level and set `ssl_verify: false`.
```

#### YAML examples

**Strict public CA** (the default, no configuration required):

```yaml
mail:
  default: external
  presets:
    external:
      transport: smtp
      host: smtp.example.com
      port: 587
      starttls: true
```

**Private CA bundle for an internal relay**:

```yaml
mail:
  ssl:
    verify: true
    ca_bundle: /etc/ssl/certs/corp-ca.pem
  presets:
    corporate:
      transport: smtp
      host: smtp-secure.corp.local
      port: 25
      starttls: true
      login: svc_mail
      password: "..."
```

**Per-preset override** (one relay has its own PKI, everything else uses
the default trust store):

```yaml
mail:
  presets:
    legacy_internal:
      transport: smtp
      host: legacy.corp.local
      port: 25
      starttls: true
      ssl_ca_bundle: /etc/ssl/certs/legacy-corp-ca.pem
    modern_external:
      transport: smtp
      host: smtp.example.com
      port: 587
      starttls: true
```

**Disabling verification** (testing, isolated lab environment only):

```yaml
mail:
  presets:
    lab:
      transport: smtp
      host: lab-smtp.internal
      port: 25
      starttls: true
      ssl_verify: false
```

```{warning}
Setting `ssl_verify: false` at any level emits a WARNING log at
transport build time naming the source (`preset`, `mail.ssl`,
`ssl (root)` or `default`). It disables certificate verification
entirely and exposes the SMTP session to MITM attacks. Prefer
`ssl_ca_bundle: /path/to/private-ca.pem` for private PKIs.
```

#### Hardening

Every resolved `ssl_ca_bundle` path goes through
{func}`kstlib.ssl.validate_ca_bundle_path` (7 layers: type check,
null-byte rejection, empty-string rejection, existence, file-not-dir,
readability, PEM header + size check). An invalid path raises
`MailConfigurationError` at build time, not at send time.

A non-bool `ssl_verify` (for instance `"yes"` parsed as a YAML string)
raises `TypeError` at build time. There is no silent coercion.

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
| `on_success_only` | `False` | Only send notification on success |
| `mode` | `None` | Filtering mode: `"ok"`, `"ko"`, or `"both"` (case-insensitive) |
| `collector` | `None` | Optional `NotifyCollector` to record results |
| `include_return` | `False` | Include return value in email body |
| `include_traceback` | `True` | Include traceback in failure emails |

`mode` is mutually exclusive with `on_error_only` / `on_success_only`. Mixing them raises `MailValidationError`. The aliases are:

- `mode="ok"` is equivalent to `on_success_only=True`
- `mode="ko"` is equivalent to `on_error_only=True`
- `mode="both"` is the default (notify on both success and failure)

### Alert Only on Failure

```python
@mail.notify(on_error_only=True)
def quiet_job() -> str:
    """Silent on success, alerts on failure."""
    return "done"

# Equivalent shorthand:
@mail.notify(mode="ko")
def quiet_job_v2() -> str:
    return "done"
```

### Alert Only on Success

```python
@mail.notify(on_success_only=True)
def heartbeat() -> None:
    """Reports heartbeats only on a clean run."""

# Equivalent shorthand:
@mail.notify(mode="ok")
def heartbeat_v2() -> None: ...
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

### Let Exceptions Bubble

For `notify(on_error_only=True)` or `notify(mode="ko")` to fire, the exception must SORTIR (escape) the decorated function. The decorator catches exceptions at the wrapper level: if the function swallows them internally, the wrapper sees a clean return and treats it as a success.

```python
# Bad: exception is swallowed, the decorator never sees it
@mail.notify(on_error_only=True)
def check_proxy() -> None:
    try:
        ping_proxy(timeout=2)
    except Exception as exc:
        log.warning("oops: %s", exc)
        # No re-raise: the decorator sees a clean return
```

```python
# Good: re-raise (or wrap and raise) so the decorator can act
@mail.notify(on_error_only=True)
def check_proxy() -> None:
    try:
        ping_proxy(timeout=2)
    except (TimeoutError, ConnectionError) as exc:
        log.warning("proxy unreachable: %s", exc)
        raise CheckError(f"proxy: {exc}") from exc

# Then the main loop catches at its own level so the run continues
for fn in CHECKS:
    try:
        fn()
    except Exception as exc:
        # The decorator already sent the mail; we just keep going.
        log.info("%s: KO (%s)", fn.__name__, exc)
```

### NotifyCollector for Run Summaries

When several decorated functions run in sequence and you want a single recap email at the end, pass a `NotifyCollector` to each decorator. Capture is filtered: it follows the active mode of the decorator that records it, so the same execution never gets recorded twice when several decorators share a collector.

```python
from kstlib.mail import MailBuilder, NotifyCollector

collector = NotifyCollector(maxsize=500)

mlok = MailBuilder(transport=t).sender("bot@x.com").to("users@x.com").subject("OK group")
mlko = MailBuilder(transport=t).sender("bot@x.com").to("admins@x.com").subject("KO group")

@mlok.notify(collector=collector, mode="ok")
@mlko.notify(collector=collector, mode="ko")
def check_proxy() -> None: ...

@mlok.notify(collector=collector, mode="ok")
@mlko.notify(collector=collector, mode="ko")
def check_database() -> None: ...

# Run the checks
for fn in (check_proxy, check_database):
    try:
        fn()
    except Exception:
        pass  # the relevant decorator already mailed admins

# Final summary mail
mail = MailBuilder(transport=t).sender("bot@x.com").to("ops@x.com").subject("Run recap")
mail.send_summary(collector, format="html")
```

`NotifyCollector` is thread-safe (`threading.Lock`) and bounded (`collections.deque(maxlen=maxsize)`, FIFO eviction).

```{admonition} Default redaction of user-code data (v2.5.0)
:class: warning

Since v2.5.0 the collector defaults to ``redact_user_data=True``. The
Detail column rendered by ``render_html`` / ``render_plain`` /
``to_monitor_table`` shows the exception **type** but masks the
exception **message**, return values, and tracebacks with the
placeholder ``[REDACTED] (NotifyCollector(redact_user_data=False) to
view)``. The traceback block in
``render_html(include_tracebacks=True)`` is suppressed entirely while
this flag is on.

Pass ``NotifyCollector(redact_user_data=False)`` to opt into the
legacy verbatim behaviour. Only do so when you control the decorated
functions and have ensured they never raise with sensitive content,
never return objects whose ``repr()`` exposes secrets, and never
embed user data in their tracebacks. See
{doc}`../../security/user-responsibility` for the broader contract.

The flag is also surfaced as ``ctx["redact_user_data"]`` by
``to_context()`` so custom Jinja templates can branch on it.
```

Available helpers:

| Method / property | Returns | Use case |
|-------------------|---------|----------|
| `add(result)` | `None` | Manual capture (called automatically by `notify`) |
| `reset()` | `None` | Clear every recorded entry |
| `results` | `list[NotifyResult]` | Snapshot copy in insertion order |
| `ok_count` / `ko_count` / `total_count` | `int` | Derived counters |
| `render_html(include_tracebacks=True)` | `str` | Standalone HTML table with inline CSS |
| `render_plain()` | `str` | Plain text summary |
| `to_monitor_table()` | `MonitorTable` | Integration with `kstlib.monitoring` |
| `to_context()` | `dict[str, Any]` | Context dict for an external Jinja template |

### `send_summary` Shortcut

`MailBuilder.send_summary(collector, format=...)` is a convenience that builds the summary email body from the collector and sends it in a single call. Available formats:

| `format` | Body source |
|----------|-------------|
| `"html"` (default) | `collector.render_html()` |
| `"plain"` | `collector.render_plain()` |
| `"monitor_table"` | `collector.to_monitor_table().render(inline_css=True)` |

The original builder state is preserved: `send_summary` operates on an internal snapshot, so subsequent `.send()` calls keep the original subject and body.

For a custom template, bypass `send_summary` and feed `collector.to_context()` to `MailBuilder.message`:

```python
mail.message(template="my_summary.j2", placeholders=collector.to_context()).send()
```

### `to_context()` keys

The dict returned by `collector.to_context()` exposes the following keys to Jinja2 templates:

| Key | Type | Description |
|-----|------|-------------|
| `results` | `list[NotifyResult]` | Recorded results in insertion order |
| `ok_count` | `int` | Number of successful results |
| `ko_count` | `int` | Number of failed results |
| `total_count` | `int` | Total number of results |
| `ok_ratio` | `float` | Ratio OK / total (0.0 to 1.0; 0.0 if empty) |
| `started_at` | `datetime \| None` | Min of all `started_at`; `None` if empty |
| `ended_at` | `datetime \| None` | Max of all `ended_at`; `None` if empty |
| `total_duration_ms` | `float` | Sum of all `duration_ms` |

Each item in `results` is a `NotifyResult` instance with attributes: `function_name`, `success`, `started_at`, `ended_at`, `duration_ms`, `return_value`, `exception`, `traceback_str` (cf API reference).

### Custom Jinja2 templates with NotifyCollector

`MailBuilder.message(template=...)` renders templates with **real Jinja2** (loops, conditions, filters, attribute access). Combined with `collector.to_context()`, you can write a custom recap that iterates over `results`:

```python
from kstlib.mail import MailBuilder, NotifyCollector

collector = NotifyCollector(maxsize=500)

@mail.notify(collector=collector)
def check_proxy(): ...

@mail.notify(collector=collector)
def check_database(): ...

# ... run checks ...

# Inline Jinja2 template with loop on results
template = """
<h1>Run summary</h1>
<p>OK: {{ ok_count }} / {{ total_count }}
   ({{ "%.0f" | format(ok_ratio * 100) }}%)</p>

<table>
  <tr><th>Function</th><th>Status</th><th>Duration (ms)</th></tr>
  {% for r in results %}
  <tr style="background:{{ '#dcfce7' if r.success else '#fee2e2' }}">
    <td><code>{{ r.function_name }}</code></td>
    <td>{{ "OK" if r.success else "FAILED" }}</td>
    <td>{{ "%.2f" | format(r.duration_ms) }}</td>
  </tr>
  {% endfor %}
</table>
"""

recap = MailBuilder(transport=t).sender("bot@x.com").to("ops@x.com").subject("Run recap")
recap.message(
    content=template,
    content_type="html",
    placeholders=collector.to_context(),
).send()

# Or using a template file:
recap.message(
    template="path/to/summary.j2",
    placeholders=collector.to_context(),
).send()
```

Missing variables resolve to an empty string (Jinja2 `ChainableUndefined`), keeping templates forgiving toward optional fields.

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
| `SesTransport` | AWS SES delivery backend (`pip install kstlib[ses]`) |
| `ResendTransport` | Resend.com API delivery backend |
| `GmailTransport` | Gmail API delivery backend (OAuth2) |
