"""Session management with tmux and container backends.

This module provides config-driven session management for running
persistent processes like trading bots. It supports two backends:

- **tmux**: For local development and backtesting with detach/attach
- **container**: For production with Podman/Docker and persistent logs

The module is designed around the principle of backend abstraction,
allowing the same code to work with either tmux sessions or containers.

Examples:
    Local development with tmux:

    >>> from kstlib.ops import SessionManager
    >>> session = SessionManager("astro", backend="tmux")
    >>> session.start("python -m astro.bot")  # doctest: +SKIP
    >>> session.attach()  # tmux attach-session -t astro  # doctest: +SKIP

    Production with containers:

    >>> session = SessionManager(
    ...     "astro",
    ...     backend="container",
    ...     image="astro-bot:latest",
    ... )
    >>> session.start()  # doctest: +SKIP
    >>> session.attach()  # podman attach astro  # doctest: +SKIP

    Config-driven usage:

    >>> session = SessionManager.from_config("astro")  # doctest: +SKIP
    >>> session.start()  # doctest: +SKIP

Note:
    The attach() method uses os.execvp and replaces the current process.
    It does not return on success.
"""

from kstlib.ops.base import AbstractRunner
from kstlib.ops.container import ContainerRunner
from kstlib.ops.exceptions import (
    BackendNotFoundError,
    ContainerRuntimeNotFoundError,
    OpsError,
    SessionAmbiguousError,
    SessionAttachError,
    SessionError,
    SessionExistsError,
    SessionNotFoundError,
    SessionStartError,
    SessionStopError,
    TmuxNotFoundError,
)
from kstlib.ops.manager import SessionConfigError, SessionManager, auto_detect_backend
from kstlib.ops.models import (
    BackendType,
    SessionConfig,
    SessionState,
    SessionStatus,
)
from kstlib.ops.tmux import TmuxRunner

__all__ = [
    "AbstractRunner",
    "BackendNotFoundError",
    "BackendType",
    "ContainerRunner",
    "ContainerRuntimeNotFoundError",
    "OpsError",
    "SessionAmbiguousError",
    "SessionAttachError",
    "SessionConfig",
    "SessionConfigError",
    "SessionError",
    "SessionExistsError",
    "SessionManager",
    "SessionNotFoundError",
    "SessionStartError",
    "SessionState",
    "SessionStatus",
    "SessionStopError",
    "TmuxNotFoundError",
    "TmuxRunner",
    "auto_detect_backend",
]
