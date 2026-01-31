"""Global SSL configuration for kstlib.

This module provides centralized SSL/TLS configuration with deep defense
validation for CA bundle paths. All HTTP clients (rapi, auth, alerts)
can use this module for consistent SSL configuration.

Configuration cascade (highest to lowest priority):
    1. kwargs passed directly to functions
    2. Module-specific config (e.g., auth.providers.corporate.ssl_verify)
    3. Global ssl config from kstlib.conf.yml
    4. Secure defaults (verify=True)

Example:
    Global config in kstlib.conf.yml::

        ssl:
          verify: true
          ca_bundle: /path/to/ca-bundle.crt  # null by default

    Usage in code::

        from kstlib.ssl import get_ssl_config, build_ssl_context

        # Get global config
        ssl_cfg = get_ssl_config()
        print(ssl_cfg.verify)  # True

        # Build context for httpx (respects cascade)
        verify = build_ssl_context(ssl_verify=False)  # kwargs override
        async with httpx.AsyncClient(verify=verify) as client:
            ...
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kstlib.config import get_config
from kstlib.logging import TRACE_LEVEL, get_logger

__all__ = [
    "SSLConfig",
    "build_ssl_context",
    "get_ssl_config",
    "validate_ca_bundle_path",
    "validate_ssl_verify",
]

logger = get_logger(__name__)

# Minimum size for a valid PEM certificate (header + minimal content)
MIN_PEM_SIZE = 50


@dataclass(frozen=True, slots=True)
class SSLConfig:
    """SSL/TLS configuration container.

    Immutable dataclass holding SSL settings. Use the ``httpx_verify`` property
    to get the appropriate value for httpx Client/AsyncClient.

    Attributes:
        verify: Whether to verify SSL certificates.
        ca_bundle: Path to custom CA bundle file (None = system default).

    Example:
        >>> config = SSLConfig(verify=True, ca_bundle=None)
        >>> config.httpx_verify
        True
        >>> config = SSLConfig(verify=True, ca_bundle="/path/to/ca.pem")
        >>> config.httpx_verify
        '/path/to/ca.pem'
    """

    verify: bool
    ca_bundle: str | None

    @property
    def httpx_verify(self) -> bool | str:
        """Return the appropriate verify value for httpx.

        If a CA bundle is configured, returns the path string.
        Otherwise, returns the boolean verify setting.

        Returns:
            CA bundle path if set, otherwise verify boolean.
        """
        if self.ca_bundle:
            return self.ca_bundle
        return self.verify


def get_ssl_config() -> SSLConfig:
    """Load SSL configuration from kstlib.conf.yml.

    Returns the global SSL settings from configuration file.
    Falls back to secure defaults if not configured.

    Returns:
        SSLConfig with verify and ca_bundle settings.

    Example:
        >>> config = get_ssl_config()  # doctest: +SKIP
        >>> config.verify  # doctest: +SKIP
        True
    """
    config = get_config()
    ssl_section = config.get("ssl", {})  # type: ignore[no-untyped-call]

    verify = ssl_section.get("verify", True)
    ca_bundle = ssl_section.get("ca_bundle")

    # Validate loaded values
    verify = validate_ssl_verify(verify)

    if ca_bundle is not None:
        ca_bundle = validate_ca_bundle_path(ca_bundle)

    return SSLConfig(verify=verify, ca_bundle=ca_bundle)


def build_ssl_context(
    ssl_verify: bool | None = None,
    ssl_ca_bundle: str | None = None,
) -> bool | str:
    """Build SSL context for httpx with cascade priority.

    Cascade order (highest priority first):
        1. Explicit kwargs (ssl_verify, ssl_ca_bundle)
        2. Global config from kstlib.conf.yml
        3. Secure default (verify=True)

    Args:
        ssl_verify: Override SSL verification (True/False).
        ssl_ca_bundle: Override CA bundle path.

    Returns:
        Value suitable for httpx verify parameter:
        - bool: True/False for system CA verification
        - str: Path to custom CA bundle

    Example:
        >>> # Use global config
        >>> verify = build_ssl_context()  # doctest: +SKIP

        >>> # Override with kwargs
        >>> verify = build_ssl_context(ssl_verify=False)  # doctest: +SKIP
        >>> verify  # doctest: +SKIP
        False

        >>> # Custom CA bundle
        >>> verify = build_ssl_context(ssl_ca_bundle="/path/to/ca.pem")  # doctest: +SKIP
    """
    # Load global config as base
    global_config = get_ssl_config()

    # Determine effective values (kwargs override global)
    effective_verify = ssl_verify if ssl_verify is not None else global_config.verify
    effective_ca_bundle = ssl_ca_bundle if ssl_ca_bundle is not None else global_config.ca_bundle

    # Validate kwargs if provided
    if ssl_verify is not None:
        effective_verify = validate_ssl_verify(ssl_verify)

    if ssl_ca_bundle is not None:
        effective_ca_bundle = validate_ca_bundle_path(ssl_ca_bundle)

    # Build result
    if effective_ca_bundle:
        if logger.isEnabledFor(TRACE_LEVEL):
            logger.log(TRACE_LEVEL, "[SSL] Using CA bundle: %s", effective_ca_bundle)
        return effective_ca_bundle

    if logger.isEnabledFor(TRACE_LEVEL):
        logger.log(TRACE_LEVEL, "[SSL] Verify: %s", effective_verify)

    return effective_verify


def validate_ssl_verify(value: Any) -> bool:
    """Validate ssl_verify with strict type check.

    Ensures the value is a boolean and logs a security warning
    if certificate verification is disabled.

    Args:
        value: Value to validate (should be bool).

    Returns:
        Validated boolean value.

    Raises:
        TypeError: If value is not a bool (YAML may pass "true" string).

    Example:
        >>> validate_ssl_verify(True)
        True
        >>> validate_ssl_verify("true")  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        TypeError: ssl_verify must be bool, got str: 'true'
    """
    if not isinstance(value, bool):
        msg = f"ssl_verify must be bool, got {type(value).__name__}: {value!r}"
        raise TypeError(msg)

    if not value:
        logger.warning(
            "[SECURITY] ssl_verify=False disables certificate validation. "
            "This exposes you to MITM attacks. Use only for development."
        )

    return value


def _validate_ca_bundle_string(path_str: str) -> None:
    """Validate CA bundle path string (layers 1-3).

    Args:
        path_str: Path string to validate.

    Raises:
        TypeError: If path is not a string.
        ValueError: If path contains null bytes or is empty.
    """
    # Layer 1: Type check
    path_value: Any = path_str
    if not isinstance(path_value, str):
        msg = f"ssl_ca_bundle must be str, got {type(path_value).__name__}"
        raise TypeError(msg)

    # Layer 2: Null byte injection
    if "\x00" in path_str:
        msg = "ssl_ca_bundle path contains null byte (potential injection attack)"
        raise ValueError(msg)

    # Layer 3: Empty string
    if not path_str.strip():
        msg = "ssl_ca_bundle cannot be empty string"
        raise ValueError(msg)


def _resolve_ca_bundle_path(path_str: str) -> Path:
    """Resolve CA bundle path (layer 4).

    Args:
        path_str: Path string to resolve.

    Returns:
        Resolved Path object.

    Raises:
        ValueError: If path does not exist or cannot be accessed.
    """
    try:
        return Path(path_str).expanduser().resolve(strict=True)
    except FileNotFoundError:
        msg = f"ssl_ca_bundle path does not exist: {path_str}"
        raise ValueError(msg) from None
    except OSError as e:
        msg = f"ssl_ca_bundle path error: {path_str} ({e})"
        raise ValueError(msg) from None


def _validate_ca_bundle_file(ca_path: Path, original_path: str) -> int:
    """Validate CA bundle file properties (layers 5-7).

    Args:
        ca_path: Resolved path to CA bundle file.
        original_path: Original path string for error messages.

    Returns:
        File size in bytes.

    Raises:
        ValueError: If file is invalid.
    """
    # Layer 5: File type
    if not ca_path.is_file():
        msg = f"ssl_ca_bundle must be a file, not directory: {original_path}"
        raise ValueError(msg)

    # Layer 6: Readable
    if not os.access(ca_path, os.R_OK):
        msg = f"ssl_ca_bundle file is not readable: {original_path}"
        raise ValueError(msg)

    # Layer 7: PEM format validation
    file_size = ca_path.stat().st_size
    if file_size < MIN_PEM_SIZE:
        msg = f"ssl_ca_bundle file too small ({file_size} bytes): {original_path}"
        raise ValueError(msg)

    try:
        with ca_path.open("r", encoding="utf-8") as f:
            header = f.read(1024)
            if "-----BEGIN" not in header:
                msg = f"ssl_ca_bundle does not appear to be PEM format: {original_path}"
                raise ValueError(msg)
    except UnicodeDecodeError:
        msg = f"ssl_ca_bundle is not valid text/PEM file: {original_path}"
        raise ValueError(msg) from None

    return file_size


def validate_ca_bundle_path(path_str: str) -> str:
    """Validate and normalize CA bundle path with deep defense.

    Performs 7 layers of security validation:
        1. Type check (must be string)
        2. Null byte injection check
        3. Empty/whitespace check
        4. Path existence check
        5. File type check (not directory)
        6. Readability check
        7. PEM format validation

    Args:
        path_str: Path to CA bundle file.

    Returns:
        Normalized absolute path (symlinks resolved).

    Raises:
        TypeError: If path is not a string.
        ValueError: If validation fails at any layer.

    Example:
        >>> validate_ca_bundle_path("/etc/ssl/certs/ca-certificates.crt")  # doctest: +SKIP
        '/etc/ssl/certs/ca-certificates.crt'
    """
    # Layers 1-3: String validation
    _validate_ca_bundle_string(path_str)

    # Layer 4: Path resolution
    ca_path = _resolve_ca_bundle_path(path_str)

    # Layers 5-7: File validation
    file_size = _validate_ca_bundle_file(ca_path, path_str)

    if logger.isEnabledFor(TRACE_LEVEL):
        logger.log(TRACE_LEVEL, "[SSL] CA bundle validated: %s (%d bytes)", ca_path, file_size)

    return str(ca_path)
