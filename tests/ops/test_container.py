"""Tests for the ContainerRunner class."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Generator
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from kstlib.ops.container import ContainerRunner
from kstlib.ops.exceptions import (
    ContainerRuntimeNotFoundError,
    SessionExistsError,
    SessionNotFoundError,
    SessionStartError,
)
from kstlib.ops.models import BackendType, SessionConfig, SessionState

if TYPE_CHECKING:
    pass


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_which() -> Generator[MagicMock, None, None]:
    """Mock shutil.which to return podman path."""
    with patch("kstlib.ops.container.shutil.which") as mock:
        mock.return_value = "/usr/bin/podman"
        yield mock


@pytest.fixture
def mock_run() -> Generator[MagicMock, None, None]:
    """Mock subprocess.run for container commands."""
    with patch("kstlib.ops.container.subprocess.run") as mock:
        yield mock


@pytest.fixture
def runner(mock_which: MagicMock) -> ContainerRunner:
    """Create a ContainerRunner with mocked binary."""
    return ContainerRunner()


@pytest.fixture
def config() -> SessionConfig:
    """Create a basic container config."""
    return SessionConfig(
        name="test-container",
        backend=BackendType.CONTAINER,
        image="python:3.10-slim",
    )


def make_inspect_result(
    name: str,
    running: bool = True,
    exited: bool = False,
    exit_code: int = 0,
    pid: int = 12345,
) -> str:
    """Create a JSON inspect result."""
    return json.dumps(
        [
            {
                "Name": name,
                "State": {
                    "Running": running,
                    "Status": "exited" if exited else ("running" if running else "stopped"),
                    "Pid": pid if running else 0,
                    "ExitCode": exit_code,
                },
                "Config": {
                    "Image": "python:3.10-slim",
                },
                "Image": "sha256:abc123",
                "Created": "2026-01-25T10:00:00.000000000Z",
            }
        ]
    )


# ============================================================================
# ContainerRunner initialization tests
# ============================================================================


class TestContainerRunnerInit:
    """Tests for ContainerRunner initialization."""

    def test_default_runtime(self, mock_which: MagicMock) -> None:
        """Use podman as default runtime."""
        runner = ContainerRunner()
        assert runner.runtime == "podman"
        _ = runner.binary
        mock_which.assert_called_with("podman")

    def test_docker_runtime(self) -> None:
        """Use docker runtime when specified."""
        with patch("kstlib.ops.container.shutil.which") as mock:
            mock.return_value = "/usr/bin/docker"
            runner = ContainerRunner(runtime="docker")
            assert runner.runtime == "docker"
            assert runner.binary == "/usr/bin/docker"

    def test_runtime_not_found(self) -> None:
        """Raise ContainerRuntimeNotFoundError when runtime not in PATH."""
        with patch("kstlib.ops.container.shutil.which") as mock:
            mock.return_value = None
            runner = ContainerRunner()
            with pytest.raises(ContainerRuntimeNotFoundError, match="not found in PATH"):
                _ = runner.binary


# ============================================================================
# ContainerRunner.exists tests
# ============================================================================


class TestContainerRunnerExists:
    """Tests for ContainerRunner.exists method."""

    def test_container_exists(
        self,
        runner: ContainerRunner,
        mock_run: MagicMock,
    ) -> None:
        """Return True when container exists."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=make_inspect_result("test"),
            stderr="",
        )
        assert runner.exists("test") is True

    def test_container_not_exists(
        self,
        runner: ContainerRunner,
        mock_run: MagicMock,
    ) -> None:
        """Return False when container does not exist."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="no such container",
        )
        assert runner.exists("nonexistent") is False


# ============================================================================
# ContainerRunner.start tests
# ============================================================================


class TestContainerRunnerStart:
    """Tests for ContainerRunner.start method."""

    def test_start_simple_container(
        self,
        runner: ContainerRunner,
        mock_run: MagicMock,
        config: SessionConfig,
    ) -> None:
        """Start a container with default options."""
        mock_run.side_effect = [
            # inspect returns 1 (not exists)
            subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
            # run returns 0 (success)
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="container-id-123\n",
                stderr="",
            ),
            # inspect for status
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=make_inspect_result("test-container"),
                stderr="",
            ),
        ]
        status = runner.start(config)
        assert status.name == "test-container"
        assert status.state == SessionState.RUNNING
        assert status.backend == BackendType.CONTAINER

    def test_start_with_volumes(
        self,
        runner: ContainerRunner,
        mock_run: MagicMock,
    ) -> None:
        """Start container with volume mounts."""
        config = SessionConfig(
            name="test",
            backend=BackendType.CONTAINER,
            image="python:3.10-slim",
            volumes=["./data:/app/data", "./logs:/app/logs"],
        )
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="id\n", stderr=""),
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=make_inspect_result("test"),
                stderr="",
            ),
        ]
        runner.start(config)
        run_call = mock_run.call_args_list[1]
        cmd = run_call[0][0]
        assert "-v" in cmd
        assert "./data:/app/data" in cmd
        assert "./logs:/app/logs" in cmd

    def test_start_with_ports(
        self,
        runner: ContainerRunner,
        mock_run: MagicMock,
    ) -> None:
        """Start container with port mappings."""
        config = SessionConfig(
            name="test",
            backend=BackendType.CONTAINER,
            image="python:3.10-slim",
            ports=["8080:80", "9090:9090"],
        )
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="id\n", stderr=""),
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=make_inspect_result("test"),
                stderr="",
            ),
        ]
        runner.start(config)
        run_call = mock_run.call_args_list[1]
        cmd = run_call[0][0]
        assert "-p" in cmd
        assert "8080:80" in cmd

    def test_start_with_env_vars(
        self,
        runner: ContainerRunner,
        mock_run: MagicMock,
    ) -> None:
        """Start container with environment variables."""
        config = SessionConfig(
            name="test",
            backend=BackendType.CONTAINER,
            image="python:3.10-slim",
            env={"APP_ENV": "production", "DEBUG": "0"},
        )
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="id\n", stderr=""),
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=make_inspect_result("test"),
                stderr="",
            ),
        ]
        runner.start(config)
        run_call = mock_run.call_args_list[1]
        cmd = run_call[0][0]
        assert "-e" in cmd

    def test_start_with_command(
        self,
        runner: ContainerRunner,
        mock_run: MagicMock,
    ) -> None:
        """Start container with custom command."""
        config = SessionConfig(
            name="test",
            backend=BackendType.CONTAINER,
            image="python:3.10-slim",
            command="python -m app",
        )
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="id\n", stderr=""),
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=make_inspect_result("test"),
                stderr="",
            ),
        ]
        runner.start(config)
        run_call = mock_run.call_args_list[1]
        cmd = run_call[0][0]
        assert "python" in cmd
        assert "-m" in cmd
        assert "app" in cmd

    def test_start_container_already_exists(
        self,
        runner: ContainerRunner,
        mock_run: MagicMock,
        config: SessionConfig,
    ) -> None:
        """Raise SessionExistsError when container already exists."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=make_inspect_result("test-container"),
            stderr="",
        )
        with pytest.raises(SessionExistsError, match="already exists"):
            runner.start(config)

    def test_start_without_image(
        self,
        runner: ContainerRunner,
        mock_run: MagicMock,
    ) -> None:
        """Raise SessionStartError when image is missing."""
        config = SessionConfig(
            name="test",
            backend=BackendType.CONTAINER,
            # No image
        )
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="",
        )
        with pytest.raises(SessionStartError, match="image is required"):
            runner.start(config)

    def test_start_fails(
        self,
        runner: ContainerRunner,
        mock_run: MagicMock,
        config: SessionConfig,
    ) -> None:
        """Raise SessionStartError when run command fails."""
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
            subprocess.CompletedProcess(
                args=[],
                returncode=125,
                stdout="",
                stderr="container name already in use",
            ),
        ]
        with pytest.raises(SessionStartError, match="Failed to start"):
            runner.start(config)


