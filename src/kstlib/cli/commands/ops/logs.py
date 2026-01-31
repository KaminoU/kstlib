"""Show session logs."""

from __future__ import annotations

from kstlib.cli.common import console, exit_error
from kstlib.ops.exceptions import OpsError, SessionNotFoundError

from .common import (
    BACKEND_OPTION,
    LINES_OPTION,
    SESSION_ARGUMENT,
    get_session_manager,
)


def logs(
    name: str = SESSION_ARGUMENT,
    backend: str | None = BACKEND_OPTION,
    lines: int = LINES_OPTION,
) -> None:
    """Show logs from a session.

    Retrieves and displays recent output from a tmux session or container.
    ANSI color codes are preserved in the output.

    Examples:
        kstlib ops logs dev
        kstlib ops logs prod --lines 50
    """
    try:
        manager = get_session_manager(name, backend=backend)

        if not manager.exists():
            exit_error(f"Session '{name}' not found.")

        log_content = manager.logs(lines=lines)

        if log_content.strip():
            console.print(log_content, markup=False)
        else:
            console.print(f"[dim]No logs available for session '{name}'.[/]")

    except SessionNotFoundError:
        exit_error(f"Session '{name}' not found.")
    except OpsError as e:
        exit_error(str(e))


__all__ = ["logs"]
