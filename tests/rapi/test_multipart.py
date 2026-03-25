"""Tests for multipart/form-data upload support in RAPI."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from kstlib.rapi.client import FilePayload, RapiClient
from kstlib.rapi.config import (
    ApiConfig,
    EndpointConfig,
    MultipartConfig,
    RapiConfigManager,
)
from kstlib.rapi.exceptions import RequestError


class TestMultipartConfig:
    """Tests for MultipartConfig dataclass."""

    def test_default_values(self) -> None:
        """Default config uses field_name='file' and auto content_type."""
        config = MultipartConfig()
        assert config.field_name == "file"
        assert config.content_type is None

    def test_custom_values(self) -> None:
        """Custom field_name and content_type are preserved."""
        config = MultipartConfig(field_name="dataFile", content_type="application/zip")
        assert config.field_name == "dataFile"
        assert config.content_type == "application/zip"

    def test_invalid_field_name_empty(self) -> None:
        """Empty field_name raises ValueError."""
        with pytest.raises(ValueError, match="field_name must be"):
            MultipartConfig(field_name="")

    def test_invalid_field_name_too_long(self) -> None:
        """Excessively long field_name raises ValueError."""
        with pytest.raises(ValueError, match="field_name must be"):
            MultipartConfig(field_name="x" * 200)


class TestFilePayload:
    """Tests for FilePayload dataclass."""

    def test_default_field_name(self) -> None:
        """Default field_name is 'file'."""
        payload = FilePayload(filename="test.json", data=b"{}", content_type="application/json")
        assert payload.field_name == "file"

    def test_custom_field_name(self) -> None:
        """Custom field_name is preserved."""
        payload = FilePayload(
            filename="test.json",
            data=b"{}",
            content_type="application/json",
            field_name="upload",
        )
        assert payload.field_name == "upload"


class TestEndpointConfigMultipart:
    """Tests for EndpointConfig multipart features."""

    def test_is_multipart_true(self) -> None:
        """Endpoint with multipart/form-data Content-Type is detected."""
        ep = EndpointConfig(
            name="upload",
            api_name="test",
            path="/upload",
            method="POST",
            headers={"Content-Type": "multipart/form-data"},
        )
        assert ep.is_multipart is True

    def test_is_multipart_false(self) -> None:
        """Endpoint without multipart Content-Type is not detected."""
        ep = EndpointConfig(
            name="create",
            api_name="test",
            path="/create",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        assert ep.is_multipart is False

    def test_is_multipart_no_content_type(self) -> None:
        """Endpoint without Content-Type header is not multipart."""
        ep = EndpointConfig(name="get", api_name="test", path="/get")
        assert ep.is_multipart is False

    def test_is_multipart_case_insensitive(self) -> None:
        """Multipart detection is case-insensitive."""
        ep = EndpointConfig(
            name="upload",
            api_name="test",
            path="/upload",
            method="POST",
            headers={"Content-Type": "Multipart/Form-Data"},
        )
        assert ep.is_multipart is True

    def test_multipart_config_stored(self) -> None:
        """MultipartConfig is stored on endpoint."""
        mp = MultipartConfig(field_name="dataFile")
        ep = EndpointConfig(
            name="upload",
            api_name="test",
            path="/upload",
            method="POST",
            multipart=mp,
        )
        assert ep.multipart is not None
        assert ep.multipart.field_name == "dataFile"


class TestMultipartConfigParsing:
    """Tests for multipart config parsing from YAML."""

    def test_parse_multipart_dict(self) -> None:
        """Multipart config parsed from dict in YAML."""
        config = {
            "api": {
                "test": {
                    "base_url": "https://example.com",
                    "endpoints": {
                        "upload": {
                            "path": "/upload",
                            "method": "POST",
                            "headers": {"Content-Type": "multipart/form-data"},
                            "multipart": {"field_name": "dataFile", "content_type": "application/zip"},
                        },
                    },
                }
            }
        }
        manager = RapiConfigManager(config)
        ep = manager.apis["test"].endpoints["upload"]
        assert ep.multipart is not None
        assert ep.multipart.field_name == "dataFile"
        assert ep.multipart.content_type == "application/zip"

    def test_parse_multipart_true(self) -> None:
        """Multipart: true uses defaults."""
        config = {
            "api": {
                "test": {
                    "base_url": "https://example.com",
                    "endpoints": {
                        "upload": {
                            "path": "/upload",
                            "method": "POST",
                            "headers": {"Content-Type": "multipart/form-data"},
                            "multipart": True,
                        },
                    },
                }
            }
        }
        manager = RapiConfigManager(config)
        ep = manager.apis["test"].endpoints["upload"]
        assert ep.multipart is not None
        assert ep.multipart.field_name == "file"

    def test_parse_no_multipart(self) -> None:
        """Endpoint without multipart section has None."""
        config = {
            "api": {
                "test": {
                    "base_url": "https://example.com",
                    "endpoints": {
                        "create": {"path": "/create", "method": "POST"},
                    },
                }
            }
        }
        manager = RapiConfigManager(config)
        ep = manager.apis["test"].endpoints["create"]
        assert ep.multipart is None


class TestPrepareMultipart:
    """Tests for RapiClient._prepare_multipart()."""

    def _make_client(self) -> RapiClient:
        """Create a minimal client for testing."""
        config = {
            "api": {
                "test": {
                    "base_url": "https://example.com",
                    "endpoints": {
                        "upload": {
                            "path": "/upload",
                            "method": "POST",
                            "headers": {"Content-Type": "multipart/form-data"},
                        },
                    },
                }
            }
        }
        return RapiClient(config_manager=RapiConfigManager(config))

    def _make_endpoint(self, **kwargs: object) -> EndpointConfig:
        """Create a multipart endpoint config."""
        defaults: dict[str, object] = {
            "name": "upload",
            "api_name": "test",
            "path": "/upload",
            "method": "POST",
            "headers": {"Content-Type": "multipart/form-data"},
        }
        defaults.update(kwargs)
        return EndpointConfig(**defaults)  # type: ignore[arg-type]

    def test_prepare_from_file_ref(self, tmp_path: Path) -> None:
        """File reference (@path) reads binary content."""
        test_file = tmp_path / "data.json"
        test_file.write_bytes(b'{"key": "value"}')

        client = self._make_client()
        ep = self._make_endpoint()
        result = client._prepare_multipart(f"@{test_file}", ep)

        assert len(result) == 1
        field_name, (filename, data, content_type) = result[0]
        assert field_name == "file"
        assert filename == "data.json"
        assert data == b'{"key": "value"}'
        assert content_type == "application/json"

    def test_prepare_from_file_payload(self) -> None:
        """FilePayload is used directly."""
        client = self._make_client()
        ep = self._make_endpoint()
        payload = FilePayload(
            filename="report.csv",
            data=b"a,b\n1,2",
            content_type="text/csv",
            field_name="upload",
        )
        result = client._prepare_multipart(payload, ep)

        assert len(result) == 1
        field_name, (filename, data, content_type) = result[0]
        assert field_name == "upload"
        assert filename == "report.csv"
        assert data == b"a,b\n1,2"
        assert content_type == "text/csv"

    def test_prepare_file_not_found(self) -> None:
        """Missing file raises RequestError."""
        client = self._make_client()
        ep = self._make_endpoint()
        with pytest.raises(RequestError, match="File not found"):
            client._prepare_multipart("@/nonexistent/file.json", ep)

    def test_prepare_invalid_body_dict(self) -> None:
        """Dict body raises RequestError for multipart."""
        client = self._make_client()
        ep = self._make_endpoint()
        with pytest.raises(RequestError, match="requires a file body"):
            client._prepare_multipart({"key": "value"}, ep)

    def test_prepare_invalid_body_none(self) -> None:
        """None body raises RequestError for multipart."""
        client = self._make_client()
        ep = self._make_endpoint()
        with pytest.raises(RequestError, match="requires a file body"):
            client._prepare_multipart(None, ep)

    def test_prepare_auto_detect_mime_zip(self, tmp_path: Path) -> None:
        """ZIP file gets a zip-related MIME type."""
        test_file = tmp_path / "archive.zip"
        test_file.write_bytes(b"PK\x03\x04fake")

        client = self._make_client()
        ep = self._make_endpoint()
        result = client._prepare_multipart(f"@{test_file}", ep)

        _, (_, _, content_type) = result[0]
        assert "zip" in content_type

    def test_prepare_auto_detect_mime_unknown(self, tmp_path: Path) -> None:
        """Unknown extension falls back to application/octet-stream."""
        test_file = tmp_path / "data.k51binary"
        test_file.write_bytes(b"\x00\x01\x02")

        client = self._make_client()
        ep = self._make_endpoint()
        result = client._prepare_multipart(f"@{test_file}", ep)

        _, (_, _, content_type) = result[0]
        assert content_type == "application/octet-stream"

    def test_prepare_custom_content_type(self, tmp_path: Path) -> None:
        """MultipartConfig content_type overrides auto-detection."""
        test_file = tmp_path / "data.json"
        test_file.write_bytes(b"{}")

        client = self._make_client()
        mp = MultipartConfig(content_type="application/octet-stream")
        ep = self._make_endpoint(multipart=mp)
        result = client._prepare_multipart(f"@{test_file}", ep)

        _, (_, _, content_type) = result[0]
        assert content_type == "application/octet-stream"

    def test_prepare_custom_field_name(self, tmp_path: Path) -> None:
        """MultipartConfig field_name is used."""
        test_file = tmp_path / "data.json"
        test_file.write_bytes(b"{}")

        client = self._make_client()
        mp = MultipartConfig(field_name="dataFile")
        ep = self._make_endpoint(multipart=mp)
        result = client._prepare_multipart(f"@{test_file}", ep)

        field_name, _ = result[0]
        assert field_name == "dataFile"

    def test_prepare_file_too_large(self, tmp_path: Path) -> None:
        """File exceeding max_upload_size raises RequestError."""
        test_file = tmp_path / "huge.bin"
        test_file.write_bytes(b"x" * 1000)

        client = self._make_client()
        # Override limits to a small value
        with patch.object(
            type(client),
            "_prepare_multipart",
            wraps=client._prepare_multipart,
        ):
            from kstlib.limits import RapiLimits

            small_limits = RapiLimits(
                timeout=30.0,
                max_response_size=1000000,
                max_retries=0,
                retry_delay=1.0,
                retry_backoff=1.0,
                max_upload_size=500,
            )
            with patch("kstlib.rapi.client.get_rapi_limits", return_value=small_limits):
                ep = self._make_endpoint()
                with pytest.raises(RequestError, match="File too large"):
                    client._prepare_multipart(f"@{test_file}", ep)


class TestBuildRequestMultipart:
    """Tests for multipart branch in _build_request."""

    def _make_client_and_configs(self) -> tuple[RapiClient, ApiConfig, EndpointConfig]:
        """Create client with multipart endpoint."""
        config = {
            "api": {
                "test": {
                    "base_url": "https://example.com",
                    "endpoints": {
                        "upload": {
                            "path": "/upload",
                            "method": "POST",
                            "headers": {
                                "Content-Type": "multipart/form-data",
                                "Accept": "application/json",
                            },
                        },
                    },
                }
            }
        }
        manager = RapiConfigManager(config)
        client = RapiClient(config_manager=manager)
        api_config = manager.apis["test"]
        ep_config = api_config.endpoints["upload"]
        return client, api_config, ep_config

    def test_build_multipart_uses_files_param(self, tmp_path: Path) -> None:
        """Multipart request uses httpx files= parameter."""
        test_file = tmp_path / "data.json"
        test_file.write_bytes(b'{"key": "value"}')

        client, api_config, ep_config = self._make_client_and_configs()
        request = client._build_request(api_config, ep_config, (), {}, f"@{test_file}", None)

        assert request.method == "POST"
        # httpx generates multipart content-type with boundary
        ct = request.headers.get("content-type", "")
        assert "multipart/form-data" in ct
        assert "boundary" in ct

    def test_build_multipart_preserves_accept(self, tmp_path: Path) -> None:
        """Accept header is preserved in multipart requests."""
        test_file = tmp_path / "data.json"
        test_file.write_bytes(b"{}")

        client, api_config, ep_config = self._make_client_and_configs()
        request = client._build_request(api_config, ep_config, (), {}, f"@{test_file}", None)

        assert request.headers.get("accept") == "application/json"

    def test_build_normal_request_unchanged(self) -> None:
        """Non-multipart request still uses content= parameter."""
        config = {
            "api": {
                "test": {
                    "base_url": "https://example.com",
                    "endpoints": {
                        "create": {
                            "path": "/create",
                            "method": "POST",
                        },
                    },
                }
            }
        }
        manager = RapiConfigManager(config)
        client = RapiClient(config_manager=manager)
        api_config = manager.apis["test"]
        ep_config = api_config.endpoints["create"]

        request = client._build_request(api_config, ep_config, (), {}, {"key": "value"}, None)

        assert request.method == "POST"
        ct = request.headers.get("content-type", "")
        assert ct == "application/json"
