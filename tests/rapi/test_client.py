"""Tests for kstlib.rapi.client module."""

from pathlib import Path
from unittest import mock

import httpx
import pytest

from kstlib.rapi.client import RapiClient, RapiResponse
from kstlib.rapi.config import RapiConfigManager
from kstlib.rapi.exceptions import (
    EndpointNotFoundError,
    RequestError,
    ResponseTooLargeError,
)


class TestRapiResponse:
    """Tests for RapiResponse dataclass."""

    def test_basic_creation(self) -> None:
        """Create response with minimal fields."""
        response = RapiResponse(status_code=200)
        assert response.status_code == 200
        assert response.headers == {}
        assert response.data is None
        assert response.text == ""
        assert response.elapsed == 0.0
        assert response.endpoint_ref == ""

    def test_ok_property_success(self) -> None:
        """Verify ok property for 2xx status codes."""
        assert RapiResponse(status_code=200).ok is True
        assert RapiResponse(status_code=201).ok is True
        assert RapiResponse(status_code=204).ok is True
        assert RapiResponse(status_code=299).ok is True

    def test_ok_property_failure(self) -> None:
        """Verify ok property for non-2xx status codes."""
        assert RapiResponse(status_code=400).ok is False
        assert RapiResponse(status_code=404).ok is False
        assert RapiResponse(status_code=500).ok is False
        assert RapiResponse(status_code=302).ok is False

    def test_full_response(self) -> None:
        """Create response with all fields."""
        response = RapiResponse(
            status_code=200,
            headers={"content-type": "application/json"},
            data={"key": "value"},
            text='{"key": "value"}',
            elapsed=0.123,
            endpoint_ref="api.endpoint",
        )
        assert response.data == {"key": "value"}
        assert response.elapsed == 0.123


class TestRapiClientInit:
    """Tests for RapiClient initialization."""

    def test_default_init(self) -> None:
        """Initialize client with defaults."""
        # This will try to load from config, which should work
        client = RapiClient()
        assert client._limits is not None
        assert client._limits.timeout > 0

    def test_custom_config_manager(self) -> None:
        """Initialize client with custom config manager."""
        config = {
            "api": {
                "test": {
                    "base_url": "https://test.com",
                    "endpoints": {"ep": {"path": "/"}},
                }
            }
        }
        manager = RapiConfigManager(config)
        client = RapiClient(config_manager=manager)

        # Should be able to resolve the endpoint
        api, _endpoint = client._config_manager.resolve("test.ep")
        assert api.name == "test"


class TestRapiClientHeaderMerge:
    """Tests for header merging in RapiClient."""

    def test_merge_headers_all_levels(self) -> None:
        """Merge headers from service, endpoint, and runtime levels."""
        config = {
            "api": {
                "test": {
                    "base_url": "https://test.com",
                    "headers": {"X-Service": "service-value"},
                    "endpoints": {
                        "ep": {
                            "path": "/",
                            "headers": {"X-Endpoint": "endpoint-value"},
                        }
                    },
                }
            }
        }
        manager = RapiConfigManager(config)
        client = RapiClient(config_manager=manager)

        merged = client._merge_headers(
            {"X-Service": "service-value"},
            {"X-Endpoint": "endpoint-value"},
            {"X-Runtime": "runtime-value"},
        )

        assert merged["X-Service"] == "service-value"
        assert merged["X-Endpoint"] == "endpoint-value"
        assert merged["X-Runtime"] == "runtime-value"

    def test_merge_headers_override(self) -> None:
        """Later levels override earlier levels."""
        client = RapiClient(config_manager=RapiConfigManager({}))

        merged = client._merge_headers(
            {"X-Header": "service"},
            {"X-Header": "endpoint"},
            {"X-Header": "runtime"},
        )

        assert merged["X-Header"] == "runtime"

    def test_merge_headers_partial(self) -> None:
        """Merge with empty levels."""
        client = RapiClient(config_manager=RapiConfigManager({}))

        merged = client._merge_headers(
            {"X-Service": "value"},
            {},
            {},
        )

        assert merged["X-Service"] == "value"


