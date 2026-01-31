"""Tests for HTTP trace logging utilities."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from kstlib.utils.http_trace import DEFAULT_SENSITIVE_KEYS, HTTPTraceLogger

if TYPE_CHECKING:
    pass


class TestDefaultSensitiveKeys:
    """Tests for DEFAULT_SENSITIVE_KEYS constant."""

    def test_contains_expected_keys(self) -> None:
        """Verify default sensitive keys include common secrets."""
        expected = {"client_secret", "code", "refresh_token", "access_token", "password"}
        assert expected.issubset(DEFAULT_SENSITIVE_KEYS)

    def test_is_frozenset(self) -> None:
        """Verify keys are immutable."""
        assert isinstance(DEFAULT_SENSITIVE_KEYS, frozenset)


class TestHTTPTraceLoggerInit:
    """Tests for HTTPTraceLogger initialization."""

    def test_init_with_defaults(self) -> None:
        """Verify default initialization values."""
        logger = logging.getLogger("test")
        tracer = HTTPTraceLogger(logger)

        assert tracer._logger is logger
        assert tracer._trace_level == 5
        assert tracer._sensitive_keys is DEFAULT_SENSITIVE_KEYS
        assert tracer._pretty_print is True
        assert tracer._max_body_length == 2000

    def test_init_with_custom_values(self) -> None:
        """Verify custom initialization values."""
        logger = logging.getLogger("test")
        custom_keys = frozenset({"secret", "token"})
        tracer = HTTPTraceLogger(
            logger,
            trace_level=10,
            sensitive_keys=custom_keys,
            pretty_print=False,
            max_body_length=500,
        )

        assert tracer._trace_level == 10
        assert tracer._sensitive_keys is custom_keys
        assert tracer._pretty_print is False
        assert tracer._max_body_length == 500

    def test_sensitive_keys_property(self) -> None:
        """Verify sensitive_keys property returns correct value."""
        logger = logging.getLogger("test")
        tracer = HTTPTraceLogger(logger)
        assert tracer.sensitive_keys is DEFAULT_SENSITIVE_KEYS


class TestHTTPTraceLoggerConfigure:
    """Tests for HTTPTraceLogger.configure method."""

    def test_configure_pretty_print(self) -> None:
        """Verify configure updates pretty_print."""
        logger = logging.getLogger("test")
        tracer = HTTPTraceLogger(logger)

        tracer.configure(pretty_print=False)
        assert tracer._pretty_print is False

        tracer.configure(pretty_print=True)
        assert tracer._pretty_print is True

    def test_configure_max_body_length(self) -> None:
        """Verify configure updates max_body_length."""
        logger = logging.getLogger("test")
        tracer = HTTPTraceLogger(logger)

        tracer.configure(max_body_length=1000)
        assert tracer._max_body_length == 1000

    def test_configure_none_values_unchanged(self) -> None:
        """Verify None values don't change settings."""
        logger = logging.getLogger("test")
        tracer = HTTPTraceLogger(logger, pretty_print=True, max_body_length=2000)

        tracer.configure(pretty_print=None, max_body_length=None)
        assert tracer._pretty_print is True
        assert tracer._max_body_length == 2000


class TestHTTPTraceLoggerRedactRequestBody:
    """Tests for _redact_request_body method."""

    def test_empty_content(self) -> None:
        """Verify empty content returns empty dict string."""
        logger = logging.getLogger("test")
        tracer = HTTPTraceLogger(logger)

        assert tracer._redact_request_body(None) == "{}"
        assert tracer._redact_request_body(b"") == "{}"

    def test_redacts_sensitive_keys(self) -> None:
        """Verify sensitive keys are redacted."""
        logger = logging.getLogger("test")
        tracer = HTTPTraceLogger(logger)

        body = b"client_secret=mysecret&grant_type=authorization_code"
        result = tracer._redact_request_body(body)

        assert "mysecret" not in result
        assert "[REDACTED:" in result
        assert "grant_type" in result

    def test_preserves_non_sensitive_keys(self) -> None:
        """Verify non-sensitive keys are preserved."""
        logger = logging.getLogger("test")
        tracer = HTTPTraceLogger(logger)

        body = b"grant_type=authorization_code&scope=openid"
        result = tracer._redact_request_body(body)

        assert "authorization_code" in result
        assert "openid" in result

    def test_handles_binary_content(self) -> None:
        """Verify unparseable content returns fallback string."""
        logger = logging.getLogger("test")
        tracer = HTTPTraceLogger(logger)

        # UTF-8 decode will fail on invalid sequences
        body = b"\xff\xfe invalid utf8"
        result = tracer._redact_request_body(body)

        assert result == "[binary or unparseable]"


