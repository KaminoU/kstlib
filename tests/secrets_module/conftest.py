"""Fixtures for secrets module tests."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator


# =============================================================================
# LocalStack Fixtures (for KMS integration tests)
# =============================================================================

LOCALSTACK_ENDPOINT = "http://localhost:4566"
LOCALSTACK_REGION = "us-east-1"
LOCALSTACK_KEY_ALIAS = "alias/kstlib-test"


def _is_localstack_available() -> bool:
    """Check if LocalStack is running and reachable."""
    try:
        import urllib.request

        req = urllib.request.Request(
            f"{LOCALSTACK_ENDPOINT}/_localstack/health",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=2) as response:
            return bool(response.status == 200)
    except Exception:
        return False


def _has_boto3() -> bool:
    """Check if boto3 is installed."""
    try:
        import boto3  # type: ignore[import-not-found]  # noqa: F401

        return True
    except ImportError:
        return False


# Markers for conditional test execution
requires_localstack = pytest.mark.skipif(
    not _is_localstack_available(),
    reason="LocalStack not available (run: cd infra && docker compose up -d)",
)

requires_boto3 = pytest.mark.skipif(
    not _has_boto3(),
    reason="boto3 not installed (run: pip install boto3)",
)


@pytest.fixture(scope="session")
def localstack_endpoint() -> str:
    """Return the LocalStack endpoint URL."""
    return os.getenv("LOCALSTACK_ENDPOINT", LOCALSTACK_ENDPOINT)


@pytest.fixture(scope="session")
def localstack_region() -> str:
    """Return the LocalStack region."""
    return os.getenv("AWS_DEFAULT_REGION", LOCALSTACK_REGION)


@pytest.fixture(scope="session")
def localstack_key_alias() -> str:
    """Return the LocalStack KMS key alias."""
    return LOCALSTACK_KEY_ALIAS


@pytest.fixture(scope="session")
def kms_client(localstack_endpoint: str, localstack_region: str) -> Generator[Any, None, None]:
    """Create a boto3 KMS client configured for LocalStack.

    This fixture is session-scoped for efficiency since LocalStack state
    is persistent within a test session.
    """
    if not _has_boto3():
        pytest.skip("boto3 not installed")

    import boto3  # type: ignore[import-not-found]

    client = boto3.client(
        "kms",
        endpoint_url=localstack_endpoint,
        region_name=localstack_region,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    yield client


@pytest.fixture
def kms_encrypt_decrypt(
    kms_client: Any,
    localstack_key_alias: str,
) -> tuple[Any, str]:
    """Return a tuple of (kms_client, key_alias) for encrypt/decrypt tests."""
    return (kms_client, localstack_key_alias)


# =============================================================================
# Mock boto3 Fixtures (for unit tests without LocalStack)
# =============================================================================


@pytest.fixture
def mock_boto3_kms(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Mock boto3.client for KMS tests without real AWS/LocalStack.

    Returns a dict to capture calls and configure responses.
    """
    import types

    captures: dict[str, Any] = {
        "client_calls": [],
        "encrypt_calls": [],
        "decrypt_calls": [],
        "describe_key_calls": [],
        "encrypt_response": {
            "CiphertextBlob": b"encrypted-data",
            "KeyId": "arn:aws:kms:us-east-1:123456789012:key/test-key",
        },
        "decrypt_response": {
            "Plaintext": b"decrypted-secret",
            "KeyId": "arn:aws:kms:us-east-1:123456789012:key/test-key",
        },
        "describe_key_response": {
            "KeyMetadata": {
                "KeyId": "test-key-id",
                "Arn": "arn:aws:kms:us-east-1:123456789012:key/test-key",
            }
        },
    }

    def mock_encrypt(**kwargs: Any) -> dict[str, Any]:
        captures["encrypt_calls"].append(kwargs)
        return dict(captures["encrypt_response"])

    def mock_decrypt(**kwargs: Any) -> dict[str, Any]:
        captures["decrypt_calls"].append(kwargs)
        return dict(captures["decrypt_response"])

    def mock_describe_key(**kwargs: Any) -> dict[str, Any]:
        captures["describe_key_calls"].append(kwargs)
        return dict(captures["describe_key_response"])

    def mock_client(service_name: str, **kwargs: Any) -> Any:
        captures["client_calls"].append({"service_name": service_name, **kwargs})
        return types.SimpleNamespace(
            encrypt=mock_encrypt,
            decrypt=mock_decrypt,
            describe_key=mock_describe_key,
        )

    # Create a fake boto3 module
    fake_boto3 = types.SimpleNamespace(client=mock_client)

    # Patch boto3 at the module level where KMSProvider imports it
    monkeypatch.setattr("kstlib.secrets.providers.kms.boto3", fake_boto3)
    monkeypatch.setattr("kstlib.secrets.providers.kms._HAS_BOTO3", True)

    return captures


