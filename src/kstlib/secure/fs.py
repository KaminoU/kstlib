"""Filesystem guardrails utilities for securing file access.

Example:
    Basic usage with a temporary directory::

        >>> import tempfile
        >>> from kstlib.secure import PathGuardrails, STRICT_POLICY
        >>> with tempfile.TemporaryDirectory() as tmpdir:
        ...     guard = PathGuardrails(tmpdir, policy=STRICT_POLICY)
        ...     guard.root.is_dir()
        True
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final

from kstlib.secure.permissions import DirectoryPermissions

__all__ = [
    "RELAXED_POLICY",
    "STRICT_POLICY",
    "GuardPolicy",
    "PathGuardrails",
    "PathSecurityError",
]


class PathSecurityError(RuntimeError):
    """Raised when filesystem guardrails detect a security violation."""


@dataclass(frozen=True, slots=True)
class GuardPolicy:
    """Configuration values defining how guardrails behave.

    Attributes:
        name: Human-friendly label used for diagnostics.
        allow_external: When True, paths outside the root are accepted.
        auto_create_root: Automatically create the root directory when missing.
        enforce_permissions: Whether POSIX permissions should be validated.
        max_permission_octal: Maximum allowed permission mask (defaults to PRIVATE).

    Example:
        >>> from kstlib.secure import GuardPolicy
        >>> policy = GuardPolicy(name="custom", allow_external=False)
        >>> policy.name
        'custom'
    """

    name: str
    allow_external: bool = False
    auto_create_root: bool = True
    enforce_permissions: bool = True
    max_permission_octal: int = DirectoryPermissions.PRIVATE  # 0o700


STRICT_POLICY: Final[GuardPolicy] = GuardPolicy(name="strict")
RELAXED_POLICY: Final[GuardPolicy] = GuardPolicy(
    name="relaxed",
    allow_external=False,
    auto_create_root=True,
    enforce_permissions=False,
    max_permission_octal=0o777,  # No restrictions
)


class PathGuardrails:
    """Validate and resolve paths relative to a trusted root.

    Example:
        >>> import tempfile
        >>> from kstlib.secure import PathGuardrails, RELAXED_POLICY
        >>> with tempfile.TemporaryDirectory() as tmpdir:
        ...     guard = PathGuardrails(tmpdir, policy=RELAXED_POLICY)
        ...     guard.policy.name
        'relaxed'
    """

    def __init__(self, root: str | Path, *, policy: GuardPolicy = STRICT_POLICY) -> None:
        """Initialise guardrails rooted at *root* while enforcing *policy*.

        Raises:
            PathSecurityError: If root does not exist or is not a directory.
        """
        self._policy = policy
        expanded = Path(root).expanduser()
        if policy.auto_create_root:
            expanded.mkdir(parents=True, exist_ok=True, mode=0o755)
        self._root = expanded.resolve()
        if not self._root.exists():
            raise PathSecurityError(f"Guardrail root does not exist: {self._root}")
        if not self._root.is_dir():
            raise PathSecurityError(f"Guardrail root must be a directory: {self._root}")
        self._harden_permissions(self._root)
        self._validate_permissions(self._root)

    @property
    def root(self) -> Path:
        """Return the resolved guardrail root directory."""
        return self._root

    @property
    def policy(self) -> GuardPolicy:
        """Return the policy associated with the guardrails."""
        return self._policy

    def resolve_file(self, candidate: str | Path) -> Path:
        """Resolve *candidate* and ensure it points to an existing file.

        Raises:
            PathSecurityError: If path is not a file or is outside root.
        """
        path = self._resolve(candidate)
        if not path.is_file():
            raise PathSecurityError(f"Expected file path but found: {path}")
        return path

    def resolve_directory(self, candidate: str | Path) -> Path:
        """Resolve *candidate* and ensure it points to an existing directory.

        Raises:
            PathSecurityError: If path is not a directory or is outside root.
        """
        path = self._resolve(candidate)
        if not path.is_dir():
            raise PathSecurityError(f"Expected directory path but found: {path}")
        return path

    def resolve_path(self, candidate: str | Path) -> Path:
        """Resolve *candidate* relative to the guardrail root without type checks."""
        return self._resolve(candidate, require_exists=False)

    def relax(self, *, allow_external: bool | None = None) -> PathGuardrails:
        """Return a new guardrail instance with adjusted external allowances."""
        new_policy = replace(
            self._policy,
            allow_external=self._policy.allow_external if allow_external is None else allow_external,
        )
        return PathGuardrails(self._root, policy=new_policy)

    def _resolve(self, candidate: str | Path, *, require_exists: bool = True) -> Path:
        path = Path(candidate).expanduser()
        if not path.is_absolute():
            path = self._root / path
        resolved = path.resolve()
        self._ensure_within_root(resolved)
        if require_exists and not resolved.exists():
            raise PathSecurityError(f"Resolved path does not exist: {resolved}")
        return resolved

    def _ensure_within_root(self, path: Path) -> None:
        if self._policy.allow_external:
            return
        if os.name == "nt" and self._root.drive and path.drive.lower() != self._root.drive.lower():
            raise PathSecurityError(f"Path is on a different drive: {path}")
        try:
            path.relative_to(self._root)
        except ValueError as exc:
            raise PathSecurityError(f"Path escapes guardrail root: {path}") from exc

    def _validate_permissions(self, directory: Path) -> None:
        if not self._policy.enforce_permissions:
            return
        if os.name != "posix":
            return
        # POSIX-only path - tested with real POSIX tests on Linux/macOS
        mode = directory.stat().st_mode  # pragma: no cover - POSIX only
        if stat.S_IMODE(mode) & ~self._policy.max_permission_octal:  # pragma: no cover - POSIX only
            raise PathSecurityError(  # pragma: no cover - POSIX only
                f"Directory {directory} exceeds allowed permissions {oct(self._policy.max_permission_octal)}"
            )

    def _harden_permissions(self, directory: Path) -> None:
        if not self._policy.enforce_permissions:
            return
        if os.name != "posix":
            return
        # POSIX-only path - tested with real POSIX tests on Linux/macOS
        current_mode = stat.S_IMODE(directory.stat().st_mode)  # pragma: no cover - POSIX only
        allowed_mask = self._policy.max_permission_octal  # pragma: no cover - POSIX only
        if current_mode & ~allowed_mask == 0:  # pragma: no cover - POSIX only
            return  # pragma: no cover - POSIX only
        desired_mode = current_mode & allowed_mask  # pragma: no cover - POSIX only
        try:  # pragma: no cover - POSIX only
            directory.chmod(desired_mode)  # pragma: no cover - POSIX only
        except PermissionError as exc:  # pragma: no cover - POSIX only, env-specific
            raise PathSecurityError(
                f"Unable to adjust permissions for {directory}; requires <= {oct(allowed_mask)}"
            ) from exc
