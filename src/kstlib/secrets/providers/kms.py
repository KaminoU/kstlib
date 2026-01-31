"""AWS KMS-backed secret provider.

This provider uses AWS KMS to encrypt/decrypt secret values directly.
It supports both real AWS KMS and LocalStack for local development.

Note: For SOPS-managed files with KMS encryption, use SOPSProvider instead.
This provider is for direct KMS encrypt/decrypt operations.
"""

# pylint: disable=too-many-arguments
# Justification: __init__ takes standard AWS config params (key_id, region,
# endpoint, access_key, secret_key) - this is the canonical AWS client pattern.
# Wrapping in a dataclass would add indirection without benefit.

# pylint: disable=broad-exception-caught
# Justification: False positive - ClientError is a fallback to Exception only when
# boto3 is not installed (line 34). At runtime with boto3, we catch the real
# botocore.exceptions.ClientError, not the generic Exception.

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any

from kstlib.logging import get_logger
from kstlib.secrets.exceptions import SecretDecryptionError
from kstlib.secrets.models import SecretRecord, SecretRequest, SecretSource
from kstlib.secrets.providers.base import SecretProvider

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = get_logger(__name__)

# boto3 is optional - only needed when KMS provider is used
try:
    import boto3  # type: ignore[import-not-found]
    from botocore.exceptions import ClientError  # type: ignore[import-not-found]

    _HAS_BOTO3 = True
except ImportError:  # pragma: no cover
    _HAS_BOTO3 = False
    boto3 = None  # type: ignore[assignment]
    ClientError = Exception  # type: ignore[misc,assignment]


class KMSProvider(SecretProvider):
    """Load and decrypt secrets using AWS KMS.

    This provider can:
    - Decrypt base64-encoded ciphertext stored in environment variables or config
    - Store encrypted values using KMS encrypt operation

    Unlike SOPSProvider which decrypts entire files, KMSProvider works with
    individual secret values that have been encrypted with KMS.

    Example:
        >>> from kstlib.secrets.providers.kms import KMSProvider
        >>> provider = KMSProvider(
        ...     key_id="alias/my-key",
        ...     endpoint_url="http://localhost:4566",  # LocalStack
        ... )
        >>> # provider.resolve(SecretRequest(name="db.password", metadata={"ciphertext": "..."}))
    """

    name = "kms"

    def __init__(
        self,
        *,
        key_id: str | None = None,
        region_name: str = "us-east-1",
        endpoint_url: str | None = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
    ) -> None:
        """Configure the KMS provider.

        Args:
            key_id: Default KMS key ID or alias (e.g., "alias/kstlib-test").
            region_name: AWS region (default: us-east-1).
            endpoint_url: Custom endpoint for LocalStack (e.g., "http://localhost:4566").
            aws_access_key_id: AWS access key (optional, uses default credential chain).
            aws_secret_access_key: AWS secret key (optional, uses default credential chain).
        """
        self._key_id = key_id
        self._region_name = region_name
        self._endpoint_url = endpoint_url
        self._aws_access_key_id = aws_access_key_id
        self._aws_secret_access_key = aws_secret_access_key
        self._client: Any = None

    def configure(self, settings: Mapping[str, Any] | None = None) -> None:
        """Apply configuration from settings mapping."""
        if not settings:
            return
        if "key_id" in settings:
            self._key_id = settings["key_id"]
        if "region_name" in settings:
            self._region_name = settings["region_name"]
        if "endpoint_url" in settings:
            self._endpoint_url = settings["endpoint_url"]
        if "aws_access_key_id" in settings:
            self._aws_access_key_id = settings["aws_access_key_id"]
        if "aws_secret_access_key" in settings:
            self._aws_secret_access_key = settings["aws_secret_access_key"]
        # Reset client to pick up new config
        self._client = None

    def _get_client(self) -> Any:
        """Lazily initialize and return the KMS client."""
        if self._client is not None:
            return self._client

        if not _HAS_BOTO3:
            raise SecretDecryptionError("boto3 is required for KMS provider. Install with: pip install boto3")

        client_kwargs: dict[str, Any] = {
            "service_name": "kms",
            "region_name": self._region_name,
        }
        if self._endpoint_url:
            client_kwargs["endpoint_url"] = self._endpoint_url
        if self._aws_access_key_id:
            client_kwargs["aws_access_key_id"] = self._aws_access_key_id
        if self._aws_secret_access_key:
            client_kwargs["aws_secret_access_key"] = self._aws_secret_access_key

        self._client = boto3.client(**client_kwargs)  # type: ignore[union-attr]
        return self._client

    def resolve(self, request: SecretRequest) -> SecretRecord | None:
        """Resolve a secret by decrypting KMS ciphertext.

        The ciphertext can be provided in request metadata as:
        - "ciphertext": base64-encoded encrypted data
        - "ciphertext_blob": raw bytes (less common)

        If no ciphertext is provided, returns None (allowing fallback to other providers).
        """
        metadata = request.metadata or {}
        ciphertext_b64 = metadata.get("ciphertext")
        ciphertext_blob = metadata.get("ciphertext_blob")

        if ciphertext_b64 is None and ciphertext_blob is None:
            return None

        try:
            if ciphertext_b64:
                ciphertext_blob = base64.b64decode(ciphertext_b64)

            client = self._get_client()
            response = client.decrypt(CiphertextBlob=ciphertext_blob)
            plaintext = response["Plaintext"]

            # Decode if bytes
            if isinstance(plaintext, bytes):
                plaintext = plaintext.decode("utf-8")

            return SecretRecord(
                value=plaintext,
                source=SecretSource.KMS,
                metadata={
                    "key_id": response.get("KeyId", self._key_id),
                    "region": self._region_name,
                    "endpoint": self._endpoint_url,
                },
            )
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "Unknown")  # type: ignore[union-attr]
            logger.debug("KMS decryption failed for %s: %s", request.name, error_code)
            raise SecretDecryptionError(f"Failed to decrypt secret '{request.name}': {error_code}") from exc

    def encrypt(self, plaintext: str | bytes, *, key_id: str | None = None) -> str:
        """Encrypt a plaintext value and return base64-encoded ciphertext.

        Args:
            plaintext: The value to encrypt (string or bytes).
            key_id: KMS key ID or alias. If not provided, uses the default key_id.

        Returns:
            Base64-encoded ciphertext that can be decrypted later.

        Raises:
            SecretDecryptionError: If encryption fails or no key_id is configured.
        """
        effective_key_id = key_id or self._key_id
        if not effective_key_id:
            raise SecretDecryptionError("No KMS key_id configured for encryption")

        if isinstance(plaintext, str):
            plaintext = plaintext.encode("utf-8")

        try:
            client = self._get_client()
            response = client.encrypt(KeyId=effective_key_id, Plaintext=plaintext)
            ciphertext_blob = response["CiphertextBlob"]
            return base64.b64encode(ciphertext_blob).decode("ascii")
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "Unknown")  # type: ignore[union-attr]
            raise SecretDecryptionError(f"Failed to encrypt: {error_code}") from exc

    def is_available(self) -> bool:
        """Check if KMS is reachable and the configured key exists.

        Returns:
            True if KMS is accessible and the key can be used.
        """
        if not _HAS_BOTO3:
            return False

        if not self._key_id:
            return False

        try:
            client = self._get_client()
            client.describe_key(KeyId=self._key_id)
        except ClientError:
            return False
        return True


__all__ = ["KMSProvider"]
