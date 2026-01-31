"""Unit tests for token storage backends."""

from __future__ import annotations

import subprocess

import pytest

from kstlib.auth.token import (
    FileTokenStorage,
    MemoryTokenStorage,
    SOPSTokenStorage,
    get_token_storage,
)

from .conftest import requires_age, requires_sops


class TestMemoryTokenStorage:
    """Tests for MemoryTokenStorage."""

    def test_save_and_load(self, memory_storage, sample_token):
        """Test saving and loading a token."""
        memory_storage.save("provider1", sample_token)
        loaded = memory_storage.load("provider1")

        assert loaded is not None
        assert loaded.access_token == sample_token.access_token
        assert loaded.refresh_token == sample_token.refresh_token

    def test_load_nonexistent(self, memory_storage):
        """Test loading a non-existent token returns None."""
        assert memory_storage.load("nonexistent") is None

    def test_exists(self, memory_storage, sample_token):
        """Test exists() method."""
        assert memory_storage.exists("provider1") is False

        memory_storage.save("provider1", sample_token)
        assert memory_storage.exists("provider1") is True

    def test_delete(self, memory_storage, sample_token):
        """Test deleting a token."""
        memory_storage.save("provider1", sample_token)
        assert memory_storage.exists("provider1") is True

        result = memory_storage.delete("provider1")
        assert result is True
        assert memory_storage.exists("provider1") is False

    def test_delete_nonexistent(self, memory_storage):
        """Test deleting a non-existent token returns False."""
        assert memory_storage.delete("nonexistent") is False

    def test_clear_all(self, memory_storage, sample_token):
        """Test clearing all tokens."""
        memory_storage.save("provider1", sample_token)
        memory_storage.save("provider2", sample_token)

        memory_storage.clear_all()

        assert memory_storage.exists("provider1") is False
        assert memory_storage.exists("provider2") is False

    def test_multiple_providers(self, memory_storage, sample_token, expired_token):
        """Test storing tokens for multiple providers."""
        memory_storage.save("provider1", sample_token)
        memory_storage.save("provider2", expired_token)

        loaded1 = memory_storage.load("provider1")
        loaded2 = memory_storage.load("provider2")

        assert loaded1.access_token == sample_token.access_token
        assert loaded2.access_token == expired_token.access_token

    def test_sensitive_token_context(self, memory_storage, sample_token):
        """Test sensitive_token context manager."""
        memory_storage.save("provider1", sample_token)

        with memory_storage.sensitive_token("provider1") as token:
            assert token is not None
            assert token.access_token == sample_token.access_token

    def test_sensitive_token_nonexistent(self, memory_storage):
        """Test sensitive_token with non-existent token."""
        with memory_storage.sensitive_token("nonexistent") as token:
            assert token is None


