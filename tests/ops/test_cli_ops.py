"""Tests for the ops CLI commands."""

from __future__ import annotations

import importlib
import json
import sys
from collections.abc import Generator
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from kstlib.cli.app import app
from kstlib.ops.models import BackendType, SessionState, SessionStatus

# Force-import the actual modules (not the re-exported functions)
importlib.import_module("kstlib.cli.commands.ops.list_sessions")
importlib.import_module("kstlib.cli.commands.ops.status")
list_sessions_mod = sys.modules["kstlib.cli.commands.ops.list_sessions"]
status_mod = sys.modules["kstlib.cli.commands.ops.status"]

if TYPE_CHECKING:
    pass


runner = CliRunner()


# ============================================================================
# Fixtures and Helpers
# ============================================================================


def make_mock_manager() -> MagicMock:
    """Create a mock SessionManager."""
    mock = MagicMock()
    mock.exists.return_value = True
    mock.is_running.return_value = True
    mock.start.return_value = SessionStatus(
        name="test",
        state=SessionState.RUNNING,
        backend=BackendType.TMUX,
        pid=12345,
    )
    mock.status.return_value = SessionStatus(
        name="test",
        state=SessionState.RUNNING,
        backend=BackendType.TMUX,
        pid=12345,
        window_count=1,
    )
    mock.logs.return_value = "Log line 1\nLog line 2\n"
    mock.stop.return_value = True
    return mock


def _extract_json(stdout: str) -> Any:
    """Extract JSON array or object from CLI output that may contain log lines.

    Args:
        stdout: Raw CLI stdout potentially with log warnings before JSON.

    Returns:
        Parsed JSON data.
    """
    # Find the first '[' or '{' which starts the JSON payload
    for i, ch in enumerate(stdout):
        if ch in ("[", "{"):
            return json.loads(stdout[i:])
    return json.loads(stdout)


def _make_config_box(sessions: dict[str, Any] | Any) -> MagicMock:
    """Build a mock config Box with ops.sessions data.

    Args:
        sessions: Value for ops.sessions (dict, string, etc. for testing).

    Returns:
        MagicMock that behaves like Box.get().
    """
    config: dict[str, Any] = {"ops": {"sessions": sessions}}
    mock_box = MagicMock()
    mock_box.get.side_effect = lambda key, default=None: config.get(key, default)
    return mock_box


@pytest.fixture
def mock_session_manager() -> Generator[MagicMock, None, None]:
    """Fixture for mocked SessionManager."""
    mock_manager = make_mock_manager()
    with patch("kstlib.cli.commands.ops.common.SessionManager") as mock_class:
        # from_config raises OpsError to force fallback to regular init
        from kstlib.ops.exceptions import OpsError

        mock_class.from_config.side_effect = OpsError("Not in config")
        mock_class.return_value = mock_manager
        yield mock_manager


# ============================================================================
# Test ops --help
# ============================================================================


class TestOpsHelp:
    """Tests for ops help command."""

    def test_ops_help(self) -> None:
        """Display ops help."""
        result = runner.invoke(app, ["ops", "--help"])
        assert result.exit_code == 0
        assert "start" in result.stdout
        assert "stop" in result.stdout
        assert "attach" in result.stdout
        assert "status" in result.stdout
        assert "logs" in result.stdout
        assert "list" in result.stdout


# ============================================================================
# Test ops start
# ============================================================================


class TestOpsStart:
    """Tests for ops start command."""

    def test_start_session(self, mock_session_manager: MagicMock) -> None:
        """Start a session successfully."""
        result = runner.invoke(
            app,
            ["ops", "start", "test", "--backend", "tmux", "--command", "echo hello"],
        )
        assert result.exit_code == 0
        assert "started" in result.stdout.lower()

    def test_start_help(self) -> None:
        """Display start help."""
        result = runner.invoke(app, ["ops", "start", "--help"])
        assert result.exit_code == 0
        assert "--backend" in result.stdout
        assert "--command" in result.stdout


# ============================================================================
# Test ops stop
# ============================================================================