class TestRapiClientBuildRequest:
    """Tests for request building in RapiClient."""

    def test_build_simple_get(self) -> None:
        """Build simple GET request."""
        config = {
            "api": {
                "httpbin": {
                    "base_url": "https://httpbin.org",
                    "endpoints": {"get_ip": {"path": "/ip"}},
                }
            }
        }
        manager = RapiConfigManager(config)
        client = RapiClient(config_manager=manager)

        api, endpoint = manager.resolve("httpbin.get_ip")
        request = client._build_request(api, endpoint, (), {}, None, None)

        assert request.method == "GET"
        assert str(request.url) == "https://httpbin.org/ip"

    def test_build_post_with_json_body(self) -> None:
        """Build POST request with JSON body."""
        config = {
            "api": {
                "httpbin": {
                    "base_url": "https://httpbin.org",
                    "endpoints": {"post_data": {"path": "/post", "method": "POST"}},
                }
            }
        }
        manager = RapiConfigManager(config)
        client = RapiClient(config_manager=manager)

        api, endpoint = manager.resolve("httpbin.post_data")
        request = client._build_request(
            api,
            endpoint,
            (),
            {},
            {"key": "value"},
            None,
        )

        assert request.method == "POST"
        assert "application/json" in request.headers.get("content-type", "")

    def test_build_with_path_params(self) -> None:
        """Build request with path parameters."""
        config = {
            "api": {
                "httpbin": {
                    "base_url": "https://httpbin.org",
                    "endpoints": {"delay": {"path": "/delay/{seconds}"}},
                }
            }
        }
        manager = RapiConfigManager(config)
        client = RapiClient(config_manager=manager)

        api, endpoint = manager.resolve("httpbin.delay")
        request = client._build_request(
            api,
            endpoint,
            (5,),  # Positional arg
            {},
            None,
            None,
        )

        assert "/delay/5" in str(request.url)

    def test_build_with_query_params(self) -> None:
        """Build request with query parameters from config and kwargs."""
        config = {
            "api": {
                "api": {
                    "base_url": "https://api.com",
                    "endpoints": {
                        "search": {
                            "path": "/search",
                            "query": {"version": "1"},
                        }
                    },
                }
            }
        }
        manager = RapiConfigManager(config)
        client = RapiClient(config_manager=manager)

        api, endpoint = manager.resolve("api.search")
        request = client._build_request(
            api,
            endpoint,
            (),
            {"q": "test"},  # Extra query param
            None,
            None,
        )

        url_str = str(request.url)
        assert "version=1" in url_str
        assert "q=test" in url_str

    def test_build_with_runtime_headers(self) -> None:
        """Build request with runtime headers."""
        config = {
            "api": {
                "api": {
                    "base_url": "https://api.com",
                    "endpoints": {"ep": {"path": "/"}},
                }
            }
        }
        manager = RapiConfigManager(config)
        client = RapiClient(config_manager=manager)

        api, endpoint = manager.resolve("api.ep")
        request = client._build_request(
            api,
            endpoint,
            (),
            {},
            None,
            {"X-Custom": "runtime"},
        )

        assert request.headers.get("x-custom") == "runtime"


class TestRapiClientCall:
    """Tests for RapiClient.call method."""

    def test_call_endpoint_not_found(self) -> None:
        """Raise EndpointNotFoundError for unknown endpoint."""
        config = {
            "api": {
                "test": {
                    "base_url": "https://test.com",
                    "endpoints": {"ep": {"path": "/"}},
                }
            }
        }
        manager = RapiConfigManager(config)
        client = RapiClient(config_manager=manager)

        with pytest.raises(EndpointNotFoundError):
            client.call("unknown.endpoint")

    @mock.patch("httpx.Client")
    def test_call_success(self, mock_client_class: mock.Mock) -> None:
        """Make successful API call."""
        # Setup mock
        mock_response = mock.Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.text = '{"ip": "1.2.3.4"}'
        mock_response.json.return_value = {"ip": "1.2.3.4"}

        mock_client = mock.Mock()
        mock_client.send.return_value = mock_response
        mock_client.__enter__ = mock.Mock(return_value=mock_client)
        mock_client.__exit__ = mock.Mock(return_value=False)
        mock_client_class.return_value = mock_client

        config = {
            "api": {
                "httpbin": {
                    "base_url": "https://httpbin.org",
                    "endpoints": {"get_ip": {"path": "/ip"}},
                }
            }
        }
        manager = RapiConfigManager(config)
        client = RapiClient(config_manager=manager)

        response = client.call("httpbin.get_ip")

        assert response.ok
        assert response.status_code == 200
        assert response.data == {"ip": "1.2.3.4"}

    @mock.patch("httpx.Client")
    def test_call_with_body(self, mock_client_class: mock.Mock) -> None:
        """Make API call with JSON body."""
        mock_response = mock.Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.text = '{"success": true}'
        mock_response.json.return_value = {"success": True}

        mock_client = mock.Mock()
        mock_client.send.return_value = mock_response
        mock_client.__enter__ = mock.Mock(return_value=mock_client)
        mock_client.__exit__ = mock.Mock(return_value=False)
        mock_client_class.return_value = mock_client

        config = {
            "api": {
                "httpbin": {
                    "base_url": "https://httpbin.org",
                    "endpoints": {"post_data": {"path": "/post", "method": "POST"}},
                }
            }
        }
        manager = RapiConfigManager(config)
        client = RapiClient(config_manager=manager)

        response = client.call("httpbin.post_data", body={"key": "value"})

        assert response.ok
        # Verify request was made with body
        mock_client.send.assert_called_once()

    @mock.patch("httpx.Client")
    def test_call_timeout_error(self, mock_client_class: mock.Mock) -> None:
        """Handle timeout error with retries."""
        mock_client = mock.Mock()
        mock_client.send.side_effect = httpx.TimeoutException("Timeout")
        mock_client.__enter__ = mock.Mock(return_value=mock_client)
        mock_client.__exit__ = mock.Mock(return_value=False)
        mock_client_class.return_value = mock_client

        config = {
            "api": {
                "test": {
                    "base_url": "https://test.com",
                    "endpoints": {"ep": {"path": "/"}},
                }
            }
        }
        manager = RapiConfigManager(config)
        client = RapiClient(config_manager=manager)

        # Override limits for faster test
        client._limits = client._limits.__class__(
            timeout=1.0,
            max_response_size=1000000,
            max_retries=1,  # Only 1 retry
            retry_delay=0.01,
            retry_backoff=1.0,
        )

        with pytest.raises(RequestError):
            client.call("test.ep")

        # Should have tried twice (initial + 1 retry)
        assert mock_client.send.call_count == 2

    @mock.patch("httpx.Client")
    def test_call_client_error_no_retry(self, mock_client_class: mock.Mock) -> None:
        """Don't retry on 4xx client errors."""
        mock_response = mock.Mock(spec=httpx.Response)
        mock_response.status_code = 404
        mock_response.headers = {"content-type": "application/json"}
        mock_response.text = '{"error": "not found"}'
        mock_response.json.return_value = {"error": "not found"}

        mock_client = mock.Mock()
        mock_client.send.return_value = mock_response
        mock_client.__enter__ = mock.Mock(return_value=mock_client)
        mock_client.__exit__ = mock.Mock(return_value=False)
        mock_client_class.return_value = mock_client

        config = {
            "api": {
                "test": {
                    "base_url": "https://test.com",
                    "endpoints": {"ep": {"path": "/"}},
                }
            }
        }
        manager = RapiConfigManager(config)
        client = RapiClient(config_manager=manager)

        response = client.call("test.ep")

        assert response.status_code == 404
        assert response.ok is False
        # Should only be called once (no retry)
        mock_client.send.assert_called_once()

    @mock.patch("httpx.Client")
    def test_call_response_too_large(self, mock_client_class: mock.Mock) -> None:
        """Raise ResponseTooLargeError when response exceeds limit."""
        mock_response = mock.Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.headers = {"content-length": "999999999"}  # ~1GB

        mock_client = mock.Mock()
        mock_client.send.return_value = mock_response
        mock_client.__enter__ = mock.Mock(return_value=mock_client)
        mock_client.__exit__ = mock.Mock(return_value=False)
        mock_client_class.return_value = mock_client

        config = {
            "api": {
                "test": {
                    "base_url": "https://test.com",
                    "endpoints": {"ep": {"path": "/"}},
                }
            }
        }
        manager = RapiConfigManager(config)
        client = RapiClient(config_manager=manager)

        # Set a small limit for testing
        client._limits = client._limits.__class__(
            timeout=30.0,
            max_response_size=1000,  # 1KB limit
            max_retries=0,
            retry_delay=1.0,
            retry_backoff=2.0,
        )

        with pytest.raises(ResponseTooLargeError):
            client.call("test.ep")


