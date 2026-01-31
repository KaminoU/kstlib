#!/usr/bin/env python3
"""Binance Testnet Resilience Example.

This example demonstrates the kstlib resilience stack:
- WebSocketManager with proactive disconnect/reconnect
- Heartbeat with HeartbeatTarget protocol for auto-restart
- TimeTrigger for modulo-based reconnection (30min, 4h, 8h, etc.)
- AlertManager for Slack notifications

Usage:
    python main.py
    python main.py --config kstlib.conf.yml

Prerequisites:
    1. Configure config/slack.sops.yml with Slack webhooks
    2. Encrypt with SOPS: sops --encrypt --in-place config/*.sops.yml
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Add parent to path for imports when running directly
sys.path.insert(0, str(Path(__file__).parent))

from core import state_writer as state_writer_module
from core import ws_binance as ws_binance_module
from core.state_writer import StateWriter
from core.ws_binance import BinanceKlineStream, Kline
from display import dashboard
from display.dashboard import Dashboard

if TYPE_CHECKING:
    from collections.abc import Mapping

# kstlib imports
from kstlib.alerts import AlertLevel, AlertManager, AlertMessage
from kstlib.alerts.channels import SlackChannel
from kstlib.helpers import TimeTrigger
from kstlib.logging import LogManager, init_logging
from kstlib.resilience import GracefulShutdown, Heartbeat

# Placeholder logger - will be replaced by LogManager in main()
# Use standard logging to avoid handler duplication from multiple init_logging() calls
import logging as _logging

log: LogManager | _logging.Logger = _logging.getLogger(__name__)


def create_alert_manager(config: Mapping[str, Any], environment: str = "mainnet") -> AlertManager:
    """Create AlertManager from config with Slack channels.

    Args:
        config: Configuration with credentials.sops_* webhook URLs.
        environment: Environment name (testnet/mainnet) for channel routing.

    Returns:
        Configured AlertManager.

    Note:
        Expects SOPS keys: sops_hb, sops_wd, sops_{environment}
        e.g., sops_testnet or sops_mainnet
    """
    credentials = config.get("credentials", {})
    manager = AlertManager()

    # Add channels if webhooks are configured
    # Environment channel uses sops_{environment} key (e.g., sops_testnet, sops_mainnet)
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
    """Send alert via AlertManager (on_alert callback compatible).

    Args:
        manager: AlertManager instance.
        channel: Target channel name (heartbeat, watchdog, testnet).
        message: Alert message.
        context: Additional context data.
        level: Alert severity (INFO=green, WARNING=orange, CRITICAL=red).
    """
    try:
        alert = AlertMessage(
            title=f"[{channel.upper()}] kstlib-resilience",
            body=message,
            level=level,
            timestamp=True,
        )
        await manager.send(alert, channel=channel)
    except Exception as exc:
        log.warning("Failed to send alert: %s", exc)


class ResilienceDemo:
    """Main orchestrator using kstlib resilience components.

    Uses:
    - BinanceKlineStream: WebSocket with is_dead property
    - Heartbeat: Monitors stream via HeartbeatTarget protocol
    - TimeTrigger: Detects modulo boundaries for reconnection
    - AlertManager: Slack notifications via on_alert callback
    """

    def __init__(
        self,
        config: Mapping[str, Any],
        shutdown: GracefulShutdown | None = None,
    ) -> None:
        """Initialize the demo.

        Args:
            config: Application configuration.
            shutdown: Optional GracefulShutdown for unified signal handling.
                      If provided, keyboard quit (q/F10) uses shutdown.trigger().
        """
        self._config = config
        self._shutdown = shutdown
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
        self._timeframe = stream_config.get("timeframe", "15m")
        self._ws_url = binance_config.get("ws_url", "wss://stream.binance.com:9443/ws")
        self._environment = binance_config.get("environment", "mainnet")  # For Slack alerts

        # Reconnect settings - now using TimeTrigger format
        modulo_minutes = reconnect_config.get("modulo_minutes", 30)
        self._modulo = f"{modulo_minutes}m"
        self._margin_seconds = reconnect_config.get("margin_seconds", 5)

        # State file path
        state_file = hb_config.get("state_file", "state/heartbeat.state.json")
        self._state_file = Path(__file__).parent / state_file
        self._heartbeat_interval = hb_config.get("interval", 5.0)

        # Initialize components
        self._dashboard = Dashboard(
            symbol=self._symbol.upper(),
            timeframe=self._timeframe,
        )
        self._state_writer = StateWriter(self._state_file)
        self._alert_manager = create_alert_manager(config, self._environment)

        # TimeTrigger for modulo-based reconnection
        self._trigger = TimeTrigger(self._modulo)

        # Will be initialized in run()
        self._stream: BinanceKlineStream | None = None
        self._stream_task: asyncio.Task[None] | None = None
        self._heartbeat: Heartbeat | None = None

        # Restart lock to prevent concurrent restarts
        self._restarting: bool = False
        self._restart_lock: asyncio.Lock | None = None  # Created in run()

    @property
    def is_dead(self) -> bool:
        """HeartbeatTarget protocol: Return True if stream needs restart.

        Returns False during restart to prevent restart loops.
        The Heartbeat monitors this object (ResilienceDemo) instead of
        the stream directly, so we can control the is_dead logic.
        """
        # Don't report dead while restarting
        if self._restarting:
            return False
        # Don't report dead if no stream yet
        if self._stream is None:
            return False
        # Don't report dead if intentional shutdown
        if self._stream.is_shutdown:
            return False
        # Delegate to actual stream
        return self._stream.is_dead

    async def _on_alert(self, channel: str, message: str, context: Mapping[str, Any]) -> None:
        """Callback for Heartbeat/Watchdog alerts (always CRITICAL)."""
        await send_alert(self._alert_manager, channel, message, context, level=AlertLevel.CRITICAL)

    async def _on_connect(self) -> None:
        """Handle WebSocket connection."""
        # Note: WebSocketManager already logs connection, avoid duplicate
        self._dashboard.set_status("Connected, streaming...")
        self._state_writer.set_status("connected")

        await send_alert(
            self._alert_manager,
            self._environment,
            f"Connected to {self._symbol.upper()}@{self._timeframe}",
            {"event": "connect"},
            level=AlertLevel.INFO,  # Green = success
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
        # Update live price
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

            self._dashboard.add_candle(kline)
            self._state_writer.record_candle(kline.open_time.isoformat())
            self._dashboard.log_info(
                f"Closed: O={kline.open:.2f} H={kline.high:.2f} "
                f"L={kline.low:.2f} C={kline.close:.2f} V={kline.volume:.2f}"
            )
            self._dashboard.set_status("Connected")

            # Check proactive reconnect when candle CLOSES
            # Trigger if this candle's OPEN_TIME is at boundary (e.g., 22:30 for 30m modulo)
            # This means the candle that opened at 22:30 just closed (at ~22:35 for 5m candles)
            open_ts = kline.open_time.timestamp()
            if (open_ts % self._trigger.modulo_seconds) == 0 and self._stream:
                self._dashboard.log_info(
                    f"TimeTrigger: {self._modulo} boundary (open={kline.open_time}), triggering reconnect..."
                )
                self._stream.trigger_reconnect()
        else:
            self._dashboard.set_status("Streaming...")

    async def _on_target_dead(self) -> None:
        """Callback when Heartbeat detects stream is dead."""
        # Use lock to prevent concurrent restarts
        if self._restart_lock is None:
            return

        async with self._restart_lock:
            # Double-check after acquiring lock
            if self._restarting:
                return
            if self._stream is None or self._stream.is_shutdown:
                return

            # Mark as restarting BEFORE doing anything
            self._restarting = True

            try:
                self._dashboard.log_warn("Heartbeat: Stream dead, restarting...")
                self._dashboard.increment_heartbeat_sessions()
                self._state_writer.increment_heartbeat_sessions()

                await send_alert(
                    self._alert_manager,
                    "heartbeat",
                    f"Stream died, restarting {self._symbol.upper()}@{self._timeframe}",
                    {"event": "restart"},
                    level=AlertLevel.CRITICAL,  # Red = serious issue
                )

                # Cancel old stream task if still running (prevent orphan streams)
                if self._stream_task and not self._stream_task.done():
                    self._stream_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await self._stream_task

                # Create new stream
                self._stream = self._create_stream()
                # Start streaming in background (store reference to prevent GC)
                self._stream_task = asyncio.create_task(self._run_stream())

                # Wait for connection to establish (max 30 seconds)
                # Don't clear _restarting until stream is connected
                for _ in range(60):  # 60 * 0.5 = 30 seconds max
                    if self._stream.is_connected:
                        self._dashboard.log_info("Heartbeat: Stream reconnected successfully")
                        break
                    await asyncio.sleep(0.5)
                else:
                    # Connection failed after timeout - cancel task to avoid orphan
                    self._dashboard.log_warn("Heartbeat: Stream failed to connect after 30s, will retry")
                    if self._stream_task and not self._stream_task.done():
                        self._stream_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await self._stream_task
            finally:
                # Clear restarting flag
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
        """Background keyboard listener for test commands.

        Handles:
            d: Simulate Binance disconnect
            q: Quit gracefully
            F10: Quit gracefully (classic exit key)
        """
        if sys.platform == "win32":
            import msvcrt

            while self._running:
                try:
                    if msvcrt.kbhit():
                        char = msvcrt.getch()
                        # F10 on Windows: 0x00 followed by 0x44
                        if char in (b"\x00", b"\xe0"):
                            # Special key - read the scan code
                            scan = msvcrt.getch()
                            if scan == b"\x44":  # F10
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

            # Save terminal settings
            old_settings = termios.tcgetattr(sys.stdin)
            try:
                tty.setcbreak(sys.stdin.fileno())
                while self._running:
                    try:
                        if select.select([sys.stdin], [], [], 0.1)[0]:
                            char = sys.stdin.read(1)
                            # F10 on Unix: ESC [ 2 1 ~ (varies by terminal)
                            if char == "\x1b":  # ESC
                                # Read escape sequence
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
                                        if code == "21~":  # F10
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
            key: Key pressed ('d', 'q', 'F10', etc.)
        """
        if key == "d" and self._stream:
            self._dashboard.log_warn("Simulating Binance disconnect (key: d)")
            await self._stream.kill()
        elif key in ("q", "F10"):
            key_display = "F10" if key == "F10" else "q"
            self._dashboard.log_info(f"Quit requested (key: {key_display})")
            # Use GracefulShutdown if available for unified shutdown path
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

        # Initialize Heartbeat with HeartbeatTarget protocol
        # Use self as target (not self._stream) so we can control is_dead logic
        # and prevent restart loops when creating new streams
        # Note: No state_file - we use on_beat callback to delegate state writing
        # to StateWriter (avoids race condition with two writers on same file)
        self._heartbeat = Heartbeat(
            interval=self._heartbeat_interval,
            target=self,  # ResilienceDemo implements is_dead property
            on_target_dead=self._on_target_dead,
            on_alert=self._on_alert,
            on_beat=self._state_writer.update,
        )

        # Log startup
        self._dashboard.log_info(f"Starting {self._symbol.upper()}@{self._timeframe}")
        self._dashboard.log_info(f"URL: {self._ws_url}")
        self._dashboard.log_info(f"TimeTrigger: {self._modulo} (margin: {self._margin_seconds}s)")
        self._dashboard.log_info("Keys: d=disconnect, q/F10=quit")
        self._dashboard.set_status("Connecting...")
        self._state_writer.set_status("starting")

        # Start background tasks
        stream_task = asyncio.create_task(self._run_stream())
        display_task = asyncio.create_task(self._display_loop())
        keyboard_task = asyncio.create_task(self._keyboard_loop())

        # Start heartbeat (async version)
        await self._heartbeat.astart()

        # Wait for shutdown signal
        shutdown_task = asyncio.create_task(self._shutdown_event.wait())
        try:
            await shutdown_task
        except asyncio.CancelledError:
            self._dashboard.log_warn("Cancelled")
        finally:
            self._running = False

            # Stop heartbeat first
            if self._heartbeat:
                await self._heartbeat.ashutdown()

            # Gracefully shutdown stream (prevents SSL errors on close)
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

            # Give SSL connections time to close gracefully
            # Windows + mainnet SSL needs more time to avoid "Event loop is closed" errors
            await asyncio.sleep(1.0)

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

    script_dir = Path(__file__).parent
    original_cwd = os.getcwd()

    try:
        os.chdir(script_dir)
        config = kstlib_load_config(filename=str(config_path)) if config_path else kstlib_load_config()
        return dict(config)
    finally:
        os.chdir(original_cwd)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Binance Testnet Resilience Demo")
    parser.add_argument("--config", type=Path, default=None, help="Path to kstlib.conf.yml")
    parser.add_argument("--log-preset", type=str, default=None, help="Logging preset (dev, trace, prod)")
    args = parser.parse_args()

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

    # Propagate logger to modules
    dashboard.set_logger(log)
    state_writer_module.set_logger(log)
    ws_binance_module.set_logger(log)

    # Setup graceful shutdown with kstlib.resilience.GracefulShutdown
    # This provides: signal handling, timeout protection, standardized logging
    shutdown = GracefulShutdown(timeout=30)

    # Create demo with shutdown for unified exit path (CTRL+C, q, F10 all use same path)
    demo = ResilienceDemo(config, shutdown=shutdown)
    demo._dashboard.attach_to_logger(log)

    # Register demo.stop() as shutdown callback
    shutdown.register("demo", demo.stop, priority=10)
    shutdown.install()

    try:
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(demo.run())
    finally:
        shutdown.uninstall()


if __name__ == "__main__":
    main()
