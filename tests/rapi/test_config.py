"""Tests for kstlib.rapi.config module."""

from pathlib import Path

import pytest

from kstlib.rapi.config import (
    ApiConfig,
    EndpointConfig,
    RapiConfigManager,
)
from kstlib.rapi.exceptions import EndpointAmbiguousError, EndpointNotFoundError


class TestEndpointConfig:
    """Tests for EndpointConfig dataclass."""

    def test_basic_creation(self) -> None:
        """Create endpoint config with required fields."""
        config = EndpointConfig(
            name="get_ip",
            api_name="httpbin",
            path="/ip",
        )
        assert config.name == "get_ip"
        assert config.api_name == "httpbin"
        assert config.path == "/ip"
        assert config.method == "GET"
        assert config.query == {}
        assert config.headers == {}
        assert config.body_template is None

    def test_full_ref(self) -> None:
        """Verify full_ref property."""
        config = EndpointConfig(
            name="list_users",
            api_name="azure",
            path="/users",
        )
        assert config.full_ref == "azure.list_users"

    def test_build_path_named_param(self) -> None:
        """Build path with named parameter."""
        config = EndpointConfig(
            name="delay",
            api_name="httpbin",
            path="/delay/{seconds}",
        )
        result = config.build_path(seconds=5)
        assert result == "/delay/5"

    def test_build_path_positional_param(self) -> None:
        """Build path with positional parameter."""
        config = EndpointConfig(
            name="delay",
            api_name="httpbin",
            path="/delay/{0}",
        )
        result = config.build_path(5)
        assert result == "/delay/5"

    def test_build_path_mixed_params(self) -> None:
        """Build path with mixed positional and named parameters."""
        config = EndpointConfig(
            name="resource",
            api_name="api",
            path="/v1/{0}/items/{item_id}",
        )
        result = config.build_path("users", item_id=123)
        assert result == "/v1/users/items/123"

    def test_build_path_multiple_positional(self) -> None:
        """Build path with multiple positional parameters."""
        config = EndpointConfig(
            name="nested",
            api_name="api",
            path="/a/{0}/b/{1}/c",
        )
        result = config.build_path("first", "second")
        assert result == "/a/first/b/second/c"

    def test_build_path_missing_named_param(self) -> None:
        """Raise ValueError for missing named parameter."""
        config = EndpointConfig(
            name="delay",
            api_name="httpbin",
            path="/delay/{seconds}",
        )
        with pytest.raises(ValueError) as exc_info:
            config.build_path()
        assert "seconds" in str(exc_info.value)

    def test_build_path_missing_positional_param(self) -> None:
        """Raise ValueError for missing positional parameter."""
        config = EndpointConfig(
            name="test",
            api_name="api",
            path="/items/{0}/{1}",
        )
        with pytest.raises(ValueError) as exc_info:
            config.build_path("only_one")
        assert "1" in str(exc_info.value)

    def test_build_path_no_params(self) -> None:
        """Build path without parameters."""
        config = EndpointConfig(
            name="get_ip",
            api_name="httpbin",
            path="/ip",
        )
        result = config.build_path()
        assert result == "/ip"

    def test_build_path_positional_as_named_fallback(self) -> None:
        """Use positional arg as fallback for first named param."""
        config = EndpointConfig(
            name="delay",
            api_name="httpbin",
            path="/delay/{seconds}",
        )
        result = config.build_path(10)
        assert result == "/delay/10"


class TestApiConfig:
    """Tests for ApiConfig dataclass."""

    def test_basic_creation(self) -> None:
        """Create API config with required fields."""
        config = ApiConfig(
            name="httpbin",
            base_url="https://httpbin.org",
            endpoints={},
        )
        assert config.name == "httpbin"
        assert config.base_url == "https://httpbin.org"
        assert config.credentials is None
        assert config.auth_type is None
        assert config.headers == {}
        assert config.endpoints == {}

    def test_full_creation(self) -> None:
        """Create API config with all fields."""
        endpoint = EndpointConfig(name="test", api_name="api", path="/test")
        config = ApiConfig(
            name="api",
            base_url="https://api.example.com",
            credentials="my_creds",
            auth_type="bearer",
            headers={"X-Custom": "value"},
            endpoints={"test": endpoint},
        )
        assert config.credentials == "my_creds"
        assert config.auth_type == "bearer"
        assert config.headers == {"X-Custom": "value"}
        assert "test" in config.endpoints


