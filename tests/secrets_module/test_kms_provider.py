"""Tests for the KMS secret provider."""

from __future__ import annotations

# pylint: disable=missing-function-docstring,missing-class-docstring,protected-access
import base64
from typing import Any
from unittest.mock import MagicMock

import pytest

from kstlib.secrets.exceptions import SecretDecryptionError
from kstlib.secrets.models import SecretRequest, SecretSource
from kstlib.secrets.providers import get_provider
from kstlib.secrets.providers.kms import KMSProvider


def _has_boto3_installed() -> bool:
    """Check if boto3 is installed."""
    try:
        import boto3  # type: ignore[import-not-found]  # noqa: F401

        return True
    except ImportError:
        return False


def _is_localstack_reachable() -> bool:
    """Check if LocalStack is running and reachable."""
    try:
        import urllib.request

        req = urllib.request.Request(
            "http://localhost:4566/_localstack/health",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=2) as response:
            return bool(response.status == 200)
    except Exception:
        return False


# Conditional skip markers
requires_boto3 = pytest.mark.skipif(
    not _has_boto3_installed(),
    reason="boto3 not installed (run: pip install boto3)",
)

requires_localstack = pytest.mark.skipif(
    not _is_localstack_reachable(),
    reason="LocalStack not available (run: cd infra && docker compose up -d)",
)


# =============================================================================
# Unit Tests (mocked boto3)
# =============================================================================


