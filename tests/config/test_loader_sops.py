"""Tests for SOPS integration in the configuration loader.

This module tests automatic SOPS decryption for .sops.* files,
graceful degradation when SOPS is unavailable, and ENC[...] detection.
"""

# pylint: disable=protected-access,missing-function-docstring,import-outside-toplevel,unused-argument,line-too-long,redefined-outer-name
# Reason: Tests exercise internals, rely on pytest fixtures, and inline imports for targeted behaviour.

import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from kstlib.config import (
    ConfigSopsError,
    ConfigSopsNotAvailableError,
    SopsDecryptor,
    get_decryptor,
    get_real_extension,
    has_encrypted_values,
    is_sops_file,
    load_config,
    load_from_file,
    reset_decryptor,
)
from kstlib.config.loader import ConfigLoader

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def reset_sops_decryptor() -> Any:
    """Reset the global SOPS decryptor before and after each test."""
    reset_decryptor()
    yield
    reset_decryptor()


@pytest.fixture
def sops_encrypted_yaml(tmp_path: Path) -> Path:
    """Create a fake SOPS-encrypted YAML file."""
    content = """api_key: ENC[AES256_GCM,data:abc123,iv:xyz,tag:def,type:str]
db:
  password: ENC[AES256_GCM,data:secret123,iv:uvw,tag:ghi,type:str]
  host: localhost
"""
    path = tmp_path / "secrets.sops.yml"
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def decrypted_yaml_content() -> str:
    """Decrypted content that the mock SOPS binary should return."""
    return """api_key: real_api_key_value
db:
  password: super_secret_password
  host: localhost
"""


@pytest.fixture
def mock_sops_binary(tmp_path: Path, decrypted_yaml_content: str) -> Path:
    """Create a mock SOPS binary that returns decrypted content."""
    if sys.platform == "win32":
        script = tmp_path / "sops.bat"
        script.write_text(
            f"@echo off\necho {decrypted_yaml_content.replace(chr(10), '&echo.')}",
            encoding="utf-8",
        )
    else:
        script = tmp_path / "sops"
        script.write_text(
            f"#!/bin/bash\ncat << 'EOF'\n{decrypted_yaml_content}EOF\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
    return script


# ============================================================================
# is_sops_file() tests
# ============================================================================


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("secrets.sops.yml", True),
        ("config.sops.yaml", True),
        ("data.sops.json", True),
        ("settings.sops.toml", True),
        ("SECRETS.SOPS.YML", True),  # Case insensitive
        ("config.yml", False),
        ("secrets.yaml", False),
        ("data.json", False),
        ("settings.toml", False),
        ("sops.yml", False),  # Must have .sops. prefix
        ("my.sops.txt", False),  # .txt not supported
    ],
    ids=[
        "sops.yml",
        "sops.yaml",
        "sops.json",
        "sops.toml",
        "uppercase",
        "plain.yml",
        "plain.yaml",
        "plain.json",
        "plain.toml",
        "no-prefix",
        "unsupported-ext",
    ],
)
def test_is_sops_file(filename: str, expected: bool) -> None:
    """Test SOPS file detection by extension."""
    assert is_sops_file(Path(filename)) == expected


# ============================================================================
# get_real_extension() tests
# ============================================================================


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("secrets.sops.yml", ".yml"),
        ("config.sops.yaml", ".yaml"),
        ("data.sops.json", ".json"),
        ("settings.sops.toml", ".toml"),
        ("config.enc.yml", ".yml"),  # .enc marker also supported
        ("normal.yml", ".yml"),
        ("normal.json", ".json"),
    ],
    ids=[
        "sops.yml",
        "sops.yaml",
        "sops.json",
        "sops.toml",
        "enc.yml",
        "normal.yml",
        "normal.json",
    ],
)
def test_get_real_extension(filename: str, expected: str) -> None:
    """Test extraction of real format extension."""
    assert get_real_extension(Path(filename)) == expected


# ============================================================================
# has_encrypted_values() tests
# ============================================================================


def test_has_encrypted_values_finds_enc_markers() -> None:
    """Test detection of ENC[AES256_GCM,...] values in config data."""
    data = {
        "api_key": "ENC[AES256_GCM,data:abc123]",
        "db": {
            "password": "ENC[AES256_GCM,data:secret]",
            "host": "localhost",
        },
        "list": [
            {"key": "ENC[AES256_GCM,data:item]"},
            {"key": "normal"},
        ],
    }
    found = has_encrypted_values(data)
    assert "api_key" in found
    assert "db.password" in found
    assert "list[0].key" in found
    assert "db.host" not in found
    assert "list[1].key" not in found


def test_has_encrypted_values_empty_on_clean_data() -> None:
    """Test that clean data returns empty list."""
    data = {
        "api_key": "normal_value",
        "db": {"password": "secret", "host": "localhost"},
    }
    assert has_encrypted_values(data) == []


