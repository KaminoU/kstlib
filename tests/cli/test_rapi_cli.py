"""Integration tests for the `kstlib rapi` CLI commands."""

from __future__ import annotations

import importlib
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from kstlib.cli.app import app
from kstlib.rapi import (
    CredentialError,
    EndpointAmbiguousError,
    EndpointNotFoundError,
    RapiConfigManager,
    RapiResponse,
    RequestError,
    ResponseTooLargeError,
    ServerNotFoundError,
)

# Import modules (not functions) to allow patching
call_module = importlib.import_module("kstlib.cli.commands.rapi.call")
list_module = importlib.import_module("kstlib.cli.commands.rapi.list")
show_module = importlib.import_module("kstlib.cli.commands.rapi.show")
# Package-level helper used by call/list/show to load config (with friendly
# exit on failure). Tests patch this entry point rather than the underlying
# load_rapi_config because list.py and call.py do a lazy
# `from kstlib.cli.commands.rapi import _load_config_or_exit` inside the
# command body and do not import load_rapi_config in their own namespace.
rapi_pkg = importlib.import_module("kstlib.cli.commands.rapi")

# Mark all tests in this module as CLI tests (excluded from main tox runs)
# Run with: tox -e cli OR pytest -m cli
pytestmark = pytest.mark.cli

runner = CliRunner()


def _mock_config_manager() -> RapiConfigManager:
    """Create a mock config manager with test endpoints."""
    config = {
        "api": {
            "httpbin": {
                "base_url": "https://httpbin.org",
                "endpoints": {
                    "get_ip": {"path": "/ip"},
                    "post_data": {"path": "/post", "method": "POST"},
                    "delay": {"path": "/delay/{seconds}"},
                    "status": {"path": "/status/{code}"},
                },
            },
            "github": {
                "base_url": "https://api.github.com",
                "credentials": "github_token",
                "auth_type": "bearer",
                "endpoints": {
                    "user": {"path": "/user"},
                },
            },
        }
    }
    return RapiConfigManager(config)


def _mock_config_manager_with_descriptions() -> RapiConfigManager:
    """Create a mock config manager with long descriptions for testing."""
    config = {
        "api": {
            "testapi": {
                "base_url": "https://api.test.com",
                "endpoints": {
                    "short_desc": {
                        "path": "/short",
                        "description": "Short description.",
                    },
                    "long_desc": {
                        "path": "/long",
                        "description": "This is a very long description that exceeds forty three characters and should be truncated.",
                    },
                },
            },
        }
    }
    return RapiConfigManager(config)


def _mock_config_manager_with_query() -> RapiConfigManager:
    """Create a mock config manager with endpoints that have query params."""
    config = {
        "api": {
            "binance": {
                "base_url": "https://api.binance.com",
                "credentials": "binance_api_cred",
                "auth_type": "hmac",
                "headers": {"X-MBX-APIKEY": "{{api_key}}"},
                "endpoints": {
                    "ticker": {
                        "path": "/api/v3/ticker/price",
                        "query": {"symbol": "BTCUSDT", "type": "MINI"},
                    },
                    "klines": {
                        "path": "/api/v3/klines",
                        "query": {"symbol": "BTCUSDT", "interval": "1h", "limit": "100"},
                    },
                    "order": {
                        "path": "/api/v3/order",
                        "method": "POST",
                        "body": {"symbol": "BTCUSDT", "side": "BUY"},
                    },
                },
            },
            "httpbin": {
                "base_url": "https://httpbin.org",
                "endpoints": {
                    "get_ip": {"path": "/ip"},
                    "delay": {"path": "/delay/{seconds}"},
                },
            },
        }
    }
    return RapiConfigManager(config)


def _mock_response(
    data: dict[str, Any] | None = None,
    status_code: int = 200,
    text: str = "",
    endpoint_ref: str = "test.endpoint",
) -> RapiResponse:
    """Create a mock RapiResponse."""
    response = MagicMock(spec=RapiResponse)
    response.data = data
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.text = text or json.dumps(data) if data else ""
    response.elapsed = 0.123
    response.endpoint_ref = endpoint_ref
    response.headers = {"content-type": "application/json"}
    return response


