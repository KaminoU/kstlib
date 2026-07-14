"""Tests for HTTP trace logging utilities."""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock

import pytest

from kstlib.utils.http_trace import (
    DEFAULT_SENSITIVE_KEYS,
    HTTPTraceLogger,
    create_trace_event_hooks,
)

# OAuth 2.0 / OIDC bearer-credential keys that must be redacted in HTTP traces.
OIDC_OAUTH_CREDENTIAL_KEYS = (
    "id_token",
    "id_token_hint",
    "assertion",
    "client_assertion",
    "subject_token",
    "actor_token",
    "device_code",
    "registration_access_token",
    "initial_access_token",
)


class TestDefaultSensitiveKeys:
    """Tests for DEFAULT_SENSITIVE_KEYS constant."""

    def test_contains_expected_keys(self) -> None:
        """Verify default sensitive keys include common secrets."""
        expected = {"client_secret", "code", "refresh_token", "access_token", "password"}
        assert expected.issubset(DEFAULT_SENSITIVE_KEYS)

    def test_is_frozenset(self) -> None:
        """Verify keys are immutable."""
        assert isinstance(DEFAULT_SENSITIVE_KEYS, frozenset)

    def test_contains_oidc_oauth_credentials(self) -> None:
        """Verify OAuth2/OIDC bearer-credential keys are redacted by default."""
        assert set(OIDC_OAUTH_CREDENTIAL_KEYS).issubset(DEFAULT_SENSITIVE_KEYS)

    def test_excludes_non_credential_type_siblings(self) -> None:
        """Verify non-secret type identifiers stay visible (exact match, not substring)."""
        visible = {
            "token_type",
            "client_assertion_type",
            "subject_token_type",
            "actor_token_type",
            "grant_type",
            "response_type",
            "scope",
            "nonce",
            "state",
            "user_code",
        }
        assert visible.isdisjoint(DEFAULT_SENSITIVE_KEYS)


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
        """Verify Authorization header value is redacted (name kept, not dropped)."""
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
        assert "***REDACTED***" in call_args
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


class TestHTTPTraceLoggerRedactsCredentials:
    """Tests that OAuth2/OIDC bearer credentials are redacted on both trace paths."""

    @staticmethod
    def _traced_response(text: str) -> str:
        """Trace a response body through on_response and return the logged call string."""
        mock_logger = MagicMock()
        mock_logger.isEnabledFor.return_value = True
        tracer = HTTPTraceLogger(mock_logger, trace_level=5)

        mock_response = MagicMock()
        mock_response.request.method = "POST"
        mock_response.request.url = "https://idp.example.com/token"
        mock_response.status_code = 200
        mock_response.text = text

        tracer.on_response(mock_response)
        return str(mock_logger.log.call_args)

    @staticmethod
    def _traced_request(content: bytes) -> str:
        """Trace a request body through on_request and return the logged call string."""
        mock_logger = MagicMock()
        mock_logger.isEnabledFor.return_value = True
        tracer = HTTPTraceLogger(mock_logger, trace_level=5)

        mock_request = MagicMock()
        mock_request.method = "POST"
        mock_request.url = "https://idp.example.com/token"
        mock_request.content = content
        mock_request.headers = {"Content-Type": "application/x-www-form-urlencoded"}

        tracer.on_request(mock_request)
        return str(mock_logger.log.call_args)

    @pytest.mark.parametrize("key", OIDC_OAUTH_CREDENTIAL_KEYS)
    def test_credential_redacted_in_response_json(self, key: str) -> None:
        """Verify each credential key is redacted in a JSON response body."""
        logged = self._traced_response(json.dumps({key: "eyJfakeSensitiveValue", "token_type": "Bearer"}))

        assert "eyJfakeSensitiveValue" not in logged
        assert "***REDACTED***" in logged
        assert "Bearer" in logged

    @pytest.mark.parametrize("key", OIDC_OAUTH_CREDENTIAL_KEYS)
    def test_credential_redacted_in_request_form(self, key: str) -> None:
        """Verify each credential key is redacted in a form-encoded request body."""
        logged = self._traced_request(f"{key}=eyJfakeSensitiveValue&grant_type=authorization_code".encode())

        assert "eyJfakeSensitiveValue" not in logged
        assert "[REDACTED:" in logged
        assert "grant_type" in logged

    def test_non_credential_keys_stay_visible_in_response(self) -> None:
        """Verify non-secret protocol metadata is not redacted (debug value preserved)."""
        logged = self._traced_response(
            json.dumps(
                {
                    "token_type": "Bearer",
                    "token_endpoint": "https://idp.example.com/token",
                    "grant_type": "authorization_code",
                    "nonce": "n-abc123value",
                    "state": "st-xyz789value",
                    "expires_in": 3600,
                }
            )
        )

        for visible in ("Bearer", "token_endpoint", "authorization_code", "n-abc123value", "st-xyz789value"):
            assert visible in logged
        assert "***REDACTED***" not in logged