class TestRapiConfigManager:
    """Tests for RapiConfigManager class."""

    def test_load_single_api(self) -> None:
        """Load single API configuration."""
        config = {
            "api": {
                "httpbin": {
                    "base_url": "https://httpbin.org",
                    "endpoints": {
                        "get_ip": {"path": "/ip"},
                    },
                }
            }
        }
        manager = RapiConfigManager(config)

        assert "httpbin" in manager.list_apis()
        assert "httpbin.get_ip" in manager.list_endpoints()

    def test_load_multiple_apis(self) -> None:
        """Load multiple API configurations."""
        config = {
            "api": {
                "httpbin": {
                    "base_url": "https://httpbin.org",
                    "endpoints": {"get_ip": {"path": "/ip"}},
                },
                "jsonplaceholder": {
                    "base_url": "https://jsonplaceholder.typicode.com",
                    "endpoints": {"get_posts": {"path": "/posts"}},
                },
            }
        }
        manager = RapiConfigManager(config)

        assert len(manager.list_apis()) == 2
        assert "httpbin.get_ip" in manager.list_endpoints()
        assert "jsonplaceholder.get_posts" in manager.list_endpoints()

    def test_resolve_full_reference(self) -> None:
        """Resolve endpoint with full reference."""
        config = {
            "api": {
                "httpbin": {
                    "base_url": "https://httpbin.org",
                    "endpoints": {
                        "get_ip": {"path": "/ip"},
                        "post_data": {"path": "/post", "method": "POST"},
                    },
                }
            }
        }
        manager = RapiConfigManager(config)

        api, endpoint = manager.resolve("httpbin.get_ip")

        assert api.name == "httpbin"
        assert api.base_url == "https://httpbin.org"
        assert endpoint.name == "get_ip"
        assert endpoint.path == "/ip"
        assert endpoint.method == "GET"

    def test_resolve_short_reference_unique(self) -> None:
        """Resolve endpoint with unique short reference."""
        config = {
            "api": {
                "httpbin": {
                    "base_url": "https://httpbin.org",
                    "endpoints": {
                        "get_ip": {"path": "/ip"},
                    },
                }
            }
        }
        manager = RapiConfigManager(config)

        api, endpoint = manager.resolve("get_ip")

        assert api.name == "httpbin"
        assert endpoint.name == "get_ip"

    def test_resolve_short_reference_ambiguous(self) -> None:
        """Raise EndpointAmbiguousError for ambiguous short reference."""
        config = {
            "api": {
                "api1": {
                    "base_url": "https://api1.example.com",
                    "endpoints": {"get_data": {"path": "/data"}},
                },
                "api2": {
                    "base_url": "https://api2.example.com",
                    "endpoints": {"get_data": {"path": "/data"}},
                },
            }
        }
        manager = RapiConfigManager(config)

        with pytest.raises(EndpointAmbiguousError) as exc_info:
            manager.resolve("get_data")

        assert "get_data" in str(exc_info.value)
        assert "api1" in exc_info.value.matching_apis
        assert "api2" in exc_info.value.matching_apis

    def test_resolve_not_found_full_ref(self) -> None:
        """Raise EndpointNotFoundError for unknown full reference."""
        config = {
            "api": {
                "httpbin": {
                    "base_url": "https://httpbin.org",
                    "endpoints": {"get_ip": {"path": "/ip"}},
                }
            }
        }
        manager = RapiConfigManager(config)

        with pytest.raises(EndpointNotFoundError):
            manager.resolve("httpbin.unknown")

    def test_resolve_not_found_short_ref(self) -> None:
        """Raise EndpointNotFoundError for unknown short reference."""
        config = {
            "api": {
                "httpbin": {
                    "base_url": "https://httpbin.org",
                    "endpoints": {"get_ip": {"path": "/ip"}},
                }
            }
        }
        manager = RapiConfigManager(config)

        with pytest.raises(EndpointNotFoundError):
            manager.resolve("unknown_endpoint")

    def test_resolve_unknown_api(self) -> None:
        """Raise EndpointNotFoundError for unknown API."""
        config = {
            "api": {
                "httpbin": {
                    "base_url": "https://httpbin.org",
                    "endpoints": {"get_ip": {"path": "/ip"}},
                }
            }
        }
        manager = RapiConfigManager(config)

        with pytest.raises(EndpointNotFoundError):
            manager.resolve("unknown_api.get_ip")

    def test_get_api(self) -> None:
        """Get API config by name."""
        config = {
            "api": {
                "httpbin": {
                    "base_url": "https://httpbin.org",
                    "endpoints": {},
                }
            }
        }
        manager = RapiConfigManager(config)

        api = manager.get_api("httpbin")
        assert api is not None
        assert api.name == "httpbin"

        assert manager.get_api("unknown") is None

    def test_list_endpoints_filtered(self) -> None:
        """List endpoints filtered by API name."""
        config = {
            "api": {
                "api1": {
                    "base_url": "https://api1.com",
                    "endpoints": {"ep1": {"path": "/1"}, "ep2": {"path": "/2"}},
                },
                "api2": {
                    "base_url": "https://api2.com",
                    "endpoints": {"ep3": {"path": "/3"}},
                },
            }
        }
        manager = RapiConfigManager(config)

        endpoints = manager.list_endpoints("api1")
        assert len(endpoints) == 2
        assert "api1.ep1" in endpoints
        assert "api1.ep2" in endpoints
        assert "api2.ep3" not in endpoints

    def test_empty_config(self) -> None:
        """Handle empty configuration gracefully."""
        manager = RapiConfigManager({})
        assert manager.list_apis() == []
        assert manager.list_endpoints() == []

    def test_none_config(self) -> None:
        """Handle None configuration gracefully."""
        manager = RapiConfigManager(None)
        assert manager.list_apis() == []
        assert manager.list_endpoints() == []

    def test_skip_api_without_base_url(self) -> None:
        """Skip APIs without base_url."""
        config = {
            "api": {
                "valid": {
                    "base_url": "https://valid.com",
                    "endpoints": {"ep": {"path": "/"}},
                },
                "invalid": {
                    "endpoints": {"ep": {"path": "/"}},
                },  # Missing base_url
            }
        }
        manager = RapiConfigManager(config)

        assert "valid" in manager.list_apis()
        assert "invalid" not in manager.list_apis()

    def test_endpoint_method_uppercase(self) -> None:
        """Ensure endpoint method is uppercased."""
        config = {
            "api": {
                "test": {
                    "base_url": "https://test.com",
                    "endpoints": {
                        "post": {"path": "/post", "method": "post"},
                    },
                }
            }
        }
        manager = RapiConfigManager(config)

        _, endpoint = manager.resolve("test.post")
        assert endpoint.method == "POST"

    def test_endpoint_with_query_params(self) -> None:
        """Load endpoint with default query parameters."""
        config = {
            "api": {
                "azure": {
                    "base_url": "https://management.azure.com",
                    "endpoints": {
                        "list_subs": {
                            "path": "/subscriptions",
                            "query": {"api-version": "2020-01-01"},
                        },
                    },
                }
            }
        }
        manager = RapiConfigManager(config)

        _, endpoint = manager.resolve("azure.list_subs")
        assert endpoint.query == {"api-version": "2020-01-01"}

    def test_endpoint_with_headers(self) -> None:
        """Load endpoint with custom headers."""
        config = {
            "api": {
                "api": {
                    "base_url": "https://api.com",
                    "endpoints": {
                        "ep": {
                            "path": "/",
                            "headers": {"X-Custom": "value"},
                        },
                    },
                }
            }
        }
        manager = RapiConfigManager(config)

        _, endpoint = manager.resolve("api.ep")
        assert endpoint.headers == {"X-Custom": "value"}

    def test_endpoint_auth_default_true(self) -> None:
        """Endpoint auth defaults to True."""
        config = {
            "api": {
                "api": {
                    "base_url": "https://api.com",
                    "endpoints": {"ep": {"path": "/"}},
                }
            }
        }
        manager = RapiConfigManager(config)

        _, endpoint = manager.resolve("api.ep")
        assert endpoint.auth is True

    def test_endpoint_auth_false(self) -> None:
        """Endpoint can disable auth with auth: false."""
        config = {
            "api": {
                "api": {
                    "base_url": "https://api.com",
                    "credentials": "token",
                    "endpoints": {
                        "public": {"path": "/public", "auth": False},
                        "private": {"path": "/private"},
                    },
                }
            }
        }
        manager = RapiConfigManager(config)

        _, public = manager.resolve("api.public")
        _, private = manager.resolve("api.private")
        assert public.auth is False
        assert private.auth is True

    def test_api_with_credentials(self) -> None:
        """Load API with credentials reference."""
        config = {
            "api": {
                "azure": {
                    "base_url": "https://management.azure.com",
                    "credentials": "azure_cli",
                    "auth_type": "bearer",
                    "endpoints": {"test": {"path": "/"}},
                }
            }
        }
        manager = RapiConfigManager(config)

        api = manager.get_api("azure")
        assert api is not None
        assert api.credentials == "azure_cli"
        assert api.auth_type == "bearer"

    def test_api_with_service_headers(self) -> None:
        """Load API with service-level headers."""
        config = {
            "api": {
                "api": {
                    "base_url": "https://api.com",
                    "headers": {"X-Service": "header"},
                    "endpoints": {"test": {"path": "/"}},
                }
            }
        }
        manager = RapiConfigManager(config)

        api = manager.get_api("api")
        assert api is not None
        assert api.headers == {"X-Service": "header"}


