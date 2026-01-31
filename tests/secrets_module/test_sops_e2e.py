"""End-to-end tests for SOPS encryption/decryption.

These tests verify that SOPS integration works correctly with different backends:
- Age: Modern, simple encryption (recommended)
- GPG: Traditional PGP-based encryption
- KMS: AWS Key Management Service (via LocalStack for testing)

Each test creates temporary keys, encrypts sample secrets, and verifies
the roundtrip (encrypt -> decrypt -> compare).
"""

from __future__ import annotations

# pylint: disable=missing-function-docstring,missing-class-docstring
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from .conftest import (
    requires_age,
    requires_boto3,
    requires_gpg,
    requires_localstack,
    requires_sops,
)

# =============================================================================
# Age Backend Tests
# =============================================================================


@requires_sops
@requires_age
class TestSopsAgeBackend:
    """E2E tests for SOPS with age encryption backend."""

    def test_encrypt_decrypt_yaml_roundtrip(
        self,
        tmp_path: Path,
        age_keypair: dict[str, Any],
        age_sops_config: Path,
        sample_secrets_yaml: Path,
    ) -> None:
        """Encrypt and decrypt YAML file using age key."""
        encrypted_file = tmp_path / "secrets.enc.yaml"
        decrypted_file = tmp_path / "secrets.dec.yaml"

        env = {
            **os.environ,
            "SOPS_AGE_KEY_FILE": str(age_keypair["keys_file"]),
        }

        # Encrypt
        subprocess.run(
            [
                "sops",
                "--config",
                str(age_sops_config),
                "--encrypt",
                "--output",
                str(encrypted_file),
                str(sample_secrets_yaml),
            ],
            env=env,
            check=True,
            capture_output=True,
        )

        # Verify encrypted file exists and contains sops metadata
        assert encrypted_file.exists()
        encrypted_content = encrypted_file.read_text()
        assert "sops:" in encrypted_content
        assert "ENC[AES256_GCM" in encrypted_content

        # Decrypt
        subprocess.run(
            [
                "sops",
                "--config",
                str(age_sops_config),
                "--decrypt",
                "--output",
                str(decrypted_file),
                str(encrypted_file),
            ],
            env=env,
            check=True,
            capture_output=True,
        )

        # Verify roundtrip
        original = yaml.safe_load(sample_secrets_yaml.read_text())
        decrypted = yaml.safe_load(decrypted_file.read_text())
        assert original == decrypted

    def test_encrypt_decrypt_json_roundtrip(
        self,
        tmp_path: Path,
        age_keypair: dict[str, Any],
        age_sops_config: Path,
        sample_secrets_json: Path,
    ) -> None:
        """Encrypt and decrypt JSON file using age key."""
        import json

        encrypted_file = tmp_path / "secrets.enc.json"
        decrypted_file = tmp_path / "secrets.dec.json"

        env = {
            **os.environ,
            "SOPS_AGE_KEY_FILE": str(age_keypair["keys_file"]),
        }

        # Encrypt
        subprocess.run(
            [
                "sops",
                "--config",
                str(age_sops_config),
                "--encrypt",
                "--output",
                str(encrypted_file),
                str(sample_secrets_json),
            ],
            env=env,
            check=True,
            capture_output=True,
        )

        # Verify encrypted
        assert encrypted_file.exists()
        encrypted_content = encrypted_file.read_text()
        assert "sops" in encrypted_content
        assert "ENC[AES256_GCM" in encrypted_content

        # Decrypt
        subprocess.run(
            [
                "sops",
                "--config",
                str(age_sops_config),
                "--decrypt",
                "--output",
                str(decrypted_file),
                str(encrypted_file),
            ],
            env=env,
            check=True,
            capture_output=True,
        )

        # Verify roundtrip
        original = json.loads(sample_secrets_json.read_text())
        decrypted = json.loads(decrypted_file.read_text())
        assert original == decrypted

    def test_encrypted_values_are_not_plaintext(
        self,
        tmp_path: Path,
        age_keypair: dict[str, Any],
        age_sops_config: Path,
        sample_secrets_yaml: Path,
    ) -> None:
        """Verify that sensitive values are actually encrypted."""
        encrypted_file = tmp_path / "secrets.enc.yaml"

        env = {
            **os.environ,
            "SOPS_AGE_KEY_FILE": str(age_keypair["keys_file"]),
        }

        subprocess.run(
            [
                "sops",
                "--config",
                str(age_sops_config),
                "--encrypt",
                "--output",
                str(encrypted_file),
                str(sample_secrets_yaml),
            ],
            env=env,
            check=True,
            capture_output=True,
        )

        encrypted_content = encrypted_file.read_text()

        # Plaintext values should NOT appear in encrypted file
        assert "super-secret-password-123" not in encrypted_content
        assert "sk-test-api-key-xyz" not in encrypted_content
        assert "very-confidential-secret" not in encrypted_content