def _trace_response_body(
    payload: dict[str, object],
    *,
    extra_sensitive_keys: set[str] | None = None,
    sensitive_keys: frozenset[str] | None = None,
) -> str:
    """Trace a JSON response payload and return the logged call string."""
    mock_logger = MagicMock()
    mock_logger.isEnabledFor.return_value = True
    tracer = HTTPTraceLogger(
        mock_logger,
        trace_level=5,
        sensitive_keys=sensitive_keys,
        extra_sensitive_keys=extra_sensitive_keys,
    )
    mock_response = MagicMock()
    mock_response.request.method = "POST"
    mock_response.request.url = "https://idp.example.com/token"
    mock_response.status_code = 200
    mock_response.text = json.dumps(payload)
    tracer.on_response(mock_response)
    return str(mock_logger.log.call_args)


def _trace_request_body(
    content: bytes,
    *,
    extra_sensitive_keys: set[str] | None = None,
) -> str:
    """Trace a form-encoded request body and return the logged call string."""
    mock_logger = MagicMock()
    mock_logger.isEnabledFor.return_value = True
    tracer = HTTPTraceLogger(mock_logger, trace_level=5, extra_sensitive_keys=extra_sensitive_keys)
    mock_request = MagicMock()
    mock_request.method = "POST"
    mock_request.url = "https://idp.example.com/token"
    mock_request.content = content
    mock_request.headers = {"Content-Type": "application/x-www-form-urlencoded"}
    tracer.on_request(mock_request)
    return str(mock_logger.log.call_args)


