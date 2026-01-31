#!/usr/bin/env python3
"""Resilience test: Binance 1h candles with 4h proactive restart in tmux.

This example validates the kstlib resilience stack in long-running conditions:
- WebSocket streams Binance klines (1h candles)
- Proactive disconnect/reconnect every 4h (TimeTrigger modulo)
- Reactive reconnect if Binance drops the connection
- CSV logging for post-mortem gap analysis
- Slack alerts on connect/disconnect/restart events
- Heartbeat + StateWriter for watchdog monitoring
- GracefulShutdown for clean exit (CTRL+C)

Designed to run inside a tmux session via kstlib ops:
    kstlib ops start resilience-tmux

Usage (direct):
    python main.py
    python main.py --config kstlib.conf.yml
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Add parent examples dirs to path for shared core/ and display/ imports
_SCRIPT_DIR = Path(__file__).parent
_BINANCE_TESTNET_DIR = _SCRIPT_DIR.parent.parent / "resilience" / "binance_testnet"
sys.path.insert(0, str(_SCRIPT_DIR))
sys.path.insert(0, str(_BINANCE_TESTNET_DIR))

from candle_logger import CandleLogger  # noqa: E402
from core import state_writer as state_writer_module  # noqa: E402
from core import ws_binance as ws_binance_module  # noqa: E402
from core.state_writer import StateWriter  # noqa: E402
from core.ws_binance import BinanceKlineStream, Kline  # noqa: E402
from display import dashboard as dashboard_module  # noqa: E402
from display.dashboard import Dashboard  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Mapping

# kstlib imports
import logging as _logging  # noqa: E402

from kstlib.alerts import AlertLevel, AlertManager, AlertMessage  # noqa: E402
from kstlib.alerts.channels import SlackChannel  # noqa: E402
from kstlib.helpers import TimeTrigger  # noqa: E402
from kstlib.logging import LogManager, init_logging  # noqa: E402
from kstlib.resilience import GracefulShutdown, Heartbeat  # noqa: E402

log: LogManager | _logging.Logger = _logging.getLogger(__name__)


def create_alert_manager(config: Mapping[str, Any], environment: str = "mainnet") -> AlertManager:
    """Create AlertManager from config with Slack channels.

    Args:
        config: Configuration with credentials.sops_* webhook URLs.
        environment: Environment name for channel routing.

    Returns:
        Configured AlertManager.
    """
    credentials = config.get("credentials", {})
    manager = AlertManager()

    webhooks = {
        "heartbeat": credentials.get("sops_hb"),
        "watchdog": credentials.get("sops_wd"),
        environment: credentials.get(f"sops_{environment}"),
    }

    for name, url in webhooks.items():
        if url:
            channel = SlackChannel(
                webhook_url=url,
                username="kstlib-resilience",
                icon_emoji=":robot_face:",
            )
            manager.add_channel(channel, key=name)
            log.debug("Added Slack channel: %s", name)

    return manager


async def send_alert(
    manager: AlertManager,
    channel: str,
    message: str,
    context: Mapping[str, Any],
    *,
    level: AlertLevel = AlertLevel.WARNING,
) -> None:
    """Send alert via AlertManager.

    Args:
        manager: AlertManager instance.
        channel: Target channel name.
        message: Alert message.
        context: Additional context data.
        level: Alert severity.
    """
    try:
        alert = AlertMessage(
            title=f"[{channel.upper()}] kstlib-resilience-tmux",
            body=message,
            level=level,
            timestamp=True,
        )
        await manager.send(alert, channel=channel)
    except Exception as exc:
        log.warning("Failed to send alert: %s", exc)


class ResilienceTmuxDemo:
    """Orchestrator for 1h candle streaming with 4h proactive restart.

    Combines:
    - BinanceKlineStream: WebSocket with is_dead/is_shutdown protocol
    - Heartbeat: Monitors stream, auto-restarts on death
    - TimeTrigger("4h"): Proactive reconnect every 4 hours
    - CandleLogger: CSV logging for gap analysis
    - AlertManager: Slack notifications
    - Dashboard: Terminal display (print + Rich table)
    """

    def __init__(
        self,
        config: Mapping[str, Any],
        shutdown: GracefulShutdown | None = None,
        *,
        debug_mode: bool = False,
    ) -> None:
        """Initialize the resilience demo.

        Args:
            config: Application configuration.
            shutdown: Optional GracefulShutdown for unified signal handling.
            debug_mode: If True, disable dashboard clear screen.
        """
        self._config = config
        self._shutdown = shutdown
        self._debug_mode = debug_mode
        self._running = False
        self._shutdown_event: asyncio.Event | None = None

        # Extract config sections
        binance_config = config.get("binance", {})
        resilience_config = config.get("resilience", {})
        stream_config = binance_config.get("stream", {})
        reconnect_config = binance_config.get("reconnect", {})
        hb_config = resilience_config.get("heartbeat", {})

        # Stream settings
        self._symbol = stream_config.get("symbol", "btcusdt")
        self._timeframe = stream_config.get("timeframe", "1h")
        self._ws_url = binance_config.get("ws_url", "wss://stream.binance.com:9443/ws")
        self._environment = binance_config.get("environment", "mainnet")

        # Reconnect: 4h modulo
        modulo_minutes = reconnect_config.get("modulo_minutes", 240)
        self._modulo = f"{modulo_minutes}m"
        self._margin_seconds = reconnect_config.get("margin_seconds", 5)

        # State file
        state_file = hb_config.get("state_file", "state/heartbeat.state.json")
        self._state_file = _SCRIPT_DIR / state_file
        self._heartbeat_interval = hb_config.get("interval", 5.0)

        # CSV logger
        csv_file = _SCRIPT_DIR / f"candles_{self._symbol.upper()}_{self._timeframe}.csv"
        self._candle_logger = CandleLogger(
            csv_file,
            symbol=self._symbol.upper(),
            timeframe=self._timeframe,
        )

        # Components
        self._dashboard = Dashboard(
            symbol=self._symbol.upper(),
            timeframe=self._timeframe,
            debug_mode=self._debug_mode,
        )
        self._state_writer = StateWriter(self._state_file)
        self._alert_manager = create_alert_manager(config, self._environment)
        self._trigger = TimeTrigger(self._modulo)

        # Runtime state
        self._stream: BinanceKlineStream | None = None
        self._stream_task: asyncio.Task[None] | None = None
        self._heartbeat: Heartbeat | None = None
        self._restarting: bool = False
        self._restart_lock: asyncio.Lock | None = None

    @property
    def is_dead(self) -> bool:
        """HeartbeatTarget protocol: True if stream needs restart."""
        if self._restarting:
            return False
        if self._stream is None:
            return False
        if self._stream.is_shutdown:
            return False
        return self._stream.is_dead

    async def _on_alert(self, channel: str, message: str, context: Mapping[str, Any]) -> None:
        """Callback for Heartbeat/Watchdog alerts (always CRITICAL)."""
        await send_alert(self._alert_manager, channel, message, context, level=AlertLevel.CRITICAL)

    async def _on_connect(self) -> None:
        """Handle WebSocket connection."""
        self._dashboard.set_status("Connected, streaming 1h candles...")
        self._state_writer.set_status("connected")

        await send_alert(
            self._alert_manager,
            self._environment,
            f"Connected to {self._symbol.upper()}@{self._timeframe}",
            {"event": "connect"},
            level=AlertLevel.INFO,
        )

    async def _on_disconnect(self, reason: Any) -> None:
        """Handle WebSocket disconnection."""
        reason_name = reason.name if hasattr(reason, "name") else str(reason)
        self._dashboard.log_warn(f"Disconnected: {reason_name}")
        self._dashboard.increment_websocket_reconnects()
        self._dashboard.set_status(f"Reconnecting... ({reason_name})")

        self._state_writer.increment_websocket_reconnects()
        self._state_writer.set_status("reconnecting", error=reason_name)

        await send_alert(
            self._alert_manager,
            self._environment,
            f"Disconnected: {reason_name}",
            {"event": "disconnect", "reason": reason_name},
        )

    async def _on_kline(self, kline: Kline) -> None:
        """Handle kline reception."""
        # Update live price on every tick
        time_str = kline.open_time.strftime("%H:%M:%S")
        self._dashboard.update_live_price(kline.close, time_str)

        if kline.is_closed:
            log.info(
                "Candle CLOSED: %s O=%.2f H=%.2f L=%.2f C=%.2f V=%.2f",
                kline.open_time.isoformat(),
                kline.open,
                kline.high,
                kline.low,
                kline.close,
                kline.volume,
            )

            # Log to CSV (append, flush immediately)
            self._candle_logger.log(kline)

            # Update dashboard and state
            self._dashboard.add_candle(kline)
            self._state_writer.record_candle(kline.open_time.isoformat())
            self._dashboard.log_info(
                f"Closed: O={kline.open:.2f} H={kline.high:.2f} "
                f"L={kline.low:.2f} C={kline.close:.2f} V={kline.volume:.2f} "
                f"[CSV:{self._candle_logger.count}]"
            )
            self._dashboard.set_status("Connected")

            # Check proactive reconnect: trigger at 4h boundary
            open_ts = kline.open_time.timestamp()
            if (open_ts % self._trigger.modulo_seconds) == 0 and self._stream:
                self._dashboard.log_info(
                    f"TimeTrigger: {self._modulo} boundary (open={kline.open_time}), triggering reconnect..."
                )
                self._stream.trigger_reconnect()

                await send_alert(
                    self._alert_manager,
                    self._environment,
                    f"Proactive reconnect at {self._modulo} boundary ({kline.open_time.isoformat()})",
                    {"event": "proactive_reconnect", "boundary": self._modulo},
                    level=AlertLevel.INFO,
                )
        else:
            self._dashboard.set_status("Streaming...")

    async def _on_target_dead(self) -> None:
        """Callback when Heartbeat detects stream is dead."""
        if self._restart_lock is None:
            return

        async with self._restart_lock:
            if self._restarting:
                return
            if self._stream is None or self._stream.is_shutdown:
                return

            self._restarting = True
            old_stream_id = self._stream.stream_id

            try:
                log.warning(
                    "[Heartbeat] Stream#%d detected DEAD, initiating restart...",
                    old_stream_id,
                )
                self._dashboard.log_warn(f"Heartbeat: Stream#{old_stream_id} dead, restarting...")
                self._dashboard.increment_heartbeat_sessions()
                self._state_writer.increment_heartbeat_sessions()

                await send_alert(
                    self._alert_manager,
                    "heartbeat",
                    f"Stream died, restarting {self._symbol.upper()}@{self._timeframe}",
                    {"event": "restart"},
                    level=AlertLevel.CRITICAL,
                )

                # Cancel old stream task
                if self._stream_task and not self._stream_task.done():
                    log.debug("[Heartbeat] Cancelling old stream task for Stream#%d", old_stream_id)
                    self._stream_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await self._stream_task

                # CRITICAL: Shutdown old stream's WebSocketManager to prevent duplicates!
                # Without this, the old stream (with auto_reconnect=True) may continue
                # reconnecting in the background while we create a new one.
                old_stream = self._stream
                if old_stream and not old_stream.is_shutdown:
                    log.info("[Heartbeat] Shutting down old Stream#%d WebSocketManager", old_stream_id)
                    try:
                        await old_stream.shutdown()
                        log.debug("[Heartbeat] Old Stream#%d shutdown complete", old_stream_id)
                    except Exception as exc:
                        log.warning("[Heartbeat] Old Stream#%d shutdown error: %s", old_stream_id, exc)

                # Create new stream
                log.info("[Heartbeat] Creating NEW stream (old was Stream#%d)", old_stream_id)
                self._stream = self._create_stream()
                log.info("[Heartbeat] New stream is Stream#%d", self._stream.stream_id)
                self._stream_task = asyncio.create_task(self._run_stream())

                # Wait for connection (max 30s)
                for _ in range(60):
                    if self._stream.is_connected:
                        log.info(
                            "[Heartbeat] Stream#%d reconnected successfully",
                            self._stream.stream_id,
                        )
                        self._dashboard.log_info(f"Heartbeat: Stream#{self._stream.stream_id} reconnected")
                        break
                    await asyncio.sleep(0.5)
                else:
                    log.warning(
                        "[Heartbeat] Stream#%d failed to connect after 30s, will retry",
                        self._stream.stream_id,
                    )
                    self._dashboard.log_warn(f"Heartbeat: Stream#{self._stream.stream_id} failed to connect after 30s")
                    if self._stream_task and not self._stream_task.done():
                        self._stream_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await self._stream_task
            finally:
                self._restarting = False

    def _create_stream(self) -> BinanceKlineStream:
        """Create a new BinanceKlineStream instance."""
        return BinanceKlineStream(
            symbol=self._symbol,
            timeframe=self._timeframe,
            ws_url=self._ws_url,
            modulo_minutes=int(self._trigger.modulo_seconds / 60),
            margin_seconds=self._margin_seconds,
            on_connect=self._on_connect,
            on_disconnect=self._on_disconnect,
            on_kline=self._on_kline,
            on_alert=self._on_alert,
            config=self._config.get("websocket"),
        )

    async def _run_stream(self) -> None:
        """Run the stream until it dies or shutdown requested."""
        if self._stream is None:
            return
        try:
            async with self._stream:
                async for _kline in self._stream.stream():
                    if not self._running:
                        break
        except Exception as exc:
            log.warning("Stream ended with exception: %s", exc)

    async def _keyboard_loop(self) -> None:
        """Background keyboard listener.

        Handles:
            d: Simulate Binance disconnect
            q: Quit gracefully
            F10: Quit gracefully
        """
        if sys.platform == "win32":
            import msvcrt

            while self._running:
                try:
                    if msvcrt.kbhit():
                        char = msvcrt.getch()
                        if char in (b"\x00", b"\xe0"):
                            scan = msvcrt.getch()
                            if scan == b"\x44":
                                await self._handle_key("F10")
                        else:
                            key = char.decode("utf-8", errors="ignore").lower()
                            await self._handle_key(key)
                    await asyncio.sleep(0.1)
                except asyncio.CancelledError:
                    break
                except Exception:
                    await asyncio.sleep(0.5)
        else:
            import select
            import termios
            import tty

            old_settings = termios.tcgetattr(sys.stdin)
            try:
                tty.setcbreak(sys.stdin.fileno())
                while self._running:
                    try:
                        if select.select([sys.stdin], [], [], 0.1)[0]:
                            char = sys.stdin.read(1)
                            if char == "\x1b":
                                if select.select([sys.stdin], [], [], 0.05)[0]:
                                    seq = sys.stdin.read(1)
                                    if seq == "[":
                                        code = ""
                                        while True:
                                            if select.select([sys.stdin], [], [], 0.05)[0]:
                                                c = sys.stdin.read(1)
                                                code += c
                                                if c == "~" or c.isalpha():
                                                    break
                                            else:
                                                break
                                        if code == "21~":
                                            await self._handle_key("F10")
                            else:
                                await self._handle_key(char.lower())
                        await asyncio.sleep(0.1)
                    except asyncio.CancelledError:
                        break
                    except Exception:
                        await asyncio.sleep(0.5)
            finally:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)

    async def _handle_key(self, key: str) -> None:
        """Handle keyboard input.

        Args:
            key: Key pressed ('d', 'q', 'F10').
        """
        if key == "d" and self._stream:
            self._dashboard.log_warn("Simulating Binance disconnect (key: d)")
            await self._stream.kill()
        elif key in ("q", "F10"):
            key_display = "F10" if key == "F10" else "q"
            self._dashboard.log_info(f"Quit requested (key: {key_display})")
            if self._shutdown:
                self._shutdown.trigger()
            else:
                self.stop()

    async def _display_loop(self) -> None:
        """Background display refresh loop."""
        while self._running:
            try:
                self._dashboard.refresh()
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(1.0)

    async def run(self) -> None:
        """Run the resilience demo."""
        self._running = True
        self._shutdown_event = asyncio.Event()
        self._restart_lock = asyncio.Lock()

        # Initialize stream
        self._stream = self._create_stream()

        # Initialize Heartbeat (no state_file, delegate via on_beat)
        self._heartbeat = Heartbeat(
            interval=self._heartbeat_interval,
            target=self,
            on_target_dead=self._on_target_dead,
            on_alert=self._on_alert,
            on_beat=self._state_writer.update,
        )

        # Log startup info
        self._dashboard.log_info(f"Starting {self._symbol.upper()}@{self._timeframe}")
        self._dashboard.log_info(f"URL: {self._ws_url}")
        self._dashboard.log_info(f"TimeTrigger: {self._modulo} (margin: {self._margin_seconds}s)")
        self._dashboard.log_info(f"CSV: {self._candle_logger.path.name}")
        self._dashboard.log_info("Keys: d=disconnect, q/F10=quit")
        self._dashboard.set_status("Connecting...")
        self._state_writer.set_status("starting")

        # Start background tasks
        stream_task = asyncio.create_task(self._run_stream())
        display_task = asyncio.create_task(self._display_loop())
        keyboard_task = asyncio.create_task(self._keyboard_loop())

        # Start heartbeat
        await self._heartbeat.astart()

        # Wait for shutdown signal
        shutdown_task = asyncio.create_task(self._shutdown_event.wait())
        try:
            await shutdown_task
        except asyncio.CancelledError:
            self._dashboard.log_warn("Cancelled")
        finally:
            self._running = False

            # Stop heartbeat
            if self._heartbeat:
                await self._heartbeat.ashutdown()

            # Shutdown stream
            if self._stream and not self._stream.is_shutdown:
                try:
                    await self._stream.shutdown()
                except Exception as exc:
                    log.debug("Stream shutdown error (expected): %s", exc)

            # Cancel background tasks
            for task in [stream_task, display_task, keyboard_task]:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

            # SSL close grace period
            await asyncio.sleep(1.0)

            # Close CSV logger
            self._candle_logger.close()
            self._dashboard.log_info(
                f"CSV: {self._candle_logger.count} candles logged to {self._candle_logger.path.name}"
            )

            # Final state
            self._state_writer.set_status("stopped")
            self._dashboard.log_info("Stopped")
            self._dashboard.set_status("Stopped")
            self._dashboard.refresh()

    def stop(self) -> None:
        """Signal graceful shutdown."""
        self._running = False
        if self._shutdown_event:
            self._shutdown_event.set()


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load configuration from kstlib.conf.yml."""
    from kstlib.config import load_config as kstlib_load_config

    original_cwd = os.getcwd()
    try:
        os.chdir(_SCRIPT_DIR)
        config = kstlib_load_config(filename=str(config_path)) if config_path else kstlib_load_config()
        return dict(config)
    finally:
        os.chdir(original_cwd)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Resilience tmux: 1h candles, 4h restart")
    parser.add_argument("--config", type=Path, default=None, help="Path to kstlib.conf.yml")
    parser.add_argument("--log-preset", type=str, default=None, help="Logging preset (dev, trace, prod)")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Debug mode: disable clear screen, show all logs (implies --log-preset=trace)",
    )
    args = parser.parse_args()

    # Debug mode implies trace logging
    if args.debug and not args.log_preset:
        args.log_preset = "trace"

    # Load config
    try:
        config = load_config(args.config)
    except Exception as exc:
        print(f"Error loading config: {exc}", file=sys.stderr)
        sys.exit(1)

    # Initialize logging
    global log
    logger_config = config.get("logger", {})
    if args.log_preset:
        log = init_logging(preset=args.log_preset)
    elif logger_config.get("preset"):
        log = init_logging(preset=logger_config["preset"])
    else:
        log = init_logging(preset="dev")

    # Propagate logger to shared modules
    dashboard_module.set_logger(log)
    state_writer_module.set_logger(log)
    ws_binance_module.set_logger(log)

    # Setup graceful shutdown
    shutdown = GracefulShutdown(timeout=30)
    demo = ResilienceTmuxDemo(config, shutdown=shutdown, debug_mode=args.debug)
    demo._dashboard.attach_to_logger(log)

    # Register shutdown callback
    shutdown.register("demo", demo.stop, priority=10)
    shutdown.install()

    try:
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(demo.run())
    finally:
        shutdown.uninstall()


if __name__ == "__main__":
    main()
