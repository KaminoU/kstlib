# User responsibility

kstlib does not see and cannot redact every piece of data that flows
through its public APIs. Six surfaces let user-provided content reach a
log line, an email body, or a return value that the caller must vet.
This page documents each one so library users know what they own and
what kstlib already takes care of.

## Why this page exists

The v2.5.0 audit pass found that kstlib itself is now defensive on the
sanitization axis: secrets in transports / providers carry
`field(repr=False)`, dataclasses with sensitive payloads override
`__repr__`, and the four HIGH leak gaps (auth callback OAuth code,
WebSocket URL credentials, pipeline shell command, pipeline subprocess
stderr) were all closed. What kstlib **cannot** decide on its own is
whether the strings, exceptions, and return values you pass through its
APIs contain secrets. Those six cases below are the places where the
contract is shared.

When in doubt, the rule of thumb is **redact at the boundary you control**:
strip credentials from a message before it reaches the kstlib API, or
wrap user code with your own sanitizer. Treat any field listed below
as if it could land verbatim in a summary email or a DEBUG log.

---

## 1. NotifyCollector exception / return_value / traceback

Module: `kstlib.mail` ({mod}`kstlib.mail.NotifyCollector`,
{mod}`kstlib.mail.NotifyResult`)

The `@notify` decorator captures, for each decorated function call, the
return value, the exception (if raised), and the traceback. Those are
later rendered into the summary email by `NotifyCollector.render_html()`
/ `render_plain()` / `to_monitor_table()`.

### What kstlib does

Since v2.5.0 the collector defaults to `redact_user_data=True`. In that
mode the Detail column shows:

- For failures: `"<ExcType>: [REDACTED] (NotifyCollector(redact_user_data=False) to view)"`
- For successful return values: `"[REDACTED] ..."`
- The tracebacks block in `render_html(include_tracebacks=True)` is
  suppressed entirely, regardless of `include_tracebacks`.

`to_context()` surfaces `ctx["redact_user_data"]` so custom Jinja
templates can decide whether to render `{{ result.exception }}` or
`{{ result.traceback_str }}` directly. The raw `NotifyResult` objects
stay in `ctx["results"]` so existing template code keeps working.

### Where the user must care

Set `redact_user_data=False` only when **you** control the decorated
functions and know they:

- never raise with sensitive content in the exception message,
- never return objects whose `repr()` exposes a secret,
- never include credentials in their tracebacks.

```{admonition} Don't
:class: error

```python
from kstlib.mail import NotifyCollector

# Decorated function leaks a token in its exception message
@notify(collector=collector)
def fetch():
    raise ValueError(f"Auth failed for token={MY_TOKEN}")  # leak

# This collector renders the verbatim message in the summary email :
collector = NotifyCollector(redact_user_data=False)
```

```{admonition} Do
:class: tip

```python
# Default collector hides exception messages :
collector = NotifyCollector()  # redact_user_data=True

# Or sanitize the exception ourselves before re-raising :
@notify(collector=collector)
def fetch():
    try:
        ...
    except AuthError:
        raise ValueError("Auth failed (see provider logs)") from None
```

---

## 2. CallableError propagation in transform/

Module: `kstlib.transform` ({mod}`kstlib.transform.CallableError`,
{mod}`kstlib.transform.chain`)

A `transform.chain` whose YAML lists a `callable: my.module:fn` patch
imports and invokes that callable on each forward / patch / backward
step. If the callable raises, the chain wraps the exception in a
`CallableError(target_label, str(error_box[0]), chain_name=...)`. The
`str(error_box[0])` part is the user code's own exception message.

### What kstlib does

The exception type, the chain name, and the target label are kstlib
data. The exception **message** is forwarded as-is from your callable.

### Where the user must care

If your callable raises with a payload-derived message, that string
becomes the body of `CallableError` and bubbles up to whatever logger
or error handler the application uses.

```{admonition} Don't
:class: error

```python
def my_patch(data, **kwargs):
    if "bad" in data:
        # The first 200 chars of the payload now travel inside the
        # CallableError message.
        raise ValueError(f"Invalid payload: {data[:200]}")
```

```{admonition} Do
:class: tip

```python
def my_patch(data, **kwargs):
    if "bad" in data:
        raise ValueError(
            f"Invalid payload (length={len(data)}, type={type(data).__name__})"
        )
```

The pattern matches kstlib's own `transform/primitives.py`: exception
messages carry **type and size**, never content slices.

---

## 3. StepResult.stdout / StepResult.stderr in pipeline/

Module: `kstlib.pipeline` ({mod}`kstlib.pipeline.StepResult`)

A pipeline `ShellStep` / `PythonStep` returns a `StepResult` whose
`stdout` and `stderr` attributes contain the **complete** captured
output of the subprocess. `StepResult.error` is also populated with the
stripped stderr on failure.

### What kstlib does

Since v2.5.0 the failure WARNING dropped the stderr from the log
("Step '<name>' failed (rc=N). See StepResult.stderr for details (not
logged for safety)."). The full stderr is preserved on the result
object so the caller can inspect it deliberately.

### Where the user must care