class TestRapiClientAuth:
    """Tests for authentication in RapiClient."""

    def test_apply_auth_bearer(self) -> None:
        """Apply bearer token authentication."""
        config = {
            "api": {
                "api": {
                    "base_url": "https://api.com",
                    "credentials": "test_cred",
                    "auth_type": "bearer",
                    "endpoints": {"ep": {"path": "/"}},
                }
            }
        }
        manager = RapiConfigManager(config)

        # Create client with mock credentials
        cred_config = {
            "test_cred": {
                "type": "env",
                "var": "TEST_TOKEN",
            }
        }
        client = RapiClient(config_manager=manager, credentials_config=cred_config)

        api = manager.get_api("api")
        assert api is not None

        headers: dict[str, str] = {}

        # Mock the environment variable
        with mock.patch.dict("os.environ", {"TEST_TOKEN": "my_bearer_token"}):
            client._apply_auth(headers, api)

        assert headers.get("Authorization") == "Bearer my_bearer_token"

    def test_apply_auth_basic(self) -> None:
        """Apply basic authentication."""
        config = {
            "api": {
                "api": {
                    "base_url": "https://api.com",
                    "credentials": "test_cred",
                    "auth_type": "basic",
                    "endpoints": {"ep": {"path": "/"}},
                }
            }
        }
        manager = RapiConfigManager(config)

        cred_config = {
            "test_cred": {
                "type": "env",
                "var_key": "TEST_USER",
                "var_secret": "TEST_PASS",
            }
        }
        client = RapiClient(config_manager=manager, credentials_config=cred_config)

        api = manager.get_api("api")
        assert api is not None

        headers: dict[str, str] = {}

        with mock.patch.dict(
            "os.environ",
            {"TEST_USER": "user", "TEST_PASS": "pass"},
        ):
            client._apply_auth(headers, api)

        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Basic ")

    def test_apply_auth_api_key(self) -> None:
        """Apply API key authentication."""
        config = {
            "api": {
                "api": {
                    "base_url": "https://api.com",
                    "credentials": "test_cred",
                    "auth_type": "api_key",
                    "endpoints": {"ep": {"path": "/"}},
                }
            }
        }
        manager = RapiConfigManager(config)

        cred_config = {
            "test_cred": {
                "type": "env",
                "var": "TEST_API_KEY",
            }
        }
        client = RapiClient(config_manager=manager, credentials_config=cred_config)

        api = manager.get_api("api")
        assert api is not None

        headers: dict[str, str] = {}

        with mock.patch.dict("os.environ", {"TEST_API_KEY": "my_api_key"}):
            client._apply_auth(headers, api)

        assert headers.get("X-API-Key") == "my_api_key"

    def test_apply_auth_no_credentials(self) -> None:
        """Skip auth when no credentials configured."""
        config = {
            "api": {
                "api": {
                    "base_url": "https://api.com",
                    # No credentials
                    "endpoints": {"ep": {"path": "/"}},
                }
            }
        }
        manager = RapiConfigManager(config)
        client = RapiClient(config_manager=manager)

        api = manager.get_api("api")
        assert api is not None

        headers: dict[str, str] = {}
        client._apply_auth(headers, api)

        assert "Authorization" not in headers
        assert "X-API-Key" not in headers


