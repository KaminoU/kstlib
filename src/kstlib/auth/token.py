"""Token storage backends for the authentication module."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from kstlib.auth.errors import TokenStorageError
from kstlib.auth.models import Token
from kstlib.logging import TRACE_LEVEL, get_logger

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = get_logger(__name__)

# Deep defense: provider name limits
_MAX_PROVIDER_NAME_LENGTH = 128
_MIN_PROVIDER_NAME_LENGTH = 1


def _validate_provider_name(provider_name: str) -> None:
    """Validate provider name for security.

    Args:
        provider_name: Provider identifier to validate.

    Raises:
        TokenStorageError: If provider name is invalid.
    """
    if not provider_name or len(provider_name) < _MIN_PROVIDER_NAME_LENGTH:
        raise TokenStorageError("Provider name cannot be empty")
    if len(provider_name) > _MAX_PROVIDER_NAME_LENGTH:
        raise TokenStorageError(f"Provider name exceeds maximum length ({_MAX_PROVIDER_NAME_LENGTH})")


class AbstractTokenStorage(ABC):
    """Abstract base class for token storage backends.

    Implementations handle persisting and retrieving tokens, with optional
    encryption (e.g., SOPS) for secure storage.
    """

    @abstractmethod
    def save(self, provider_name: str, token: Token) -> None:
        """Persist a token for a provider.

        Args:
            provider_name: Provider identifier.
            token: Token to save.

        Raises:
            TokenStorageError: If save fails.
        """

    @abstractmethod
    def load(self, provider_name: str) -> Token | None:
        """Load a token for a provider.

        Args:
            provider_name: Provider identifier.

        Returns:
            Token if found, None otherwise.

        Raises:
            TokenStorageError: If load fails (not for missing tokens).
        """

    @abstractmethod
    def delete(self, provider_name: str) -> bool:
        """Delete a token for a provider.

        Args:
            provider_name: Provider identifier.

        Returns:
            True if token existed and was deleted.
        """

    @abstractmethod
    def exists(self, provider_name: str) -> bool:
        """Check if a token exists for a provider.

        Args:
            provider_name: Provider identifier.

        Returns:
            True if token exists.
        """

    @contextmanager
    def sensitive_token(self, provider_name: str) -> Iterator[Token | None]:
        """Context manager for secure token access.

        Loads the token and yields it. On exit, clears the reference.
        Subclasses may implement additional cleanup (e.g., memory scrubbing).

        Args:
            provider_name: Provider identifier.

        Yields:
            Token if available, None otherwise.

        Example:
            >>> with storage.sensitive_token("corporate") as token:  # doctest: +SKIP
            ...     if token:
            ...         print(token.access_token)
            ... # token reference cleared here
        """
        token = self.load(provider_name)
        try:
            yield token
        finally:
            del token


class MemoryTokenStorage(AbstractTokenStorage):
    """In-memory token storage (for development/testing).

    Tokens are stored in a dictionary and lost when the process exits.
    No encryption or persistence.
    """

    def __init__(self) -> None:
        """Initialize empty storage."""
        self._tokens: dict[str, Token] = {}

    def save(self, provider_name: str, token: Token) -> None:
        """Store token in memory."""
        _validate_provider_name(provider_name)
        self._tokens[provider_name] = token
        logger.debug("Token saved in memory for provider '%s'", provider_name)

    def load(self, provider_name: str) -> Token | None:
        """Retrieve token from memory."""
        return self._tokens.get(provider_name)

    def delete(self, provider_name: str) -> bool:
        """Remove token from memory."""
        if provider_name in self._tokens:
            del self._tokens[provider_name]
            logger.debug("Token deleted from memory for provider '%s'", provider_name)
            return True
        return False

    def exists(self, provider_name: str) -> bool:
        """Check if token exists in memory."""
        return provider_name in self._tokens

    def clear_all(self) -> None:
        """Clear all tokens from memory."""
        self._tokens.clear()


class FileTokenStorage(AbstractTokenStorage):
    """Plain JSON file token storage.

    Tokens are stored as unencrypted JSON files with restrictive permissions (600).
    Suitable for development, testing, or environments where SOPS is unavailable.

    Warning:
        Tokens are stored in plaintext. Use SOPS storage for production environments
        where token confidentiality is critical.
    """

    _warned: bool = False  # Class-level flag for one-time warning

    def __init__(
        self,
        directory: Path | str | None = None,
    ) -> None:
        """Initialize file storage.

        Args:
            directory: Directory to store token files.
                Default: ~/.config/kstlib/auth/tokens
        """
        if directory is None:
            directory = Path.home() / ".config" / "kstlib" / "auth" / "tokens"
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _token_path(self, provider_name: str) -> Path:
        """Get the file path for a provider's token."""
        _validate_provider_name(provider_name)
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in provider_name)
        return self.directory / f"{safe_name}.token.json"

    def save(self, provider_name: str, token: Token) -> None:
        """Save token to JSON file with restrictive permissions."""
        import stat

        # One-time warning about unencrypted storage (only on save, not on read/delete)
        if not FileTokenStorage._warned:
            logger.warning(
                "FileTokenStorage: Tokens will be stored UNENCRYPTED at %s. "
                "Consider using 'sops' storage for sensitive environments.",
                self.directory,
            )
            FileTokenStorage._warned = True

        path = self._token_path(provider_name)

        if logger.isEnabledFor(TRACE_LEVEL):
            logger.log(TRACE_LEVEL, "[TOKEN] Saving to file: %s", path)
        data = token.to_dict()

        try:
            # Write to file
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")

            # Set restrictive permissions (owner read/write only: 600)
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)

            logger.debug("Token saved (plaintext) for provider '%s': %s", provider_name, path)
        except OSError as e:
            msg = f"Failed to save token for '{provider_name}': {e}"
            raise TokenStorageError(msg) from e

    def load(self, provider_name: str) -> Token | None:
        """Load token from JSON file."""
        path = self._token_path(provider_name)
        if not path.exists():
            if logger.isEnabledFor(TRACE_LEVEL):
                logger.log(TRACE_LEVEL, "[TOKEN] File not found: %s", path)
            return None

        if logger.isEnabledFor(TRACE_LEVEL):
            logger.log(TRACE_LEVEL, "[TOKEN] Loading from file: %s", path)

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Token.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Failed to parse token file for '%s': %s", provider_name, e)
            return None
        except OSError as e:
            logger.warning("Failed to read token file for '%s': %s", provider_name, e)
            return None

    def delete(self, provider_name: str) -> bool:
        """Delete token file."""
        path = self._token_path(provider_name)
        if path.exists():
            path.unlink()
            logger.debug("Token file deleted for provider '%s'", provider_name)
            return True
        return False

    def exists(self, provider_name: str) -> bool:
        """Check if token file exists."""
        return self._token_path(provider_name).exists()


