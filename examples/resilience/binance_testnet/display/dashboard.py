"""Dashboard display with spinner, logs, and OHLCV table.

Provides a unified terminal display with:
- Spinner showing counters (HB sessions, WS reconnects, candles)
- Log zone (last 7 messages from kstlib logger)
- Rich table with recent OHLCV data
"""

from __future__ import annotations

import logging
import os
import sys
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table

from kstlib.logging import LogManager

# Placeholder logger - will be replaced by main.py via set_logger()
# Use standard logging to avoid handler duplication from multiple init_logging() calls
import logging as _logging


# Windows cp1252 compatibility - use ASCII fallbacks for non-UTF8 consoles
def _supports_unicode() -> bool:
    """Check if the console supports Unicode output."""
    try:
        encoding = sys.stdout.encoding or "ascii"
        return encoding.lower() in ("utf-8", "utf8", "utf-16", "utf-32")
    except Exception:
        return False


# Symbols with ASCII fallback for Windows
_UNICODE_SUPPORT = _supports_unicode()
SPINNER_CHAR = "*" if not _UNICODE_SUPPORT else "\u280b"  # ⠋
CHECK_CHAR = "+" if not _UNICODE_SUPPORT else "\u2713"  # ✓

if TYPE_CHECKING:
    from core.ws_binance import Kline

# kstlib LogManager - initialized with placeholder, replaced by main.py
log: LogManager | _logging.Logger = _logging.getLogger(__name__)

# Maximum candles to display in table
MAX_TABLE_ROWS = 10

# Maximum log entries to display
MAX_LOG_ENTRIES = 7


class BufferHandler(logging.Handler):
    """Handler that stores formatted log records in a buffer for dashboard display."""

    def __init__(self, maxlen: int = MAX_LOG_ENTRIES) -> None:
        """Initialize buffer handler.

        Args:
            maxlen: Maximum number of log entries to keep.
        """
        super().__init__()
        self.buffer: deque[str] = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        """Store formatted log record in buffer."""
        try:
            msg = self.format(record)
            self.buffer.append(msg)
        except Exception:
            self.handleError(record)

    def get_logs(self) -> list[str]:
        """Return buffered log entries."""
        return list(self.buffer)


def set_logger(logger: LogManager) -> None:
    """Set the module logger from main.py after init_logging()."""
    global log
    log = logger


@dataclass
class DashboardState:
    """Tracks dashboard display state.

    Attributes:
        heartbeat_sessions: Number of HB restarts.
        websocket_reconnects: Number of WS reconnections.
        candles_received: Total candles received.
        symbol: Trading pair.
        timeframe: Candle interval.
        status: Current status message.
        live_price: Current streaming price.
        live_time: Timestamp of last price update.
    """

    heartbeat_sessions: int = 1
    websocket_reconnects: int = 0
    candles_received: int = 0
    symbol: str = "BTCUSDT"
    timeframe: str = "15m"
    status: str = "Initializing..."
    live_price: float = 0.0
    live_time: str = "--:--:--"


