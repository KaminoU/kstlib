"""Integration tests for the `kstlib rapi` CLI commands."""

from __future__ import annotations

import importlib
import json
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from box import Box
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


def _extraction_response(
    *,
    id_value: str | None = None,
    ids_value: list[str] | None = None,
    get_map: dict[str, Any] | None = None,
    extracted_map: dict[str, Any] | None = None,
    status_code: int = 200,
) -> RapiResponse:
    """Build a mock RapiResponse with extraction accessors configured.

    The accessors (`.id`, `.ids`, `.get`) are properties/methods on the real
    class, so they are set here where the local is MagicMock-typed (mypy would
    reject setting them on a `RapiResponse`-typed handle). The `extracted`
    mapping mirrors what an endpoint `extract:` directive would produce.
    """
    response = MagicMock(spec=RapiResponse)
    response.data = {}
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.id = id_value
    response.ids = ids_value if ids_value is not None else []
    response.extracted = Box(extracted_map or {})
    resolved = get_map or {}
    response.get.side_effect = lambda expr: resolved.get(expr)
    return cast("RapiResponse", response)


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


class TestRapiCallExtraction:
    """Tests for `kstlib rapi call` extraction flags (--pick/--extract/--show-id/--show-ids)."""

    @staticmethod
    def _run(args: list[str], response: RapiResponse | None) -> tuple[Any, MagicMock, MagicMock]:
        """Invoke `rapi call` with the client patched, returning result + client mocks."""
        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            if response is not None:
                mock_client.call.return_value = response
            mock_client_cls.return_value = mock_client
            result = runner.invoke(app, ["rapi", "call", *args])
        return result, mock_client_cls, mock_client

    def test_pick_scalar(self) -> None:
        """--pick prints a scalar value bare (no quotes, no Rich)."""
        resp = _extraction_response(get_map={"login": "octocat"})

        result, _, client = self._run(["github.user", "--pick", "login"], resp)

        assert result.exit_code == 0
        assert result.stdout.strip() == "octocat"
        client.call.assert_called_once()

    def test_pick_list_default_json_array(self) -> None:
        """--pick returning a list prints a JSON array by default."""
        resp = _extraction_response(get_map={"items[*].id": ["a", "b"]})

        result, *_ = self._run(["httpbin.get_ip", "--pick", "items[*].id"], resp)

        assert result.exit_code == 0
        assert json.loads(result.stdout) == ["a", "b"]

    def test_pick_list_raw_lines(self) -> None:
        """--pick list with --raw prints one element per line."""
        resp = _extraction_response(get_map={"items[*].id": ["a", "b", "c"]})

        result, *_ = self._run(["httpbin.get_ip", "--pick", "items[*].id", "--raw"], resp)

        assert result.exit_code == 0
        assert result.stdout.strip().splitlines() == ["a", "b", "c"]

    def test_pick_dict_json(self) -> None:
        """--pick returning a dict prints JSON."""
        resp = _extraction_response(get_map={"obj": {"k": "v"}})

        result, *_ = self._run(["httpbin.get_ip", "--pick", "obj"], resp)

        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"k": "v"}

    def test_pick_no_match_exits_1(self) -> None:
        """--pick matching nothing (None) writes a hint to stderr and exits 1."""
        resp = _extraction_response(get_map={"login": "octocat"})

        result, *_ = self._run(["github.user", "--pick", "missing"], resp)

        assert result.exit_code == 1
        assert "matched nothing" in result.output

    def test_extract_single_and_multi_keys(self) -> None:
        """--extract builds a JSON dict from key=jmespath specs."""
        resp = _extraction_response(get_map={"login": "octocat", "id": 583231})

        result, *_ = self._run(
            ["github.user", "--extract", "login=login", "--extract", "uid=id"],
            resp,
        )

        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"login": "octocat", "uid": 583231}

    def test_extract_raw_minify_compact(self) -> None:
        """--extract with --raw --minify produces compact JSON."""
        resp = _extraction_response(get_map={"a": 1})

        result, *_ = self._run(["httpbin.get_ip", "--extract", "a=a", "--raw", "--minify"], resp)

        assert result.exit_code == 0
        assert '{"a":1}' in result.stdout

    def test_extract_malformed_spec_no_equals(self) -> None:
        """--extract spec without '=' is rejected before any client call."""
        result, client_cls, _ = self._run(["github.user", "--extract", "noequals"], None)

        assert result.exit_code == 2
        assert "Invalid --extract spec" in result.output
        client_cls.assert_not_called()

    def test_extract_malformed_spec_empty_key(self) -> None:
        """--extract spec with an empty key is rejected."""
        result, client_cls, _ = self._run(["github.user", "--extract", "=data.id"], None)

        assert result.exit_code == 2
        assert "Key must not be empty" in result.output
        client_cls.assert_not_called()

    def test_show_id_present(self) -> None:
        """--show-id prints the resolved id and exits 0."""
        resp = _extraction_response(id_value="abc-123")

        result, *_ = self._run(["github.user", "--show-id"], resp)

        assert result.exit_code == 0
        assert result.stdout.strip() == "abc-123"

    def test_show_id_absent_exits_1(self) -> None:
        """--show-id with no resolvable id writes a hint to stderr and exits 1."""
        resp = _extraction_response(id_value=None)

        result, *_ = self._run(["github.user", "--show-id"], resp)

        assert result.exit_code == 1
        assert "No id could be resolved" in result.output

    def test_show_ids_populated(self) -> None:
        """--show-ids prints all ids as a JSON array."""
        resp = _extraction_response(ids_value=["a", "b", "c"])

        result, *_ = self._run(["github.user", "--show-ids"], resp)

        assert result.exit_code == 0
        assert json.loads(result.stdout) == ["a", "b", "c"]

    def test_show_ids_empty_is_valid(self) -> None:
        """--show-ids with an empty list prints [] and exits 0 (empty is legitimate)."""
        resp = _extraction_response(ids_value=[])

        result, *_ = self._run(["github.user", "--show-ids"], resp)

        assert result.exit_code == 0
        assert result.stdout.strip() == "[]"

    def test_show_ids_raw_empty_emits_nothing(self) -> None:
        """--show-ids --raw with an empty list emits no line (scriptable)."""
        resp = _extraction_response(ids_value=[])

        result, *_ = self._run(["github.user", "--show-ids", "--raw"], resp)

        assert result.exit_code == 0
        assert result.stdout.strip() == ""

    def test_mutual_exclusivity_rejected(self) -> None:
        """Combining two extraction modes is rejected before any client call."""
        combos = (
            ["--show-id", "--show-ids"],
            ["--pick", "x", "--show-id"],
            ["--extract", "a=b", "--pick", "x"],
            ["--extract", "a=b", "--show-ids"],
        )
        for combo in combos:
            result, client_cls, _ = self._run(["github.user", *combo], None)

            assert result.exit_code == 2, combo
            assert "Only one of" in result.output
            client_cls.assert_not_called()

    def test_extraction_pick_to_file(self, tmp_path: Any) -> None:
        """--pick with --out writes the extracted value to a file."""
        resp = _extraction_response(get_map={"obj": {"k": "v"}})

        out_file = tmp_path / "extract.json"
        result, *_ = self._run(["httpbin.get_ip", "--pick", "obj", "-o", str(out_file)], resp)

        assert result.exit_code == 0
        assert json.loads(out_file.read_text()) == {"k": "v"}
        assert "Output written to" in result.stdout

    def test_extraction_to_file_quiet(self, tmp_path: Any) -> None:
        """--pick with --out and --quiet suppresses the confirmation message."""
        resp = _extraction_response(get_map={"login": "octocat"})

        out_file = tmp_path / "value.txt"
        result, *_ = self._run(
            ["github.user", "--pick", "login", "-o", str(out_file), "-q"],
            resp,
        )

        assert result.exit_code == 0
        assert out_file.read_text() == "octocat"
        assert "Output written to" not in result.stdout

    def test_format_ignored_when_extraction_active(self) -> None:
        """--format is ignored when an extraction flag is active."""
        resp = _extraction_response(id_value="abc-123")

        result, *_ = self._run(["github.user", "--show-id", "--format", "full"], resp)

        assert result.exit_code == 0
        assert result.stdout.strip() == "abc-123"
        assert "status_code" not in result.stdout

    def test_extraction_non_ok_response_still_exits_1(self) -> None:
        """A non-OK HTTP response still exits 1 even when a value was extracted."""
        resp = _extraction_response(id_value="abc", status_code=404)

        result, *_ = self._run(["github.user", "--show-id"], resp)

        assert result.exit_code == 1
        assert "abc" in result.stdout


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


