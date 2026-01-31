"""Abstract base protocol for session runners.

This module defines the protocol that all session runners must implement,
enabling backend abstraction for tmux and container-based session management.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from kstlib.ops.models import SessionConfig, SessionStatus


@runtime_checkable
class AbstractRunner(Protocol):
    """Protocol defining the interface for session runners.

    All session runners (TmuxRunner, ContainerRunner) must implement
    this protocol to ensure consistent behavior across backends.

    The protocol defines core operations for session lifecycle management:
    - start: Create and start a new session
    - stop: Stop a running session
    - attach: Attach terminal to a session (replaces current process)
    - status: Get current session status
    - logs: Retrieve session logs
    - exists: Check if a session exists
    - list_sessions: List all sessions managed by this runner

    Examples:
        >>> def run_session(runner: AbstractRunner, config: SessionConfig) -> None:
        ...     status = runner.start(config)
        ...     print(f"Session {status.name} started with PID {status.pid}")
    """

    def start(self, config: SessionConfig) -> SessionStatus:
        """Create and start a new session.

        Args:
            config: Session configuration including name, command, etc.

        Returns:
            SessionStatus with current state after starting.

        Raises:
            SessionExistsError: If a session with this name already exists.
            SessionStartError: If the session failed to start.
            BackendNotFoundError: If the backend binary is not available.
        """
        ...

    def stop(
        self,
        name: str,
        *,
        graceful: bool = True,
        timeout: int = 10,
    ) -> bool:
        """Stop a running session.

        Args:
            name: Session name to stop.
            graceful: If True, send SIGTERM first and wait for graceful shutdown.
                     If False, send SIGKILL immediately.
            timeout: Seconds to wait for graceful shutdown before forcing.

        Returns:
            True if the session was stopped, False if it was not running.

        Raises:
            SessionNotFoundError: If the session does not exist.
            SessionStopError: If the session could not be stopped.
        """
        ...

    def attach(self, name: str) -> None:
        """Attach terminal to a running session.

        This method replaces the current process with the attach command
        using os.execvp. It does not return on success.

        Args:
            name: Session name to attach to.

        Raises:
            SessionNotFoundError: If the session does not exist.
            SessionAttachError: If attachment failed.

        Note:
            This method uses os.execvp and does not return on success.
            The calling process is replaced by the attach command.
        """
        ...

    def status(self, name: str) -> SessionStatus:
        """Get the current status of a session.

        Args:
            name: Session name to query.

        Returns:
            SessionStatus with current state information.

        Raises:
            SessionNotFoundError: If the session does not exist.
        """
        ...

    def logs(self, name: str, lines: int = 100) -> str:
        """Retrieve recent logs from a session.

        Args:
            name: Session name to get logs from.
            lines: Number of lines to retrieve (default 100).

        Returns:
            String containing the log output with ANSI codes preserved.

        Raises:
            SessionNotFoundError: If the session does not exist.
        """
        ...

    def exists(self, name: str) -> bool:
        """Check if a session with the given name exists.

        Args:
            name: Session name to check.

        Returns:
            True if the session exists, False otherwise.
        """
        ...

    def list_sessions(self) -> list[SessionStatus]:
        """List all sessions managed by this runner.

        Returns:
            List of SessionStatus for all sessions.
            Empty list if no sessions exist.
        """
        ...


__all__ = [
    "AbstractRunner",
]
