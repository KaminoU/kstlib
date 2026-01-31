"""Data models for the kstlib.ops module.

This module defines the core data structures used by the ops module:

- BackendType: Enum for backend selection (tmux, container)
- SessionState: Enum for session state (running, stopped, exited, unknown)
- SessionConfig: Configuration for creating a session
- SessionStatus: Current status of a session
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from kstlib.ops.validators import (
    validate_command,
    validate_env,
    validate_image_name,
    validate_ports,
    validate_session_name,
    validate_volumes,
)


class BackendType(str, Enum):
    """Backend type for session management.

    Attributes:
        TMUX: Use tmux for session management (dev/local).
        CONTAINER: Use Podman/Docker for session management (prod).
    """

    TMUX = "tmux"
    CONTAINER = "container"


class SessionState(str, Enum):
    """State of a session or container.

    Attributes:
        RUNNING: Session is active and running.
        STOPPED: Session was stopped gracefully.
        EXITED: Container exited (with exit code).
        DEFINED: Session exists in config but has not been started.
        UNKNOWN: State cannot be determined.
    """

    RUNNING = "running"
    STOPPED = "stopped"
    EXITED = "exited"
    DEFINED = "defined"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SessionConfig:
    """Configuration for creating a session.

    This dataclass holds all configuration options for both tmux and container
    backends. Options that are not applicable to the selected backend are ignored.

    Attributes:
        name: Unique session name (required).
        backend: Backend type (tmux or container).
        command: Command to run in the session (tmux) or container.
        working_dir: Working directory for the session.
        env: Environment variables to set.
        image: Container image to use (container backend only).
        volumes: Volume mounts in "host:container" format.
        ports: Port mappings in "host:container" format.
        runtime: Container runtime to use ("podman" or "docker").
        log_volume: Log volume mount for persistence (auto-mounted).

    Examples:
        >>> config = SessionConfig(
        ...     name="astro",
        ...     backend=BackendType.TMUX,
        ...     command="python -m astro.bot",
        ... )

        >>> config = SessionConfig(
        ...     name="astro-prod",
        ...     backend=BackendType.CONTAINER,
        ...     image="astro-bot:latest",
        ...     volumes=["./data:/app/data"],
        ...     log_volume="./logs:/app/logs",
        ... )
    """

    name: str
    backend: BackendType = BackendType.TMUX
    # Common options
    command: str | None = None
    working_dir: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    # Container-specific options
    image: str | None = None
    volumes: list[str] = field(default_factory=list)
    ports: list[str] = field(default_factory=list)
    runtime: str | None = None
    # Log persistence (post-mortem analysis)
    log_volume: str | None = None

    def __post_init__(self) -> None:
        """Validate configuration values.

        Raises:
            ValueError: If any configuration value is invalid.
        """
        validate_session_name(self.name)
        if self.command is not None:
            validate_command(self.command)
        if self.image is not None:
            validate_image_name(self.image)
        if self.volumes:
            validate_volumes(self.volumes)
        if self.ports:
            validate_ports(self.ports)
        if self.env:
            validate_env(self.env)


@dataclass(slots=True)
class SessionStatus:
    """Current status of a session or container.

    This dataclass holds the runtime status information for a session,
    including state, PID, creation time, and backend-specific details.

    Attributes:
        name: Session name.
        state: Current state (running, stopped, exited, unknown).
        backend: Backend type used for this session.
        pid: Process ID (tmux server PID or container main PID).
        created_at: ISO timestamp when the session was created.
        window_count: Number of tmux windows (tmux backend only).
        image: Container image name (container backend only).
        exit_code: Container exit code if exited (container backend only).

    Examples:
        >>> status = SessionStatus(
        ...     name="astro",
        ...     state=SessionState.RUNNING,
        ...     backend=BackendType.TMUX,
        ...     pid=12345,
        ...     window_count=1,
        ... )

        >>> status = SessionStatus(
        ...     name="astro-prod",
        ...     state=SessionState.RUNNING,
        ...     backend=BackendType.CONTAINER,
        ...     pid=67890,
        ...     image="astro-bot:latest",
        ... )
    """

    name: str
    state: SessionState
    backend: BackendType
    pid: int | None = None
    created_at: str | None = None
    # tmux-specific
    window_count: int = 0
    # container-specific
    image: str | None = None
    exit_code: int | None = None


__all__ = [
    "BackendType",
    "SessionConfig",
    "SessionState",
    "SessionStatus",
]