class TestFileTokenStorage:
    """Tests for FileTokenStorage (plain JSON files)."""

    def test_save_and_load(self, file_storage, sample_token):
        """Test saving and loading a token."""
        file_storage.save("provider1", sample_token)
        loaded = file_storage.load("provider1")

        assert loaded is not None
        assert loaded.access_token == sample_token.access_token
        assert loaded.refresh_token == sample_token.refresh_token

    def test_load_nonexistent(self, file_storage):
        """Test loading a non-existent token returns None."""
        assert file_storage.load("nonexistent") is None

    def test_exists(self, file_storage, sample_token):
        """Test exists() method."""
        assert file_storage.exists("provider1") is False

        file_storage.save("provider1", sample_token)
        assert file_storage.exists("provider1") is True

    def test_delete(self, file_storage, sample_token):
        """Test deleting a token."""
        file_storage.save("provider1", sample_token)
        assert file_storage.exists("provider1") is True

        result = file_storage.delete("provider1")
        assert result is True
        assert file_storage.exists("provider1") is False

    def test_delete_nonexistent(self, file_storage):
        """Test deleting a non-existent token returns False."""
        assert file_storage.delete("nonexistent") is False

    def test_multiple_providers(self, file_storage, sample_token, expired_token):
        """Test storing tokens for multiple providers."""
        file_storage.save("provider1", sample_token)
        file_storage.save("provider2", expired_token)

        loaded1 = file_storage.load("provider1")
        loaded2 = file_storage.load("provider2")

        assert loaded1.access_token == sample_token.access_token
        assert loaded2.access_token == expired_token.access_token

    def test_sensitive_token_context(self, file_storage, sample_token):
        """Test sensitive_token context manager."""
        file_storage.save("provider1", sample_token)

        with file_storage.sensitive_token("provider1") as token:
            assert token is not None
            assert token.access_token == sample_token.access_token

    def test_sensitive_token_nonexistent(self, file_storage):
        """Test sensitive_token with non-existent token."""
        with file_storage.sensitive_token("nonexistent") as token:
            assert token is None

    def test_file_is_plaintext_json(self, file_storage, sample_token):
        """Test that the saved file is plain JSON (not encrypted)."""
        import json

        file_storage.save("provider1", sample_token)
        token_path = file_storage._token_path("provider1")

        assert token_path.exists()
        assert token_path.suffix == ".json"

        # Should be valid JSON
        content = token_path.read_text()
        data = json.loads(content)
        assert data["access_token"] == sample_token.access_token

    def test_file_permissions(self, file_storage, sample_token):
        """Test that saved token file has restrictive permissions (600)."""
        import os
        import stat

        file_storage.save("provider1", sample_token)
        token_path = file_storage._token_path("provider1")

        mode = token_path.stat().st_mode & 0o777

        if os.name == "nt":
            # Windows doesn't support Unix-style permissions
            # Just verify the file exists and is readable
            assert token_path.exists()
        else:
            # POSIX: should be 600 (owner read/write)
            expected = stat.S_IRUSR | stat.S_IWUSR
            assert mode == expected, f"Expected {oct(expected)}, got {oct(mode)}"

    def test_persistence_across_instances(self, temp_storage_dir, sample_token):
        """Test tokens persist across storage instances."""
        storage1 = FileTokenStorage(directory=temp_storage_dir)
        storage1.save("provider1", sample_token)

        storage2 = FileTokenStorage(directory=temp_storage_dir)
        loaded = storage2.load("provider1")

        assert loaded is not None
        assert loaded.access_token == sample_token.access_token

    def test_safe_filename(self, file_storage, sample_token):
        """Test that provider names with special characters are sanitized."""
        file_storage.save("provider/with:special<chars>", sample_token)
        token_path = file_storage._token_path("provider/with:special<chars>")

        # Should not contain any special characters in the filename
        assert "/" not in token_path.name
        assert ":" not in token_path.name
        assert "<" not in token_path.name
        assert ">" not in token_path.name

    def test_overwrite_existing(self, file_storage, sample_token, expired_token):
        """Test that saving overwrites existing token."""
        file_storage.save("provider1", sample_token)
        file_storage.save("provider1", expired_token)

        loaded = file_storage.load("provider1")
        assert loaded.access_token == expired_token.access_token