class TestOpsStop:
    """Tests for ops stop command."""

    def test_stop_session(self, mock_session_manager: MagicMock) -> None:
        """Stop a session successfully."""
        result = runner.invoke(app, ["ops", "stop", "test"])
        assert result.exit_code == 0
        assert "stopped" in result.stdout.lower()

    def test_stop_not_found(self, mock_session_manager: MagicMock) -> None:
        """Stop a session that doesn't exist."""
        mock_session_manager.exists.return_value = False
        result = runner.invoke(app, ["ops", "stop", "nonexistent"])
        assert result.exit_code == 1
        assert "not found" in result.stdout.lower()


# ============================================================================
# Test ops status
# ============================================================================


class TestOpsStatus:
    """Tests for ops status command."""

    def test_status_session(self, mock_session_manager: MagicMock) -> None:
        """Get status of a session."""
        result = runner.invoke(app, ["ops", "status", "test"])
        assert result.exit_code == 0
        assert "running" in result.stdout.lower()

    def test_status_json(self, mock_session_manager: MagicMock) -> None:
        """Get status in JSON format."""
        result = runner.invoke(app, ["ops", "status", "test", "--json"])
        assert result.exit_code == 0
        assert '"name"' in result.stdout
        assert '"state"' in result.stdout


# ============================================================================
# Test ops logs
# ============================================================================


class TestOpsLogs:
    """Tests for ops logs command."""

    def test_logs_session(self, mock_session_manager: MagicMock) -> None:
        """Get logs from a session."""
        result = runner.invoke(app, ["ops", "logs", "test"])
        assert result.exit_code == 0
        assert "Log line" in result.stdout


# ============================================================================
# Test ops list
# ============================================================================


class TestOpsList:
    """Tests for ops list command."""

    def test_list_help(self) -> None:
        """Display list help."""
        result = runner.invoke(app, ["ops", "list", "--help"])
        assert result.exit_code == 0
        assert "--backend" in result.stdout
        assert "--json" in result.stdout


# ============================================================================
# Test ops list - Config-driven sessions (functional)
# ============================================================================