class TestHTTPTraceLoggerConfigExtensible:
    """Tests for the additive, config-extensible sensitive-key path with wildcards."""

    def test_extra_key_redacted_in_response(self) -> None:
        """Verify an extra config key is redacted in a JSON response."""
        logged = _trace_response_body(
            {"x_custom_secret": "TOPSECRET", "token_type": "Bearer"},
            extra_sensitive_keys={"x_custom_secret"},
        )
        assert "TOPSECRET" not in logged
        assert "***REDACTED***" in logged
        assert "Bearer" in logged

    def test_extra_key_redacted_in_request(self) -> None:
        """Verify an extra config key is redacted in a form request body."""
        logged = _trace_request_body(
            b"x_custom_secret=TOPSECRET&grant_type=authorization_code",
            extra_sensitive_keys={"x_custom_secret"},
        )
        assert "TOPSECRET" not in logged
        assert "[REDACTED:" in logged
        assert "grant_type" in logged

    def test_wildcard_redacts_matching_key_response(self) -> None:
        """Verify a wildcard pattern redacts matching keys in a JSON response."""
        logged = _trace_response_body(
            {"weird_token": "WEIRDVALUE", "grant_type": "authorization_code"},
            extra_sensitive_keys={"*token*"},
        )
        assert "WEIRDVALUE" not in logged
        assert "***REDACTED***" in logged
        assert "authorization_code" in logged

    def test_wildcard_redacts_matching_key_request(self) -> None:
        """Verify a wildcard pattern redacts matching keys in a form request."""
        logged = _trace_request_body(
            b"weird_token=WEIRDVALUE&grant_type=authorization_code",
            extra_sensitive_keys={"*token*"},
        )
        assert "WEIRDVALUE" not in logged
        assert "[REDACTED:" in logged
        assert "grant_type" in logged

    def test_adversarial_1_empty_config_floor_still_holds(self) -> None:
        """Adversarial 1 (the non-negotiable): empty config, floor keys still redacted."""
        logged = _trace_response_body(
            {"access_token": "SECRETAT", "client_secret": "SECRETCS", "id_token": "SECRETIDT"},
            extra_sensitive_keys=set(),
        )
        for secret in ("SECRETAT", "SECRETCS", "SECRETIDT"):
            assert secret not in logged
        assert "***REDACTED***" in logged

    def test_adversarial_2_config_cannot_replace_floor(self) -> None:
        """Adversarial 2: config listing only a custom key never removes floor keys (union)."""
        logged = _trace_response_body(
            {"access_token": "SECRETAT", "custom_x": "SECRETCX"},
            extra_sensitive_keys={"custom_x"},
        )
        assert "SECRETAT" not in logged
        assert "SECRETCX" not in logged
        assert "***REDACTED***" in logged

    def test_adversarial_3_star_wildcard_redacts_everything(self) -> None:
        """Adversarial 3: a bare '*' redacts every key (conscious opt-in behavior)."""
        logged = _trace_response_body(
            {"anything": "VALUEONE", "grant_type": "VALUETWO", "foo": "VALUETHREE"},
            extra_sensitive_keys={"*"},
        )
        for value in ("VALUEONE", "VALUETWO", "VALUETHREE"):
            assert value not in logged

    def test_adversarial_4_wildcard_over_redacts_type_siblings(self) -> None:
        """Adversarial 4: '*token*' also masks token_type/subject_token_type (documented, intentional)."""
        logged = _trace_response_body(
            {
                "token_type": "BEARERVALUE",
                "subject_token_type": "URNVALUE",
                "grant_type": "authorization_code",
            },
            extra_sensitive_keys={"*token*"},
        )
        assert "BEARERVALUE" not in logged
        assert "URNVALUE" not in logged
        assert "authorization_code" in logged

    def test_adversarial_5_pathological_wildcard_is_bounded(self) -> None:
        """Adversarial 5: a pathological all-star pattern completes without blowup (anti-ReDoS)."""
        # fnmatch translates globs to a bounded regex; consecutive stars collapse.
        # The test completing at all is the proof there is no catastrophic backtracking.
        logged = _trace_response_body(
            {"some_key": "X" * 200},
            extra_sensitive_keys={"*" * 50},
        )
        assert "***REDACTED***" in logged
        assert "X" * 200 not in logged

    def test_adversarial_6_nested_json_redacted_recursively(self) -> None:
        """Adversarial 6: floor and config keys are redacted at any nesting depth."""
        payload: dict[str, object] = {
            "outer": {"inner": {"access_token": "SECRETAT", "custom_x": "SECRETCX"}},
            "items": [{"id_token": "SECRETIDT"}],
        }
        logged = _trace_response_body(payload, extra_sensitive_keys={"custom_x"})
        for secret in ("SECRETAT", "SECRETCX", "SECRETIDT"):
            assert secret not in logged
        assert "***REDACTED***" in logged

    def test_adversarial_7_form_and_json_parity(self) -> None:
        """Adversarial 7: request (form) and response (JSON) honor the config identically."""
        resp = _trace_response_body({"custom_x": "SHAREDSECRET"}, extra_sensitive_keys={"custom_x"})
        req = _trace_request_body(b"custom_x=SHAREDSECRET", extra_sensitive_keys={"custom_x"})
        assert "SHAREDSECRET" not in resp
        assert "SHAREDSECRET" not in req

    def test_case_insensitive_floor(self) -> None:
        """Verify floor keys are redacted regardless of key case."""
        logged = _trace_response_body({"Access_Token": "SECRETAT", "ID_TOKEN": "SECRETIDT"})
        assert "SECRETAT" not in logged
        assert "SECRETIDT" not in logged

    def test_case_insensitive_extra_and_wildcard(self) -> None:
        """Verify extra keys and wildcards match regardless of key case."""
        logged = _trace_response_body(
            {"X_Custom_Secret": "SECRETONE", "WEIRD_TOKEN": "SECRETTWO"},
            extra_sensitive_keys={"x_custom_secret", "*token*"},
        )
        assert "SECRETONE" not in logged
        assert "SECRETTWO" not in logged

    def test_identity_preserved_without_extra(self) -> None:
        """Verify no extra keys preserves the DEFAULT_SENSITIVE_KEYS identity (no churn)."""
        logger = logging.getLogger("test")
        assert HTTPTraceLogger(logger)._sensitive_keys is DEFAULT_SENSITIVE_KEYS
        assert HTTPTraceLogger(logger, extra_sensitive_keys=set())._sensitive_keys is DEFAULT_SENSITIVE_KEYS
        custom = frozenset({"only_this"})
        assert HTTPTraceLogger(logger, sensitive_keys=custom)._sensitive_keys is custom

    def test_extra_produces_union_not_identity(self) -> None:
        """Verify extra keys produce a union that still contains the whole floor."""
        logger = logging.getLogger("test")
        tracer = HTTPTraceLogger(logger, extra_sensitive_keys={"x_custom"})
        assert tracer._sensitive_keys is not DEFAULT_SENSITIVE_KEYS
        assert DEFAULT_SENSITIVE_KEYS.issubset(tracer._sensitive_keys)
        assert "x_custom" in tracer._sensitive_keys

    def test_replace_path_unchanged_and_additive_on_top(self) -> None:
        """Verify sensitive_keys (replace) and extra_sensitive_keys (additive) compose."""
        logger = logging.getLogger("test")
        tracer = HTTPTraceLogger(
            logger,
            sensitive_keys=frozenset({"base_only"}),
            extra_sensitive_keys={"extra_only"},
        )
        assert "base_only" in tracer._sensitive_keys
        assert "extra_only" in tracer._sensitive_keys
        assert "access_token" not in tracer._sensitive_keys

    def test_create_hooks_threads_extra_keys(self) -> None:
        """Verify create_trace_event_hooks threads extra_sensitive_keys to the tracer."""
        mock_logger = MagicMock()
        mock_logger.isEnabledFor.return_value = True
        hooks, enabled = create_trace_event_hooks(mock_logger, 5, extra_sensitive_keys={"x_custom"})
        assert enabled is True
        mock_request = MagicMock()
        mock_request.method = "POST"
        mock_request.url = "https://idp.example.com/token"
        mock_request.content = b"x_custom=SECRETVALUE"
        mock_request.headers = {"Content-Type": "application/x-www-form-urlencoded"}
        hooks["request"][0](mock_request)
        assert "SECRETVALUE" not in str(mock_logger.log.call_args)

    def test_wildcard_char_class_pattern(self) -> None:
        """Verify a character-class pattern (with '[') matches like fnmatch."""
        logged = _trace_response_body(
            {"cust5_token": "SECRETVAL", "custX_token": "VISIBLEVAL"},
            extra_sensitive_keys={"cust[0-9]_token"},
        )
        assert "SECRETVAL" not in logged
        assert "VISIBLEVAL" in logged

    def test_replace_path_redacts_cased_key(self) -> None:
        """Verify the sensitive_keys replace path redacts case-insensitively."""
        logged = _trace_response_body(
            {"Base_Only": "SECRETVAL"},
            sensitive_keys=frozenset({"base_only"}),
        )
        assert "SECRETVAL" not in logged
        assert "***REDACTED***" in logged

    def test_form_path_redacts_cased_floor_key(self) -> None:
        """Verify the form request path redacts a cased floor key."""
        logged = _trace_request_body(b"Client_Secret=SECRETVAL&grant_type=authorization_code")
        assert "SECRETVAL" not in logged
        assert "[REDACTED:" in logged
        assert "grant_type" in logged