def test_has_encrypted_values_root_string() -> None:
    """Test detection when root is an encrypted string."""
    assert has_encrypted_values("ENC[AES256_GCM,data:root]") == ["<root>"]


# ============================================================================
# SopsDecryptor class tests
# ============================================================================


def test_sops_decryptor_init_defaults() -> None:
    """Test SopsDecryptor initialization with defaults."""
    decryptor = SopsDecryptor()
    assert decryptor.binary == "sops"
    assert decryptor.max_cache == 64  # DEFAULT_MAX_SOPS_CACHE_ENTRIES
    assert decryptor.cache_size == 0


def test_sops_decryptor_init_custom() -> None:
    """Test SopsDecryptor initialization with custom values."""
    decryptor = SopsDecryptor(binary="custom-sops", max_cache_entries=100)
    assert decryptor.binary == "custom-sops"
    assert decryptor.max_cache == 100


def test_sops_decryptor_cache_limit_clamped() -> None:
    """Test that cache size is clamped to hard maximum."""
    decryptor = SopsDecryptor(max_cache_entries=9999)
    assert decryptor.max_cache == 256  # HARD_MAX_SOPS_CACHE_ENTRIES


def test_sops_decryptor_raises_not_available(tmp_path: Path) -> None:
    """Test that missing SOPS binary raises ConfigSopsNotAvailableError."""
    decryptor = SopsDecryptor(binary="nonexistent-sops-binary-xyz")
    test_file = tmp_path / "test.sops.yml"
    test_file.write_text("key: value", encoding="utf-8")

    with pytest.raises(ConfigSopsNotAvailableError, match="not found in PATH"):
        decryptor.decrypt_file(test_file)


def test_sops_decryptor_raises_on_failure(tmp_path: Path, monkeypatch: Any) -> None:
    """Test that SOPS decryption failure raises ConfigSopsError."""
    # Create a fake sops that fails
    if sys.platform == "win32":
        fake_sops = tmp_path / "sops.bat"
        fake_sops.write_text("@echo off\necho Decryption failed >&2\nexit /b 1", encoding="utf-8")
    else:
        fake_sops = tmp_path / "sops"
        fake_sops.write_text("#!/bin/bash\necho 'Decryption failed' >&2\nexit 1", encoding="utf-8")
        fake_sops.chmod(0o755)

    # Add to PATH
    original_path = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{original_path}")

    test_file = tmp_path / "test.sops.yml"
    test_file.write_text("key: ENC[AES256_GCM,data:xxx]", encoding="utf-8")

    decryptor = SopsDecryptor()
    with pytest.raises(ConfigSopsError, match="Failed to decrypt"):
        decryptor.decrypt_file(test_file)


def test_sops_decryptor_caches_result(tmp_path: Path, monkeypatch: Any, decrypted_yaml_content: str) -> None:
    """Test that decrypted content is cached by mtime."""
    # Create a fake sops that counts calls
    call_count = {"count": 0}

    def mock_run(*args: Any, **kwargs: Any) -> MagicMock:
        call_count["count"] += 1
        result = MagicMock()
        result.returncode = 0
        result.stdout = decrypted_yaml_content
        result.stderr = ""
        return result

    test_file = tmp_path / "test.sops.yml"
    test_file.write_text("key: ENC[AES256_GCM,data:xxx]", encoding="utf-8")

    decryptor = SopsDecryptor()

    with patch("shutil.which", return_value="/fake/sops"):
        with patch("subprocess.run", side_effect=mock_run):
            # First call - should invoke SOPS
            content1 = decryptor.decrypt_file(test_file)
            assert call_count["count"] == 1

            # Second call - should use cache
            content2 = decryptor.decrypt_file(test_file)
            assert call_count["count"] == 1  # No additional call
            assert content1 == content2


def test_sops_decryptor_cache_invalidates_on_mtime(tmp_path: Path, decrypted_yaml_content: str) -> None:
    """Test that cache is invalidated when file mtime changes."""
    call_count = {"count": 0}

    def mock_run(*args: Any, **kwargs: Any) -> MagicMock:
        call_count["count"] += 1
        result = MagicMock()
        result.returncode = 0
        result.stdout = decrypted_yaml_content
        result.stderr = ""
        return result

    test_file = tmp_path / "test.sops.yml"
    test_file.write_text("key: ENC[AES256_GCM,data:xxx]", encoding="utf-8")

    decryptor = SopsDecryptor()

    with patch("shutil.which", return_value="/fake/sops"):
        with patch("subprocess.run", side_effect=mock_run):
            # First call
            decryptor.decrypt_file(test_file)
            assert call_count["count"] == 1

            # Modify file (changes mtime)
            import time

            time.sleep(0.1)  # Ensure mtime changes
            test_file.write_text("key: ENC[AES256_GCM,data:yyy]", encoding="utf-8")

            # Second call - should re-decrypt due to mtime change
            decryptor.decrypt_file(test_file)
            assert call_count["count"] == 2


