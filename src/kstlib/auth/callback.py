"""Local callback server for OAuth2 authorization code flow."""

from __future__ import annotations

import html
import secrets
import socket
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

from typing_extensions import Self

from kstlib.auth.errors import AuthorizationError, CallbackServerError
from kstlib.logging import TRACE_LEVEL, get_logger

if TYPE_CHECKING:
    import types

logger = get_logger(__name__)

# Defense in depth: maximum timeout regardless of config (10 minutes)
_CALLBACK_TIMEOUT_HARD_LIMIT = 600

# HTML templates for callback responses
SUCCESS_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>Authentication Successful</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               display: flex; justify-content: center; align-items: center; height: 100vh;
               margin: 0; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }}
        .container {{ background: white; padding: 40px 60px; border-radius: 12px;
                     box-shadow: 0 10px 40px rgba(0,0,0,0.2); text-align: center; }}
        h1 {{ color: #22c55e; margin-bottom: 10px; }}
        p {{ color: #666; }}
        .icon {{ font-size: 48px; margin-bottom: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">✓</div>
        <h1>Authentication Successful</h1>
        <p>You can close this window and return to your application.</p>
    </div>
</body>
</html>"""

ERROR_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>Authentication Failed</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               display: flex; justify-content: center; align-items: center; height: 100vh;
               margin: 0; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }}
        .container {{ background: white; padding: 40px 60px; border-radius: 12px;
                     box-shadow: 0 10px 40px rgba(0,0,0,0.2); text-align: center; }}
        h1 {{ color: #ef4444; margin-bottom: 10px; }}
        p {{ color: #666; }}
        .error {{ color: #999; font-size: 12px; margin-top: 20px; font-family: monospace; }}
        .icon {{ font-size: 48px; margin-bottom: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">✗</div>
        <h1>Authentication Failed</h1>
        <p>{error_description}</p>
        <p class="error">{error_code}</p>
    </div>
</body>
</html>"""


@dataclass
class CallbackResult:
    """Result from the OAuth2 callback.

    Attributes:
        code: Authorization code (on success).
        state: State parameter for CSRF validation.
        error: OAuth2 error code (on failure).
        error_description: Human-readable error description.
        raw_params: All query parameters from callback.
    """

    code: str | None = None
    state: str | None = None
    error: str | None = None
    error_description: str | None = None
    raw_params: dict[str, list[str]] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Check if callback was successful."""
        return self.code is not None and self.error is None


class CallbackHandler(BaseHTTPRequestHandler):
    """HTTP request handler for OAuth2 callback."""

    # Class-level storage for result (set by server)
    callback_result: CallbackResult | None = None
    callback_path: str = "/callback"
    expected_state: str | None = None

    def log_message(self, fmt: str, *args: Any) -> None:  # pylint: disable=arguments-differ
        """Suppress default HTTP logging."""
        logger.debug("Callback server: %s", fmt % args)

    def do_GET(self) -> None:
        """Handle GET request (OAuth2 callback)."""
        parsed = urlparse(self.path)

        # Only handle the callback path
        if not parsed.path.rstrip("/").endswith(self.callback_path.rstrip("/")):
            self.send_error(404, "Not Found")
            return

        # Parse query parameters
        params = parse_qs(parsed.query)

        # Extract OAuth2 parameters
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]
        error = params.get("error", [None])[0]
        error_description = params.get("error_description", ["Unknown error"])[0]

        if logger.isEnabledFor(TRACE_LEVEL):
            # Redact code for security
            redacted_code = f"{code[:8]}...{code[-4:]}" if code and len(code) > 12 else "[short]"
            logger.log(
                TRACE_LEVEL,
                "[CALLBACK] Received: code=%s | state=%s | error=%s",
                redacted_code if code else None,
                state,
                error,
            )

        # Store result
        CallbackHandler.callback_result = CallbackResult(
            code=code,
            state=state,
            error=error,
            error_description=error_description if error else None,
            raw_params=params,
        )

        # Send response
        if error:
            self._send_error_response(error, error_description)
        elif code:
            self._send_success_response()
        else:
            self._send_error_response("missing_code", "No authorization code received")

    def _send_success_response(self) -> None:
        """Send success HTML response."""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(SUCCESS_HTML.encode("utf-8"))

    def _send_error_response(self, error: str, description: str) -> None:
        """Send error HTML response."""
        self.send_response(400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        # Escape user-controlled values to prevent XSS
        safe_html = ERROR_HTML.format(
            error_code=html.escape(error),
            error_description=html.escape(description),
        )
        self.wfile.write(safe_html.encode("utf-8"))


class CallbackServer:  # pylint: disable=too-many-instance-attributes
    """Local HTTP server to receive OAuth2 authorization callbacks.

    The server runs in a background thread and waits for the IdP to redirect
    the user back with an authorization code.

    Example:
        >>> server = CallbackServer(port=8400)  # doctest: +SKIP
        >>> server.start()  # doctest: +SKIP
        >>> # User completes authentication in browser
        >>> result = server.wait_for_callback(timeout=120)  # doctest: +SKIP
        >>> if result.success:  # doctest: +SKIP
        ...     print(f"Got code: {result.code}")
        >>> server.stop()  # doctest: +SKIP
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8400,
        *,
        path: str = "/callback",
        port_range: tuple[int, int] | None = None,
    ) -> None:
        """Initialize the callback server.

        Args:
            host: Host to bind to.
            port: Port to listen on.
            path: URL path for callback endpoint.
            port_range: Optional (min, max) port range to try if port is busy.
        """
        self.host = host
        self.port = port
        self.path = path
        self.port_range = port_range
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._state: str | None = None
        self._stop_flag: bool = False

    @property
    def redirect_uri(self) -> str:
        """Get the full redirect URI for OAuth2 configuration."""
        return f"http://{self.host}:{self.port}{self.path}"

    def generate_state(self) -> str:
        """Generate a cryptographically secure state parameter."""
        self._state = secrets.token_urlsafe(32)
        return self._state

    def _find_available_port(self) -> int:
        """Find an available port within the configured range.

        Raises:
            CallbackServerError: If no port is available in the configured range.
        """
        if self.port_range:
            min_port, max_port = self.port_range
            if logger.isEnabledFor(TRACE_LEVEL):
                logger.log(TRACE_LEVEL, "[CALLBACK] Scanning port range %d-%d", min_port, max_port)
            for port in range(min_port, max_port + 1):
                if self._is_port_available(port):
                    if logger.isEnabledFor(TRACE_LEVEL):
                        logger.log(TRACE_LEVEL, "[CALLBACK] Found available port %d", port)
                    return port
            msg = f"No available port in range {min_port}-{max_port}"
            raise CallbackServerError(msg)

        if self._is_port_available(self.port):
            if logger.isEnabledFor(TRACE_LEVEL):
                logger.log(TRACE_LEVEL, "[CALLBACK] Port %d is available", self.port)
            return self.port

        msg = f"Port {self.port} is not available"
        raise CallbackServerError(msg, port=self.port)

    def _is_port_available(self, port: int) -> bool:
        """Check if a port is available for binding."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((self.host, port))
                return True
            except OSError:
                return False

    def start(self) -> None:
        """Start the callback server in a background thread.

        Raises:
            CallbackServerError: If server fails to start.
        """
        if self._server is not None:
            return  # Already running

        # Reset state
        self._stop_flag = False
        CallbackHandler.callback_result = None
        CallbackHandler.callback_path = self.path
        CallbackHandler.expected_state = self._state

        # Find available port
        self.port = self._find_available_port()

        if logger.isEnabledFor(TRACE_LEVEL):
            logger.log(TRACE_LEVEL, "[CALLBACK] Binding server to %s:%d", self.host, self.port)

        try:
            self._server = HTTPServer((self.host, self.port), CallbackHandler)
            self._server.timeout = 0.5  # Short timeout for responsive shutdown
            # Update port to actual assigned port (important when port=0)
            self.port = self._server.server_address[1]

            if logger.isEnabledFor(TRACE_LEVEL):
                logger.log(TRACE_LEVEL, "[CALLBACK] Server bound successfully to port %d", self.port)
        except OSError as e:
            msg = f"Failed to start callback server on {self.host}:{self.port}"
            raise CallbackServerError(msg, port=self.port) from e

        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        logger.info("Callback server started at %s", self.redirect_uri)

    def _serve(self) -> None:
        """Server loop running in background thread."""
        if self._server is None:
            return
        while not self._stop_flag and self._server:
            try:
                self._server.handle_request()
            except Exception:  # pylint: disable=broad-exception-caught
                if not self._stop_flag:
                    logger.exception("Error handling callback request")
                break

    def stop(self) -> None:
        """Stop the callback server."""
        self._stop_flag = True
        if self._server is not None:
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        logger.debug("Callback server stopped")

    def wait_for_callback(self, timeout: float = 120.0) -> CallbackResult:
        """Wait for the OAuth2 callback.

        Args:
            timeout: Maximum time to wait in seconds (capped at 600s).

        Returns:
            CallbackResult with authorization code or error.

        Raises:
            CallbackServerError: If timeout expires without callback.
            AuthorizationError: If callback contains an error.
        """
        # Defense in depth: cap timeout regardless of config
        timeout = min(timeout, _CALLBACK_TIMEOUT_HARD_LIMIT)
        start_time = time.time()
        while time.time() - start_time < timeout:
            if CallbackHandler.callback_result is not None:
                result = CallbackHandler.callback_result
                CallbackHandler.callback_result = None  # Clear for next use

                # Validate state if we generated one
                if self._state and result.state != self._state:
                    if logger.isEnabledFor(TRACE_LEVEL):
                        logger.log(
                            TRACE_LEVEL,
                            "[CALLBACK] State mismatch: expected=%s | received=%s",
                            self._state,
                            result.state,
                        )
                    raise AuthorizationError(
                        "State mismatch - possible CSRF attack",
                        error_code="state_mismatch",
                    )

                if logger.isEnabledFor(TRACE_LEVEL):
                    logger.log(TRACE_LEVEL, "[CALLBACK] State validated successfully")

                if result.error:
                    raise AuthorizationError(
                        result.error_description or result.error,
                        error_code=result.error,
                        error_description=result.error_description,
                    )

                return result

            time.sleep(0.1)

        msg = f"Timeout waiting for OAuth2 callback after {timeout}s"
        raise CallbackServerError(msg)

    def __enter__(self) -> Self:
        """Context manager entry - start server."""
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Context manager exit - stop server."""
        self.stop()


__all__ = [
    "CallbackHandler",
    "CallbackResult",
    "CallbackServer",
]
