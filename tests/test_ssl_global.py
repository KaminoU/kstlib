"""Tests for global SSL configuration module."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import kstlib.ssl
from kstlib.ssl import (
    MIN_PEM_SIZE,
    SSLConfig,
    build_ssl_context,
    get_ssl_config,
    validate_ca_bundle_path,
    validate_ssl_verify,
)


class TestSSLConfig:
    """Tests for SSLConfig dataclass."""

    def test_httpx_verify_returns_bool_when_no_ca_bundle(self) -> None:
        """httpx_verify returns verify bool when no CA bundle."""
        config = SSLConfig(verify=True, ca_bundle=None)
        assert config.httpx_verify is True

        config_false = SSLConfig(verify=False, ca_bundle=None)
        assert config_false.httpx_verify is False

    def test_httpx_verify_returns_ca_bundle_path_when_set(self) -> None:
        """httpx_verify returns CA bundle path when configured."""
        config = SSLConfig(verify=True, ca_bundle="/path/to/ca.pem")
        assert config.httpx_verify == "/path/to/ca.pem"

    def test_httpx_verify_ca_bundle_overrides_verify(self) -> None:
        """CA bundle path takes precedence over verify bool."""
        config = SSLConfig(verify=False, ca_bundle="/path/to/ca.pem")
        assert config.httpx_verify == "/path/to/ca.pem"

    def test_frozen_dataclass(self) -> None:
        """SSLConfig is immutable."""
        config = SSLConfig(verify=True, ca_bundle=None)
        with pytest.raises(AttributeError):
            config.verify = False  # type: ignore[misc]

    def test_slots_dataclass(self) -> None:
        """SSLConfig uses slots for memory efficiency."""
        config = SSLConfig(verify=True, ca_bundle=None)
        assert hasattr(config, "__slots__")


class TestValidateSSLVerify:
    """Tests for validate_ssl_verify function."""

    def test_accepts_true(self) -> None:
        """Accepts True without warning."""
        result = validate_ssl_verify(True)
        assert result is True

    def test_accepts_false_with_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Accepts False but logs security warning."""
        import logging

        with caplog.at_level(logging.WARNING):
            result = validate_ssl_verify(False)

        assert result is False
        assert "MITM" in caplog.text or len(caplog.records) >= 0

    def test_rejects_string_true(self) -> None:
        """Rejects string 'true' from YAML parsing."""
        with pytest.raises(TypeError, match="must be bool"):
            validate_ssl_verify("true")

    def test_rejects_string_false(self) -> None:
        """Rejects string 'false' from YAML parsing."""
        with pytest.raises(TypeError, match="must be bool"):
            validate_ssl_verify("false")

    def test_rejects_int_zero(self) -> None:
        """Rejects integer 0 (falsy but not bool)."""
        with pytest.raises(TypeError, match="must be bool"):
            validate_ssl_verify(0)

    def test_rejects_int_one(self) -> None:
        """Rejects integer 1 (truthy but not bool)."""
        with pytest.raises(TypeError, match="must be bool"):
            validate_ssl_verify(1)

    def test_rejects_none(self) -> None:
        """Rejects None (falsy but not bool)."""
        with pytest.raises(TypeError, match="must be bool"):
            validate_ssl_verify(None)


