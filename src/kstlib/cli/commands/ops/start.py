"""Start a session."""

from __future__ import annotations

from kstlib.cli.common import (
    CommandResult,
    CommandStatus,
    emit_result,
    exit_error,
)
from kstlib.ops.exceptions import OpsError, SessionExistsError

from .common import (
    BACKEND_OPTION,
    COMMAND_OPTION,
    ENV_OPTION,
    IMAGE_OPTION,
    PORT_OPTION,
    QUIET_OPTION,
    SESSION_ARGUMENT,
    VOLUME_OPTION,
    WORKDIR_OPTION,
    get_session_manager,
)


def start(  # noqa: PLR0913
    name: str = SESSION_ARGUMENT,
    backend: str | None = BACKEND_OPTION,
    command: str | None = COMMAND_OPTION,
    image: str | None = IMAGE_OPTION,
    quiet: bool = QUIET_OPTION,
    working_dir: str | None = WORKDIR_OPTION,
    env: list[str] | None = ENV_OPTION,
    volume: list[str] | None = VOLUME_OPTION,
    port: list[str] | None = PORT_OPTION,
) -> None:
    """Start a new session.

    Creates and starts a new tmux session or container with the specified
    configuration. If the session is defined in kstlib.conf.yml, those
    settings will be used as defaults.

    Examples:
        kstlib ops start dev --backend tmux --command "python app.py"
        kstlib ops start prod --backend container --image app:latest
        kstlib ops start astro  # Uses config from kstlib.conf.yml
    """
    # Parse environment variables
    env_dict: dict[str, str] = {}
    if env:
        for item in env:
            if "=" in item:
                key, value = item.split("=", 1)
                env_dict[key] = value
            else:
                exit_error(f"Invalid environment variable format: {item}")

    try:
        manager = get_session_manager(
            name,
            backend=backend,
            image=image,
            command=command,
        )

        # Build kwargs for start
        kwargs: dict[str, str | list[str] | dict[str, str] | None] = {}
        if working_dir:
            kwargs["working_dir"] = working_dir
        if env_dict:
            kwargs["env"] = env_dict
        if volume:
            kwargs["volumes"] = list(volume)
        if port:
            kwargs["ports"] = list(port)

        status = manager.start(command, **kwargs)

        result = CommandResult(
            status=CommandStatus.OK,
            message=f"Session '{name}' started ({status.backend.value} backend).",
            payload={
                "name": status.name,
                "state": status.state.value,
                "backend": status.backend.value,
                "pid": status.pid,
            },
        )
        emit_result(result, quiet)

    except SessionExistsError:
        exit_error(f"Session '{name}' already exists. Use 'kstlib ops stop {name}' first.")
    except OpsError as e:
        exit_error(str(e))


__all__ = ["start"]