class TestRapiConfigManagerFromFile:
    """Tests for RapiConfigManager.from_file() and related methods."""

    def test_from_file_basic(self, tmp_path: Path) -> None:
        """Load config from a basic *.rapi.yml file."""
        rapi_file = tmp_path / "github.rapi.yml"
        rapi_file.write_text(
            """
name: github
base_url: "https://api.github.com"
endpoints:
  user:
    path: "/user"
  repos:
    path: "/user/repos"
"""
        )

        manager = RapiConfigManager.from_file(str(rapi_file))

        assert "github" in manager.list_apis()
        api = manager.get_api("github")
        assert api is not None
        assert api.base_url == "https://api.github.com"
        assert "user" in api.endpoints
        assert "repos" in api.endpoints

    def test_from_file_with_credentials_inline(self, tmp_path: Path) -> None:
        """Load config with inline credentials definition."""
        rapi_file = tmp_path / "api.rapi.yml"
        rapi_file.write_text(
            """
name: myapi
base_url: "https://api.example.com"
credentials:
  type: env
  var: "API_TOKEN"
auth:
  type: bearer
endpoints:
  test:
    path: "/test"
"""
        )

        manager = RapiConfigManager.from_file(str(rapi_file))

        api = manager.get_api("myapi")
        assert api is not None
        assert api.auth_type == "bearer"
        assert api.credentials == "_rapi_myapi_cred"
        assert "_rapi_myapi_cred" in manager.credentials_config
        assert manager.credentials_config["_rapi_myapi_cred"]["type"] == "env"

    def test_from_file_with_credentials_reference(self, tmp_path: Path) -> None:
        """Load config with credentials as string reference."""
        rapi_file = tmp_path / "api.rapi.yml"
        rapi_file.write_text(
            """
name: myapi
base_url: "https://api.example.com"
credentials: "existing_cred"
auth: bearer
endpoints:
  test:
    path: "/test"
"""
        )

        manager = RapiConfigManager.from_file(str(rapi_file))

        api = manager.get_api("myapi")
        assert api is not None
        assert api.credentials == "existing_cred"
        assert api.auth_type == "bearer"

    def test_from_file_with_headers(self, tmp_path: Path) -> None:
        """Load config with service-level headers."""
        rapi_file = tmp_path / "api.rapi.yml"
        rapi_file.write_text(
            """
name: myapi
base_url: "https://api.example.com"
headers:
  Accept: "application/json"
  X-Custom: "value"
endpoints:
  test:
    path: "/test"
"""
        )

        manager = RapiConfigManager.from_file(str(rapi_file))

        api = manager.get_api("myapi")
        assert api is not None
        assert api.headers == {"Accept": "application/json", "X-Custom": "value"}

    def test_from_file_name_derived_from_filename(self, tmp_path: Path) -> None:
        """Derive API name from filename when not specified."""
        rapi_file = tmp_path / "slack.rapi.yml"
        rapi_file.write_text(
            """
base_url: "https://slack.com/api"
endpoints:
  chat:
    path: "/chat.postMessage"
    method: POST
"""
        )

        manager = RapiConfigManager.from_file(str(rapi_file))

        assert "slack" in manager.list_apis()

    def test_from_file_not_found(self) -> None:
        """Raise FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            RapiConfigManager.from_file("nonexistent.rapi.yml")

    def test_from_file_missing_base_url(self, tmp_path: Path) -> None:
        """Raise ValueError for missing base_url."""
        rapi_file = tmp_path / "invalid.rapi.yml"
        rapi_file.write_text(
            """