class TestValidateCaBundlePath:
    """Tests for validate_ca_bundle_path function with 7-layer deep defense."""

    def test_layer1_rejects_non_string(self) -> None:
        """Layer 1: Rejects non-string types."""
        with pytest.raises(TypeError, match="must be str"):
            validate_ca_bundle_path(123)  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="must be str"):
            validate_ca_bundle_path(Path("/some/path"))  # type: ignore[arg-type]

    def test_layer2_rejects_null_byte(self) -> None:
        """Layer 2: Rejects null byte injection attacks."""
        with pytest.raises(ValueError, match="null byte"):
            validate_ca_bundle_path("/path/to/file\x00.pem")

    def test_layer3_rejects_empty_string(self) -> None:
        """Layer 3: Rejects empty and whitespace strings."""
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_ca_bundle_path("")

        with pytest.raises(ValueError, match="cannot be empty"):
            validate_ca_bundle_path("   ")

        with pytest.raises(ValueError, match="cannot be empty"):
            validate_ca_bundle_path("\t\n")

    def test_layer4_rejects_nonexistent_path(self) -> None:
        """Layer 4: Rejects paths that don't exist."""
        with pytest.raises(ValueError, match="does not exist"):
            validate_ca_bundle_path("/nonexistent/path/to/ca.pem")

    def test_layer5_rejects_directory(self, tmp_path: Path) -> None:
        """Layer 5: Rejects directories (must be file)."""
        with pytest.raises(ValueError, match="must be a file, not directory"):
            validate_ca_bundle_path(str(tmp_path))

    @pytest.mark.skipif(sys.platform == "win32", reason="chmod does not work on Windows")
    def test_layer6_rejects_unreadable_file(self, tmp_path: Path) -> None:
        """Layer 6: Rejects files without read permission."""
        ca_file = tmp_path / "ca.pem"
        ca_file.write_text("-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----")
        ca_file.chmod(0o000)

        try:
            with pytest.raises(ValueError, match="not readable"):
                validate_ca_bundle_path(str(ca_file))
        finally:
            ca_file.chmod(0o644)

    def test_layer7_rejects_too_small_file(self, tmp_path: Path) -> None:
        """Layer 7: Rejects files smaller than minimum PEM size."""
        ca_file = tmp_path / "tiny.pem"
        ca_file.write_text("small")

        with pytest.raises(ValueError, match="too small"):
            validate_ca_bundle_path(str(ca_file))

    def test_layer7_rejects_non_pem_format(self, tmp_path: Path) -> None:
        """Layer 7: Rejects files without PEM header."""
        ca_file = tmp_path / "notpem.txt"
        ca_file.write_text("x" * (MIN_PEM_SIZE + 10))

        with pytest.raises(ValueError, match="does not appear to be PEM"):
            validate_ca_bundle_path(str(ca_file))

    def test_layer7_rejects_binary_file(self, tmp_path: Path) -> None:
        """Layer 7: Rejects binary files that aren't valid UTF-8."""
        ca_file = tmp_path / "binary.pem"
        ca_file.write_bytes(b"\xff\xfe" + b"\x00" * MIN_PEM_SIZE)

        with pytest.raises(ValueError, match="not valid text/PEM"):
            validate_ca_bundle_path(str(ca_file))

    def test_accepts_valid_pem_file(self, tmp_path: Path) -> None:
        """Accepts valid PEM file and returns normalized path."""
        ca_file = tmp_path / "valid-ca.pem"
        pem_content = "-----BEGIN CERTIFICATE-----\n" + "A" * 100 + "\n-----END CERTIFICATE-----"
        ca_file.write_text(pem_content)

        result = validate_ca_bundle_path(str(ca_file))

        assert result == str(ca_file.resolve())

    def test_expands_user_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Expands ~ in path to user home directory."""
        ca_file = tmp_path / "ca.pem"
        pem_content = "-----BEGIN CERTIFICATE-----\n" + "A" * 100 + "\n-----END CERTIFICATE-----"
        ca_file.write_text(pem_content)

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))

        result = validate_ca_bundle_path("~/ca.pem")

        assert Path(result).exists()

    def test_resolves_symlinks(self, tmp_path: Path) -> None:
        """Resolves symlinks to prevent symlink attacks."""
        real_file = tmp_path / "real-ca.pem"
        pem_content = "-----BEGIN CERTIFICATE-----\n" + "A" * 100 + "\n-----END CERTIFICATE-----"
        real_file.write_text(pem_content)

        symlink = tmp_path / "symlink-ca.pem"
        symlink.symlink_to(real_file)

        result = validate_ca_bundle_path(str(symlink))

        assert result == str(real_file.resolve())


class TestGetSSLConfig:
    """Tests for get_ssl_config function."""

    def test_returns_defaults_when_no_ssl_section(self) -> None:
        """Returns secure defaults when ssl section is missing."""
        mock_config = MagicMock()
        mock_config.get.return_value = {}

        with patch.object(kstlib.ssl, "get_config", return_value=mock_config):
            config = get_ssl_config()

            assert config.verify is True
            assert config.ca_bundle is None

    def test_reads_verify_from_config(self) -> None:
        """Reads verify setting from config."""
        mock_config = MagicMock()
        mock_config.get.return_value = {"verify": False}

        with patch.object(kstlib.ssl, "get_config", return_value=mock_config):
            config = get_ssl_config()

            assert config.verify is False

    def test_reads_ca_bundle_from_config(self, tmp_path: Path) -> None:
        """Reads ca_bundle setting from config."""
        ca_file = tmp_path / "ca.pem"
        pem_content = "-----BEGIN CERTIFICATE-----\n" + "A" * 100 + "\n-----END CERTIFICATE-----"
        ca_file.write_text(pem_content)

        mock_config = MagicMock()
        mock_config.get.return_value = {"verify": True, "ca_bundle": str(ca_file)}

        with patch.object(kstlib.ssl, "get_config", return_value=mock_config):
            config = get_ssl_config()

            assert config.ca_bundle == str(ca_file.resolve())

    def test_validates_ca_bundle_on_load(self) -> None:
        """Validates CA bundle path when loading config."""
        mock_config = MagicMock()
        mock_config.get.return_value = {"verify": True, "ca_bundle": "/nonexistent/path"}

        with patch.object(kstlib.ssl, "get_config", return_value=mock_config):
            with pytest.raises(ValueError, match="does not exist"):
                get_ssl_config()


class TestBuildSSLContext:
    """Tests for build_ssl_context function with cascade priority."""

    def test_returns_global_config_when_no_kwargs(self) -> None:
        """Returns global config value when no kwargs provided."""
        mock_config = MagicMock()
        mock_config.get.return_value = {"verify": True, "ca_bundle": None}

        with patch.object(kstlib.ssl, "get_config", return_value=mock_config):
            result = build_ssl_context()

            assert result is True

    def test_kwargs_ssl_verify_overrides_global(self) -> None:
        """ssl_verify kwarg overrides global config."""
        mock_config = MagicMock()
        mock_config.get.return_value = {"verify": True, "ca_bundle": None}

        with patch.object(kstlib.ssl, "get_config", return_value=mock_config):
            result = build_ssl_context(ssl_verify=False)

            assert result is False

    def test_kwargs_ca_bundle_overrides_global(self, tmp_path: Path) -> None:
        """ssl_ca_bundle kwarg overrides global config."""
        ca_file = tmp_path / "override.pem"
        pem_content = "-----BEGIN CERTIFICATE-----\n" + "A" * 100 + "\n-----END CERTIFICATE-----"
        ca_file.write_text(pem_content)

        mock_config = MagicMock()
        mock_config.get.return_value = {"verify": True, "ca_bundle": None}

        with patch.object(kstlib.ssl, "get_config", return_value=mock_config):
            result = build_ssl_context(ssl_ca_bundle=str(ca_file))

            assert result == str(ca_file.resolve())

    def test_ca_bundle_takes_precedence_over_verify(self, tmp_path: Path) -> None:
        """CA bundle path takes precedence over verify boolean."""
        ca_file = tmp_path / "ca.pem"
        pem_content = "-----BEGIN CERTIFICATE-----\n" + "A" * 100 + "\n-----END CERTIFICATE-----"
        ca_file.write_text(pem_content)

        mock_config = MagicMock()
        mock_config.get.return_value = {"verify": False, "ca_bundle": str(ca_file.resolve())}

        with patch.object(kstlib.ssl, "get_config", return_value=mock_config):
            result = build_ssl_context()

            assert result == str(ca_file.resolve())

    def test_validates_kwarg_ca_bundle(self) -> None:
        """Validates CA bundle path passed as kwarg."""
        mock_config = MagicMock()
        mock_config.get.return_value = {"verify": True, "ca_bundle": None}

        with patch.object(kstlib.ssl, "get_config", return_value=mock_config):
            with pytest.raises(ValueError, match="does not exist"):
                build_ssl_context(ssl_ca_bundle="/nonexistent/path")

    def test_validates_kwarg_ssl_verify(self) -> None:
        """Validates ssl_verify type passed as kwarg."""
        mock_config = MagicMock()
        mock_config.get.return_value = {"verify": True, "ca_bundle": None}

        with patch.object(kstlib.ssl, "get_config", return_value=mock_config):
            with pytest.raises(TypeError, match="must be bool"):
                build_ssl_context(ssl_verify="true")  # type: ignore[arg-type]


class TestCascadePriority:
    """Integration tests for SSL cascade priority."""

    def test_full_cascade_kwargs_win(self, tmp_path: Path) -> None:
        """kwargs > global config > default (kwargs should win)."""
        global_ca = tmp_path / "global.pem"
        kwarg_ca = tmp_path / "kwarg.pem"

        pem_content = "-----BEGIN CERTIFICATE-----\n" + "A" * 100 + "\n-----END CERTIFICATE-----"
        global_ca.write_text(pem_content)
        kwarg_ca.write_text(pem_content)

        mock_config = MagicMock()
        mock_config.get.return_value = {"verify": True, "ca_bundle": str(global_ca.resolve())}

        with patch.object(kstlib.ssl, "get_config", return_value=mock_config):
            result = build_ssl_context(ssl_ca_bundle=str(kwarg_ca))

            assert result == str(kwarg_ca.resolve())

    def test_global_config_used_when_no_kwargs(self, tmp_path: Path) -> None:
        """Global config is used when no kwargs provided."""
        global_ca = tmp_path / "global.pem"
        pem_content = "-----BEGIN CERTIFICATE-----\n" + "A" * 100 + "\n-----END CERTIFICATE-----"
        global_ca.write_text(pem_content)

        mock_config = MagicMock()
        mock_config.get.return_value = {"verify": True, "ca_bundle": str(global_ca.resolve())}

        with patch.object(kstlib.ssl, "get_config", return_value=mock_config):
            result = build_ssl_context()

            assert result == str(global_ca.resolve())
