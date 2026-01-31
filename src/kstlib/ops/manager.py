"""Session manager facade for unified backend access.

This module provides the SessionManager class, a config-driven facade
that abstracts the underlying backend (tmux or container) and provides
a unified interface for session management.

Features:
- Automatic backend selection based on configuration
- Config-driven session creation from kstlib.conf.yml
- Unified API for start, stop, attach, status, and logs
- Support for both tmux and container backends

Example:
    >>> from kstlib.ops import SessionManager
    >>> # Local dev with tmux
    >>> session = SessionManager("dev", backend="tmux")
    >>> session.start("python -m app")  # doctest: +SKIP
    >>> session.attach()  # doctest: +SKIP

    >>> # From config file
    >>> session = SessionManager.from_config("astro")  # doctest: +SKIP
    >>> session.start()  # doctest: +SKIP
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from kstlib.ops.container import ContainerRunner
from kstlib.ops.exceptions import (
    ContainerRuntimeNotFoundError,
    OpsError,
    SessionAmbiguousError,
    TmuxNotFoundError,
)
from kstlib.ops.models import BackendType, SessionConfig, SessionState, SessionStatus
from kstlib.ops.tmux import TmuxRunner
from kstlib.ops.validators import validate_session_name

if TYPE_CHECKING:
    from kstlib.ops.base import AbstractRunner

logger = logging.getLogger(__name__)


def auto_detect_backend(name: str) -> BackendType | None:
    """Auto-detect which backend a session exists in.

    Checks both tmux and container backends to find where a session with
    the given name exists. Skips backends that are not available (binary
    not found).

    Args:
        name: Session name to search for.

    Returns:
        BackendType if found in exactly one backend, None if not found.

    Raises:
        SessionAmbiguousError: If session exists in multiple backends.

    Examples:
        >>> # Session exists in tmux only
        >>> backend = auto_detect_backend("mybot")  # doctest: +SKIP
        >>> backend == BackendType.TMUX  # doctest: +SKIP
        True

        >>> # Session not found
        >>> auto_detect_backend("nonexistent") is None  # doctest: +SKIP
        True
    """
    found_in: list[str] = []

    # Check tmux backend (skip if not installed)
    try:
        tmux_runner = TmuxRunner()
        if tmux_runner.exists(name):
            found_in.append("tmux")
    except TmuxNotFoundError:
        logger.debug("tmux not found, skipping tmux backend check")

    # Check container backend (skip if not installed)
    try:
        container_runner = ContainerRunner()
        if container_runner.exists(name):
            found_in.append("container")
    except ContainerRuntimeNotFoundError:
        logger.debug("container runtime not found, skipping container backend check")

    # Return based on findings
    if len(found_in) == 0:
        return None
    if len(found_in) == 1:
        return BackendType(found_in[0])
    # Found in multiple backends
    raise SessionAmbiguousError(name, found_in)


class SessionConfigError(OpsError):
    """Configuration error for session management.

    Raised when session configuration is invalid or missing required fields.
    """


class SessionManager:
    """Config-driven session manager with backend abstraction.

    Provides a unified interface for managing sessions across different
    backends (tmux, container). The backend can be specified directly
    or loaded from kstlib.conf.yml configuration.

    Args:
        name: Unique session name.
        backend: Backend type ("tmux" or "container").
        **kwargs: Backend-specific options (image, volumes, ports, etc.).

    Attributes:
        name: The session name.
        backend: The backend type being used.
        config: The full session configuration.

    Examples:
        >>> # Direct instantiation with tmux
        >>> session = SessionManager("dev", backend="tmux")
        >>> session.start("python app.py")  # doctest: +SKIP
        >>> session.attach()  # doctest: +SKIP

        >>> # Direct instantiation with container
        >>> session = SessionManager(
        ...     "prod",
        ...     backend="container",
        ...     image="app:latest",
        ...     volumes=["./data:/app/data"],
        ... )
        >>> session.start()  # doctest: +SKIP

        >>> # From config file (recommended)
        >>> session = SessionManager.from_config("astro")  # doctest: +SKIP
    """

    def __init__(
        self,
        name: str,
        *,
        backend: str | BackendType = BackendType.TMUX,
        **kwargs: Any,
    ) -> None:
        """Initialize SessionManager.

        Args:
            name: Unique session name.
            backend: Backend type ("tmux" or "container").
            **kwargs: Backend-specific options.

        Raises:
            SessionConfigError: If configuration is invalid.
        """
        # Validate session name early for better error messages
        try:
            validate_session_name(name)
        except ValueError as e:
            raise SessionConfigError(str(e)) from None

        self._name = name

        # Normalize backend type
        if isinstance(backend, BackendType):
            self._backend = backend
        else:
            # Must be a string - convert to BackendType
            try:
                self._backend = BackendType(backend.lower())
            except ValueError:
                raise SessionConfigError(f"Invalid backend '{backend}'. Must be 'tmux' or 'container'.") from None

        # Build session config (validation happens in SessionConfig.__post_init__)
        try:
            self._config = SessionConfig(
                name=name,
                backend=self._backend,
                command=kwargs.get("command"),
                working_dir=kwargs.get("working_dir"),
                env=kwargs.get("env", {}),
                image=kwargs.get("image"),
                volumes=kwargs.get("volumes", []),
                ports=kwargs.get("ports", []),
                runtime=kwargs.get("runtime"),
                log_volume=kwargs.get("log_volume"),
            )
        except ValueError as e:
            raise SessionConfigError(str(e)) from None

        # Initialize the appropriate runner
        self._runner: AbstractRunner
        if self._backend == BackendType.TMUX:
            tmux_binary = kwargs.get("tmux_binary", "tmux")
            self._runner = TmuxRunner(binary=tmux_binary)
        else:
            runtime = kwargs.get("runtime")  # None = auto-detect
            self._runner = ContainerRunner(runtime=runtime)

    @property
    def name(self) -> str:
        """Return the session name."""
        return self._name

    @property
    def backend(self) -> BackendType:
        """Return the backend type."""
        return self._backend

    @property
    def config(self) -> SessionConfig:
        """Return the session configuration."""
        return self._config

    @classmethod
    def from_config(
        cls,
        name: str,
    ) -> SessionManager:
        """Create SessionManager from kstlib configuration.

        Loads session configuration from kstlib.conf.yml under the
        ops.sessions.{name} key.

        Args:
            name: Session name to load from config.

        Returns:
            SessionManager configured from the config file.

        Raises:
            SessionConfigError: If session not found in config.

        Example:
            Config file (kstlib.conf.yml)::

                ops:
                  sessions:
                    astro:
                      backend: tmux
                      command: "python -m astro.bot"
                      working_dir: "/opt/astro"

            Usage::

                >>> session = SessionManager.from_config("astro")  # doctest: +SKIP
        """
        from kstlib.config import get_config

        config = get_config()

        # Navigate to ops.sessions (Box is dynamically typed)
        ops_config: dict[str, Any] = config.get("ops", {})  # type: ignore[no-untyped-call]
        sessions_config: dict[str, Any] = ops_config.get("sessions", {})

        if name not in sessions_config:
            available = list(sessions_config)
            raise SessionConfigError(f"Session '{name}' not found in config. Available sessions: {available or 'none'}")

        session_data = sessions_config[name]

        # Get defaults from ops config
        default_backend = ops_config.get("default_backend", "tmux")
        tmux_binary = ops_config.get("tmux_binary", "tmux")
        container_runtime = ops_config.get("container_runtime")  # None = auto-detect

        # Build kwargs from session config
        backend = session_data.get("backend", default_backend)
        kwargs: dict[str, Any] = {
            "backend": backend,
            "command": session_data.get("command"),
            "working_dir": session_data.get("working_dir"),
            "env": session_data.get("env", {}),
            "image": session_data.get("image"),
            "volumes": session_data.get("volumes", []),
            "ports": session_data.get("ports", []),
            "log_volume": session_data.get("log_volume"),
            "tmux_binary": tmux_binary,
            "runtime": session_data.get("runtime", container_runtime),
        }

        return cls(name, **kwargs)

    def start(
        self,
        command: str | None = None,
        **kwargs: Any,
    ) -> SessionStatus:
        """Start the session.

        Args:
            command: Command to run (overrides config).
            **kwargs: Additional options to override config.

        Returns:
            SessionStatus with current state.

        Raises:
            SessionExistsError: If session already exists.
            SessionStartError: If session failed to start.
        """
        # Build effective config with overrides
        config_dict = {
            "name": self._name,
            "backend": self._backend,
            "command": command or self._config.command,
            "working_dir": kwargs.get("working_dir", self._config.working_dir),
            "env": {**self._config.env, **kwargs.get("env", {})},
            "image": kwargs.get("image", self._config.image),
            "volumes": kwargs.get("volumes", list(self._config.volumes)),
            "ports": kwargs.get("ports", list(self._config.ports)),
            "runtime": kwargs.get("runtime", self._config.runtime),
            "log_volume": kwargs.get("log_volume", self._config.log_volume),
        }

        effective_config = SessionConfig(**config_dict)
        return self._runner.start(effective_config)

    def stop(
        self,
        *,
        graceful: bool = True,
        timeout: int = 10,
    ) -> bool:
        """Stop the session.

        Args:
            graceful: If True, attempt graceful shutdown first.
            timeout: Seconds to wait for graceful shutdown.

        Returns:
            True if stopped successfully.

        Raises:
            SessionNotFoundError: If session does not exist.
            SessionStopError: If session could not be stopped.
        """
        return self._runner.stop(self._name, graceful=graceful, timeout=timeout)

    def attach(self) -> None:
        """Attach to the session.

        This method replaces the current process. It does not return on success.

        Raises:
            SessionNotFoundError: If session does not exist.
            SessionAttachError: If attachment failed.
        """
        self._runner.attach(self._name)

    def status(self) -> SessionStatus:
        """Get current session status.

        Returns:
            SessionStatus with current state.

        Raises:
            SessionNotFoundError: If session does not exist.
        """
        return self._runner.status(self._name)

    def logs(self, lines: int = 100) -> str:
        """Get recent session logs.

        Args:
            lines: Number of lines to retrieve.

        Returns:
            Log output as string (ANSI codes preserved).

        Raises:
            SessionNotFoundError: If session does not exist.
        """
        return self._runner.logs(self._name, lines=lines)

    def exists(self) -> bool:
        """Check if the session exists.

        Returns:
            True if session exists, False otherwise.
        """
        return self._runner.exists(self._name)

    def is_running(self) -> bool:
        """Check if the session is currently running.

        Returns:
            True if running, False otherwise.
        """
        if not self.exists():
            return False
        try:
            status = self.status()
            return status.state == SessionState.RUNNING
        except Exception:
            return False


__all__ = [
    "SessionConfigError",
    "SessionManager",
    "auto_detect_backend",
]
