"""State writer for watchdog communication.

Writes structured state files that the external watchdog service can monitor.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kstlib.logging import LogManager

# Placeholder logger - will be replaced by main.py via set_logger()
# Use standard logging to avoid handler duplication from multiple init_logging() calls
import logging as _logging

log: LogManager | _logging.Logger = _logging.getLogger(__name__)


def set_logger(logger: LogManager) -> None:
    """Set the module logger from main.py after init_logging()."""
    global log
    log = logger


@dataclass
class ResilienceState:
    """State data written for watchdog monitoring.

    Attributes:
        timestamp: Last update time (ISO 8601 UTC).
        pid: Process ID.
        heartbeat_sessions: Number of heartbeat restarts.
        websocket_reconnects: Number of WS reconnections.
        candles_received: Total candles processed.
        last_candle_time: Timestamp of last candle.
        status: Current status (running, error, stopped).
        error: Last error message if any.
        metadata: Additional context data.
    """

    timestamp: str
    pid: int = 0
    heartbeat_sessions: int = 1
    websocket_reconnects: int = 0
    candles_received: int = 0
    last_candle_time: str | None = None
    status: str = "running"
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dictionary."""
        return {
            "timestamp": self.timestamp,
            "pid": self.pid,
            "heartbeat_sessions": self.heartbeat_sessions,
            "websocket_reconnects": self.websocket_reconnects,
            "candles_received": self.candles_received,
            "last_candle_time": self.last_candle_time,
            "status": self.status,
            "error": self.error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResilienceState:
        """Deserialize from dictionary."""
        return cls(
            timestamp=data["timestamp"],
            pid=data.get("pid", 0),
            heartbeat_sessions=data.get("heartbeat_sessions", 1),
            websocket_reconnects=data.get("websocket_reconnects", 0),
            candles_received=data.get("candles_received", 0),
            last_candle_time=data.get("last_candle_time"),
            status=data.get("status", "unknown"),
            error=data.get("error"),
            metadata=data.get("metadata", {}),
        )


class StateWriter:
    """Writes resilience state to file for watchdog monitoring.

    The state file is a JSON file that contains counters and status
    information. The external watchdog service reads this file to
    determine if the main process is healthy.

    Args:
        state_file: Path to the state file.
    """

    def __init__(self, state_file: str | Path) -> None:
        self._state_file = Path(state_file)
        self._state = ResilienceState(
            timestamp=datetime.now(timezone.utc).isoformat(),
            pid=os.getpid(),
        )

    @property
    def state(self) -> ResilienceState:
        """Return current state."""
        return self._state

    def increment_heartbeat_sessions(self) -> None:
        """Increment heartbeat session counter (called on HB restart)."""
        self._state.heartbeat_sessions += 1
        self._write()

    def increment_websocket_reconnects(self) -> None:
        """Increment WebSocket reconnection counter."""
        self._state.websocket_reconnects += 1
        self._write()

    def record_candle(self, candle_time: str | None = None) -> None:
        """Record a candle reception."""
        self._state.candles_received += 1
        self._state.last_candle_time = candle_time
        self._write()

    def set_status(self, status: str, error: str | None = None) -> None:
        """Update status and optional error message."""
        self._state.status = status
        self._state.error = error
        self._write()

    def set_metadata(self, key: str, value: Any) -> None:
        """Set a metadata key-value pair."""
        self._state.metadata[key] = value
        self._write()

    def update(self) -> None:
        """Update timestamp and write state (heartbeat tick)."""
        self._write()

    def _write(self) -> None:
        """Write state to file atomically."""
        self._state.timestamp = datetime.now(timezone.utc).isoformat()
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            temp_file = self._state_file.with_suffix(".tmp")
            temp_file.write_text(json.dumps(self._state.to_dict(), indent=2))
            temp_file.replace(self._state_file)
        except OSError as exc:
            log.error("Failed to write state file: %s", exc)

    @classmethod
    def read_state(cls, state_file: str | Path) -> ResilienceState | None:
        """Read state from file (used by watchdog)."""
        path = Path(state_file)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return ResilienceState.from_dict(data)
        except (json.JSONDecodeError, KeyError, OSError) as exc:
            log.warning("Failed to read state file: %s", exc)
            return None


__all__ = ["ResilienceState", "StateWriter"]