# ============================================================================
# ContainerRunner.stop tests
# ============================================================================


class TestContainerRunnerStop:
    """Tests for ContainerRunner.stop method."""

    def test_stop_container(
        self,
        runner: ContainerRunner,
        mock_run: MagicMock,
    ) -> None:
        """Stop a running container."""
        mock_run.side_effect = [
            # inspect returns running container
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=make_inspect_result("test"),
                stderr="",
            ),
            # stop returns 0
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            # rm returns 0
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        ]
        result = runner.stop("test")
        assert result is True

    def test_stop_force(
        self,
        runner: ContainerRunner,
        mock_run: MagicMock,
    ) -> None:
        """Stop container with force (kill)."""
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=make_inspect_result("test"),
                stderr="",
            ),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        ]
        result = runner.stop("test", graceful=False)
        assert result is True
        # Check that kill was called instead of stop
        stop_call = mock_run.call_args_list[1]
        cmd = stop_call[0][0]
        assert "kill" in cmd

    def test_stop_container_not_found(
        self,
        runner: ContainerRunner,
        mock_run: MagicMock,
    ) -> None:
        """Raise SessionNotFoundError when container does not exist."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="",
        )
        with pytest.raises(SessionNotFoundError, match="not found"):
            runner.stop("nonexistent")


# ============================================================================
# ContainerRunner.status tests
# ============================================================================


class TestContainerRunnerStatus:
    """Tests for ContainerRunner.status method."""

    def test_get_running_status(
        self,
        runner: ContainerRunner,
        mock_run: MagicMock,
    ) -> None:
        """Get status of a running container."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=make_inspect_result("test", running=True, pid=9999),
            stderr="",
        )
        status = runner.status("test")
        assert status.name == "test"
        assert status.state == SessionState.RUNNING
        assert status.backend == BackendType.CONTAINER
        assert status.pid == 9999

    def test_get_exited_status(
        self,
        runner: ContainerRunner,
        mock_run: MagicMock,
    ) -> None:
        """Get status of an exited container."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=make_inspect_result("test", running=False, exited=True, exit_code=1),
            stderr="",
        )
        status = runner.status("test")
        assert status.state == SessionState.EXITED
        assert status.exit_code == 1

    def test_status_container_not_found(
        self,
        runner: ContainerRunner,
        mock_run: MagicMock,
    ) -> None:
        """Raise SessionNotFoundError when container does not exist."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="no such container",
        )
        with pytest.raises(SessionNotFoundError, match="not found"):
            runner.status("nonexistent")