class SOPSTokenStorage(AbstractTokenStorage):
    """SOPS-encrypted token storage.

    Tokens are encrypted using SOPS before being written to disk.
    Uses the SOPS CLI directly for encryption/decryption operations.
    """

    def __init__(
        self,
        directory: Path | str,
        *,
        sops_binary: str = "sops",
        age_recipients: list[str] | None = None,
    ) -> None:
        """Initialize SOPS storage.

        Args:
            directory: Directory to store encrypted token files.
            sops_binary: Path to sops binary (default: "sops").
            age_recipients: Age public keys for encryption.
                If not provided, relies on .sops.yaml or environment.
        """
        import shutil

        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.sops_binary = shutil.which(sops_binary) or sops_binary
        self.age_recipients = age_recipients

    def _token_path(self, provider_name: str) -> Path:
        """Get the file path for a provider's encrypted token."""
        _validate_provider_name(provider_name)
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in provider_name)
        return self.directory / f"{safe_name}.token.sops.json"

    def _run_sops(
        self,
        args: list[str],
        *,
        input_data: str | None = None,
    ) -> str:
        """Run SOPS command and return output."""
        import subprocess

        cmd = [self.sops_binary, *args]

        if logger.isEnabledFor(TRACE_LEVEL):
            # Log command without sensitive data
            safe_args = [a for a in args if not a.startswith("/")]  # Redact paths
            logger.log(TRACE_LEVEL, "[SOPS] Running: sops %s", " ".join(safe_args[:3]))

        try:
            result = subprocess.run(
                cmd,
                input=input_data,
                capture_output=True,
                text=True,
                check=True,
            )

            if logger.isEnabledFor(TRACE_LEVEL):
                logger.log(TRACE_LEVEL, "[SOPS] Command succeeded")

            return result.stdout
        except subprocess.CalledProcessError as e:
            # Redact potentially sensitive output
            stderr = e.stderr or ""
            if "could not decrypt" in stderr.lower():
                stderr = "Decryption failed (credentials/keys may be missing)"
            msg = f"SOPS command failed: {stderr}"
            raise TokenStorageError(msg) from e
        except FileNotFoundError as e:
            msg = f"SOPS binary not found at '{self.sops_binary}'"
            raise TokenStorageError(msg) from e

    def save(self, provider_name: str, token: Token) -> None:
        """Save token encrypted with SOPS."""
        import tempfile

        path = self._token_path(provider_name)

        if logger.isEnabledFor(TRACE_LEVEL):
            logger.log(TRACE_LEVEL, "[TOKEN] Encrypting and saving to: %s", path)

        data = token.to_dict()
        json_data = json.dumps(data, indent=2)

        try:
            # Write plaintext to temp file, then encrypt to target
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".json",
                delete=False,
                encoding="utf-8",
            ) as tmp:
                tmp.write(json_data)
                tmp_path = Path(tmp.name)

            try:
                from kstlib.secure.permissions import FilePermissions

                # Remove existing file (READONLY can't be overwritten)
                if path.exists():
                    path.chmod(FilePermissions.OWNER_RW)  # Unlock for deletion
                    path.unlink()

                # Build SOPS encrypt command
                args = ["--encrypt", "--output", str(path)]

                # Add age recipients if specified
                if self.age_recipients:
                    args.extend(["--age", ",".join(self.age_recipients)])

                args.append(str(tmp_path))
                self._run_sops(args)

                # Read-only: token files are immutable once written
                path.chmod(FilePermissions.READONLY)
                logger.debug("Token saved (SOPS encrypted) for provider '%s': %s", provider_name, path)
            finally:
                # Clean up temp file
                tmp_path.unlink(missing_ok=True)

        except Exception as e:
            if isinstance(e, TokenStorageError):
                raise
            msg = f"Failed to save encrypted token for '{provider_name}': {e}"
            raise TokenStorageError(msg) from e

    def load(self, provider_name: str) -> Token | None:
        """Load and decrypt token from SOPS file."""
        path = self._token_path(provider_name)
        if not path.exists():
            if logger.isEnabledFor(TRACE_LEVEL):
                logger.log(TRACE_LEVEL, "[TOKEN] Encrypted file not found: %s", path)
            return None

        if logger.isEnabledFor(TRACE_LEVEL):
            logger.log(TRACE_LEVEL, "[TOKEN] Decrypting from: %s", path)

        try:
            decrypted = self._run_sops(["--decrypt", str(path)])
            data = json.loads(decrypted)
            return Token.from_dict(data)
        except TokenStorageError:
            logger.warning("Failed to decrypt token for '%s'", provider_name)
            return None
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Failed to parse decrypted token for '%s': %s", provider_name, e)
            return None

    def delete(self, provider_name: str) -> bool:
        """Delete encrypted token file."""
        from kstlib.secure.permissions import FilePermissions

        path = self._token_path(provider_name)
        if path.exists():
            path.chmod(FilePermissions.OWNER_RW)  # Unlock READONLY file
            path.unlink()
            logger.debug("Encrypted token file deleted for provider '%s'", provider_name)
            return True
        return False

    def exists(self, provider_name: str) -> bool:
        """Check if encrypted token file exists."""
        return self._token_path(provider_name).exists()

    @contextmanager
    def sensitive_token(self, provider_name: str) -> Iterator[Token | None]:
        """Context manager for secure token access with cleanup."""
        token = self.load(provider_name)
        try:
            yield token
        finally:
            # Clear reference (Python GC will handle the rest)
            del token


