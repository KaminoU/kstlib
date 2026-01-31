"""Tests for cipher key resolution."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from kstlib.db.cipher import apply_cipher_key, resolve_cipher_key
from kstlib.db.exceptions import EncryptionError


class TestResolveCipherKey:
    """Tests for resolve_cipher_key function."""

    def test_direct_passphrase(self) -> None:
        """Direct passphrase is returned as-is."""
        key = resolve_cipher_key(passphrase="my-secret-key")
        assert key == "my-secret-key"

    def test_passphrase_has_priority(self) -> None:
        """Passphrase takes priority over env_var."""
        with patch.dict(os.environ, {"DB_KEY": "env-key"}):
            key = resolve_cipher_key(passphrase="direct-key", env_var="DB_KEY")
            assert key == "direct-key"

    def test_env_var_resolution(self) -> None:
        """Key resolved from environment variable."""
        with patch.dict(os.environ, {"TEST_DB_KEY": "secret-from-env"}):
            key = resolve_cipher_key(env_var="TEST_DB_KEY")
            assert key == "secret-from-env"

    def test_env_var_missing_raises(self) -> None:
        """Missing environment variable raises EncryptionError."""
        with patch.dict(os.environ, {}, clear=True):
            # Ensure variable doesn't exist
            os.environ.pop("NONEXISTENT_KEY", None)
            with pytest.raises(EncryptionError, match="not set or empty"):
                resolve_cipher_key(env_var="NONEXISTENT_KEY")

    def test_env_var_empty_raises(self) -> None:
        """Empty environment variable raises EncryptionError."""
        with (
            patch.dict(os.environ, {"EMPTY_KEY": ""}),
            pytest.raises(EncryptionError, match="not set or empty"),
        ):
            resolve_cipher_key(env_var="EMPTY_KEY")

    def test_no_source_raises(self) -> None:
        """No key source raises EncryptionError."""
        with pytest.raises(EncryptionError, match="No encryption key source"):
            resolve_cipher_key()

    def test_sops_resolution(self) -> None:
        """Key resolved from SOPS file."""
        mock_record = MagicMock()
        mock_record.value = "sops-secret"
        mock_provider = MagicMock()
        mock_provider.resolve.return_value = mock_record

        with patch("kstlib.secrets.providers.sops.SOPSProvider", return_value=mock_provider):
            key = resolve_cipher_key(sops_path="secrets.yml")
            assert key == "sops-secret"

    def test_sops_custom_key_name(self) -> None:
        """Custom key name in SOPS file."""
        mock_record = MagicMock()
        mock_record.value = "custom-secret"
        mock_provider = MagicMock()
        mock_provider.resolve.return_value = mock_record

        with patch("kstlib.secrets.providers.sops.SOPSProvider", return_value=mock_provider):
            key = resolve_cipher_key(sops_path="secrets.yml", sops_key="custom_key")
            assert key == "custom-secret"
            # Verify the key name was passed correctly
            call_args = mock_provider.resolve.call_args[0][0]
            assert call_args.name == "custom_key"

    def test_sops_key_not_found_raises(self) -> None:
        """Missing key in SOPS file raises EncryptionError."""
        mock_provider = MagicMock()
        mock_provider.resolve.return_value = None

        with (
            patch(
                "kstlib.secrets.providers.sops.SOPSProvider",
                return_value=mock_provider,
            ),
            pytest.raises(EncryptionError, match="not found in SOPS"),
        ):
            resolve_cipher_key(sops_path="secrets.yml", sops_key="missing_key")

    def test_sops_resolution_error(self) -> None:
        """SOPS resolution error wrapped in EncryptionError."""
        mock_provider = MagicMock()
        mock_provider.resolve.side_effect = RuntimeError("SOPS failed")

        with (
            patch(
                "kstlib.secrets.providers.sops.SOPSProvider",
                return_value=mock_provider,
            ),
            pytest.raises(EncryptionError, match="Failed to resolve SOPS"),
        ):
            resolve_cipher_key(sops_path="secrets.yml")


class TestApplyCipherKey:
    """Tests for apply_cipher_key function."""

    def test_applies_key_to_connection(self) -> None:
        """Key is applied via PRAGMA."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.execute.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (0,)

        apply_cipher_key(mock_conn, "test-key")

        # Check PRAGMA key was called
        calls = [str(call) for call in mock_conn.execute.call_args_list]
        assert any("PRAGMA key" in call for call in calls)

    def test_verifies_key_works(self) -> None:
        """Key verification query is executed."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.execute.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (0,)

        apply_cipher_key(mock_conn, "test-key")

        # Check sqlite_master was queried
        calls = [str(call) for call in mock_conn.execute.call_args_list]
        assert any("sqlite_master" in call for call in calls)

    def test_invalid_key_raises(self) -> None:
        """Invalid key raises EncryptionError."""
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = RuntimeError("file is not a database")

        with pytest.raises(EncryptionError, match="Failed to apply cipher key"):
            apply_cipher_key(mock_conn, "wrong-key")

    def test_key_with_single_quotes_escaped(self) -> None:
        """Single quotes in key are escaped to prevent SQL injection."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.execute.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (0,)

        # Key containing single quotes that could break SQL
        key_with_quotes = "pass'word'; DROP TABLE users; --"
        apply_cipher_key(mock_conn, key_with_quotes)

        # Verify the PRAGMA call has escaped quotes (doubled)
        pragma_call = mock_conn.execute.call_args_list[0]
        sql = pragma_call[0][0]
        # Escaped key should have doubled quotes
        assert "pass''word''; DROP TABLE users; --" in sql
        assert "PRAGMA key" in sql