class TestRapiList:
    """Tests for `kstlib rapi list` command."""

    def test_list_all_endpoints(self) -> None:
        """List all configured endpoints."""
        with patch.object(rapi_pkg, "_load_config_or_exit") as mock_load:
            mock_load.return_value = _mock_config_manager()

            result = runner.invoke(app, ["rapi", "list"])

            assert result.exit_code == 0
            assert "httpbin.get_ip" in result.stdout
            assert "httpbin.post_data" in result.stdout
            assert "github.user" in result.stdout
            assert "5 endpoints" in result.stdout

    def test_list_filter_by_api(self) -> None:
        """List endpoints filtered by API name."""
        with patch.object(rapi_pkg, "_load_config_or_exit") as mock_load:
            mock_load.return_value = _mock_config_manager()

            result = runner.invoke(app, ["rapi", "list", "httpbin"])

            assert result.exit_code == 0
            assert "httpbin.get_ip" in result.stdout
            assert "github.user" not in result.stdout

    def test_list_unknown_api(self) -> None:
        """Filter by unknown API fails."""
        with patch.object(rapi_pkg, "_load_config_or_exit") as mock_load:
            mock_load.return_value = _mock_config_manager()

            result = runner.invoke(app, ["rapi", "list", "unknown"])

            assert result.exit_code == 1
            assert "not found" in result.stdout

    def test_list_verbose(self) -> None:
        """Verbose output shows method, query, body, and description columns."""
        with patch.object(rapi_pkg, "_load_config_or_exit") as mock_load:
            mock_load.return_value = _mock_config_manager()

            result = runner.invoke(app, ["rapi", "list", "--verbose"])

            assert result.exit_code == 0
            assert "Method" in result.stdout
            assert "GET" in result.stdout
            assert "POST" in result.stdout
            assert "Query" in result.stdout
            assert "Body" in result.stdout
            assert "Description" in result.stdout

    def test_list_empty_config(self) -> None:
        """Empty config shows message."""
        with patch.object(rapi_pkg, "_load_config_or_exit") as mock_load:
            mock_load.return_value = RapiConfigManager({})

            result = runner.invoke(app, ["rapi", "list"])

            assert result.exit_code == 0
            assert "No APIs configured" in result.stdout

    def test_list_filter_single_term(self) -> None:
        """Filter by single keyword matches endpoints."""
        with patch.object(rapi_pkg, "_load_config_or_exit") as mock_load:
            mock_load.return_value = _mock_config_manager()

            result = runner.invoke(app, ["rapi", "list", "--filter", "github"])

            assert result.exit_code == 0
            assert "github.user" in result.stdout
            assert "httpbin" not in result.stdout
            assert "1 matching" in result.stdout

    def test_list_filter_multiple_terms(self) -> None:
        """Filter with multiple terms uses AND logic."""
        with patch.object(rapi_pkg, "_load_config_or_exit") as mock_load:
            mock_load.return_value = _mock_config_manager()

            result = runner.invoke(app, ["rapi", "list", "--filter", "httpbin GET"])

            assert result.exit_code == 0
            assert "httpbin.get_ip" in result.stdout
            assert "httpbin.delay" in result.stdout
            assert "httpbin.post_data" not in result.stdout  # POST, not GET

    def test_list_filter_no_match(self) -> None:
        """Filter with no matches shows message."""
        with patch.object(rapi_pkg, "_load_config_or_exit") as mock_load:
            mock_load.return_value = _mock_config_manager()

            result = runner.invoke(app, ["rapi", "list", "--filter", "nonexistent"])

            assert result.exit_code == 0
            assert "No endpoints matching" in result.stdout

    def test_list_filter_combined_with_api(self) -> None:
        """Filter can be combined with API argument."""
        with patch.object(rapi_pkg, "_load_config_or_exit") as mock_load:
            mock_load.return_value = _mock_config_manager()

            result = runner.invoke(app, ["rapi", "list", "httpbin", "--filter", "ip"])

            assert result.exit_code == 0
            assert "httpbin.get_ip" in result.stdout
            assert "github" not in result.stdout

    def test_list_verbose_full_description(self) -> None:
        """Verbose mode shows full description without truncation."""
        with patch.object(rapi_pkg, "_load_config_or_exit") as mock_load:
            mock_load.return_value = _mock_config_manager_with_descriptions()

            result = runner.invoke(app, ["rapi", "list", "--verbose"])

            assert result.exit_code == 0
            # Full description should be displayed (Rich may word-wrap)
            # Check that "be truncated." appears (end of full description)
            assert "be truncated." in result.stdout
            # No "..." truncation marker in long_desc row
            # (Note: short_desc row won't have "..." either since it's short)

    def test_list_verbose_short_desc_truncates(self) -> None:
        """Verbose mode with --short-desc truncates long descriptions."""
        with patch.object(rapi_pkg, "_load_config_or_exit") as mock_load:
            mock_load.return_value = _mock_config_manager_with_descriptions()

            result = runner.invoke(app, ["rapi", "list", "--verbose", "--short-desc"])

            assert result.exit_code == 0
            # Long description should be truncated with "..."
            assert "..." in result.stdout
            # Full text should NOT appear
            assert "should be truncated" not in result.stdout

    def test_list_short_desc_without_verbose_ignored(self) -> None:
        """--short-desc without verbose is ignored (no description column)."""
        with patch.object(rapi_pkg, "_load_config_or_exit") as mock_load:
            mock_load.return_value = _mock_config_manager_with_descriptions()

            result = runner.invoke(app, ["rapi", "list", "--short-desc"])

            assert result.exit_code == 0
            # No description column in non-verbose mode
            assert "Description" not in result.stdout


