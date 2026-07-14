"""HTTP trace logging utilities with sensitive data redaction."""

from __future__ import annotations

import fnmatch
import json
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

if TYPE_CHECKING:
    import logging
    from collections.abc import Iterable

    import httpx

#: Default set of body keys whose values are redacted in HTTP traces.
#:
#: Each entry names a field whose value is a bearer credential (an OAuth 2.0 /
#: OpenID Connect token, secret, assertion, authorization code, or PKCE
#: verifier). Such values must never appear in logs, even at TRACE level.
#: Keys are matched exactly, so non-secret siblings such as ``token_type`` or
#: ``client_assertion_type`` stay visible for debugging. Pass a custom frozenset
#: to the ``sensitive_keys`` argument of :class:`HTTPTraceLogger` to replace
#: this default set.
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
        # OpenID Connect ID Tokens (OIDC Core / RP-Initiated Logout)
        "id_token",
        "id_token_hint",
        # Assertion framework (RFC 7521 / 7523)
        "assertion",
        "client_assertion",
        # Token exchange (RFC 8693)
        "subject_token",
        "actor_token",
        # Device authorization grant (RFC 8628)
        "device_code",
        # Dynamic client registration (RFC 7591 / 7592)
        "registration_access_token",
        "initial_access_token",
    }
)

#: Default set of HTTP header names whose values are redacted in traces.
#:
#: Header names carry a different vocabulary from body/query keys, so they have
#: their own floor. Matching is case-insensitive. Each entry names a header that
#: carries a bearer credential or session secret. This set is unioned with
#: :data:`DEFAULT_SENSITIVE_KEYS` and any ``extra_sensitive_keys`` when matching
#: header names, so a custom key configured for bodies also masks headers.
HEADER_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "api-key",
        "x-auth-token",
    }
)


def _is_wildcard(key: str) -> bool:
    """Return True if the key is an fnmatch pattern (contains ``*``, ``?`` or ``[``)."""
    return any(char in key for char in "*?[")