# =============================================================================
# SOPS E2E Fixtures (age, GPG, KMS backends)
# =============================================================================


def _has_sops() -> bool:
    """Check if sops binary is available."""
    return shutil.which("sops") is not None


def _has_age_keygen() -> bool:
    """Check if age-keygen binary is available."""
    return shutil.which("age-keygen") is not None


def _has_gpg() -> bool:
    """Check if gpg binary is available."""
    return shutil.which("gpg") is not None


# Markers for SOPS e2e tests
requires_sops = pytest.mark.skipif(
    not _has_sops(),
    reason="sops not installed (run: scoop install sops)",
)

requires_age = pytest.mark.skipif(
    not _has_age_keygen(),
    reason="age-keygen not installed (run: scoop install age)",
)


def _gpg_works_with_temp_dirs() -> bool:
    """Check if GPG works with temporary directories.

    Some Scoop GPG builds use Cygwin paths internally which breaks
    with Windows temp directories.
    """
    if not _has_gpg():
        return False
    import tempfile

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {**os.environ, "GNUPGHOME": tmpdir}
            result = subprocess.run(
                ["gpg", "--list-keys"],
                env=env,
                capture_output=True,
                text=True,
            )
            # Check for cygdrive path mangling in stderr
            if "cygdrive" in result.stderr:
                return False
            # Also check for "No such file or directory" with mixed paths
            if result.returncode != 0 and "No such file" in result.stderr:
                return False
        return True
    except Exception:
        return False


requires_gpg = pytest.mark.skipif(
    not _gpg_works_with_temp_dirs(),
    reason="gpg not installed or has path compatibility issues",
)


@pytest.fixture
def age_keypair(tmp_path: Path) -> Generator[dict[str, Any], None, None]:
    """Generate temporary age keypair for SOPS testing.

    Yields:
        dict with keys_file (Path) and public_key (str).
    """
    keys_file = tmp_path / "age-keys.txt"

    # Generate private key
    subprocess.run(
        ["age-keygen", "-o", str(keys_file)],
        capture_output=True,
        text=True,
        check=True,
    )

    # Extract public key using age-keygen -y (cleaner than parsing stderr)
    result = subprocess.run(
        ["age-keygen", "-y", str(keys_file)],
        capture_output=True,
        text=True,
        check=True,
    )

    public_key = result.stdout.strip()
    if not public_key.startswith("age1"):
        pytest.fail(f"Invalid age public key: {public_key}")

    yield {"keys_file": keys_file, "public_key": public_key}

    # Cleanup handled by tmp_path fixture


@pytest.fixture
def age_sops_config(tmp_path: Path, age_keypair: dict[str, Any]) -> Path:
    """Create a .sops.yaml config for age encryption.

    Returns:
        Path to the .sops.yaml file.
    """
    sops_config = tmp_path / ".sops.yaml"
    sops_config.write_text(f"""\
creation_rules:
  - path_regex: .*\\.ya?ml$
    age: {age_keypair["public_key"]}
  - path_regex: .*\\.json$
    age: {age_keypair["public_key"]}
""")
    return sops_config