class TestHTTPTraceLoggerFormatResponseBody:
    """Tests for _format_response_body method."""

    def test_pretty_prints_json(self) -> None:
        """Verify JSON responses are pretty-printed when enabled."""
        logger = logging.getLogger("test")
        tracer = HTTPTraceLogger(logger, pretty_print=True)

        mock_response = MagicMock()
        mock_response.text = '{"key":"value"}'

        result = tracer._format_response_body(mock_response)

        assert "{\n" in result
        assert '"key"' in result

    def test_no_pretty_print_when_disabled(self) -> None:
        """Verify JSON is not pretty-printed when disabled."""
        logger = logging.getLogger("test")
        tracer = HTTPTraceLogger(logger, pretty_print=False)

        mock_response = MagicMock()
        mock_response.text = '{"key":"value"}'

        result = tracer._format_response_body(mock_response)

        assert "{\n" not in result

    def test_truncates_long_body(self) -> None:
        """Verify long bodies are truncated."""
        logger = logging.getLogger("test")
        tracer = HTTPTraceLogger(logger, max_body_length=50)

        mock_response = MagicMock()
        mock_response.text = "x" * 100

        result = tracer._format_response_body(mock_response)

        assert "[truncated" in result
        assert "100 total chars" in result
        assert len(result.split("\n")[0]) <= 50

    def test_handles_read_error(self) -> None:
        """Verify read errors return fallback string."""
        logger = logging.getLogger("test")
        tracer = HTTPTraceLogger(logger)

        mock_response = MagicMock()
        mock_response.read.side_effect = Exception("Read error")

        result = tracer._format_response_body(mock_response)

        assert result == "[unable to read body]"


class TestHTTPTraceLoggerOnRequest:
    """Tests for on_request method."""

    def test_logs_when_trace_enabled(self) -> None:
        """Verify request is logged when trace level enabled."""
        mock_logger = MagicMock()
        mock_logger.isEnabledFor.return_value = True
        tracer = HTTPTraceLogger(mock_logger, trace_level=5)

        mock_request = MagicMock()
        mock_request.method = "POST"
        mock_request.url = "https://example.com/token"
        mock_request.content = b"grant_type=authorization_code"
        mock_request.headers = {"Content-Type": "application/x-www-form-urlencoded"}

        tracer.on_request(mock_request)

        mock_logger.log.assert_called_once()
        args = mock_logger.log.call_args[0]
        assert args[0] == 5  # trace level
        assert "POST" in args[2]
        assert "example.com" in str(args[3])

    def test_skips_when_trace_disabled(self) -> None:
        """Verify request is not logged when trace level disabled."""
        mock_logger = MagicMock()
        mock_logger.isEnabledFor.return_value = False
        tracer = HTTPTraceLogger(mock_logger)

        mock_request = MagicMock()

        tracer.on_request(mock_request)

        mock_logger.log.assert_not_called()

    def test_redacts_authorization_header(self) -> None:
        """Verify Authorization header is not logged."""
        mock_logger = MagicMock()
        mock_logger.isEnabledFor.return_value = True
        tracer = HTTPTraceLogger(mock_logger)

        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.url = "https://example.com/api"
        mock_request.content = None
        mock_request.headers = {
            "Authorization": "Bearer secret_token",
            "Accept": "application/json",
        }

        tracer.on_request(mock_request)

        call_args = str(mock_logger.log.call_args)
        assert "secret_token" not in call_args
        assert "Accept" in call_args


class TestHTTPTraceLoggerOnResponse:
    """Tests for on_response method."""

    def test_logs_when_trace_enabled(self) -> None:
        """Verify response is logged when trace level enabled."""
        mock_logger = MagicMock()
        mock_logger.isEnabledFor.return_value = True
        tracer = HTTPTraceLogger(mock_logger, trace_level=5)

        mock_response = MagicMock()
        mock_response.request.method = "POST"
        mock_response.request.url = "https://example.com/token"
        mock_response.status_code = 200
        mock_response.text = '{"access_token":"..."}'

        tracer.on_response(mock_response)

        mock_logger.log.assert_called_once()
        args = mock_logger.log.call_args[0]
        assert args[0] == 5  # trace level
        assert "status=%d" in args[1]  # format string
        assert args[4] == 200  # actual status code arg

    def test_skips_when_trace_disabled(self) -> None:
        """Verify response is not logged when trace level disabled."""
        mock_logger = MagicMock()
        mock_logger.isEnabledFor.return_value = False
        tracer = HTTPTraceLogger(mock_logger)

        mock_response = MagicMock()

        tracer.on_response(mock_response)

        mock_logger.log.assert_not_called()


class TestHTTPTraceLoggerIntegration:
    """Integration tests for HTTPTraceLogger with httpx."""

    @pytest.mark.asyncio
    async def test_can_be_used_as_httpx_hooks(self) -> None:
        """Verify tracer methods can be used as httpx event hooks."""
        mock_logger = MagicMock()
        mock_logger.isEnabledFor.return_value = False
        tracer = HTTPTraceLogger(mock_logger)

        # Verify the methods have the correct signature for httpx
        assert callable(tracer.on_request)
        assert callable(tracer.on_response)

        # Verify they can be called without error when trace disabled
        mock_request = MagicMock()
        mock_response = MagicMock()

        tracer.on_request(mock_request)
        tracer.on_response(mock_response)