name: invalid
endpoints:
  test:
    path: "/test"
"""
        )

        with pytest.raises(ValueError, match="Missing 'base_url'"):
            RapiConfigManager.from_file(str(rapi_file))

    def test_from_file_invalid_format(self, tmp_path: Path) -> None:
        """Raise TypeError for invalid YAML format."""
        rapi_file = tmp_path / "invalid.rapi.yml"
        rapi_file.write_text("just a string, not a dict")

        with pytest.raises(TypeError, match="expected dict"):
            RapiConfigManager.from_file(str(rapi_file))

    def test_from_files_multiple(self, tmp_path: Path) -> None:
        """Load config from multiple files."""
        file1 = tmp_path / "github.rapi.yml"
        file1.write_text(
            """
name: github
base_url: "https://api.github.com"
endpoints:
  user:
    path: "/user"
"""
        )

        file2 = tmp_path / "slack.rapi.yml"
        file2.write_text(
            """
name: slack
base_url: "https://slack.com/api"
endpoints:
  chat:
    path: "/chat.postMessage"
"""
        )

        manager = RapiConfigManager.from_files([file1, file2])

        assert "github" in manager.list_apis()
        assert "slack" in manager.list_apis()
        assert len(manager.source_files) == 2

    def test_discover_finds_files(self, tmp_path: Path) -> None:
        """Discover *.rapi.yml files in directory."""
        file1 = tmp_path / "api1.rapi.yml"
        file1.write_text(
            """
