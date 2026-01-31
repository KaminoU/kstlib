"""Tests for kstlib.rapi.credentials module."""

import json
import os
import tempfile
from unittest import mock

import pytest

from kstlib.rapi.credentials import CredentialRecord, CredentialResolver
from kstlib.rapi.exceptions import CredentialError


class TestCredentialRecord:
    """Tests for CredentialRecord dataclass."""

    def test_basic_creation(self) -> None:
        """Create record with value only."""
        record = CredentialRecord(value="token123")
        assert record.value == "token123"
        assert record.secret is None
        assert record.source == "unknown"
        assert record.expires_at is None

    def test_full_creation(self) -> None:
        """Create record with all fields."""
        record = CredentialRecord(
            value="key123",
            secret="secret456",
            source="env",
            expires_at=1234567890.0,
        )
        assert record.value == "key123"
        assert record.secret == "secret456"
        assert record.source == "env"
        assert record.expires_at == 1234567890.0

    def test_creation_with_extras(self) -> None:
        """Create record with extras dict."""
        record = CredentialRecord(
            value="key123",
            secret="secret456",
            source="sops",
            extras={"passphrase": "pass123", "account_id": "acc001"},
        )
        assert record.value == "key123"
        assert record.secret == "secret456"
        assert record.extras == {"passphrase": "pass123", "account_id": "acc001"}
        assert record.extras.get("passphrase") == "pass123"

    def test_extras_default_empty(self) -> None:
        """Extras defaults to empty dict."""
        record = CredentialRecord(value="key")
        assert record.extras == {}

    def test_immutable(self) -> None:
        """Verify record is frozen (immutable)."""
        record = CredentialRecord(value="test")
        with pytest.raises(AttributeError):
            record.value = "changed"  # type: ignore[misc]


class TestCredentialResolverExtractValue:
    """Tests for CredentialResolver.extract_value static method."""

    def test_simple_key(self) -> None:
        """Extract simple key from dict."""
        data = {"foo": "bar"}
        assert CredentialResolver.extract_value(data, ".foo") == "bar"

    def test_nested_key(self) -> None:
        """Extract nested key from dict."""
        data = {"foo": {"bar": {"baz": "value"}}}
        assert CredentialResolver.extract_value(data, ".foo.bar.baz") == "value"

    def test_array_index(self) -> None:
        """Extract array element."""
        data = {"items": [1, 2, 3]}
        assert CredentialResolver.extract_value(data, ".items[1]") == 2

    def test_root_array_index(self) -> None:
        """Extract from root array."""
        data = [1, 2, 3]
        assert CredentialResolver.extract_value(data, ".[0]") == 1

    def test_complex_path(self) -> None:
        """Extract using complex path with nested arrays."""
        data = {"foo": {"bar": [{"baz": "value1"}, {"baz": "value2"}]}}
        assert CredentialResolver.extract_value(data, ".foo.bar[1].baz") == "value2"

    def test_missing_key_returns_none(self) -> None:
        """Return None for missing key."""
        data = {"foo": "bar"}
        assert CredentialResolver.extract_value(data, ".missing") is None

    def test_missing_array_index_returns_none(self) -> None:
        """Return None for out-of-bounds array index."""
        data = {"items": [1, 2]}
        assert CredentialResolver.extract_value(data, ".items[10]") is None

    def test_empty_path_returns_data(self) -> None:
        """Return data itself for empty path."""
        data = {"foo": "bar"}
        assert CredentialResolver.extract_value(data, "") == data
        assert CredentialResolver.extract_value(data, ".") == data

    def test_none_data_returns_none(self) -> None:
        """Return None for None data."""
        assert CredentialResolver.extract_value(None, ".foo") is None


