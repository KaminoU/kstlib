"""Tests for the SessionManager class."""

from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from kstlib.ops.exceptions import (
    ContainerRuntimeNotFoundError,
    SessionAmbiguousError,
    SessionNotFoundError,
    TmuxNotFoundError,
)
from kstlib.ops.manager import SessionConfigError, SessionManager, auto_detect_backend
from kstlib.ops.models import BackendType, SessionState, SessionStatus

if TYPE_CHECKING:
    pass


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_tmux_runner() -> Generator[MagicMock, None, None]:
    """Mock TmuxRunner class."""
    with patch("kstlib.ops.manager.TmuxRunner") as mock:
        runner = MagicMock()
        mock.return_value = runner
        yield runner


@pytest.fixture
def mock_container_runner() -> Generator[MagicMock, None, None]:
    """Mock ContainerRunner class."""
    with patch("kstlib.ops.manager.ContainerRunner") as mock:
        runner = MagicMock()
        mock.return_value = runner
        yield runner


@pytest.fixture
def mock_config() -> Generator[MagicMock, None, None]:
    """Mock get_config to return test config."""
    config = {
        "ops": {
            "default_backend": "tmux",
            "tmux_binary": "tmux",
            "container_runtime": "podman",
            "sessions": {
                "test-session": {
                    "backend": "tmux",
                    "command": "python app.py",
                    "working_dir": "/opt/app",
                    "env": {"APP_ENV": "test"},
                },
                "prod-session": {
                    "backend": "container",
                    "image": "app:latest",
                    "volumes": ["./data:/app/data"],
                    "ports": ["8080:80"],
                },
            },
        },
    }
    with patch("kstlib.config.get_config") as mock:
        # Create a mock that behaves like Box
        mock_box = MagicMock()
        mock_box.get.side_effect = lambda key, default=None: config.get(key, default)
        mock.return_value = mock_box
        yield mock


# ============================================================================
# SessionManager initialization tests
# ============================================================================


class TestSessionManagerInit:
    """Tests for SessionManager initialization."""

    def test_default_backend_is_tmux(self, mock_tmux_runner: MagicMock) -> None:
        """Default backend should be tmux."""
        manager = SessionManager("test")
        assert manager.backend == BackendType.TMUX

    def test_explicit_tmux_backend(self, mock_tmux_runner: MagicMock) -> None:
        """Specify tmux backend explicitly."""
        manager = SessionManager("test", backend="tmux")
        assert manager.backend == BackendType.TMUX

    def test_container_backend(self, mock_container_runner: MagicMock) -> None:
        """Specify container backend."""
        manager = SessionManager("test", backend="container", image="app:latest")
        assert manager.backend == BackendType.CONTAINER

    def test_backend_enum(self, mock_tmux_runner: MagicMock) -> None:
        """Accept BackendType enum."""
        manager = SessionManager("test", backend=BackendType.TMUX)
        assert manager.backend == BackendType.TMUX

    def test_invalid_backend(self) -> None:
        """Raise error for invalid backend."""
        with pytest.raises(SessionConfigError, match="Invalid backend"):
            SessionManager("test", backend="invalid")

    def test_name_property(self, mock_tmux_runner: MagicMock) -> None:
        """Name property returns session name."""
        manager = SessionManager("my-session")
        assert manager.name == "my-session"

    def test_config_property(self, mock_tmux_runner: MagicMock) -> None:
        """Config property returns session configuration."""
        manager = SessionManager(
            "test",
            command="python app.py",
            working_dir="/opt/app",
        )
        assert manager.config.name == "test"
        assert manager.config.command == "python app.py"
        assert manager.config.working_dir == "/opt/app"


# ============================================================================
# SessionManager.from_config tests
# ============================================================================