name: api1
base_url: "https://api1.com"
endpoints:
  test:
    path: "/test"
"""
        )

        file2 = tmp_path / "api2.rapi.yml"
        file2.write_text(
            """
name: api2
base_url: "https://api2.com"
endpoints:
  test:
    path: "/test"
"""
        )

        # Create a non-matching file
        other = tmp_path / "other.yml"
        other.write_text("not a rapi file")

        manager = RapiConfigManager.discover(str(tmp_path))

        assert "api1" in manager.list_apis()
        assert "api2" in manager.list_apis()
        assert len(manager.list_apis()) == 2

    def test_discover_no_files_found(self, tmp_path: Path) -> None:
        """Raise FileNotFoundError when no files match."""
        with pytest.raises(FileNotFoundError, match="No RAPI config files found"):
            RapiConfigManager.discover(str(tmp_path))

    def test_discover_directory_not_found(self) -> None:
        """Raise FileNotFoundError for missing directory."""
        with pytest.raises(FileNotFoundError, match="Directory not found"):
            RapiConfigManager.discover("/nonexistent/directory")

    def test_credentials_config_property(self, tmp_path: Path) -> None:
        """Access credentials_config property."""
        rapi_file = tmp_path / "api.rapi.yml"
        rapi_file.write_text(
            """
