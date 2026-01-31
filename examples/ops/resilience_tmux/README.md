# Resilience tmux - 1h Candles with 4h Restart

Long-running resilience test for the kstlib stack.
Streams Binance BTCUSDT 1h candles with proactive WebSocket
restart every 4 hours, inside a tmux session.

## Architecture

```
tmux session (kstlib ops)
+-----------------------------------------------------------+
|  WebSocket        TimeTrigger       Heartbeat +           |
|  Binance          (4h cycle)        StateWriter           |
|  klines 1h                                                |
|       |                                                   |
|       v                                                   |
|  Dashboard        CandleLogger      Slack Alerts          |
|  (print)          (CSV file)        (connect/disconnect)  |
|                                                           |
|  GracefulShutdown (CTRL+C / q / F10)                      |
+-----------------------------------------------------------+
```

## Quick Start

```bash
cd examples/ops/resilience_tmux

# Direct run (foreground)
python main.py

# Via kstlib ops (tmux session, detachable)
kstlib ops start resilience-tmux
kstlib ops attach resilience-tmux   # Ctrl+B D to detach
kstlib ops status resilience-tmux
kstlib ops logs resilience-tmux
kstlib ops stop resilience-tmux
```

## What It Tests

| Component | Behavior |
|-----------|----------|
| WebSocket | Streams `btcusdt@kline_1h` from Binance mainnet |
| TimeTrigger | Proactive disconnect/reconnect every 4h (00:00, 04:00, ...) |
| Heartbeat | Monitors stream, auto-restarts if dead |
| CandleLogger | Appends each closed candle to CSV (flush on write) |
| Slack alerts | Connect, disconnect, proactive reconnect, stream death |
| GracefulShutdown | Clean exit on CTRL+C, `q`, or `F10` |

## CSV Gap Analysis

The CSV file `candles_BTCUSDT_1h.csv` logs every closed candle:

```csv
timestamp,open,high,low,close,volume
2026-01-27T14:00:00Z,100500.00,100800.00,100200.00,100600.00,1234.50
2026-01-27T15:00:00Z,100600.00,100900.00,100400.00,100700.00,1345.60
2026-01-27T16:00:00Z,100700.00,101000.00,100500.00,100800.00,1456.70
```

Each row should be exactly 1 hour apart. Any gap means a candle was lost
during reconnection.

### Analyze gaps (Python)

```python
from candle_logger import analyze_gaps

gaps = analyze_gaps("candles_BTCUSDT_1h.csv", expected_interval_seconds=3600)
if gaps:
    for g in gaps:
        print(f"GAP: {g['before']} -> {g['after']} ({g['missing_candles']} missing)")
else:
    print("No gaps found - resilience OK!")
```

## Slack Alerts (Optional)

Create `config/slack.sops.yml` with webhook URLs:

```yaml
credentials:
  sops_hb: "https://hooks.slack.com/services/xxx/yyy/zzz"
  sops_wd: "https://hooks.slack.com/services/xxx/yyy/zzz"
  sops_mainnet: "https://hooks.slack.com/services/xxx/yyy/zzz"
```

Encrypt with SOPS:

```bash
sops --encrypt --in-place config/slack.sops.yml
```

Then uncomment the include in `kstlib.conf.yml`.

## Files

| File | Purpose |
|------|---------|
| `main.py` | Main script (WebSocket + resilience + CSV) |
| `candle_logger.py` | CSV append logger + gap analyzer |
| `kstlib.conf.yml` | kstlib config (includes, resilience, ops) |
| `config/binance.yml` | Binance stream settings (1h, 4h modulo) |
| `candles_BTCUSDT_1h.csv` | Output: logged candles (created at runtime) |
| `state/` | Heartbeat state files (created at runtime) |