def get_token_storage(
    storage_type: str = "memory",
    *,
    directory: Path | str | None = None,
    **kwargs: Any,
) -> AbstractTokenStorage:
    """Factory function to create a token storage backend.

    Args:
        storage_type: Type of storage ("memory", "file", or "sops").
        directory: Directory for file/SOPS storage (default: ~/.config/kstlib/auth/tokens).
        **kwargs: Additional arguments for SOPS storage (e.g., age_recipients).

    Returns:
        Token storage instance.

    Raises:
        ValueError: If storage_type is unknown.

    Example:
        >>> storage = get_token_storage("memory")
        >>> storage = get_token_storage("file", directory="/tmp/tokens")  # doctest: +SKIP
        >>> storage = get_token_storage("sops", directory="/tmp/tokens")  # doctest: +SKIP
    """
    if storage_type == "memory":
        return MemoryTokenStorage()

    if storage_type == "file":
        return FileTokenStorage(directory)

    if storage_type == "sops":
        if directory is None:
            directory = Path.home() / ".config" / "kstlib" / "auth" / "tokens"
        return SOPSTokenStorage(directory, **kwargs)

    msg = f"Unknown storage type: {storage_type}. Use 'memory', 'file', or 'sops'."
    raise ValueError(msg)


__all__ = [
    "AbstractTokenStorage",
    "FileTokenStorage",
    "MemoryTokenStorage",
    "SOPSTokenStorage",
    "get_token_storage",
]
