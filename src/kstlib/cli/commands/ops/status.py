"""Show session status."""

from __future__ import annotations

import json as json_lib

from rich.table import Table

from kstlib.cli.common import console, exit_error
from kstlib.ops import SessionManager
from kstlib.ops.exceptions import OpsError, SessionNotFoundError
from kstlib.ops.models import SessionState, SessionStatus
from kstlib.utils.formatting import format_timestamp

from .common import (
    BACKEND_OPTION,
    JSON_OPTION,
    QUIET_OPTION,
    SESSION_ARGUMENT,
    get_session_manager,
)


def _config_fallback_status(name: str) -> SessionStatus | None:
    """Try to build a DEFINED status from config for a non-running session.

    Args:
        name: Session name to look up in config.

    Returns:
        SessionStatus with DEFINED state, or None if not in config.
    """
    try:
        manager = SessionManager.from_config(name)
    except OpsError:
        return None

    return SessionStatus(
        name=name,
        state=SessionState.DEFINED,
        backend=manager.config.backend,
        image=manager.config.image,
    )


def _format_created_at(created_at: str | None) -> str | None:
    """Format created_at value for display.

    Args:
        created_at: Raw created_at value (epoch string or ISO format).

    Returns:
        Formatted datetime string, or None if no value.
    """
    if not created_at:
        return None
    try:
        float(created_at)
        return format_timestamp(created_at)
    except ValueError:
        # Already formatted (ISO from Docker), keep as-is
        return created_at


def status(
    name: str = SESSION_ARGUMENT,
    backend: str | None = BACKEND_OPTION,
    quiet: bool = QUIET_OPTION,
    json: bool = JSON_OPTION,
) -> None:
    """Show status of a session.

    Displays detailed information about a session including its state,
    PID, backend type, and other relevant details.

    Examples:
        kstlib ops status dev
        kstlib ops status prod --json
    """
    try:
        manager = get_session_manager(name, backend=backend)

        if not manager.exists():
            # Try config fallback for defined-but-not-started sessions
            session_status = _config_fallback_status(name)
            if session_status is None:
                exit_error(f"Session '{name}' not found.")
        else:
            session_status = manager.status()

        if json:
            # JSON output
            data = {
                "name": session_status.name,
                "state": session_status.state.value,
                "backend": session_status.backend.value,
                "pid": session_status.pid,
                "created_at": session_status.created_at,
                "window_count": session_status.window_count,
                "image": session_status.image,
                "exit_code": session_status.exit_code,
            }
            console.print(json_lib.dumps(data, indent=2))
            return

        if quiet:
            console.print(f"{name}: {session_status.state.value}")
            return

        # Rich table output
        table = Table(title=f"Session: {name}")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="white")

        table.add_row("State", session_status.state.value)
        table.add_row("Backend", session_status.backend.value)

        # Add optional fields as rows (reduces branching complexity)
        optional_rows = [
            ("PID", str(session_status.pid) if session_status.pid else None),
            ("Created", _format_created_at(session_status.created_at)),
            ("Windows", str(session_status.window_count) if session_status.window_count > 0 else None),
            ("Image", session_status.image),
            ("Exit Code", str(session_status.exit_code) if session_status.exit_code is not None else None),
        ]
        for label, value in optional_rows:
            if value:
                table.add_row(label, value)

        console.print(table)

    except SessionNotFoundError:
        exit_error(f"Session '{name}' not found.")
    except OpsError as e:
        exit_error(str(e))


__all__ = ["status"]