class TestSessionManagerFromConfig:
    """Tests for SessionManager.from_config classmethod."""

    def test_load_tmux_session(
        self,
        mock_config: MagicMock,
        mock_tmux_runner: MagicMock,
    ) -> None:
        """Load tmux session from config."""
        manager = SessionManager.from_config("test-session")
        assert manager.name == "test-session"
        assert manager.backend == BackendType.TMUX
        assert manager.config.command == "python app.py"
        assert manager.config.working_dir == "/opt/app"

    def test_load_container_session(
        self,
        mock_config: MagicMock,
        mock_container_runner: MagicMock,
    ) -> None:
        """Load container session from config."""
        manager = SessionManager.from_config("prod-session")
        assert manager.name == "prod-session"
        assert manager.backend == BackendType.CONTAINER
        assert manager.config.image == "app:latest"

    def test_session_not_in_config(self, mock_config: MagicMock) -> None:
        """Raise error when session not found in config."""
        with pytest.raises(SessionConfigError, match="not found in config"):
            SessionManager.from_config("nonexistent")


# ============================================================================
# SessionManager.start tests
# ============================================================================


class TestSessionManagerStart:
    """Tests for SessionManager.start method."""

    def test_start_session(self, mock_tmux_runner: MagicMock) -> None:
        """Start a session."""
        mock_tmux_runner.start.return_value = SessionStatus(
            name="test",
            state=SessionState.RUNNING,
            backend=BackendType.TMUX,
        )
        manager = SessionManager("test")
        status = manager.start("python app.py")
        assert status.state == SessionState.RUNNING
        mock_tmux_runner.start.assert_called_once()

    def test_start_with_command_override(self, mock_tmux_runner: MagicMock) -> None:
        """Override command at start time."""
        mock_tmux_runner.start.return_value = SessionStatus(
            name="test",
            state=SessionState.RUNNING,
            backend=BackendType.TMUX,
        )
        manager = SessionManager("test", command="original")
        manager.start("override")
        call_args = mock_tmux_runner.start.call_args
        config = call_args[0][0]
        assert config.command == "override"

    def test_start_uses_config_command(self, mock_tmux_runner: MagicMock) -> None:
        """Use config command when none provided at start."""
        mock_tmux_runner.start.return_value = SessionStatus(
            name="test",
            state=SessionState.RUNNING,
            backend=BackendType.TMUX,
        )
        manager = SessionManager("test", command="from-config")
        manager.start()
        call_args = mock_tmux_runner.start.call_args
        config = call_args[0][0]
        assert config.command == "from-config"


# ============================================================================
# SessionManager.stop tests
# ============================================================================


class TestSessionManagerStop:
    """Tests for SessionManager.stop method."""

    def test_stop_session(self, mock_tmux_runner: MagicMock) -> None:
        """Stop a session."""
        mock_tmux_runner.stop.return_value = True
        manager = SessionManager("test")
        result = manager.stop()
        assert result is True
        mock_tmux_runner.stop.assert_called_once_with(
            "test",
            graceful=True,
            timeout=10,
        )

    def test_stop_force(self, mock_tmux_runner: MagicMock) -> None:
        """Force stop a session."""
        mock_tmux_runner.stop.return_value = True
        manager = SessionManager("test")
        manager.stop(graceful=False, timeout=5)
        mock_tmux_runner.stop.assert_called_once_with(
            "test",
            graceful=False,
            timeout=5,
        )


# ============================================================================
# SessionManager.attach tests
# ============================================================================


class TestSessionManagerAttach:
    """Tests for SessionManager.attach method."""

    def test_attach_session(self, mock_tmux_runner: MagicMock) -> None:
        """Attach to a session."""
        manager = SessionManager("test")
        manager.attach()
        mock_tmux_runner.attach.assert_called_once_with("test")


# ============================================================================
# SessionManager.status tests
# ============================================================================


class TestSessionManagerStatus:
    """Tests for SessionManager.status method."""

    def test_get_status(self, mock_tmux_runner: MagicMock) -> None:
        """Get session status."""
        expected_status = SessionStatus(
            name="test",
            state=SessionState.RUNNING,
            backend=BackendType.TMUX,
            pid=12345,
        )
        mock_tmux_runner.status.return_value = expected_status
        manager = SessionManager("test")
        status = manager.status()
        assert status.name == "test"
        assert status.state == SessionState.RUNNING
        assert status.pid == 12345