class TestCredentialResolverEnv:
    """Tests for CredentialResolver env type resolution."""

    def test_resolve_env_single_var(self) -> None:
        """Resolve credential from single environment variable."""
        config = {
            "github": {
                "type": "env",
                "var": "TEST_GITHUB_TOKEN",
            }
        }
        resolver = CredentialResolver(config)

        with mock.patch.dict(os.environ, {"TEST_GITHUB_TOKEN": "ghp_abc123"}):
            record = resolver.resolve("github")

        assert record.value == "ghp_abc123"
        assert record.source == "env"
        assert record.secret is None

    def test_resolve_env_key_secret_pair(self) -> None:
        """Resolve credential with key+secret from environment."""
        config = {
            "kraken": {
                "type": "env",
                "var_key": "TEST_KRAKEN_KEY",
                "var_secret": "TEST_KRAKEN_SECRET",
            }
        }
        resolver = CredentialResolver(config)

        with mock.patch.dict(
            os.environ,
            {
                "TEST_KRAKEN_KEY": "api_key_123",
                "TEST_KRAKEN_SECRET": "secret_456",
            },
        ):
            record = resolver.resolve("kraken")

        assert record.value == "api_key_123"
        assert record.secret == "secret_456"
        assert record.source == "env"

    def test_resolve_env_missing_var(self) -> None:
        """Raise CredentialError when environment variable not set."""
        config = {"github": {"type": "env", "var": "MISSING_VAR"}}
        resolver = CredentialResolver(config)

        with mock.patch.dict(os.environ, {}, clear=True):
            with pytest.raises(CredentialError) as exc_info:
                resolver.resolve("github")
            assert "MISSING_VAR" in str(exc_info.value)

    def test_resolve_env_missing_secret_var(self) -> None:
        """Raise CredentialError when secret variable not set."""
        config = {
            "api": {
                "type": "env",
                "var_key": "TEST_KEY",
                "var_secret": "MISSING_SECRET",
            }
        }
        resolver = CredentialResolver(config)

        with mock.patch.dict(os.environ, {"TEST_KEY": "key123"}, clear=True):
            with pytest.raises(CredentialError) as exc_info:
                resolver.resolve("api")
            assert "MISSING_SECRET" in str(exc_info.value)

    def test_resolve_env_missing_config(self) -> None:
        """Raise CredentialError when var/var_key missing from config."""
        config = {"bad": {"type": "env"}}  # Missing var or var_key
        resolver = CredentialResolver(config)

        with pytest.raises(CredentialError) as exc_info:
            resolver.resolve("bad")
        assert "var" in str(exc_info.value).lower()


class TestCredentialResolverFile:
    """Tests for CredentialResolver file type resolution."""

    def test_resolve_file_json_token_path(self) -> None:
        """Resolve credential from JSON file with token_path."""
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
        ) as f:
            json.dump({"access_token": "token123"}, f)
            temp_path = f.name

        try:
            config = {
                "azure": {
                    "type": "file",
                    "path": temp_path,
                    "token_path": ".access_token",
                }
            }
            resolver = CredentialResolver(config)
            record = resolver.resolve("azure")

            assert record.value == "token123"
            assert record.source == "file"
        finally:
            os.unlink(temp_path)

    def test_resolve_file_json_key_secret(self) -> None:
        """Resolve credential from JSON file with key_field and secret_field."""
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
        ) as f:
            json.dump({"api_key": "key123", "api_secret": "secret456"}, f)
            temp_path = f.name

        try:
            config = {
                "api": {
                    "type": "file",
                    "path": temp_path,
                    "key_field": "api_key",
                    "secret_field": "api_secret",
                }
            }
            resolver = CredentialResolver(config)
            record = resolver.resolve("api")

            assert record.value == "key123"
            assert record.secret == "secret456"
            assert record.source == "file"
        finally:
            os.unlink(temp_path)

    def test_resolve_file_nested_path(self) -> None:
        """Resolve credential from nested JSON structure."""
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
        ) as f:
            json.dump({"auth": {"tokens": [{"value": "nested_token"}]}}, f)
            temp_path = f.name

        try:
            config = {
                "nested": {
                    "type": "file",
                    "path": temp_path,
                    "token_path": ".auth.tokens[0].value",
                }
            }
            resolver = CredentialResolver(config)
            record = resolver.resolve("nested")

            assert record.value == "nested_token"
        finally:
            os.unlink(temp_path)

    def test_resolve_file_missing_file(self) -> None:
        """Raise CredentialError when file not found."""
        config = {
            "missing": {
                "type": "file",
                "path": "/nonexistent/path.json",
                "token_path": ".token",
            }
        }
        resolver = CredentialResolver(config)

        with pytest.raises(CredentialError) as exc_info:
            resolver.resolve("missing")
        assert "not found" in str(exc_info.value).lower()

    def test_resolve_file_missing_path_config(self) -> None:
        """Raise CredentialError when path missing from config."""
        config = {"bad": {"type": "file", "token_path": ".token"}}
        resolver = CredentialResolver(config)

        with pytest.raises(CredentialError) as exc_info:
            resolver.resolve("bad")
        assert "path" in str(exc_info.value).lower()

    def test_resolve_file_missing_token_path_in_file(self) -> None:
        """Raise CredentialError when token_path not found in file."""
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
        ) as f:
            json.dump({"other": "data"}, f)
            temp_path = f.name

        try:
            config = {
                "azure": {
                    "type": "file",
                    "path": temp_path,
                    "token_path": ".missing_field",
                }
            }
            resolver = CredentialResolver(config)

            with pytest.raises(CredentialError) as exc_info:
                resolver.resolve("azure")
            assert "not found" in str(exc_info.value).lower()
        finally:
            os.unlink(temp_path)


