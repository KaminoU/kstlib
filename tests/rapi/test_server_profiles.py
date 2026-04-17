"""Tests for the runtime layer of the rapi multi-server feature.

Covers:
- ``RapiClient.call(server=...)`` resolves and overrides base_url
- The cascade priority runtime > endpoint > file > None
- ``ServerNotFoundError`` is raised for unknown server names
- Inline credentials from ServerConfig are resolved correctly
- Header cascade: api < server < endpoint < runtime
- Async path mirrors sync path
- Backward compatibility: ``server=None`` keeps current behavior
"""

from __future__ import annotations

from typing import Any
from unittest import mock

import httpx
import pytest

from kstlib.rapi.client import RapiClient
from kstlib.rapi.config import RapiConfigManager
from kstlib.rapi.exceptions import ServerNotFoundError


def _mock_response(status: int = 200, body: bytes = b"{}") -> mock.Mock:
    """Build an httpx.Response mock with JSON content type."""
    resp = mock.Mock(spec=httpx.Response)
    resp.status_code = status
    resp.reason_phrase = "OK"
    resp.headers = {"content-type": "application/json"}
    resp.content = body
    resp.text = body.decode()
    resp.json.return_value = {}
    return resp


def _mock_client_class(send_return: mock.Mock | None = None) -> mock.Mock:
    """Build a mocked httpx.Client class with a send() that returns send_return."""
    mock_client = mock.Mock()
    mock_client.send.return_value = send_return or _mock_response()
    mock_client.__enter__ = mock.Mock(return_value=mock_client)
    mock_client.__exit__ = mock.Mock(return_value=False)
    return mock_client


def _make_manager(
    *,
    api_data: dict[str, Any],
    servers: dict[str, dict[str, Any]] | None = None,
) -> RapiConfigManager:
    """Build a RapiConfigManager with inline API + optional server profiles."""
    manager = RapiConfigManager({"api": api_data})
    if servers:
        manager._servers = servers
    return manager


# ============================================================================
# server= kwarg overrides base_url
# ============================================================================


class TestServerKwargBaseUrl:
    """The server= kwarg replaces api_config.base_url at request time."""

    @mock.patch("httpx.Client")
    def test_runtime_server_overrides_base_url(self, mock_client_class: mock.Mock) -> None:
        """call(server='github') routes to github.base_url, not api.base_url."""
        mock_client_class.return_value = _mock_client_class()

        manager = _make_manager(
            api_data={
                "github": {
                    "base_url": "https://wrong.example.com",
                    "endpoints": {"user": {"path": "/user"}},
                }
            },
            servers={
                "github": {"base_url": "https://api.github.com"},
            },
        )
        client = RapiClient(config_manager=manager)
        client.call("github.user", server="github")

        # Verify the actual outgoing request URL came from the server profile
        sent_request = mock_client_class.return_value.send.call_args.args[0]
        assert "api.github.com" in str(sent_request.url)
        assert "wrong.example.com" not in str(sent_request.url)

    @mock.patch("httpx.Client")
    def test_no_server_kwarg_uses_static_base_url(self, mock_client_class: mock.Mock) -> None:
        """call() without server= falls back to api_config.base_url (regression)."""
        mock_client_class.return_value = _mock_client_class()

        manager = _make_manager(
            api_data={
                "github": {
                    "base_url": "https://api.github.com",
                    "endpoints": {"user": {"path": "/user"}},
                }
            }
        )
        client = RapiClient(config_manager=manager)
        client.call("github.user")

        sent_request = mock_client_class.return_value.send.call_args.args[0]
        assert "api.github.com" in str(sent_request.url)


# ============================================================================
# Cascade: runtime > endpoint > file > None
# ============================================================================


