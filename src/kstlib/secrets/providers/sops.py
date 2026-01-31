"""SOPS-backed provider."""

from __future__ import annotations

# pylint: disable=duplicate-code
import json
import logging
import re
import shutil
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from pathlib import Path
from subprocess import run as subprocess_run
from typing import Any

import yaml

from kstlib.limits import HARD_MAX_SOPS_CACHE_ENTRIES, SopsLimits, get_sops_limits
from kstlib.secrets.exceptions import SecretDecryptionError
from kstlib.secrets.models import SecretRecord, SecretRequest, SecretSource
from kstlib.secrets.providers.base import SecretProvider

logger = logging.getLogger(__name__)


class SOPSProvider(SecretProvider):
    """Load secrets from SOPS encrypted documents."""

    name = "sops"

    def __init__(
        self,
        *,
        path: str | Path | None = None,
        binary: str = "sops",
        document_format: str = "auto",
        limits: SopsLimits | None = None,
    ) -> None:
        """Configure the provider with optional defaults."""
        self._path = Path(path) if path else None
        self._binary = binary
        self._document_format = document_format
        self._limits = limits or get_sops_limits()
        self._max_cache_entries = self._limits.max_cache_entries
        self._cache: OrderedDict[Path, tuple[float, Any]] = OrderedDict()

    def configure(self, settings: Mapping[str, Any] | None = None) -> None:
        """Apply overrides supplied by configuration files."""
        if not settings:
            return
        target = settings.get("path")
        if target:
            self._path = Path(target)
        binary = settings.get("binary")
        if binary:
            self._binary = binary
        fmt = settings.get("format") or settings.get("document_format")
        if fmt:
            self._document_format = fmt
        max_entries = settings.get("max_cache_entries")
        if max_entries is not None:
            # Enforce hard limit for deep defense
            self._max_cache_entries = min(int(max_entries), HARD_MAX_SOPS_CACHE_ENTRIES)

    def resolve(self, request: SecretRequest) -> SecretRecord | None:
        """Resolve the requested secret from the encrypted document."""
        path = self._resolve_path(request)
        if path is None:
            return None

        document = self._load_document(path)
        value = self._extract_value(document, request)
        if value is None:
            return None

        metadata = {
            "path": str(path),
            "format": self._document_format,
            "binary": self._binary,
        }
        return SecretRecord(value=value, source=SecretSource.SOPS, metadata=metadata)

    def _resolve_path(self, request: SecretRequest) -> Path | None:
        """Determine the effective SOPS path for a secret request."""
        candidate = request.metadata.get("path") if request.metadata else None
        if candidate:
            return Path(candidate)
        return self._path

    def _load_document(self, path: Path) -> Any:
        """Decrypt and parse the underlying SOPS document."""
        try:
            mtime = path.stat().st_mtime
        except FileNotFoundError as exc:  # pragma: no cover - defensive branch
            raise SecretDecryptionError(f"SOPS file not found: {path}") from exc

        cached = self._cache.get(path)
        if cached and cached[0] == mtime:
            # Move to end for LRU tracking
            self._cache.move_to_end(path)
            return cached[1]

        binary_path = shutil.which(self._binary)
        if binary_path is None:
            raise SecretDecryptionError(
                "SOPS binary not found. Install from https://github.com/getsops/sops or set 'binary' option.",
            )

        command = [binary_path, "--decrypt", str(path)]
        process = subprocess_run(
            command,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
        if process.returncode != 0:
            diagnostic = process.stderr.strip() or process.stdout.strip()
            if diagnostic:
                logger.debug(
                    "SOPS decryption failed for %s: %s",
                    path,
                    self._redact_sensitive_output(diagnostic),
                )
            raise SecretDecryptionError(
                f"Failed to decrypt secrets file '{path.name}'. Check SOPS configuration and file permissions."
            )

        document = self._parse_document(process.stdout)
        self._cache[path] = (mtime, document)
        self._cache.move_to_end(path)
        # Evict oldest entries (LRU) if cache exceeds limit
        while len(self._cache) > self._max_cache_entries:
            self._cache.popitem(last=False)
        return document

    def _parse_document(self, payload: str) -> Any:
        """Deserialize the decrypted payload according to the configured format."""
        fmt = self._document_format.lower()
        try:
            if fmt == "json":
                return json.loads(payload)
            if fmt == "yaml":
                return yaml.safe_load(payload)
            if fmt == "text":
                return payload
            # auto-detect: try json then yaml, fallback to text
            return json.loads(payload)
        except json.JSONDecodeError:
            try:
                return yaml.safe_load(payload)
            except yaml.YAMLError as exc:
                raise SecretDecryptionError("Unable to parse decrypted document as JSON or YAML") from exc
        except yaml.YAMLError as exc:
            raise SecretDecryptionError("Unable to parse decrypted document as YAML") from exc

    def _extract_value(self, document: Any, request: SecretRequest) -> Any | None:
        """Extract the value identified by the request metadata or name."""
        key_path = request.metadata.get("key_path") if request.metadata else None
        if key_path is None:
            key_path = request.name

        if isinstance(key_path, str):
            parts = [part for part in key_path.split(".") if part]
        elif isinstance(key_path, Sequence):
            parts = [str(part) for part in key_path]
        else:  # pragma: no cover - defensive guard
            raise SecretDecryptionError("Invalid 'key_path' metadata; expected string or sequence of strings.")

        current = document
        for part in parts:
            if isinstance(current, Mapping) and part in current:
                current = current[part]
            else:
                return None
        return current

    @staticmethod
    def _redact_sensitive_output(message: str) -> str:
        """Redact known sensitive substrings from diagnostic output."""
        patterns = [
            re.compile(r"arn:aws:[^\s]+", re.IGNORECASE),
            re.compile(r"AKIA[0-9A-Z]{16}"),
            re.compile(r"(?:/home/|/Users/)[^\s]+"),
        ]
        redacted = message
        for pattern in patterns:
            redacted = pattern.sub("[REDACTED]", redacted)
        return redacted

    def purge_cache(self, *, path: str | Path | None = None) -> None:
        """Clear decrypted document cache entries."""
        if path is None:
            self._cache.clear()
            return

        target = Path(path)
        if target in self._cache:
            self._cache.pop(target, None)
            return

        try:
            resolved = target.resolve()
        except OSError:  # pragma: no cover - inaccessible paths
            return
        self._cache.pop(resolved, None)


__all__ = ["SOPSProvider"]