class TestRapiImplicitRouting:
    """Tests for implicit endpoint routing (`rapi <api>.<endpoint>` without `call`)."""

    @staticmethod
    def _run(args: list[str], response: RapiResponse | None) -> tuple[Any, MagicMock, MagicMock]:
        """Invoke `rapi` with the client patched, returning result + client mocks."""
        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            if response is not None:
                mock_client.call.return_value = response
            mock_client_cls.return_value = mock_client
            result = runner.invoke(app, ["rapi", *args])
        return result, mock_client_cls, mock_client

    def test_implicit_matches_explicit_call(self) -> None:
        """`rapi <endpoint>` produces the same result as `rapi call <endpoint>`."""
        data = {"origin": "1.2.3.4"}
        implicit, _, implicit_client = self._run(
            ["httpbin.get_ip"],
            _mock_response(data=data, endpoint_ref="httpbin.get_ip"),
        )
        explicit, _, explicit_client = self._run(
            ["call", "httpbin.get_ip"],
            _mock_response(data=data, endpoint_ref="httpbin.get_ip"),
        )

        assert implicit.exit_code == 0
        assert explicit.exit_code == 0
        assert implicit.stdout == explicit.stdout
        implicit_client.call.assert_called_once()
        explicit_client.call.assert_called_once()

    def test_implicit_preserves_flags(self) -> None:
        """Flags on the implicit form behave exactly as on the explicit form."""
        implicit, *_ = self._run(
            ["github.user", "--show-ids"],
            _extraction_response(ids_value=["a", "b"]),
        )
        explicit, *_ = self._run(
            ["call", "github.user", "--show-ids"],
            _extraction_response(ids_value=["a", "b"]),
        )

        assert implicit.exit_code == 0
        assert explicit.exit_code == 0
        assert implicit.stdout == explicit.stdout
        assert json.loads(implicit.stdout) == ["a", "b"]

    def test_implicit_preserves_positional_args(self) -> None:
        """Positional endpoint arguments survive the implicit redirect."""
        response = _mock_response(data={"ok": True}, endpoint_ref="httpbin.delay")

        result, _, client = self._run(["httpbin.delay", "3"], response)

        assert result.exit_code == 0
        assert "3" in client.call.call_args.args

    def test_unknown_command_without_dot_is_not_redirected(self) -> None:
        """An unknown token without a dot keeps the native error, no redirect."""
        result, client_cls, _ = self._run(["bogus"], None)

        assert result.exit_code != 0
        assert "No such command" in result.output
        client_cls.assert_not_called()

    def test_real_subcommands_not_captured(self) -> None:
        """`list` and `show` resolve as real sub-commands, never as endpoints."""
        for args, marker in (
            (["list"], "httpbin"),
            (["show", "httpbin.get_ip"], "get_ip"),
        ):
            result, client_cls, _ = self._run(args, None)

            assert result.exit_code == 0, f"args={args}"
            assert marker in result.stdout
            client_cls.assert_not_called()