class TestServerCascade:
    """Runtime server > endpoint server: > file server: > None."""

    @mock.patch("httpx.Client")
    def test_runtime_overrides_endpoint_directive(self, mock_client_class: mock.Mock) -> None:
        """server='alt' kwarg wins over endpoint-level server: target."""
        mock_client_class.return_value = _mock_client_class()

        manager = _make_manager(
            api_data={
                "transfer": {
                    "base_url": "https://default.example.com",
                    "endpoints": {
                        "upload": {
                            "path": "/upload",
                            "method": "POST",
                            "server": "target",
                        },
                    },
                }
            },
            servers={
                "target": {"base_url": "https://target.example.com"},
                "alt": {"base_url": "https://alt.example.com"},
            },
        )
        client = RapiClient(config_manager=manager)
        client.call("transfer.upload", server="alt")

        sent = mock_client_class.return_value.send.call_args.args[0]
        assert "alt.example.com" in str(sent.url)
        assert "target.example.com" not in str(sent.url)

    @mock.patch("httpx.Client")
    def test_endpoint_directive_overrides_file_directive(self, mock_client_class: mock.Mock) -> None:
        """Endpoint-level server: target wins over file-level server: source."""
        mock_client_class.return_value = _mock_client_class()

        manager = _make_manager(
            api_data={
                "transfer": {
                    "base_url": "https://default.example.com",
                    "server": "source",
                    "endpoints": {
                        "upload": {"path": "/upload", "server": "target"},
                    },
                }
            },
            servers={
                "source": {"base_url": "https://source.example.com"},
                "target": {"base_url": "https://target.example.com"},
            },
        )
        client = RapiClient(config_manager=manager)
        client.call("transfer.upload")

        sent = mock_client_class.return_value.send.call_args.args[0]
        assert "target.example.com" in str(sent.url)

    @mock.patch("httpx.Client")
    def test_file_directive_used_when_no_endpoint_or_runtime(self, mock_client_class: mock.Mock) -> None:
        """File-level server: source is used when nothing else specifies."""
        mock_client_class.return_value = _mock_client_class()

        manager = _make_manager(
            api_data={
                "transfer": {
                    "base_url": "https://default.example.com",
                    "server": "source",
                    "endpoints": {"list": {"path": "/list"}},
                }
            },
            servers={
                "source": {"base_url": "https://source.example.com"},
            },
        )
        client = RapiClient(config_manager=manager)
        client.call("transfer.list")

        sent = mock_client_class.return_value.send.call_args.args[0]
        assert "source.example.com" in str(sent.url)


# ============================================================================
# ServerNotFoundError on unknown name
# ============================================================================


class TestServerNotFound:
    """Unknown server names raise ServerNotFoundError, no HTTP call made."""

    @mock.patch("httpx.Client")
    def test_unknown_runtime_server_raises(self, mock_client_class: mock.Mock) -> None:
        """call(server='ghost') raises before any HTTP call."""
        manager = _make_manager(
            api_data={
                "github": {
                    "base_url": "https://api.github.com",
                    "endpoints": {"user": {"path": "/user"}},
                }
            },
            servers={
                "github": {"base_url": "https://api.github.com"},
            },
        )
        client = RapiClient(config_manager=manager)

        with pytest.raises(ServerNotFoundError, match="ghost"):
            client.call("github.user", server="ghost")

        # No HTTP call was attempted
        mock_client_class.return_value.send.assert_not_called() if mock_client_class.return_value.send.called else None


# ============================================================================
# Inline credentials from ServerConfig
# ============================================================================


