"""Tests for kstlib.rapi.config module."""

from pathlib import Path

import pytest

from kstlib.rapi.config import (
    ApiConfig,
    EndpointConfig,
    RapiConfigManager,
    SafeguardConfig,
    _expand_env_vars,
    _expand_env_vars_recursive,
)
from kstlib.rapi.exceptions import (
    EndpointAmbiguousError,
    EndpointNotFoundError,
    EnvVarError,
    SafeguardMissingError,
)


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

    def test_safeguard_none_by_default(self) -> None:
        """Safeguard is None by default."""
        config = EndpointConfig(
            name="test",
            api_name="api",
            path="/test",
        )
        assert config.safeguard is None

    def test_safeguard_set(self) -> None:
        """Set safeguard string on endpoint."""
        config = EndpointConfig(
            name="delete",
            api_name="api",
            path="/users/{userId}",
            method="DELETE",
            safeguard="DELETE USER {userId}",
        )
        assert config.safeguard == "DELETE USER {userId}"

    def test_safeguard_too_long_rejected(self) -> None:
        """Reject safeguard string exceeding max length."""
        long_safeguard = "X" * 200
        with pytest.raises(ValueError, match="safeguard too long"):
            EndpointConfig(
                name="test",
                api_name="api",
                path="/test",
                safeguard=long_safeguard,
            )

    def test_safeguard_invalid_chars_rejected(self) -> None:
        """Reject safeguard with invalid characters."""
        with pytest.raises(ValueError, match="invalid characters"):
            EndpointConfig(
                name="test",
                api_name="api",
                path="/test",
                safeguard="DELETE; DROP TABLE users",
            )

        with pytest.raises(ValueError, match="invalid characters"):
            EndpointConfig(
                name="test",
                api_name="api",
                path="/test",
                safeguard="<script>alert('xss')</script>",
            )

    def test_safeguard_valid_chars(self) -> None:
        """Accept safeguard with valid characters."""
        config = EndpointConfig(
            name="test",
            api_name="api",
            path="/test",
            safeguard="DELETE USER {userId}/account-123_test",
        )
        assert config.safeguard == "DELETE USER {userId}/account-123_test"

    def test_build_safeguard_with_kwargs(self) -> None:
        """Build safeguard with keyword arguments."""
        config = EndpointConfig(
            name="delete",
            api_name="api",
            path="/users/{userId}",
            method="DELETE",
            safeguard="DELETE USER {userId}",
        )
        result = config.build_safeguard(userId="abc123")
        assert result == "DELETE USER abc123"

    def test_build_safeguard_with_positional(self) -> None:
        """Build safeguard with positional arguments."""
        config = EndpointConfig(
            name="delete",
            api_name="api",
            path="/users/{0}",
            method="DELETE",
            safeguard="DELETE USER {0}",
        )
        result = config.build_safeguard("user-456")
        assert result == "DELETE USER user-456"

    def test_build_safeguard_none_returns_none(self) -> None:
        """Build safeguard returns None when no safeguard configured."""
        config = EndpointConfig(
            name="get",
            api_name="api",
            path="/test",
        )
        result = config.build_safeguard()
        assert result is None

    def test_build_safeguard_multiple_params(self) -> None:
        """Build safeguard with multiple parameters."""
        config = EndpointConfig(
            name="delete_item",
            api_name="api",
            path="/users/{userId}/items/{itemId}",
            method="DELETE",
            safeguard="DELETE ITEM {itemId} FROM USER {userId}",
        )
        result = config.build_safeguard(userId="user1", itemId="item2")
        assert result == "DELETE ITEM item2 FROM USER user1"


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