If your pipeline definition runs `curl -u user:pass`, `psql -c "GRANT
TO ... IDENTIFIED BY 'pwd'"`, or any tool that echoes credentials in
its stderr, the secret is sitting in `result.stderr`. If you forward
that field to a logger, an email, or a dashboard, the secret follows.

```{admonition} Don't
:class: error

```python
result = step.execute(config)
if result.status is StepStatus.FAILED:
    log.error("Pipeline failed: %s", result.stderr)  # may leak
```

```{admonition} Do
:class: tip

```python
result = step.execute(config)
if result.status is StepStatus.FAILED:
    log.error("Pipeline step '%s' failed (rc=%d)", config.name, result.return_code)
    # Inspect result.stderr only in interactive debugging, not in
    # automated logs.
```

The same applies to `StepConfig.command` / `StepConfig.args`. Prefer
passing credentials via `StepConfig.env` rather than command-line
flags - the helper `_sanitize_command()` redacts known shapes
(`Authorization: Bearer ...`, `--password=...`, `sshpass -p ...`,
`PGPASSWORD=...`) before the DEBUG log, but it is best-effort and only
catches patterns it knows about.

---

## 4. NotifyResult fields surfaced to summary builders

Module: `kstlib.mail` ({mod}`kstlib.mail.NotifyResult`)

`NotifyResult` is the dataclass populated by the `@notify` decorator
for each call. It exposes `exception`, `return_value`, `traceback_str`,
`function_name`, `started_at`, `ended_at`, `duration_ms`, `success`.

### What kstlib does

`NotifyResult.exception` is the actual exception instance. Its default
`repr()` is the exception's own repr, which kstlib does not control.
`return_value` is your function's return - kstlib stores it as-is.
`traceback_str` is the formatted traceback string at decoration time.

The `NotifyCollector` rendering helpers respect the `redact_user_data`
flag (see #1), but **direct access** to a `NotifyResult` instance does
not - the dataclass remains a transparent record.

### Where the user must care

If you build a custom rendering pipeline (Jinja template, audit log,
Slack message) from a list of `NotifyResult`, you are responsible for
deciding which fields to surface. Treat `exception`, `return_value`,
and `traceback_str` as user-controlled.

```{admonition} Do
:class: tip

```python
# Custom Jinja template guarded by the collector's flag :
template = """
{% for r in results %}
  {{ r.function_name }} : {{ "OK" if r.success else "FAILED" }}
  {% if not redact_user_data and r.exception %}
    {{ r.exception }}
  {% endif %}
{% endfor %}
"""

context = collector.to_context()
rendered = jinja_env.from_string(template).render(**context)
```

---

## 5. AlertMessage title and body

Module: `kstlib.alerts` ({mod}`kstlib.alerts.AlertMessage`)

`AlertMessage(title, body, level, ...)` is the user-composed payload
delivered to channels (Slack, email, ...). The `title` is truncated to
50 characters before logging; the `body` is treated as the message you
want the channel to display.

### What kstlib does

`AlertManager.send(...)` truncates the title before logging, and
channels (`SlackChannel`, `EmailChannel`) use `mask_webhook_url()`
(Slack) or transport-level `__repr__` redaction (email transports) to
keep their own configuration out of the logs.

### Where the user must care

The body is by design what travels to the channel. If you build a body
that contains credentials, those credentials reach Slack / your inbox.
That is rarely a "secret" issue (you trust the channel) but it is one
when the channel is shared, archived, or forwarded.

```{admonition} Do
:class: tip

```python
alert = AlertMessage(
    title="Pipeline failure",
    body=(
        "step=publish-report\n"
        "rc=2\n"
        "logs: see CI run https://ci.example.com/run/12345\n"
    ),
    level=AlertLevel.WARNING,
)
```

Avoid embedding raw exception messages, full configs, or anything you
would not put in the channel's persistent history.

---

## 6. WebSocket on_message / on_error callbacks

Module: `kstlib.websocket` ({mod}`kstlib.websocket.WebSocketManager`)

`WebSocketManager` accepts `on_connect`, `on_message`, `on_disconnect`,
`on_error` callbacks. The data they receive (frame payload, close
reason, exception) is passed to user code unchanged.

### What kstlib does

Since v2.5.0 the connect log uses `mask_url()` to redact userinfo and
sensitive query parameters from `self._url`, and the close-frame
reason is split (short WARNING + redacted TRACE detail). The library
itself never logs the message payloads.

### Where the user must care

If your `on_message` does `log.debug("Received: %s", message)`, every
frame lands in your DEBUG stream. WebSocket frames from trading APIs
or chat services routinely include account ids, balances, or session
identifiers.

```{admonition} Do
:class: tip

```python
def on_message(message):
    # Process the structured payload, but log only what is safe to log.
    payload = json.loads(message)
    log.debug("Received frame: type=%s seq=%d", payload.get("type"), payload.get("seq"))

ws = WebSocketManager(url, on_message=on_message)
```

---

## See also

- {doc}`../features/logging/index` - the logging system itself
- {doc}`../features/logging/introspection-guide` - 7-level convention,
  cascade, recipes, and the 12 sanitization model patterns
  (`field(repr=False)`, helper redactions, `[SECURITY]` tag, the
  `HTTPTraceLogger` infrastructure).
