"""List all sessions."""

from __future__ import annotations

import json as json_lib
import logging
from typing import Any

from rich.table import Table

from kstlib.cli.common import console
from kstlib.config import get_config
from kstlib.ops import (
    ContainerRunner,
    SessionStatus,
    TmuxRunner,
)
from kstlib.ops.exceptions import BackendNotFoundError
from kstlib.ops.models import BackendType, SessionState
from kstlib.ops.validators import (
    validate_command,
    validate_env,
    validate_image_name,
    validate_ports,
    validate_session_name,
    validate_volumes,
)

from .common import (
    BACKEND_OPTION,
    JSON_OPTION,
)

log = logging.getLogger(__name__)

# Maximum number of config sessions to prevent DoS via large config
_MAX_CONFIG_SESSIONS = 50

_VALID_BACKENDS = {"tmux", "container"}

_STATE_STYLES: dict[str, str] = {
    "running": "green",
    "defined": "dim",
    "exited": "yellow",
    "stopped": "yellow",
    "unknown": "red",
}


def _load_config_sessions() -> dict[str, dict[str, Any]]:
    """Load session definitions from kstlib configuration.

    Reads ``ops.sessions`` from the config file and validates
    each entry with deep defense checks.

    Returns:
        Validated session configs keyed by session name.
    """
    config = get_config()
    ops_config: dict[str, Any] = config.get("ops", {})  # type: ignore[no-untyped-call]
    raw_sessions: Any = ops_config.get("sessions", {})

    # Deep defense: sessions must be a dict
    if not isinstance(raw_sessions, dict):
        log.warning("ops.sessions is not a dict, ignoring config sessions")
        return {}

    # Deep defense: limit number of sessions
    if len(raw_sessions) > _MAX_CONFIG_SESSIONS:
        log.warning(
            "ops.sessions has %d entries (max %d), truncating",
            len(raw_sessions),
            _MAX_CONFIG_SESSIONS,
        )
        # Take only first N entries
        raw_sessions = dict(list(raw_sessions.items())[:_MAX_CONFIG_SESSIONS])

    validated: dict[str, dict[str, Any]] = {}
    for name, data in raw_sessions.items():
        if not isinstance(data, dict):
            log.warning("Session '%s' config is not a dict, skipping", name)
            continue

        try:
            _validate_config_session(name, data)
        except ValueError as exc:
            log.warning("Invalid config session '%s': %s", name, exc)
            continue

        validated[name] = data

    return validated


def _validate_config_session(name: str, data: dict[str, Any]) -> None:
    """Validate a single config session entry.

    Args:
        name: Session name (YAML key).
        data: Session configuration dict.

    Raises:
        ValueError: If any field is invalid.
    """
    validate_session_name(name)

    backend = data.get("backend", "tmux")
    if backend not in _VALID_BACKENDS:
        raise ValueError(f"Invalid backend '{backend}'")

    image = data.get("image")
    if image is not None:
        validate_image_name(image)

    command = data.get("command")
    if command is not None:
        validate_command(command)

    env = data.get("env")
    if env is not None:
        if not isinstance(env, dict):
            raise ValueError("env must be a dict")
        validate_env(env)

    volumes = data.get("volumes")
    if volumes is not None:
        if not isinstance(volumes, list):
            raise ValueError("volumes must be a list")
        validate_volumes(volumes)

    ports = data.get("ports")
    if ports is not None:
        if not isinstance(ports, list):
            raise ValueError("ports must be a list")
        validate_ports(ports)


def _collect_sessions(backend: str | None) -> list[SessionStatus]:
    """Collect sessions from runtime backends and config definitions.

    Merges runtime sessions with config-defined sessions. Config sessions
    that are not currently running appear with state DEFINED.

    Args:
        backend: Backend to query, or None for all.

    Returns:
        List of SessionStatus from queried backends plus config-defined sessions.
    """
    sessions: list[SessionStatus] = []

    # Collect from tmux
    if backend is None or backend == "tmux":
        try:
            tmux = TmuxRunner()
            sessions.extend(tmux.list_sessions())
        except BackendNotFoundError:
            pass

    # Collect from container
    if backend is None or backend == "container":
        try:
            container = ContainerRunner()
            sessions.extend(container.list_sessions())
        except BackendNotFoundError:
            pass

    # Merge config-defined sessions
    runtime_names: set[str] = {s.name for s in sessions}
    config_sessions = _load_config_sessions()

    for name, data in config_sessions.items():
        if name in runtime_names:
            continue

        session_backend = data.get("backend", "tmux")

        # Apply backend filter to config sessions too
        if backend is not None and session_backend != backend:
            continue

        backend_type = BackendType(session_backend)
        sessions.append(
            SessionStatus(
                name=name,
                state=SessionState.DEFINED,
                backend=backend_type,
                image=data.get("image"),
            ),
        )

    return sessions


def list_sessions(
    backend: str | None = BACKEND_OPTION,
    json: bool = JSON_OPTION,
) -> None:
    """List all sessions.

    Shows all tmux sessions and containers managed by the ops module,
    plus config-defined sessions that have not been started yet.
    Can be filtered by backend type.

    Examples:
        kstlib ops list
        kstlib ops list --backend tmux
        kstlib ops list --backend container --json
    """
    sessions = _collect_sessions(backend)

    if json:
        # JSON output
        data = [
            {
                "name": s.name,
                "state": s.state.value,
                "backend": s.backend.value,
                "pid": s.pid,
                "image": s.image,
            }
            for s in sessions
        ]
        console.print(json_lib.dumps(data, indent=2))
        return

    if not sessions:
        console.print("[dim]No sessions found.[/]")
        return

    # Rich table output
    table = Table(title="Sessions")
    table.add_column("Name", style="cyan")
    table.add_column("State", style="white")
    table.add_column("Backend", style="blue")
    table.add_column("PID", style="dim")
    table.add_column("Image", style="dim")

    for session in sessions:
        state_style = _STATE_STYLES.get(session.state.value, "yellow")
        table.add_row(
            session.name,
            f"[{state_style}]{session.state.value}[/]",
            session.backend.value,
            str(session.pid) if session.pid else "-",
            session.image or "-",
        )

    console.print(table)


__all__ = ["list_sessions"]