class TestServerCredentials:
    """ServerConfig.credentials (inline dict) is resolved via resolve_inline."""

    @mock.patch("httpx.Client")
    def test_server_inline_env_credentials_used(
        self, mock_client_class: mock.Mock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """server.credentials with type=env yields the right Authorization header."""
        monkeypatch.setenv("GITHUB_TEST_TOKEN", "ghp_secrettoken")
        mock_client_class.return_value = _mock_client_class()

        manager = _make_manager(
            api_data={
                "github": {
                    "base_url": "https://api.github.com",
                    "endpoints": {"user": {"path": "/user"}},
                }
            },
            servers={
                "github": {
                    "base_url": "https://api.github.com",
                    "credentials": {"type": "env", "var": "GITHUB_TEST_TOKEN"},
                    "auth": "bearer",
                },
            },
        )
        client = RapiClient(config_manager=manager)
        client.call("github.user", server="github")

        sent = mock_client_class.return_value.send.call_args.args[0]
        assert sent.headers.get("authorization") == "Bearer ghp_secrettoken"

    @mock.patch("httpx.Client")
    def test_server_credentials_replace_static_credentials(
        self, mock_client_class: mock.Mock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When server has credentials, the static api_config credentials are NOT used."""
        monkeypatch.setenv("STATIC_TOKEN", "static_value")
        monkeypatch.setenv("SERVER_TOKEN", "server_value")
        mock_client_class.return_value = _mock_client_class()

        manager = _make_manager(
            api_data={
                "myapi": {
                    "base_url": "https://api.example.com",
                    "credentials": "static_cred",
                    "auth_type": "bearer",
                    "endpoints": {"get": {"path": "/data"}},
                }
            },
            servers={
                "override": {
                    "base_url": "https://api.example.com",
                    "credentials": {"type": "env", "var": "SERVER_TOKEN"},
                },
            },
        )
        # Inject static_cred into resolver registry too (so the static path
        # is functional and we can prove the server one wins)
        manager._credentials_config["static_cred"] = {
            "type": "env",
            "var": "STATIC_TOKEN",
        }
        client = RapiClient(config_manager=manager)
        client.call("myapi.get", server="override")

        sent = mock_client_class.return_value.send.call_args.args[0]
        assert sent.headers.get("authorization") == "Bearer server_value"
        assert "static_value" not in sent.headers.get("authorization", "")


# ============================================================================
# Header cascade: api < server < endpoint < runtime
# ============================================================================


class TestHeaderCascade:
    """Verify the 4-level header cascade applies server headers correctly."""

    @mock.patch("httpx.Client")
    def test_server_headers_layer_between_api_and_endpoint(self, mock_client_class: mock.Mock) -> None:
        """api < server < endpoint < runtime: each layer overrides the previous."""
        mock_client_class.return_value = _mock_client_class()

        manager = _make_manager(
            api_data={
                "github": {
                    "base_url": "https://api.github.com",
                    "headers": {
                        "X-Layer": "api",
                        "X-Api-Only": "yes",
                    },
                    "endpoints": {
                        "user": {
                            "path": "/user",
                            "headers": {
                                "X-Layer": "endpoint",
                                "X-Endpoint-Only": "yes",
                            },
                        },
                    },
                }
            },
            servers={
                "github": {
                    "base_url": "https://api.github.com",
                    "headers": {
                        "X-Layer": "server",
                        "X-Server-Only": "yes",
                    },
                },
            },
        )
        client = RapiClient(config_manager=manager)
        client.call(
            "github.user",
            server="github",
            headers={"X-Layer": "runtime", "X-Runtime-Only": "yes"},
        )

        sent = mock_client_class.return_value.send.call_args.args[0]
        # X-Layer is overridden at every level → runtime wins
        assert sent.headers.get("x-layer") == "runtime"
        # Each layer's exclusive header survives
        assert sent.headers.get("x-api-only") == "yes"
        assert sent.headers.get("x-server-only") == "yes"
        assert sent.headers.get("x-endpoint-only") == "yes"
        assert sent.headers.get("x-runtime-only") == "yes"

    @mock.patch("httpx.Client")
    def test_server_overrides_api_endpoint_overrides_server(self, mock_client_class: mock.Mock) -> None:
        """Confirm middle of the cascade: api < server < endpoint."""
        mock_client_class.return_value = _mock_client_class()

        manager = _make_manager(
            api_data={
                "github": {
                    "base_url": "https://api.github.com",
                    "headers": {"X-Same": "api-value"},
                    "endpoints": {
                        "user": {"path": "/user", "headers": {"X-Same": "endpoint-value"}},
                    },
                }
            },
            servers={
                "github": {
                    "base_url": "https://api.github.com",
                    "headers": {"X-Same": "server-value"},
                },
            },
        )
        client = RapiClient(config_manager=manager)
        client.call("github.user", server="github")

        sent = mock_client_class.return_value.send.call_args.args[0]
        # endpoint is the highest layer (no runtime override here)
        assert sent.headers.get("x-same") == "endpoint-value"


# ============================================================================
# Async path mirrors sync path
# ============================================================================


class TestAsyncServer:
    """call_async() applies the server cascade identically to call()."""

    @pytest.mark.asyncio
    @mock.patch("httpx.AsyncClient")
    async def test_call_async_with_server(self, mock_async_class: mock.Mock) -> None:
        """call_async(server='github') routes to the github base_url."""
        resp = _mock_response()
        mock_async = mock.AsyncMock()
        mock_async.send = mock.AsyncMock(return_value=resp)
        mock_async.__aenter__ = mock.AsyncMock(return_value=mock_async)
        mock_async.__aexit__ = mock.AsyncMock(return_value=False)
        mock_async_class.return_value = mock_async

        manager = _make_manager(
            api_data={
                "github": {
                    "base_url": "https://wrong.example.com",
                    "endpoints": {"user": {"path": "/user"}},
                }
            },
            servers={
                "github": {"base_url": "https://api.github.com"},
            },
        )
        client = RapiClient(config_manager=manager)
        await client.call_async("github.user", server="github")

        sent_request = mock_async.send.call_args.args[0]
        assert "api.github.com" in str(sent_request.url)


# ============================================================================
# Module-level call() and call_async() pass server through
# ============================================================================


class TestModuleLevelCallServer:
    """The convenience call()/call_async() functions accept server= too."""

    @mock.patch("kstlib.rapi.client.RapiClient")
    def test_module_call_passes_server(self, mock_rapi_class: mock.Mock) -> None:
        """call(server=...) is forwarded to RapiClient.call."""
        from kstlib.rapi import call

        mock_instance = mock.Mock()
        mock_instance.call.return_value = mock.Mock()
        mock_rapi_class.return_value = mock_instance

        call("github.user", server="github")

        # Verify the kwarg propagated
        kwargs = mock_instance.call.call_args.kwargs
        assert kwargs.get("server") == "github"


# ============================================================================
# Phase 5: end-to-end integration tests
# ============================================================================


class TestActiveViyaPattern:
    """The ${ACTIVE_VIYA:-Default} env var pattern in token_path.

    These tests verify that the global YAML env-var expansion
    (``_expand_env_vars_recursive``) correctly substitutes ``${VAR}``
    placeholders inside ``token_path`` at config-load time, which is
    the foundation of the Pattern A multi-environment workflow
    documented in features/rapi/index.md.
    """

    def test_token_path_env_var_expansion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ACTIVE_VIYA in token_path is substituted at YAML load."""
        monkeypatch.setenv("ACTIVE_VIYA", "source")
        from kstlib.rapi.config import _expand_env_vars_recursive

        raw = {
            "credentials": {
                "type": "file",
                "path": "~/.sas/credentials.json",
                "token_path": ".${ACTIVE_VIYA:-Default}['access-token']",
            },
        }
        expanded = _expand_env_vars_recursive(raw)
        assert expanded["credentials"]["token_path"] == ".source['access-token']"

    def test_token_path_default_when_env_var_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When ACTIVE_VIYA is not set, the :-Default fallback wins."""
        monkeypatch.delenv("ACTIVE_VIYA", raising=False)
        from kstlib.rapi.config import _expand_env_vars_recursive

        raw = {"token_path": ".${ACTIVE_VIYA:-Default}['access-token']"}
        expanded = _expand_env_vars_recursive(raw)
        assert expanded["token_path"] == ".Default['access-token']"

    def test_token_path_switches_with_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Different ACTIVE_VIYA values yield different token_path strings."""
        from kstlib.rapi.config import _expand_env_vars_recursive

        raw_template = {"token_path": ".${ACTIVE_VIYA:-Default}['access-token']"}

        monkeypatch.setenv("ACTIVE_VIYA", "source")
        assert _expand_env_vars_recursive(raw_template)["token_path"] == ".source['access-token']"

        monkeypatch.setenv("ACTIVE_VIYA", "target")
        assert _expand_env_vars_recursive(raw_template)["token_path"] == ".target['access-token']"


class TestFullYamlLoadIntegration:
    """End-to-end: load a *.rapi.yml file with server: directive and call it."""

    @mock.patch("httpx.Client")
    def test_yaml_file_with_endpoint_server_directive(self, mock_client_class: mock.Mock, tmp_path: Any) -> None:
        """A *.rapi.yml file with endpoint server: parses and routes correctly."""
        mock_client_class.return_value = _mock_client_class()

        # Write a real *.rapi.yml file with an endpoint-level server: directive
        rapi_file = tmp_path / "transfer.rapi.yml"
        rapi_file.write_text(
            "name: transfer\n"
            'base_url: "https://default.example.com"\n'
            "endpoints:\n"
            "  upload:\n"
            "    path: /upload\n"
            "    method: POST\n"
            "    server: target\n",
            encoding="utf-8",
        )

        # Load via RapiConfigManager.from_file (real YAML parsing pipeline)
        manager = RapiConfigManager.from_file(rapi_file)

        # Inject a servers section as if it came from kstlib.conf.yml
        manager._servers = {
            "target": {"base_url": "https://target.example.com"},
        }

        # Verify the directive was parsed into EndpointConfig
        endpoint = manager._apis["transfer"].endpoints["upload"]
        assert endpoint.server == "target"

        # Now call it via RapiClient and verify the URL routing
        client = RapiClient(config_manager=manager)
        client.call("transfer.upload")

        sent = mock_client_class.return_value.send.call_args.args[0]
        assert "target.example.com" in str(sent.url)
        assert "default.example.com" not in str(sent.url)

    @mock.patch("httpx.Client")
    def test_yaml_file_with_file_level_server_directive(self, mock_client_class: mock.Mock, tmp_path: Any) -> None:
        """A *.rapi.yml file with top-level server: applies to all endpoints."""
        mock_client_class.return_value = _mock_client_class()

        rapi_file = tmp_path / "transfer.rapi.yml"
        rapi_file.write_text(
            "name: transfer\n"
            'base_url: "https://default.example.com"\n'
            "server: source\n"
            "endpoints:\n"
            "  list:\n"
            "    path: /items\n",
            encoding="utf-8",
        )

        manager = RapiConfigManager.from_file(rapi_file)
        manager._servers = {
            "source": {"base_url": "https://source.example.com"},
        }

        # File-level server: lives on the ApiConfig
        assert manager._apis["transfer"].server == "source"
        assert manager._apis["transfer"].endpoints["list"].server is None

        client = RapiClient(config_manager=manager)
        client.call("transfer.list")

        sent = mock_client_class.return_value.send.call_args.args[0]
        assert "source.example.com" in str(sent.url)


class TestRuntimeOverridesFullCascade:
    """Cross-validation: runtime kwarg overrides everything in the YAML."""

    @mock.patch("httpx.Client")
    def test_runtime_kwarg_wins_over_yaml_endpoint_directive(self, mock_client_class: mock.Mock, tmp_path: Any) -> None:
        """call(server='alt') overrides server: target written in the YAML file."""
        mock_client_class.return_value = _mock_client_class()

        rapi_file = tmp_path / "transfer.rapi.yml"
        rapi_file.write_text(
            "name: transfer\n"
            'base_url: "https://default.example.com"\n'
            "endpoints:\n"
            "  upload:\n"
            "    path: /upload\n"
            "    method: POST\n"
            "    server: target\n",
            encoding="utf-8",
        )

        manager = RapiConfigManager.from_file(rapi_file)
        manager._servers = {
            "target": {"base_url": "https://target.example.com"},
            "alt": {"base_url": "https://alt.example.com"},
        }

        client = RapiClient(config_manager=manager)
        client.call("transfer.upload", server="alt")

        sent = mock_client_class.return_value.send.call_args.args[0]
        # Runtime "alt" wins over endpoint-level "target"
        assert "alt.example.com" in str(sent.url)
        assert "target.example.com" not in str(sent.url)
        assert "default.example.com" not in str(sent.url)
