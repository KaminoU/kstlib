# Binance Testnet Resilience Example

This example demonstrates kstlib's resilience stack using Binance testnet WebSocket streams.

## Overview

The example runs a WebSocket connection to Binance testnet, streaming 15-minute klines (candlesticks) for BTC/USDT. It demonstrates:

- **Proactive reconnection**: Disconnect/reconnect at time boundaries using `TimeTrigger`
- **Heartbeat monitoring**: `Heartbeat` with `HeartbeatTarget` protocol for auto-restart
- **External watchdog**: `Watchdog.from_state_file()` in a separate process
- **Live dashboard**: Terminal display with counters, logs, and OHLCV table
- **Slack alerts**: `AlertManager` with `SlackChannel` for notifications

## kstlib Components Used

| Component | Module | Purpose |
|-----------|--------|---------|
| `TimeTrigger` | `kstlib.helpers` | Detect modulo time boundaries (30m, 4h, 8h) |
| `Heartbeat` | `kstlib.resilience` | Monitor stream via `HeartbeatTarget` protocol |
| `Watchdog.from_state_file()` | `kstlib.resilience` | External process monitoring heartbeat file |
| `AlertManager` | `kstlib.alerts` | Multi-channel alert dispatch |
| `SlackChannel` | `kstlib.alerts.channels` | Slack webhook notifications |
| `WebSocketManager` | `kstlib.websocket` | Managed WebSocket with reconnection |

## Architecture

```
┌───────────────────────────────────────────────────────────────────────┐
│                              main.py                                   │
│  ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────────┐  │
│  │    Heartbeat    │──▶│  WebSocket      │──▶│     Dashboard       │  │
│  │ (HeartbeatTarget│   │  (klines)       │   │ (Spinner + Table)   │  │
│  │   protocol)     │   └─────────────────┘   └─────────────────────┘  │
│  └─────────────────┘            │                                     │
│          │                      │                                     │
│          ▼                      ▼                                     │
│  state/heartbeat.json    ┌─────────────────┐                          │
│          │               │   TimeTrigger   │                          │
│          │               │  (30m modulo)   │                          │
│          │               └─────────────────┘                          │
│          │                      │                                     │
│          │                      ▼ should_trigger()                    │
│          │               trigger_reconnect()                          │
│          │                      │                                     │
│          │                      ▼ on_disconnect                       │
│          │               ┌─────────────────┐                          │
│          │               │  AlertManager   │──▶ Slack                 │
│          │               │  (SlackChannel) │                          │
│          │               └─────────────────┘                          │
└──────────│────────────────────────────────────────────────────────────┘
           │
           ▼
┌───────────────────────────────────────────────────────────────────────┐
│                       watchdog_service.py                              │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │  Watchdog.from_state_file(state_file, max_age=30)               │  │
│  │                                                                  │  │
│  │  Every check_interval (default: 5min):                          │  │
│  │  1. Read state/heartbeat.json                                   │  │
│  │  2. Check timestamp freshness (< max_age seconds)               │  │
│  │  3. If stale --> on_alert() --> AlertManager --> Slack          │  │
│  └─────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────┘
```

## Prerequisites

1. **Python 3.10+** with kstlib installed
2. **Binance Testnet API keys** from https://testnet.binance.vision/
3. **SOPS** for secrets encryption (optional but recommended)
4. **Slack webhook** for alerts (optional)

## Setup

### 1. Install kstlib

```bash
pip install kstlib
```

Or for development (from the kstlib root directory):

```bash
pip install -e .
```

### 2. Configure API Keys

Edit `config/binance.token.sops.yml`:

```yaml
binance_credentials:
  api_key: "YOUR_TESTNET_API_KEY"
  api_secret: "YOUR_TESTNET_API_SECRET"
```

> **Note**: For testnet, the API keys are not actually required for public streams (klines). They're only needed if you want to test authenticated endpoints.

### 3. Configure Slack (Optional)

Edit `config/slack.sops.yml`:

```yaml
credentials:
  sops_hb: "https://hooks.slack.com/services/YOUR/HEARTBEAT/WEBHOOK"
  sops_wd: "https://hooks.slack.com/services/YOUR/WATCHDOG/WEBHOOK"
  sops_testnet: "https://hooks.slack.com/services/YOUR/TESTNET/WEBHOOK"
```

### 4. Encrypt Secrets (Recommended)

```bash
cd examples/resilience/binance_testnet/config

# Encrypt with your SOPS configuration
sops --encrypt --in-place binance.token.sops.yml
sops --encrypt --in-place slack.sops.yml
```

## Usage

### Run the Main Application

```bash
cd examples/resilience/binance_testnet
python main.py
```

You'll see a live dashboard:

```
⠋ HB:1 | WS:0 | CANDLES:5  -  Listening BTCUSDT@15m

─── Logs ───
14:30:02 [INFO ] WebSocket connected
14:30:05 [DEBUG] Candle update: 42150.00
14:30:15 [INFO ] Candle closed: 14:15:00 | O:42100.00 H:42150.00 ...
14:30:17 [INFO ] TimeTrigger: 30m boundary reached, triggering reconnect...

┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                     OHLCV - BTCUSDT 15m                         ┃
┣━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┫
┃ Time     ┃ Open     ┃ High     ┃ Low      ┃ Close    ┃ Volume   ┃
┡━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━┩
│ 14:15:00 │ 42100.00 │ 42150.00 │ 42050.00 │ 42120.00 │   125.50 │
│ 14:30:00 │ 42120.00 │ 42200.00 │ 42100.00 │ 42180.00 │    98.20 │
└──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘

Status: Connected, streaming... | Press Ctrl+C to stop
```

### Keyboard Controls

| Key | Action |
|-----|--------|
| `d` | Simulate disconnect (test reconnection) |
| `q` | Quit gracefully |
| `F10` | Quit gracefully (classic exit key) |
| `Ctrl+C` | Force quit |

### Run the Watchdog (Separate Terminal)

```bash
cd examples/resilience/binance_testnet
python watchdog_service.py
```

Output:

```
[2026-01-22 14:35:00] INFO Watchdog service started
[2026-01-22 14:35:00] INFO State file: .../state/heartbeat.state.json
[2026-01-22 14:35:00] INFO Check interval: 300.0 seconds
[2026-01-22 14:35:00] INFO Max age: 30.0 seconds
```

## Configuration

### kstlib.conf.yml

Main configuration file that includes other configs:

```yaml
include:
  - config/binance.yml
  - config/binance.token.sops.yml
  - config/slack.sops.yml

resilience:
  heartbeat:
    interval: 5.0  # seconds between heartbeats
    state_file: state/heartbeat.state.json

  watchdog:
    state_file: state/heartbeat.state.json  # Same file as heartbeat
    cycle_interval: 300  # 5 minutes between checks
    max_heartbeat_age: 30  # seconds before considering stale

websocket:
  ping:
    interval: 15
    timeout: 10
  reconnect:
    delay: 0.5
    max_delay: 30.0
    max_attempts: 20
```

### config/binance.yml

Trading configuration:

```yaml
binance:
  # Environment: "testnet" or "mainnet" (used for Slack alerts channel)
  environment: testnet

  # WebSocket endpoint
  ws_url: "wss://stream.testnet.binance.vision/ws"

  stream:
    symbol: btcusdt
    timeframe: 15m
  reconnect:
    modulo_minutes: 30  # Reconnect at :00 and :30
    margin_seconds: 5   # Start disconnect 5s before boundary
```

### Switching to Mainnet

To run on Binance mainnet (real data, no trading), update `config/binance.yml`:

```yaml
binance:
  environment: mainnet
  ws_url: "wss://stream.binance.com:9443/ws"
  stream:
    symbol: btcusdt
    timeframe: 15m
```

And add `sops_mainnet` webhook in `config/slack.sops.yml`:

```yaml
credentials:
  sops_hb: "https://hooks.slack.com/services/YOUR/HEARTBEAT/WEBHOOK"
  sops_wd: "https://hooks.slack.com/services/YOUR/WATCHDOG/WEBHOOK"
  sops_mainnet: "https://hooks.slack.com/services/YOUR/MAINNET/WEBHOOK"
```

> **Note**: The `environment` field determines which Slack webhook key to use (`sops_testnet` vs `sops_mainnet`).

## How It Works

### TimeTrigger for Proactive Reconnection

Instead of waiting for Binance to disconnect (every 24h), the application proactively reconnects at configurable time boundaries:

```python
from kstlib.helpers import TimeTrigger

trigger = TimeTrigger("30m")  # 30-minute boundaries

# In kline handler, after candle close:
if trigger.should_trigger(margin=5.0):  # 5s before boundary
    stream.trigger_reconnect()
```

### Heartbeat with HeartbeatTarget Protocol

The `BinanceKlineStream` implements the `HeartbeatTarget` protocol (has `is_dead` property), allowing `Heartbeat` to monitor and auto-restart:

```python
from kstlib.resilience import Heartbeat

heartbeat = Heartbeat(
    state_file=state_file,
    interval=5.0,
    target=stream,  # HeartbeatTarget protocol
    on_target_dead=restart_stream,
    on_alert=send_slack_alert,
)
```

### External Watchdog

The watchdog runs as a separate process using `Watchdog.from_state_file()`:

```python
from kstlib.resilience import Watchdog

watchdog = Watchdog.from_state_file(
    state_file="state/heartbeat.state.json",
    check_interval=300.0,  # Check every 5 minutes
    max_age=30.0,          # Alert if file > 30s old
    on_timeout=log_warning,
    on_alert=send_slack_alert,
)
```

## Dashboard Counters

| Counter | Meaning |
|---------|---------|
| **HB:n** | Heartbeat sessions (increments if HB restarts after crash) |
| **WS:n** | WebSocket reconnections (planned + forced) |
| **CANDLES:n** | Total candles received since start |

## State File Format

The heartbeat writes `state/heartbeat.state.json`:

```json
{
  "timestamp": "2026-01-22T14:35:00.123456+00:00",
  "heartbeat_sessions": 1,
  "websocket_reconnects": 4,
  "candles_received": 42,
  "last_candle_time": "2026-01-22T14:30:00+00:00",
  "status": "running",
  "error": null,
  "metadata": {}
}
```

## Systemd Service (Production)

For long-running deployment (e.g., on Raspberry Pi):

### Main Application

Create `/etc/systemd/system/binance-resilience.service`:

```ini
[Unit]
Description=Binance Resilience Demo
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/kstlib/examples/resilience/binance_testnet
ExecStart=/home/pi/.venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Watchdog Service

Create `/etc/systemd/system/binance-watchdog.service`:

```ini
[Unit]
Description=Binance Resilience Watchdog
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/kstlib/examples/resilience/binance_testnet
ExecStart=/home/pi/.venv/bin/python watchdog_service.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Enable Services

```bash
sudo systemctl daemon-reload
sudo systemctl enable binance-resilience binance-watchdog
sudo systemctl start binance-resilience binance-watchdog
```

## Troubleshooting

### WebSocket Connection Failed

- Check internet connectivity
- Verify testnet URL is accessible: `wss://stream.testnet.binance.vision/ws`
- Check firewall settings

### State File Not Found

- Ensure `state/` directory exists
- Check file permissions
- Look for `heartbeat.state.json` in the state directory

### Slack Alerts Not Working

- Verify webhook URL is correct in `config/slack.sops.yml`
- Check SOPS decryption is working: `sops --decrypt config/slack.sops.yml`
- Test webhook manually with curl

### TimeTrigger Not Triggering

- Verify `modulo_minutes` in config matches your expectations
- Check `margin_seconds` is not too small
- Enable trace logging: `python main.py --log-preset trace`

## License

See main kstlib LICENSE.
