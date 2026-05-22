# Logging introspection guide

This guide explains how kstlib uses Python logging internally and how
operators can tune the verbosity for their own needs without touching
the application code.

## Two distinct channels

kstlib distinguishes two concerns that often get conflated:

| Channel | Audience | Configured via | Default state |
|---|---|---|---|
| **Multi-flag CLI verbosity** (`-v` / `-vv` / `-vvv`) | The user running `kstlib <command>` interactively | CLI flags only, ad-hoc per invocation | OFF |
| **Logging introspection** (this guide) | Operators investigating *how kstlib itself* behaves | `kstlib.conf.yml` cascade + `--log-module` flag | OFF (opt-in) |

The two channels are **not mapped onto each other**. Adding `-vvv` does
not flip kstlib internal logs to TRACE, and conversely turning on the
internal logger never affects the user-facing CLI output. Each channel
serves its own purpose:

- The CLI verbosity controls whether the `kstlib rapi`, `kstlib auth
  status`, etc. command prints extra output to stdout.
- The introspection logger controls how chatty the kstlib library is
  when *another application* embeds it.

If you want to debug the library, configure the introspection channel.
If you want more output from a specific command, use `-v` / `-vv` /
`-vvv`.

## The 7-level convention

kstlib extends the stdlib logging levels with two custom levels
(`TRACE` below DEBUG, `SUCCESS` between INFO and WARNING):

| Level | Numeric | When to use it | Verbosity |
|---|---|---|---|
| **TRACE** | 5 | Detailed diagnostic (URL, body, headers, internals, per-item in a loop) | Firehose |
| **DEBUG** | 10 | Branch / decision / internal state (cascade resolved, preset selected, per-batch summary) | Synthesis |
| **INFO** | 20 | Important business operation completed, **rare** (config loaded, mail sent, pipeline started/ended) | Sparse |
| **SUCCESS** | 25 | Visible confirmation of a successful tool operation (export complete, package downloaded) | Reserved for terminal user-facing wins |
| **WARNING** | 30 | Non-blocking anomaly: deprecated, fallback, ssl_verify=false, validation rejection | Mandatory |
| **ERROR** | 40 | Operation failure: 4xx/5xx, file not found, blocking validation | Mandatory |
| **CRITICAL** | 50 | Unexpected systemic failure: corruption, deadlock, OOM | Mandatory |

INFO and SUCCESS are spent sparingly: every kstlib INFO line answers
the question "what user-visible business event just happened?" and not
"what step of the algorithm did we just take?".

## The `kstlib.logging.modules` cascade

kstlib loggers follow `kstlib.<sub-package>[.<module>]`, mirroring the
layout of `src/kstlib/`. You can override the level of any logger
through the `modules` map.

### Cascade priority

```text
                  kstlib.conf.yml                       CLI

   +------------------+   +------------------------+   +-----------+
   | kstlib.logging.  |   | logger.presets         |   | --log-    |
   | modules          |-> | .<active>.modules      |-> | module    |
   | (global default) |   | (preset override)      |   | (replace) |
   +------------------+   +------------------------+   +-----------+
        layer 1                  layer 2                  layer 3
        merge by key             wins on conflict         total override
```

- **Layer 1** is the global default applied for every preset.
- **Layer 2** is keyed on the active preset and *overrides* layer 1
  for shared module names.
