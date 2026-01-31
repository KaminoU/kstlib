# Examples Gallery

Browse runnable examples organized by module. Each example demonstrates practical usage patterns.

```{tip}
All examples are standalone scripts. Run them with `python examples/<module>/<script>.py`

Some examples include **real API credentials** protected by SOPS encryption.
See `examples/mail/` for a working demo with auto-decrypted secrets.
```

---

:::{dropdown} alerts - Multi-channel alerting

Slack, Email, throttling, level filtering, and channel targeting.

| Example | Description |
|---------|-------------|
| [email_basic.py](https://github.com/KaminoU/kstlib/blob/main/examples/alerts/email_basic.py) | Email alerts via SMTP |
| [slack_basic.py](https://github.com/KaminoU/kstlib/blob/main/examples/alerts/slack_basic.py) | Slack with channel targeting (key/alias) and batch sending |
| [multi_channel.py](https://github.com/KaminoU/kstlib/blob/main/examples/alerts/multi_channel.py) | Multi-channel AlertManager with level-based filtering |
| [kstlib.conf.yml](https://github.com/KaminoU/kstlib/blob/main/examples/alerts/kstlib.conf.yml) | Config with SOPS credentials and channel aliases |

```bash
cd examples/alerts

# Single channel via environment variable
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/T.../B.../xxx"
python slack_basic.py

# Multi-channel with SOPS credentials (config-driven)
python slack_basic.py --sops
```

**Channel Targeting** - target by config key or alias:

```python
await manager.send(alert, channel="hb")         # By config key
await manager.send(alert, channel="heartbeat")   # By alias
await manager.send(alert)                        # Broadcast
```

**Batch Sending** - multiple alerts in one call:

```python
alerts = [
    AlertMessage(title="Alert 1", body="...", level=AlertLevel.WARNING),
    AlertMessage(title="Alert 2", body="...", level=AlertLevel.WARNING),
]
results = await manager.send(alerts, channel="watchdog")
```

**Timestamp Prefix** - add send datetime to alert titles:

```python
alert = AlertMessage(
    title="Heartbeat Check",
    body="System is healthy",
    level=AlertLevel.INFO,
    timestamp=True,  # Adds "2026-01-21 17:30:45 ::: " prefix
)
```

```{note}
The `slack_basic.py` example demonstrates **SOPS auto-decrypt** for webhook URLs.
Run from `examples/alerts/` directory for config auto-discovery.
```
:::

:::{dropdown} auth - Authentication and OAuth2/OIDC

Keycloak and Google OAuth2 providers with SOPS token storage.

**Google OAuth2** - two approaches to the same flow:

| Example | Description |
|---------|-------------|
| [oauth2_google.py](https://github.com/KaminoU/kstlib/blob/main/examples/auth/oauth2_google.py) | **Production** - kstlib.auth with TRACE logging (`--trace`) |
| [oauth2_manual_google.py](https://github.com/KaminoU/kstlib/blob/main/examples/auth/oauth2_manual_google.py) | **Educational** - httpx direct, see OAuth2 "under the hood" |

```bash
cd examples/auth

# Production approach (~60 lines)
python oauth2_google.py your-email@gmail.com
python oauth2_google.py your-email@gmail.com --trace  # HTTP details

# Educational approach (~400 lines, explicit HTTP calls)
python oauth2_manual_google.py your-email@gmail.com
```

```{note}
Both examples use **SOPS-encrypted token storage** in `tokens/`. Tokens persist across runs
and are automatically refreshed when expired. The token format is compatible between both examples.
```

**Keycloak Providers:**

| File | Description |
|------|-------------|
| [README.md](https://github.com/KaminoU/kstlib/blob/main/examples/auth/README.md) | Setup instructions and usage guide |
| [kstlib.conf.yml](https://github.com/KaminoU/kstlib/blob/main/examples/auth/kstlib.conf.yml) | Main config with provider includes |

Provider configs (`providers/`):

| Config | Description |
|--------|-------------|
| [oauth2-keycloak-dev.yml](https://github.com/KaminoU/kstlib/blob/main/examples/auth/providers/oauth2-keycloak-dev.yml) | Manual endpoints + file storage |
| [oidc-hybrid-keycloak.yml](https://github.com/KaminoU/kstlib/blob/main/examples/auth/providers/oidc-hybrid-keycloak.yml) | Hybrid mode + file storage |
| [oidc-keycloak-dev.yml](https://github.com/KaminoU/kstlib/blob/main/examples/auth/providers/oidc-keycloak-dev.yml) | Auto-discovery OIDC + SOPS storage |
:::

:::{dropdown} cache - Caching decorators

TTL, LRU, and file-backed caching strategies.

| Example | Description |
|---------|-------------|
| [basic_usage.py](https://github.com/KaminoU/kstlib/blob/main/examples/cache/basic_usage.py) | TTL cache decorator basics |
:::

:::{dropdown} config - Configuration loading

Cascading search, includes, and environment variables.

| Example | Description |
|---------|-------------|
| [01_basic_usage.py](https://github.com/KaminoU/kstlib/blob/main/examples/config/01_basic_usage.py) | Load config from file |
| [02_includes.py](https://github.com/KaminoU/kstlib/blob/main/examples/config/02_includes.py) | YAML includes and merging |
| [03_cascading_search.py](https://github.com/KaminoU/kstlib/blob/main/examples/config/03_cascading_search.py) | Search paths and auto-discovery |
| [04_env_variable.py](https://github.com/KaminoU/kstlib/blob/main/examples/config/04_env_variable.py) | Environment variable substitution |
| [05_strict_format.py](https://github.com/KaminoU/kstlib/blob/main/examples/config/05_strict_format.py) | Strict YAML format validation |
| [06_error_handling.py](https://github.com/KaminoU/kstlib/blob/main/examples/config/06_error_handling.py) | Error handling patterns |
| [07_deep_merge.py](https://github.com/KaminoU/kstlib/blob/main/examples/config/07_deep_merge.py) | Deep merge strategies |
| [08_multi_environment.py](https://github.com/KaminoU/kstlib/blob/main/examples/config/08_multi_environment.py) | Multi-environment setup |
| [09_auto_discovery.py](https://github.com/KaminoU/kstlib/blob/main/examples/config/09_auto_discovery.py) | Auto-discovery of config files |
| [run_all_examples.py](https://github.com/KaminoU/kstlib/blob/main/examples/config/run_all_examples.py) | Run all config examples |
:::

:::{dropdown} db - Async SQLite database

Connection pooling and SQLCipher encryption.

| Example | Description |
|---------|-------------|
| [01_siren_sqlite_demo.py](https://github.com/KaminoU/kstlib/blob/main/examples/db/01_siren_sqlite_demo.py) | In-memory SQLite for CSV analytics |
| [02_encrypted_sqlite_demo.py](https://github.com/KaminoU/kstlib/blob/main/examples/db/02_encrypted_sqlite_demo.py) | SQLCipher encrypted database |
:::

:::{dropdown} logging - Logging presets

Rich console, file rotation, and structlog integration.

| Example | Description |
|---------|-------------|
| [basic_usage.py](https://github.com/KaminoU/kstlib/blob/main/examples/logging/basic_usage.py) | Setup logging with presets |
:::

:::{dropdown} mail - Email builder

Templates, attachments, and multiple transport options.

| Example | Description |
|---------|-------------|
| [basic_plain.py](https://github.com/KaminoU/kstlib/blob/main/examples/mail/basic_plain.py) | Plain text email |
| [html_template.py](https://github.com/KaminoU/kstlib/blob/main/examples/mail/html_template.py) | HTML with Jinja templates |
| [attachments_inline.py](https://github.com/KaminoU/kstlib/blob/main/examples/mail/attachments_inline.py) | Attachments and inline images |
| [notify_decorator.py](https://github.com/KaminoU/kstlib/blob/main/examples/mail/notify_decorator.py) | **@mail.notify()** decorator for job notifications |
| [smtp_ethereal.py](https://github.com/KaminoU/kstlib/blob/main/examples/mail/smtp_ethereal.py) | SMTP transport with Ethereal fake service |
| [gmail_send.py](https://github.com/KaminoU/kstlib/blob/main/examples/mail/gmail_send.py) | Gmail OAuth2 transport |
| [resend_send.py](https://github.com/KaminoU/kstlib/blob/main/examples/mail/resend_send.py) | Resend API async transport |
| [smtp_trace.py](https://github.com/KaminoU/kstlib/blob/main/examples/mail/smtp_trace.py) | TRACE logging for SMTP debugging |
| [kstlib.conf.yml](https://github.com/KaminoU/kstlib/blob/main/examples/mail/kstlib.conf.yml) | Config with SOPS include |
| [mail.conf.sops.yml](https://github.com/KaminoU/kstlib/blob/main/examples/mail/mail.conf.sops.yml) | Encrypted Resend API key |

**@mail.notify() Decorator** - automatic email notifications for function execution:

```python
from kstlib.mail import MailBuilder
from kstlib.mail.transports import SMTPTransport

transport = SMTPTransport(host="smtp.example.com", port=587)
mail = (
    MailBuilder(transport=transport)
    .sender("bot@example.com")
    .to("admin@example.com")
    .subject("ETL Job")
)

@mail.notify
def extract_data() -> dict[str, int]:
    """Extract data from source."""
    return {"rows": 1000}

# Sends "[OK] ETL Job - extract_data" on success
# Sends "[FAILED] ETL Job - extract_data" with traceback on failure
result = extract_data()
```

| Option | Description |
|--------|-------------|
| `subject="..."` | Override the base subject |
| `on_error_only=True` | Only send notification on failure |
| `include_return=True` | Include return value in email body |
| `include_traceback=False` | Exclude traceback from failure emails |

```{note}
The `notify_decorator.py` example uses **Ethereal Email** for safe testing.
Create a free account at https://ethereal.email and set `ETHEREAL_USER` and `ETHEREAL_PASS`.
```

```{note}
The `resend_send.py` example demonstrates **SOPS auto-decrypt** with real API credentials.
The API key in `mail.conf.sops.yml` is encrypted and automatically decrypted by the config loader.
Run `python resend_send.py you@example.com` to test (requires matching age key).
```
:::

:::{dropdown} metrics - Unified metrics decorator

Timing, profiling, and call statistics.

| Example | Description |
|---------|-------------|
| [01_decorators_demo.py](https://github.com/KaminoU/kstlib/blob/main/examples/metrics/01_decorators_demo.py) | @metrics decorator with timing, profiling, and statistics |
:::

:::{dropdown} monitoring - HTML dashboards and reports

Typed render types, Jinja2 integration, `@collector` decorators, and email delivery.

| Example | Description |
|---------|-------------|
| [service_dashboard.py](https://github.com/KaminoU/kstlib/blob/main/examples/monitoring/service_dashboard.py) | Render types demo with StatusCell, MonitorTable, MonitorKV |
| [send_dashboard_gmail.py](https://github.com/KaminoU/kstlib/blob/main/examples/monitoring/send_dashboard_gmail.py) | Send dashboard via Gmail with SOPS credentials |
| [server/run.py](https://github.com/KaminoU/kstlib/blob/main/examples/monitoring/server/run.py) | **Simplified API** with `@mon.collector` decorators |
| [server/server.monitor.yml](https://github.com/KaminoU/kstlib/blob/main/examples/monitoring/server/server.monitor.yml) | YAML config (template, delivery) |

**Simplified API** - config in YAML, collectors in Python:

```python
from kstlib.monitoring import Monitoring, MonitorKV, StatusCell, StatusLevel

mon = Monitoring.from_config()  # Load from kstlib.conf.yml

@mon.collector
def system_info():
    return MonitorKV(items={
        "Hostname": platform.node(),
        "CPU": StatusCell(f"{cpu}%", StatusLevel.OK),
    })

@mon.collector
def services():
    table = MonitorTable(headers=["Service", "Status"])
    table.add_row(["API", StatusCell("UP", StatusLevel.OK)])
    return table

mon.run_sync()  # Collect, render, deliver
```

**Render Types** - typed cells with automatic styling:

```python
from kstlib.monitoring import (
    StatusCell, StatusLevel,
    MonitorTable, MonitorKV,
    render_template,
)

# Create status badges
api_status = StatusCell("UP", StatusLevel.OK)
db_status = StatusCell("DEGRADED", StatusLevel.WARNING)

# Create a table
table = MonitorTable(headers=["Service", "Status"])
table.add_row(["API Gateway", api_status])
table.add_row(["Database", db_status])

# Render with Jinja2
html = render_template("""
<h1>System Status</h1>
{{ table | render }}
""", {"table": table})
```

**Email Delivery** - send dashboards via Gmail OAuth2:

```yaml
# kstlib.conf.yml
monitoring:
  template_file: dashboard.html
  inline_css: true
  delivery:
    type: mail
    sender: bot@example.com
    recipients: [team@example.com]
```

```bash
cd examples/monitoring/server
python run.py              # Send email
python run.py --no-send    # Save to file only
```

```{note}
Mail delivery requires Gmail OAuth2 token. Run `kstlib auth login google` first.
```
:::

:::{dropdown} ops - Unified session management

tmux and containers (Docker/Podman), config-driven via `kstlib.conf.yml`.

**Config-Driven Examples:**

| Folder | Description |
|--------|-------------|
| [config_driven/tmux/](https://github.com/KaminoU/kstlib/tree/main/examples/ops/config_driven/tmux) | tmux session from config |
| [config_driven/container/](https://github.com/KaminoU/kstlib/tree/main/examples/ops/config_driven/container) | Docker/Podman container from config |
| [config_driven/README.md](https://github.com/KaminoU/kstlib/blob/main/examples/ops/config_driven/README.md) | Lifecycle, auto-detect, CLI overrides |

**Resilience Test (Long-Running):**

| File | Description |
|------|-------------|
| [resilience_tmux/README.md](https://github.com/KaminoU/kstlib/blob/main/examples/ops/resilience_tmux/README.md) | Architecture and usage guide |
| [resilience_tmux/main.py](https://github.com/KaminoU/kstlib/blob/main/examples/ops/resilience_tmux/main.py) | Binance 1h candles + 4h proactive restart |
| [resilience_tmux/candle_logger.py](https://github.com/KaminoU/kstlib/blob/main/examples/ops/resilience_tmux/candle_logger.py) | CSV logger with gap analysis |
| [resilience_tmux/kstlib.conf.yml](https://github.com/KaminoU/kstlib/blob/main/examples/ops/resilience_tmux/kstlib.conf.yml) | Config with resilience + Slack alerts |

Components demonstrated:
`SessionManager`, `BinanceKlineStream`, `TimeTrigger("240m")`, `Heartbeat` + `StateWriter`,
`CandleLogger`, `AlertManager` with Slack, `GracefulShutdown`.

```bash
cd examples/ops/resilience_tmux

# Direct run (foreground)
python main.py

# Via kstlib ops (tmux session, detachable)
kstlib ops start resilience-tmux
kstlib ops attach resilience-tmux   # Ctrl+B D to detach
kstlib ops logs resilience-tmux
kstlib ops stop resilience-tmux
```

**CLI Quick Reference:**

```bash
kstlib ops start <name>              # Start from config
kstlib ops stop <name>               # Graceful stop
kstlib ops attach <name>             # Interactive attach
kstlib ops status <name> [--json]    # Session state
kstlib ops logs <name> [--lines 50]  # Recent output
kstlib ops list [--backend tmux]     # All sessions
```
:::

:::{dropdown} rapi - Config-driven REST API client

Define APIs in YAML, call from CLI or Python.

**Basic Examples:**

| Example | Description |
|---------|-------------|
| [01_httpbin_basics.py](https://github.com/KaminoU/kstlib/blob/main/examples/rapi/01_httpbin_basics.py) | Basic usage with httpbin.org (GET, POST, path params, headers) |
| [02_credentials_and_auth.py](https://github.com/KaminoU/kstlib/blob/main/examples/rapi/02_credentials_and_auth.py) | Credential resolver, Bearer/Basic auth |
| [03_error_handling.py](https://github.com/KaminoU/kstlib/blob/main/examples/rapi/03_error_handling.py) | HTTP errors, timeouts, retry behavior |

**External Config Examples** - real-world with `*.rapi.yml` config files:

| Folder | Description |
|--------|-------------|
| [binance/](https://github.com/KaminoU/kstlib/tree/main/examples/rapi/binance) | **Binance API** - HMAC signing, SOPS credentials, testnet |
| [github/](https://github.com/KaminoU/kstlib/tree/main/examples/rapi/github) | **GitHub API** - Real token via SOPS, `from_file()` demo |
| [httpbin/](https://github.com/KaminoU/kstlib/tree/main/examples/rapi/httpbin) | **httpbin.org** - External config, auto-discovery |

```bash
# Run the Binance demo (requires SOPS-encrypted API keys)
cd examples/rapi/binance
kstlib rapi binance.balance       # Account info (HMAC signed)
kstlib rapi binance.ticker-price  # Public endpoint (no auth)

# Run the GitHub demo (requires SOPS-encrypted token)
cd examples/rapi/github
python demo.py
```

**CLI Examples:**

```bash
kstlib rapi list                                    # List endpoints
kstlib rapi github.user                             # Simple GET
kstlib rapi github.repos-issues owner=KaminoU repo=igcv3  # Path params
kstlib rapi github.repos-list per_page=50 page=2    # Query params
kstlib rapi myapi.create -b '{"user": "alice"}'     # POST with JSON
kstlib rapi myapi.create -b @data.json              # Body from file
kstlib rapi github.user -o user.json                # Output to file
kstlib -vvv rapi github.user                        # TRACE mode
```
:::

:::{dropdown} resilience - Fault tolerance patterns

Circuit breaker, graceful shutdown, heartbeat, rate limiter, and watchdog.

| Example | Description |
|---------|-------------|
| [01_circuit_breaker.py](https://github.com/KaminoU/kstlib/blob/main/examples/resilience/01_circuit_breaker.py) | Circuit breaker pattern with state machine |
| [02_graceful_shutdown.py](https://github.com/KaminoU/kstlib/blob/main/examples/resilience/02_graceful_shutdown.py) | Priority-based shutdown callbacks |
| [03_heartbeat.py](https://github.com/KaminoU/kstlib/blob/main/examples/resilience/03_heartbeat.py) | Process liveness signaling |
| [04_rate_limiter.py](https://github.com/KaminoU/kstlib/blob/main/examples/resilience/04_rate_limiter.py) | Token bucket rate limiting |
| [05_watchdog.py](https://github.com/KaminoU/kstlib/blob/main/examples/resilience/05_watchdog.py) | Thread/process freeze detection |

**binance_testnet/** - complete real-world integration for a Binance WebSocket bot:

| File | Description |
|------|-------------|
| [README.md](https://github.com/KaminoU/kstlib/blob/main/examples/resilience/binance_testnet/README.md) | Full documentation with architecture diagram |
| [main.py](https://github.com/KaminoU/kstlib/blob/main/examples/resilience/binance_testnet/main.py) | Main application with dashboard |
| [watchdog_service.py](https://github.com/KaminoU/kstlib/blob/main/examples/resilience/binance_testnet/watchdog_service.py) | External watchdog process |
| [kstlib.conf.yml](https://github.com/KaminoU/kstlib/blob/main/examples/resilience/binance_testnet/kstlib.conf.yml) | Configuration with includes |

Components demonstrated:
`Heartbeat` with `HeartbeatTarget`, `Watchdog.from_state_file()`, `TimeTrigger`,
`AlertManager` with `SlackChannel`, `WebSocketManager` with managed reconnection.

```bash
cd examples/resilience/binance_testnet
python main.py
```
:::

:::{dropdown} secrets - Secret resolution

SOPS encryption with AGE and AWS KMS backends.

**AGE Examples** (local encryption):

| Example | Description |
|---------|-------------|
| [decrypt_example.py](https://github.com/KaminoU/kstlib/blob/main/examples/secrets/decrypt_example.py) | Decrypt secrets with AGE |
| [decrypt_secure_example.py](https://github.com/KaminoU/kstlib/blob/main/examples/secrets/decrypt_secure_example.py) | Secure decryption patterns |
| [encrypt_example.py](https://github.com/KaminoU/kstlib/blob/main/examples/secrets/encrypt_example.py) | Encrypt secrets with SOPS |

**AWS KMS Examples** (production-grade encryption):

| Example | Description |
|---------|-------------|
| [kms/.sops.yaml](https://github.com/KaminoU/kstlib/blob/main/examples/secrets/kms/.sops.yaml) | SOPS config with real AWS KMS key |
| [kms/secrets.example.yml](https://github.com/KaminoU/kstlib/blob/main/examples/secrets/kms/secrets.example.yml) | Template for KMS-encrypted secrets |
| [kms/decrypt_example.py](https://github.com/KaminoU/kstlib/blob/main/examples/secrets/kms/decrypt_example.py) | Decrypt KMS-encrypted secrets |

```bash
# Decrypt via CLI (auto-detects KMS from sops metadata)
kstlib secrets decrypt examples/secrets/kms/secrets.sops.yml

# Or via Python
from kstlib.config.sops import decrypt_sops_file
secrets = decrypt_sops_file("secrets.sops.yml")
```

```{note}
The `kms/` examples use a **real production AWS KMS key** in `eu-west-3`.
This demonstrates enterprise-grade secret management with automatic key rotation
and IAM-based access control. Requires valid AWS credentials with KMS permissions.
```
:::

:::{dropdown} secure - Filesystem guardrails

Path validation and secure file operations.

| Example | Description |
|---------|-------------|
| [guardrails_demo.py](https://github.com/KaminoU/kstlib/blob/main/examples/secure/guardrails_demo.py) | Path validation and permission checks |
:::

:::{dropdown} ui - Rich-based UI components

Panels, spinners, and tables for terminal output.

**Panels:**

| Example | Description |
|---------|-------------|
| [panel_basic_usage.py](https://github.com/KaminoU/kstlib/blob/main/examples/ui/panel_basic_usage.py) | Panel presets and customization |

**Spinners** - animated feedback for CLI operations:

| Example | Description |
|---------|-------------|
| [01_basic_usage.py](https://github.com/KaminoU/kstlib/blob/main/examples/ui/spinner/01_basic_usage.py) | Context manager and manual control |
| [02_all_styles.py](https://github.com/KaminoU/kstlib/blob/main/examples/ui/spinner/02_all_styles.py) | Gallery of 9 spinner styles |
| [03_animation_types.py](https://github.com/KaminoU/kstlib/blob/main/examples/ui/spinner/03_animation_types.py) | Spin, bounce, and color wave |
| [04_presets.py](https://github.com/KaminoU/kstlib/blob/main/examples/ui/spinner/04_presets.py) | Built-in presets and overrides |
| [05_customization.py](https://github.com/KaminoU/kstlib/blob/main/examples/ui/spinner/05_customization.py) | Styling, position, speed |
| [06_with_logs.py](https://github.com/KaminoU/kstlib/blob/main/examples/ui/spinner/06_with_logs.py) | Logs scrolling above spinner |
| [07_decorator_and_zones.py](https://github.com/KaminoU/kstlib/blob/main/examples/ui/spinner/07_decorator_and_zones.py) | @with_spinner decorator + log zones |
| [run_all_examples.py](https://github.com/KaminoU/kstlib/blob/main/examples/ui/spinner/run_all_examples.py) | Run all spinner demos |

**Tables:**

| Example | Description |
|---------|-------------|
| [table_basic_usage.py](https://github.com/KaminoU/kstlib/blob/main/examples/ui/table_basic_usage.py) | Table builder with column config |
:::

---

## Running Examples

### Single example

```bash
python examples/resilience/01_circuit_breaker.py
python examples/ui/spinner/01_basic_usage.py
```

### All examples in a module

```bash
python examples/config/run_all_examples.py
python examples/ui/spinner/run_all_examples.py
```

### From project root with module syntax

```bash
python -m examples.ui.spinner.01_basic_usage
```