class TestCredentialResolverCache:
    """Tests for CredentialResolver caching."""

    def test_cache_hit(self) -> None:
        """Verify credentials are cached after first resolution."""
        config = {"github": {"type": "env", "var": "TEST_TOKEN"}}
        resolver = CredentialResolver(config)

        with mock.patch.dict(os.environ, {"TEST_TOKEN": "cached_value"}):
            record1 = resolver.resolve("github")

        # Even without env var, should return cached value
        with mock.patch.dict(os.environ, {}, clear=True):
            record2 = resolver.resolve("github")

        assert record1 is record2  # Same object
        assert record2.value == "cached_value"

    def test_clear_cache(self) -> None:
        """Verify cache can be cleared."""
        config = {"github": {"type": "env", "var": "TEST_TOKEN"}}
        resolver = CredentialResolver(config)

        with mock.patch.dict(os.environ, {"TEST_TOKEN": "value1"}):
            record1 = resolver.resolve("github")

        resolver.clear_cache()

        with mock.patch.dict(os.environ, {"TEST_TOKEN": "value2"}):
            record2 = resolver.resolve("github")

        assert record1.value == "value1"
        assert record2.value == "value2"


class TestCredentialResolverNotFound:
    """Tests for CredentialResolver error handling."""

    def test_credential_not_in_config(self) -> None:
        """Raise CredentialError when credential not found in config."""
        config = {"github": {"type": "env", "var": "TOKEN"}}
        resolver = CredentialResolver(config)

        with pytest.raises(CredentialError) as exc_info:
            resolver.resolve("unknown")
        assert "not found" in str(exc_info.value).lower()

    def test_unknown_credential_type(self) -> None:
        """Raise CredentialError for unknown credential type."""
        config = {"bad": {"type": "unknown_type"}}
        resolver = CredentialResolver(config)

        with pytest.raises(CredentialError) as exc_info:
            resolver.resolve("bad")
        assert "unknown" in str(exc_info.value).lower()

    def test_empty_config(self) -> None:
        """Handle empty configuration gracefully."""
        resolver = CredentialResolver({})

        with pytest.raises(CredentialError):
            resolver.resolve("any")

    def test_none_config(self) -> None:
        """Handle None configuration gracefully."""
        resolver = CredentialResolver(None)

        with pytest.raises(CredentialError):
            resolver.resolve("any")


class TestCredentialResolverExpiresAt:
    """Tests for expires_at extraction and parsing."""

    def test_parse_expires_at_int(self) -> None:
        """Parse integer timestamp."""
        result = CredentialResolver._parse_expires_at(1704067200)
        assert result == 1704067200.0

    def test_parse_expires_at_float(self) -> None:
        """Parse float timestamp."""
        result = CredentialResolver._parse_expires_at(1704067200.5)
        assert result == 1704067200.5

    def test_parse_expires_at_iso_string(self) -> None:
        """Parse ISO 8601 string."""
        result = CredentialResolver._parse_expires_at("2024-01-01T00:00:00+00:00")
        assert result is not None
        assert result == 1704067200.0

    def test_parse_expires_at_iso_string_z(self) -> None:
        """Parse ISO 8601 string with Z suffix."""
        result = CredentialResolver._parse_expires_at("2024-01-01T00:00:00Z")
        assert result is not None
        assert result == 1704067200.0

    def test_parse_expires_at_numeric_string(self) -> None:
        """Parse numeric string."""
        result = CredentialResolver._parse_expires_at("1704067200")
        assert result == 1704067200.0

    def test_parse_expires_at_invalid_string(self) -> None:
        """Return None for invalid string."""
        result = CredentialResolver._parse_expires_at("not-a-date")
        assert result is None

    def test_parse_expires_at_none(self) -> None:
        """Return None for None input."""
        result = CredentialResolver._parse_expires_at(None)
        assert result is None

    def test_resolve_file_with_expires_at(self) -> None:
        """Resolve credential with expires_at from file."""
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
        ) as f:
            json.dump(
                {"access_token": "token123", "expires_at": 1704067200},
                f,
            )
            temp_path = f.name

        try:
            config = {
                "api": {
                    "type": "file",
                    "path": temp_path,
                    "token_path": ".access_token",
                    "expires_at_path": ".expires_at",
                }
            }
            resolver = CredentialResolver(config)
            record = resolver.resolve("api")

            assert record.value == "token123"
            assert record.expires_at == 1704067200.0
        finally:
            os.unlink(temp_path)

    def test_resolve_file_with_expires_at_iso(self) -> None:
        """Resolve credential with ISO expires_at from file."""
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
        ) as f:
            json.dump(
                {
                    "access_token": "token123",
                    "expires_at": "2024-01-01T00:00:00Z",
                },
                f,
            )
            temp_path = f.name

        try:
            config = {
                "api": {
                    "type": "file",
                    "path": temp_path,
                    "token_path": ".access_token",
                    "expires_at_path": ".expires_at",
                }
            }
            resolver = CredentialResolver(config)
            record = resolver.resolve("api")

            assert record.value == "token123"
            assert record.expires_at == 1704067200.0
        finally:
            os.unlink(temp_path)

    def test_resolve_file_without_expires_at_path(self) -> None:
        """Resolve credential without expires_at when not configured."""
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
        ) as f:
            json.dump({"access_token": "token123", "expires_at": 1234567890}, f)
            temp_path = f.name

        try:
            config = {
                "api": {
                    "type": "file",
                    "path": temp_path,
                    "token_path": ".access_token",
                    # No expires_at_path configured
                }
            }
            resolver = CredentialResolver(config)
            record = resolver.resolve("api")

            assert record.value == "token123"
            assert record.expires_at is None  # Not extracted
        finally:
            os.unlink(temp_path)

    def test_resolve_file_key_field_with_expires_at(self) -> None:
        """Resolve credential with key_field and expires_at."""
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
        ) as f:
            json.dump(
                {
                    "api_key": "key123",
                    "api_secret": "secret456",
                    "expires_at": 1704067200,
                },
                f,
            )
            temp_path = f.name

        try:
            config = {
                "api": {
                    "type": "file",
                    "path": temp_path,
                    "key_field": "api_key",
                    "secret_field": "api_secret",
                    "expires_at_path": ".expires_at",
                }
            }
            resolver = CredentialResolver(config)
            record = resolver.resolve("api")

            assert record.value == "key123"
            assert record.secret == "secret456"
            assert record.expires_at == 1704067200.0
        finally:
            os.unlink(temp_path)


