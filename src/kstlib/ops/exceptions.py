"""Specialized exceptions raised by the kstlib.ops module.

Exception hierarchy::

    KstlibError
        OpsError (base for all ops errors)
            BackendNotFoundError (binary not in PATH)
                TmuxNotFoundError
                ContainerRuntimeNotFoundError
            SessionError (session-related errors)
                SessionExistsError
                SessionNotFoundError
                SessionStartError
                SessionAttachError
                SessionStopError
                SessionAmbiguousError
"""

from __future__ import annotations

from kstlib.config.exceptions import KstlibError


class OpsError(KstlibError):
    """Base exception for all ops module errors.

    All ops-specific exceptions inherit from this class,
    allowing for easy catching of any ops error.
    """


# ============================================================================
# Backend errors (binary not found)
# ============================================================================


class BackendNotFoundError(OpsError, FileNotFoundError):
    """Backend binary (tmux, podman, docker) not found in PATH.

    Raised when the required backend binary is not installed or not
    accessible from the current PATH.
    """


class TmuxNotFoundError(BackendNotFoundError):
    """tmux binary not found in PATH.

    Install tmux to use the tmux backend:
    - macOS: brew install tmux
    - Ubuntu/Debian: apt install tmux
    - Windows: Use WSL2 with tmux installed
    """


class ContainerRuntimeNotFoundError(BackendNotFoundError):
    """Container runtime (podman or docker) not found in PATH.

    Install podman or docker to use the container backend:
    - Podman: https://podman.io/getting-started/installation
    - Docker: https://docs.docker.com/get-docker/
    """


# ============================================================================
# Session errors
# ============================================================================


class SessionError(OpsError):
    """Base exception for session-related errors.

    All session operation exceptions inherit from this class.
    """


class SessionExistsError(SessionError):
    """Session or container with this name already exists.

    Raised when attempting to create a session with a name that is
    already in use by another session or container.
    """

    def __init__(self, name: str, backend: str) -> None:
        """Initialize SessionExistsError.

        Args:
            name: The session name that already exists.
            backend: The backend type (tmux, container).
        """
        super().__init__(f"{backend} session '{name}' already exists")
        self.name = name
        self.backend = backend


class SessionNotFoundError(SessionError):
    """Session or container not found.

    Raised when attempting to access a session that does not exist.
    """

    def __init__(self, name: str, backend: str) -> None:
        """Initialize SessionNotFoundError.

        Args:
            name: The session name that was not found.
            backend: The backend type (tmux, container).
        """
        super().__init__(f"{backend} session '{name}' not found")
        self.name = name
        self.backend = backend


class SessionStartError(SessionError):
    """Failed to start session or container.

    Raised when the backend command to create a new session fails.
    """

    def __init__(self, name: str, backend: str, reason: str) -> None:
        """Initialize SessionStartError.

        Args:
            name: The session name that failed to start.
            backend: The backend type (tmux, container).
            reason: The reason for the failure.
        """
        super().__init__(f"Failed to start {backend} session '{name}': {reason}")
        self.name = name
        self.backend = backend
        self.reason = reason


class SessionAttachError(SessionError):
    """Failed to attach to session or container.

    Raised when the backend command to attach to a session fails.
    This can happen if the session is not running or if the terminal
    is not interactive.
    """

    def __init__(self, name: str, backend: str, reason: str) -> None:
        """Initialize SessionAttachError.

        Args:
            name: The session name that failed to attach.
            backend: The backend type (tmux, container).
            reason: The reason for the failure.
        """
        super().__init__(f"Failed to attach to {backend} session '{name}': {reason}")
        self.name = name
        self.backend = backend
        self.reason = reason


class SessionStopError(SessionError):
    """Failed to stop session or container.

    Raised when the backend command to stop a session fails.
    """

    def __init__(self, name: str, backend: str, reason: str) -> None:
        """Initialize SessionStopError.

        Args:
            name: The session name that failed to stop.
            backend: The backend type (tmux, container).
            reason: The reason for the failure.
        """
        super().__init__(f"Failed to stop {backend} session '{name}': {reason}")
        self.name = name
        self.backend = backend
        self.reason = reason


class SessionAmbiguousError(SessionError):
    """Session exists in multiple backends.

    Raised when auto-detection finds a session in both tmux and container
    backends, requiring explicit backend specification.
    """

    def __init__(self, name: str, backends: list[str]) -> None:
        """Initialize SessionAmbiguousError.

        Args:
            name: The session name that exists in multiple backends.
            backends: List of backend names where the session was found.
        """
        backend_list = ", ".join(backends)
        super().__init__(
            f"Session '{name}' found in multiple backends: {backend_list}. Use --backend to specify which one."
        )
        self.name = name
        self.backends = backends


__all__ = [
    "BackendNotFoundError",
    "ContainerRuntimeNotFoundError",
    "OpsError",
    "SessionAmbiguousError",
    "SessionAttachError",
    "SessionError",
    "SessionExistsError",
    "SessionNotFoundError",
    "SessionStartError",
    "SessionStopError",
    "TmuxNotFoundError",
]
