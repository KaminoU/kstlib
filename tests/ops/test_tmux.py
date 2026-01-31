"""Tests for the TmuxRunner class."""

from __future__ import annotations

import subprocess
from collections.abc import Generator
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from kstlib.ops.exceptions import (
    SessionExistsError,
    SessionNotFoundError,
    SessionStartError,
    TmuxNotFoundError,
)
from kstlib.ops.models import BackendType, SessionConfig, SessionState
from kstlib.ops.tmux import TmuxRunner

if TYPE_CHECKING:
    pass


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_which() -> Generator[MagicMock, None, None]:
    """Mock shutil.which to return tmux path."""
    with patch("kstlib.ops.tmux.shutil.which") as mock:
        mock.return_value = "/usr/bin/tmux"
        yield mock


@pytest.fixture
def mock_run() -> Generator[MagicMock, None, None]:
    """Mock subprocess.run for tmux commands."""
    with patch("kstlib.ops.tmux.subprocess.run") as mock:
        yield mock


@pytest.fixture
def runner(mock_which: MagicMock) -> TmuxRunner:
    """Create a TmuxRunner with mocked binary."""
    return TmuxRunner()


@pytest.fixture
def config() -> SessionConfig:
    """Create a basic session config."""
    return SessionConfig(
        name="test-session",
        backend=BackendType.TMUX,
        command="python app.py",
    )


# ============================================================================
# TmuxRunner initialization tests
# ============================================================================


class TestTmuxRunnerInit:
    """Tests for TmuxRunner initialization."""

    def test_default_binary(self, mock_which: MagicMock) -> None:
        """Use default tmux binary name."""
        runner = TmuxRunner()
        _ = runner.binary  # Access to trigger validation
        mock_which.assert_called_with("tmux")

    def test_custom_binary(self) -> None:
        """Use custom binary path."""
        with patch("kstlib.ops.tmux.shutil.which") as mock:
            mock.return_value = "/custom/tmux"
            runner = TmuxRunner(binary="/custom/tmux")
            assert runner.binary == "/custom/tmux"

    def test_binary_not_found(self) -> None:
        """Raise TmuxNotFoundError when binary not in PATH."""
        with patch("kstlib.ops.tmux.shutil.which") as mock:
            mock.return_value = None
            runner = TmuxRunner()
            with pytest.raises(TmuxNotFoundError, match="not found in PATH"):
                _ = runner.binary


# ============================================================================
# TmuxRunner.exists tests
# ============================================================================


class TestTmuxRunnerExists:
    """Tests for TmuxRunner.exists method."""

    def test_session_exists(
        self,
        runner: TmuxRunner,
        mock_run: MagicMock,
    ) -> None:
        """Return True when session exists."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="",
        )
        assert runner.exists("test-session") is True
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "has-session" in call_args
        assert "test-session" in call_args

    def test_session_not_exists(
        self,
        runner: TmuxRunner,
        mock_run: MagicMock,
    ) -> None:
        """Return False when session does not exist."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="can't find session",
        )
        assert runner.exists("nonexistent") is False


# ============================================================================
# TmuxRunner.start tests
# ============================================================================