class TestCredentialResolverYaml:
    """Tests for YAML file resolution."""

    def test_resolve_yaml_file(self) -> None:
        """Resolve credential from YAML file."""
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".yaml",
            delete=False,
        ) as f:
            f.write("access_token: yaml_token_123\n")
            temp_path = f.name

        try:
            config = {
                "api": {
                    "type": "file",
                    "path": temp_path,
                    "token_path": ".access_token",
                }
            }
            resolver = CredentialResolver(config)
            record = resolver.resolve("api")

            assert record.value == "yaml_token_123"
            assert record.source == "file"
        finally:
            os.unlink(temp_path)

    def test_resolve_yml_file(self) -> None:
        """Resolve credential from .yml file."""
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".yml",
            delete=False,
        ) as f:
            f.write("api_key: yml_key_456\napi_secret: yml_secret_789\n")
            temp_path = f.name

        try:
            config = {
                "api": {
                    "type": "file",
                    "path": temp_path,
                    "key_field": "api_key",
                    "secret_field": "api_secret",
                }
            }
            resolver = CredentialResolver(config)
            record = resolver.resolve("api")

            assert record.value == "yml_key_456"
            assert record.secret == "yml_secret_789"
        finally:
            os.unlink(temp_path)


class TestCredentialResolverFileEdgeCases:
    """Tests for file resolution edge cases."""

    def test_resolve_file_missing_token_path_and_key_field(self) -> None:
        """Raise CredentialError when neither token_path nor key_field provided."""
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
        ) as f:
            json.dump({"some": "data"}, f)
            temp_path = f.name

        try:
            config = {
                "api": {
                    "type": "file",
                    "path": temp_path,
                    # No token_path or key_field
                }
            }
            resolver = CredentialResolver(config)

            with pytest.raises(CredentialError) as exc_info:
                resolver.resolve("api")
            assert "token_path" in str(exc_info.value).lower() or "key_field" in str(exc_info.value).lower()
        finally:
            os.unlink(temp_path)

    def test_resolve_file_key_field_missing_in_data(self) -> None:
        """Raise CredentialError when key_field not found in file."""
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
        ) as f:
            json.dump({"other": "data"}, f)
            temp_path = f.name

        try:
            config = {
                "api": {
                    "type": "file",
                    "path": temp_path,
                    "key_field": "missing_key",
                }
            }
            resolver = CredentialResolver(config)

            with pytest.raises(CredentialError) as exc_info:
                resolver.resolve("api")
            assert "not found" in str(exc_info.value).lower()
        finally:
            os.unlink(temp_path)

    def test_resolve_file_secret_field_missing_in_data(self) -> None:
        """Raise CredentialError when secret_field not found in file."""
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
        ) as f:
            json.dump({"api_key": "key123"}, f)
            temp_path = f.name

        try:
            config = {
                "api": {
                    "type": "file",
                    "path": temp_path,
                    "key_field": "api_key",
                    "secret_field": "missing_secret",
                }
            }
            resolver = CredentialResolver(config)

            with pytest.raises(CredentialError) as exc_info:
                resolver.resolve("api")
            assert "not found" in str(exc_info.value).lower()
        finally:
            os.unlink(temp_path)

    def test_resolve_file_invalid_json(self) -> None:
        """Raise CredentialError when file contains invalid JSON."""
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
        ) as f:
            f.write("not valid json {{{")
            temp_path = f.name

        try:
            config = {
                "api": {
                    "type": "file",
                    "path": temp_path,
                    "token_path": ".token",
                }
            }
            resolver = CredentialResolver(config)

            with pytest.raises(CredentialError) as exc_info:
                resolver.resolve("api")
            assert "failed to read" in str(exc_info.value).lower()
        finally:
            os.unlink(temp_path)