class TestRapiClientShortcuts:
    """Tests for convenience functions."""

    @mock.patch("kstlib.rapi.client.RapiClient")
    def test_call_function(self, mock_client_class: mock.Mock) -> None:
        """Test call() convenience function."""
        from kstlib.rapi.client import call

        mock_client = mock.Mock()
        mock_client.call.return_value = RapiResponse(status_code=200)
        mock_client_class.return_value = mock_client

        response = call("test.endpoint", body={"key": "value"})

        mock_client.call.assert_called_once_with(
            "test.endpoint",
            body={"key": "value"},
            headers=None,
        )
        assert response.status_code == 200

    @mock.patch("kstlib.rapi.client.RapiClient")
    @pytest.mark.asyncio
    async def test_call_async_function(self, mock_client_class: mock.Mock) -> None:
        """Test call_async() convenience function."""
        from kstlib.rapi.client import call_async

        mock_client = mock.Mock()

        async def mock_call_async(*args: object, **kwargs: object) -> RapiResponse:
            return RapiResponse(status_code=200)

        mock_client.call_async = mock_call_async
        mock_client_class.return_value = mock_client

        response = await call_async("test.endpoint")

        assert response.status_code == 200


class TestRapiClientFactoryMethods:
    """Tests for RapiClient factory methods (from_file, discover)."""

    def test_from_file_basic(self, tmp_path: Path) -> None:
        """Create client from a basic RAPI YAML file."""
        rapi_file = tmp_path / "github.rapi.yml"
        rapi_file.write_text(
            """
name: github
base_url: "https://api.github.com"

endpoints:
  user:
    path: "/user"
  repos:
    path: "/repos/{owner}/{repo}"
"""
        )

        client = RapiClient.from_file(str(rapi_file))

        assert "github" in client.list_apis()
        assert "github.user" in client.list_endpoints()
        assert "github.repos" in client.list_endpoints()

    def test_from_file_not_found(self) -> None:
        """Raise error when file does not exist."""
        with pytest.raises(FileNotFoundError):
            RapiClient.from_file("/nonexistent/path.rapi.yml")

    def test_from_file_with_credentials(self, tmp_path: Path) -> None:
        """Create client with additional credentials config."""
        rapi_file = tmp_path / "api.rapi.yml"
        rapi_file.write_text(
            """
name: myapi
base_url: "https://api.example.com"
credentials: mytoken

endpoints:
  data:
    path: "/data"
"""
        )

        creds = {"mytoken": {"type": "env", "var": "MY_API_TOKEN"}}
        client = RapiClient.from_file(str(rapi_file), credentials_config=creds)

        assert "myapi" in client.list_apis()
        # Credentials should be merged
        assert "mytoken" in client._credential_resolver._config

    def test_discover_finds_files(self, tmp_path: Path) -> None:
        """Discover and load multiple RAPI files."""
        # Create two RAPI files
        (tmp_path / "github.rapi.yml").write_text(
            """
name: github
base_url: "https://api.github.com"
endpoints:
  user:
    path: "/user"
"""
        )
        (tmp_path / "gitlab.rapi.yml").write_text(
            """
name: gitlab
base_url: "https://gitlab.com/api/v4"
endpoints:
  projects:
    path: "/projects"
"""
        )

        client = RapiClient.discover(str(tmp_path))

        apis = client.list_apis()
        assert "github" in apis
        assert "gitlab" in apis

    def test_discover_no_files(self, tmp_path: Path) -> None:
        """Raise error when no files match pattern."""
        with pytest.raises(FileNotFoundError, match="No RAPI config files found"):
            RapiClient.discover(str(tmp_path))

    def test_discover_custom_pattern(self, tmp_path: Path) -> None:
        """Discover files with custom pattern."""
        (tmp_path / "custom.api.yaml").write_text(
            """
name: custom
base_url: "https://custom.api.com"
endpoints:
  test:
    path: "/test"
"""
        )

        client = RapiClient.discover(str(tmp_path), pattern="*.api.yaml")

        assert "custom" in client.list_apis()

    def test_config_manager_property(self) -> None:
        """Access config_manager property."""
        config = {
            "api": {
                "test": {
                    "base_url": "https://test.com",
                    "endpoints": {"ep": {"path": "/"}},
                }
            }
        }
        manager = RapiConfigManager(config)
        client = RapiClient(config_manager=manager)

        assert client.config_manager is manager

    def test_list_apis(self) -> None:
        """List all configured API names."""
        config = {
            "api": {
                "api1": {
                    "base_url": "https://api1.com",
                    "endpoints": {"ep": {"path": "/"}},
                },
                "api2": {
                    "base_url": "https://api2.com",
                    "endpoints": {"ep": {"path": "/"}},
                },
            }
        }
        manager = RapiConfigManager(config)
        client = RapiClient(config_manager=manager)

        apis = client.list_apis()

        assert "api1" in apis
        assert "api2" in apis

    def test_list_endpoints_all(self) -> None:
        """List all endpoints across APIs."""
        config = {
            "api": {
                "api1": {
                    "base_url": "https://api1.com",
                    "endpoints": {"ep1": {"path": "/"}, "ep2": {"path": "/two"}},
                },
                "api2": {
                    "base_url": "https://api2.com",
                    "endpoints": {"ep3": {"path": "/three"}},
                },
            }
        }
        manager = RapiConfigManager(config)
        client = RapiClient(config_manager=manager)

        endpoints = client.list_endpoints()

        assert "api1.ep1" in endpoints
        assert "api1.ep2" in endpoints
        assert "api2.ep3" in endpoints

    def test_list_endpoints_filtered(self) -> None:
        """List endpoints for specific API."""
        config = {
            "api": {
                "api1": {
                    "base_url": "https://api1.com",
                    "endpoints": {"ep1": {"path": "/"}, "ep2": {"path": "/two"}},
                },
                "api2": {
                    "base_url": "https://api2.com",
                    "endpoints": {"ep3": {"path": "/three"}},
                },
            }
        }
        manager = RapiConfigManager(config)
        client = RapiClient(config_manager=manager)

        endpoints = client.list_endpoints("api1")

        assert "api1.ep1" in endpoints
        assert "api1.ep2" in endpoints
        assert "api2.ep3" not in endpoints


