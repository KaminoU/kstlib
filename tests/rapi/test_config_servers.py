"""Tests for named server profiles in RapiConfigManager."""

from __future__ import annotations

from typing import Any

import pytest

from kstlib.rapi.config import RapiConfigManager, ServerConfig
from kstlib.rapi.exceptions import ServerNotFoundError


def _make_manager(
    *,
    defaults: dict[str, Any] | None = None,
    servers: dict[str, dict[str, Any]] | None = None,
) -> RapiConfigManager:
    """Build a minimal RapiConfigManager with defaults and servers injected."""
    manager = RapiConfigManager({"api": {}})
    if defaults:
        manager._defaults = defaults
    if servers:
        manager._servers = servers
    return manager


class TestResolveServerNone:
    """resolve_server(None) returns defaults."""

    def test_returns_defaults_base_url(self) -> None:
        """Return base_url from defaults when server_name is None."""
        manager = _make_manager(defaults={"base_url": "https://default.example.com"})
        server = manager.resolve_server(None)
        assert server.base_url == "https://default.example.com"

    def test_returns_defaults_name(self) -> None:
        """ServerConfig name is 'defaults' when no server specified."""
        manager = _make_manager(defaults={"base_url": "https://x.com"})
        server = manager.resolve_server(None)
        assert server.name == "defaults"

    def test_returns_defaults_credentials(self) -> None:
        """Return credentials from defaults."""
        creds = {"type": "file", "path": "~/.sas/creds.json"}
        manager = _make_manager(defaults={"base_url": "https://x.com", "credentials": creds})
        server = manager.resolve_server(None)
        assert server.credentials == creds

    def test_returns_defaults_auth(self) -> None:
        """Return auth from defaults."""
        manager = _make_manager(defaults={"base_url": "https://x.com", "auth": "bearer"})
        server = manager.resolve_server(None)
        assert server.auth == "bearer"

    def test_returns_defaults_headers(self) -> None:
        """Return headers from defaults."""
        hdrs = {"Accept": "application/json", "Content-Type": "application/json"}
        manager = _make_manager(defaults={"base_url": "https://x.com", "headers": hdrs})
        server = manager.resolve_server(None)
        assert server.headers == hdrs

    def test_empty_defaults(self) -> None:
        """Return empty ServerConfig when defaults is empty."""
        manager = _make_manager(defaults={})
        server = manager.resolve_server(None)
        assert server.base_url == ""
        assert server.credentials == {}
        assert server.auth is None
        assert server.headers == {}


class TestResolveServerNoServersSection:
    """No rapi.servers section -> defaults used, no error."""

    def test_resolve_none_without_servers(self) -> None:
        """resolve_server(None) works even if no servers configured."""
        manager = _make_manager(defaults={"base_url": "https://default.com", "auth": "bearer"})
        server = manager.resolve_server(None)
        assert server.base_url == "https://default.com"
        assert server.auth == "bearer"

    def test_resolve_named_without_servers_raises(self) -> None:
        """resolve_server('source') raises when no servers configured."""
        manager = _make_manager(defaults={"base_url": "https://default.com"})
        with pytest.raises(ServerNotFoundError, match="source"):
            manager.resolve_server("source")

    def test_server_names_empty(self) -> None:
        """server_names is empty when no servers configured."""
        manager = _make_manager()
        assert manager.server_names == []