class TestCredentialResolverSops:
    """Tests for SOPS credential resolution."""

    def test_resolve_sops_token_path(self) -> None:
        """Resolve credential from SOPS file with token_path."""
        mock_record = mock.MagicMock()
        mock_record.value = "sops_token_123"

        config = {
            "api": {
                "type": "sops",
                "path": "secrets.sops.json",
                "token_path": ".access_token",
            }
        }
        resolver = CredentialResolver(config)

        with mock.patch("kstlib.secrets.resolve_secret", return_value=mock_record):
            record = resolver.resolve("api")

        assert record.value == "sops_token_123"
        assert record.source == "sops"

    def test_resolve_sops_key_field(self) -> None:
        """Resolve credential from SOPS file with key_field."""
        mock_key_record = mock.MagicMock()
        mock_key_record.value = "sops_key"
        mock_secret_record = mock.MagicMock()
        mock_secret_record.value = "sops_secret"

        config = {
            "api": {
                "type": "sops",
                "path": "secrets.sops.json",
                "key_field": "api_key",
                "secret_field": "api_secret",
            }
        }
        resolver = CredentialResolver(config)

        with mock.patch(
            "kstlib.secrets.resolve_secret",
            side_effect=[mock_key_record, mock_secret_record],
        ):
            record = resolver.resolve("api")

        assert record.value == "sops_key"
        assert record.secret == "sops_secret"
        assert record.source == "sops"

    def test_resolve_sops_key_field_only(self) -> None:
        """Resolve credential from SOPS file with key_field only (no secret)."""
        mock_record = mock.MagicMock()
        mock_record.value = "sops_key_only"

        config = {
            "api": {
                "type": "sops",
                "path": "secrets.sops.json",
                "key_field": "api_key",
            }
        }
        resolver = CredentialResolver(config)

        with mock.patch("kstlib.secrets.resolve_secret", return_value=mock_record):
            record = resolver.resolve("api")

        assert record.value == "sops_key_only"
        assert record.secret is None
        assert record.source == "sops"

    def test_resolve_sops_missing_path(self) -> None:
        """Raise CredentialError when path missing from sops config."""
        config = {
            "api": {
                "type": "sops",
                "key_field": "api_key",
            }
        }
        resolver = CredentialResolver(config)

        with pytest.raises(CredentialError) as exc_info:
            resolver.resolve("api")
        assert "path" in str(exc_info.value).lower()

    def test_resolve_sops_missing_token_path_and_key_field(self) -> None:
        """Raise CredentialError when neither token_path nor key_field provided."""
        config = {
            "api": {
                "type": "sops",
                "path": "secrets.sops.json",
            }
        }
        resolver = CredentialResolver(config)

        with pytest.raises(CredentialError) as exc_info:
            resolver.resolve("api")
        assert "token_path" in str(exc_info.value).lower() or "key_field" in str(exc_info.value).lower()

    def test_resolve_sops_resolution_error(self) -> None:
        """Raise CredentialError when SOPS resolution fails."""
        config = {
            "api": {
                "type": "sops",
                "path": "secrets.sops.json",
                "token_path": ".token",
            }
        }
        resolver = CredentialResolver(config)

        with mock.patch(
            "kstlib.secrets.resolve_secret",
            side_effect=RuntimeError("SOPS decryption failed"),
        ):
            with pytest.raises(CredentialError) as exc_info:
                resolver.resolve("api")
            assert "sops" in str(exc_info.value).lower()

    def test_resolve_sops_key_field_error(self) -> None:
        """Raise CredentialError when key_field resolution fails."""
        config = {
            "api": {
                "type": "sops",
                "path": "secrets.sops.json",
                "key_field": "api_key",
            }
        }
        resolver = CredentialResolver(config)

        with mock.patch(
            "kstlib.secrets.resolve_secret",
            side_effect=RuntimeError("Key not found"),
        ):
            with pytest.raises(CredentialError) as exc_info:
                resolver.resolve("api")
            assert "sops" in str(exc_info.value).lower()

    def test_resolve_sops_secret_field_error(self) -> None:
        """Raise CredentialError when secret_field resolution fails."""
        mock_key_record = mock.MagicMock()
        mock_key_record.value = "key_value"

        config = {
            "api": {
                "type": "sops",
                "path": "secrets.sops.json",
                "key_field": "api_key",
                "secret_field": "api_secret",
            }
        }
        resolver = CredentialResolver(config)

        # First call succeeds (key), second fails (secret)
        with mock.patch(
            "kstlib.secrets.resolve_secret",
            side_effect=[mock_key_record, RuntimeError("Secret not found")],
        ):
            with pytest.raises(CredentialError) as exc_info:
                resolver.resolve("api")
            assert "sops" in str(exc_info.value).lower()


