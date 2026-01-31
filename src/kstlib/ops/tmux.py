"""tmux session runner for local development.

This module provides the TmuxRunner class for managing tmux sessions,
enabling detach/attach workflows for local development and backtesting.

Features:
- Create named sessions with custom commands and working directories
- Attach to running sessions (replaces current process)
- Capture session logs with ANSI codes preserved
- List all sessions with status information

Example:
    >>> from kstlib.ops import SessionConfig, BackendType
    >>> from kstlib.ops.tmux import TmuxRunner
    >>> runner = TmuxRunner()  # doctest: +SKIP
    >>> config = SessionConfig(  # doctest: +SKIP
    ...     name="dev",
    ...     backend=BackendType.TMUX,
    ...     command="python app.py",
    ... )
    >>> status = runner.start(config)  # doctest: +SKIP
    >>> runner.attach("dev")  # Replaces process  # doctest: +SKIP
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import TYPE_CHECKING

from kstlib.ops.exceptions import (
    SessionAttachError,
    SessionExistsError,
    SessionNotFoundError,
    SessionStartError,
    SessionStopError,
    TmuxNotFoundError,
)
from kstlib.ops.models import BackendType, SessionConfig, SessionState, SessionStatus

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


class TmuxRunner:
    """tmux session runner for local development.

    Manages tmux sessions for running persistent processes with
    detach/attach capability.

    Args:
        binary: Path or name of the tmux binary.

    Attributes:
        binary: The tmux binary path (validated on first use).

    Examples:
        >>> runner = TmuxRunner()  # doctest: +SKIP
        >>> config = SessionConfig(name="bot", command="python bot.py")
        >>> status = runner.start(config)  # doctest: +SKIP
        >>> runner.attach("bot")  # doctest: +SKIP
    """

    def __init__(self, binary: str = "tmux") -> None:
        """Initialize TmuxRunner.

        Args:
            binary: Path or name of the tmux binary.
        """
        self._binary_name = binary
        self._binary_path: str | None = None

    @property
    def binary(self) -> str:
        """Return validated tmux binary path.

        Raises:
            TmuxNotFoundError: If tmux is not installed.
        """
        if self._binary_path is None:
            path = shutil.which(self._binary_name)
            if path is None:
                raise TmuxNotFoundError(
                    f"tmux binary '{self._binary_name}' not found in PATH. "
                    "Install tmux: brew install tmux (macOS), apt install tmux (Linux)"
                )
            self._binary_path = path
        return self._binary_path

    def _run(
        self,
        args: Sequence[str],
        *,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """Run a tmux command.

        Args:
            args: Command arguments (without binary name).
            check: Whether to raise on non-zero exit.

        Returns:
            CompletedProcess with stdout/stderr.

        Raises:
            TmuxNotFoundError: If tmux is not installed.
        """
        cmd = [self.binary, *args]
        logger.debug("Running: %s", " ".join(cmd))
        return subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            check=check,
        )

    def start(self, config: SessionConfig) -> SessionStatus:
        """Create and start a new tmux session.

        Args:
            config: Session configuration.

        Returns:
            SessionStatus with state information.

        Raises:
            SessionExistsError: If session already exists.
            SessionStartError: If session failed to start.
            TmuxNotFoundError: If tmux is not installed.
        """
        if self.exists(config.name):
            raise SessionExistsError(config.name, "tmux")

        # Build command: tmux new-session -d -s {name} [-c {dir}] [command]
        args = ["new-session", "-d", "-s", config.name]

        if config.working_dir:
            args.extend(["-c", config.working_dir])

        # Environment variables
        for key, value in config.env.items():
            args.extend(["-e", f"{key}={value}"])

        if config.command:
            args.append(config.command)

        result = self._run(args)

        if result.returncode != 0:
            raise SessionStartError(
                config.name,
                "tmux",
                result.stderr.strip() or "Unknown error",
            )

        logger.info("Started tmux session: %s", config.name)
        return self.status(config.name)

    def stop(
        self,
        name: str,
        *,
        graceful: bool = True,
        timeout: int = 10,  # noqa: ARG002
    ) -> bool:
        """Stop a tmux session.

        Args:
            name: Session name to stop.
            graceful: If True, send C-c first, then kill if needed.
            timeout: Unused for tmux (interface compliance with AbstractRunner).

        Returns:
            True if stopped, False if not running.

        Raises:
            SessionNotFoundError: If session doesn't exist.
            SessionStopError: If session couldn't be stopped.
        """
        if not self.exists(name):
            raise SessionNotFoundError(name, "tmux")

        if graceful:
            # Send interrupt signal first
            self._run(["send-keys", "-t", name, "C-c"])
            # Small delay is handled by tmux itself

        # Kill the session
        result = self._run(["kill-session", "-t", name])

        if result.returncode != 0:
            # Session may have already exited
            if not self.exists(name):
                logger.info("tmux session already stopped: %s", name)
                return True
            raise SessionStopError(
                name,
                "tmux",
                result.stderr.strip() or "Unknown error",
            )

        logger.info("Stopped tmux session: %s", name)
        return True

    def attach(self, name: str) -> None:
        """Attach to a tmux session.

        This method replaces the current process with tmux attach.
        It does not return on success.

        Args:
            name: Session name to attach to.

        Raises:
            SessionNotFoundError: If session doesn't exist.
            SessionAttachError: If attach failed.
        """
        if not self.exists(name):
            raise SessionNotFoundError(name, "tmux")

        binary = self.binary
        logger.info("Attaching to tmux session: %s", name)

        # Replace current process with tmux attach
        try:
            os.execvp(binary, [binary, "attach-session", "-t", name])  # noqa: S606
        except OSError as e:
            raise SessionAttachError(name, "tmux", str(e)) from e

    def status(self, name: str) -> SessionStatus:
        """Get status of a tmux session.

        Args:
            name: Session name to query.

        Returns:
            SessionStatus with current state.

        Raises:
            SessionNotFoundError: If session doesn't exist.
        """
        # List format: #{session_name}:#{window_count}:#{session_created}:#{pid}
        result = self._run(
            [
                "list-sessions",
                "-F",
                "#{session_name}:#{session_windows}:#{session_created}:#{pid}",
            ]
        )

        if result.returncode != 0:
            if "no server running" in result.stderr:
                raise SessionNotFoundError(name, "tmux")
            raise SessionNotFoundError(name, "tmux")

        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split(":")
            if len(parts) >= 4 and parts[0] == name:
                return SessionStatus(
                    name=name,
                    state=SessionState.RUNNING,
                    backend=BackendType.TMUX,
                    pid=int(parts[3]) if parts[3].isdigit() else None,
                    created_at=parts[2] if parts[2] else None,
                    window_count=int(parts[1]) if parts[1].isdigit() else 0,
                )

        raise SessionNotFoundError(name, "tmux")

    def logs(self, name: str, lines: int = 100) -> str:
        """Capture recent output from a tmux session.

        Args:
            name: Session name to get logs from.
            lines: Number of lines to capture.

        Returns:
            String with captured output (ANSI codes preserved).

        Raises:
            SessionNotFoundError: If session doesn't exist.
        """
        if not self.exists(name):
            raise SessionNotFoundError(name, "tmux")

        # capture-pane -t {name} -p -S -{lines}
        result = self._run(["capture-pane", "-t", name, "-p", "-S", f"-{lines}"])

        if result.returncode != 0:
            return ""

        return result.stdout

    def exists(self, name: str) -> bool:
        """Check if a tmux session exists.

        Args:
            name: Session name to check.

        Returns:
            True if session exists, False otherwise.
        """
        result = self._run(["has-session", "-t", name])
        return result.returncode == 0

    def list_sessions(self) -> list[SessionStatus]:
        """List all tmux sessions.

        Returns:
            List of SessionStatus for all sessions.
        """
        result = self._run(
            [
                "list-sessions",
                "-F",
                "#{session_name}:#{session_windows}:#{session_created}:#{pid}",
            ]
        )

        if result.returncode != 0:
            # No server running or no sessions
            return []

        sessions: list[SessionStatus] = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split(":")
            if len(parts) >= 4:
                sessions.append(
                    SessionStatus(
                        name=parts[0],
                        state=SessionState.RUNNING,
                        backend=BackendType.TMUX,
                        pid=int(parts[3]) if parts[3].isdigit() else None,
                        created_at=parts[2] if parts[2] else None,
                        window_count=int(parts[1]) if parts[1].isdigit() else 0,
                    )
                )

        return sessions

    def send_keys(self, name: str, keys: str, *, enter: bool = True) -> None:
        """Send keys to a tmux session.

        Args:
            name: Session name to send keys to.
            keys: Keys or text to send.
            enter: If True, send Enter key after the text.

        Raises:
            SessionNotFoundError: If session doesn't exist.
        """
        if not self.exists(name):
            raise SessionNotFoundError(name, "tmux")

        args = ["send-keys", "-t", name, keys]
        if enter:
            args.append("Enter")

        self._run(args)


__all__ = [
    "TmuxRunner",
]
