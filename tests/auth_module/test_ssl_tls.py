"""SSL/TLS configuration tests for auth module.

Tests cover:
- Default secure configuration
- Custom CA bundle validation
- Security hardening (deep defense)
- Attack vector prevention
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from kstlib.auth.config import build_provider_config
from kstlib.auth.providers.base import AuthProviderConfig
from kstlib.auth.providers.oauth2 import OAuth2Provider
from kstlib.auth.token import MemoryTokenStorage


# ─────────────────────────────────────────────────────────────────────────────
# Test fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def valid_pem_content() -> str:
    """Return valid PEM certificate content for testing."""
    return (
        "-----BEGIN CERTIFICATE-----\n"
        "MIIBkTCB+wIJAKHBfpL7FakeTestCertificateDataHereXYZ123\n"
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ\n"
        "-----END CERTIFICATE-----\n"
    )


@pytest.fixture
def ca_bundle_file(tmp_path: pytest.TempPathFactory, valid_pem_content: str):
    """Create a valid CA bundle file for testing."""
    ca_file = tmp_path / "ca-bundle.pem"
    ca_file.write_text(valid_pem_content)
    return ca_file


# ─────────────────────────────────────────────────────────────────────────────
# AuthProviderConfig SSL tests
# ─────────────────────────────────────────────────────────────────────────────


class TestAuthProviderConfigSSL:
    """Tests for SSL configuration in AuthProviderConfig."""

    def test_ssl_verify_default_true(self) -> None:
        """SSL verification is enabled by default (secure by default)."""
        config = AuthProviderConfig(
            client_id="app",
            issuer="https://example.com",
        )
        assert config.ssl_verify is True

    def test_ssl_ca_bundle_default_none(self) -> None:
        """CA bundle is None by default."""
        config = AuthProviderConfig(
            client_id="app",
            issuer="https://example.com",
        )
        assert config.ssl_ca_bundle is None

    def test_ssl_verify_false_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Disabling SSL verification logs a security warning."""
        with caplog.at_level("WARNING"):
            AuthProviderConfig(
                client_id="app",
                issuer="https://example.com",
                ssl_verify=False,
            )
        assert "SECURITY" in caplog.text
        assert "MITM" in caplog.text

    def test_ssl_ca_bundle_valid_path(self, tmp_path: pytest.TempPathFactory, valid_pem_content: str) -> None:
        """Valid CA bundle path is accepted and normalized."""
        ca_file = tmp_path / "ca.pem"
        ca_file.write_text(valid_pem_content)

        config = AuthProviderConfig(
            client_id="app",
            issuer="https://example.com",
            ssl_ca_bundle=str(ca_file),
        )
        # Path should be normalized to absolute
        assert config.ssl_ca_bundle == str(ca_file.resolve())

    def test_ssl_ca_bundle_nonexistent_raises(self) -> None:
        """Non-existent CA bundle path raises ValueError."""
        with pytest.raises(ValueError, match="does not exist"):
            AuthProviderConfig(
                client_id="app",
                issuer="https://example.com",
                ssl_ca_bundle="/nonexistent/path/ca.pem",
            )

    def test_ssl_ca_bundle_directory_raises(self, tmp_path: pytest.TempPathFactory) -> None:
        """Directory path (not file) raises ValueError."""
        with pytest.raises(ValueError, match="must be a file"):
            AuthProviderConfig(
                client_id="app",
                issuer="https://example.com",
                ssl_ca_bundle=str(tmp_path),
            )

    @pytest.mark.skipif(os.name == "nt", reason="Unix HOME expansion only")
    def test_ssl_ca_bundle_expands_user(
        self, tmp_path: pytest.TempPathFactory, valid_pem_content: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tilde in path is expanded to user home."""
        # Mock home directory
        monkeypatch.setenv("HOME", str(tmp_path))

        # Create file in "home"
        ca_file = tmp_path / "my-ca.pem"
        ca_file.write_text(valid_pem_content)

        config = AuthProviderConfig(
            client_id="app",
            issuer="https://example.com",
            ssl_ca_bundle="~/my-ca.pem",
        )
        assert config.ssl_ca_bundle == str(ca_file.resolve())


# ─────────────────────────────────────────────────────────────────────────────
# OAuth2Provider SSL tests
# ─────────────────────────────────────────────────────────────────────────────


class TestOAuth2ProviderSSL:
    """Tests for SSL handling in OAuth2Provider HTTP client."""

    def test_http_client_verify_true_default(self) -> None:
        """HTTP client uses verify=True by default."""
        config = AuthProviderConfig(
            client_id="app",
            authorize_url="https://example.com/authorize",
            token_url="https://example.com/token",
        )
        provider = OAuth2Provider("test", config, MemoryTokenStorage())

        assert provider._build_ssl_context() is True

    def test_http_client_verify_false(self) -> None:
        """HTTP client uses verify=False when configured."""
        config = AuthProviderConfig(
            client_id="app",
            authorize_url="https://example.com/authorize",
            token_url="https://example.com/token",
            ssl_verify=False,
        )
        provider = OAuth2Provider("test", config, MemoryTokenStorage())

        assert provider._build_ssl_context() is False

    def test_http_client_verify_ca_bundle(self, tmp_path: pytest.TempPathFactory, valid_pem_content: str) -> None:
        """HTTP client uses CA bundle path when configured."""
        ca_file = tmp_path / "ca.pem"
        ca_file.write_text(valid_pem_content)

        config = AuthProviderConfig(
            client_id="app",
            authorize_url="https://example.com/authorize",
            token_url="https://example.com/token",
            ssl_ca_bundle=str(ca_file),
        )
        provider = OAuth2Provider("test", config, MemoryTokenStorage())

        ssl_context = provider._build_ssl_context()
        assert ssl_context == str(ca_file.resolve())

    def test_ssl_ca_bundle_takes_precedence(self, tmp_path: pytest.TempPathFactory, valid_pem_content: str) -> None:
        """CA bundle takes precedence over ssl_verify=False."""
        ca_file = tmp_path / "ca.pem"
        ca_file.write_text(valid_pem_content)

        config = AuthProviderConfig(
            client_id="app",
            authorize_url="https://example.com/authorize",
            token_url="https://example.com/token",
            ssl_verify=False,
            ssl_ca_bundle=str(ca_file),
        )
        provider = OAuth2Provider("test", config, MemoryTokenStorage())

        # CA bundle should be used, not False
        ssl_context = provider._build_ssl_context()
        assert ssl_context == str(ca_file.resolve())

    def test_http_client_created_with_verify_false(self) -> None:
        """HTTP client is created with verify=False when ssl_verify=False."""
        config = AuthProviderConfig(
            client_id="app",
            authorize_url="https://example.com/authorize",
            token_url="https://example.com/token",
            ssl_verify=False,
        )
        provider = OAuth2Provider("test", config, MemoryTokenStorage())

        # Access http_client to trigger creation
        client = provider.http_client

        # Verify the client was created
        assert client is not None
        assert provider._http_client is client
        # Verify ssl context is False (can't directly inspect httpx client verify param)
        assert provider._build_ssl_context() is False


# ─────────────────────────────────────────────────────────────────────────────
# build_provider_config SSL tests
# ─────────────────────────────────────────────────────────────────────────────


class TestBuildProviderConfigSSL:
    """Tests for SSL options in config parsing."""

    def test_parse_ssl_verify_true(self) -> None:
        """Parse ssl_verify: true from YAML."""
        config = {
            "providers": {
                "test": {
                    "client_id": "app",
                    "issuer": "https://example.com",
                    "ssl_verify": True,
                }
            }
        }
        provider_config = build_provider_config("test", config=config)
        assert provider_config.ssl_verify is True

    def test_parse_ssl_verify_false(self) -> None:
        """Parse ssl_verify: false from YAML."""
        config = {
            "providers": {
                "test": {
                    "client_id": "app",
                    "issuer": "https://example.com",
                    "ssl_verify": False,
                }
            }
        }
        provider_config = build_provider_config("test", config=config)
        assert provider_config.ssl_verify is False

    def test_parse_ssl_ca_bundle(self, tmp_path: pytest.TempPathFactory, valid_pem_content: str) -> None:
        """Parse ssl_ca_bundle path from YAML."""
        ca_file = tmp_path / "ca.pem"
        ca_file.write_text(valid_pem_content)

        config = {
            "providers": {
                "test": {
                    "client_id": "app",
                    "issuer": "https://example.com",
                    "ssl_ca_bundle": str(ca_file),
                }
            }
        }
        provider_config = build_provider_config("test", config=config)
        assert provider_config.ssl_ca_bundle == str(ca_file.resolve())

    def test_ssl_options_default_when_missing(self) -> None:
        """SSL options default to secure values when not specified."""
        config = {
            "providers": {
                "test": {
                    "client_id": "app",
                    "issuer": "https://example.com",
                }
            }
        }
        provider_config = build_provider_config("test", config=config)
        assert provider_config.ssl_verify is True
        assert provider_config.ssl_ca_bundle is None


# ─────────────────────────────────────────────────────────────────────────────
# Security hardening tests (deep defense)
# ─────────────────────────────────────────────────────────────────────────────


class TestSSLSecurityHardening:
    """Security hardening tests for SSL configuration.

    Tests all attack vectors:
    - Type confusion attacks
    - Path traversal attacks
    - Null byte injection
    - Symlink attacks
    - Permission bypass
    - Empty/malformed file attacks
    """

    # ─────────────────────────────────────────────────────────────────────
    # Type validation tests
    # ─────────────────────────────────────────────────────────────────────

    def test_ssl_verify_rejects_string_false(self) -> None:
        """ssl_verify='false' (string) raises TypeError."""
        with pytest.raises(TypeError, match="must be bool"):
            AuthProviderConfig(
                client_id="app",
                issuer="https://example.com",
                ssl_verify="false",  # type: ignore[arg-type]
            )

    def test_ssl_verify_rejects_string_true(self) -> None:
        """ssl_verify='true' (string) raises TypeError."""
        with pytest.raises(TypeError, match="must be bool"):
            AuthProviderConfig(
                client_id="app",
                issuer="https://example.com",
                ssl_verify="true",  # type: ignore[arg-type]
            )

    def test_ssl_verify_rejects_int_zero(self) -> None:
        """ssl_verify=0 (int) raises TypeError."""
        with pytest.raises(TypeError, match="must be bool"):
            AuthProviderConfig(
                client_id="app",
                issuer="https://example.com",
                ssl_verify=0,  # type: ignore[arg-type]
            )

    def test_ssl_verify_rejects_int_one(self) -> None:
        """ssl_verify=1 (int) raises TypeError."""
        with pytest.raises(TypeError, match="must be bool"):
            AuthProviderConfig(
                client_id="app",
                issuer="https://example.com",
                ssl_verify=1,  # type: ignore[arg-type]
            )

    def test_ssl_ca_bundle_rejects_non_string(self) -> None:
        """ssl_ca_bundle must be string, not list/dict/int."""
        with pytest.raises(TypeError, match="must be str"):
            AuthProviderConfig(
                client_id="app",
                issuer="https://example.com",
                ssl_ca_bundle=123,  # type: ignore[arg-type]
            )

    def test_ssl_ca_bundle_rejects_list(self) -> None:
        """ssl_ca_bundle must be string, not list."""
        with pytest.raises(TypeError, match="must be str"):
            AuthProviderConfig(
                client_id="app",
                issuer="https://example.com",
                ssl_ca_bundle=["/path/to/ca.pem"],  # type: ignore[arg-type]
            )

    # ─────────────────────────────────────────────────────────────────────
    # Path injection/traversal tests
    # ─────────────────────────────────────────────────────────────────────

    def test_null_byte_injection_blocked(self) -> None:
        """Null byte in path is rejected (CVE-style attack)."""
        with pytest.raises(ValueError, match="null byte"):
            AuthProviderConfig(
                client_id="app",
                issuer="https://example.com",
                ssl_ca_bundle="/etc/ssl/certs/ca.pem\x00.txt",
            )

    def test_path_traversal_blocked(self) -> None:
        """Path traversal attempts are blocked (nonexistent path)."""
        with pytest.raises(ValueError, match="does not exist"):
            AuthProviderConfig(
                client_id="app",
                issuer="https://example.com",
                ssl_ca_bundle="../../../etc/passwd",
            )

    def test_empty_string_path_rejected(self) -> None:
        """Empty string path is rejected."""
        with pytest.raises(ValueError, match="cannot be empty"):
            AuthProviderConfig(
                client_id="app",
                issuer="https://example.com",
                ssl_ca_bundle="",
            )

    def test_whitespace_only_path_rejected(self) -> None:
        """Whitespace-only path is rejected."""
        with pytest.raises(ValueError, match="cannot be empty"):
            AuthProviderConfig(
                client_id="app",
                issuer="https://example.com",
                ssl_ca_bundle="   ",
            )

    # ─────────────────────────────────────────────────────────────────────
    # File validation tests
    # ─────────────────────────────────────────────────────────────────────

    def test_directory_rejected(self, tmp_path: pytest.TempPathFactory) -> None:
        """Directory path (not file) is rejected."""
        with pytest.raises(ValueError, match="must be a file"):
            AuthProviderConfig(
                client_id="app",
                issuer="https://example.com",
                ssl_ca_bundle=str(tmp_path),
            )

    def test_empty_file_rejected(self, tmp_path: pytest.TempPathFactory) -> None:
        """Empty CA bundle file is rejected."""
        empty_file = tmp_path / "empty.pem"
        empty_file.touch()

        with pytest.raises(ValueError, match="file too small"):
            AuthProviderConfig(
                client_id="app",
                issuer="https://example.com",
                ssl_ca_bundle=str(empty_file),
            )

    def test_too_small_file_rejected(self, tmp_path: pytest.TempPathFactory) -> None:
        """File smaller than minimum PEM size is rejected."""
        tiny_file = tmp_path / "tiny.pem"
        tiny_file.write_text("abc")  # 3 bytes, too small

        with pytest.raises(ValueError, match="too small"):
            AuthProviderConfig(
                client_id="app",
                issuer="https://example.com",
                ssl_ca_bundle=str(tiny_file),
            )

    def test_non_pem_file_rejected(self, tmp_path: pytest.TempPathFactory) -> None:
        """File without PEM markers is rejected."""
        not_pem = tmp_path / "not_a_cert.txt"
        not_pem.write_text("x" * 100)  # Valid size but not PEM

        with pytest.raises(ValueError, match="not.*PEM format"):
            AuthProviderConfig(
                client_id="app",
                issuer="https://example.com",
                ssl_ca_bundle=str(not_pem),
            )

    def test_binary_file_rejected(self, tmp_path: pytest.TempPathFactory) -> None:
        """Binary file (not text) is rejected."""
        binary_file = tmp_path / "binary.bin"
        # Use bytes that will cause UnicodeDecodeError
        binary_file.write_bytes(b"\xff\xfe\x00\x01" * 50)

        with pytest.raises(ValueError, match="not valid text"):
            AuthProviderConfig(
                client_id="app",
                issuer="https://example.com",
                ssl_ca_bundle=str(binary_file),
            )

    @pytest.mark.skipif(os.name == "nt", reason="Unix permissions only")
    def test_unreadable_file_rejected(self, tmp_path: pytest.TempPathFactory) -> None:
        """File without read permission is rejected."""
        unreadable = tmp_path / "unreadable.pem"
        unreadable.write_text("-----BEGIN CERTIFICATE-----\ndata\n-----END CERTIFICATE-----")
        unreadable.chmod(0o000)

        try:
            with pytest.raises(ValueError, match="not readable"):
                AuthProviderConfig(
                    client_id="app",
                    issuer="https://example.com",
                    ssl_ca_bundle=str(unreadable),
                )
        finally:
            unreadable.chmod(0o644)  # Restore for cleanup

    # ─────────────────────────────────────────────────────────────────────
    # Symlink tests
    # ─────────────────────────────────────────────────────────────────────

    @pytest.mark.skipif(os.name == "nt", reason="Unix symlinks only")
    def test_symlink_resolved_to_target(self, tmp_path: pytest.TempPathFactory, valid_pem_content: str) -> None:
        """Symlink is resolved to actual file path."""
        real_file = tmp_path / "real_ca.pem"
        real_file.write_text(valid_pem_content)

        symlink = tmp_path / "link_to_ca.pem"
        symlink.symlink_to(real_file)

        config = AuthProviderConfig(
            client_id="app",
            issuer="https://example.com",
            ssl_ca_bundle=str(symlink),
        )
        # Path should be resolved to real file
        assert config.ssl_ca_bundle == str(real_file.resolve())

    @pytest.mark.skipif(os.name == "nt", reason="Unix symlinks only")
    def test_broken_symlink_rejected(self, tmp_path: pytest.TempPathFactory) -> None:
        """Broken symlink is rejected."""
        broken_link = tmp_path / "broken.pem"
        broken_link.symlink_to("/nonexistent/target.pem")

        with pytest.raises(ValueError, match="does not exist"):
            AuthProviderConfig(
                client_id="app",
                issuer="https://example.com",
                ssl_ca_bundle=str(broken_link),
            )

    # ─────────────────────────────────────────────────────────────────────
    # Valid CA bundle tests (positive cases)
    # ─────────────────────────────────────────────────────────────────────

    def test_valid_pem_accepted(self, tmp_path: pytest.TempPathFactory) -> None:
        """Valid PEM file is accepted."""
        valid_pem = tmp_path / "ca-bundle.pem"
        valid_pem.write_text(
            "-----BEGIN CERTIFICATE-----\nMIIBkTCB+wIJAKHBfpL7FakeCertData123ABC\n-----END CERTIFICATE-----\n"
        )

        config = AuthProviderConfig(
            client_id="app",
            issuer="https://example.com",
            ssl_ca_bundle=str(valid_pem),
        )
        assert config.ssl_ca_bundle == str(valid_pem.resolve())

    def test_valid_pem_with_multiple_certs(self, tmp_path: pytest.TempPathFactory) -> None:
        """PEM file with multiple certificates is accepted."""
        multi_pem = tmp_path / "multi-ca.pem"
        multi_pem.write_text(
            "-----BEGIN CERTIFICATE-----\n"
            "MIIBkTCB+wIJAKHBfpL7FakeCert1Data\n"
            "-----END CERTIFICATE-----\n"
            "-----BEGIN CERTIFICATE-----\n"
            "MIIBkTCB+wIJAKHBfpL7FakeCert2Data\n"
            "-----END CERTIFICATE-----\n"
        )

        config = AuthProviderConfig(
            client_id="app",
            issuer="https://example.com",
            ssl_ca_bundle=str(multi_pem),
        )
        assert config.ssl_ca_bundle == str(multi_pem.resolve())

    @pytest.mark.skipif(os.name == "nt", reason="Unix HOME expansion only")
    def test_tilde_expansion(
        self, tmp_path: pytest.TempPathFactory, valid_pem_content: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tilde (~) in path is expanded to home directory."""
        # Mock home directory
        monkeypatch.setenv("HOME", str(tmp_path))

        # Create file in "home"
        ca_file = tmp_path / "my-ca.pem"
        ca_file.write_text(valid_pem_content)

        config = AuthProviderConfig(
            client_id="app",
            issuer="https://example.com",
            ssl_ca_bundle="~/my-ca.pem",
        )
        assert config.ssl_ca_bundle == str(ca_file.resolve())

    def test_relative_path_resolved_to_absolute(
        self, tmp_path: pytest.TempPathFactory, valid_pem_content: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Relative path is resolved to absolute path."""
        # Change to tmp_path directory
        monkeypatch.chdir(tmp_path)

        ca_file = tmp_path / "relative-ca.pem"
        ca_file.write_text(valid_pem_content)

        config = AuthProviderConfig(
            client_id="app",
            issuer="https://example.com",
            ssl_ca_bundle="relative-ca.pem",
        )
        # Should be absolute path now
        assert os.path.isabs(config.ssl_ca_bundle)
        assert config.ssl_ca_bundle == str(ca_file.resolve())