# =============================================================================
# GPG Backend Tests
# =============================================================================


@requires_sops
@requires_gpg
class TestSopsGpgBackend:
    """E2E tests for SOPS with GPG encryption backend."""

    def test_encrypt_decrypt_yaml_roundtrip(
        self,
        tmp_path: Path,
        gpg_keypair: dict[str, Any],
        gpg_sops_config: Path,
        sample_secrets_yaml: Path,
    ) -> None:
        """Encrypt and decrypt YAML file using GPG key."""
        encrypted_file = tmp_path / "secrets.enc.yaml"
        decrypted_file = tmp_path / "secrets.dec.yaml"

        env = {
            **os.environ,
            "GNUPGHOME": str(gpg_keypair["gnupghome"]),
        }

        # Encrypt
        subprocess.run(
            [
                "sops",
                "--config",
                str(gpg_sops_config),
                "--encrypt",
                "--output",
                str(encrypted_file),
                str(sample_secrets_yaml),
            ],
            env=env,
            check=True,
            capture_output=True,
        )

        # Verify encrypted file exists and contains sops metadata
        assert encrypted_file.exists()
        encrypted_content = encrypted_file.read_text()
        assert "sops:" in encrypted_content
        assert "ENC[AES256_GCM" in encrypted_content

        # Decrypt
        subprocess.run(
            [
                "sops",
                "--config",
                str(gpg_sops_config),
                "--decrypt",
                "--output",
                str(decrypted_file),
                str(encrypted_file),
            ],
            env=env,
            check=True,
            capture_output=True,
        )

        # Verify roundtrip
        original = yaml.safe_load(sample_secrets_yaml.read_text())
        decrypted = yaml.safe_load(decrypted_file.read_text())
        assert original == decrypted

    def test_gpg_fingerprint_in_encrypted_file(
        self,
        tmp_path: Path,
        gpg_keypair: dict[str, Any],
        gpg_sops_config: Path,
        sample_secrets_yaml: Path,
    ) -> None:
        """Verify GPG fingerprint is recorded in encrypted file metadata."""
        encrypted_file = tmp_path / "secrets.enc.yaml"

        env = {
            **os.environ,
            "GNUPGHOME": str(gpg_keypair["gnupghome"]),
        }

        subprocess.run(
            [
                "sops",
                "--config",
                str(gpg_sops_config),
                "--encrypt",
                "--output",
                str(encrypted_file),
                str(sample_secrets_yaml),
            ],
            env=env,
            check=True,
            capture_output=True,
        )

        encrypted_content = encrypted_file.read_text()

        # GPG fingerprint should be in sops metadata
        assert gpg_keypair["fingerprint"] in encrypted_content


# =============================================================================
# KMS Backend Tests (LocalStack)
# =============================================================================