- **Layer 3** is the CLI flag `--log-module`, repeatable. When at least
  one `--log-module` is supplied it **replaces** the YAML-resolved map
  entirely (no merge). See [CLI module overrides](#cli-module-overrides)
  for the three accepted syntaxes.

#### Module mutes are persistent by design

Verbosity flags (`-v` / `-vv` / `-vvv` or `--log-level`) only adjust the
**root handler level**. They do **not** reset the YAML modules cascade.
That is intentional : the embedded defaults mute precisely the loggers
that would otherwise drown the output the user is trying to read (cf
[Default-muted verbose modules](#default-muted-verbose-modules) below).

To bypass a specific mute under verbosity, use `--log-module` :

```bash
# Default: kstlib.rapi.config and kstlib.config.loader stay at WARNING
kstlib -vvv rapi list

# Raise rapi.config to TRACE for this command only
kstlib -vvv --log-module rapi.config=TRACE rapi list

# Raise multiple modules at once via inverse syntax
kstlib -vvv --log-module TRACE=rapi.config,config.loader rapi list
```

### CLI module overrides

The `--log-module` flag is repeatable and accepts three syntaxes :

| Syntax | Example | Notes |
|---|---|---|
| Classic, fully-qualified | `--log-module kstlib.rapi.config=TRACE` | Backward-compatible, exact match. |
| Classic, prefix omitted | `--log-module rapi.config=TRACE` | `kstlib.` is auto-prepended. |
| Inverse, level groups list | `--log-module DEBUG=foo.bar,baz.qux` | Level on the LEFT, comma-separated module list on the RIGHT. |

Mode is decided on the LEFT side : a known level token (case-insensitive)
triggers inverse mode, anything else is treated as a module name. Levels
recognized : `TRACE`, `DEBUG`, `INFO`, `SUCCESS`, `WARNING`, `ERROR`,
`CRITICAL`.

Repeated `--log-module` flags accumulate. When the same logger appears
twice, the last value wins.

### Validation

- Logger names must match `kstlib.<component>[.<component>...]` after the
  optional auto-prepend, where each component is alphanumeric plus
  underscore. Malformed names (double dots, leading dot, embedded space
  or punctuation) emit a `WARNING [SECURITY]` and are skipped. You
  cannot configure loggers outside the `kstlib.` hierarchy.
- Levels must be one of `TRACE`, `DEBUG`, `INFO`, `SUCCESS`, `WARNING`,
  `ERROR`, `CRITICAL` (case-insensitive). Unknown levels emit a
  `WARNING` and are skipped.
- Validation never aborts the bootstrap or the CLI command : a typo in
  one entry leaves the rest of the configuration applied. Warnings are
  emitted on the `kstlib_logging_internal` logger, which you can
  observe via `logging.getLogger("kstlib_logging_internal").setLevel(logging.WARNING)`.

## Built-in presets

| Preset | `output` | console level | file level | Use case |
|---|---|---|---|---|
| `dev` | `console` | DEBUG | (n/a) | Everyday iteration. No file I/O, fast feedback. |
| `prod` | `file` | WARNING | INFO | Production deployment, persistent, quiet console. |
| `debug` | `both` | TRACE | TRACE | Investigation session. Logs survive the terminal. |
| `trace` | `both` | TRACE | TRACE | Legacy alias of debug; kept for backward compatibility. |
| `trace_mail` | `both` | WARNING | TRACE | Verbose SMTP/SSL debugging to a dedicated file. |

Activate a preset at startup:

```yaml
# kstlib.conf.yml
kstlib:
  logging:
    enabled: true
    preset: dev
```

Or programmatically:

```python
from kstlib.logging import init_logging

init_logging(preset="debug")
```

### Caller context in `debug` and `trace` presets

For post-mortem incident debugging, the `debug` and `trace` presets enrich the file handler format with caller location :

```text
[2026-05-20 14:30:15 | INFO    ] ::: PID 1234 / TID 5678 ::: [manager.py:1115 close] WebSocket closed gracefully (reconnect possible)
```

The `[%(filename)s:%(lineno)d %(funcName)s]` segment is added only to the **file handler** format. Console output preserves the Rich `show_path: true` visual rendering, avoiding visual duplication.

Other presets (`dev`, `prod`, `trace_mail`) are **not affected** so clean production logs are preserved.

#### Why

When investigating an incident from log files (no live terminal), seeing the caller location helps trace the exact code path that emitted each log record. Useful for diagnosing unexpected lifecycle transitions (e.g., who called `force_close()`, which `receive_loop` emitted the warning) or post-mortem reconstruction of a multi-task asyncio sequence.

## Recipes

### Default-muted verbose modules

Two loggers are muted to `WARNING` in the embedded
`src/kstlib/kstlib.conf.yml` so they stay quiet out of the box, even
when a consumer activates `enabled: true` with the `dev` or `debug`
preset:

| Logger | Why it is muted by default |
|---|---|
| `kstlib.rapi.config` | Emits one TRACE line per endpoint plus DEBUG per defaults / includes / merge step. ~1300 records on a typical SAS Viya install. |
| `kstlib.config.loader` | Verbose cascade trace (defaults / user / preset merge) that grows with the number of `include:` patterns. |

These defaults are baseline only: they can be raised when you actually
need to debug those subsystems. The cascade gives you three override
surfaces, ordered by scope:

1. **Per-environment** : drop a matching key in your user
   `kstlib.conf.yml`. The user value deep-merges with the embedded
   defaults, so you can flip a single module without restating the
   rest:

   ```yaml
   kstlib:
     logging:
       enabled: true
       preset: dev
       modules:
         kstlib.rapi.config: DEBUG    # raises only this one
         # kstlib.config.loader stays at the default WARNING
   ```

2. **Per-preset** : narrow the scope of an override to a single preset,
   so it only kicks in when that preset is active:

   ```yaml
   logger:
     presets:
       debug:
         modules:
           kstlib.rapi.config: TRACE
   ```

3. **Per-invocation (CLI `--log-module`)** : the `--log-module` flag
   **replaces** the YAML `modules` map for the duration of the
   command. Use it to probe a single subsystem without touching any
   config file. All three syntaxes are accepted :

   ```bash
   # Fully-qualified
   kstlib --log-module kstlib.rapi.config=DEBUG rapi list

   # Prefix omitted (kstlib. auto-prepended)
   kstlib --log-module rapi.config=DEBUG rapi list

   # Inverse: one level, multiple modules
   kstlib --log-module DEBUG=rapi.config,config.loader rapi list
   ```

   Verbosity flags do **not** reset these mutes. To widen what you see
   under `-vvv`, name the modules explicitly :

   ```bash
   # Default: rapi.config and config.loader stay at WARNING
   kstlib -vvv rapi list

   # Bypass both mutes for this command only
   kstlib -vvv --log-module TRACE=rapi.config,config.loader rapi list
   ```

To bring everything back to the embedded defaults, omit the `modules`
key from your user config and don't pass any `--log-module` flag.

### Behavior matrix

| Command | Handler level | `kstlib.rapi.config` logger level | Net effect |
|---|---|---|---|
| `kstlib rapi list` | WARNING | WARNING (YAML default) | Quiet, only WARNINGs surface. |
| `kstlib -vvv rapi list` | TRACE | WARNING (YAML default, **persistent**) | TRACE everywhere except the muted modules ; `rapi.config` stays quiet. |
| `kstlib -vvv --log-module rapi.config=TRACE rapi list` | TRACE | TRACE (explicit override) | Full TRACE on `rapi.config` plus the rest of the kstlib hierarchy. |
| `kstlib --log-module rapi.config=DEBUG rapi list` | WARNING | DEBUG | Logger lets DEBUG through, but the handler is still at WARNING : nothing visible until you also pass a verbosity flag. |
| `kstlib -vvv --log-module rapi.config=WARNING rapi list` | TRACE | WARNING (explicit) | TRACE everywhere except `rapi.config` (kept at WARNING by the explicit override). |

### Investigate a pipeline run

Switch to the `debug` preset for the duration of the run. It enables
TRACE on both console and a rotating file, so you keep a record of
the run after the terminal closes:

```yaml
kstlib:
  logging:
    enabled: true
    preset: debug
```

Or one-shot from the CLI:

```bash
kstlib --log-level TRACE --log-file pipeline run morning-report
```

### Production : quiet by default, but watch for auth issues

```yaml
kstlib:
  logging:
    enabled: true
    preset: prod
    modules:
      kstlib.auth: WARNING
      # Crank kstlib.auth to ERROR if even WARNINGs are too chatty :
      # kstlib.auth: ERROR
```

The `prod` preset writes to a file at INFO and keeps the console at
WARNING. The `modules` override pushes auth-specific events down to
WARNING (or ERROR) without affecting the rest of the library.

### Per-invocation override from the CLI

```bash
kstlib --log-module kstlib.rapi.client=TRACE rapi call viya.list_jobs
```

The `--log-module` flag is repeatable and **replaces** any
`kstlib.logging.modules` entries from the YAML. Use it to probe a
single subsystem without editing config files.

## Sanitization

The convention reserves several patterns for never letting secrets
reach a log line, summarized below:

| Pattern | Purpose |
|---|---|
| `field(repr=False)` on dataclass fields | Never expose secrets in `repr()` |
| `_shared.redaction.redact_sensitive` | Regex-based redaction on stderr / 3rd-party error messages |
| `_shared.redaction.mask_webhook_url` | Slack / Discord / Teams webhook URL masking |
| `_shared.redaction.mask_url` | Generic URL userinfo + sensitive query parameter redaction |
| `[SECURITY]` tag on WARNING | Surface security events (path traversal, null byte, etc.) for SOC |
| Custom `__repr__` on transports | Hide credentials in mail / alerts transport repr |
| `_sanitize_command()` | Best-effort redaction of shell command lines |
| Type-only exception messages | `f"Invalid (type={type(x).__name__})"` rather than embedding the value |

## `HTTPTraceLogger` for httpx clients

`kstlib.utils.http_trace.HTTPTraceLogger` is the official infrastructure
to add HTTP TRACE logging to an httpx-based client without leaking
credentials. It hooks into httpx event hooks and applies redaction on
request bodies (against `DEFAULT_SENSITIVE_KEYS` covering `client_secret`,
`code`, `refresh_token`, `access_token`, `code_verifier`, `password`,
`api_key`, `secret`, `token`) and on response bodies (truncated to a
configurable max length).

```python
import httpx
import logging
from kstlib.utils.http_trace import HTTPTraceLogger

log = logging.getLogger(__name__)
tracer = HTTPTraceLogger(log)

client = httpx.Client(
    event_hooks={
        "request": [tracer.on_request],
        "response": [tracer.on_response],
    }
)
```

Already adopted by `kstlib.auth.providers.oauth2`. Other modules
(notably `kstlib.rapi.client`) are progressively switching to the same
helper rather than rolling their own redaction.

## See also

- {doc}`index` - logging API quick start
- {doc}`../../security/user-responsibility` - data fields users must
  vet themselves