class TestRapiCall:
    """Tests for `kstlib rapi call` command."""

    def test_call_simple_get(self) -> None:
        """Simple GET request."""
        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            mock_client.call.return_value = _mock_response(
                data={"origin": "1.2.3.4"},
                endpoint_ref="httpbin.get_ip",
            )
            mock_client_cls.return_value = mock_client

            result = runner.invoke(app, ["rapi", "call", "httpbin.get_ip"])

            assert result.exit_code == 0
            assert "1.2.3.4" in result.stdout
            mock_client.call.assert_called_once()

    def test_call_with_path_param(self) -> None:
        """Call with positional path parameter."""
        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            mock_client.call.return_value = _mock_response(
                data={"url": "https://httpbin.org/delay/3"},
                endpoint_ref="httpbin.delay",
            )
            mock_client_cls.return_value = mock_client

            result = runner.invoke(app, ["rapi", "call", "httpbin.delay", "3"])

            assert result.exit_code == 0
            mock_client.call.assert_called_once()
            # Check that "3" was passed as positional arg
            call_args = mock_client.call.call_args
            assert "3" in call_args.args

    def test_call_with_query_params(self) -> None:
        """Call with keyword query parameters."""
        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            mock_client.call.return_value = _mock_response(
                data={"args": {"foo": "bar"}},
                endpoint_ref="httpbin.get_ip",
            )
            mock_client_cls.return_value = mock_client

            result = runner.invoke(app, ["rapi", "call", "httpbin.get_ip", "foo=bar"])

            assert result.exit_code == 0
            call_kwargs = mock_client.call.call_args.kwargs
            assert call_kwargs.get("foo") == "bar"

    def test_call_with_body(self) -> None:
        """POST call with JSON body."""
        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            mock_client.call.return_value = _mock_response(
                data={"json": {"user": "alice"}},
                endpoint_ref="httpbin.post_data",
            )
            mock_client_cls.return_value = mock_client

            result = runner.invoke(app, ["rapi", "call", "httpbin.post_data", "--body", '{"user": "alice"}'])

            assert result.exit_code == 0
            call_kwargs = mock_client.call.call_args.kwargs
            assert call_kwargs.get("body") == {"user": "alice"}

    def test_call_with_headers(self) -> None:
        """Call with custom headers."""
        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            mock_client.call.return_value = _mock_response(
                data={"headers": {"X-Custom": "value"}},
                endpoint_ref="httpbin.get_ip",
            )
            mock_client_cls.return_value = mock_client

            result = runner.invoke(app, ["rapi", "call", "httpbin.get_ip", "-H", "X-Custom: value"])

            assert result.exit_code == 0
            call_kwargs = mock_client.call.call_args.kwargs
            assert call_kwargs.get("headers") == {"X-Custom": "value"}

    def test_call_invalid_body_json(self) -> None:
        """Invalid JSON body fails."""
        with patch.object(rapi_pkg, "_load_config_or_exit") as mock_load:
            mock_load.return_value = _mock_config_manager()

            result = runner.invoke(app, ["rapi", "call", "httpbin.post_data", "--body", "not-json"])

            assert result.exit_code == 1
            assert "Invalid JSON" in result.stdout

    def test_call_invalid_header_format(self) -> None:
        """Invalid header format fails."""
        with patch.object(rapi_pkg, "_load_config_or_exit") as mock_load:
            mock_load.return_value = _mock_config_manager()

            result = runner.invoke(app, ["rapi", "call", "httpbin.get_ip", "-H", "bad-format"])

            assert result.exit_code == 1
            assert "Invalid header" in result.stdout

    def test_call_endpoint_not_found(self) -> None:
        """Unknown endpoint fails with error."""
        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            mock_client.call.side_effect = EndpointNotFoundError("unknown.endpoint", ["httpbin", "github"])
            mock_client_cls.return_value = mock_client

            result = runner.invoke(app, ["rapi", "call", "unknown.endpoint"])

            assert result.exit_code == 1
            assert "not found" in result.stdout

    def test_call_endpoint_ambiguous(self) -> None:
        """Ambiguous endpoint fails with error."""
        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_manager = MagicMock()
            mock_manager.resolve.side_effect = EndpointAmbiguousError("users", ["api1", "api2"])
            mock_load.return_value = mock_manager
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client

            result = runner.invoke(app, ["rapi", "call", "users"])

            assert result.exit_code == 1
            assert "Ambiguous" in result.stdout

    def test_call_request_error(self) -> None:
        """Request error shows status and retryable flag."""
        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            mock_client.call.side_effect = RequestError("Server error", status_code=500, retryable=True)
            mock_client_cls.return_value = mock_client

            result = runner.invoke(app, ["rapi", "call", "httpbin.get_ip"])

            assert result.exit_code == 1
            assert "Request failed" in result.stdout

    def test_call_output_text(self) -> None:
        """Output as raw text."""
        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            response = _mock_response(data={"origin": "1.2.3.4"})
            response.text = '{"origin": "1.2.3.4"}'
            mock_client.call.return_value = response
            mock_client_cls.return_value = mock_client

            result = runner.invoke(app, ["rapi", "call", "httpbin.get_ip", "--format", "text"])

            assert result.exit_code == 0
            assert '{"origin": "1.2.3.4"}' in result.stdout

    def test_call_output_full(self) -> None:
        """Output full response with metadata."""
        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            mock_client.call.return_value = _mock_response(
                data={"origin": "1.2.3.4"},
                endpoint_ref="httpbin.get_ip",
            )
            mock_client_cls.return_value = mock_client

            result = runner.invoke(app, ["rapi", "call", "httpbin.get_ip", "--format", "full"])

            assert result.exit_code == 0
            assert "status_code" in result.stdout
            assert "elapsed" in result.stdout
            assert "endpoint" in result.stdout

    def test_call_non_ok_response_exits_1(self) -> None:
        """Non-OK response exits with code 1."""
        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            mock_client.call.return_value = _mock_response(
                data={"error": "Not Found"},
                status_code=404,
            )
            mock_client_cls.return_value = mock_client

            result = runner.invoke(app, ["rapi", "call", "httpbin.get_ip"])

            assert result.exit_code == 1

    def test_call_output_to_file(self, tmp_path: Any) -> None:
        """Output written to file with -o option."""
        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            mock_client.call.return_value = _mock_response(
                data={"origin": "1.2.3.4"},
                endpoint_ref="httpbin.get_ip",
            )
            mock_client_cls.return_value = mock_client

            out_file = tmp_path / "output.json"
            result = runner.invoke(app, ["rapi", "call", "httpbin.get_ip", "-o", str(out_file)])

            assert result.exit_code == 0
            assert out_file.exists()
            content = json.loads(out_file.read_text())
            assert content["origin"] == "1.2.3.4"
            assert "Output written to" in result.stdout

    def test_call_output_to_file_quiet(self, tmp_path: Any) -> None:
        """Output to file with quiet mode suppresses confirmation."""
        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            mock_client.call.return_value = _mock_response(
                data={"origin": "1.2.3.4"},
                endpoint_ref="httpbin.get_ip",
            )
            mock_client_cls.return_value = mock_client

            out_file = tmp_path / "output.json"
            result = runner.invoke(app, ["rapi", "call", "httpbin.get_ip", "-o", str(out_file), "-q"])

            assert result.exit_code == 0
            assert out_file.exists()
            assert "Output written to" not in result.stdout

    def test_call_output_to_file_full_format(self, tmp_path: Any) -> None:
        """Output full format to file."""
        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            mock_client.call.return_value = _mock_response(
                data={"origin": "1.2.3.4"},
                endpoint_ref="httpbin.get_ip",
            )
            mock_client_cls.return_value = mock_client

            out_file = tmp_path / "result.json"
            result = runner.invoke(app, ["rapi", "call", "httpbin.get_ip", "-f", "full", "-o", str(out_file)])

            assert result.exit_code == 0
            content = json.loads(out_file.read_text())
            assert "status_code" in content
            assert "elapsed" in content
            assert "endpoint" in content
            assert content["data"]["origin"] == "1.2.3.4"

    def test_call_with_body_from_file(self, tmp_path: Any) -> None:
        """POST call with JSON body loaded from file."""
        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            mock_client.call.return_value = _mock_response(
                data={"json": {"user": "bob"}},
                endpoint_ref="httpbin.post_data",
            )
            mock_client_cls.return_value = mock_client

            body_file = tmp_path / "data.json"
            body_file.write_text('{"user": "bob"}')

            result = runner.invoke(app, ["rapi", "call", "httpbin.post_data", "--body", f"@{body_file}"])

            assert result.exit_code == 0
            call_kwargs = mock_client.call.call_args.kwargs
            assert call_kwargs.get("body") == {"user": "bob"}

    def test_call_body_file_not_found(self) -> None:
        """Body file not found fails with error."""
        with patch.object(rapi_pkg, "_load_config_or_exit") as mock_load:
            mock_load.return_value = _mock_config_manager()

            result = runner.invoke(app, ["rapi", "call", "httpbin.post_data", "--body", "@nonexistent.json"])

            assert result.exit_code == 1
            assert "not found" in result.stdout

    def test_call_invalid_format(self) -> None:
        """Invalid format option fails."""
        with patch.object(rapi_pkg, "_load_config_or_exit") as mock_load:
            mock_load.return_value = _mock_config_manager()

            result = runner.invoke(app, ["rapi", "call", "httpbin.get_ip", "--format", "invalid"])

            assert result.exit_code == 1
            assert "Invalid output format" in result.stdout

    def test_call_minify_without_raw_errors(self) -> None:
        """--minify without --raw rejected with hint pointing to --raw --minify."""
        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client

            result = runner.invoke(app, ["rapi", "call", "httpbin.get_ip", "--minify"])

            # typer.BadParameter -> click UsageError -> exit code 2.
            assert result.exit_code != 0
            assert "--raw --minify" in result.output
            assert "--minify requires --raw" in result.output
            # Validation fails before any RapiClient construction or call.
            mock_client_cls.assert_not_called()
            mock_client.call.assert_not_called()

    def test_call_minify_with_raw_ok(self) -> None:
        """--minify together with --raw passes validation and produces compact JSON."""
        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            mock_client.call.return_value = _mock_response(
                data={"key": "value"},
                endpoint_ref="httpbin.get_ip",
            )
            mock_client_cls.return_value = mock_client

            result = runner.invoke(app, ["rapi", "call", "httpbin.get_ip", "--raw", "--minify"])

            assert result.exit_code == 0
            # Compact JSON: no whitespace between key/value separators.
            assert '{"key":"value"}' in result.stdout
            mock_client.call.assert_called_once()

    def test_call_raw_only_passes_validation(self) -> None:
        """--raw alone (no --minify) does not trigger the validation guard."""
        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            mock_client.call.return_value = _mock_response(
                data={"key": "value"},
                endpoint_ref="httpbin.get_ip",
            )
            mock_client_cls.return_value = mock_client

            result = runner.invoke(app, ["rapi", "call", "httpbin.get_ip", "--raw"])

            assert result.exit_code == 0
            mock_client.call.assert_called_once()

    def test_call_credential_error(self) -> None:
        """Credential error shows credential name."""
        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            mock_client.call.side_effect = CredentialError(credential_name="github_token", reason="Token expired")
            mock_client_cls.return_value = mock_client

            result = runner.invoke(app, ["rapi", "call", "github.user"])

            assert result.exit_code == 1
            assert "Credential error" in result.stdout

    def test_call_response_too_large(self) -> None:
        """Response too large shows sizes."""
        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            mock_client.call.side_effect = ResponseTooLargeError(response_size=20_000_000, max_size=10_000_000)
            mock_client_cls.return_value = mock_client

            result = runner.invoke(app, ["rapi", "call", "httpbin.get_ip"])

            assert result.exit_code == 1
            assert "too large" in result.stdout

    def test_call_auth_expired_exit_4(self) -> None:
        """AuthExpiredError triggers distinct exit code 4 with hint in output."""
        from kstlib.auth import AuthExpiredError

        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            mock_client.call.side_effect = AuthExpiredError(
                "Access token expired or invalidated (HTTP 401) on endpoint 'github.user'.",
                token_source="~/.sas/credentials.json",
                suggested_action="Re-authenticate with: sas-admin --profile $VIYA_HOST -k auth login -u <user>",
            )
            mock_client_cls.return_value = mock_client

            result = runner.invoke(app, ["rapi", "call", "github.user"])

            assert result.exit_code == 4
            assert "expired" in result.output.lower()
            assert "Source:" in result.output
            assert "credentials.json" in result.output
            assert "Hint:" in result.output
            assert "sas-admin" in result.output

    def test_call_auth_expired_env_hint(self) -> None:
        """AuthExpiredError with env-source hint surfaces the env var name."""
        from kstlib.auth import AuthExpiredError

        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            mock_client.call.side_effect = AuthExpiredError(
                "Access token expired (HTTP 401).",
                token_source="env:KSTLIB_TOKEN",
                suggested_action="Refresh and re-export env var: $KSTLIB_TOKEN",
            )
            mock_client_cls.return_value = mock_client

            result = runner.invoke(app, ["rapi", "call", "github.user"])

            assert result.exit_code == 4
            assert "Source: env:KSTLIB_TOKEN" in result.output
            assert "Hint:" in result.output
            assert "$KSTLIB_TOKEN" in result.output

    def test_call_auth_expired_no_token_source_no_hint(self) -> None:
        """AuthExpiredError without token_source/suggested_action keeps exit 4 with minimal message."""
        from kstlib.auth import AuthExpiredError

        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            mock_client.call.side_effect = AuthExpiredError("Access token expired (HTTP 401).")
            mock_client_cls.return_value = mock_client

            result = runner.invoke(app, ["rapi", "call", "github.user"])

            assert result.exit_code == 4
            assert "expired" in result.output.lower()
            assert "Source:" not in result.output
            assert "Hint:" not in result.output

    # ========================================================================
    # Phase 4: --server flag (server profile selection)
    # ========================================================================

    def test_call_with_server_flag(self) -> None:
        """--server flag is forwarded to client.call()."""
        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            mock_client.call.return_value = _mock_response(
                data={"login": "octocat"},
                endpoint_ref="github.user",
            )
            mock_client_cls.return_value = mock_client

            result = runner.invoke(app, ["rapi", "call", "--server", "github", "github.user"])

            assert result.exit_code == 0
            call_kwargs = mock_client.call.call_args.kwargs
            assert call_kwargs.get("server") == "github"

    def test_call_with_server_short_flag(self) -> None:
        """-s short flag works the same as --server."""
        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            mock_client.call.return_value = _mock_response(
                data={"login": "octocat"},
                endpoint_ref="github.user",
            )
            mock_client_cls.return_value = mock_client

            result = runner.invoke(app, ["rapi", "call", "-s", "github", "github.user"])

            assert result.exit_code == 0
            call_kwargs = mock_client.call.call_args.kwargs
            assert call_kwargs.get("server") == "github"

    def test_call_without_server_flag_passes_none(self) -> None:
        """No --server flag forwards server=None to client.call()."""
        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            mock_client.call.return_value = _mock_response(
                data={"origin": "1.2.3.4"},
                endpoint_ref="httpbin.get_ip",
            )
            mock_client_cls.return_value = mock_client

            result = runner.invoke(app, ["rapi", "call", "httpbin.get_ip"])

            assert result.exit_code == 0
            call_kwargs = mock_client.call.call_args.kwargs
            assert call_kwargs.get("server") is None

    def test_call_server_not_found(self) -> None:
        """Unknown server name exits 1 with helpful message listing available."""
        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            mock_client.call.side_effect = ServerNotFoundError(
                "ghost",
                available=["github", "jira"],
            )
            mock_client_cls.return_value = mock_client

            result = runner.invoke(app, ["rapi", "call", "-s", "ghost", "github.user"])

            assert result.exit_code == 1
            assert "Server profile not found" in result.stdout
            assert "ghost" in result.stdout
            # Available servers listed for the user
            assert "github" in result.stdout
            assert "jira" in result.stdout

    def test_call_server_not_found_no_servers_configured(self) -> None:
        """Unknown server with no servers configured shows '(none configured)'."""
        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            mock_client.call.side_effect = ServerNotFoundError("ghost", available=[])
            mock_client_cls.return_value = mock_client

            result = runner.invoke(app, ["rapi", "call", "-s", "ghost", "github.user"])

            assert result.exit_code == 1
            assert "Server profile not found" in result.stdout
            assert "(none configured)" in result.stdout


