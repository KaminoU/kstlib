"""Attach to a session."""

from __future__ import annotations

from kstlib.cli.common import exit_error
from kstlib.ops.exceptions import OpsError, SessionNotFoundError

from .common import (
    BACKEND_OPTION,
    SESSION_ARGUMENT,
    get_session_manager,
)


def attach(
    name: str = SESSION_ARGUMENT,
    backend: str | None = BACKEND_OPTION,
) -> None:
    """Attach to a running session.

    Attaches the current terminal to a tmux session or container.
    This command replaces the current process.

    For tmux: Use Ctrl+B D to detach.
    For container: Use Ctrl+P Ctrl+Q to detach.

    Examples:
        kstlib ops attach dev
        kstlib ops attach prod --backend container
    """
    try:
        manager = get_session_manager(name, backend=backend)

        if not manager.exists():
            exit_error(f"Session '{name}' not found.")

        if not manager.is_running():
            exit_error(f"Session '{name}' is not running.")

        # This replaces the current process and does not return
        manager.attach()

    except SessionNotFoundError:
        exit_error(f"Session '{name}' not found.")
    except OpsError as e:
        exit_error(str(e))


__all__ = ["attach"]