name: myapi
base_url: "https://api.example.com"
credentials:
  type: sops
  path: "./secrets.sops.json"
  token_path: ".token"
endpoints:
  test:
    path: "/test"
"""
        )

        manager = RapiConfigManager.from_file(str(rapi_file))

        creds = manager.credentials_config
        assert "_rapi_myapi_cred" in creds
        assert creds["_rapi_myapi_cred"]["type"] == "sops"

    def test_source_files_property(self, tmp_path: Path) -> None:
        """Access source_files property."""
        rapi_file = tmp_path / "api.rapi.yml"
        rapi_file.write_text(
            """
name: myapi
base_url: "https://api.example.com"
endpoints:
  test:
    path: "/test"
"""
        )

        manager = RapiConfigManager.from_file(str(rapi_file))

        assert len(manager.source_files) == 1
        assert manager.source_files[0].name == "api.rapi.yml"


class TestLoadRapiConfigWithInclude:
    """Tests for load_rapi_config() with include patterns."""

    def test_include_single_pattern(self, tmp_path: Path) -> None:
        """Include external RAPI files via glob pattern."""
        from unittest import mock

        from kstlib.rapi.config import load_rapi_config

        # Create external RAPI file
        (tmp_path / "github.rapi.yml").write_text(
            """
name: github
base_url: "https://api.github.com"
endpoints:
  user:
    path: "/user"
"""
        )

        # Mock get_config to return our test config
        mock_config = {
            "rapi": {
                "include": [str(tmp_path / "*.rapi.yml")],
                "api": {
                    "inline": {
                        "base_url": "https://inline.example.com",
                        "endpoints": {"test": {"path": "/test"}},
                    }
                },
            }
        }

        with mock.patch("kstlib.config.get_config", return_value=mock_config):
            manager = load_rapi_config()

        # Should have both inline and included APIs
        assert "inline" in manager.apis
        assert "github" in manager.apis

    def test_include_multiple_patterns(self, tmp_path: Path) -> None:
        """Include external RAPI files via multiple patterns."""
        from unittest import mock

        from kstlib.rapi.config import load_rapi_config

        # Create two external RAPI files
        (tmp_path / "api1.rapi.yml").write_text(
            """
name: api1
base_url: "https://api1.com"
endpoints:
  ep1:
    path: "/ep1"
"""
        )
        (tmp_path / "api2.yaml").write_text(
            """
name: api2
base_url: "https://api2.com"
endpoints:
  ep2:
    path: "/ep2"
"""
        )

        mock_config = {
            "rapi": {
                "include": [
                    str(tmp_path / "*.rapi.yml"),
                    str(tmp_path / "*.yaml"),
                ],
            }
        }

        with mock.patch("kstlib.config.get_config", return_value=mock_config):
            manager = load_rapi_config()

        assert "api1" in manager.apis
        assert "api2" in manager.apis

    def test_include_string_pattern(self, tmp_path: Path) -> None:
        """Include with single string pattern (not list)."""
        from unittest import mock

        from kstlib.rapi.config import load_rapi_config

        (tmp_path / "single.rapi.yml").write_text(
            """
name: single
base_url: "https://single.example.com"
endpoints:
  test:
    path: "/test"
"""
        )

        mock_config = {
            "rapi": {
                "include": str(tmp_path / "single.rapi.yml"),
            }
        }

        with mock.patch("kstlib.config.get_config", return_value=mock_config):
            manager = load_rapi_config()

        assert "single" in manager.apis

    def test_include_conflict_keeps_inline(self, tmp_path: Path) -> None:
        """When API name conflicts, inline config takes precedence."""
        from unittest import mock

        from kstlib.rapi.config import load_rapi_config

        # Create external RAPI file with same name as inline
        (tmp_path / "conflict.rapi.yml").write_text(
            """