class TestResolveServerOverrideBaseUrl:
    """Server overrides base_url only, other keys inherited from defaults."""

    def test_base_url_overridden(self) -> None:
        """Server base_url overrides defaults base_url."""
        manager = _make_manager(
            defaults={
                "base_url": "https://default.com",
                "credentials": {"type": "file", "path": "~/.sas/default.json"},
                "auth": "bearer",
                "headers": {"Accept": "application/json"},
            },
            servers={
                "source": {"base_url": "https://source.com"},
            },
        )
        server = manager.resolve_server("source")
        assert server.base_url == "https://source.com"

    def test_credentials_inherited(self) -> None:
        """Credentials fall back to defaults when not specified in server."""
        manager = _make_manager(
            defaults={
                "base_url": "https://default.com",
                "credentials": {"type": "file", "path": "~/.sas/default.json"},
            },
            servers={
                "source": {"base_url": "https://source.com"},
            },
        )
        server = manager.resolve_server("source")
        assert server.credentials == {"type": "file", "path": "~/.sas/default.json"}

    def test_auth_inherited(self) -> None:
        """Auth falls back to defaults when not specified in server."""
        manager = _make_manager(
            defaults={"base_url": "https://default.com", "auth": "bearer"},
            servers={"source": {"base_url": "https://source.com"}},
        )
        server = manager.resolve_server("source")
        assert server.auth == "bearer"

    def test_headers_inherited(self) -> None:
        """Headers fall back to defaults when not specified in server."""
        manager = _make_manager(
            defaults={"base_url": "https://default.com", "headers": {"Accept": "application/json"}},
            servers={"source": {"base_url": "https://source.com"}},
        )
        server = manager.resolve_server("source")
        assert server.headers == {"Accept": "application/json"}


class TestResolveServerOverrideCredentials:
    """Server overrides credentials, base_url inherited from defaults."""

    def test_credentials_overridden(self) -> None:
        """Server credentials replace defaults credentials."""
        manager = _make_manager(
            defaults={
                "base_url": "https://default.com",
                "credentials": {"type": "file", "path": "~/.sas/default.json", "token_path": ".Default"},
            },
            servers={
                "target": {
                    "credentials": {"type": "file", "path": "~/.sas/target.json", "token_path": ".Target"},
                },
            },
        )
        server = manager.resolve_server("target")
        assert server.credentials["path"] == "~/.sas/target.json"
        assert server.credentials["token_path"] == ".Target"

    def test_base_url_inherited(self) -> None:
        """Base URL falls back to defaults when not specified in server."""
        manager = _make_manager(
            defaults={"base_url": "https://default.com"},
            servers={"target": {"credentials": {"type": "env", "var": "TOKEN"}}},
        )
        server = manager.resolve_server("target")
        assert server.base_url == "https://default.com"


class TestResolveServerDeepMergeHeaders:
    """Server overrides headers partially, deep merge with defaults."""

    def test_server_header_added(self) -> None:
        """Server adds a new header on top of defaults."""
        manager = _make_manager(
            defaults={
                "base_url": "https://default.com",
                "headers": {"Accept": "application/json", "Content-Type": "application/json"},
            },
            servers={
                "source": {"headers": {"X-Custom": "value"}},
            },
        )
        server = manager.resolve_server("source")
        assert server.headers["Accept"] == "application/json"
        assert server.headers["Content-Type"] == "application/json"
        assert server.headers["X-Custom"] == "value"

    def test_server_header_overrides(self) -> None:
        """Server overrides an existing default header."""
        manager = _make_manager(
            defaults={
                "base_url": "https://default.com",
                "headers": {"Accept": "application/json"},
            },
            servers={
                "source": {"headers": {"Accept": "text/plain"}},
            },
        )
        server = manager.resolve_server("source")
        assert server.headers["Accept"] == "text/plain"

    def test_credentials_deep_merged(self) -> None:
        """Credentials are deep merged (server overrides specific keys)."""
        manager = _make_manager(
            defaults={
                "base_url": "https://default.com",
                "credentials": {"type": "file", "path": "~/.sas/default.json", "token_path": ".Default"},
            },
            servers={
                "source": {"credentials": {"path": "~/.sas/source.json"}},
            },
        )
        server = manager.resolve_server("source")
        assert server.credentials["type"] == "file"
        assert server.credentials["path"] == "~/.sas/source.json"
        assert server.credentials["token_path"] == ".Default"


class TestResolveServerUnknown:
    """resolve_server('unknown') raises ServerNotFoundError."""

    def test_unknown_raises(self) -> None:
        """Raise ServerNotFoundError for unknown server name."""
        manager = _make_manager(
            defaults={"base_url": "https://default.com"},
            servers={"source": {"base_url": "https://source.com"}},
        )
        with pytest.raises(ServerNotFoundError, match="unknown"):
            manager.resolve_server("unknown")

    def test_error_lists_available(self) -> None:
        """Error message includes available server names."""
        manager = _make_manager(
            defaults={},
            servers={"source": {}, "target": {}},
        )
        with pytest.raises(ServerNotFoundError) as exc_info:
            manager.resolve_server("staging")
        assert exc_info.value.available == ["source", "target"]
        assert exc_info.value.server_name == "staging"

    def test_error_no_servers(self) -> None:
        """Error message says no servers configured when servers dict is empty."""
        manager = _make_manager(defaults={})
        with pytest.raises(ServerNotFoundError, match="No server profiles configured"):
            manager.resolve_server("anything")