class TestCredentialResolverProvider:
    """Tests for provider credential resolution."""

    def test_resolve_provider_success(self) -> None:
        """Resolve credential from kstlib.auth provider."""
        from datetime import datetime, timezone

        mock_token = mock.MagicMock()
        mock_token.access_token = "provider_access_token"
        mock_token.is_expired = False
        mock_token.expires_at = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        mock_storage = mock.MagicMock()
        mock_storage.load.return_value = mock_token

        config = {
            "corp": {
                "type": "provider",
                "provider": "corporate",
            }
        }
        resolver = CredentialResolver(config)

        with mock.patch(
            "kstlib.auth.get_token_storage_from_config",
            return_value=mock_storage,
        ):
            record = resolver.resolve("corp")

        assert record.value == "provider_access_token"
        assert record.source == "provider"
        assert record.expires_at == 1704067200.0

    def test_resolve_provider_no_token(self) -> None:
        """Raise CredentialError when no token found."""
        mock_storage = mock.MagicMock()
        mock_storage.load.return_value = None

        config = {
            "corp": {
                "type": "provider",
                "provider": "corporate",
            }
        }
        resolver = CredentialResolver(config)

        with mock.patch(
            "kstlib.auth.get_token_storage_from_config",
            return_value=mock_storage,
        ):
            with pytest.raises(CredentialError) as exc_info:
                resolver.resolve("corp")
            assert "no valid token" in str(exc_info.value).lower()

    def test_resolve_provider_empty_access_token(self) -> None:
        """Raise CredentialError when access_token is empty."""
        mock_token = mock.MagicMock()
        mock_token.access_token = ""

        mock_storage = mock.MagicMock()
        mock_storage.load.return_value = mock_token

        config = {
            "corp": {
                "type": "provider",
                "provider": "corporate",
            }
        }
        resolver = CredentialResolver(config)

        with mock.patch(
            "kstlib.auth.get_token_storage_from_config",
            return_value=mock_storage,
        ):
            with pytest.raises(CredentialError) as exc_info:
                resolver.resolve("corp")
            assert "no valid token" in str(exc_info.value).lower()

    def test_resolve_provider_expired_refreshable(self) -> None:
        """Refresh expired token when refreshable."""
        from datetime import datetime, timezone

        mock_expired_token = mock.MagicMock()
        mock_expired_token.access_token = "old_token"
        mock_expired_token.is_expired = True
        mock_expired_token.is_refreshable = True

        mock_refreshed_token = mock.MagicMock()
        mock_refreshed_token.access_token = "new_token"
        mock_refreshed_token.is_expired = False
        mock_refreshed_token.expires_at = datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc)

        mock_storage = mock.MagicMock()
        mock_storage.load.return_value = mock_expired_token

        mock_provider = mock.MagicMock()
        mock_provider.refresh.return_value = mock_refreshed_token

        config = {
            "corp": {
                "type": "provider",
                "provider": "corporate",
            }
        }
        resolver = CredentialResolver(config)

        with (
            mock.patch(
                "kstlib.auth.get_token_storage_from_config",
                return_value=mock_storage,
            ),
            mock.patch(
                "kstlib.auth.OIDCProvider",
            ) as mock_oidc_cls,
        ):
            mock_oidc_cls.from_config.return_value = mock_provider
            record = resolver.resolve("corp")

        assert record.value == "new_token"
        assert record.source == "provider"
        # Verify token was saved
        mock_storage.save.assert_called_once()

    def test_resolve_provider_expired_not_refreshable(self) -> None:
        """Raise CredentialError when expired token not refreshable."""
        mock_token = mock.MagicMock()
        mock_token.access_token = "old_token"
        mock_token.is_expired = True
        mock_token.is_refreshable = False

        mock_storage = mock.MagicMock()
        mock_storage.load.return_value = mock_token

        config = {
            "corp": {
                "type": "provider",
                "provider": "corporate",
            }
        }
        resolver = CredentialResolver(config)

        with mock.patch(
            "kstlib.auth.get_token_storage_from_config",
            return_value=mock_storage,
        ):
            with pytest.raises(CredentialError) as exc_info:
                resolver.resolve("corp")
            assert "expired" in str(exc_info.value).lower()

    def test_resolve_provider_missing_provider_name(self) -> None:
        """Raise CredentialError when provider name missing from config."""
        config = {
            "corp": {
                "type": "provider",
            }
        }
        resolver = CredentialResolver(config)

        with pytest.raises(CredentialError) as exc_info:
            resolver.resolve("corp")
        assert "provider" in str(exc_info.value).lower()

    def test_resolve_provider_import_error(self) -> None:
        """Raise CredentialError when kstlib.auth import fails."""
        config = {
            "corp": {
                "type": "provider",
                "provider": "corporate",
            }
        }
        resolver = CredentialResolver(config)

        with mock.patch(
            "kstlib.auth.get_token_storage_from_config",
            side_effect=ImportError("kstlib.auth not available"),
        ):
            with pytest.raises(CredentialError) as exc_info:
                resolver.resolve("corp")
            assert "not available" in str(exc_info.value).lower()

    def test_resolve_provider_generic_error(self) -> None:
        """Raise CredentialError on generic provider error."""
        config = {
            "corp": {
                "type": "provider",
                "provider": "corporate",
            }
        }
        resolver = CredentialResolver(config)

        with mock.patch(
            "kstlib.auth.get_token_storage_from_config",
            side_effect=RuntimeError("Something went wrong"),
        ):
            with pytest.raises(CredentialError) as exc_info:
                resolver.resolve("corp")
            assert "failed to get token" in str(exc_info.value).lower()

    def test_resolve_provider_no_expires_at(self) -> None:
        """Handle provider token without expires_at."""
        mock_token = mock.MagicMock()
        mock_token.access_token = "token_no_expiry"
        mock_token.is_expired = False
        mock_token.expires_at = None

        mock_storage = mock.MagicMock()
        mock_storage.load.return_value = mock_token

        config = {
            "corp": {
                "type": "provider",
                "provider": "corporate",
            }
        }
        resolver = CredentialResolver(config)

        with mock.patch(
            "kstlib.auth.get_token_storage_from_config",
            return_value=mock_storage,
        ):
            record = resolver.resolve("corp")

        assert record.value == "token_no_expiry"
        assert record.expires_at is None