def _trace_request_meta(
    *,
    url: str = "https://idp.example.com/token",
    headers: dict[str, str] | None = None,
    extra_sensitive_keys: set[str] | None = None,
) -> str:
    """Trace a request (headers and url, no body) and return the logged call string."""
    mock_logger = MagicMock()
    mock_logger.isEnabledFor.return_value = True
    tracer = HTTPTraceLogger(mock_logger, trace_level=5, extra_sensitive_keys=extra_sensitive_keys)
    mock_request = MagicMock()
    mock_request.method = "GET"
    mock_request.url = url
    mock_request.content = None
    mock_request.headers = headers if headers is not None else {}
    tracer.on_request(mock_request)
    return str(mock_logger.log.call_args)


def _trace_response_url(url: str) -> str:
    """Trace a response with the given request URL and return the logged call string."""
    mock_logger = MagicMock()
    mock_logger.isEnabledFor.return_value = True
    tracer = HTTPTraceLogger(mock_logger, trace_level=5)
    mock_response = MagicMock()
    mock_response.request.method = "GET"
    mock_response.request.url = url
    mock_response.status_code = 200
    mock_response.text = "{}"
    tracer.on_response(mock_response)
    return str(mock_logger.log.call_args)


class TestHTTPTraceLoggerHeaderRedaction:
    """Tests for sensitive request-header value redaction (mask value, keep name)."""

    def test_redacts_cookie_header(self) -> None:
        """Verify a Cookie header value is redacted (session cookie leak)."""
        logged = _trace_request_meta(headers={"Cookie": "session=SECRETCOOKIE", "Accept": "text/html"})
        assert "SECRETCOOKIE" not in logged
        assert "***REDACTED***" in logged
        assert "text/html" in logged

    def test_redacts_api_key_header(self) -> None:
        """Verify an X-Api-Key header value is redacted."""
        logged = _trace_request_meta(headers={"X-Api-Key": "sk_live_SECRETKEY"})
        assert "sk_live_SECRETKEY" not in logged
        assert "***REDACTED***" in logged

    def test_non_sensitive_headers_visible(self) -> None:
        """Verify non-sensitive headers stay visible for debugging."""
        logged = _trace_request_meta(
            headers={
                "Content-Type": "application/json",
                "Accept": "text/html",
                "User-Agent": "kstlib-test/1.0",
            }
        )
        for visible in ("application/json", "text/html", "kstlib-test/1.0"):
            assert visible in logged
        assert "***REDACTED***" not in logged

    def test_adversarial_empty_config_header_floor_holds(self) -> None:
        """Adversarial 1: empty config, the header floor still redacts cookie and authorization."""
        logged = _trace_request_meta(
            headers={"Cookie": "SECRETCK", "Authorization": "Bearer SECRETAUTH"},
            extra_sensitive_keys=set(),
        )
        assert "SECRETCK" not in logged
        assert "SECRETAUTH" not in logged

    def test_adversarial_wildcard_config_matches_header(self) -> None:
        """Adversarial 2: a wildcard config key redacts a matching custom header."""
        logged = _trace_request_meta(
            headers={"X-Custom-Key": "SECRETXK"},
            extra_sensitive_keys={"*key*"},
        )
        assert "SECRETXK" not in logged
        assert "***REDACTED***" in logged

    def test_adversarial_case_insensitive_header(self) -> None:
        """Adversarial 4: sensitive headers are redacted regardless of case."""
        logged = _trace_request_meta(headers={"COOKIE": "SECRETC", "Set-Cookie": "SECRETSC"})
        assert "SECRETC" not in logged
        assert "SECRETSC" not in logged