class TestRapiClientPrepareBody:
    """Tests for body preparation in RapiClient."""

    def test_prepare_body_string(self) -> None:
        """Prepare string body."""
        client = RapiClient(config_manager=RapiConfigManager({}))
        headers: dict[str, str] = {}

        content = client._prepare_body("plain text body", headers)

        assert content == b"plain text body"
        # String body should not set Content-Type automatically
        assert "Content-Type" not in headers

    def test_prepare_body_bytes(self) -> None:
        """Prepare bytes body."""
        client = RapiClient(config_manager=RapiConfigManager({}))
        headers: dict[str, str] = {}

        content = client._prepare_body(b"raw bytes", headers)

        assert content == b"raw bytes"

    def test_prepare_body_large_truncates_log(self) -> None:
        """Large body should be truncated in trace log."""
        client = RapiClient(config_manager=RapiConfigManager({}))
        headers: dict[str, str] = {}

        # Create body larger than 1000 chars
        large_body = {"data": "x" * 1500}
        content = client._prepare_body(large_body, headers)

        assert content is not None
        assert len(content) > 1000


class TestRapiClientAuthEdgeCases:
    """Tests for authentication edge cases."""

    def test_apply_auth_credential_resolve_fails(self) -> None:
        """Handle credential resolution failure gracefully."""
        config = {
            "api": {
                "api": {
                    "base_url": "https://api.com",
                    "credentials": "nonexistent_cred",
                    "endpoints": {"ep": {"path": "/"}},
                }
            }
        }
        manager = RapiConfigManager(config)
        # No credentials config, so resolution will fail
        client = RapiClient(config_manager=manager)

        api = manager.get_api("api")
        assert api is not None

        headers: dict[str, str] = {}
        # Should not raise, just log warning
        client._apply_auth(headers, api)

        # No auth header should be set
        assert "Authorization" not in headers

    def test_apply_auth_hmac_missing_secret_raises(self) -> None:
        """HMAC auth raises ValueError when secret is missing."""
        config = {
            "api": {
                "api": {
                    "base_url": "https://api.com",
                    "credentials": "test_cred",
                    "auth_type": "hmac",
                    "endpoints": {"ep": {"path": "/"}},
                }
            }
        }
        manager = RapiConfigManager(config)

        # Credential without secret (only var, no var_secret)
        cred_config = {"test_cred": {"type": "env", "var": "TEST_KEY"}}
        client = RapiClient(config_manager=manager, credentials_config=cred_config)

        api = manager.get_api("api")
        assert api is not None

        headers: dict[str, str] = {}
        query_params: dict[str, str] = {}

        with (
            mock.patch.dict("os.environ", {"TEST_KEY": "api_key_only"}),
            pytest.raises(ValueError, match="HMAC auth requires secret_key"),
        ):
            client._apply_auth(headers, api, query_params)

    def test_apply_auth_unknown_type_logs_warning(self) -> None:
        """Unknown auth type logs warning."""
        config = {
            "api": {
                "api": {
                    "base_url": "https://api.com",
                    "credentials": "test_cred",
                    "auth_type": "custom_unknown",
                    "endpoints": {"ep": {"path": "/"}},
                }
            }
        }
        manager = RapiConfigManager(config)

        cred_config = {"test_cred": {"type": "env", "var": "TEST_KEY"}}
        client = RapiClient(config_manager=manager, credentials_config=cred_config)

        api = manager.get_api("api")
        assert api is not None

        headers: dict[str, str] = {}

        with mock.patch.dict("os.environ", {"TEST_KEY": "secret"}):
            client._apply_auth(headers, api)

        # Unknown type doesn't set any headers
        assert "Authorization" not in headers