class TestFieldsValidation:
    """Tests for fields mapping validation (deep defense)."""

    def test_validate_field_name_valid(self) -> None:
        """Accept valid field names."""
        from kstlib.rapi.credentials import _validate_field_name

        # Should not raise
        _validate_field_name("api_key", "test")
        _validate_field_name("secret", "test")
        _validate_field_name("passphrase_123", "test")
        _validate_field_name("a", "test")

    def test_validate_field_name_empty(self) -> None:
        """Reject empty field name."""
        from kstlib.rapi.credentials import _validate_field_name

        with pytest.raises(CredentialError) as exc_info:
            _validate_field_name("", "test")
        assert "Empty field name" in str(exc_info.value)

    def test_validate_field_name_too_long(self) -> None:
        """Reject field name exceeding max length."""
        from kstlib.rapi.credentials import _MAX_FIELD_NAME_LENGTH, _validate_field_name

        long_name = "a" * (_MAX_FIELD_NAME_LENGTH + 1)
        with pytest.raises(CredentialError) as exc_info:
            _validate_field_name(long_name, "test")
        assert "exceeds max length" in str(exc_info.value)

    def test_validate_field_name_invalid_chars(self) -> None:
        """Reject field name with invalid characters."""
        from kstlib.rapi.credentials import _validate_field_name

        invalid_names = ["api-key", "api.key", "api key", "123key", "@secret", "key$"]
        for name in invalid_names:
            with pytest.raises(CredentialError) as exc_info:
                _validate_field_name(name, "test")
            assert "alphanumeric" in str(exc_info.value)

    def test_validate_field_value_valid(self) -> None:
        """Accept valid field values."""
        from kstlib.rapi.credentials import _validate_field_value

        _validate_field_value("short_value", "field", "test")
        _validate_field_value("a" * 1000, "field", "test")  # 1KB is fine

    def test_validate_field_value_too_large(self) -> None:
        """Reject field value exceeding max size."""
        from kstlib.rapi.credentials import _MAX_FIELD_VALUE_SIZE, _validate_field_value

        large_value = "x" * (_MAX_FIELD_VALUE_SIZE + 1)
        with pytest.raises(CredentialError) as exc_info:
            _validate_field_value(large_value, "field", "test")
        assert "exceeds max size" in str(exc_info.value)

    def test_validate_fields_mapping_valid(self) -> None:
        """Accept valid fields mapping."""
        from kstlib.rapi.credentials import _validate_fields_mapping

        _validate_fields_mapping({"key": "api_key"}, "test")
        _validate_fields_mapping({"key": "api_key", "secret": "api_secret"}, "test")
        _validate_fields_mapping({"key": "k", "secret": "s", "passphrase": "p"}, "test")

    def test_validate_fields_mapping_missing_key(self) -> None:
        """Reject fields mapping without key field."""
        from kstlib.rapi.credentials import _validate_fields_mapping

        with pytest.raises(CredentialError) as exc_info:
            _validate_fields_mapping({"secret": "api_secret"}, "test")
        assert "Missing required 'key'" in str(exc_info.value)

    def test_validate_fields_mapping_too_many_fields(self) -> None:
        """Reject fields mapping with too many fields."""
        from kstlib.rapi.credentials import _MAX_FIELDS, _validate_fields_mapping

        many_fields = {f"field_{i}": f"source_{i}" for i in range(_MAX_FIELDS + 1)}
        many_fields["key"] = "api_key"
        with pytest.raises(CredentialError) as exc_info:
            _validate_fields_mapping(many_fields, "test")
        assert "Too many fields" in str(exc_info.value)