class TestSafeguardConfig:
    """Tests for SafeguardConfig dataclass."""

    def test_default_values(self) -> None:
        """SafeguardConfig uses sensible defaults."""
        config = SafeguardConfig()

        assert "DELETE" in config.required_methods
        assert "PUT" in config.required_methods
        assert "GET" not in config.required_methods
        assert "POST" not in config.required_methods
        assert "PATCH" not in config.required_methods

    def test_custom_methods(self) -> None:
        """Create config with custom required methods."""
        config = SafeguardConfig(required_methods=frozenset({"DELETE"}))

        assert "DELETE" in config.required_methods
        assert "PUT" not in config.required_methods

    def test_empty_methods(self) -> None:
        """Create config with no required methods (opt-out)."""
        config = SafeguardConfig(required_methods=frozenset())

        assert len(config.required_methods) == 0

    def test_immutable(self) -> None:
        """SafeguardConfig is immutable (frozen)."""
        config = SafeguardConfig()

        with pytest.raises(AttributeError):
            config.required_methods = frozenset()  # type: ignore[misc]


class TestSafeguardValidation:
    """Tests for safeguard validation at config load time."""

    def test_delete_without_safeguard_rejected(self) -> None:
        """Reject DELETE endpoint without safeguard."""
        config = {
            "api": {
                "admin": {
                    "base_url": "https://admin.example.com",
                    "endpoints": {
                        "delete_user": {
                            "path": "/users/{userId}",
                            "method": "DELETE",
                            # No safeguard!
                        },
                    },
                }
            }
        }

        with pytest.raises(SafeguardMissingError) as exc_info:
            RapiConfigManager(config)

        assert "admin.delete_user" in str(exc_info.value)
        assert "DELETE" in str(exc_info.value)

    def test_put_without_safeguard_rejected(self) -> None:
        """Reject PUT endpoint without safeguard."""
        config = {
            "api": {
                "api": {
                    "base_url": "https://api.example.com",
                    "endpoints": {
                        "replace_data": {
                            "path": "/data/{id}",
                            "method": "PUT",
                            # No safeguard!
                        },
                    },
                }
            }
        }

        with pytest.raises(SafeguardMissingError) as exc_info:
            RapiConfigManager(config)

        assert "PUT" in str(exc_info.value)

    def test_delete_with_safeguard_accepted(self) -> None:
        """Accept DELETE endpoint with safeguard."""
        config = {
            "api": {
                "admin": {
                    "base_url": "https://admin.example.com",
                    "endpoints": {
                        "delete_user": {
                            "path": "/users/{userId}",
                            "method": "DELETE",
                            "safeguard": "DELETE USER {userId}",
                        },
                    },
                }
            }
        }

        manager = RapiConfigManager(config)

        _, endpoint = manager.resolve("admin.delete_user")
        assert endpoint.safeguard == "DELETE USER {userId}"

    def test_get_without_safeguard_accepted(self) -> None:
        """Accept GET endpoint without safeguard (not dangerous)."""
        config = {
            "api": {
                "api": {
                    "base_url": "https://api.example.com",
                    "endpoints": {
                        "get_data": {"path": "/data", "method": "GET"},
                    },
                }
            }
        }

        manager = RapiConfigManager(config)

        _, endpoint = manager.resolve("api.get_data")
        assert endpoint.safeguard is None

    def test_post_without_safeguard_accepted(self) -> None:
        """Accept POST endpoint without safeguard (not in default list)."""
        config = {
            "api": {
                "api": {
                    "base_url": "https://api.example.com",
                    "endpoints": {
                        "create_data": {"path": "/data", "method": "POST"},
                    },
                }
            }
        }

        manager = RapiConfigManager(config)

        _, endpoint = manager.resolve("api.create_data")
        assert endpoint.safeguard is None

    def test_custom_safeguard_config_no_requirements(self) -> None:
        """Accept DELETE without safeguard when custom config has no requirements."""
        config = {
            "api": {
                "api": {
                    "base_url": "https://api.example.com",
                    "endpoints": {
                        "delete": {"path": "/data", "method": "DELETE"},
                    },
                }
            }
        }

        # Custom config with no required methods
        safeguard_config = SafeguardConfig(required_methods=frozenset())
        manager = RapiConfigManager(config, safeguard_config=safeguard_config)

        _, endpoint = manager.resolve("api.delete")
        assert endpoint.safeguard is None

    def test_safeguard_from_yaml(self, tmp_path: Path) -> None:
        """Load safeguard from YAML file."""
        rapi_file = tmp_path / "api.rapi.yml"
        rapi_file.write_text(
            """
name: admin
base_url: "https://admin.example.com"
endpoints:
  delete_user:
    path: "/users/{userId}"
    method: DELETE
    safeguard: "DELETE USER {userId}"
  get_user:
    path: "/users/{userId}"
    method: GET
"""
        )

        manager = RapiConfigManager.from_file(str(rapi_file))

        _, delete_ep = manager.resolve("admin.delete_user")
        _, get_ep = manager.resolve("admin.get_user")

        assert delete_ep.safeguard == "DELETE USER {userId}"
        assert get_ep.safeguard is None

    def test_safeguard_missing_in_yaml_rejected(self, tmp_path: Path) -> None:
        """Reject YAML file with DELETE endpoint missing safeguard."""
        rapi_file = tmp_path / "api.rapi.yml"
        rapi_file.write_text(
            """
name: admin
base_url: "https://admin.example.com"
endpoints:
  delete_user:
    path: "/users/{userId}"
    method: DELETE
"""
        )

        with pytest.raises(SafeguardMissingError):
            RapiConfigManager.from_file(str(rapi_file))