class TestOpsListConfigDriven:
    """Tests for config-driven session listing."""

    def test_list_shows_defined_sessions(self) -> None:
        """Config sessions appear with state 'defined'."""
        config_box = _make_config_box(
            {
                "myapp": {"backend": "tmux", "command": "python app.py"},
            }
        )
        with (
            patch.object(list_sessions_mod, "TmuxRunner") as mock_tmux,
            patch.object(list_sessions_mod, "ContainerRunner") as mock_container,
            patch.object(list_sessions_mod, "get_config", return_value=config_box),
        ):
            mock_tmux.return_value.list_sessions.return_value = []
            mock_container.return_value.list_sessions.return_value = []
            result = runner.invoke(app, ["ops", "list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert len(data) == 1
        assert data[0]["name"] == "myapp"
        assert data[0]["state"] == "defined"
        assert data[0]["backend"] == "tmux"

    def test_list_running_overrides_defined(self) -> None:
        """Running session is not duplicated with 'defined'."""
        runtime_session = SessionStatus(
            name="myapp",
            state=SessionState.RUNNING,
            backend=BackendType.TMUX,
            pid=999,
        )
        config_box = _make_config_box(
            {
                "myapp": {"backend": "tmux", "command": "python app.py"},
            }
        )
        with (
            patch.object(list_sessions_mod, "TmuxRunner") as mock_tmux,
            patch.object(list_sessions_mod, "ContainerRunner") as mock_container,
            patch.object(list_sessions_mod, "get_config", return_value=config_box),
        ):
            mock_tmux.return_value.list_sessions.return_value = [runtime_session]
            mock_container.return_value.list_sessions.return_value = []
            result = runner.invoke(app, ["ops", "list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert len(data) == 1
        assert data[0]["state"] == "running"

    def test_list_defined_with_backend_filter(self) -> None:
        """Backend filter applies to config-defined sessions."""
        config_box = _make_config_box(
            {
                "tmux-app": {"backend": "tmux"},
                "container-app": {"backend": "container", "image": "app:latest"},
            }
        )
        with (
            patch.object(list_sessions_mod, "TmuxRunner") as mock_tmux,
            patch.object(list_sessions_mod, "ContainerRunner") as mock_container,
            patch.object(list_sessions_mod, "get_config", return_value=config_box),
        ):
            mock_tmux.return_value.list_sessions.return_value = []
            mock_container.return_value.list_sessions.return_value = []
            result = runner.invoke(app, ["ops", "list", "--backend", "container", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert len(data) == 1
        assert data[0]["name"] == "container-app"

    def test_list_defined_json_output(self) -> None:
        """JSON output includes defined sessions with all fields."""
        config_box = _make_config_box(
            {
                "myapp": {"backend": "container", "image": "myimg:v1"},
            }
        )
        with (
            patch.object(list_sessions_mod, "TmuxRunner") as mock_tmux,
            patch.object(list_sessions_mod, "ContainerRunner") as mock_container,
            patch.object(list_sessions_mod, "get_config", return_value=config_box),
        ):
            mock_tmux.return_value.list_sessions.return_value = []
            mock_container.return_value.list_sessions.return_value = []
            result = runner.invoke(app, ["ops", "list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data[0]["image"] == "myimg:v1"
        assert data[0]["pid"] is None

    def test_list_mixed_runtime_and_defined(self) -> None:
        """Mix of runtime and defined sessions displays correctly."""
        runtime_session = SessionStatus(
            name="running-app",
            state=SessionState.RUNNING,
            backend=BackendType.TMUX,
            pid=111,
        )
        config_box = _make_config_box(
            {
                "running-app": {"backend": "tmux"},
                "defined-app": {"backend": "tmux", "command": "echo hi"},
            }
        )
        with (
            patch.object(list_sessions_mod, "TmuxRunner") as mock_tmux,
            patch.object(list_sessions_mod, "ContainerRunner") as mock_container,
            patch.object(list_sessions_mod, "get_config", return_value=config_box),
        ):
            mock_tmux.return_value.list_sessions.return_value = [runtime_session]
            mock_container.return_value.list_sessions.return_value = []
            result = runner.invoke(app, ["ops", "list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert len(data) == 2
        names = {d["name"] for d in data}
        assert names == {"running-app", "defined-app"}
        states = {d["name"]: d["state"] for d in data}
        assert states["running-app"] == "running"
        assert states["defined-app"] == "defined"


# ============================================================================
# Test ops status - Config fallback for defined sessions
# ============================================================================


class TestOpsStatusConfigFallback:
    """Tests for status config fallback."""

    def test_status_defined_session(self, mock_session_manager: MagicMock) -> None:
        """Status shows 'defined' for config-only session."""
        mock_session_manager.exists.return_value = False
        mock_from_config = MagicMock()
        mock_from_config.config.backend = BackendType.TMUX
        mock_from_config.config.image = None
        with patch.object(status_mod, "SessionManager") as mock_cls:
            mock_cls.from_config.return_value = mock_from_config
            result = runner.invoke(app, ["ops", "status", "myapp"])
        assert result.exit_code == 0
        assert "defined" in result.stdout.lower()

    def test_status_truly_not_found(self, mock_session_manager: MagicMock) -> None:
        """Session not in runtime or config gives error."""
        mock_session_manager.exists.return_value = False
        from kstlib.ops.exceptions import OpsError

        with patch.object(status_mod, "SessionManager") as mock_cls:
            mock_cls.from_config.side_effect = OpsError("Not found")
            result = runner.invoke(app, ["ops", "status", "ghost"])
        assert result.exit_code == 1
        assert "not found" in result.stdout.lower()


# ============================================================================
# Test ops list - Deep defense / security
# ============================================================================


class TestOpsListDeepDefense:
    """Tests for deep defense validation in config session loading."""

    def _invoke_list_json(self, sessions_value: Any) -> Any:
        """Helper to invoke list --json with a given sessions config value.

        Args:
            sessions_value: Value for ops.sessions in config.

        Returns:
            CliRunner result.
        """
        config_box = _make_config_box(sessions_value)
        with (
            patch.object(list_sessions_mod, "TmuxRunner") as mock_tmux,
            patch.object(list_sessions_mod, "ContainerRunner") as mock_container,
            patch.object(list_sessions_mod, "get_config", return_value=config_box),
        ):
            mock_tmux.return_value.list_sessions.return_value = []
            mock_container.return_value.list_sessions.return_value = []
            return runner.invoke(app, ["ops", "list", "--json"])

    def test_list_config_sessions_not_dict(self) -> None:
        """sessions: 'not a dict' is ignored without crash."""
        result = self._invoke_list_json("not a dict")
        assert result.exit_code == 0
        data = _extract_json(result.stdout)
        assert data == []

    def test_list_config_sessions_max_limit(self) -> None:
        """51+ sessions are truncated to 50."""
        sessions = {f"app{i}": {"backend": "tmux"} for i in range(55)}
        result = self._invoke_list_json(sessions)
        assert result.exit_code == 0
        data = _extract_json(result.stdout)
        assert len(data) <= 50

    def test_list_config_invalid_session_name(self) -> None:
        """Session name with '../' is skipped with warning."""
        result = self._invoke_list_json(
            {
                "../evil": {"backend": "tmux"},
                "valid-app": {"backend": "tmux"},
            }
        )
        assert result.exit_code == 0
        data = _extract_json(result.stdout)
        names = {d["name"] for d in data}
        assert "../evil" not in names
        assert "valid-app" in names

    def test_list_config_invalid_backend(self) -> None:
        """Session with invalid backend is skipped."""
        result = self._invoke_list_json(
            {
                "badbackend": {"backend": "malicious"},
            }
        )
        assert result.exit_code == 0
        data = _extract_json(result.stdout)
        assert data == []

    def test_list_config_invalid_image(self) -> None:
        """Session with path traversal image is skipped."""
        result = self._invoke_list_json(
            {
                "badimage": {"backend": "container", "image": "../../etc/passwd"},
            }
        )
        assert result.exit_code == 0
        data = _extract_json(result.stdout)
        assert data == []

    def test_list_config_invalid_command(self) -> None:
        """Session with command injection attempt is skipped."""
        result = self._invoke_list_json(
            {
                "badcmd": {"backend": "tmux", "command": "echo hello; rm -rf /"},
            }
        )
        assert result.exit_code == 0
        data = _extract_json(result.stdout)
        assert data == []

    def test_list_config_invalid_env(self) -> None:
        """Session with non-dict env is skipped."""
        result = self._invoke_list_json(
            {
                "badenv": {"backend": "tmux", "env": "not a dict"},
            }
        )
        assert result.exit_code == 0
        data = _extract_json(result.stdout)
        assert data == []

    def test_list_config_invalid_volumes(self) -> None:
        """Session with path traversal volumes is skipped."""
        result = self._invoke_list_json(
            {
                "badvol": {"backend": "container", "image": "app:latest", "volumes": ["../../../:/root"]},
            }
        )
        assert result.exit_code == 0
        data = _extract_json(result.stdout)
        assert data == []

    def test_list_config_invalid_ports(self) -> None:
        """Session with out-of-range port is skipped."""
        result = self._invoke_list_json(
            {
                "badport": {"backend": "container", "image": "app:latest", "ports": ["99999:80"]},
            }
        )
        assert result.exit_code == 0
        data = _extract_json(result.stdout)
        assert data == []

    def test_list_config_empty_sessions(self) -> None:
        """Empty sessions dict produces zero defined sessions."""
        result = self._invoke_list_json({})
        assert result.exit_code == 0
        data = _extract_json(result.stdout)
        assert data == []

    def test_list_config_no_ops_key(self) -> None:
        """Config without ops key produces zero defined sessions."""
        config: dict[str, Any] = {}
        mock_box = MagicMock()
        mock_box.get.side_effect = lambda key, default=None: config.get(key, default)
        with (
            patch.object(list_sessions_mod, "TmuxRunner") as mock_tmux,
            patch.object(list_sessions_mod, "ContainerRunner") as mock_container,
            patch.object(list_sessions_mod, "get_config", return_value=mock_box),
        ):
            mock_tmux.return_value.list_sessions.return_value = []
            mock_container.return_value.list_sessions.return_value = []
            result = runner.invoke(app, ["ops", "list", "--json"])
        assert result.exit_code == 0
        data = _extract_json(result.stdout)
        assert data == []

    def test_list_config_null_values(self) -> None:
        """Null command and image are accepted as optional fields."""
        result = self._invoke_list_json(
            {
                "nullapp": {"backend": "tmux", "command": None, "image": None},
            }
        )
        assert result.exit_code == 0
        data = _extract_json(result.stdout)
        assert len(data) == 1
        assert data[0]["name"] == "nullapp"
