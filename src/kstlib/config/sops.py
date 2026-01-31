"""SOPS decryption support for configuration files.

This module provides transparent SOPS decryption for configuration files
with .sops.yml, .sops.yaml, .sops.json, or .sops.toml extensions.

Features:
- Automatic detection of SOPS files by extension
- LRU cache with mtime-based invalidation
- Graceful degradation when SOPS is not available
- Warning detection for unencrypted ENC[...] values

Example:
    >>> from kstlib.config.sops import is_sops_file, get_decryptor
    >>> from pathlib import Path
    >>> is_sops_file(Path("secrets.sops.yml"))
    True
    >>> is_sops_file(Path("config.yml"))
    False
"""

from __future__ import annotations

import logging
import pathlib
import shutil
import subprocess
from collections import OrderedDict
from typing import Any

from kstlib.config.exceptions import ConfigSopsError, ConfigSopsNotAvailableError
from kstlib.limits import (
    DEFAULT_MAX_SOPS_CACHE_ENTRIES,
    HARD_MAX_SOPS_CACHE_ENTRIES,
)

logger = logging.getLogger(__name__)

SOPS_FILE_PATTERNS: tuple[str, ...] = (
    ".sops.yml",
    ".sops.yaml",
    ".sops.json",
    ".sops.toml",
)

ENC_MARKER = "ENC[AES256_GCM,"


def is_sops_file(path: pathlib.Path) -> bool:
    """Check if file should be decrypted via SOPS based on extension.

    Args:
        path: Path to the configuration file.

    Returns:
        True if the file has a SOPS extension (.sops.yml, .sops.yaml, etc.).

    Examples:
        >>> from pathlib import Path
        >>> is_sops_file(Path("secrets.sops.yml"))
        True
        >>> is_sops_file(Path("config.yml"))
        False
        >>> is_sops_file(Path("data.sops.json"))
        True
    """
    name = path.name.lower()
    return any(name.endswith(ext) for ext in SOPS_FILE_PATTERNS)


def get_real_extension(path: pathlib.Path) -> str:
    """Extract actual format extension, ignoring .sops prefix.

    For SOPS files like 'secrets.sops.yml', returns '.yml'.
    For non-SOPS files, returns the normal suffix.

    Args:
        path: Path to the configuration file.

    Returns:
        The real format extension (e.g., '.yml', '.json', '.toml').

    Examples:
        >>> from pathlib import Path
        >>> get_real_extension(Path("secrets.sops.yml"))
        '.yml'
        >>> get_real_extension(Path("config.sops.json"))
        '.json'
        >>> get_real_extension(Path("normal.yml"))
        '.yml'
    """
    name = path.name.lower()
    for marker in (".sops", ".enc"):
        if marker in name:
            idx = name.rfind(marker)
            return name[idx + len(marker) :]
    return path.suffix.lower()


def has_encrypted_values(data: Any, path: str = "") -> list[str]:
    """Recursively find keys containing ENC[AES256_GCM,...] values.

    This function detects SOPS-encrypted values that were not decrypted,
    typically because the file was loaded without SOPS decryption.

    Args:
        data: The parsed configuration data to inspect.
        path: Current key path (for recursion, start with empty string).

    Returns:
        List of dotted key paths containing encrypted values.

    Examples:
        >>> has_encrypted_values({"key": "ENC[AES256_GCM,data...]"})
        ['key']
        >>> has_encrypted_values({"db": {"password": "ENC[AES256_GCM,...]"}})
        ['db.password']
        >>> has_encrypted_values({"normal": "value"})
        []
    """
    found: list[str] = []
    if isinstance(data, str) and ENC_MARKER in data:
        found.append(path or "<root>")
    elif isinstance(data, dict):
        for k, v in data.items():
            found.extend(has_encrypted_values(v, f"{path}.{k}" if path else k))
    elif isinstance(data, list):
        for i, item in enumerate(data):
            found.extend(has_encrypted_values(item, f"{path}[{i}]"))
    return found