class TestRapiListQueryIndicator:
    """Tests for query parameter indicator in `kstlib rapi list`."""

    def test_list_shows_query_param_indicator(self) -> None:
        """List shows (N) indicator for endpoints with default query params."""
        with patch.object(rapi_pkg, "_load_config_or_exit") as mock_load:
            mock_load.return_value = _mock_config_manager_with_query()

            result = runner.invoke(app, ["rapi", "list"])

            assert result.exit_code == 0
            # binance.ticker has 2 query params
            assert "(2)" in result.stdout
            # binance.klines has 3 query params
            assert "(3)" in result.stdout
            # httpbin.get_ip has no query params, should not have indicator
            assert "get_ip" in result.stdout

    def test_list_no_indicator_without_query(self) -> None:
        """List does not show indicator for endpoints without query params."""
        with patch.object(rapi_pkg, "_load_config_or_exit") as mock_load:
            mock_load.return_value = _mock_config_manager()

            result = runner.invoke(app, ["rapi", "list"])

            assert result.exit_code == 0
            # No query params in basic config, no indicators
            assert "(" not in result.stdout or "endpoints" in result.stdout.lower()


class TestRapiShow:
    """Tests for `kstlib rapi show` command."""

    def test_show_endpoint_full_ref(self) -> None:
        """Show endpoint with full reference."""
        with patch.object(rapi_pkg, "_load_config_or_exit") as mock_load:
            mock_load.return_value = _mock_config_manager_with_query()

            result = runner.invoke(app, ["rapi", "show", "binance.ticker"])

            assert result.exit_code == 0
            assert "binance.ticker" in result.stdout
            assert "/api/v3/ticker/price" in result.stdout
            assert "GET" in result.stdout
            assert "https://api.binance.com" in result.stdout

    def test_show_endpoint_short_ref(self) -> None:
        """Show endpoint with short reference (if unique)."""
        with patch.object(rapi_pkg, "_load_config_or_exit") as mock_load:
            mock_load.return_value = _mock_config_manager_with_query()

            result = runner.invoke(app, ["rapi", "show", "ticker"])

            assert result.exit_code == 0
            assert "binance.ticker" in result.stdout

    def test_show_endpoint_not_found(self) -> None:
        """Show unknown endpoint fails with error."""
        with patch.object(rapi_pkg, "_load_config_or_exit") as mock_load:
            mock_load.return_value = _mock_config_manager()

            result = runner.invoke(app, ["rapi", "show", "unknown.endpoint"])

            assert result.exit_code == 1
            assert "not found" in result.stdout

    def test_show_endpoint_with_path_params(self) -> None:
        """Show endpoint with path parameters."""
        with patch.object(rapi_pkg, "_load_config_or_exit") as mock_load:
            mock_load.return_value = _mock_config_manager()

            result = runner.invoke(app, ["rapi", "show", "httpbin.delay"])

            assert result.exit_code == 0
            assert "{seconds}" in result.stdout
            assert "Path Parameters" in result.stdout

    def test_show_endpoint_with_query_params(self) -> None:
        """Show endpoint displays default query parameters."""
        with patch.object(rapi_pkg, "_load_config_or_exit") as mock_load:
            mock_load.return_value = _mock_config_manager_with_query()

            result = runner.invoke(app, ["rapi", "show", "binance.ticker"])

            assert result.exit_code == 0
            assert "Query Parameters" in result.stdout
            assert "symbol" in result.stdout
            assert "BTCUSDT" in result.stdout

    def test_show_endpoint_with_body_template(self) -> None:
        """Show endpoint displays body template."""
        with patch.object(rapi_pkg, "_load_config_or_exit") as mock_load:
            mock_load.return_value = _mock_config_manager_with_query()

            result = runner.invoke(app, ["rapi", "show", "binance.order"])

            assert result.exit_code == 0
            assert "Body Template" in result.stdout
            assert "POST" in result.stdout

    def test_show_endpoint_with_auth(self) -> None:
        """Show endpoint displays authentication info."""
        with patch.object(rapi_pkg, "_load_config_or_exit") as mock_load:
            mock_load.return_value = _mock_config_manager_with_query()

            result = runner.invoke(app, ["rapi", "show", "binance.ticker"])

            assert result.exit_code == 0
            assert "Authentication" in result.stdout
            assert "Required" in result.stdout
            assert "hmac" in result.stdout

    def test_show_endpoint_ref_too_long(self) -> None:
        """Hardening: reject endpoint reference exceeding max length."""
        long_ref = "a" * 300  # Exceeds HARD_MAX_ENDPOINT_REF_LENGTH (256)

        result = runner.invoke(app, ["rapi", "show", long_ref])

        assert result.exit_code == 1
        assert "too long" in result.stdout

    def test_show_endpoint_ref_invalid_chars(self) -> None:
        """Hardening: reject endpoint reference with invalid characters."""
        invalid_refs = [
            "api/endpoint",  # slash
            "api;endpoint",  # semicolon
            "api endpoint",  # space
            "api<script>",  # XSS attempt
            "api$var",  # shell variable
        ]
        for ref in invalid_refs:
            result = runner.invoke(app, ["rapi", "show", ref])

            assert result.exit_code == 1, f"Should reject: {ref}"
            assert "invalid characters" in result.stdout

    def test_show_endpoint_examples_section(self) -> None:
        """Show endpoint includes usage examples."""
        with patch.object(rapi_pkg, "_load_config_or_exit") as mock_load:
            mock_load.return_value = _mock_config_manager_with_query()

            result = runner.invoke(app, ["rapi", "show", "binance.ticker"])

            assert result.exit_code == 0
            assert "Examples" in result.stdout
            assert "kstlib rapi binance.ticker" in result.stdout