class TestKMSProviderUnit:
    """Unit tests for KMSProvider without real AWS/LocalStack."""

    def test_provider_registration(self) -> None:
        """KMS provider is registered in the provider registry."""
        provider = get_provider("kms")
        assert isinstance(provider, KMSProvider)
        assert provider.name == "kms"

    def test_init_stores_configuration(self) -> None:
        """Constructor stores all configuration options."""
        provider = KMSProvider(
            key_id="alias/my-key",
            region_name="eu-west-1",
            endpoint_url="http://localhost:4566",
            aws_access_key_id="AKIATEST",
            aws_secret_access_key="secret",
        )
        assert provider._key_id == "alias/my-key"
        assert provider._region_name == "eu-west-1"
        assert provider._endpoint_url == "http://localhost:4566"
        assert provider._aws_access_key_id == "AKIATEST"
        assert provider._aws_secret_access_key == "secret"

    def test_configure_updates_settings(self) -> None:
        """Configure method updates provider settings."""
        provider = KMSProvider(key_id="alias/old-key")

        provider.configure(
            {
                "key_id": "alias/new-key",
                "region_name": "ap-northeast-1",
                "endpoint_url": "http://new-endpoint:4566",
            }
        )

        assert provider._key_id == "alias/new-key"
        assert provider._region_name == "ap-northeast-1"
        assert provider._endpoint_url == "http://new-endpoint:4566"

    def test_configure_noop_with_none(self) -> None:
        """Configure does nothing when settings is None."""
        provider = KMSProvider(key_id="alias/original")
        provider.configure(None)
        assert provider._key_id == "alias/original"

    def test_configure_noop_with_empty_dict(self) -> None:
        """Configure does nothing when settings is empty."""
        provider = KMSProvider(key_id="alias/original")
        provider.configure({})
        assert provider._key_id == "alias/original"

    def test_resolve_returns_none_without_ciphertext(self) -> None:
        """Resolve returns None when no ciphertext is provided."""
        provider = KMSProvider(key_id="alias/test")
        request = SecretRequest(name="db.password")

        result = provider.resolve(request)

        assert result is None

    def test_resolve_decrypts_ciphertext(self, mock_boto3_kms: dict[str, Any]) -> None:
        """Resolve decrypts base64-encoded ciphertext."""
        provider = KMSProvider(
            key_id="alias/test",
            endpoint_url="http://localhost:4566",
        )
        ciphertext = base64.b64encode(b"encrypted-data").decode("ascii")
        request = SecretRequest(
            name="db.password",
            metadata={"ciphertext": ciphertext},
        )

        record = provider.resolve(request)

        assert record is not None
        assert record.value == "decrypted-secret"
        assert record.source is SecretSource.KMS
        assert "key_id" in record.metadata

    def test_resolve_decrypts_ciphertext_blob(self, mock_boto3_kms: dict[str, Any]) -> None:
        """Resolve decrypts raw ciphertext_blob bytes."""
        provider = KMSProvider(
            key_id="alias/test",
            endpoint_url="http://localhost:4566",
        )
        request = SecretRequest(
            name="api.key",
            metadata={"ciphertext_blob": b"encrypted-bytes"},
        )

        record = provider.resolve(request)

        assert record is not None
        assert record.value == "decrypted-secret"

    def test_resolve_handles_client_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Resolve raises SecretDecryptionError on KMS client error."""
        import types

        # Create a mock ClientError class
        class MockClientError(Exception):
            def __init__(self, error_response: dict[str, Any], operation_name: str) -> None:
                self.response = error_response
                self.operation_name = operation_name
                super().__init__(f"{operation_name}: {error_response}")

        def mock_decrypt(**_: Any) -> None:
            raise MockClientError(
                {"Error": {"Code": "AccessDeniedException", "Message": "Access denied"}},
                "Decrypt",
            )

        mock_client = MagicMock()
        mock_client.decrypt = mock_decrypt

        fake_boto3 = types.SimpleNamespace(client=lambda **_: mock_client)

        monkeypatch.setattr("kstlib.secrets.providers.kms._HAS_BOTO3", True)
        monkeypatch.setattr("kstlib.secrets.providers.kms.boto3", fake_boto3)
        monkeypatch.setattr("kstlib.secrets.providers.kms.ClientError", MockClientError)

        provider = KMSProvider(key_id="alias/test")
        request = SecretRequest(
            name="secret",
            metadata={"ciphertext": base64.b64encode(b"data").decode()},
        )

        with pytest.raises(SecretDecryptionError) as exc_info:
            provider.resolve(request)

        assert "AccessDeniedException" in str(exc_info.value)

    def test_encrypt_returns_base64_ciphertext(self, mock_boto3_kms: dict[str, Any]) -> None:
        """Encrypt returns base64-encoded ciphertext."""
        provider = KMSProvider(
            key_id="alias/test",
            endpoint_url="http://localhost:4566",
        )

        result = provider.encrypt("my secret")

        assert result == base64.b64encode(b"encrypted-data").decode("ascii")
        assert mock_boto3_kms["encrypt_calls"][0]["Plaintext"] == b"my secret"

    def test_encrypt_accepts_bytes(self, mock_boto3_kms: dict[str, Any]) -> None:
        """Encrypt accepts bytes input."""
        provider = KMSProvider(key_id="alias/test")

        provider.encrypt(b"binary secret")

        assert mock_boto3_kms["encrypt_calls"][0]["Plaintext"] == b"binary secret"

    def test_encrypt_uses_provided_key_id(self, mock_boto3_kms: dict[str, Any]) -> None:
        """Encrypt uses the key_id passed as argument."""
        provider = KMSProvider(key_id="alias/default")

        provider.encrypt("secret", key_id="alias/override")

        assert mock_boto3_kms["encrypt_calls"][0]["KeyId"] == "alias/override"

    def test_encrypt_requires_key_id(self) -> None:
        """Encrypt raises error when no key_id is configured."""
        provider = KMSProvider()

        with pytest.raises(SecretDecryptionError, match="No KMS key_id"):
            provider.encrypt("secret")

    def test_is_available_returns_false_without_boto3(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """is_available returns False when boto3 is not installed."""
        monkeypatch.setattr("kstlib.secrets.providers.kms._HAS_BOTO3", False)

        provider = KMSProvider(key_id="alias/test")

        assert provider.is_available() is False

    def test_is_available_returns_false_without_key_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """is_available returns False when no key_id is configured."""
        monkeypatch.setattr("kstlib.secrets.providers.kms._HAS_BOTO3", True)

        provider = KMSProvider()

        assert provider.is_available() is False

    def test_is_available_returns_true_on_success(self, mock_boto3_kms: dict[str, Any]) -> None:
        """is_available returns True when key is accessible."""
        provider = KMSProvider(key_id="alias/test")

        assert provider.is_available() is True
        assert mock_boto3_kms["describe_key_calls"][0]["KeyId"] == "alias/test"

    def test_is_available_returns_false_on_client_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """is_available returns False when KMS returns an error."""
        import types

        # Create a mock ClientError class
        class MockClientError(Exception):
            def __init__(self, error_response: dict[str, Any], operation_name: str) -> None:
                self.response = error_response
                self.operation_name = operation_name
                super().__init__(f"{operation_name}: {error_response}")

        def mock_describe_key(**_: Any) -> None:
            raise MockClientError(
                {"Error": {"Code": "NotFoundException", "Message": "Key not found"}},
                "DescribeKey",
            )

        mock_client = MagicMock()
        mock_client.describe_key = mock_describe_key

        fake_boto3 = types.SimpleNamespace(client=lambda **_: mock_client)

        monkeypatch.setattr("kstlib.secrets.providers.kms._HAS_BOTO3", True)
        monkeypatch.setattr("kstlib.secrets.providers.kms.boto3", fake_boto3)
        monkeypatch.setattr("kstlib.secrets.providers.kms.ClientError", MockClientError)

        provider = KMSProvider(key_id="alias/missing")

        assert provider.is_available() is False

    def test_get_client_raises_without_boto3(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_get_client raises SecretDecryptionError when boto3 is missing."""
        monkeypatch.setattr("kstlib.secrets.providers.kms._HAS_BOTO3", False)

        provider = KMSProvider(key_id="alias/test")

        with pytest.raises(SecretDecryptionError, match="boto3 is required"):
            provider._get_client()

    def test_configure_updates_aws_credentials(self) -> None:
        """Configure method updates AWS credential settings."""
        provider = KMSProvider(key_id="alias/test")

        provider.configure(
            {
                "aws_access_key_id": "AKIA_NEW_KEY",
                "aws_secret_access_key": "new_secret_key",
            }
        )

        assert provider._aws_access_key_id == "AKIA_NEW_KEY"
        assert provider._aws_secret_access_key == "new_secret_key"

    def test_encrypt_handles_client_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Encrypt raises SecretDecryptionError on KMS client error."""
        import types

        # Create a mock ClientError class
        class MockClientError(Exception):
            def __init__(self, error_response: dict[str, Any], operation_name: str) -> None:
                self.response = error_response
                self.operation_name = operation_name
                super().__init__(f"{operation_name}: {error_response}")

        def mock_encrypt(**_: Any) -> None:
            raise MockClientError(
                {"Error": {"Code": "InvalidKeyIdException", "Message": "Invalid key"}},
                "Encrypt",
            )

        mock_client = MagicMock()
        mock_client.encrypt = mock_encrypt

        fake_boto3 = types.SimpleNamespace(client=lambda **_: mock_client)

        monkeypatch.setattr("kstlib.secrets.providers.kms._HAS_BOTO3", True)
        monkeypatch.setattr("kstlib.secrets.providers.kms.boto3", fake_boto3)
        monkeypatch.setattr("kstlib.secrets.providers.kms.ClientError", MockClientError)

        provider = KMSProvider(key_id="alias/test")

        with pytest.raises(SecretDecryptionError) as exc_info:
            provider.encrypt("secret-data")

        assert "InvalidKeyIdException" in str(exc_info.value)


# =============================================================================
# Integration Tests (LocalStack)
# =============================================================================


@requires_boto3
@requires_localstack
class TestKMSProviderIntegration:
    """Integration tests with LocalStack."""

    def test_encrypt_decrypt_roundtrip(
        self,
        localstack_endpoint: str,
        localstack_region: str,
        localstack_key_alias: str,
    ) -> None:
        """Encrypt and decrypt a secret through LocalStack."""
        provider = KMSProvider(
            key_id=localstack_key_alias,
            region_name=localstack_region,
            endpoint_url=localstack_endpoint,
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )

        # Encrypt
        plaintext = "super-secret-password-123"
        ciphertext = provider.encrypt(plaintext)

        # Ciphertext should be base64-encoded
        assert ciphertext
        # Should decode without error
        base64.b64decode(ciphertext)

        # Decrypt
        request = SecretRequest(
            name="test.secret",
            metadata={"ciphertext": ciphertext},
        )
        record = provider.resolve(request)

        assert record is not None
        assert record.value == plaintext
        assert record.source is SecretSource.KMS

    def test_is_available_with_localstack(
        self,
        localstack_endpoint: str,
        localstack_region: str,
        localstack_key_alias: str,
    ) -> None:
        """is_available returns True with valid LocalStack config."""
        provider = KMSProvider(
            key_id=localstack_key_alias,
            region_name=localstack_region,
            endpoint_url=localstack_endpoint,
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )

        assert provider.is_available() is True

    def test_is_available_with_invalid_key(
        self,
        localstack_endpoint: str,
        localstack_region: str,
    ) -> None:
        """is_available returns False with non-existent key."""
        provider = KMSProvider(
            key_id="alias/non-existent-key",
            region_name=localstack_region,
            endpoint_url=localstack_endpoint,
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )

        assert provider.is_available() is False

    def test_decrypt_invalid_ciphertext(
        self,
        localstack_endpoint: str,
        localstack_region: str,
        localstack_key_alias: str,
    ) -> None:
        """Decrypting invalid ciphertext raises SecretDecryptionError."""
        provider = KMSProvider(
            key_id=localstack_key_alias,
            region_name=localstack_region,
            endpoint_url=localstack_endpoint,
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )

        # Invalid base64-encoded "ciphertext" that wasn't actually encrypted
        invalid_ciphertext = base64.b64encode(b"not-real-ciphertext").decode()
        request = SecretRequest(
            name="test.secret",
            metadata={"ciphertext": invalid_ciphertext},
        )

        with pytest.raises(SecretDecryptionError):
            provider.resolve(request)

    def test_configure_resets_client(
        self,
        localstack_endpoint: str,
        localstack_region: str,
        localstack_key_alias: str,
    ) -> None:
        """Configure resets the cached client."""
        provider = KMSProvider(
            key_id=localstack_key_alias,
            region_name=localstack_region,
            endpoint_url=localstack_endpoint,
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )

        # Force client initialization
        _ = provider._get_client()
        original_client = provider._client

        # Configure with new settings
        provider.configure({"region_name": "eu-west-1"})

        # Client should be reset
        assert provider._client is None
        assert provider._region_name == "eu-west-1"

        # New client should be created on next access
        _ = provider._get_client()
        assert provider._client is not original_client
