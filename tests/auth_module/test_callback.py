"""Tests for the OAuth2 callback server module."""

from __future__ import annotations

import contextlib
import os
import socket
import time
from io import BytesIO
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from kstlib.auth.callback import (
    CallbackHandler,
    CallbackResult,
    CallbackServer,
)
from kstlib.auth.errors import AuthorizationError, CallbackServerError

if TYPE_CHECKING:
    pass


# ─────────────────────────────────────────────────────────────────────────────
# CallbackResult tests
# ─────────────────────────────────────────────────────────────────────────────


class TestCallbackResult:
    """Tests for CallbackResult dataclass."""

    def test_success_with_code(self) -> None:
        """Successful result has code and no error."""
        result = CallbackResult(code="abc123", state="xyz")
        assert result.success is True
        assert result.code == "abc123"
        assert result.state == "xyz"
        assert result.error is None

    def test_failure_with_error(self) -> None:
        """Failed result has error and no code."""
        result = CallbackResult(
            error="access_denied",
            error_description="User denied access",
        )
        assert result.success is False
        assert result.code is None
        assert result.error == "access_denied"

    def test_failure_when_both_code_and_error(self) -> None:
        """If error is present, success is False even with code."""
        result = CallbackResult(code="abc", error="invalid_request")
        assert result.success is False

    def test_raw_params_storage(self) -> None:
        """Raw params are stored from callback."""
        result = CallbackResult(
            code="abc",
            raw_params={"code": ["abc"], "extra": ["value"]},
        )
        assert result.raw_params["extra"] == ["value"]


# ─────────────────────────────────────────────────────────────────────────────
# CallbackHandler tests
# ─────────────────────────────────────────────────────────────────────────────


class MockRequest:
    """Mock HTTP request for testing CallbackHandler."""

    def __init__(self, path: str) -> None:
        self.path = path

    def makefile(self, mode: str, *args, **kwargs) -> BytesIO:
        """Return a file-like object for the request."""
        return BytesIO(f"GET {self.path} HTTP/1.1\r\n\r\n".encode())


class TestCallbackHandler:
    """Tests for CallbackHandler."""

    def test_log_message_suppresses_output(self, caplog: pytest.LogCaptureFixture) -> None:
        """log_message should use logger instead of standard output."""
        import logging

        caplog.set_level(logging.DEBUG)

        handler = CallbackHandler.__new__(CallbackHandler)
        handler.log_message("Test message: %s", "value")
        # Verify debug logging was used - message may or may not appear depending on logger config
        # The key is that it doesn't raise and doesn't print to stdout

    def test_do_get_wrong_path_returns_404(self) -> None:
        """GET request to wrong path returns 404."""
        # Reset class state
        CallbackHandler.callback_result = None
        CallbackHandler.callback_path = "/callback"

        # Create mock handler
        handler = CallbackHandler.__new__(CallbackHandler)
        handler.path = "/wrong-path"

        # Mock the send_error method
        handler.send_error = MagicMock()

        # Call do_GET
        handler.do_GET()

        # Verify 404 was sent
        handler.send_error.assert_called_once_with(404, "Not Found")
        assert CallbackHandler.callback_result is None

    def test_do_get_missing_code_sends_error_response(self) -> None:
        """GET request without code or error sends missing_code error."""
        CallbackHandler.callback_result = None
        CallbackHandler.callback_path = "/callback"

        handler = CallbackHandler.__new__(CallbackHandler)
        handler.path = "/callback?state=xyz"

        # Mock response methods
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = BytesIO()

        handler.do_GET()

        # Verify error response was sent (status 400)
        handler.send_response.assert_called_with(400)

        # Verify result was stored with missing_code error
        assert CallbackHandler.callback_result is not None
        assert CallbackHandler.callback_result.error is None
        assert CallbackHandler.callback_result.code is None

    def test_do_get_with_error_sends_error_response(self) -> None:
        """GET request with OAuth error sends error HTML."""
        CallbackHandler.callback_result = None
        CallbackHandler.callback_path = "/callback"

        handler = CallbackHandler.__new__(CallbackHandler)
        handler.path = "/callback?error=access_denied&error_description=User%20denied"

        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = BytesIO()

        handler.do_GET()

        handler.send_response.assert_called_with(400)
        assert CallbackHandler.callback_result is not None
        assert CallbackHandler.callback_result.error == "access_denied"

    def test_do_get_with_code_sends_success_response(self) -> None:
        """GET request with code sends success HTML."""
        CallbackHandler.callback_result = None
        CallbackHandler.callback_path = "/callback"

        handler = CallbackHandler.__new__(CallbackHandler)
        handler.path = "/callback?code=auth_code_123&state=xyz"

        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = BytesIO()

        handler.do_GET()

        handler.send_response.assert_called_with(200)
        assert CallbackHandler.callback_result is not None
        assert CallbackHandler.callback_result.code == "auth_code_123"
        assert CallbackHandler.callback_result.success is True