class SopsDecryptor:
    """Lightweight SOPS decryptor with LRU cache.

    This class provides SOPS file decryption with:
    - Configurable binary path
    - LRU cache with mtime-based invalidation
    - Clear error messages for troubleshooting

    Attributes:
        binary: Name or path of the SOPS binary.
        max_cache: Maximum cache entries (clamped to hard limit).

    Examples:
        >>> decryptor = SopsDecryptor()  # doctest: +SKIP
        >>> content = decryptor.decrypt_file(Path("secrets.sops.yml"))  # doctest: +SKIP
    """

    def __init__(
        self,
        binary: str = "sops",
        max_cache_entries: int = DEFAULT_MAX_SOPS_CACHE_ENTRIES,
    ) -> None:
        """Initialize the SOPS decryptor.

        Args:
            binary: Name or path of the SOPS binary.
            max_cache_entries: Maximum number of cached decrypted files.
        """
        self._binary = binary
        self._max_cache = min(max_cache_entries, HARD_MAX_SOPS_CACHE_ENTRIES)
        self._cache: OrderedDict[pathlib.Path, tuple[float, str]] = OrderedDict()

    @property
    def binary(self) -> str:
        """Return the configured SOPS binary name."""
        return self._binary

    @property
    def max_cache(self) -> int:
        """Return the maximum cache size."""
        return self._max_cache

    def decrypt_file(self, path: pathlib.Path) -> str:
        """Decrypt a SOPS-encrypted file and return content as string.

        Args:
            path: Path to the SOPS-encrypted file.

        Returns:
            Decrypted file content as a string.

        Raises:
            ConfigSopsNotAvailableError: If SOPS binary is not found.
            ConfigSopsError: If decryption fails.
        """
        resolved = path.resolve()
        mtime = resolved.stat().st_mtime

        # Cache hit?
        cached = self._cache.get(resolved)
        if cached and cached[0] == mtime:
            self._cache.move_to_end(resolved)
            logger.debug("SOPS cache hit for: %s", path.name)
            return cached[1]

        # Find binary
        binary_path = shutil.which(self._binary)
        if binary_path is None:
            raise ConfigSopsNotAvailableError(
                f"SOPS binary '{self._binary}' not found in PATH. Install from https://github.com/getsops/sops"
            )

        # Decrypt - binary_path is validated via shutil.which()
        # resolved is a Path object from user config (trusted source)
        result = subprocess.run(
            [binary_path, "--decrypt", str(resolved)],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

        if result.returncode != 0:
            raise ConfigSopsError(f"Failed to decrypt '{path.name}': {result.stderr.strip()}")

        content = result.stdout

        # Update cache with LRU eviction
        self._cache[resolved] = (mtime, content)
        self._cache.move_to_end(resolved)
        while len(self._cache) > self._max_cache:
            self._cache.popitem(last=False)

        logger.debug("SOPS decrypted and cached: %s", path.name)
        return content

    def purge_cache(self, path: pathlib.Path | None = None) -> None:
        """Clear cache entries.

        Args:
            path: If provided, only clear this specific path.
                  If None, clear all cached entries.
        """
        if path is None:
            self._cache.clear()
            logger.debug("SOPS cache cleared")
        else:
            removed = self._cache.pop(path.resolve(), None)
            if removed:
                logger.debug("SOPS cache entry removed: %s", path.name)

    @property
    def cache_size(self) -> int:
        """Return the current number of cached entries."""
        return len(self._cache)


# Global singleton
_decryptor: SopsDecryptor | None = None


def get_decryptor(binary: str = "sops") -> SopsDecryptor:
    """Get or create global SOPS decryptor singleton.

    Args:
        binary: SOPS binary name (only used on first call).

    Returns:
        The global SopsDecryptor instance.

    Examples:
        >>> decryptor = get_decryptor()  # doctest: +SKIP
        >>> content = decryptor.decrypt_file(path)  # doctest: +SKIP
    """
    global _decryptor
    if _decryptor is None:
        _decryptor = SopsDecryptor(binary=binary)
    return _decryptor


def reset_decryptor() -> None:
    """Reset the global decryptor singleton (for testing)."""
    global _decryptor
    _decryptor = None


__all__ = [
    "ENC_MARKER",
    "SOPS_FILE_PATTERNS",
    "SopsDecryptor",
    "get_decryptor",
    "get_real_extension",
    "has_encrypted_values",
    "is_sops_file",
    "reset_decryptor",
]