# ============================================================================
# ContainerRunner.logs tests
# ============================================================================


class TestContainerRunnerLogs:
    """Tests for ContainerRunner.logs method."""

    def test_get_logs(
        self,
        runner: ContainerRunner,
        mock_run: MagicMock,
    ) -> None:
        """Retrieve logs from a container."""
        mock_run.side_effect = [
            # inspect returns running container
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=make_inspect_result("test"),
                stderr="",
            ),
            # logs returns content
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="Line 1\nLine 2\n",
                stderr="Error line\n",
            ),
        ]
        logs = runner.logs("test", lines=50)
        assert "Line 1" in logs
        assert "Error line" in logs

    def test_logs_container_not_found(
        self,
        runner: ContainerRunner,
        mock_run: MagicMock,
    ) -> None:
        """Raise SessionNotFoundError when container does not exist."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="",
        )
        with pytest.raises(SessionNotFoundError, match="not found"):
            runner.logs("nonexistent")


# ============================================================================
# ContainerRunner.list_sessions tests
# ============================================================================


class TestContainerRunnerListSessions:
    """Tests for ContainerRunner.list_sessions method."""

    def test_list_multiple_containers(
        self,
        runner: ContainerRunner,
        mock_run: MagicMock,
    ) -> None:
        """List all containers."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                '{"Names":"container1","State":"running","Image":"img1","CreatedAt":"2026-01-25"}\n'
                '{"Names":"container2","State":"exited","Image":"img2","CreatedAt":"2026-01-24"}\n'
            ),
            stderr="",
        )
        sessions = runner.list_sessions()
        assert len(sessions) == 2
        assert sessions[0].name == "container1"
        assert sessions[0].state == SessionState.RUNNING
        assert sessions[1].name == "container2"
        assert sessions[1].state == SessionState.EXITED

    def test_list_empty(
        self,
        runner: ContainerRunner,
        mock_run: MagicMock,
    ) -> None:
        """Return empty list when no containers."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="",
        )
        sessions = runner.list_sessions()
        assert sessions == []


# ============================================================================
# ContainerRunner.exec tests
# ============================================================================


class TestContainerRunnerExec:
    """Tests for ContainerRunner.exec method."""

    def test_exec_command(
        self,
        runner: ContainerRunner,
        mock_run: MagicMock,
    ) -> None:
        """Execute a command in a container."""
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=make_inspect_result("test"),
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="hello\n",
                stderr="",
            ),
        ]
        result = runner.exec("test", "echo hello")
        assert result.stdout == "hello\n"

    def test_exec_container_not_found(
        self,
        runner: ContainerRunner,
        mock_run: MagicMock,
    ) -> None:
        """Raise SessionNotFoundError when container does not exist."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="",
        )
        with pytest.raises(SessionNotFoundError, match="not found"):
            runner.exec("nonexistent", "ls")