class TestCredentialResolverEnvFields:
    """Tests for CredentialResolver env type with fields mapping."""

    def test_resolve_env_fields_basic(self) -> None:
        """Resolve credentials using fields mapping."""
        config = {
            "exchange": {
                "type": "env",
                "fields": {
                    "key": "TEST_API_KEY",
                    "secret": "TEST_API_SECRET",
                },
            }
        }
        resolver = CredentialResolver(config)

        with mock.patch.dict(
            os.environ,
            {"TEST_API_KEY": "key123", "TEST_API_SECRET": "secret456"},
        ):
            record = resolver.resolve("exchange")

        assert record.value == "key123"
        assert record.secret == "secret456"
        assert record.source == "env"
        assert record.extras == {}

    def test_resolve_env_fields_with_extras(self) -> None:
        """Resolve credentials with extra fields."""
        config = {
            "coinbase": {
                "type": "env",
                "fields": {
                    "key": "CB_KEY",
                    "secret": "CB_SECRET",
                    "passphrase": "CB_PASSPHRASE",
                },
            }
        }
        resolver = CredentialResolver(config)

        with mock.patch.dict(
            os.environ,
            {
                "CB_KEY": "api_key",
                "CB_SECRET": "api_secret",
                "CB_PASSPHRASE": "my_passphrase",
            },
        ):
            record = resolver.resolve("coinbase")

        assert record.value == "api_key"
        assert record.secret == "api_secret"
        assert record.extras == {"passphrase": "my_passphrase"}

    def test_resolve_env_fields_key_only(self) -> None:
        """Resolve credentials with only key field."""
        config = {
            "simple": {
                "type": "env",
                "fields": {"key": "SIMPLE_TOKEN"},
            }
        }
        resolver = CredentialResolver(config)

        with mock.patch.dict(os.environ, {"SIMPLE_TOKEN": "token123"}):
            record = resolver.resolve("simple")

        assert record.value == "token123"
        assert record.secret is None
        assert record.extras == {}

    def test_resolve_env_fields_missing_key_var(self) -> None:
        """Raise error when key env var is missing."""
        config = {
            "bad": {
                "type": "env",
                "fields": {"key": "MISSING_KEY"},
            }
        }
        resolver = CredentialResolver(config)

        with mock.patch.dict(os.environ, {}, clear=True):
            with pytest.raises(CredentialError) as exc_info:
                resolver.resolve("bad")
            assert "MISSING_KEY" in str(exc_info.value)
            assert "fields.key" in str(exc_info.value)

    def test_resolve_env_fields_missing_extra_var(self) -> None:
        """Raise error when extra env var is missing."""
        config = {
            "bad": {
                "type": "env",
                "fields": {
                    "key": "API_KEY",
                    "passphrase": "MISSING_PASS",
                },
            }
        }
        resolver = CredentialResolver(config)

        with mock.patch.dict(os.environ, {"API_KEY": "key123"}, clear=True):
            with pytest.raises(CredentialError) as exc_info:
                resolver.resolve("bad")
            assert "MISSING_PASS" in str(exc_info.value)
            assert "fields.passphrase" in str(exc_info.value)


class TestCredentialResolverFileFields:
    """Tests for CredentialResolver file type with fields mapping."""

    def test_resolve_file_fields_basic(self) -> None:
        """Resolve credentials from file using fields mapping."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(
                {"api_key": "key123", "api_secret": "secret456"},
                f,
            )
            temp_path = f.name

        try:
            config = {
                "exchange": {
                    "type": "file",
                    "path": temp_path,
                    "fields": {
                        "key": "api_key",
                        "secret": "api_secret",
                    },
                }
            }
            resolver = CredentialResolver(config)
            record = resolver.resolve("exchange")

            assert record.value == "key123"
            assert record.secret == "secret456"
            assert record.source == "file"
        finally:
            os.unlink(temp_path)

    def test_resolve_file_fields_with_extras(self) -> None:
        """Resolve credentials from file with extra fields."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(
                {
                    "key": "api_key_val",
                    "secret": "secret_val",
                    "passphrase": "pass_val",
                    "account": "acc_123",
                },
                f,
            )
            temp_path = f.name

        try:
            config = {
                "okx": {
                    "type": "file",
                    "path": temp_path,
                    "fields": {
                        "key": "key",
                        "secret": "secret",
                        "passphrase": "passphrase",
                        "account_id": "account",
                    },
                }
            }
            resolver = CredentialResolver(config)
            record = resolver.resolve("okx")

            assert record.value == "api_key_val"
            assert record.secret == "secret_val"
            assert record.extras == {
                "passphrase": "pass_val",
                "account_id": "acc_123",
            }
        finally:
            os.unlink(temp_path)

    def test_resolve_file_fields_missing_field(self) -> None:
        """Raise error when field is missing from file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"api_key": "key123"}, f)
            temp_path = f.name

        try:
            config = {
                "bad": {
                    "type": "file",
                    "path": temp_path,
                    "fields": {
                        "key": "api_key",
                        "secret": "missing_secret",
                    },
                }
            }
            resolver = CredentialResolver(config)

            with pytest.raises(CredentialError) as exc_info:
                resolver.resolve("bad")
            assert "missing_secret" in str(exc_info.value)
            assert "fields.secret" in str(exc_info.value)
        finally:
            os.unlink(temp_path)