class TestRapiConfigLoading:
    """Tests for the shared config loading helper used by list/show/call."""

    def test_load_failure_exits_1(self) -> None:
        """A config loading error prints a friendly message and exits 1."""
        with patch.object(rapi_pkg, "load_rapi_config") as mock_load:
            mock_load.side_effect = RuntimeError("boom")

            result = runner.invoke(app, ["rapi", "list"])

        assert result.exit_code == 1
        assert "Failed to load rapi config" in result.output

    def test_load_success_flows_to_command(self) -> None:
        """A successful load feeds the sub-command without interference."""
        with patch.object(rapi_pkg, "load_rapi_config") as mock_load:
            mock_load.return_value = _mock_config_manager()

            result = runner.invoke(app, ["rapi", "list"])

        assert result.exit_code == 0
        assert "httpbin" in result.stdout


class TestRapiShowExtracted:
    """Tests for `--show-extracted` (values declared by the endpoint extract: directive)."""

    @staticmethod
    def _run(args: list[str], response: RapiResponse | None) -> tuple[Any, MagicMock, MagicMock]:
        """Invoke `rapi call` with the client patched, returning result + client mocks."""
        with (
            patch.object(rapi_pkg, "_load_config_or_exit") as mock_load,
            patch.object(call_module, "RapiClient") as mock_client_cls,
        ):
            mock_load.return_value = _mock_config_manager()
            mock_client = MagicMock()
            if response is not None:
                mock_client.call.return_value = response
            mock_client_cls.return_value = mock_client
            result = runner.invoke(app, ["rapi", "call", *args])
        return result, mock_client_cls, mock_client

    def test_key_scalar_prints_bare(self) -> None:
        """A declared scalar key prints bare (no quotes, no Rich)."""
        resp = _extraction_response(extracted_map={"object_id": "abc-123"})

        result, *_ = self._run(["github.user", "--show-extracted", "object_id"], resp)

        assert result.exit_code == 0
        assert result.stdout.strip() == "abc-123"

    def test_key_list_prints_json_array(self) -> None:
        """A declared list key prints a JSON array by default."""
        resp = _extraction_response(extracted_map={"object_ids": ["a", "b"]})

        result, *_ = self._run(["github.user", "--show-extracted", "object_ids"], resp)

        assert result.exit_code == 0
        assert json.loads(result.stdout) == ["a", "b"]

    def test_key_list_raw_one_per_line(self) -> None:
        """A declared list key with --raw prints one element per line."""
        resp = _extraction_response(extracted_map={"object_ids": ["a", "b", "c"]})

        result, *_ = self._run(
            ["github.user", "--show-extracted", "object_ids", "--raw"],
            resp,
        )

        assert result.exit_code == 0
        assert result.stdout.strip().splitlines() == ["a", "b", "c"]

    def test_key_absent_exits_1_names_available(self) -> None:
        """An unknown key fails with a hint naming the available keys."""
        resp = _extraction_response(extracted_map={"object_ids": ["a"]})

        result, *_ = self._run(["github.user", "--show-extracted", "bogus"], resp)

        assert result.exit_code == 1
        assert "No extracted key 'bogus'" in result.output
        assert "object_ids" in result.output

    def test_key_evaluated_to_none_exits_1(self) -> None:
        """A declared key whose expression matched nothing fails with a hint."""
        resp = _extraction_response(extracted_map={"object_ids": None})

        result, *_ = self._run(["github.user", "--show-extracted", "object_ids"], resp)

        assert result.exit_code == 1
        assert "matched nothing" in result.output

    def test_key_empty_list_is_legitimate(self) -> None:
        """A declared key holding an empty collection exits 0 (legitimate result)."""
        resp = _extraction_response(extracted_map={"object_ids": []})

        result, *_ = self._run(["github.user", "--show-extracted", "object_ids"], resp)

        assert result.exit_code == 0
        assert result.stdout.strip() == "[]"

    def test_all_keys_prints_json_dict(self) -> None:
        """The bare flag prints all extracted keys as a JSON dict."""
        resp = _extraction_response(extracted_map={"object_id": "x", "names": ["a"]})

        result, *_ = self._run(["github.user", "--show-extracted"], resp)

        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"object_id": "x", "names": ["a"]}

    def test_all_keys_without_directive_exits_1(self) -> None:
        """The bare flag on an endpoint without extract: directive fails with a hint."""
        resp = _extraction_response(extracted_map={})

        result, *_ = self._run(["github.user", "--show-extracted"], resp)

        assert result.exit_code == 1
        assert "No extract: directive declared" in result.output

    @pytest.mark.parametrize(
        "other",
        [["--pick", "login"], ["--extract", "a=a"], ["--show-id"], ["--show-ids"]],
        ids=["pick", "extract", "show-id", "show-ids"],
    )
    def test_exclusive_with_each_other_flag(self, other: list[str]) -> None:
        """--show-extracted rejects combination with every other extraction flag."""
        result, client_cls, _ = self._run(
            ["github.user", "--show-extracted", "k", *other],
            None,
        )

        assert result.exit_code == 2
        assert "Only one of" in result.output
        client_cls.assert_not_called()

    def test_bare_flag_before_option_not_greedy(self) -> None:
        """A bare flag followed by another option selects all keys, option preserved."""
        resp = _extraction_response(extracted_map={"object_ids": ["a", "b"]})

        result, *_ = self._run(["github.user", "--show-extracted", "--raw"], resp)

        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"object_ids": ["a", "b"]}

    def test_bare_flag_before_query_arg_preserved(self) -> None:
        """A bare flag followed by key=value keeps it as a query argument."""
        resp = _extraction_response(extracted_map={"object_id": "x"})

        result, _, client = self._run(
            ["httpbin.get_ip", "--show-extracted", "limit=5"],
            resp,
        )

        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"object_id": "x"}
        assert client.call.call_args.kwargs["limit"] == "5"

    def test_equals_form_selects_key(self) -> None:
        """The --show-extracted=key form selects the key explicitly."""
        resp = _extraction_response(extracted_map={"object_id": "abc-123"})

        result, *_ = self._run(["github.user", "--show-extracted=object_id"], resp)

        assert result.exit_code == 0
        assert result.stdout.strip() == "abc-123"

    def test_raw_minify_compact_json(self) -> None:
        """--raw --minify renders the selected dict as compact JSON."""
        resp = _extraction_response(extracted_map={"a": 1})

        result, *_ = self._run(
            ["github.user", "--show-extracted", "--raw", "--minify"],
            resp,
        )

        assert result.exit_code == 0
        assert '{"a":1}' in result.stdout

    def test_out_file_writes_and_confirms(self, tmp_path: Any) -> None:
        """--out writes the extracted value to a file with a confirmation."""
        resp = _extraction_response(extracted_map={"object_ids": ["a", "b"]})
        target = tmp_path / "extracted.json"

        result, *_ = self._run(
            ["github.user", "--show-extracted", "object_ids", "--out", str(target)],
            resp,
        )

        assert result.exit_code == 0
        assert json.loads(target.read_text(encoding="utf-8")) == ["a", "b"]
        assert "Output written to" in result.stdout

    def test_out_file_quiet_is_silent(self, tmp_path: Any) -> None:
        """--out with --quiet writes the file without the confirmation line."""
        resp = _extraction_response(extracted_map={"object_id": "x"})
        target = tmp_path / "extracted.txt"

        result, *_ = self._run(
            ["github.user", "--show-extracted", "object_id", "--out", str(target), "--quiet"],
            resp,
        )

        assert result.exit_code == 0
        assert target.read_text(encoding="utf-8") == "x"
        assert "Output written to" not in result.stdout

    def test_format_ignored_when_active(self) -> None:
        """--format is ignored while --show-extracted drives the output."""
        resp = _extraction_response(extracted_map={"object_id": "x"})

        result, *_ = self._run(
            ["github.user", "-f", "full", "--show-extracted", "object_id"],
            resp,
        )

        assert result.exit_code == 0
        assert result.stdout.strip() == "x"