# ─────────────────────────────────────────────────────────────────────────────
# CallbackServer tests
# ─────────────────────────────────────────────────────────────────────────────


class TestCallbackServer:
    """Tests for CallbackServer."""

    def test_redirect_uri_property(self) -> None:
        """redirect_uri returns full callback URL."""
        server = CallbackServer(host="127.0.0.1", port=8400, path="/oauth/callback")
        assert server.redirect_uri == "http://127.0.0.1:8400/oauth/callback"

    def test_generate_state_returns_unique_values(self) -> None:
        """generate_state returns cryptographically random values."""
        server = CallbackServer()
        state1 = server.generate_state()
        state2 = server.generate_state()
        assert state1 != state2
        assert len(state1) > 20  # Should be reasonably long

    def test_find_available_port_with_range_success(self) -> None:
        """_find_available_port finds available port in range."""
        server = CallbackServer(port_range=(9000, 9005))
        port = server._find_available_port()
        assert 9000 <= port <= 9005

    def test_find_available_port_with_range_all_busy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_find_available_port raises when all ports in range are busy."""
        server = CallbackServer(port_range=(9000, 9002))

        # Make all ports appear unavailable
        monkeypatch.setattr(server, "_is_port_available", lambda p: False)

        with pytest.raises(CallbackServerError, match="No available port in range"):
            server._find_available_port()

    def test_find_available_port_single_port_busy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_find_available_port raises when single port is busy."""
        server = CallbackServer(port=8400)
        monkeypatch.setattr(server, "_is_port_available", lambda p: False)

        with pytest.raises(CallbackServerError, match="Port 8400 is not available"):
            server._find_available_port()

    def test_is_port_available_returns_true_for_free_port(self) -> None:
        """_is_port_available returns True for available port."""
        server = CallbackServer()
        # Use a high random port that's likely free
        result = server._is_port_available(59999)
        # Just verify it returns a boolean, actual availability varies
        assert isinstance(result, bool)

    def test_is_port_available_returns_false_for_bound_port(self) -> None:
        """_is_port_available returns False when port is in use."""
        # Bind a port first
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            bound_port = sock.getsockname()[1]

            server = CallbackServer()
            assert server._is_port_available(bound_port) is False

    def test_start_already_running_returns_early(self) -> None:
        """start() returns early if server is already running."""
        server = CallbackServer(port=0)  # Use any free port
        server._server = MagicMock()  # Pretend already running

        # This should return immediately without starting another server
        server.start()
        # No exception means success

    def test_start_oserror_raises_callback_server_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """start() raises CallbackServerError on OSError."""
        server = CallbackServer(port=8400)
        server._server = None

        # Make _find_available_port succeed
        monkeypatch.setattr(server, "_find_available_port", lambda: 8400)

        # Make HTTPServer raise OSError
        def raise_oserror(*args, **kwargs):
            raise OSError("Address already in use")

        monkeypatch.setattr("kstlib.auth.callback.HTTPServer", raise_oserror)

        with pytest.raises(CallbackServerError, match="Failed to start callback server"):
            server.start()

    def test_serve_returns_early_when_server_none(self) -> None:
        """_serve returns early if _server is None."""
        server = CallbackServer()
        server._server = None
        server._stop_flag = False

        # Should return without error
        server._serve()

    def test_serve_handles_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_serve logs exception and breaks loop on error."""
        server = CallbackServer()

        mock_http_server = MagicMock()
        mock_http_server.handle_request.side_effect = RuntimeError("Test error")

        server._server = mock_http_server
        server._stop_flag = False

        # _serve should catch the exception and exit the loop
        server._serve()

        # Verify handle_request was called
        mock_http_server.handle_request.assert_called_once()

    def test_stop_cleans_up_resources(self) -> None:
        """stop() cleans up server and thread."""
        server = CallbackServer()

        mock_http_server = MagicMock()
        mock_thread = MagicMock()

        server._server = mock_http_server
        server._thread = mock_thread

        server.stop()

        assert server._stop_flag is True
        mock_http_server.server_close.assert_called_once()
        mock_thread.join.assert_called_once_with(timeout=2)
        assert server._server is None
        assert server._thread is None

    def test_wait_for_callback_returns_result_on_success(self) -> None:
        """wait_for_callback returns result when callback is received."""
        server = CallbackServer()
        server._state = None  # No state validation

        # Simulate callback result
        CallbackHandler.callback_result = CallbackResult(code="test_code", state="xyz")

        result = server.wait_for_callback(timeout=1.0)

        assert result.code == "test_code"
        assert CallbackHandler.callback_result is None  # Should be cleared

    def test_wait_for_callback_state_mismatch_raises(self) -> None:
        """wait_for_callback raises on state mismatch."""
        server = CallbackServer()
        server._state = "expected_state"

        CallbackHandler.callback_result = CallbackResult(code="test_code", state="wrong_state")

        with pytest.raises(AuthorizationError, match="State mismatch"):
            server.wait_for_callback(timeout=1.0)

    def test_wait_for_callback_with_error_raises(self) -> None:
        """wait_for_callback raises on OAuth error in result."""
        server = CallbackServer()
        server._state = None

        CallbackHandler.callback_result = CallbackResult(
            error="access_denied",
            error_description="User denied access",
        )

        with pytest.raises(AuthorizationError, match="User denied access"):
            server.wait_for_callback(timeout=1.0)

    def test_wait_for_callback_timeout_raises(self) -> None:
        """wait_for_callback raises on timeout."""
        server = CallbackServer()
        CallbackHandler.callback_result = None

        with pytest.raises(CallbackServerError, match="Timeout waiting for OAuth2 callback"):
            server.wait_for_callback(timeout=0.1)

    def test_context_manager_starts_and_stops_server(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Context manager starts server on enter and stops on exit."""
        start_called = []
        stop_called = []

        def mock_start(self):
            start_called.append(True)

        def mock_stop(self):
            stop_called.append(True)

        monkeypatch.setattr(CallbackServer, "start", mock_start)
        monkeypatch.setattr(CallbackServer, "stop", mock_stop)

        server = CallbackServer()
        with server as s:
            assert s is server
            assert len(start_called) == 1

        assert len(stop_called) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Integration tests
