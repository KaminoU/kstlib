"""Stop a session."""

from __future__ import annotations

from kstlib.cli.common import (
    CommandResult,
    CommandStatus,
    emit_result,
    exit_error,
)
from kstlib.ops.exceptions import OpsError, SessionNotFoundError

from .common import (
    BACKEND_OPTION,
    FORCE_OPTION,
    QUIET_OPTION,
    SESSION_ARGUMENT,
    TIMEOUT_OPTION,
    get_session_manager,
)


def stop(
    name: str = SESSION_ARGUMENT,
    backend: str | None = BACKEND_OPTION,
    quiet: bool = QUIET_OPTION,
    force: bool = FORCE_OPTION,
    timeout: int = TIMEOUT_OPTION,
) -> None:
    """Stop a running session.

    Stops a tmux session or container. By default, attempts a graceful
    shutdown first, then forces termination if the timeout is exceeded.

    Examples:
        kstlib ops stop dev
        kstlib ops stop prod --force
        kstlib ops stop bot --timeout 30
    """
    try:
        manager = get_session_manager(name, backend=backend)

        if not manager.exists():
            exit_error(f"Session '{name}' not found.")

        manager.stop(graceful=not force, timeout=timeout)

        result = CommandResult(
            status=CommandStatus.OK,
            message=f"Session '{name}' stopped.",
        )
        emit_result(result, quiet)

    except SessionNotFoundError:
        exit_error(f"Session '{name}' not found.")
    except OpsError as e:
        exit_error(str(e))


__all__ = ["stop"]