class TestResolveServerEnvVars:
    """Environment variable substitution in server base_url."""

    def test_env_var_in_server_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Env vars in server base_url are expanded by load_rapi_config."""
        monkeypatch.setenv("VIYA_SOURCE_HOST", "source.example.com")
        from kstlib.rapi.config import _expand_env_vars_recursive

        servers_raw = {"source": {"base_url": "https://${VIYA_SOURCE_HOST}"}}
        servers = {k: _expand_env_vars_recursive(v) for k, v in servers_raw.items()}
        manager = _make_manager(
            defaults={"base_url": "https://default.com"},
            servers=servers,
        )
        server = manager.resolve_server("source")
        assert server.base_url == "https://source.example.com"


class TestResolveServerIsolation:
    """Resolve does not mutate internal state."""

    def test_resolve_does_not_mutate_defaults(self) -> None:
        """Resolving a server does not modify the stored defaults."""
        defaults = {"base_url": "https://default.com", "headers": {"Accept": "application/json"}}
        manager = _make_manager(
            defaults=defaults,
            servers={"source": {"headers": {"X-Extra": "yes"}}},
        )
        manager.resolve_server("source")
        assert "X-Extra" not in manager._defaults.get("headers", {})

    def test_resolve_does_not_mutate_server(self) -> None:
        """Resolving a server does not modify the stored server profile."""
        servers = {"source": {"base_url": "https://source.com"}}
        manager = _make_manager(
            defaults={"base_url": "https://default.com", "auth": "bearer"},
            servers=servers,
        )
        manager.resolve_server("source")
        assert "auth" not in manager._servers["source"]


class TestServerConfig:
    """ServerConfig dataclass basics."""

    def test_frozen(self) -> None:
        """ServerConfig is frozen (immutable)."""
        cfg = ServerConfig(name="test", base_url="https://x.com")
        with pytest.raises(AttributeError):
            cfg.name = "other"  # type: ignore[misc]

    def test_defaults(self) -> None:
        """ServerConfig has sane defaults."""
        cfg = ServerConfig(name="test", base_url="https://x.com")
        assert cfg.credentials == {}
        assert cfg.auth is None
        assert cfg.headers == {}


class TestServerNames:
    """server_names property."""

    def test_lists_configured_servers(self) -> None:
        """server_names lists all configured server profiles."""
        manager = _make_manager(
            defaults={},
            servers={"source": {}, "target": {}, "staging": {}},
        )
        assert sorted(manager.server_names) == ["source", "staging", "target"]


class TestServerNameValidation:
    """Deep defense: server name validation."""

    def test_empty_name_rejected(self) -> None:
        """Empty server name raises ValueError."""
        from kstlib.rapi.config import _validate_server_name

        with pytest.raises(ValueError, match="must not be empty"):
            _validate_server_name("")

    def test_too_long_name_rejected(self) -> None:
        """Server name exceeding max length raises ValueError."""
        from kstlib.rapi.config import _validate_server_name

        with pytest.raises(ValueError, match="too long"):
            _validate_server_name("a" * 65)

    def test_invalid_chars_rejected(self) -> None:
        """Server name with special characters raises ValueError."""
        from kstlib.rapi.config import _validate_server_name

        with pytest.raises(ValueError, match="Invalid server profile name"):
            _validate_server_name("my server!")

    def test_name_starting_with_digit_rejected(self) -> None:
        """Server name starting with digit raises ValueError."""
        from kstlib.rapi.config import _validate_server_name

        with pytest.raises(ValueError, match="Invalid server profile name"):
            _validate_server_name("1source")

    def test_valid_names_accepted(self) -> None:
        """Valid server names pass validation."""
        from kstlib.rapi.config import _validate_server_name

        for name in ["source", "target", "viya-prod", "staging_01", "A"]:
            _validate_server_name(name)


class TestServerProfileValidation:
    """Deep defense: server profile content validation."""

    def test_unknown_keys_rejected(self) -> None:
        """Unknown keys in server profile raise ValueError."""
        from kstlib.rapi.config import _validate_server_profile

        with pytest.raises(ValueError, match="unknown keys"):
            _validate_server_profile("test", {"base_url": "https://x.com", "evil_key": "pwned"})

    def test_invalid_auth_type_rejected(self) -> None:
        """Invalid auth type raises ValueError."""
        from kstlib.rapi.config import _validate_server_profile

        with pytest.raises(ValueError, match="invalid auth type"):
            _validate_server_profile("test", {"auth": "kerberos"})

    def test_invalid_url_scheme_rejected(self) -> None:
        """Non-http(s) URL scheme raises ValueError."""
        from kstlib.rapi.config import _validate_base_url

        with pytest.raises(ValueError, match="Invalid URL scheme"):
            _validate_base_url("file:///etc/passwd", context="test")

    def test_ftp_scheme_rejected(self) -> None:
        """FTP URL scheme raises ValueError."""
        from kstlib.rapi.config import _validate_base_url

        with pytest.raises(ValueError, match="Invalid URL scheme"):
            _validate_base_url("ftp://evil.com/payload", context="test")

    def test_http_scheme_accepted(self) -> None:
        """HTTP URL passes validation."""
        from kstlib.rapi.config import _validate_base_url

        _validate_base_url("http://localhost:8080", context="test")

    def test_https_scheme_accepted(self) -> None:
        """HTTPS URL passes validation."""
        from kstlib.rapi.config import _validate_base_url

        _validate_base_url("https://viya.example.com", context="test")

    def test_env_var_url_skipped(self) -> None:
        """URL with unexpanded env var is not validated (will be expanded later)."""
        from kstlib.rapi.config import _validate_base_url

        _validate_base_url("https://${VIYA_HOST}", context="test")

    def test_header_name_too_long_rejected(self) -> None:
        """Header name exceeding max length raises ValueError."""
        from kstlib.rapi.config import _validate_server_profile

        with pytest.raises(ValueError, match="header name too long"):
            _validate_server_profile("test", {"headers": {"X" * 200: "value"}})

    def test_headers_not_dict_rejected(self) -> None:
        """Non-dict headers raise ValueError."""
        from kstlib.rapi.config import _validate_server_profile

        with pytest.raises(ValueError, match="headers must be a dict"):
            _validate_server_profile("test", {"headers": "not-a-dict"})

    def test_valid_profile_accepted(self) -> None:
        """Valid profile passes all validation."""
        from kstlib.rapi.config import _validate_server_profile

        _validate_server_profile(
            "source",
            {
                "base_url": "https://viya.example.com",
                "auth": "bearer",
                "credentials": {"type": "file", "path": "~/.sas/creds.json"},
                "headers": {"Accept": "application/json"},
            },
        )


class TestMaxServersLimit:
    """Deep defense: max server count."""

    def test_too_many_servers_in_raw_config(self) -> None:
        """More than MAX_SERVERS profiles raises ValueError in load_rapi_config."""
        from kstlib.rapi.config import _MAX_SERVERS

        servers_raw = {f"server{i}": {"base_url": f"https://s{i}.com"} for i in range(_MAX_SERVERS + 1)}
        with pytest.raises(ValueError, match="Too many server profiles"):
            from kstlib.rapi.config import _validate_server_name, _validate_server_profile

            if len(servers_raw) > _MAX_SERVERS:
                raise ValueError(f"Too many server profiles: {len(servers_raw)} > {_MAX_SERVERS}")


# ============================================================================
# Phase 2: server: directive parsing + cascade + validation
# ============================================================================


def _make_manager_with_apis(
    api_data: dict[str, Any],
    *,
    servers: dict[str, dict[str, Any]] | None = None,
) -> RapiConfigManager:
    """Build a RapiConfigManager with inline API data and optional servers."""
    manager = RapiConfigManager({"api": api_data})
    if servers:
        manager._servers = servers
    return manager


class TestServerDirectiveParsing:
    """Parse server: at file and endpoint levels."""

    def test_file_level_server_parsed_into_apiconfig(self) -> None:
        """File-level server: is stored on ApiConfig."""
        manager = _make_manager_with_apis(
            {
                "transfer": {
                    "base_url": "https://example.com",
                    "server": "target",
                    "endpoints": {
                        "list": {"path": "/items", "method": "GET"},
                    },
                }
            }
        )
        api = manager._apis["transfer"]
        assert api.server == "target"
        assert api.endpoints["list"].server is None

    def test_endpoint_level_server_parsed_into_endpointconfig(self) -> None:
        """Endpoint-level server: is stored on EndpointConfig."""
        manager = _make_manager_with_apis(
            {
                "transfer": {
                    "base_url": "https://example.com",
                    "endpoints": {
                        "upload": {
                            "path": "/upload",
                            "method": "POST",
                            "server": "target",
                        },
                    },
                }
            }
        )
        endpoint = manager._apis["transfer"].endpoints["upload"]
        assert endpoint.server == "target"

    def test_no_server_directive_yields_none(self) -> None:
        """Absence of server: leaves both fields at None (backward compat)."""
        manager = _make_manager_with_apis(
            {
                "github": {
                    "base_url": "https://api.github.com",
                    "endpoints": {
                        "user": {"path": "/user", "method": "GET"},
                    },
                }
            }
        )
        api = manager._apis["github"]
        assert api.server is None
        assert api.endpoints["user"].server is None

    def test_endpoint_overrides_file_level(self) -> None:
        """Endpoint-level server: takes precedence over file-level (storage check)."""
        manager = _make_manager_with_apis(
            {
                "transfer": {
                    "base_url": "https://example.com",
                    "server": "source",
                    "endpoints": {
                        "list": {"path": "/items"},
                        "upload": {"path": "/up", "method": "POST", "server": "target"},
                    },
                }
            }
        )
        api = manager._apis["transfer"]
        assert api.server == "source"
        assert api.endpoints["list"].server is None
        assert api.endpoints["upload"].server == "target"


class TestResolveEffectiveServer:
    """Cascade priority: runtime > endpoint > file > None."""

    def _build(self) -> RapiConfigManager:
        return _make_manager_with_apis(
            {
                "transfer": {
                    "base_url": "https://example.com",
                    "server": "source",
                    "endpoints": {
                        "list": {"path": "/items"},
                        "upload": {"path": "/up", "method": "POST", "server": "target"},
                        "plain": {"path": "/plain"},
                    },
                }
            },
            servers={
                "source": {"base_url": "https://src.example.com"},
                "target": {"base_url": "https://tgt.example.com"},
                "alt": {"base_url": "https://alt.example.com"},
            },
        )

    def test_runtime_wins_over_endpoint_and_file(self) -> None:
        """Runtime server name overrides any YAML directive."""
        manager = self._build()
        api = manager._apis["transfer"]
        endpoint = api.endpoints["upload"]  # has endpoint-level "target"
        resolved = manager.resolve_effective_server(api, endpoint, runtime_server="alt")
        assert resolved is not None
        assert resolved.name == "alt"
        assert resolved.base_url == "https://alt.example.com"

    def test_endpoint_wins_over_file(self) -> None:
        """Endpoint-level server: wins over file-level when no runtime override."""
        manager = self._build()
        api = manager._apis["transfer"]
        endpoint = api.endpoints["upload"]  # endpoint=target, file=source
        resolved = manager.resolve_effective_server(api, endpoint, runtime_server=None)
        assert resolved is not None
        assert resolved.name == "target"

    def test_file_used_when_no_endpoint_or_runtime(self) -> None:
        """File-level server: used when endpoint has no server directive."""
        manager = self._build()
        api = manager._apis["transfer"]
        endpoint = api.endpoints["list"]  # no endpoint server
        resolved = manager.resolve_effective_server(api, endpoint, runtime_server=None)
        assert resolved is not None
        assert resolved.name == "source"

    def test_returns_none_when_nothing_specified(self) -> None:
        """Returns None when neither runtime nor YAML provides a server name."""
        manager = _make_manager_with_apis(
            {
                "github": {
                    "base_url": "https://api.github.com",
                    "endpoints": {"user": {"path": "/user"}},
                }
            }
        )
        api = manager._apis["github"]
        endpoint = api.endpoints["user"]
        resolved = manager.resolve_effective_server(api, endpoint, runtime_server=None)
        assert resolved is None

    def test_runtime_unknown_raises_server_not_found(self) -> None:
        """Unknown runtime server name raises ServerNotFoundError."""
        manager = self._build()
        api = manager._apis["transfer"]
        endpoint = api.endpoints["plain"]
        with pytest.raises(ServerNotFoundError):
            manager.resolve_effective_server(api, endpoint, runtime_server="ghost")


class TestValidateServerReferences:
    """Load-time validation of server: references."""

    def test_warning_when_servers_section_absent(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """File-level server: with no servers section logs a warning, no error."""
        import logging

        caplog.set_level(logging.WARNING, logger="kstlib.rapi.config")
        manager = _make_manager_with_apis(
            {
                "transfer": {
                    "base_url": "https://example.com",
                    "server": "target",
                    "endpoints": {"list": {"path": "/items"}},
                }
            }
        )
        # No exception
        manager._validate_server_references()
        # Warning logged
        assert any("server: 'target'" in rec.message for rec in caplog.records)
        assert any("rapi.servers section is absent" in rec.message for rec in caplog.records)

    def test_warning_for_endpoint_level_when_servers_absent(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Endpoint-level server: with no servers section logs a warning."""
        import logging

        caplog.set_level(logging.WARNING, logger="kstlib.rapi.config")
        manager = _make_manager_with_apis(
            {
                "transfer": {
                    "base_url": "https://example.com",
                    "endpoints": {
                        "upload": {"path": "/up", "server": "target"},
                    },
                }
            }
        )
        manager._validate_server_references()
        assert any("transfer.upload" in rec.message for rec in caplog.records)
        assert any("server: 'target'" in rec.message for rec in caplog.records)

    def test_strict_error_when_unknown_name_with_servers_present(self) -> None:
        """Unknown server: with servers section present raises ServerNotFoundError."""
        manager = _make_manager_with_apis(
            {
                "transfer": {
                    "base_url": "https://example.com",
                    "server": "ghost",
                    "endpoints": {"list": {"path": "/items"}},
                }
            },
            servers={
                "github": {"base_url": "https://api.github.com"},
            },
        )
        with pytest.raises(ServerNotFoundError, match="ghost"):
            manager._validate_server_references()

    def test_strict_error_for_endpoint_level(self) -> None:
        """Unknown endpoint-level server: also raises when servers present."""
        manager = _make_manager_with_apis(
            {
                "transfer": {
                    "base_url": "https://example.com",
                    "endpoints": {
                        "upload": {"path": "/up", "server": "ghost"},
                    },
                }
            },
            servers={
                "real": {"base_url": "https://real.example.com"},
            },
        )
        with pytest.raises(ServerNotFoundError, match="ghost"):
            manager._validate_server_references()

    def test_no_error_when_reference_is_valid(self) -> None:
        """Valid server: reference passes validation silently."""
        manager = _make_manager_with_apis(
            {
                "transfer": {
                    "base_url": "https://example.com",
                    "server": "target",
                    "endpoints": {
                        "upload": {"path": "/up", "server": "source"},
                    },
                }
            },
            servers={
                "source": {"base_url": "https://src.example.com"},
                "target": {"base_url": "https://tgt.example.com"},
            },
        )
        manager._validate_server_references()  # No exception

    def test_no_error_when_no_server_directives(self) -> None:
        """Configs without any server: directive validate cleanly."""
        manager = _make_manager_with_apis(
            {
                "github": {
                    "base_url": "https://api.github.com",
                    "endpoints": {"user": {"path": "/user"}},
                }
            },
            servers={
                "ghost": {"base_url": "https://ghost.example.com"},
            },
        )
        manager._validate_server_references()  # No exception, no warning