class TestTmuxRunnerStart:
    """Tests for TmuxRunner.start method."""

    def test_start_simple_session(
        self,
        runner: TmuxRunner,
        mock_run: MagicMock,
        config: SessionConfig,
    ) -> None:
        """Start a session with default options."""
        # Mock exists check (not exists) and new-session
        mock_run.side_effect = [
            # has-session returns 1 (not exists)
            subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
            # new-session returns 0 (success)
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            # list-sessions for status
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="test-session:1:1234567890:12345\n",
                stderr="",
            ),
        ]
        status = runner.start(config)
        assert status.name == "test-session"
        assert status.state == SessionState.RUNNING
        assert status.backend == BackendType.TMUX

    def test_start_with_working_dir(
        self,
        runner: TmuxRunner,
        mock_run: MagicMock,
    ) -> None:
        """Start session with working directory."""
        config = SessionConfig(
            name="test",
            backend=BackendType.TMUX,
            command="python app.py",
            working_dir="/opt/app",
        )
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="test:1:1234567890:12345\n",
                stderr="",
            ),
        ]
        runner.start(config)
        # Check that new-session was called with -c option
        new_session_call = mock_run.call_args_list[1]
        cmd = new_session_call[0][0]
        assert "-c" in cmd
        assert "/opt/app" in cmd

    def test_start_with_env_vars(
        self,
        runner: TmuxRunner,
        mock_run: MagicMock,
    ) -> None:
        """Start session with environment variables."""
        config = SessionConfig(
            name="test",
            backend=BackendType.TMUX,
            command="python app.py",
            env={"APP_ENV": "production", "DEBUG": "0"},
        )
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="test:1:1234567890:12345\n",
                stderr="",
            ),
        ]
        runner.start(config)
        new_session_call = mock_run.call_args_list[1]
        cmd = new_session_call[0][0]
        assert "-e" in cmd

    def test_start_session_already_exists(
        self,
        runner: TmuxRunner,
        mock_run: MagicMock,
        config: SessionConfig,
    ) -> None:
        """Raise SessionExistsError when session already exists."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,  # has-session succeeds (session exists)
            stdout="",
            stderr="",
        )
        with pytest.raises(SessionExistsError, match="already exists"):
            runner.start(config)

    def test_start_fails(
        self,
        runner: TmuxRunner,
        mock_run: MagicMock,
        config: SessionConfig,
    ) -> None:
        """Raise SessionStartError when tmux command fails."""
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
            subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
                stderr="duplicate session",
            ),
        ]
        with pytest.raises(SessionStartError, match="Failed to start"):
            runner.start(config)


# ============================================================================
# TmuxRunner.stop tests
# ============================================================================


class TestTmuxRunnerStop:
    """Tests for TmuxRunner.stop method."""

    def test_stop_session(
        self,
        runner: TmuxRunner,
        mock_run: MagicMock,
    ) -> None:
        """Stop a running session."""
        mock_run.side_effect = [
            # has-session returns 0 (exists)
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            # send-keys C-c (graceful)
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            # kill-session returns 0
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        ]
        result = runner.stop("test-session")
        assert result is True

    def test_stop_force(
        self,
        runner: TmuxRunner,
        mock_run: MagicMock,
    ) -> None:
        """Stop session without graceful shutdown."""
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        ]
        result = runner.stop("test-session", graceful=False)
        assert result is True
        # Should only call has-session and kill-session, no send-keys
        assert mock_run.call_count == 2

    def test_stop_session_not_found(
        self,
        runner: TmuxRunner,
        mock_run: MagicMock,
    ) -> None:
        """Raise SessionNotFoundError when session does not exist."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="",
        )
        with pytest.raises(SessionNotFoundError, match="not found"):
            runner.stop("nonexistent")

    def test_stop_already_exited(
        self,
        runner: TmuxRunner,
        mock_run: MagicMock,
    ) -> None:
        """Return True when session already exited during stop."""
        mock_run.side_effect = [
            # has-session returns 0 (exists)
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            # send-keys succeeds
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            # kill-session fails (session gone)
            subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
                stderr="session not found",
            ),
            # has-session returns 1 (not exists)
            subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
        ]
        result = runner.stop("test-session")
        assert result is True


# ============================================================================
# TmuxRunner.status tests
# ============================================================================