class TestEnvVarExpansion:
    """Tests for environment variable expansion in config."""

    def test_expand_simple_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Expand simple ${VAR} syntax."""
        monkeypatch.setenv("TEST_HOST", "example.com")
        result = _expand_env_vars("https://${TEST_HOST}/api")
        assert result == "https://example.com/api"

    def test_expand_var_with_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Expand ${VAR:-default} when var is not set."""
        monkeypatch.delenv("MISSING_VAR", raising=False)
        result = _expand_env_vars("https://${MISSING_VAR:-localhost}/api")
        assert result == "https://localhost/api"

    def test_expand_var_with_default_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Expand ${VAR:-default} when var IS set (use var value)."""
        monkeypatch.setenv("SET_VAR", "actual-value")
        result = _expand_env_vars("https://${SET_VAR:-default}/api")
        assert result == "https://actual-value/api"

    def test_expand_missing_var_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Raise EnvVarError when required var is not set."""
        monkeypatch.delenv("REQUIRED_VAR", raising=False)
        with pytest.raises(EnvVarError) as exc_info:
            _expand_env_vars("https://${REQUIRED_VAR}/api")
        assert "REQUIRED_VAR" in str(exc_info.value)

    def test_expand_missing_var_with_source(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """EnvVarError includes source file in message."""
        monkeypatch.delenv("MISSING", raising=False)
        with pytest.raises(EnvVarError) as exc_info:
            _expand_env_vars("${MISSING}", source="test.rapi.yml")
        assert "test.rapi.yml" in str(exc_info.value)

    def test_expand_multiple_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Expand multiple variables in one string."""
        monkeypatch.setenv("HOST", "api.example.com")
        monkeypatch.setenv("PORT", "8080")
        result = _expand_env_vars("https://${HOST}:${PORT}/v1")
        assert result == "https://api.example.com:8080/v1"

    def test_expand_empty_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Expand ${VAR:-} with empty default."""
        monkeypatch.delenv("OPTIONAL", raising=False)
        result = _expand_env_vars("prefix${OPTIONAL:-}suffix")
        assert result == "prefixsuffix"

    def test_no_expansion_needed(self) -> None:
        """String without ${} is returned unchanged."""
        result = _expand_env_vars("https://example.com/api")
        assert result == "https://example.com/api"

    def test_recursive_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Recursively expand vars in dict values."""
        monkeypatch.setenv("API_HOST", "api.test.com")
        monkeypatch.setenv("API_TOKEN", "secret123")
        data = {
            "base_url": "https://${API_HOST}",
            "credentials": {
                "token": "${API_TOKEN}",
            },
            "count": 42,
        }
        result = _expand_env_vars_recursive(data)
        assert result["base_url"] == "https://api.test.com"
        assert result["credentials"]["token"] == "secret123"
        assert result["count"] == 42

    def test_recursive_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Recursively expand vars in list items."""
        monkeypatch.setenv("ITEM", "expanded")
        data = ["${ITEM}", "static", {"nested": "${ITEM}"}]
        result = _expand_env_vars_recursive(data)
        assert result[0] == "expanded"
        assert result[1] == "static"
        assert result[2]["nested"] == "expanded"

    def test_recursive_preserves_types(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-string types are preserved."""
        monkeypatch.setenv("VAR", "value")
        data = {
            "string": "${VAR}",
            "int": 123,
            "float": 3.14,
            "bool": True,
            "none": None,
        }
        result = _expand_env_vars_recursive(data)
        assert result["string"] == "value"
        assert result["int"] == 123
        assert result["float"] == 3.14
        assert result["bool"] is True
        assert result["none"] is None


class TestEnvVarExpansionInYaml:
    """Tests for env var expansion when loading YAML files."""

    def test_base_url_expansion(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Expand env var in base_url from YAML file."""
        monkeypatch.setenv("VIYA_HOST", "viya.example.com")
        rapi_file = tmp_path / "api.rapi.yml"
        rapi_file.write_text(
            """
name: viya
base_url: "https://${VIYA_HOST}"
endpoints:
  root:
    path: /
    method: GET
"""
        )

        safeguard_config = SafeguardConfig(required_methods=frozenset())
        manager = RapiConfigManager.from_file(str(rapi_file), safeguard_config=safeguard_config)
        api, _ = manager.resolve("viya.root")
        assert api.base_url == "https://viya.example.com"

    def test_credentials_path_expansion(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Expand env var in credentials path from YAML file."""
        monkeypatch.setenv("CRED_PATH", "/etc/secrets")
        rapi_file = tmp_path / "api.rapi.yml"
        rapi_file.write_text(
            """
name: secure
base_url: "https://api.example.com"
credentials:
  type: file
  path: "${CRED_PATH}/token.json"
endpoints:
  root:
    path: /
    method: GET
"""
        )

        safeguard_config = SafeguardConfig(required_methods=frozenset())
        manager = RapiConfigManager.from_file(str(rapi_file), safeguard_config=safeguard_config)
        assert manager is not None

    def test_missing_env_var_in_yaml_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Raise EnvVarError when env var is missing in YAML."""
        monkeypatch.delenv("UNDEFINED_HOST", raising=False)
        rapi_file = tmp_path / "api.rapi.yml"
        rapi_file.write_text(
            """
name: broken
base_url: "https://${UNDEFINED_HOST}"
endpoints:
  root:
    path: /
"""
        )

        with pytest.raises(EnvVarError) as exc_info:
            RapiConfigManager.from_file(str(rapi_file))
        assert "UNDEFINED_HOST" in str(exc_info.value)
        assert str(rapi_file) in str(exc_info.value)

    def test_default_value_in_yaml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Use default value when env var not set in YAML."""
        monkeypatch.delenv("OPTIONAL_PORT", raising=False)
        rapi_file = tmp_path / "api.rapi.yml"
        rapi_file.write_text(
            """
name: optional
base_url: "https://api.example.com:${OPTIONAL_PORT:-443}"
endpoints:
  root:
    path: /
    method: GET
"""
        )

        safeguard_config = SafeguardConfig(required_methods=frozenset())
        manager = RapiConfigManager.from_file(str(rapi_file), safeguard_config=safeguard_config)
        api, _ = manager.resolve("optional.root")
        assert api.base_url == "https://api.example.com:443"


class TestDefaultsInheritance:
    """Tests for defaults inheritance from kstlib.conf.yml to included files."""

    def test_inherit_base_url(self, tmp_path: Path) -> None:
        """Inherit base_url from defaults."""
        rapi_file = tmp_path / "api.rapi.yml"
        rapi_file.write_text(
            """
name: myapi
endpoints:
  root:
    path: /
    method: GET
"""
        )

        defaults = {"base_url": "https://inherited.example.com"}
        safeguard_config = SafeguardConfig(required_methods=frozenset())
        manager = RapiConfigManager.from_file(
            str(rapi_file),
            safeguard_config=safeguard_config,
            defaults=defaults,
        )

        api, _ = manager.resolve("myapi.root")
        assert api.base_url == "https://inherited.example.com"

    def test_override_base_url(self, tmp_path: Path) -> None:
        """File base_url overrides defaults."""
        rapi_file = tmp_path / "api.rapi.yml"
        rapi_file.write_text(
            """
name: myapi
base_url: "https://file-wins.example.com"
endpoints:
  root:
    path: /
    method: GET
"""
        )

        defaults = {"base_url": "https://default.example.com"}
        safeguard_config = SafeguardConfig(required_methods=frozenset())
        manager = RapiConfigManager.from_file(
            str(rapi_file),
            safeguard_config=safeguard_config,
            defaults=defaults,
        )

        api, _ = manager.resolve("myapi.root")
        assert api.base_url == "https://file-wins.example.com"

    def test_inherit_credentials(self, tmp_path: Path) -> None:
        """Inherit credentials from defaults."""
        rapi_file = tmp_path / "api.rapi.yml"
        rapi_file.write_text(
            """
name: myapi
base_url: "https://api.example.com"
endpoints:
  root:
    path: /
    method: GET
"""
        )

        defaults = {
            "credentials": {
                "type": "file",
                "path": "~/.creds/token.json",
                "token_path": ".access_token",
            }
        }
        safeguard_config = SafeguardConfig(required_methods=frozenset())
        manager = RapiConfigManager.from_file(
            str(rapi_file),
            safeguard_config=safeguard_config,
            defaults=defaults,
        )

        api, _ = manager.resolve("myapi.root")
        assert api.credentials is not None

    def test_inherit_auth(self, tmp_path: Path) -> None:
        """Inherit auth from defaults."""
        rapi_file = tmp_path / "api.rapi.yml"
        rapi_file.write_text(
            """
name: myapi
base_url: "https://api.example.com"
endpoints:
  root:
    path: /
    method: GET
"""
        )

        defaults = {"auth": "bearer"}
        safeguard_config = SafeguardConfig(required_methods=frozenset())
        manager = RapiConfigManager.from_file(
            str(rapi_file),
            safeguard_config=safeguard_config,
            defaults=defaults,
        )

        api, _ = manager.resolve("myapi.root")
        assert api.auth_type == "bearer"

    def test_merge_headers(self, tmp_path: Path) -> None:
        """Headers are merged (file overrides default on conflict)."""
        rapi_file = tmp_path / "api.rapi.yml"
        rapi_file.write_text(
            """
name: myapi
base_url: "https://api.example.com"
headers:
  Accept: application/vnd.custom+json
  X-Custom: from-file
endpoints:
  root:
    path: /
    method: GET
"""
        )

        defaults = {
            "headers": {
                "Accept": "application/json",
                "X-Default": "from-defaults",
            }
        }
        safeguard_config = SafeguardConfig(required_methods=frozenset())
        manager = RapiConfigManager.from_file(
            str(rapi_file),
            safeguard_config=safeguard_config,
            defaults=defaults,
        )

        api, _ = manager.resolve("myapi.root")
        assert api.headers["Accept"] == "application/vnd.custom+json"
        assert api.headers["X-Default"] == "from-defaults"
        assert api.headers["X-Custom"] == "from-file"

    def test_defaults_with_env_vars(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Environment variables in defaults are expanded."""
        monkeypatch.setenv("DEFAULT_HOST", "env-host.example.com")
        rapi_file = tmp_path / "api.rapi.yml"
        rapi_file.write_text(
            """
name: myapi
endpoints:
  root:
    path: /
    method: GET
"""
        )

        defaults = {"base_url": "https://${DEFAULT_HOST}"}
        safeguard_config = SafeguardConfig(required_methods=frozenset())
        manager = RapiConfigManager.from_file(
            str(rapi_file),
            safeguard_config=safeguard_config,
            defaults=defaults,
        )

        api, _ = manager.resolve("myapi.root")
        assert api.base_url == "https://env-host.example.com"

    def test_multiple_files_share_defaults(self, tmp_path: Path) -> None:
        """Multiple files share the same defaults."""
        file1 = tmp_path / "api1.rapi.yml"
        file1.write_text(
            """
name: api1
endpoints:
  root:
    path: /api1
    method: GET
"""
        )

        file2 = tmp_path / "api2.rapi.yml"
        file2.write_text(
            """
name: api2
endpoints:
  root:
    path: /api2
    method: GET
"""
        )

        defaults = {"base_url": "https://shared.example.com", "auth": "bearer"}
        safeguard_config = SafeguardConfig(required_methods=frozenset())
        manager = RapiConfigManager.from_files(
            [str(file1), str(file2)],
            safeguard_config=safeguard_config,
            defaults=defaults,
        )

        api1, _ = manager.resolve("api1.root")
        api2, _ = manager.resolve("api2.root")
        assert api1.base_url == "https://shared.example.com"
        assert api2.base_url == "https://shared.example.com"
        assert api1.auth_type == "bearer"
        assert api2.auth_type == "bearer"

    def test_no_defaults(self, tmp_path: Path) -> None:
        """File works without defaults (backward compatible)."""
        rapi_file = tmp_path / "api.rapi.yml"
        rapi_file.write_text(
            """
name: standalone
base_url: "https://standalone.example.com"
endpoints:
  root:
    path: /
    method: GET
"""
        )

        safeguard_config = SafeguardConfig(required_methods=frozenset())
        manager = RapiConfigManager.from_file(
            str(rapi_file),
            safeguard_config=safeguard_config,
            defaults=None,
        )

        api, _ = manager.resolve("standalone.root")
        assert api.base_url == "https://standalone.example.com"

    def test_merge_credentials_partial(self, tmp_path: Path) -> None:
        """Partial credentials override in file."""
        rapi_file = tmp_path / "api.rapi.yml"
        rapi_file.write_text(
            """
name: myapi
base_url: "https://api.example.com"
credentials:
  path: ~/.different/token.json
endpoints:
  root:
    path: /
    method: GET
"""
        )

        defaults = {
            "credentials": {
                "type": "file",
                "path": "~/.default/token.json",
                "token_path": ".access_token",
            }
        }
        safeguard_config = SafeguardConfig(required_methods=frozenset())
        manager = RapiConfigManager.from_file(
            str(rapi_file),
            safeguard_config=safeguard_config,
            defaults=defaults,
        )

        api, _ = manager.resolve("myapi.root")
        assert api.credentials is not None


class TestNestedIncludes:
    """Tests for nested include support in .rapi.yml files."""

    def test_include_relative_file(self, tmp_path: Path) -> None:
        """Include a relative file from within a rapi file."""
        # Create root file with include
        root_file = tmp_path / "root.rapi.yml"
        root_file.write_text(
            """
name: myapi
base_url: "https://api.example.com"
include:
  - "./endpoints.rapi.yml"
endpoints:
  root:
    path: /
    method: GET
"""
        )

        # Create included file (no base_url needed, endpoints only)
        endpoints_file = tmp_path / "endpoints.rapi.yml"
        endpoints_file.write_text(
            """
name: ignored
base_url: "https://ignored.com"
endpoints:
  users:
    path: /users
    method: GET
  posts:
    path: /posts
    method: GET
"""
        )

        safeguard_config = SafeguardConfig(required_methods=frozenset())
        manager = RapiConfigManager.from_file(str(root_file), safeguard_config=safeguard_config)

        # Should have root endpoint + included endpoints
        assert "myapi" in manager.list_apis()
        endpoints = manager.list_endpoints("myapi")
        assert "myapi.root" in endpoints
        assert "myapi.users" in endpoints
        assert "myapi.posts" in endpoints

    def test_include_multiple_files(self, tmp_path: Path) -> None:
        """Include multiple files from within a rapi file."""
        root_file = tmp_path / "root.rapi.yml"
        root_file.write_text(
            """
name: annotations
base_url: "https://api.example.com"
include:
  - "./annotations.rapi.yml"
  - "./members.rapi.yml"
endpoints:
  root:
    path: /
    method: GET
"""
        )

        (tmp_path / "annotations.rapi.yml").write_text(
            """
name: ignored
base_url: "https://ignored.com"
endpoints:
  create:
    path: /annotations
    method: POST
"""
        )

        (tmp_path / "members.rapi.yml").write_text(
            """
name: ignored
base_url: "https://ignored.com"
endpoints:
  list-members:
    path: /members
    method: GET
"""
        )

        safeguard_config = SafeguardConfig(required_methods=frozenset())
        manager = RapiConfigManager.from_file(str(root_file), safeguard_config=safeguard_config)

        endpoints = manager.list_endpoints("annotations")
        assert "annotations.root" in endpoints
        assert "annotations.create" in endpoints
        assert "annotations.list-members" in endpoints

    def test_include_with_glob_pattern(self, tmp_path: Path) -> None:
        """Include files using glob pattern."""
        root_file = tmp_path / "root.rapi.yml"
        root_file.write_text(
            """
name: myapi
base_url: "https://api.example.com"
include:
  - "./*.endpoints.rapi.yml"
endpoints:
  root:
    path: /
    method: GET
"""
        )

        (tmp_path / "users.endpoints.rapi.yml").write_text(
            """
name: ignored
base_url: "https://ignored.com"
endpoints:
  users:
    path: /users
    method: GET
"""
        )

        (tmp_path / "posts.endpoints.rapi.yml").write_text(
            """
name: ignored
base_url: "https://ignored.com"
endpoints:
  posts:
    path: /posts
    method: GET
"""
        )

        safeguard_config = SafeguardConfig(required_methods=frozenset())
        manager = RapiConfigManager.from_file(str(root_file), safeguard_config=safeguard_config)

        endpoints = manager.list_endpoints("myapi")
        assert "myapi.root" in endpoints
        assert "myapi.users" in endpoints
        assert "myapi.posts" in endpoints

    def test_no_include_backward_compatible(self, tmp_path: Path) -> None:
        """Files without include work as before."""
        rapi_file = tmp_path / "simple.rapi.yml"
        rapi_file.write_text(
            """
name: simple
base_url: "https://api.example.com"
endpoints:
  test:
    path: /test
    method: GET
"""
        )

        safeguard_config = SafeguardConfig(required_methods=frozenset())
        manager = RapiConfigManager.from_file(str(rapi_file), safeguard_config=safeguard_config)

        assert "simple" in manager.list_apis()
        assert "simple.test" in manager.list_endpoints()


class TestEndpointCollisionDetection:
    """Tests for endpoint collision detection."""

    def test_collision_warning_non_strict(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """Warn about endpoint collision in non-strict mode."""
        import logging

        file1 = tmp_path / "api1.rapi.yml"
        file1.write_text(
            """
name: myapi
base_url: "https://api.example.com"
endpoints:
  create:
    path: /create-v1
    method: GET
"""
        )

        file2 = tmp_path / "api2.rapi.yml"
        file2.write_text(
            """
name: myapi
base_url: "https://api.example.com"
endpoints:
  create:
    path: /create-v2
    method: GET
"""
        )

        safeguard_config = SafeguardConfig(required_methods=frozenset())
        with caplog.at_level(logging.WARNING):
            manager = RapiConfigManager.from_files(
                [str(file1), str(file2)],
                safeguard_config=safeguard_config,
                strict=False,
            )

        assert "myapi.create" in caplog.text
        assert "redefined" in caplog.text.lower() or "overwriting" in caplog.text.lower()
        _, endpoint = manager.resolve("myapi.create")
        assert endpoint.path == "/create-v2"

    def test_collision_error_strict(self, tmp_path: Path) -> None:
        """Raise error on endpoint collision in strict mode."""
        from kstlib.rapi.exceptions import EndpointCollisionError

        file1 = tmp_path / "api1.rapi.yml"
        file1.write_text(
            """
name: myapi
base_url: "https://api.example.com"
endpoints:
  create:
    path: /create-v1
    method: GET
"""
        )

        file2 = tmp_path / "api2.rapi.yml"
        file2.write_text(
            """
name: myapi
base_url: "https://api.example.com"
endpoints:
  create:
    path: /create-v2
    method: GET
"""
        )

        safeguard_config = SafeguardConfig(required_methods=frozenset())
        with pytest.raises(EndpointCollisionError) as exc_info:
            RapiConfigManager.from_files(
                [str(file1), str(file2)],
                safeguard_config=safeguard_config,
                strict=True,
            )

        assert "myapi.create" in str(exc_info.value)

    def test_no_collision_different_apis(self, tmp_path: Path) -> None:
        """No collision when same endpoint name in different APIs."""
        file1 = tmp_path / "api1.rapi.yml"
        file1.write_text(
            """
name: api1
base_url: "https://api1.example.com"
endpoints:
  create:
    path: /create
    method: GET
"""
        )

        file2 = tmp_path / "api2.rapi.yml"
        file2.write_text(
            """
name: api2
base_url: "https://api2.example.com"
endpoints:
  create:
    path: /create
    method: GET
"""
        )

        safeguard_config = SafeguardConfig(required_methods=frozenset())
        manager = RapiConfigManager.from_files(
            [str(file1), str(file2)],
            safeguard_config=safeguard_config,
            strict=True,
        )

        assert "api1" in manager.list_apis()
        assert "api2" in manager.list_apis()
        _, ep1 = manager.resolve("api1.create")
        _, ep2 = manager.resolve("api2.create")
        assert ep1.api_name == "api1"
        assert ep2.api_name == "api2"

    def test_no_collision_different_endpoints(self, tmp_path: Path) -> None:
        """No collision when different endpoints in same API across files."""
        file1 = tmp_path / "api1.rapi.yml"
        file1.write_text(
            """
name: myapi
base_url: "https://api.example.com"
endpoints:
  create:
    path: /create
    method: GET
"""
        )

        file2 = tmp_path / "api2.rapi.yml"
        file2.write_text(
            """
name: myapi
base_url: "https://api.example.com"
endpoints:
  delete:
    path: /delete
    method: DELETE
    safeguard: "DELETE"
"""
        )

        manager = RapiConfigManager.from_files(
            [str(file1), str(file2)],
            strict=True,
        )

        _, create_ep = manager.resolve("myapi.create")
        _, delete_ep = manager.resolve("myapi.delete")
        assert create_ep.path == "/create"
        assert delete_ep.path == "/delete"

    def test_strict_mode_from_load_rapi_config(self, tmp_path: Path) -> None:
        """Strict mode parsed from kstlib.conf.yml."""
        from unittest import mock

        from kstlib.rapi.config import load_rapi_config
        from kstlib.rapi.exceptions import EndpointCollisionError

        file1 = tmp_path / "api1.rapi.yml"
        file1.write_text(
            """
name: myapi
base_url: "https://api.example.com"
endpoints:
  create:
    path: /create-v1
    method: GET
"""
        )

        file2 = tmp_path / "api2.rapi.yml"
        file2.write_text(
            """
name: myapi
base_url: "https://api.example.com"
endpoints:
  create:
    path: /create-v2
    method: GET
"""
        )

        mock_config = {
            "rapi": {
                "strict": True,
                "safeguard": {"required_methods": []},
                "include": [str(tmp_path / "*.rapi.yml")],
            }
        }

        with mock.patch("kstlib.config.get_config", return_value=mock_config):
            with pytest.raises(EndpointCollisionError):
                load_rapi_config()
