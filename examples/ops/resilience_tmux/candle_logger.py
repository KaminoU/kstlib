"""CSV candle logger for post-mortem analysis.

Logs each closed candle to a CSV file in append mode.
Allows detection of temporal gaps (missing candles) after
reconnection or restart events.

Usage:
    logger = CandleLogger("candles_BTCUSDT_1h.csv")
    logger.log(kline)  # Appends one row per closed candle
    logger.close()
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.ws_binance import Kline


class CandleLogger:
    """Append-only CSV logger for closed candles.

    Writes one row per closed candle with OHLCV data.
    The CSV file can be analyzed after the test to detect
    temporal gaps (missing candles = lost during reconnection).

    Args:
        path: Path to the CSV file.
        symbol: Trading pair for the header comment.
        timeframe: Candle interval for the header comment.
    """

    HEADER: list[str] = ["timestamp", "open", "high", "low", "close", "volume"]  # noqa: RUF012

    def __init__(self, path: str | Path, *, symbol: str = "BTCUSDT", timeframe: str = "1h") -> None:
        self._path = Path(path)
        self._symbol = symbol
        self._timeframe = timeframe
        self._count = 0

        # Create parent dirs if needed
        self._path.parent.mkdir(parents=True, exist_ok=True)

        # Write header if file is new or empty
        write_header = not self._path.exists() or self._path.stat().st_size == 0

        # Open in append mode, line-buffered for crash resilience
        self._file = open(self._path, "a", newline="", encoding="utf-8")  # noqa: SIM115
        self._writer = csv.writer(self._file)

        if write_header:
            self._writer.writerow(self.HEADER)
            self._file.flush()

    @property
    def count(self) -> int:
        """Number of candles logged this session."""
        return self._count

    @property
    def path(self) -> Path:
        """Path to the CSV file."""
        return self._path

    def log(self, kline: Kline) -> None:
        """Log a closed candle to CSV.

        Args:
            kline: Kline object (should be closed).
        """
        self._writer.writerow(
            [
                kline.open_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                f"{kline.open:.2f}",
                f"{kline.high:.2f}",
                f"{kline.low:.2f}",
                f"{kline.close:.2f}",
                f"{kline.volume:.2f}",
            ]
        )
        self._file.flush()
        self._count += 1

    def close(self) -> None:
        """Close the CSV file."""
        if self._file and not self._file.closed:
            self._file.flush()
            self._file.close()

    def __enter__(self) -> CandleLogger:
        """Enter context manager."""
        return self

    def __exit__(self, *args: object) -> None:
        """Exit context manager."""
        self.close()


def analyze_gaps(path: str | Path, expected_interval_seconds: int = 3600) -> list[dict[str, str]]:
    """Analyze a candle CSV file for temporal gaps.

    Reads the CSV and checks that consecutive candles are exactly
    `expected_interval_seconds` apart. Any gap indicates a lost candle.

    Args:
        path: Path to the CSV file.
        expected_interval_seconds: Expected seconds between candles (3600 for 1h).

    Returns:
        List of gap dictionaries with 'before', 'after', 'gap_seconds', 'missing_candles'.
    """
    csv_path = Path(path)
    if not csv_path.exists():
        return []

    gaps: list[dict[str, str]] = []
    prev_ts: datetime | None = None

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = datetime.strptime(row["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if prev_ts is not None:
                delta = (ts - prev_ts).total_seconds()
                if delta != expected_interval_seconds:
                    missing = int(delta / expected_interval_seconds) - 1
                    gaps.append(
                        {
                            "before": prev_ts.isoformat(),
                            "after": ts.isoformat(),
                            "gap_seconds": str(int(delta)),
                            "missing_candles": str(missing),
                        }
                    )
            prev_ts = ts

    return gaps


__all__ = ["CandleLogger", "analyze_gaps"]