@pytest.fixture
def gpg_keypair(tmp_path: Path) -> Generator[dict[str, Any], None, None]:
    """Generate temporary GPG keypair for SOPS testing.

    Creates an isolated GNUPGHOME with a test key (no passphrase).

    Yields:
        dict with gnupghome (Path), fingerprint (str), and email (str).
    """
    import platform

    gnupghome = tmp_path / ".gnupg"
    gnupghome.mkdir(exist_ok=True)

    # On Unix, GPG requires 700 permissions on GNUPGHOME
    if platform.system() != "Windows":
        gnupghome.chmod(0o700)

    # Batch key generation parameters (no passphrase)
    key_params = tmp_path / "key-params.txt"
    key_params.write_text("""\
%echo Generating test key for SOPS
Key-Type: RSA
Key-Length: 2048
Name-Real: KSTLIB Test
Name-Email: test@kstlib.local
Expire-Date: 0
%no-protection
%commit
%echo Done
""")

    env = {**os.environ, "GNUPGHOME": str(gnupghome)}

    # Generate key
    result = subprocess.run(
        ["gpg", "--batch", "--gen-key", str(key_params)],
        env=env,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        pytest.fail(f"GPG key generation failed: {result.stderr}")

    # Get fingerprint
    result = subprocess.run(
        ["gpg", "--list-secret-keys", "--with-colons"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    # Parse fingerprint from output (fpr:::::::::FINGERPRINT:)
    fingerprint = None
    for line in result.stdout.splitlines():
        if line.startswith("fpr:"):
            fingerprint = line.split(":")[9]
            break

    if not fingerprint:
        pytest.fail(f"Could not parse GPG fingerprint from: {result.stdout}")

    yield {
        "gnupghome": gnupghome,
        "fingerprint": fingerprint,
        "email": "test@kstlib.local",
    }

    # Cleanup handled by tmp_path fixture


@pytest.fixture
def gpg_sops_config(tmp_path: Path, gpg_keypair: dict[str, Any]) -> Path:
    """Create a .sops.yaml config for GPG encryption.

    Returns:
        Path to the .sops.yaml file.
    """
    sops_config = tmp_path / ".sops.yaml"
    sops_config.write_text(f"""\
creation_rules:
  - path_regex: .*\\.ya?ml$
    pgp: {gpg_keypair["fingerprint"]}
  - path_regex: .*\\.json$
    pgp: {gpg_keypair["fingerprint"]}
""")
    return sops_config


@pytest.fixture
def kms_key_arn(
    kms_client: Any,
    localstack_key_alias: str,
) -> str:
    """Resolve the KMS key ARN from the alias.

    SOPS requires a full ARN, not just an alias name.
    """
    response = kms_client.describe_key(KeyId=localstack_key_alias)
    return response["KeyMetadata"]["Arn"]


@pytest.fixture
def kms_sops_config(
    tmp_path: Path,
    kms_key_arn: str,
) -> Path:
    """Create a .sops.yaml config for KMS encryption via LocalStack.

    Returns:
        Path to the .sops.yaml file.
    """
    sops_config = tmp_path / ".sops.yaml"
    # SOPS requires full ARN, not just alias
    sops_config.write_text(f"""\
creation_rules:
  - path_regex: .*\\.ya?ml$
    kms: {kms_key_arn}
  - path_regex: .*\\.json$
    kms: {kms_key_arn}
""")
    return sops_config


@pytest.fixture
def sample_secrets_yaml(tmp_path: Path) -> Path:
    """Create a sample secrets YAML file for encryption testing.

    Returns:
        Path to the secrets file.
    """
    secrets_file = tmp_path / "secrets.yaml"
    secrets_file.write_text("""\
database:
  password: super-secret-password-123
  connection_string: postgresql://user:pass@localhost/db
api:
  key: sk-test-api-key-xyz
  secret: very-confidential-secret
""")
    return secrets_file


@pytest.fixture
def sample_secrets_json(tmp_path: Path) -> Path:
    """Create a sample secrets JSON file for encryption testing.

    Returns:
        Path to the secrets file.
    """
    secrets_file = tmp_path / "secrets.json"
    secrets_file.write_text("""\
{
  "database": {
    "password": "super-secret-password-123",
    "connection_string": "postgresql://user:pass@localhost/db"
  },
  "api": {
    "key": "sk-test-api-key-xyz",
    "secret": "very-confidential-secret"
  }
}
""")
    return secrets_file