# ============================================================================
# SessionManager.logs tests
# ============================================================================


class TestSessionManagerLogs:
    """Tests for SessionManager.logs method."""

    def test_get_logs(self, mock_tmux_runner: MagicMock) -> None:
        """Get session logs."""
        mock_tmux_runner.logs.return_value = "Line 1\nLine 2\n"
        manager = SessionManager("test")
        logs = manager.logs(lines=50)
        assert "Line 1" in logs
        mock_tmux_runner.logs.assert_called_once_with("test", lines=50)


# ============================================================================
# SessionManager.exists tests
# ============================================================================


class TestSessionManagerExists:
    """Tests for SessionManager.exists method."""

    def test_exists_true(self, mock_tmux_runner: MagicMock) -> None:
        """Return True when session exists."""
        mock_tmux_runner.exists.return_value = True
        manager = SessionManager("test")
        assert manager.exists() is True

    def test_exists_false(self, mock_tmux_runner: MagicMock) -> None:
        """Return False when session does not exist."""
        mock_tmux_runner.exists.return_value = False
        manager = SessionManager("test")
        assert manager.exists() is False


# ============================================================================
# SessionManager.is_running tests
# ============================================================================


class TestSessionManagerIsRunning:
    """Tests for SessionManager.is_running method."""

    def test_is_running_true(self, mock_tmux_runner: MagicMock) -> None:
        """Return True when session is running."""
        mock_tmux_runner.exists.return_value = True
        mock_tmux_runner.status.return_value = SessionStatus(
            name="test",
            state=SessionState.RUNNING,
            backend=BackendType.TMUX,
        )
        manager = SessionManager("test")
        assert manager.is_running() is True

    def test_is_running_false_not_exists(self, mock_tmux_runner: MagicMock) -> None:
        """Return False when session does not exist."""
        mock_tmux_runner.exists.return_value = False
        manager = SessionManager("test")
        assert manager.is_running() is False

    def test_is_running_false_stopped(self, mock_tmux_runner: MagicMock) -> None:
        """Return False when session is stopped."""
        mock_tmux_runner.exists.return_value = True
        mock_tmux_runner.status.return_value = SessionStatus(
            name="test",
            state=SessionState.STOPPED,
            backend=BackendType.TMUX,
        )
        manager = SessionManager("test")
        assert manager.is_running() is False

    def test_is_running_handles_exception(self, mock_tmux_runner: MagicMock) -> None:
        """Return False when status check raises exception."""
        mock_tmux_runner.exists.return_value = True
        mock_tmux_runner.status.side_effect = SessionNotFoundError("test", "tmux")
        manager = SessionManager("test")
        assert manager.is_running() is False


# ============================================================================
# auto_detect_backend tests
# ============================================================================