def test_sops_decryptor_purge_cache_all(tmp_path: Path, decrypted_yaml_content: str) -> None:
    """Test purging all cache entries."""
    decryptor = SopsDecryptor()

    def mock_run(*args: Any, **kwargs: Any) -> MagicMock:
        result = MagicMock()
        result.returncode = 0
        result.stdout = decrypted_yaml_content
        result.stderr = ""
        return result

    test_file = tmp_path / "test.sops.yml"
    test_file.write_text("key: value", encoding="utf-8")

    with patch("shutil.which", return_value="/fake/sops"):
        with patch("subprocess.run", side_effect=mock_run):
            decryptor.decrypt_file(test_file)
            assert decryptor.cache_size == 1

            decryptor.purge_cache()
            assert decryptor.cache_size == 0


def test_sops_decryptor_purge_cache_specific(tmp_path: Path, decrypted_yaml_content: str) -> None:
    """Test purging a specific cache entry."""
    decryptor = SopsDecryptor()

    def mock_run(*args: Any, **kwargs: Any) -> MagicMock:
        result = MagicMock()
        result.returncode = 0
        result.stdout = decrypted_yaml_content
        result.stderr = ""
        return result

    file1 = tmp_path / "test1.sops.yml"
    file1.write_text("key: value1", encoding="utf-8")
    file2 = tmp_path / "test2.sops.yml"
    file2.write_text("key: value2", encoding="utf-8")

    with patch("shutil.which", return_value="/fake/sops"):
        with patch("subprocess.run", side_effect=mock_run):
            decryptor.decrypt_file(file1)
            decryptor.decrypt_file(file2)
            assert decryptor.cache_size == 2

            decryptor.purge_cache(file1)
            assert decryptor.cache_size == 1


# ============================================================================
# Loader integration tests
# ============================================================================


def test_loader_decrypts_sops_file(tmp_path: Path, monkeypatch: Any, decrypted_yaml_content: str) -> None:
    """Test that ConfigLoader automatically decrypts .sops.yml files."""

    def mock_run(*args: Any, **kwargs: Any) -> MagicMock:
        result = MagicMock()
        result.returncode = 0
        result.stdout = decrypted_yaml_content
        result.stderr = ""
        return result

    sops_file = tmp_path / "config.sops.yml"
    sops_file.write_text("encrypted: true", encoding="utf-8")

    with patch("shutil.which", return_value="/fake/sops"):
        with patch("subprocess.run", side_effect=mock_run):
            config = load_from_file(sops_file)
            assert config.api_key == "real_api_key_value"
            assert config.db.password == "super_secret_password"


def test_loader_graceful_degradation_no_sops(tmp_path: Path, caplog: Any) -> None:
    """Test that loader warns and loads raw when SOPS is not available."""
    sops_file = tmp_path / "config.sops.yml"
    sops_file.write_text("api_key: ENC[AES256_GCM,data:xxx]\nhost: localhost\n", encoding="utf-8")

    # No SOPS binary available
    with patch("shutil.which", return_value=None):
        config = load_from_file(sops_file)
        # Should load raw content
        assert "ENC[AES256_GCM" in config.api_key
        assert config.host == "localhost"
        # Should have logged warning
        assert any("SOPS not available" in record.message for record in caplog.records)


def test_loader_graceful_degradation_decrypt_fails(tmp_path: Path, caplog: Any) -> None:
    """Test that loader warns and loads raw when decryption fails."""
    sops_file = tmp_path / "config.sops.yml"
    sops_file.write_text("api_key: ENC[AES256_GCM,data:xxx]\nhost: localhost\n", encoding="utf-8")

    def mock_run(*args: Any, **kwargs: Any) -> MagicMock:
        result = MagicMock()
        result.returncode = 1
        result.stdout = ""
        result.stderr = "Decryption failed"
        return result

    with patch("shutil.which", return_value="/fake/sops"):
        with patch("subprocess.run", side_effect=mock_run):
            config = load_from_file(sops_file)
            # Should load raw content
            assert "ENC[AES256_GCM" in config.api_key
            assert config.host == "localhost"
            # Should have logged warning
            assert any("SOPS decryption failed" in record.message for record in caplog.records)


def test_loader_warns_enc_values_in_non_sops_file(tmp_path: Path, caplog: Any) -> None:
    """Test warning when ENC[...] values found in non-SOPS file."""
    regular_file = tmp_path / "config.yml"  # Not a .sops file
    regular_file.write_text("api_key: ENC[AES256_GCM,data:xxx]\nhost: localhost\n", encoding="utf-8")

    config = load_from_file(regular_file)
    # Should load content as-is
    assert "ENC[AES256_GCM" in config.api_key
    # Should have logged warning
    assert any("ENC[...]" in record.message and "auto-decryption" in record.message for record in caplog.records)