class HTTPTraceLogger:
    """Reusable HTTP trace logger with sensitive data redaction.

    This class provides httpx event hooks for logging HTTP requests and responses
    at TRACE level with automatic redaction of sensitive data.

    Args:
        logger: Logger instance to use for trace output.
        trace_level: Logging level for trace messages (default: 5 for TRACE).
        sensitive_keys: Replaces the default redaction set entirely (power-user
            escape hatch).
        extra_sensitive_keys: Added on top of the redaction set, never replacing
            it. Entries containing ``*``, ``?`` or ``[seq]`` are treated as
            case-insensitive fnmatch patterns.
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

    def __init__(  # noqa: PLR0913
        self,
        logger: logging.Logger,
        *,
        trace_level: int = 5,
        sensitive_keys: frozenset[str] | None = None,
        extra_sensitive_keys: Iterable[str] | None = None,
        pretty_print: bool = True,
        max_body_length: int = 2000,
    ) -> None:
        """Initialize the HTTP trace logger."""
        self._logger = logger
        self._trace_level = trace_level
        base = sensitive_keys or DEFAULT_SENSITIVE_KEYS
        # Additive union: extra keys are added on top, the base is never replaced.
        # Preserve the base identity when no extra keys are given (no churn).
        extra = frozenset(extra_sensitive_keys or ())
        self._sensitive_keys = base | extra if extra else base
        # Split once into exact keys and precompiled wildcard patterns, lowercased
        # so matching is case-insensitive (cased variants of secrets stay redacted).
        # Compiling here (not per body key) keeps the trace hot path cheap and
        # independent of fnmatch's process-global compile cache.
        self._exact_keys = frozenset(k.lower() for k in self._sensitive_keys if not _is_wildcard(k))
        self._wildcard_res = tuple(
            re.compile(fnmatch.translate(k.lower())) for k in self._sensitive_keys if _is_wildcard(k)
        )
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
        """Httpx event hook for outgoing requests (TRACE logging).

        Redacts sensitive data in the request body, headers, and URL query.

        Args:
            request: The outgoing HTTP request.

        """
        if not self._logger.isEnabledFor(self._trace_level):
            return

        body_str = self._redact_request_body(request.content)
        safe_headers = {
            k: ("***REDACTED***" if self._is_sensitive_header(k) else v) for k, v in request.headers.items()
        }

        self._logger.log(
            self._trace_level,
            "[HTTP] %s %s | headers=%s | body=%s",
            request.method,
            self._redact_url(request.url),
            dict(safe_headers) or "{}",
            body_str,
        )

    def on_response(self, response: httpx.Response) -> None:
        """Httpx event hook for incoming responses (TRACE logging).

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
            self._redact_url(response.request.url),
            response.status_code,
            body,
        )

    def _is_sensitive(self, key: str) -> bool:
        """Return True if a body key must be redacted.

        Matching is case-insensitive against the exact key set first, then
        against any precompiled fnmatch wildcard patterns.

        Args:
            key: The body field name to test.

        Returns:
            True if the key's value must be redacted, False otherwise.

        """
        key_lower = key.lower()
        if key_lower in self._exact_keys:
            return True
        return any(pattern.match(key_lower) is not None for pattern in self._wildcard_res)

    def _is_sensitive_header(self, name: str) -> bool:
        """Return True if an HTTP header value must be redacted.

        Checks the dedicated header floor first, then the body-key matcher
        (body floor plus configured extra keys and wildcards), all
        case-insensitively.

        Args:
            name: The HTTP header name to test.

        Returns:
            True if the header value must be redacted, False otherwise.

        """
        return name.lower() in HEADER_SENSITIVE_KEYS or self._is_sensitive(name)

    def _redact_url(self, url: httpx.URL) -> str:
        """Redact sensitive credentials in a URL for safe logging.

        Inline userinfo credentials in the authority (``user:pass@host``) are
        always masked. Query-parameter values are redacted when the parameter
        name matches the body-key matcher (floor plus configured extra keys and
        wildcards). The path and fragment are not inspected: name-based
        redaction cannot match a bare path or fragment segment.

        Args:
            url: The request URL to redact.

        Returns:
            The URL string with sensitive credentials replaced, or a safe
            placeholder if the URL cannot be parsed.

        """
        try:
            parts = urlsplit(str(url))
            netloc = parts.netloc
            if "@" in netloc:
                netloc = f"***REDACTED***@{netloc.rsplit('@', 1)[1]}"
            if not parts.query:
                return urlunsplit(parts._replace(netloc=netloc))
            redacted = [
                (key, "***REDACTED***" if self._is_sensitive(key) else value)
                for key, value in parse_qsl(parts.query, keep_blank_values=True)
            ]
            new_query = urlencode(redacted, doseq=True, safe="*")
            return urlunsplit(parts._replace(netloc=netloc, query=new_query))
        except Exception:  # pylint: disable=broad-exception-caught
            return "[unparseable url]"

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
                if self._is_sensitive(key):
                    safe_data[key] = f"[REDACTED:{len(str(val))}chars]"
                else:
                    safe_data[key] = val

            return str(safe_data) if safe_data else "{}"
        except Exception:  # pylint: disable=broad-exception-caught
            return "[binary or unparseable]"

    def _redact_json(self, data: Any) -> Any:
        """Recursively redact sensitive keys in a parsed JSON structure.

        Args:
            data: Parsed JSON value (dict, list, or scalar).

        Returns:
            Same structure with sensitive values replaced by ``"***REDACTED***"``.

        """
        if isinstance(data, dict):
            return {
                key: ("***REDACTED***" if self._is_sensitive(key) else self._redact_json(value))
                for key, value in data.items()
            }
        if isinstance(data, list):
            return [self._redact_json(item) for item in data]
        return data

    def _format_response_body(self, response: httpx.Response) -> str:
        """Format response body for logging.

        Args:
            response: The HTTP response.

        Returns:
            Formatted body string, with sensitive keys redacted, possibly
            pretty-printed and truncated.

        """
        try:
            response.read()  # Ensure body is available
            body = response.text

            if body:
                try:
                    parsed = json.loads(body)
                except (json.JSONDecodeError, TypeError):
                    parsed = None

                if parsed is not None:
                    redacted = self._redact_json(parsed)
                    indent = 2 if self._pretty_print else None
                    body = json.dumps(redacted, indent=indent, ensure_ascii=False)

            if len(body) > self._max_body_length:
                body = f"{body[: self._max_body_length]}\n... [truncated, {len(body)} total chars]"

            return body
        except Exception:  # pylint: disable=broad-exception-caught
            return "[unable to read body]"


# Type alias for httpx event hooks - uses internal types for accurate typing
EventHooksDict = dict[str, list["httpx._types.RequestHook | httpx._types.ResponseHook"]]  # type: ignore[name-defined]


def create_trace_event_hooks(
    logger: logging.Logger,
    trace_level: int = 5,
    *,
    extra_sensitive_keys: Iterable[str] | None = None,
) -> tuple[EventHooksDict, bool]:
    """Create httpx event hooks for TRACE logging.

    This helper centralizes the common pattern of setting up HTTP trace logging
    with HTTPTraceLogger for httpx clients.

    Args:
        logger: Logger instance to use for trace output.
        trace_level: Logging level for trace messages (default: 5 for TRACE).
        extra_sensitive_keys: Additional keys or fnmatch patterns to redact,
            unioned with the default floor (never replaces it).

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
        tracer = HTTPTraceLogger(
            logger,
            trace_level=trace_level,
            extra_sensitive_keys=extra_sensitive_keys,
        )
        event_hooks = {
            "request": [tracer.on_request],
            "response": [tracer.on_response],
        }

    return event_hooks, trace_enabled


__all__ = [
    "DEFAULT_SENSITIVE_KEYS",
    "HEADER_SENSITIVE_KEYS",
    "HTTPTraceLogger",
    "create_trace_event_hooks",
]