@requires_sops
@requires_age
class TestSOPSTokenStorage:
    """Tests for SOPSTokenStorage with Age encryption."""

    @pytest.fixture
    def age_keypair(self, tmp_path):
        """Generate a temporary Age keypair for testing."""
        key_file = tmp_path / "age.key"

        # Generate Age key
        result = subprocess.run(
            ["age-keygen", "-o", str(key_file)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Failed to generate Age key: {result.stderr}"

        # Extract public key from output or file
        key_content = key_file.read_text()
        public_key = None
        for line in key_content.splitlines():
            if line.startswith("# public key:"):
                public_key = line.split(": ")[1].strip()
                break

        assert public_key is not None, "Could not extract public key"

        return {
            "key_file": key_file,
            "public_key": public_key,
        }

    @pytest.fixture
    def sops_storage(self, temp_storage_dir, age_keypair, monkeypatch, tmp_path):
        """Create a SOPSTokenStorage with Age encryption."""
        # Set SOPS_AGE_KEY_FILE for decryption
        monkeypatch.setenv("SOPS_AGE_KEY_FILE", str(age_keypair["key_file"]))

        # Create a .sops.yaml config for the test
        sops_config = tmp_path / ".sops.yaml"
        sops_config.write_text(f"creation_rules:\n  - path_regex: .*\\.json$\n    age: {age_keypair['public_key']}\n")
        monkeypatch.setenv("SOPS_CONFIG", str(sops_config))

        return SOPSTokenStorage(
            directory=temp_storage_dir,
            age_recipients=[age_keypair["public_key"]],
        )

    def test_save_and_load(self, sops_storage, sample_token):
        """Test saving and loading a SOPS-encrypted token."""
        sops_storage.save("provider1", sample_token)
        loaded = sops_storage.load("provider1")

        assert loaded is not None
        assert loaded.access_token == sample_token.access_token
        assert loaded.refresh_token == sample_token.refresh_token

    def test_file_is_encrypted(self, sops_storage, sample_token):
        """Test that the saved file is actually encrypted."""
        sops_storage.save("provider1", sample_token)
        token_path = sops_storage._token_path("provider1")

        # File should exist
        assert token_path.exists()

        # Content should be SOPS-encrypted JSON (contains "sops" metadata)
        content = token_path.read_text()
        assert '"sops":' in content or "sops" in content
        # Raw token should NOT be visible
        assert sample_token.access_token not in content

    def test_file_permissions_readonly(self, sops_storage, sample_token):
        """Test that saved token file has read-only permissions."""
        import os

        from kstlib.secure.permissions import FilePermissions

        sops_storage.save("provider1", sample_token)
        token_path = sops_storage._token_path("provider1")

        # Get file permissions (mask out file type bits)
        mode = token_path.stat().st_mode & 0o777

        if os.name == "nt":
            # Windows: chmod(READONLY) -> READONLY_ALL (read-only attribute)
            assert mode == FilePermissions.READONLY_ALL, (
                f"Expected {oct(FilePermissions.READONLY_ALL)}, got {oct(mode)}"
            )
        else:
            # POSIX: exact READONLY (owner read-only)
            assert mode == FilePermissions.READONLY, f"Expected {oct(FilePermissions.READONLY)}, got {oct(mode)}"

        # Either way, file should not be writable
        assert not os.access(token_path, os.W_OK)

    def test_load_nonexistent(self, sops_storage):
        """Test loading a non-existent token returns None."""
        assert sops_storage.load("nonexistent") is None

    def test_exists(self, sops_storage, sample_token):
        """Test exists() method."""
        assert sops_storage.exists("provider1") is False

        sops_storage.save("provider1", sample_token)
        assert sops_storage.exists("provider1") is True

    def test_delete(self, sops_storage, sample_token):
        """Test deleting an encrypted token."""
        sops_storage.save("provider1", sample_token)
        token_path = sops_storage._token_path("provider1")
        assert token_path.exists()

        result = sops_storage.delete("provider1")
        assert result is True
        assert not token_path.exists()

    def test_delete_nonexistent(self, sops_storage):
        """Test deleting a non-existent token returns False."""
        assert sops_storage.delete("nonexistent") is False

    def test_sensitive_token_context(self, sops_storage, sample_token):
        """Test sensitive_token context manager."""
        sops_storage.save("provider1", sample_token)

        with sops_storage.sensitive_token("provider1") as token:
            assert token is not None
            assert token.access_token == sample_token.access_token

    def test_persistence_across_instances(self, temp_storage_dir, age_keypair, sample_token, monkeypatch, tmp_path):
        """Test tokens persist across storage instances."""
        monkeypatch.setenv("SOPS_AGE_KEY_FILE", str(age_keypair["key_file"]))

        # Create a .sops.yaml config for the test
        sops_config = tmp_path / ".sops.yaml"
        sops_config.write_text(f"creation_rules:\n  - path_regex: .*\\.json$\n    age: {age_keypair['public_key']}\n")
        monkeypatch.setenv("SOPS_CONFIG", str(sops_config))

        storage1 = SOPSTokenStorage(
            directory=temp_storage_dir,
            age_recipients=[age_keypair["public_key"]],
        )
        storage1.save("provider1", sample_token)

        storage2 = SOPSTokenStorage(
            directory=temp_storage_dir,
            age_recipients=[age_keypair["public_key"]],
        )
        loaded = storage2.load("provider1")

        assert loaded is not None
        assert loaded.access_token == sample_token.access_token


class TestFileTokenStorageErrors:
    """Tests for FileTokenStorage error handling."""

    def test_default_directory(self, monkeypatch, tmp_path):
        """Test FileTokenStorage uses default directory when none provided."""
        # Reset the warning flag for this test
        FileTokenStorage._warned = False
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        storage = FileTokenStorage()  # No directory argument

        expected_dir = tmp_path / ".config" / "kstlib" / "auth" / "tokens"
        assert storage.directory == expected_dir
        assert expected_dir.exists()

    def test_save_oserror(self, file_storage, sample_token, monkeypatch):
        """Test save raises TokenStorageError on OSError."""
        from kstlib.auth.errors import TokenStorageError

        def mock_write_text(*args, **kwargs):
            raise OSError("Disk full")

        # Get the token path and mock write_text
        token_path = file_storage._token_path("provider1")
        monkeypatch.setattr(type(token_path), "write_text", mock_write_text)

        with pytest.raises(TokenStorageError, match="Failed to save token"):
            file_storage.save("provider1", sample_token)

    def test_load_json_decode_error(self, file_storage):
        """Test load returns None on JSONDecodeError."""
        # Create a file with invalid JSON
        token_path = file_storage._token_path("corrupted")
        token_path.write_text("not valid json {{{", encoding="utf-8")

        result = file_storage.load("corrupted")
        assert result is None

    def test_load_key_error(self, file_storage):
        """Test load returns None on KeyError (missing required fields)."""
        import json

        # Create a file with valid JSON but missing required fields
        token_path = file_storage._token_path("incomplete")
        token_path.write_text(json.dumps({"some": "data"}), encoding="utf-8")

        result = file_storage.load("incomplete")
        assert result is None

    def test_load_oserror(self, file_storage, monkeypatch):
        """Test load returns None on OSError."""
        # Create a valid token file first
        token_path = file_storage._token_path("provider1")
        token_path.write_text('{"access_token": "test"}', encoding="utf-8")

        def mock_read_text(*args, **kwargs):
            raise OSError("Permission denied")

        monkeypatch.setattr(type(token_path), "read_text", mock_read_text)

        result = file_storage.load("provider1")
        assert result is None


class TestSOPSTokenStorageErrors:
    """Tests for SOPSTokenStorage error handling (mocked, no real SOPS needed)."""

    def test_sops_called_process_error(self, tmp_path, monkeypatch):
        """Test _run_sops raises TokenStorageError on CalledProcessError."""
        import subprocess

        from kstlib.auth.errors import TokenStorageError

        storage = SOPSTokenStorage(directory=tmp_path)

        def mock_run(*args, **kwargs):
            raise subprocess.CalledProcessError(1, "sops", stderr="could not decrypt data")

        monkeypatch.setattr(subprocess, "run", mock_run)

        with pytest.raises(TokenStorageError, match="Decryption failed"):
            storage._run_sops(["--decrypt", "file.json"])

    def test_sops_called_process_error_generic(self, tmp_path, monkeypatch):
        """Test _run_sops raises TokenStorageError with generic error."""
        import subprocess

        from kstlib.auth.errors import TokenStorageError

        storage = SOPSTokenStorage(directory=tmp_path)

        def mock_run(*args, **kwargs):
            raise subprocess.CalledProcessError(1, "sops", stderr="some other error")

        monkeypatch.setattr(subprocess, "run", mock_run)

        with pytest.raises(TokenStorageError, match="some other error"):
            storage._run_sops(["--encrypt", "file.json"])

    def test_sops_file_not_found_error(self, tmp_path, monkeypatch):
        """Test _run_sops raises TokenStorageError when SOPS binary not found."""
        import subprocess

        from kstlib.auth.errors import TokenStorageError

        storage = SOPSTokenStorage(directory=tmp_path, sops_binary="/nonexistent/sops")

        def mock_run(*args, **kwargs):
            raise FileNotFoundError("sops not found")

        monkeypatch.setattr(subprocess, "run", mock_run)

        with pytest.raises(TokenStorageError, match="SOPS binary not found"):
            storage._run_sops(["--version"])

    def test_save_generic_exception(self, tmp_path, monkeypatch, sample_token):
        """Test save raises TokenStorageError on unexpected exception."""
        from kstlib.auth.errors import TokenStorageError

        storage = SOPSTokenStorage(directory=tmp_path)

        def mock_run_sops(*args, **kwargs):
            raise RuntimeError("Unexpected error")

        monkeypatch.setattr(storage, "_run_sops", mock_run_sops)

        with pytest.raises(TokenStorageError, match="Failed to save encrypted token"):
            storage.save("provider1", sample_token)

    def test_load_token_storage_error(self, tmp_path, monkeypatch):
        """Test load returns None on TokenStorageError."""
        storage = SOPSTokenStorage(directory=tmp_path)

        # Create a fake encrypted file
        token_path = storage._token_path("provider1")
        token_path.write_text('{"sops": "fake"}', encoding="utf-8")

        def mock_run_sops(*args, **kwargs):
            from kstlib.auth.errors import TokenStorageError

            raise TokenStorageError("Decryption failed")

        monkeypatch.setattr(storage, "_run_sops", mock_run_sops)

        result = storage.load("provider1")
        assert result is None

    def test_load_json_decode_error(self, tmp_path, monkeypatch):
        """Test load returns None when decrypted content is invalid JSON."""
        storage = SOPSTokenStorage(directory=tmp_path)

        # Create a fake encrypted file
        token_path = storage._token_path("provider1")
        token_path.write_text('{"sops": "fake"}', encoding="utf-8")

        def mock_run_sops(*args, **kwargs):
            return "not valid json {{{"

        monkeypatch.setattr(storage, "_run_sops", mock_run_sops)

        result = storage.load("provider1")
        assert result is None

    def test_load_key_error(self, tmp_path, monkeypatch):
        """Test load returns None when decrypted content missing required fields."""
        import json

        storage = SOPSTokenStorage(directory=tmp_path)

        # Create a fake encrypted file
        token_path = storage._token_path("provider1")
        token_path.write_text('{"sops": "fake"}', encoding="utf-8")

        def mock_run_sops(*args, **kwargs):
            return json.dumps({"incomplete": "data"})

        monkeypatch.setattr(storage, "_run_sops", mock_run_sops)

        result = storage.load("provider1")
        assert result is None

    def test_save_overwrites_existing_file(self, tmp_path, monkeypatch, sample_token):
        """Test save unlocks and deletes existing file before writing."""
        storage = SOPSTokenStorage(directory=tmp_path)

        # Create an existing "encrypted" file (simulating a previous save)
        token_path = storage._token_path("provider1")
        token_path.write_text('{"sops": "old_data"}', encoding="utf-8")
        # Make it read-only like a real SOPS file would be
        token_path.chmod(0o444)

        assert token_path.exists()

        # Mock _run_sops to simulate successful encryption
        def mock_run_sops(args, **kwargs):
            # Simulate SOPS writing to the output file
            if "--encrypt" in args:
                output_idx = args.index("--output") + 1
                output_path = args[output_idx]
                from pathlib import Path

                Path(output_path).write_text('{"sops": "new_encrypted_data"}')
                return ""
            return ""

        monkeypatch.setattr(storage, "_run_sops", mock_run_sops)

        # This should unlock, delete, and re-create the file
        storage.save("provider1", sample_token)

        # File should exist with new content
        assert token_path.exists()

    def test_save_reraises_token_storage_error(self, tmp_path, monkeypatch, sample_token):
        """Test save re-raises TokenStorageError without wrapping."""
        from kstlib.auth.errors import TokenStorageError

        storage = SOPSTokenStorage(directory=tmp_path)

        def mock_run_sops(*args, **kwargs):
            raise TokenStorageError("Original SOPS error")

        monkeypatch.setattr(storage, "_run_sops", mock_run_sops)

        with pytest.raises(TokenStorageError, match="Original SOPS error"):
            storage.save("provider1", sample_token)


class TestGetTokenStorage:
    """Tests for get_token_storage factory function."""

    def test_get_memory_storage(self):
        """Test creating memory storage."""
        storage = get_token_storage("memory")
        assert isinstance(storage, MemoryTokenStorage)

    def test_get_file_storage(self, tmp_path):
        """Test creating file storage."""
        storage = get_token_storage("file", directory=tmp_path / "tokens")
        assert isinstance(storage, FileTokenStorage)

    def test_get_sops_storage(self, tmp_path):
        """Test creating SOPS storage."""
        storage = get_token_storage("sops", directory=tmp_path / "tokens")
        assert isinstance(storage, SOPSTokenStorage)

    def test_get_sops_storage_default_directory(self, monkeypatch, tmp_path):
        """Test creating SOPS storage with default directory."""
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        storage = get_token_storage("sops")  # No directory argument

        expected_dir = tmp_path / ".config" / "kstlib" / "auth" / "tokens"
        assert storage.directory == expected_dir

    def test_invalid_storage_type(self):
        """Test invalid storage type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown storage type"):
            get_token_storage("invalid")