class TestHTTPTraceLoggerUrlRedaction:
    """Tests for URL query-string credential redaction."""

    def test_redacts_url_query_credential_request(self) -> None:
        """Verify a credential in the request URL query is redacted, other params kept."""
        logged = _trace_request_meta(url="https://idp.example.com/token?access_token=SECRETTOK&page=2")
        assert "SECRETTOK" not in logged
        assert "***REDACTED***" in logged
        assert "page=2" in logged

    def test_redacts_url_query_credential_response(self) -> None:
        """Verify a credential in the response request URL query is redacted."""
        logged = _trace_response_url("https://idp.example.com/token?code=SECRETCODE&state=abc")
        assert "SECRETCODE" not in logged
        assert "***REDACTED***" in logged
        assert "state=abc" in logged

    def test_adversarial_url_without_query_intact(self) -> None:
        """Adversarial 5: a URL without a query string is logged unchanged."""
        logged = _trace_request_meta(url="https://idp.example.com/token")
        assert "https://idp.example.com/token" in logged
        assert "***REDACTED***" not in logged

    def test_adversarial_url_query_wildcard_config(self) -> None:
        """Adversarial 6: a wildcard config key redacts a matching URL query param."""
        logged = _trace_request_meta(
            url="https://idp.example.com/x?my_secret_key=SECRETQ&page=1",
            extra_sensitive_keys={"*secret*"},
        )
        assert "SECRETQ" not in logged
        assert "page=1" in logged

    def test_url_query_fidelity_repeated_blank_encoded(self) -> None:
        """Verify non-sensitive params (repeated, blank, encoded) survive redaction intact."""
        logged = _trace_request_meta(
            url="https://idp.example.com/x?tag=a&tag=b&empty=&code=SECRETC&name=John%20Doe",
        )
        assert "SECRETC" not in logged
        assert "tag=a" in logged
        assert "tag=b" in logged
        assert "empty=" in logged
        assert "John" in logged

    def test_redacts_userinfo_credentials_request(self) -> None:
        """Verify inline user:pass@ credentials in the request URL are masked."""
        logged = _trace_request_meta(url="https://admin:s3cr3tPW@api.example.com/data?page=1")
        assert "s3cr3tPW" not in logged
        assert "***REDACTED***" in logged
        assert "api.example.com" in logged
        assert "page=1" in logged

    def test_redacts_userinfo_credentials_response(self) -> None:
        """Verify inline user:pass@ credentials in the response request URL are masked."""
        logged = _trace_response_url("https://admin:s3cr3tPW@api.example.com/data")
        assert "s3cr3tPW" not in logged
        assert "***REDACTED***" in logged
        assert "api.example.com" in logged

    def test_redacts_userinfo_without_query(self) -> None:
        """Verify userinfo is masked even when the URL has no query string."""
        logged = _trace_request_meta(url="https://admin:s3cr3tPW@api.example.com/data")
        assert "s3cr3tPW" not in logged
        assert "***REDACTED***" in logged
        assert "api.example.com" in logged

    def test_userinfo_mask_preserves_ipv6_host_and_port(self) -> None:
        """Verify masking userinfo keeps the IPv6 host and port intact."""
        logged = _trace_request_meta(url="https://admin:s3cr3tPW@[::1]:8443/data")
        assert "s3cr3tPW" not in logged
        assert "***REDACTED***" in logged
        assert "[::1]:8443" in logged

    def test_redact_url_fail_safe_on_unparseable(self) -> None:
        """Verify an unparseable URL falls back to a safe placeholder (never the raw URL)."""
        logged = _trace_request_meta(url="http://[::1")
        assert "[unparseable url]" in logged