# ============================================================================
# ContainerRunner.attach tests
# ============================================================================


class TestContainerRunnerAttach:
    """Tests for ContainerRunner.attach method."""

    def test_attach_container_not_found(
        self,
        runner: ContainerRunner,
        mock_run: MagicMock,
    ) -> None:
        """Raise SessionNotFoundError when container does not exist."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="",
        )
        with pytest.raises(SessionNotFoundError, match="not found"):
            runner.attach("nonexistent")

    def test_attach_container_not_running(
        self,
        runner: ContainerRunner,
        mock_run: MagicMock,
    ) -> None:
        """Raise SessionAttachError when container is not running."""
        mock_run.side_effect = [
            # First inspect for exists check
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=make_inspect_result("test", running=False, exited=True),
                stderr="",
            ),
            # Second inspect for running check
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=make_inspect_result("test", running=False, exited=True),
                stderr="",
            ),
        ]
        from kstlib.ops.exceptions import SessionAttachError as AttachError

        with pytest.raises(AttachError, match="not running"):
            runner.attach("test")

    def test_attach_calls_subprocess(
        self,
        runner: ContainerRunner,
        mock_run: MagicMock,
    ) -> None:
        """Verify attach calls subprocess.run for interactive attach."""
        # Calls: exists (_inspect), _inspect again, then attach subprocess.run
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=make_inspect_result("test", running=True),
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=make_inspect_result("test", running=True),
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="",
                stderr="",
            ),
        ]
        runner.attach("test")
        # Verify the attach call was made
        attach_call = mock_run.call_args_list[-1]
        assert attach_call[0][0] == ["/usr/bin/podman", "attach", "test"]
        assert attach_call[1]["check"] is False

    def test_attach_accepts_exit_code_1(
        self,
        runner: ContainerRunner,
        mock_run: MagicMock,
    ) -> None:
        """Verify attach accepts exit code 1 (docker detach behavior)."""
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=make_inspect_result("test", running=True),
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=make_inspect_result("test", running=True),
                stderr="",
            ),
            # Exit code 1 = normal detach with Ctrl+P Ctrl+Q
            subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
                stderr="",
            ),
        ]
        # Should not raise
        runner.attach("test")

    def test_attach_raises_on_error_exit_code(
        self,
        runner: ContainerRunner,
        mock_run: MagicMock,
    ) -> None:
        """Verify attach raises on error exit codes (> 1)."""
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=make_inspect_result("test", running=True),
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=make_inspect_result("test", running=True),
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=[],
                returncode=2,
                stdout="",
                stderr="",
            ),
        ]
        from kstlib.ops.exceptions import SessionAttachError as AttachError

        with pytest.raises(AttachError, match="exited with code 2"):
            runner.attach("test")