class TestAutoDetectBackend:
    """Tests for auto_detect_backend function."""

    def test_found_in_tmux_only(self) -> None:
        """Return TMUX when session only exists in tmux."""
        with (
            patch("kstlib.ops.manager.TmuxRunner") as mock_tmux,
            patch("kstlib.ops.manager.ContainerRunner") as mock_container,
        ):
            mock_tmux.return_value.exists.return_value = True
            mock_container.return_value.exists.return_value = False
            result = auto_detect_backend("test")
            assert result == BackendType.TMUX

    def test_found_in_container_only(self) -> None:
        """Return CONTAINER when session only exists in container."""
        with (
            patch("kstlib.ops.manager.TmuxRunner") as mock_tmux,
            patch("kstlib.ops.manager.ContainerRunner") as mock_container,
        ):
            mock_tmux.return_value.exists.return_value = False
            mock_container.return_value.exists.return_value = True
            result = auto_detect_backend("test")
            assert result == BackendType.CONTAINER

    def test_not_found_anywhere(self) -> None:
        """Return None when session does not exist."""
        with (
            patch("kstlib.ops.manager.TmuxRunner") as mock_tmux,
            patch("kstlib.ops.manager.ContainerRunner") as mock_container,
        ):
            mock_tmux.return_value.exists.return_value = False
            mock_container.return_value.exists.return_value = False
            result = auto_detect_backend("test")
            assert result is None

    def test_found_in_both_raises_ambiguous(self) -> None:
        """Raise SessionAmbiguousError when found in both backends."""
        with (
            patch("kstlib.ops.manager.TmuxRunner") as mock_tmux,
            patch("kstlib.ops.manager.ContainerRunner") as mock_container,
        ):
            mock_tmux.return_value.exists.return_value = True
            mock_container.return_value.exists.return_value = True
            with pytest.raises(SessionAmbiguousError) as exc_info:
                auto_detect_backend("test")
            assert exc_info.value.name == "test"
            assert "tmux" in exc_info.value.backends
            assert "container" in exc_info.value.backends

    def test_skip_unavailable_tmux(self) -> None:
        """Skip tmux check when tmux not installed."""
        with (
            patch("kstlib.ops.manager.TmuxRunner") as mock_tmux,
            patch("kstlib.ops.manager.ContainerRunner") as mock_container,
        ):
            mock_tmux.side_effect = TmuxNotFoundError("tmux not found")
            mock_container.return_value.exists.return_value = True
            result = auto_detect_backend("test")
            assert result == BackendType.CONTAINER

    def test_skip_unavailable_container(self) -> None:
        """Skip container check when container runtime not installed."""
        with (
            patch("kstlib.ops.manager.TmuxRunner") as mock_tmux,
            patch("kstlib.ops.manager.ContainerRunner") as mock_container,
        ):
            mock_tmux.return_value.exists.return_value = True
            mock_container.side_effect = ContainerRuntimeNotFoundError("no runtime")
            result = auto_detect_backend("test")
            assert result == BackendType.TMUX

    def test_skip_both_unavailable(self) -> None:
        """Return None when both backends unavailable."""
        with (
            patch("kstlib.ops.manager.TmuxRunner") as mock_tmux,
            patch("kstlib.ops.manager.ContainerRunner") as mock_container,
        ):
            mock_tmux.side_effect = TmuxNotFoundError("tmux not found")
            mock_container.side_effect = ContainerRuntimeNotFoundError("no runtime")
            result = auto_detect_backend("test")
            assert result is None


# ============================================================================
# SessionAmbiguousError tests
# ============================================================================


class TestSessionAmbiguousError:
    """Tests for SessionAmbiguousError exception."""

    def test_error_message_format(self) -> None:
        """Verify error message format includes backends."""
        error = SessionAmbiguousError("test", ["tmux", "container"])
        assert "test" in str(error)
        assert "tmux" in str(error)
        assert "container" in str(error)
        assert "--backend" in str(error)

    def test_attributes(self) -> None:
        """Verify error attributes are set correctly."""
        error = SessionAmbiguousError("mybot", ["tmux", "container"])
        assert error.name == "mybot"
        assert error.backends == ["tmux", "container"]


# ============================================================================
# SessionManager validation tests
# ============================================================================


class TestSessionManagerValidation:
    """Tests for SessionManager input validation."""

    def test_invalid_session_name_empty(self) -> None:
        """Reject empty session name."""
        with pytest.raises(SessionConfigError, match="cannot be empty"):
            SessionManager("")

    def test_invalid_session_name_starts_with_number(self) -> None:
        """Reject session name starting with number."""
        with pytest.raises(SessionConfigError, match="must start with letter"):
            SessionManager("123bot")

    def test_invalid_session_name_special_chars(self) -> None:
        """Reject session name with special characters."""
        with pytest.raises(SessionConfigError, match="must start with letter"):
            SessionManager("my;bot")

    def test_invalid_image_name(self, mock_container_runner: MagicMock) -> None:
        """Reject invalid container image name."""
        with pytest.raises(SessionConfigError, match="Invalid image name"):
            SessionManager("test", backend="container", image="Invalid Image")

    def test_invalid_command_dangerous(self, mock_tmux_runner: MagicMock) -> None:
        """Reject commands with dangerous patterns."""
        with pytest.raises(SessionConfigError, match="dangerous"):
            SessionManager("test", command="python app.py; rm -rf /")
