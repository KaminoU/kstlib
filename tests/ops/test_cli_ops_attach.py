"""Tests for the ops attach CLI command."""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from kstlib.cli.app import app
from kstlib.ops.exceptions import OpsError, SessionNotFoundError

# Force-import the actual module so patching targets are stable
importlib.import_module("kstlib.cli.commands.ops.attach")
attach_mod = sys.modules["kstlib.cli.commands.ops.attach"]

pytestmark = pytest.mark.cli

runner = CliRunner()


# ============================================================================
# Fixtures and Helpers
# ============================================================================


def _make_mock_manager(*, exists: bool = True, is_running: bool = True) -> MagicMock:
    """Create a mock SessionManager with configurable state.

    Args:
        exists: Return value for manager.exists().
        is_running: Return value for manager.is_running().

    Returns:
        Configured MagicMock acting as a SessionManager.
    """
    mock = MagicMock()
    mock.exists.return_value = exists
    mock.is_running.return_value = is_running
    mock.attach.return_value = None
    return mock


# ============================================================================
# Tests for ops attach
# ============================================================================


class TestOpsAttach:
    """Tests for the ops attach CLI command."""

    def test_attach_success(self) -> None:
        """Attach to a running session calls manager.attach()."""
        mock_manager = _make_mock_manager(exists=True, is_running=True)
        with patch.object(attach_mod, "get_session_manager", return_value=mock_manager):
            result = runner.invoke(app, ["ops", "attach", "dev"])
        assert result.exit_code == 0
        mock_manager.attach.assert_called_once()

    def test_attach_with_backend_option(self) -> None:
        """Attach passes the --backend option to get_session_manager."""
        mock_manager = _make_mock_manager(exists=True, is_running=True)
        with patch.object(attach_mod, "get_session_manager", return_value=mock_manager) as mock_gsm:
            result = runner.invoke(app, ["ops", "attach", "prod", "--backend", "tmux"])
        assert result.exit_code == 0
        mock_gsm.assert_called_once_with("prod", backend="tmux")
        mock_manager.attach.assert_called_once()

    def test_attach_session_not_found_via_exists(self) -> None:
        """Attach exits with code 1 when session does not exist."""
        mock_manager = _make_mock_manager(exists=False)
        with patch.object(attach_mod, "get_session_manager", return_value=mock_manager):
            result = runner.invoke(app, ["ops", "attach", "ghost"])
        assert result.exit_code == 1
        assert "not found" in result.stdout.lower()
        mock_manager.attach.assert_not_called()

    def test_attach_session_not_running(self) -> None:
        """Attach exits with code 1 when session exists but is not running."""
        mock_manager = _make_mock_manager(exists=True, is_running=False)
        with patch.object(attach_mod, "get_session_manager", return_value=mock_manager):
            result = runner.invoke(app, ["ops", "attach", "stopped"])
        assert result.exit_code == 1
        assert "not running" in result.stdout.lower()
        mock_manager.attach.assert_not_called()

    def test_attach_raises_session_not_found_error(self) -> None:
        """Attach handles SessionNotFoundError raised during attach()."""
        mock_manager = _make_mock_manager(exists=True, is_running=True)
        mock_manager.attach.side_effect = SessionNotFoundError("dev", "tmux")
        with patch.object(attach_mod, "get_session_manager", return_value=mock_manager):
            result = runner.invoke(app, ["ops", "attach", "dev"])
        assert result.exit_code == 1
        assert "not found" in result.stdout.lower()

    def test_attach_raises_ops_error(self) -> None:
        """Attach handles OpsError raised during attach()."""
        mock_manager = _make_mock_manager(exists=True, is_running=True)
        mock_manager.attach.side_effect = OpsError("terminal not interactive")
        with patch.object(attach_mod, "get_session_manager", return_value=mock_manager):
            result = runner.invoke(app, ["ops", "attach", "dev"])
        assert result.exit_code == 1
        assert "terminal not interactive" in result.stdout.lower()

    def test_attach_help(self) -> None:
        """Attach --help displays usage information."""
        result = runner.invoke(app, ["ops", "attach", "--help"])
        assert result.exit_code == 0
        assert "--backend" in result.stdout
        assert "NAME" in result.stdout