name: myapi
base_url: "https://external.example.com"
endpoints:
  external_ep:
    path: "/external"
"""
        )

        mock_config = {
            "rapi": {
                "include": [str(tmp_path / "*.rapi.yml")],
                "api": {
                    "myapi": {
                        "base_url": "https://inline.example.com",
                        "endpoints": {"inline_ep": {"path": "/inline"}},
                    }
                },
            }
        }

        with mock.patch("kstlib.config.get_config", return_value=mock_config):
            manager = load_rapi_config()

        # Should keep inline version
        assert "myapi" in manager.apis
        assert manager.apis["myapi"].base_url == "https://inline.example.com"
        assert "inline_ep" in manager.apis["myapi"].endpoints

    def test_include_no_files_found(self, tmp_path: Path) -> None:
        """Include pattern that matches no files is silently ignored."""
        from unittest import mock

        from kstlib.rapi.config import load_rapi_config

        mock_config = {
            "rapi": {
                "include": [str(tmp_path / "nonexistent/*.rapi.yml")],
                "api": {
                    "inline": {
                        "base_url": "https://inline.example.com",
                        "endpoints": {"test": {"path": "/test"}},
                    }
                },
            }
        }

        with mock.patch("kstlib.config.get_config", return_value=mock_config):
            # Should not raise, just return inline config
            manager = load_rapi_config()

        assert "inline" in manager.apis

    def test_include_merges_credentials(self, tmp_path: Path) -> None:
        """Include external files merges their credentials."""
        from unittest import mock

        from kstlib.rapi.config import load_rapi_config

        (tmp_path / "withcreds.rapi.yml").write_text(
            """
name: withcreds
base_url: "https://api.example.com"
credentials:
  type: env
  var: MY_TOKEN
endpoints:
  test:
    path: "/test"