class TestRapiClientCallAsync:
    """Tests for RapiClient.call_async method."""

    @mock.patch("httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_call_async_success(self, mock_client_class: mock.Mock) -> None:
        """Make successful async API call."""
        mock_response = mock.Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.text = '{"result": "ok"}'
        mock_response.json.return_value = {"result": "ok"}

        mock_client = mock.AsyncMock()
        mock_client.send.return_value = mock_response
        mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mock.AsyncMock(return_value=False)
        mock_client_class.return_value = mock_client

        config = {
            "api": {
                "test": {
                    "base_url": "https://test.com",
                    "endpoints": {"ep": {"path": "/data"}},
                }
            }
        }
        manager = RapiConfigManager(config)
        client = RapiClient(config_manager=manager)

        response = await client.call_async("test.ep")

        assert response.ok
        assert response.status_code == 200
        assert response.data == {"result": "ok"}

    @mock.patch("httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_call_async_with_body(self, mock_client_class: mock.Mock) -> None:
        """Make async API call with body."""
        mock_response = mock.Mock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.headers = {"content-type": "application/json"}
        mock_response.text = '{"created": true}'
        mock_response.json.return_value = {"created": True}

        mock_client = mock.AsyncMock()
        mock_client.send.return_value = mock_response
        mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mock.AsyncMock(return_value=False)
        mock_client_class.return_value = mock_client

        config = {
            "api": {
                "test": {
                    "base_url": "https://test.com",
                    "endpoints": {"create": {"path": "/create", "method": "POST"}},
                }
            }
        }
        manager = RapiConfigManager(config)
        client = RapiClient(config_manager=manager)

        response = await client.call_async("test.create", body={"name": "test"})

        assert response.ok
        mock_client.send.assert_called_once()

    @mock.patch("httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_call_async_timeout_with_retry(self, mock_client_class: mock.Mock) -> None:
        """Handle timeout with retries in async call."""
        mock_client = mock.AsyncMock()
        mock_client.send.side_effect = httpx.TimeoutException("Timeout")
        mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mock.AsyncMock(return_value=False)
        mock_client_class.return_value = mock_client

        config = {
            "api": {
                "test": {
                    "base_url": "https://test.com",
                    "endpoints": {"ep": {"path": "/"}},
                }
            }
        }
        manager = RapiConfigManager(config)
        client = RapiClient(config_manager=manager)

        # Fast retries for test
        client._limits = client._limits.__class__(
            timeout=1.0,
            max_response_size=1000000,
            max_retries=1,
            retry_delay=0.01,
            retry_backoff=1.0,
        )

        with pytest.raises(RequestError):
            await client.call_async("test.ep")

        assert mock_client.send.call_count == 2

    @mock.patch("httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_call_async_network_error(self, mock_client_class: mock.Mock) -> None:
        """Handle network error in async call."""
        mock_client = mock.AsyncMock()
        mock_client.send.side_effect = httpx.NetworkError("Connection refused")
        mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mock.AsyncMock(return_value=False)
        mock_client_class.return_value = mock_client

        config = {
            "api": {
                "test": {
                    "base_url": "https://test.com",
                    "endpoints": {"ep": {"path": "/"}},
                }
            }
        }
        manager = RapiConfigManager(config)
        client = RapiClient(config_manager=manager)

        client._limits = client._limits.__class__(
            timeout=1.0,
            max_response_size=1000000,
            max_retries=0,
            retry_delay=0.01,
            retry_backoff=1.0,
        )

        with pytest.raises(RequestError):
            await client.call_async("test.ep")

    @mock.patch("httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_call_async_response_too_large(self, mock_client_class: mock.Mock) -> None:
        """Raise ResponseTooLargeError in async call."""
        mock_response = mock.Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.headers = {"content-length": "999999999"}

        mock_client = mock.AsyncMock()
        mock_client.send.return_value = mock_response
        mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mock.AsyncMock(return_value=False)
        mock_client_class.return_value = mock_client

        config = {
            "api": {
                "test": {
                    "base_url": "https://test.com",
                    "endpoints": {"ep": {"path": "/"}},
                }
            }
        }
        manager = RapiConfigManager(config)
        client = RapiClient(config_manager=manager)

        client._limits = client._limits.__class__(
            timeout=30.0,
            max_response_size=1000,
            max_retries=0,
            retry_delay=1.0,
            retry_backoff=2.0,
        )

        with pytest.raises(ResponseTooLargeError):
            await client.call_async("test.ep")

    @mock.patch("httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_call_async_4xx_no_retry(self, mock_client_class: mock.Mock) -> None:
        """Don't retry on 4xx errors in async call."""
        mock_response = mock.Mock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.headers = {"content-type": "application/json"}
        mock_response.text = '{"error": "bad request"}'
        mock_response.json.return_value = {"error": "bad request"}

        mock_client = mock.AsyncMock()
        mock_client.send.return_value = mock_response
        mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mock.AsyncMock(return_value=False)
        mock_client_class.return_value = mock_client

        config = {
            "api": {
                "test": {
                    "base_url": "https://test.com",
                    "endpoints": {"ep": {"path": "/"}},
                }
            }
        }
        manager = RapiConfigManager(config)
        client = RapiClient(config_manager=manager)

        response = await client.call_async("test.ep")

        assert response.status_code == 400
        mock_client.send.assert_called_once()


class TestRapiClientSyncRetryErrors:
    """Tests for sync retry error handling."""

    @mock.patch("httpx.Client")
    def test_call_network_error_with_retry(self, mock_client_class: mock.Mock) -> None:
        """Handle network error with retries."""
        mock_client = mock.Mock()
        mock_client.send.side_effect = httpx.NetworkError("Connection refused")
        mock_client.__enter__ = mock.Mock(return_value=mock_client)
        mock_client.__exit__ = mock.Mock(return_value=False)
        mock_client_class.return_value = mock_client

        config = {
            "api": {
                "test": {
                    "base_url": "https://test.com",
                    "endpoints": {"ep": {"path": "/"}},
                }
            }
        }
        manager = RapiConfigManager(config)
        client = RapiClient(config_manager=manager)

        client._limits = client._limits.__class__(
            timeout=1.0,
            max_response_size=1000000,
            max_retries=1,
            retry_delay=0.01,
            retry_backoff=1.0,
        )

        with pytest.raises(RequestError):
            client.call("test.ep")

        assert mock_client.send.call_count == 2

    @mock.patch("httpx.Client")
    def test_call_5xx_error_with_retry(self, mock_client_class: mock.Mock) -> None:
        """Retry on 5xx server errors."""
        mock_response = mock.Mock(spec=httpx.Response)
        mock_response.status_code = 503
        mock_response.headers = {}
        mock_response.text = "Service Unavailable"

        error = httpx.HTTPStatusError("503", request=mock.Mock(), response=mock_response)

        mock_client = mock.Mock()
        mock_client.send.side_effect = error
        mock_client.__enter__ = mock.Mock(return_value=mock_client)
        mock_client.__exit__ = mock.Mock(return_value=False)
        mock_client_class.return_value = mock_client

        config = {
            "api": {
                "test": {
                    "base_url": "https://test.com",
                    "endpoints": {"ep": {"path": "/"}},
                }
            }
        }
        manager = RapiConfigManager(config)
        client = RapiClient(config_manager=manager)

        client._limits = client._limits.__class__(
            timeout=1.0,
            max_response_size=1000000,
            max_retries=1,
            retry_delay=0.01,
            retry_backoff=1.0,
        )

        with pytest.raises(RequestError):
            client.call("test.ep")

        # Should retry on 5xx
        assert mock_client.send.call_count == 2


class TestRapiClientHmacAuth:
    """Tests for HMAC authentication in RapiClient."""

    def test_hmac_sha256_hex_signature(self) -> None:
        """Generate SHA256 hex signature (Binance-style)."""
        from kstlib.rapi.config import HmacConfig

        config = {
            "api": {
                "binance": {
                    "base_url": "https://api.binance.com",
                    "credentials": "binance_cred",
                    "auth_type": "hmac",
                    "hmac_config": HmacConfig(
                        algorithm="sha256",
                        timestamp_field="timestamp",
                        signature_field="signature",
                        signature_format="hex",
                        key_header="X-MBX-APIKEY",
                    ),
                    "endpoints": {"balance": {"path": "/api/v3/account"}},
                }
            }
        }
        manager = RapiConfigManager(config)

        cred_config = {
            "binance_cred": {
                "type": "env",
                "var_key": "BINANCE_API_KEY",
                "var_secret": "BINANCE_API_SECRET",
            }
        }
        client = RapiClient(config_manager=manager, credentials_config=cred_config)

        api = manager.get_api("binance")
        assert api is not None

        headers: dict[str, str] = {}
        query_params: dict[str, str] = {"symbol": "BTCUSDT"}

        with mock.patch.dict(
            "os.environ",
            {"BINANCE_API_KEY": "my_api_key", "BINANCE_API_SECRET": "my_secret"},
        ):
            client._apply_auth(headers, api, query_params)

        # Verify API key header was set
        assert headers.get("X-MBX-APIKEY") == "my_api_key"

        # Verify timestamp and signature were added to query params
        assert "timestamp" in query_params
        assert "signature" in query_params

        # Verify signature is hex format (64 chars for SHA256)
        assert len(query_params["signature"]) == 64
        assert all(c in "0123456789abcdef" for c in query_params["signature"])

    def test_hmac_sha512_base64_signature(self) -> None:
        """Generate SHA512 base64 signature (Kraken-style)."""
        from kstlib.rapi.config import HmacConfig

        config = {
            "api": {
                "kraken": {
                    "base_url": "https://api.kraken.com",
                    "credentials": "kraken_cred",
                    "auth_type": "hmac",
                    "hmac_config": HmacConfig(
                        algorithm="sha512",
                        nonce_field="nonce",
                        signature_field="signature",
                        signature_format="base64",
                        key_header="API-Key",
                    ),
                    "endpoints": {"balance": {"path": "/0/private/Balance"}},
                }
            }
        }
        manager = RapiConfigManager(config)

        cred_config = {
            "kraken_cred": {
                "type": "env",
                "var_key": "KRAKEN_API_KEY",
                "var_secret": "KRAKEN_API_SECRET",
            }
        }
        client = RapiClient(config_manager=manager, credentials_config=cred_config)

        api = manager.get_api("kraken")
        assert api is not None

        headers: dict[str, str] = {}
        query_params: dict[str, str] = {}

        with mock.patch.dict(
            "os.environ",
            {"KRAKEN_API_KEY": "kraken_key", "KRAKEN_API_SECRET": "kraken_secret"},
        ):
            client._apply_auth(headers, api, query_params)

        # Verify API key header was set
        assert headers.get("API-Key") == "kraken_key"

        # Verify nonce (not timestamp) was added
        assert "nonce" in query_params
        assert "timestamp" not in query_params
        assert "signature" in query_params

        # Verify signature is base64 format (ends with = padding or alphanumeric)
        sig = query_params["signature"]
        # SHA512 produces 64 bytes, base64 encodes to 88 chars
        assert len(sig) == 88

    def test_hmac_sign_body(self) -> None:
        """Sign request body instead of query string."""
        from kstlib.rapi.config import HmacConfig

        config = {
            "api": {
                "api": {
                    "base_url": "https://api.example.com",
                    "credentials": "cred",
                    "auth_type": "hmac",
                    "hmac_config": HmacConfig(
                        algorithm="sha256",
                        sign_body=True,
                    ),
                    "endpoints": {"post": {"path": "/data", "method": "POST"}},
                }
            }
        }
        manager = RapiConfigManager(config)

        cred_config = {
            "cred": {
                "type": "env",
                "var_key": "API_KEY",
                "var_secret": "API_SECRET",
            }
        }
        client = RapiClient(config_manager=manager, credentials_config=cred_config)

        api = manager.get_api("api")
        assert api is not None

        headers: dict[str, str] = {}
        query_params: dict[str, str] = {"query": "param"}
        body_content = b'{"data": "test"}'

        with mock.patch.dict(
            "os.environ",
            {"API_KEY": "key", "API_SECRET": "secret"},
        ):
            client._apply_auth(headers, api, query_params, body_content)

        # Signature should be based on body, but still added to query params
        assert "signature" in query_params
        assert "timestamp" in query_params

    def test_hmac_signature_deterministic(self) -> None:
        """Same input produces same signature."""
        import hashlib
        import hmac as hmac_lib
        from urllib.parse import urlencode

        from kstlib.rapi.config import HmacConfig

        config = {
            "api": {
                "api": {
                    "base_url": "https://api.example.com",
                    "credentials": "cred",
                    "auth_type": "hmac",
                    "hmac_config": HmacConfig(algorithm="sha256"),
                    "endpoints": {"ep": {"path": "/"}},
                }
            }
        }
        manager = RapiConfigManager(config)

        cred_config = {
            "cred": {
                "type": "env",
                "var_key": "API_KEY",
                "var_secret": "API_SECRET",
            }
        }
        client = RapiClient(config_manager=manager, credentials_config=cred_config)

        api = manager.get_api("api")
        assert api is not None

        # Mock time to get deterministic timestamp
        with (
            mock.patch("time.time", return_value=1700000000.0),
            mock.patch.dict("os.environ", {"API_KEY": "key", "API_SECRET": "test_secret"}),
        ):
            headers1: dict[str, str] = {}
            query1: dict[str, str] = {"param": "value"}
            client._apply_auth(headers1, api, query1)
            sig1 = query1["signature"]

            # Calculate expected signature manually
            expected_payload = urlencode(sorted({"param": "value", "timestamp": "1700000000000"}.items()))
            expected_sig = hmac_lib.new(
                b"test_secret",
                expected_payload.encode(),
                hashlib.sha256,
            ).hexdigest()

            assert sig1 == expected_sig

    def test_hmac_config_defaults(self) -> None:
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

    def test_hmac_from_rapi_file(self, tmp_path: Path) -> None:
        """Load HMAC config from RAPI YAML file."""
        rapi_file = tmp_path / "exchange.rapi.yml"
        rapi_file.write_text(
            """
name: exchange
base_url: "https://api.exchange.com"
credentials:
  type: env
  var_key: "EXCHANGE_KEY"
  var_secret: "EXCHANGE_SECRET"
auth:
  type: hmac
  algorithm: sha512
  timestamp_field: ts
  signature_field: sig
  signature_format: base64
  key_header: X-Exchange-Key
endpoints:
  balance:
    path: "/balance"
"""
        )

        manager = RapiConfigManager.from_file(str(rapi_file))

        api = manager.get_api("exchange")
        assert api is not None
        assert api.auth_type == "hmac"
        assert api.hmac_config is not None
        assert api.hmac_config.algorithm == "sha512"
        assert api.hmac_config.timestamp_field == "ts"
        assert api.hmac_config.signature_field == "sig"
        assert api.hmac_config.signature_format == "base64"
        assert api.hmac_config.key_header == "X-Exchange-Key"

    @mock.patch("httpx.Client")
    def test_hmac_full_call_integration(self, mock_client_class: mock.Mock) -> None:
        """Test HMAC auth in full call flow."""
        from kstlib.rapi.config import HmacConfig

        mock_response = mock.Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.text = '{"balance": "100.0"}'
        mock_response.json.return_value = {"balance": "100.0"}

        mock_client = mock.Mock()
        mock_client.send.return_value = mock_response
        mock_client.__enter__ = mock.Mock(return_value=mock_client)
        mock_client.__exit__ = mock.Mock(return_value=False)
        mock_client_class.return_value = mock_client

        config = {
            "api": {
                "exchange": {
                    "base_url": "https://api.exchange.com",
                    "credentials": "exchange_cred",
                    "auth_type": "hmac",
                    "hmac_config": HmacConfig(
                        algorithm="sha256",
                        key_header="X-API-KEY",
                    ),
                    "endpoints": {"balance": {"path": "/balance"}},
                }
            }
        }
        manager = RapiConfigManager(config)

        cred_config = {
            "exchange_cred": {
                "type": "env",
                "var_key": "EXCHANGE_KEY",
                "var_secret": "EXCHANGE_SECRET",
            }
        }
        client = RapiClient(config_manager=manager, credentials_config=cred_config)

        with mock.patch.dict(
            "os.environ",
            {"EXCHANGE_KEY": "my_key", "EXCHANGE_SECRET": "my_secret"},
        ):
            response = client.call("exchange.balance")

        assert response.ok
        assert response.data == {"balance": "100.0"}

        # Verify the request had HMAC params
        call_args = mock_client.send.call_args
        request = call_args[0][0]

        # Check headers
        assert request.headers.get("x-api-key") == "my_key"

        # Check URL has timestamp and signature
        url_str = str(request.url)
        assert "timestamp=" in url_str
        assert "signature=" in url_str
