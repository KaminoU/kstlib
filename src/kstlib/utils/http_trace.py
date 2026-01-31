"""HTTP trace logging utilities with sensitive data redaction."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs

if TYPE_CHECKING:
    import logging

    import httpx

# Default sensitive keys to redact in request bodies
DEFAULT_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "client_secret",
        "code",
        "refresh_token",
        "access_token",
        "code_verifier",
        "password",
        "api_key",
        "secret",
        "token",
    }
)


class HTTPTraceLogger:
    """Reusable HTTP trace logger with sensitive data redaction.

    This class provides httpx event hooks for logging HTTP requests and responses
    at TRACE level with automatic redaction of sensitive data.

    Args:
        logger: Logger instance to use for trace output.
        trace_level: Logging level for trace messages (default: 5 for TRACE).
        sensitive_keys: Set of keys to redact in request bodies.
        pretty_print: Whether to pretty-print JSON responses.
        max_body_length: Maximum response body length before truncation.

    Examples:
        >>> import logging
        >>> import httpx
        >>> from kstlib.utils.http_trace import HTTPTraceLogger
        >>> tracer = HTTPTraceLogger(logging.getLogger(__name__))
        >>> client = httpx.Client(
        ...     event_hooks={
        ...         "request": [tracer.on_request],
        ...         "response": [tracer.on_response],
        ...     }
        ... )
    """

    def __init__(
        self,
        logger: logging.Logger,
        *,
        trace_level: int = 5,
        sensitive_keys: frozenset[str] | None = None,
        pretty_print: bool = True,
        max_body_length: int = 2000,
    ) -> None:
        """Initialize the HTTP trace logger."""
        self._logger = logger
        self._trace_level = trace_level
        self._sensitive_keys = sensitive_keys or DEFAULT_SENSITIVE_KEYS
        self._pretty_print = pretty_print
        self._max_body_length = max_body_length

    @property
    def sensitive_keys(self) -> frozenset[str]:
        """Return the set of sensitive keys being redacted."""
        return self._sensitive_keys

    def configure(
        self,
        *,
        pretty_print: bool | None = None,
        max_body_length: int | None = None,
    ) -> None:
        """Update trace configuration at runtime.

        Args:
            pretty_print: Whether to pretty-print JSON responses.
            max_body_length: Maximum response body length before truncation.
        """
        if pretty_print is not None:
            self._pretty_print = pretty_print
        if max_body_length is not None:
            self._max_body_length = max_body_length

    def on_request(self, request: httpx.Request) -> None:
        """httpx event hook for outgoing requests (TRACE logging).

        Redacts sensitive data in request body and Authorization headers.

        Args:
            request: The outgoing HTTP request.
        """
        if not self._logger.isEnabledFor(self._trace_level):
            return

        body_str = self._redact_request_body(request.content)
        safe_headers = {k: v for k, v in request.headers.items() if k.lower() != "authorization"}

        self._logger.log(
            self._trace_level,
            "[HTTP] %s %s | headers=%s | body=%s",
            request.method,
            request.url,
            dict(safe_headers) or "{}",
            body_str,
        )

    def on_response(self, response: httpx.Response) -> None:
        """httpx event hook for incoming responses (TRACE logging).

        Optionally pretty-prints JSON and truncates long bodies.

        Args:
            response: The incoming HTTP response.
        """
        if not self._logger.isEnabledFor(self._trace_level):
            return

        body = self._format_response_body(response)

        self._logger.log(
            self._trace_level,
            "[HTTP] %s %s | status=%d | body=\n%s",
            response.request.method,
            response.request.url,
            response.status_code,
            body,
        )

    def _redact_request_body(self, content: bytes | None) -> str:
        """Redact sensitive values from request body.

        Args:
            content: Raw request body bytes.

        Returns:
            String representation with sensitive values redacted.
        """
        if not content:
            return "{}"

        try:
            body_data = parse_qs(content.decode("utf-8"))
            safe_data: dict[str, Any] = {}

            for key, values in body_data.items():
                val = values[0] if len(values) == 1 else values
                if key in self._sensitive_keys:
                    safe_data[key] = f"[REDACTED:{len(str(val))}chars]"
                else:
                    safe_data[key] = val

            return str(safe_data) if safe_data else "{}"
        except Exception:  # pylint: disable=broad-exception-caught
            return "[binary or unparseable]"

    def _format_response_body(self, response: httpx.Response) -> str:
        """Format response body for logging.

        Args:
            response: The HTTP response.

        Returns:
            Formatted body string, possibly pretty-printed and truncated.
        """
        try:
            response.read()  # Ensure body is available
            body = response.text

            if self._pretty_print and body:
                try:
                    parsed = json.loads(body)
                    body = json.dumps(parsed, indent=2, ensure_ascii=False)
                except (json.JSONDecodeError, TypeError):
                    pass

            if len(body) > self._max_body_length:
                body = f"{body[: self._max_body_length]}\n... [truncated, {len(body)} total chars]"

            return body
        except Exception:  # pylint: disable=broad-exception-caught
            return "[unable to read body]"


# Type alias for httpx event hooks - uses internal types for accurate typing
EventHooksDict = dict[str, list["httpx._types.RequestHook | httpx._types.ResponseHook"]]  # type: ignore[name-defined]  # noqa: SLF001


def create_trace_event_hooks(
    logger: logging.Logger,
    trace_level: int = 5,
) -> tuple[EventHooksDict, bool]:
    """Create httpx event hooks for TRACE logging.

    This helper centralizes the common pattern of setting up HTTP trace logging
    with HTTPTraceLogger for httpx clients.

    Args:
        logger: Logger instance to use for trace output.
        trace_level: Logging level for trace messages (default: 5 for TRACE).

    Returns:
        Tuple of (event_hooks dict, trace_enabled bool).
        The event_hooks dict can be passed directly to httpx.AsyncClient().

    Examples:
        >>> import logging
        >>> import httpx
        >>> from kstlib.utils.http_trace import create_trace_event_hooks
        >>> log = logging.getLogger(__name__)
        >>> hooks, enabled = create_trace_event_hooks(log)
        >>> async with httpx.AsyncClient(event_hooks=hooks) as client:  # doctest: +SKIP
        ...     response = await client.get("https://example.com")  # doctest: +SKIP
    """
    trace_enabled = logger.isEnabledFor(trace_level)
    event_hooks: EventHooksDict = {}

    if trace_enabled:
        tracer = HTTPTraceLogger(logger, trace_level=trace_level)
        event_hooks = {
            "request": [tracer.on_request],
            "response": [tracer.on_response],
        }

    return event_hooks, trace_enabled


__all__ = ["DEFAULT_SENSITIVE_KEYS", "HTTPTraceLogger", "create_trace_event_hooks"]