@dataclass
class Dashboard:
    """Terminal dashboard with spinner, logs, and OHLCV table.

    Provides a live updating display that shows:
    1. Status line with counters (HB:n | WS:n | CANDLES:n)
    2. Recent log messages from kstlib logger (scrolling, max 7)
    3. OHLCV table with recent candles (max 10)

    The terminal is cleared before each refresh for clean display.
    Use debug_mode=True to disable clear screen and see all logs.

    Args:
        symbol: Trading pair (e.g., BTCUSDT).
        timeframe: Candle interval (e.g., 15m).
        debug_mode: If True, disable clear screen (show all logs).
    """

    symbol: str = "BTCUSDT"
    timeframe: str = "15m"
    debug_mode: bool = False
    state: DashboardState = field(default_factory=DashboardState)
    _candles: deque[Kline] = field(default_factory=lambda: deque(maxlen=MAX_TABLE_ROWS))
    _console: Console = field(default_factory=Console)
    _log_handler: BufferHandler = field(default_factory=BufferHandler)

    def __post_init__(self) -> None:
        """Initialize state with symbol/timeframe and attach log handler."""
        self.state.symbol = self.symbol.upper()
        self.state.timeframe = self.timeframe
        # Attach buffer handler to capture logs for display
        self._log_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)-5s] %(message)s", datefmt="%H:%M:%S")
        )

    def attach_to_logger(self, logger: LogManager) -> None:
        """Attach the buffer handler to a LogManager.

        Args:
            logger: The LogManager to capture logs from.
        """
        logger.addHandler(self._log_handler)

    def log_info(self, message: str) -> None:
        """Log INFO message via kstlib logger."""
        log.info(message)

    def log_warn(self, message: str) -> None:
        """Log WARNING message via kstlib logger."""
        log.warning(message)

    def log_error(self, message: str) -> None:
        """Log ERROR message via kstlib logger."""
        log.error(message)

    def log_debug(self, message: str) -> None:
        """Log DEBUG message via kstlib logger."""
        log.debug(message)

    def add_candle(self, candle: Kline) -> None:
        """Add a candle to the display."""
        self._candles.append(candle)
        self.state.candles_received += 1

    def increment_heartbeat_sessions(self) -> None:
        """Increment HB session counter."""
        self.state.heartbeat_sessions += 1

    def increment_websocket_reconnects(self) -> None:
        """Increment WS reconnect counter."""
        self.state.websocket_reconnects += 1

    def set_status(self, status: str) -> None:
        """Update status message."""
        self.state.status = status

    def update_live_price(self, price: float, time_str: str) -> None:
        """Update live streaming price.

        Args:
            price: Current close price.
            time_str: Formatted time string (HH:MM:SS).
        """
        self.state.live_price = price
        self.state.live_time = time_str

    def _clear_screen(self) -> None:
        """Clear terminal screen."""
        if sys.stdout.isatty():
            os.system("cls" if os.name == "nt" else "clear")

    def _render_spinner_line(self) -> str:
        """Render the spinner/status line."""
        hb = self.state.heartbeat_sessions
        ws = self.state.websocket_reconnects
        candles = self.state.candles_received
        symbol = self.state.symbol
        tf = self.state.timeframe

        return (
            f"[bold cyan]{SPINNER_CHAR}[/bold cyan] "
            f"[green]HB:{hb}[/green] | "
            f"[yellow]WS:{ws}[/yellow] | "
            f"[blue]CANDLES:{candles}[/blue]  -  "
            f"[bold]Listening {symbol}@{tf}[/bold]"
        )

    def _render_log_zone(self) -> None:
        """Render the log zone from captured kstlib logs."""
        self._console.print()
        self._console.print("[bold]─── Logs ───[/bold]")
        logs = self._log_handler.get_logs()
        if not logs:
            self._console.print("[dim]No logs yet...[/dim]")
        else:
            for entry in logs:
                self._console.print(f"[dim]{entry}[/dim]")
        self._console.print()

    def _render_ohlcv_table(self) -> None:
        """Render the OHLCV table."""
        table = Table(
            title=f"OHLCV - {self.state.symbol} {self.state.timeframe}",
            show_header=True,
            header_style="bold magenta",
        )

        table.add_column("Time", style="dim", width=19)
        table.add_column("Open", justify="right", style="cyan")
        table.add_column("High", justify="right", style="green")
        table.add_column("Low", justify="right", style="red")
        table.add_column("Close", justify="right", style="cyan")
        table.add_column("Volume", justify="right", style="yellow")
        table.add_column("Status", justify="center")

        if not self._candles:
            table.add_row("---", "-", "-", "-", "-", "-", "[dim]Waiting...[/dim]")
        else:
            for candle in self._candles:
                # Full timestamp: YYYY-MM-DD HH:MM:SS
                time_str = candle.open_time.strftime("%Y-%m-%d %H:%M:%S")
                table.add_row(
                    time_str,
                    f"{candle.open:,.2f}",
                    f"{candle.high:,.2f}",
                    f"{candle.low:,.2f}",
                    f"{candle.close:,.2f}",
                    f"{candle.volume:,.2f}",
                    f"[green]{CHECK_CHAR}[/green]",  # Always closed now
                )

        self._console.print(table)

    def refresh(self) -> None:
        """Refresh the entire display (clear + redraw).

        In debug_mode, skip clear screen to preserve all log history.
        """
        if self.debug_mode:
            # Debug mode: just print a separator, no clear
            return

        self._clear_screen()

        # Status/spinner line
        self._console.print(self._render_spinner_line())
        self._console.print()

        # Log zone
        self._render_log_zone()

        # OHLCV table
        self._render_ohlcv_table()

        # Footer with live price
        self._console.print()
        price = self.state.live_price
        time_str = self.state.live_time
        if price > 0:
            self._console.print(
                f"[dim]Live:[/dim] [bold cyan]{price:,.2f}[/bold cyan] "
                f"[dim]@ {time_str}[/dim]  |  "
                f"[dim]{self.state.status}[/dim]  |  "
                f"[dim]d=disconnect  q/F10=quit  Ctrl+C=force[/dim]"
            )
        else:
            self._console.print(f"[dim]{self.state.status} | d=disconnect  q/F10=quit  Ctrl+C=force[/dim]")


__all__ = ["BufferHandler", "Dashboard", "DashboardState"]