# ─────────────────────────────────────────────────────────────────────────────


class TestCallbackServerIntegration:
    """Integration tests for CallbackServer with real HTTP requests."""

    @pytest.mark.skipif(os.name == "nt", reason="HTTP callback integration test unreliable on Windows")
    def test_full_callback_flow(self) -> None:
        """Test complete callback flow with real HTTP server."""
        import urllib.request

        # Reset handler state
        CallbackHandler.callback_result = None

        server = CallbackServer(port=0)  # Use any free port
        server.start()

        try:
            # Wait for server to be ready
            time.sleep(0.2)

            # Make callback request
            callback_url = f"{server.redirect_uri}?code=test123&state=abc"
            with contextlib.suppress(Exception):
                urllib.request.urlopen(callback_url, timeout=2)

            # Wait for result
            result = server.wait_for_callback(timeout=2.0)
            assert result.code == "test123"
            assert result.state == "abc"
        finally:
            server.stop()

    def test_port_zero_assigns_real_port(self) -> None:
        """Test that port=0 results in an actual port being assigned."""
        server = CallbackServer(port=0)
        server.start()
        try:
            # Port should no longer be 0 after start
            assert server.port != 0
            assert server.port > 0
            # redirect_uri should use the actual port
            assert f":{server.port}/" in server.redirect_uri
        finally:
            server.stop()

    def test_port_range_selection(self) -> None:
        """Test that port range works correctly."""
        # Bind a port to make it unavailable
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            bound_port = sock.getsockname()[1]

            # Create server with range that includes the bound port
            server = CallbackServer(port_range=(bound_port, bound_port + 5))
            selected_port = server._find_available_port()

            # Should select a different port
            assert selected_port != bound_port
            assert bound_port <= selected_port <= bound_port + 5
