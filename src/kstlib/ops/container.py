"""Container session runner for production environments.

This module provides the ContainerRunner class for managing Podman/Docker
containers, enabling persistent processes with pseudo-terminal support.

Features:
- Create named containers with custom images and volumes
- Attach to running containers (replaces current process)
- Retrieve container logs with ANSI codes preserved
- Support for both Podman and Docker runtimes
- Automatic log volume mounting for post-mortem analysis

Example:
    >>> from kstlib.ops import SessionConfig, BackendType
    >>> from kstlib.ops.container import ContainerRunner
    >>> runner = ContainerRunner(runtime="podman")  # doctest: +SKIP
    >>> config = SessionConfig(  # doctest: +SKIP
    ...     name="bot",
    ...     backend=BackendType.CONTAINER,
    ...     image="bot:latest",
    ...     volumes=["./data:/app/data"],
    ... )
    >>> status = runner.start(config)  # doctest: +SKIP
    >>> runner.attach("bot")  # Replaces process  # doctest: +SKIP
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import TYPE_CHECKING, Any

from kstlib.ops.exceptions import (
    ContainerRuntimeNotFoundError,
    SessionAttachError,
    SessionExistsError,
    SessionNotFoundError,
    SessionStartError,
    SessionStopError,
)
from kstlib.ops.models import BackendType, SessionConfig, SessionState, SessionStatus

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


class ContainerRunner:
    """Container runner for Podman/Docker containers.

    Manages containers for running persistent processes with
    pseudo-terminal support for TUI applications.

    Args:
        runtime: Container runtime to use ("podman" or "docker").

    Attributes:
        runtime: The container runtime name.
        binary: The validated runtime binary path.

    Examples:
        >>> runner = ContainerRunner()  # Uses podman by default  # doctest: +SKIP
        >>> runner = ContainerRunner(runtime="docker")  # doctest: +SKIP
        >>> config = SessionConfig(
        ...     name="app",
        ...     backend=BackendType.CONTAINER,
        ...     image="python:3.10-slim",
        ... )
        >>> status = runner.start(config)  # doctest: +SKIP
    """

    def __init__(self, runtime: str | None = None) -> None:
        """Initialize ContainerRunner.

        Args:
            runtime: Container runtime ("podman", "docker", or None for auto-detect).
                     Auto-detection tries podman first, then docker.
        """
        if runtime is None:
            # Auto-detect: try podman first, then docker
            if shutil.which("podman"):
                self._runtime = "podman"
            elif shutil.which("docker"):
                self._runtime = "docker"
            else:
                self._runtime = "podman"  # Will fail with clear error message
        else:
            self._runtime = runtime
        self._binary_path: str | None = None

    @property
    def runtime(self) -> str:
        """Return the configured runtime name."""
        return self._runtime

    @property
    def binary(self) -> str:
        """Return validated container runtime binary path.

        Raises:
            ContainerRuntimeNotFoundError: If runtime is not installed.
        """
        if self._binary_path is None:
            path = shutil.which(self._runtime)
            if path is None:
                raise ContainerRuntimeNotFoundError(
                    f"Container runtime '{self._runtime}' not found in PATH. "
                    f"Install {self._runtime}: https://{'podman.io' if self._runtime == 'podman' else 'docker.com'}"
                )
            self._binary_path = path
        return self._binary_path

    def _run(
        self,
        args: Sequence[str],
        *,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """Run a container command.

        Args:
            args: Command arguments (without binary name).
            check: Whether to raise on non-zero exit.

        Returns:
            CompletedProcess with stdout/stderr.

        Raises:
            ContainerRuntimeNotFoundError: If runtime is not installed.
        """
        cmd = [self.binary, *args]
        logger.debug("Running: %s", " ".join(cmd))
        return subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            check=check,
        )

    def _inspect(self, name: str) -> dict[str, Any] | None:
        """Inspect a container and return its metadata.

        Args:
            name: Container name.

        Returns:
            Container metadata dict or None if not found.
        """
        result = self._run(["inspect", name, "--format", "json"])
        if result.returncode != 0:
            return None
        try:
            data = json.loads(result.stdout)
            if isinstance(data, list) and len(data) > 0:
                return data[0]  # type: ignore[no-any-return]
            return None
        except json.JSONDecodeError:
            return None

    def _restart_stopped(self, name: str) -> SessionStatus:
        """Restart a stopped container.

        Args:
            name: Container name to restart.

        Returns:
            SessionStatus after restart.

        Raises:
            SessionStartError: If restart failed.
        """
        logger.info("Restarting stopped container: %s", name)
        result = self._run(["start", name])
        if result.returncode != 0:
            raise SessionStartError(
                name,
                "container",
                f"Failed to restart: {result.stderr}",
            )
        return self.status(name)

    def _build_run_args(self, config: SessionConfig) -> list[str]:
        """Build command arguments for container run.

        Args:
            config: Session configuration.

        Returns:
            List of command arguments.
        """
        args = [
            "run",
            "-d",  # Detached
            "--name",
            config.name,
            "-it",  # Interactive with pseudo-terminal (for TUI support)
        ]

        # Working directory
        if config.working_dir:
            args.extend(["-w", config.working_dir])

        # Environment variables
        for key, value in config.env.items():
            args.extend(["-e", f"{key}={value}"])

        # Volumes
        for volume in config.volumes:
            args.extend(["-v", volume])

        # Log volume (auto-mount for post-mortem analysis)
        if config.log_volume:
            args.extend(["-v", config.log_volume])

        # Port mappings
        for port in config.ports:
            args.extend(["-p", port])

        # Image
        args.append(config.image)  # type: ignore[arg-type]

        # Command (optional)
        if config.command:
            args.extend(config.command.split())

        return args

    def start(self, config: SessionConfig) -> SessionStatus:
        """Create and start a new container.

        Args:
            config: Session configuration with image and options.

        Returns:
            SessionStatus with state information.

        Raises:
            SessionExistsError: If container already exists and is running.
            SessionStartError: If container failed to start.
            ContainerRuntimeNotFoundError: If runtime is not installed.
        """
        # Check if container already exists
        if self.exists(config.name):
            info = self._inspect(config.name)
            if info and info.get("State", {}).get("Running", False):
                raise SessionExistsError(config.name, "container")
            # Container exists but stopped - restart it
            return self._restart_stopped(config.name)

        if not config.image:
            raise SessionStartError(
                config.name,
                "container",
                "Container image is required",
            )

        args = self._build_run_args(config)
        result = self._run(args)

        if result.returncode != 0:
            raise SessionStartError(
                config.name,
                "container",
                result.stderr.strip() or "Unknown error",
            )

        logger.info("Started container: %s", config.name)
        return self.status(config.name)

    def stop(
        self,
        name: str,
        *,
        graceful: bool = True,
        timeout: int = 10,
    ) -> bool:
        """Stop a running container.

        Args:
            name: Container name to stop.
            graceful: If True, use stop with timeout. If False, use kill.
            timeout: Seconds to wait for graceful shutdown.

        Returns:
            True if stopped, False if not running.

        Raises:
            SessionNotFoundError: If container doesn't exist.
            SessionStopError: If container couldn't be stopped.
        """
        if not self.exists(name):
            raise SessionNotFoundError(name, "container")

        cmd = ["stop", "-t", str(timeout), name] if graceful else ["kill", name]
        result = self._run(cmd)

        if result.returncode != 0:
            # Check if container already stopped
            info = self._inspect(name)
            if info and not info.get("State", {}).get("Running", False):
                logger.info("Container already stopped: %s", name)
                return True
            raise SessionStopError(
                name,
                "container",
                result.stderr.strip() or "Unknown error",
            )

        # Remove the container after stopping
        self._run(["rm", name])

        logger.info("Stopped container: %s", name)
        return True

    def attach(self, name: str) -> None:
        """Attach to a running container.

        This method replaces the current process with container attach.
        It does not return on success.

        Args:
            name: Container name to attach to.

        Raises:
            SessionNotFoundError: If container doesn't exist.
            SessionAttachError: If attachment failed.

        Note:
            Use Ctrl+P Ctrl+Q to detach from the container.
        """
        if not self.exists(name):
            raise SessionNotFoundError(name, "container")

        # Check if running
        info = self._inspect(name)
        if info and not info.get("State", {}).get("Running", False):
            raise SessionAttachError(
                name,
                "container",
                "Container is not running",
            )

        binary = self.binary
        logger.info("Attaching to container: %s", name)

        # Attach to container (interactive)
        # On Windows, os.execvp doesn't work well with paths containing spaces
        # Use subprocess.run which handles this correctly
        try:
            result = subprocess.run(  # noqa: S603
                [binary, "attach", name],
                check=False,
            )
            # Docker returns exit code 1 when detaching with Ctrl+P Ctrl+Q
            # This is normal behavior, not an error
            if result.returncode not in (0, 1):
                raise SessionAttachError(
                    name,
                    "container",
                    f"Attach exited with code {result.returncode}",
                )
        except OSError as e:
            raise SessionAttachError(name, "container", str(e)) from e

    def status(self, name: str) -> SessionStatus:
        """Get status of a container.

        Args:
            name: Container name to query.

        Returns:
            SessionStatus with current state.

        Raises:
            SessionNotFoundError: If container doesn't exist.
        """
        info = self._inspect(name)
        if info is None:
            raise SessionNotFoundError(name, "container")

        state_info = info.get("State", {})
        running = state_info.get("Running", False)
        exited = state_info.get("Status") == "exited"

        if running:
            state = SessionState.RUNNING
        elif exited:
            state = SessionState.EXITED
        else:
            state = SessionState.STOPPED

        # Get PID
        pid = state_info.get("Pid")
        if pid == 0:
            pid = None

        # Get image name
        image = info.get("Config", {}).get("Image") or info.get("Image", "")

        # Get created timestamp
        created = info.get("Created", "")

        # Get exit code if exited
        exit_code = None
        if exited:
            exit_code = state_info.get("ExitCode")

        return SessionStatus(
            name=name,
            state=state,
            backend=BackendType.CONTAINER,
            pid=pid,
            created_at=created,
            image=image,
            exit_code=exit_code,
        )

    def logs(self, name: str, lines: int = 100) -> str:
        """Retrieve recent logs from a container.

        Args:
            name: Container name to get logs from.
            lines: Number of lines to retrieve.

        Returns:
            String with log output (ANSI codes preserved).

        Raises:
            SessionNotFoundError: If container doesn't exist.
        """
        if not self.exists(name):
            raise SessionNotFoundError(name, "container")

        result = self._run(["logs", "--tail", str(lines), name])

        # Combine stdout and stderr (container logs may go to either)
        return result.stdout + result.stderr

    def exists(self, name: str) -> bool:
        """Check if a container with the given name exists.

        Args:
            name: Container name to check.

        Returns:
            True if container exists, False otherwise.
        """
        return self._inspect(name) is not None

    @staticmethod
    def _parse_container_json(raw: str) -> list[dict[str, Any]]:
        """Parse container JSON output into a list of dicts.

        Podman may return a single JSON array or one JSON object per line
        depending on version.

        Args:
            raw: Raw stdout from ``ps --format json``.

        Returns:
            List of parsed container dicts.
        """
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None

        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]

        items: list[dict[str, Any]] = []
        for line in raw.split("\n"):
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    items.append(obj)
            except json.JSONDecodeError:
                continue
        return items

    @staticmethod
    def _container_to_status(data: dict[str, Any]) -> SessionStatus | None:
        """Convert a single container dict to a SessionStatus.

        Args:
            data: Parsed container JSON dict.

        Returns:
            SessionStatus or None if the data is unparseable.
        """
        try:
            name = data.get("Names") or data.get("Name", "")
            if isinstance(name, list):
                name = name[0] if name else ""

            state_str = data.get("State", "").lower()
            if state_str == "running":
                state = SessionState.RUNNING
            elif state_str in ("exited", "stopped"):
                state = SessionState.EXITED
            else:
                state = SessionState.UNKNOWN

            return SessionStatus(
                name=name,
                state=state,
                backend=BackendType.CONTAINER,
                image=data.get("Image", ""),
                created_at=data.get("CreatedAt", ""),
            )
        except (KeyError, TypeError, AttributeError):
            return None

    def list_sessions(self) -> list[SessionStatus]:
        """List all containers.

        Returns:
            List of SessionStatus for all containers.
        """
        result = self._run(["ps", "-a", "--format", "json"])

        if result.returncode != 0:
            return []

        raw = result.stdout.strip()
        if not raw:
            return []

        items = self._parse_container_json(raw)
        sessions: list[SessionStatus] = []
        for data in items:
            status = self._container_to_status(data)
            if status is not None:
                sessions.append(status)

        return sessions

    def exec(
        self,
        name: str,
        command: str,
        *,
        interactive: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """Execute a command in a running container.

        Args:
            name: Container name.
            command: Command to execute.
            interactive: If True, use -it flags.

        Returns:
            CompletedProcess with stdout/stderr.

        Raises:
            SessionNotFoundError: If container doesn't exist.
        """
        if not self.exists(name):
            raise SessionNotFoundError(name, "container")

        args = ["exec"]
        if interactive:
            args.append("-it")
        args.append(name)
        args.extend(command.split())

        return self._run(args)


__all__ = [
    "ContainerRunner",
]
