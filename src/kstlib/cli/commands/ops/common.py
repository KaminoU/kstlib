"""Shared options and utilities for ops CLI commands."""

from __future__ import annotations

from typing import Any

import typer

from kstlib.cli.common import CommandResult, CommandStatus, exit_error
from kstlib.ops import SessionManager
from kstlib.ops.exceptions import OpsError, SessionAmbiguousError
from kstlib.ops.manager import auto_detect_backend

# ============================================================================
# Shared Arguments and Options
# ============================================================================


SESSION_ARGUMENT = typer.Argument(
    ...,
    help="Session name.",
    metavar="NAME",
)

BACKEND_OPTION = typer.Option(
    None,
    "--backend",
    "-b",
    help="Backend type (tmux or container). If not specified, uses config default.",
)

IMAGE_OPTION = typer.Option(
    None,
    "--image",
    "-i",
    help="Container image (container backend only).",
)

COMMAND_OPTION = typer.Option(
    None,
    "--command",
    "-c",
    help="Command to run in the session.",
)

QUIET_OPTION = typer.Option(
    False,
    "--quiet",
    "-q",
    help="Minimal output.",
)

JSON_OPTION = typer.Option(
    False,
    "--json",
    help="Output in JSON format.",
)

WORKDIR_OPTION = typer.Option(
    None,
    "--workdir",
    "-w",
    help="Working directory for the session.",
)

ENV_OPTION = typer.Option(
    None,
    "--env",
    "-e",
    help="Environment variable (KEY=VALUE). Can be repeated.",
)

VOLUME_OPTION = typer.Option(
    None,
    "--volume",
    "-v",
    help="Volume mount (host:container). Can be repeated.",
)

PORT_OPTION = typer.Option(
    None,
    "--port",
    "-p",
    help="Port mapping (host:container). Can be repeated.",
)

FORCE_OPTION = typer.Option(
    False,
    "--force",
    "-f",
    help="Force stop without graceful shutdown.",
)

TIMEOUT_OPTION = typer.Option(
    10,
    "--timeout",
    "-t",
    help="Seconds to wait for graceful shutdown.",
)

LINES_OPTION = typer.Option(
    100,
    "--lines",
    "-n",
    help="Number of lines to show.",
)


# ============================================================================
# Helper Functions
# ============================================================================


def _rebuild_with_overrides(
    name: str,
    manager: SessionManager,
    *,
    backend: str | None,
    image: str | None,
    command: str | None,
) -> SessionManager:
    """Rebuild a config-loaded SessionManager with CLI overrides.

    Args:
        name: Session name.
        manager: Original config-loaded manager.
        backend: CLI backend override (or None).
        image: CLI image override (or None).
        command: CLI command override (or None).

    Returns:
        New SessionManager with overrides applied.
    """
    cfg = manager.config
    kwargs: dict[str, Any] = {
        "backend": backend or cfg.backend.value,
        "command": command or cfg.command,
        "working_dir": cfg.working_dir,
        "env": cfg.env,
        "image": image or cfg.image,
        "volumes": list(cfg.volumes),
        "ports": list(cfg.ports),
        "runtime": cfg.runtime,
        "log_volume": cfg.log_volume,
    }
    return SessionManager(name, **kwargs)


def _try_from_config(
    name: str,
    *,
    backend: str | None,
    image: str | None,
    command: str | None,
) -> SessionManager | None:
    """Try to load a SessionManager from config, with CLI overrides.

    Args:
        name: Session name.
        backend: CLI backend override (or None).
        image: CLI image override (or None).
        command: CLI command override (or None).

    Returns:
        SessionManager if found in config, None otherwise.
    """
    try:
        manager = SessionManager.from_config(name)
    except OpsError:
        return None
    if backend or image or command:
        return _rebuild_with_overrides(
            name,
            manager,
            backend=backend,
            image=image,
            command=command,
        )
    return manager


def get_session_manager(
    name: str,
    *,
    backend: str | None = None,
    image: str | None = None,
    command: str | None = None,
    from_config: bool = True,
) -> SessionManager:
    """Get or create a SessionManager.

    Tries to load session configuration from kstlib.conf.yml first,
    then applies CLI arguments as overrides. Falls back to auto-detection
    or explicit options if the session is not defined in config.

    Args:
        name: Session name.
        backend: Override backend type.
        image: Container image (for container backend).
        command: Command to run.
        from_config: If True, try to load from config first.

    Returns:
        SessionManager instance.

    Raises:
        typer.Exit: On configuration error or ambiguous session.
    """
    try:
        # Try to load from config first (CLI args override config values)
        if from_config:
            manager = _try_from_config(name, backend=backend, image=image, command=command)
            if manager is not None:
                return manager

        # Auto-detect backend if not specified
        if backend is None:
            detected = auto_detect_backend(name)
            if detected is not None:
                backend = detected.value

        # Create with explicit options
        kwargs: dict[str, Any] = {}
        if backend:
            kwargs["backend"] = backend
        if image:
            kwargs["image"] = image
        if command:
            kwargs["command"] = command

        return SessionManager(name, **kwargs)
    except SessionAmbiguousError as e:
        exit_error(str(e))
    except OpsError as e:
        exit_error(str(e))


def handle_ops_error(e: OpsError) -> CommandResult:
    """Convert an OpsError to a CommandResult.

    Args:
        e: The OpsError exception.

    Returns:
        CommandResult with error status.
    """
    return CommandResult(
        status=CommandStatus.ERROR,
        message=str(e),
    )


__all__ = [
    "BACKEND_OPTION",
    "COMMAND_OPTION",
    "ENV_OPTION",
    "FORCE_OPTION",
    "IMAGE_OPTION",
    "JSON_OPTION",
    "LINES_OPTION",
    "PORT_OPTION",
    "QUIET_OPTION",
    "SESSION_ARGUMENT",
    "TIMEOUT_OPTION",
    "VOLUME_OPTION",
    "WORKDIR_OPTION",
    "get_session_manager",
    "handle_ops_error",
]