def test_loader_sops_decrypt_false_skips_decryption(tmp_path: Path, decrypted_yaml_content: str) -> None:
    """Test that sops_decrypt=False skips SOPS decryption."""
    call_count = {"count": 0}

    def mock_run(*args: Any, **kwargs: Any) -> MagicMock:
        call_count["count"] += 1
        result = MagicMock()
        result.returncode = 0
        result.stdout = decrypted_yaml_content
        result.stderr = ""
        return result

    sops_file = tmp_path / "config.sops.yml"
    sops_file.write_text("api_key: ENC[AES256_GCM,data:xxx]\n", encoding="utf-8")

    with patch("shutil.which", return_value="/fake/sops"):
        with patch("subprocess.run", side_effect=mock_run):
            config = load_from_file(sops_file, sops_decrypt=False)
            # Should not have called SOPS
            assert call_count["count"] == 0
            # Should have raw encrypted value
            assert "ENC[AES256_GCM" in config.api_key


def test_loader_include_decrypts_sops_include(tmp_path: Path, decrypted_yaml_content: str) -> None:
    """Test that included .sops files are also decrypted."""

    def mock_run(*args: Any, **kwargs: Any) -> MagicMock:
        result = MagicMock()
        result.returncode = 0
        result.stdout = decrypted_yaml_content
        result.stderr = ""
        return result

    # Main config includes a SOPS file
    main_config = tmp_path / "kstlib.conf.yml"
    main_config.write_text("app: myapp\ninclude: secrets.sops.yml\n", encoding="utf-8")

    sops_file = tmp_path / "secrets.sops.yml"
    sops_file.write_text("encrypted: true", encoding="utf-8")

    with patch("shutil.which", return_value="/fake/sops"):
        with patch("subprocess.run", side_effect=mock_run):
            config = load_from_file(main_config)
            assert config.app == "myapp"
            assert config.api_key == "real_api_key_value"


def test_loader_mixed_formats_sops(tmp_path: Path) -> None:
    """Test loading SOPS files in different formats."""

    def make_mock_run(content: str) -> Any:
        def mock_run(*args: Any, **kwargs: Any) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stdout = content
            result.stderr = ""
            return result

        return mock_run

    # Test JSON format
    json_content = '{"api_key": "decrypted_json"}'
    sops_json = tmp_path / "config.sops.json"
    sops_json.write_text('{"encrypted": true}', encoding="utf-8")

    with patch("shutil.which", return_value="/fake/sops"):
        with patch("subprocess.run", side_effect=make_mock_run(json_content)):
            config = load_from_file(sops_json)
            assert config.api_key == "decrypted_json"


def test_configloader_class_sops_decrypt_attribute(tmp_path: Path) -> None:
    """Test that ConfigLoader stores sops_decrypt attribute."""
    loader_default = ConfigLoader(auto_discovery=False)
    assert loader_default.sops_decrypt is True

    loader_disabled = ConfigLoader(sops_decrypt=False, auto_discovery=False)
    assert loader_disabled.sops_decrypt is False


def test_load_config_function_passes_sops_decrypt(tmp_path: Path, monkeypatch: Any) -> None:
    """Test that load_config() passes sops_decrypt to loader."""
    call_count = {"count": 0}

    def mock_run(*args: Any, **kwargs: Any) -> MagicMock:
        call_count["count"] += 1
        result = MagicMock()
        result.returncode = 0
        result.stdout = "key: value\n"
        result.stderr = ""
        return result

    sops_file = tmp_path / "kstlib.conf.yml"
    # Rename to SOPS file
    sops_file = tmp_path / "config.sops.yml"
    sops_file.write_text("key: ENC[AES256_GCM,data:xxx]\n", encoding="utf-8")

    with patch("shutil.which", return_value="/fake/sops"):
        with patch("subprocess.run", side_effect=mock_run):
            # With sops_decrypt=True (default)
            load_config(path=sops_file, sops_decrypt=True)
            assert call_count["count"] == 1

            # With sops_decrypt=False
            load_config(path=sops_file, sops_decrypt=False)
            assert call_count["count"] == 1  # No additional call


# ============================================================================
# Global decryptor singleton tests
# ============================================================================


def test_get_decryptor_returns_singleton() -> None:
    """Test that get_decryptor returns a singleton."""
    d1 = get_decryptor()
    d2 = get_decryptor()
    assert d1 is d2


def test_reset_decryptor_clears_singleton() -> None:
    """Test that reset_decryptor clears the singleton."""
    d1 = get_decryptor()
    reset_decryptor()
    d2 = get_decryptor()
    assert d1 is not d2