@requires_sops
@requires_boto3
@requires_localstack
class TestSopsKmsBackend:
    """E2E tests for SOPS with KMS encryption backend via LocalStack."""

    def test_encrypt_decrypt_yaml_roundtrip(
        self,
        tmp_path: Path,
        kms_sops_config: Path,
        sample_secrets_yaml: Path,
        localstack_endpoint: str,
        localstack_region: str,
    ) -> None:
        """Encrypt and decrypt YAML file using KMS via LocalStack."""
        encrypted_file = tmp_path / "secrets.enc.yaml"
        decrypted_file = tmp_path / "secrets.dec.yaml"

        env = {
            **os.environ,
            "AWS_ACCESS_KEY_ID": "test",
            "AWS_SECRET_ACCESS_KEY": "test",
            "AWS_DEFAULT_REGION": localstack_region,
            # SOPS uses this env var for custom endpoints
            "AWS_ENDPOINT_URL": localstack_endpoint,
        }

        # Encrypt
        result = subprocess.run(
            [
                "sops",
                "--config",
                str(kms_sops_config),
                "--encrypt",
                "--output",
                str(encrypted_file),
                str(sample_secrets_yaml),
            ],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        if result.returncode != 0:
            pytest.skip(f"SOPS KMS encryption failed (LocalStack issue?): {result.stderr}")

        # Verify encrypted file exists and contains sops metadata
        assert encrypted_file.exists()
        encrypted_content = encrypted_file.read_text()
        assert "sops:" in encrypted_content
        assert "ENC[AES256_GCM" in encrypted_content

        # Decrypt
        result = subprocess.run(
            [
                "sops",
                "--config",
                str(kms_sops_config),
                "--decrypt",
                "--output",
                str(decrypted_file),
                str(encrypted_file),
            ],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        if result.returncode != 0:
            pytest.skip(f"SOPS KMS decryption failed (LocalStack issue?): {result.stderr}")

        # Verify roundtrip
        original = yaml.safe_load(sample_secrets_yaml.read_text())
        decrypted = yaml.safe_load(decrypted_file.read_text())
        assert original == decrypted

    def test_kms_arn_in_encrypted_file(
        self,
        tmp_path: Path,
        kms_sops_config: Path,
        sample_secrets_yaml: Path,
        localstack_endpoint: str,
        localstack_region: str,
        localstack_key_alias: str,
    ) -> None:
        """Verify KMS key info is recorded in encrypted file metadata."""
        encrypted_file = tmp_path / "secrets.enc.yaml"

        env = {
            **os.environ,
            "AWS_ACCESS_KEY_ID": "test",
            "AWS_SECRET_ACCESS_KEY": "test",
            "AWS_DEFAULT_REGION": localstack_region,
            "AWS_ENDPOINT_URL": localstack_endpoint,
        }

        result = subprocess.run(
            [
                "sops",
                "--config",
                str(kms_sops_config),
                "--encrypt",
                "--output",
                str(encrypted_file),
                str(sample_secrets_yaml),
            ],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        if result.returncode != 0:
            pytest.skip(f"SOPS KMS encryption failed: {result.stderr}")

        encrypted_content = encrypted_file.read_text()

        # KMS key should be referenced in sops metadata
        assert "kms:" in encrypted_content or "arn:aws:kms" in encrypted_content


# =============================================================================
# CLI Integration Tests
# =============================================================================


@requires_sops
@requires_age
class TestKstlibSecretsCliAge:
    """E2E tests for kstlib secrets CLI with age backend."""

    def test_cli_encrypt_decrypt_roundtrip(
        self,
        tmp_path: Path,
        age_keypair: dict[str, Any],
        age_sops_config: Path,
        sample_secrets_yaml: Path,
    ) -> None:
        """Test kstlib secrets encrypt/decrypt CLI commands."""
        encrypted_file = tmp_path / "secrets.enc.yaml"
        decrypted_file = tmp_path / "secrets.dec.yaml"

        env = {
            **os.environ,
            "SOPS_AGE_KEY_FILE": str(age_keypair["keys_file"]),
        }

        # Encrypt using kstlib CLI
        result = subprocess.run(
            [
                "kstlib",
                "secrets",
                "encrypt",
                str(sample_secrets_yaml),
                "--out",
                str(encrypted_file),
                "--config",
                str(age_sops_config),
            ],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        # Check if kstlib command worked
        if result.returncode != 0:
            pytest.fail(f"kstlib secrets encrypt failed: {result.stderr}")

        assert encrypted_file.exists()

        # Decrypt using kstlib CLI
        result = subprocess.run(
            [
                "kstlib",
                "secrets",
                "decrypt",
                str(encrypted_file),
                "--out",
                str(decrypted_file),
            ],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        if result.returncode != 0:
            pytest.fail(f"kstlib secrets decrypt failed: {result.stderr}")

        # Verify roundtrip
        original = yaml.safe_load(sample_secrets_yaml.read_text())
        decrypted = yaml.safe_load(decrypted_file.read_text())
        assert original == decrypted