"""
        )

        mock_config = {
            "rapi": {
                "include": [str(tmp_path / "*.rapi.yml")],
            }
        }

        with mock.patch("kstlib.config.get_config", return_value=mock_config):
            manager = load_rapi_config()

        assert "withcreds" in manager.apis
        # Credentials should be auto-generated
        assert "_rapi_withcreds_cred" in manager.credentials_config


class TestResolveIncludePatterns:
    """Tests for _resolve_include_patterns helper function."""

    def test_string_pattern(self, tmp_path: Path) -> None:
        """Resolve single string pattern."""
        from kstlib.rapi.config import _resolve_include_patterns

        (tmp_path / "test.rapi.yml").write_text("name: test\n")

        result = _resolve_include_patterns(str(tmp_path / "test.rapi.yml"))

        assert len(result) == 1
        assert result[0].name == "test.rapi.yml"

    def test_list_of_patterns(self, tmp_path: Path) -> None:
        """Resolve list of patterns."""
        from kstlib.rapi.config import _resolve_include_patterns

        (tmp_path / "a.rapi.yml").write_text("name: a\n")
        (tmp_path / "b.rapi.yml").write_text("name: b\n")

        result = _resolve_include_patterns([str(tmp_path / "*.rapi.yml")])

        assert len(result) == 2

    def test_no_matches(self, tmp_path: Path) -> None:
        """Return empty list for no matches."""
        from kstlib.rapi.config import _resolve_include_patterns

        result = _resolve_include_patterns([str(tmp_path / "nonexistent/*.yml")])

        assert result == []


class TestHmacConfig:
    """Tests for HmacConfig dataclass and validation."""

    def test_default_values(self) -> None:
        """HmacConfig uses sensible defaults."""
        from kstlib.rapi.config import HmacConfig

        config = HmacConfig()

        assert config.algorithm == "sha256"
        assert config.timestamp_field == "timestamp"
        assert config.nonce_field is None
        assert config.signature_field == "signature"
        assert config.signature_format == "hex"
        assert config.key_header is None
        assert config.sign_body is False

    def test_sha512_base64(self) -> None:
        """Create config with SHA512 and base64 format."""
        from kstlib.rapi.config import HmacConfig

        config = HmacConfig(
            algorithm="sha512",
            signature_format="base64",
            nonce_field="nonce",
            key_header="API-Key",
        )

        assert config.algorithm == "sha512"
        assert config.signature_format == "base64"
        assert config.nonce_field == "nonce"
        assert config.key_header == "API-Key"

    def test_invalid_algorithm_rejected(self) -> None:
        """Reject invalid HMAC algorithm."""
        from kstlib.rapi.config import HmacConfig

        with pytest.raises(ValueError, match="Invalid HMAC algorithm"):
            HmacConfig(algorithm="md5")

        with pytest.raises(ValueError, match="Invalid HMAC algorithm"):
            HmacConfig(algorithm="sha1")

        with pytest.raises(ValueError, match="Invalid HMAC algorithm"):
            HmacConfig(algorithm="")

    def test_invalid_signature_format_rejected(self) -> None:
        """Reject invalid signature format."""
        from kstlib.rapi.config import HmacConfig

        with pytest.raises(ValueError, match="Invalid signature format"):
            HmacConfig(signature_format="binary")

        with pytest.raises(ValueError, match="Invalid signature format"):
            HmacConfig(signature_format="")

    def test_field_name_too_long_rejected(self) -> None:
        """Reject field names exceeding max length."""
        from kstlib.rapi.config import HmacConfig

        long_name = "x" * 100

        with pytest.raises(ValueError, match="timestamp_field too long"):
            HmacConfig(timestamp_field=long_name)

        with pytest.raises(ValueError, match="signature_field too long"):
            HmacConfig(signature_field=long_name)

        with pytest.raises(ValueError, match="nonce_field too long"):
            HmacConfig(nonce_field=long_name)

    def test_header_name_too_long_rejected(self) -> None:
        """Reject header names exceeding max length."""
        from kstlib.rapi.config import HmacConfig

        long_header = "X-" + "A" * 200

        with pytest.raises(ValueError, match="key_header too long"):
            HmacConfig(key_header=long_header)

    def test_immutable(self) -> None:
        """HmacConfig is immutable (frozen)."""
        from kstlib.rapi.config import HmacConfig

        config = HmacConfig()

        with pytest.raises(AttributeError):
            config.algorithm = "sha512"  # type: ignore[misc]

    def test_from_yaml_auth_section(self, tmp_path: Path) -> None:
        """Parse HmacConfig from YAML auth section."""
        rapi_file = tmp_path / "api.rapi.yml"
        rapi_file.write_text(
            """
name: exchange
base_url: "https://api.exchange.com"
auth:
  type: hmac
  algorithm: sha512
  timestamp_field: ts
  nonce_field: null
  signature_field: sig
  signature_format: base64
  key_header: X-API-Key
  sign_body: false
endpoints:
  test:
    path: "/test"
"""
        )

        manager = RapiConfigManager.from_file(str(rapi_file))

        api = manager.get_api("exchange")
        assert api is not None
        assert api.hmac_config is not None
        assert api.hmac_config.algorithm == "sha512"
        assert api.hmac_config.timestamp_field == "ts"
        assert api.hmac_config.signature_field == "sig"
        assert api.hmac_config.signature_format == "base64"
        assert api.hmac_config.key_header == "X-API-Key"

    def test_from_yaml_invalid_algorithm_rejected(self, tmp_path: Path) -> None:
        """Reject invalid algorithm in YAML."""
        rapi_file = tmp_path / "api.rapi.yml"
        rapi_file.write_text(
            """
name: api
base_url: "https://api.example.com"
auth:
  type: hmac
  algorithm: md5
endpoints:
  test:
    path: "/test"
"""
        )

        with pytest.raises(ValueError, match="Invalid HMAC algorithm"):
            RapiConfigManager.from_file(str(rapi_file))