class TestTmuxRunnerStatus:
    """Tests for TmuxRunner.status method."""

    def test_get_status(
        self,
        runner: TmuxRunner,
        mock_run: MagicMock,
    ) -> None:
        """Get status of a running session."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="test-session:3:1234567890:12345\n",
            stderr="",
        )
        status = runner.status("test-session")
        assert status.name == "test-session"
        assert status.state == SessionState.RUNNING
        assert status.backend == BackendType.TMUX
        assert status.window_count == 3
        assert status.pid == 12345

    def test_status_session_not_found(
        self,
        runner: TmuxRunner,
        mock_run: MagicMock,
    ) -> None:
        """Raise SessionNotFoundError when session does not exist."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="other-session:1:1234567890:12345\n",
            stderr="",
        )
        with pytest.raises(SessionNotFoundError, match="not found"):
            runner.status("nonexistent")

    def test_status_no_server(
        self,
        runner: TmuxRunner,
        mock_run: MagicMock,
    ) -> None:
        """Raise SessionNotFoundError when no tmux server running."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="no server running",
        )
        with pytest.raises(SessionNotFoundError):
            runner.status("test-session")


# ============================================================================
# TmuxRunner.logs tests
# ============================================================================


class TestTmuxRunnerLogs:
    """Tests for TmuxRunner.logs method."""

    def test_get_logs(
        self,
        runner: TmuxRunner,
        mock_run: MagicMock,
    ) -> None:
        """Capture logs from a session."""
        mock_run.side_effect = [
            # has-session returns 0 (exists)
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            # capture-pane returns content
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="Line 1\nLine 2\nLine 3\n",
                stderr="",
            ),
        ]
        logs = runner.logs("test-session", lines=50)
        assert "Line 1" in logs
        assert "Line 2" in logs

    def test_logs_session_not_found(
        self,
        runner: TmuxRunner,
        mock_run: MagicMock,
    ) -> None:
        """Raise SessionNotFoundError when session does not exist."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="",
        )
        with pytest.raises(SessionNotFoundError, match="not found"):
            runner.logs("nonexistent")


# ============================================================================
# TmuxRunner.list_sessions tests
# ============================================================================


class TestTmuxRunnerListSessions:
    """Tests for TmuxRunner.list_sessions method."""

    def test_list_multiple_sessions(
        self,
        runner: TmuxRunner,
        mock_run: MagicMock,
    ) -> None:
        """List all running sessions."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="session1:1:1000000000:111\nsession2:2:1000000001:222\n",
            stderr="",
        )
        sessions = runner.list_sessions()
        assert len(sessions) == 2
        assert sessions[0].name == "session1"
        assert sessions[1].name == "session2"

    def test_list_empty(
        self,
        runner: TmuxRunner,
        mock_run: MagicMock,
    ) -> None:
        """Return empty list when no sessions."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="no server running",
        )
        sessions = runner.list_sessions()
        assert sessions == []


# ============================================================================
# TmuxRunner.send_keys tests
# ============================================================================


class TestTmuxRunnerSendKeys:
    """Tests for TmuxRunner.send_keys method."""

    def test_send_keys_with_enter(
        self,
        runner: TmuxRunner,
        mock_run: MagicMock,
    ) -> None:
        """Send keys with Enter."""
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        ]
        runner.send_keys("test-session", "echo hello")
        send_call = mock_run.call_args_list[1]
        cmd = send_call[0][0]
        assert "send-keys" in cmd
        assert "echo hello" in cmd
        assert "Enter" in cmd

    def test_send_keys_without_enter(
        self,
        runner: TmuxRunner,
        mock_run: MagicMock,
    ) -> None:
        """Send keys without Enter."""
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        ]
        runner.send_keys("test-session", "C-c", enter=False)
        send_call = mock_run.call_args_list[1]
        cmd = send_call[0][0]
        assert "Enter" not in cmd

    def test_send_keys_session_not_found(
        self,
        runner: TmuxRunner,
        mock_run: MagicMock,
    ) -> None:
        """Raise SessionNotFoundError when session does not exist."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="",
        )
        with pytest.raises(SessionNotFoundError, match="not found"):
            runner.send_keys("nonexistent", "test")


# ============================================================================
# TmuxRunner.attach tests
# ============================================================================


class TestTmuxRunnerAttach:
    """Tests for TmuxRunner.attach method."""

    def test_attach_session_not_found(
        self,
        runner: TmuxRunner,
        mock_run: MagicMock,
    ) -> None:
        """Raise SessionNotFoundError when session does not exist."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="",
        )
        with pytest.raises(SessionNotFoundError, match="not found"):
            runner.attach("nonexistent")

    def test_attach_calls_execvp(
        self,
        runner: TmuxRunner,
        mock_run: MagicMock,
    ) -> None:
        """Verify attach calls os.execvp."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="",
        )
        with patch("kstlib.ops.tmux.os.execvp") as mock_execvp:
            runner.attach("test-session")
            mock_execvp.assert_called_once_with(
                "/usr/bin/tmux",
                ["/usr/bin/tmux", "attach-session", "-t", "test-session"],
            )
