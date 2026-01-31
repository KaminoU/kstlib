# Alerts

Multi-channel alerting system with throttling, config-driven defaults, and deep defense hard limits.

## TL;DR

```python
import asyncio
from kstlib.alerts import AlertManager, AlertLevel
from kstlib.alerts.channels import SlackChannel, EmailChannel
from kstlib.alerts.models import AlertMessage
from kstlib.alerts.throttle import AlertThrottle

# Create channels
slack = SlackChannel(
    webhook_url="https://hooks.slack.com/services/T.../B.../xxx"
)
email = EmailChannel(
    transport=smtp_transport,
    sender="alerts@example.com",
    recipients=["oncall@example.com", "backup@example.com"],
)

# Setup manager with level filtering
manager = AlertManager()
manager.add_channel(slack, min_level=AlertLevel.WARNING)
manager.add_channel(email, min_level=AlertLevel.CRITICAL)

# Send alert
alert = AlertMessage(
    title="Database Connection Lost",
    body="Primary database unreachable for 30 seconds",
    level=AlertLevel.CRITICAL,
)
results = asyncio.run(manager.send(alert))
```

## Key Features

- **Multi-channel delivery**: Slack, Email (via kstlib.mail transports)
- **Level filtering**: INFO, WARNING, CRITICAL per channel
- **Rate limiting**: `AlertThrottle` prevents alert flooding
- **Config-driven**: Settings from `kstlib.conf.yml` with kwargs override
- **Deep defense**: Hard limits prevent misconfiguration
- **Async support**: All operations are async-first

## Configuration

Settings are read from `kstlib.conf.yml` under the `alerts` section:

```yaml
alerts:
  # Throttle settings (anti-spam)
  throttle:
    rate: 10        # Max alerts per period
    per: 60.0       # Period in seconds
    burst: 5        # Initial burst capacity

  # Channel defaults
  channels:
    timeout: 30.0      # HTTP timeout (seconds)
    max_retries: 2     # Retry attempts

  # Environment presets
  presets:
    dev:
      throttle:
        rate: 100       # More lenient for dev
        per: 60.0
        burst: 20

    prod:
      throttle:
        rate: 10        # Strict for production
        per: 60.0
        burst: 3
```

### Hard Limits (Deep Defense)

These cannot be exceeded even with explicit kwargs:

| Parameter | Min | Max | Notes |
|-----------|-----|-----|-------|
| `throttle.rate` | 1 | 1000 | Alerts per period |
| `throttle.per` | 1.0 | 86400.0 | Period duration (1 day max) |
| `channel.timeout` | 1.0 | 120.0 | HTTP timeout |
| `channel.max_retries` | 0 | 5 | Retry attempts |

## Quick Start

### AlertThrottle

Rate limiting for alert delivery. Config-driven with optional overrides:

```python
from kstlib.alerts.throttle import AlertThrottle

# Uses kstlib.conf.yml defaults
throttle = AlertThrottle()

# Override specific values
throttle = AlertThrottle(rate=5, per=30.0)

# Non-blocking check
if throttle.try_acquire():
    await channel.send(alert)
else:
    log.warning("Alert throttled")

# Blocking with timeout
try:
    throttle.acquire(timeout=5.0)
    await channel.send(alert)
except AlertThrottledError as e:
    log.warning(f"Throttled, retry after {e.retry_after}s")

# Async context manager
async with throttle:
    await channel.send(alert)
```

### SlackChannel

Send alerts to Slack via incoming webhooks:

```python
from kstlib.alerts.channels import SlackChannel

# Direct webhook URL
channel = SlackChannel(
    webhook_url="https://hooks.slack.com/services/T.../B.../xxx",
    username="kstlib-alerts",
    icon_emoji=":bell:",
    timeout=10.0,  # Optional, uses config default
)

# From config with credential resolver (SOPS support)
channel = SlackChannel.from_config(
    config={"credentials": "slack_webhook"},
    credential_resolver=resolver,
)

result = await channel.send(alert)
if result.success:
    print("Alert sent!")
```

### EmailChannel

Send alerts via email using kstlib.mail transports:

```python
from kstlib.alerts.channels import EmailChannel
from kstlib.mail.transports import SMTPTransport, ResendTransport

# With SMTP
smtp = SMTPTransport(host="smtp.example.com", port=587)
channel = EmailChannel(
    transport=smtp,
    sender="alerts@example.com",
    recipients=["oncall@example.com", "backup@example.com"],
    subject_prefix="[PROD ALERT]",
)

# With Resend (async)
resend = ResendTransport(api_key="re_xxx")
channel = EmailChannel(
    transport=resend,
    sender="alerts@example.com",
    recipients=["team@example.com"],
)
```

### AlertManager

Orchestrate multi-channel delivery with level filtering:

```python
from kstlib.alerts import AlertManager, AlertLevel
from kstlib.alerts.throttle import AlertThrottle

manager = AlertManager()

# Add channels with level filtering
manager.add_channel(slack, min_level=AlertLevel.INFO)
manager.add_channel(email, min_level=AlertLevel.CRITICAL)

# Add throttle per channel
throttle = AlertThrottle(rate=10, per=60.0)
manager.add_channel(pagerduty, min_level=AlertLevel.CRITICAL, throttle=throttle)

# Send alert - delivered to all matching channels concurrently
alert = AlertMessage(
    title="High CPU Usage",
    body="Server cpu-01 at 95% for 5 minutes",
    level=AlertLevel.WARNING,
)
results = await manager.send(alert)

# Check results
for result in results:
    if result.success:
        print(f"{result.channel}: OK")
    else:
        print(f"{result.channel}: FAILED - {result.error}")
```

### Alert Levels

Three severity levels for filtering:

```python
from kstlib.alerts.models import AlertLevel

AlertLevel.INFO      # Informational, non-urgent
AlertLevel.WARNING   # Attention needed, not critical
AlertLevel.CRITICAL  # Immediate action required
```

## Statistics

Track delivery metrics:

```python
manager = AlertManager()
# ... send alerts ...

stats = manager.stats
print(f"Sent: {stats.total_sent}")
print(f"Failed: {stats.total_failed}")
print(f"Throttled: {stats.total_throttled}")

# Per-channel breakdown
for channel, channel_stats in stats.by_channel.items():
    print(f"{channel}: {channel_stats}")
```

## Examples

See `examples/alerts/` for complete working examples:

| Example | Description |
|---------|-------------|
| `email_basic.py` | Basic email alerts |
| `slack_basic.py` | Slack webhook alerts |
| `multi_channel.py` | Multi-channel with level filtering |

## See Also

- {doc}`/api/alerts` - API Reference
- {doc}`/api/exceptions/alerts` - Exception Catalog
- {doc}`/features/mail/index` - Mail transports for EmailChannel
