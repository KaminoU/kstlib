"""Tests for the filesystem guardrail utilities."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from kstlib.secure import RELAXED_POLICY, STRICT_POLICY, GuardPolicy, PathGuardrails, PathSecurityError


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission semantics only")
def test_permission_enforcement_auto_hardens_world_writable(tmp_path: Path) -> None:
    """Guardrails should tighten world-writable directories when possible."""

    root = tmp_path / "guard"
    root.mkdir()
    os.chmod(root, 0o777)
    policy = GuardPolicy(
        name="strict-posix",
        auto_create_root=False,
        enforce_permissions=True,
        max_permission_octal=0o750,
    )

    guard = PathGuardrails(root, policy=policy)
    mode = stat.S_IMODE(guard.root.stat().st_mode)

    assert mode == 0o750


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission semantics only")
def test_permission_enforcement_raises_when_hardening_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Permission errors during hardening should surface as ``PathSecurityError``."""

    root = tmp_path / "guard"
    root.mkdir()
    os.chmod(root, 0o777)
    policy = GuardPolicy(name="strict-posix", auto_create_root=False, enforce_permissions=True)

    original_chmod = Path.chmod

    def _failing_chmod(self: Path, mode: int) -> None:  # pragma: no cover - executed in tests
        if self == root:
            raise PermissionError("blocked")
        original_chmod(self, mode)

    monkeypatch.setattr(Path, "chmod", _failing_chmod)

    with pytest.raises(PathSecurityError):
        PathGuardrails(root, policy=policy)


def test_resolves_relative_paths_within_root(tmp_path: Path) -> None:
    """Relative paths should resolve within the configured root."""

    root = tmp_path / "guard"
    (root / "reports").mkdir(parents=True)
    target = root / "reports" / "daily.txt"
    target.write_text("payload", encoding="utf-8")

    guard = PathGuardrails(root, policy=STRICT_POLICY)
    resolved = guard.resolve_file("reports/daily.txt")

    assert resolved == target


def test_rejects_path_traversal(tmp_path: Path) -> None:
    """Paths escaping the root should trigger security errors."""

    root = tmp_path / "guard"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("payload", encoding="utf-8")

    guard = PathGuardrails(root, policy=STRICT_POLICY)

    with pytest.raises(PathSecurityError):
        guard.resolve_file(outside)


def test_relax_helper_allows_external_access(tmp_path: Path) -> None:
    """``relax()`` should opt-in to external file resolution when requested."""

    root = tmp_path / "guard"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("payload", encoding="utf-8")

    base_guard = PathGuardrails(root, policy=RELAXED_POLICY)
    guard = base_guard.relax(allow_external=True)
    resolved = guard.resolve_file(outside)

    assert resolved == outside


def test_policy_property_returns_policy(tmp_path: Path) -> None:
    """The policy property returns the configured policy."""
    root = tmp_path / "guard"
    root.mkdir()
    guard = PathGuardrails(root, policy=RELAXED_POLICY)

    assert guard.policy == RELAXED_POLICY
    assert guard.policy.name == "relaxed"


def test_root_property_returns_resolved_root(tmp_path: Path) -> None:
    """The root property returns the resolved root directory."""
    root = tmp_path / "guard"
    root.mkdir()
    guard = PathGuardrails(root, policy=RELAXED_POLICY)

    assert guard.root == root.resolve()
    assert guard.root.is_dir()


def test_resolve_file_rejects_directory(tmp_path: Path) -> None:
    """resolve_file should reject directories."""
    root = tmp_path / "guard"
    subdir = root / "subdir"
    subdir.mkdir(parents=True)

    guard = PathGuardrails(root, policy=RELAXED_POLICY)

    with pytest.raises(PathSecurityError, match="Expected file"):
        guard.resolve_file("subdir")


def test_resolve_directory_accepts_directory(tmp_path: Path) -> None:
    """resolve_directory should accept directories."""
    root = tmp_path / "guard"
    subdir = root / "subdir"
    subdir.mkdir(parents=True)

    guard = PathGuardrails(root, policy=RELAXED_POLICY)
    resolved = guard.resolve_directory("subdir")

    assert resolved == subdir


def test_resolve_directory_rejects_file(tmp_path: Path) -> None:
    """resolve_directory should reject files."""
    root = tmp_path / "guard"
    root.mkdir()
    target = root / "file.txt"
    target.write_text("content", encoding="utf-8")

    guard = PathGuardrails(root, policy=RELAXED_POLICY)

    with pytest.raises(PathSecurityError, match="Expected directory"):
        guard.resolve_directory("file.txt")


def test_resolve_path_returns_non_existent_path(tmp_path: Path) -> None:
    """resolve_path should resolve paths without existence checks."""
    root = tmp_path / "guard"
    root.mkdir()

    guard = PathGuardrails(root, policy=RELAXED_POLICY)
    resolved = guard.resolve_path("nonexistent/path/file.txt")

    assert resolved == root / "nonexistent" / "path" / "file.txt"
    assert not resolved.exists()


def test_rejects_nonexistent_root_without_auto_create(tmp_path: Path) -> None:
    """Raise PathSecurityError when root doesn't exist and auto_create is False."""
    nonexistent = tmp_path / "does_not_exist"
    policy = GuardPolicy(name="no-create", auto_create_root=False)

    with pytest.raises(PathSecurityError, match="does not exist"):
        PathGuardrails(nonexistent, policy=policy)


def test_rejects_file_as_root(tmp_path: Path) -> None:
    """Raise PathSecurityError when root is a file, not a directory."""
    file_path = tmp_path / "file.txt"
    file_path.write_text("content", encoding="utf-8")
    policy = GuardPolicy(name="test", auto_create_root=False)

    with pytest.raises(PathSecurityError, match="must be a directory"):
        PathGuardrails(file_path, policy=policy)


def test_resolve_rejects_nonexistent_path(tmp_path: Path) -> None:
    """_resolve with require_exists=True rejects nonexistent paths."""
    root = tmp_path / "guard"
    root.mkdir()

    guard = PathGuardrails(root, policy=RELAXED_POLICY)

    with pytest.raises(PathSecurityError, match="does not exist"):
        guard.resolve_file("nonexistent.txt")


@pytest.mark.skipif(os.name != "nt", reason="Windows drive check only")
def test_rejects_different_drive_on_windows(tmp_path: Path) -> None:
    """Paths on a different drive should trigger security errors on Windows."""
    root = tmp_path / "guard"
    root.mkdir()

    guard = PathGuardrails(root, policy=STRICT_POLICY)

    # Create a path on a different drive (if root is on C:, try D:)
    root_drive = root.drive.upper()
    other_drive = "D:" if root_drive == "C:" else "C:"
    other_path = Path(f"{other_drive}\\some\\path\\file.txt")

    with pytest.raises(PathSecurityError, match="different drive"):
        guard.resolve_path(other_path)


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission semantics only")
def test_permission_validation_rejects_excessive_permissions(tmp_path: Path) -> None:
    """Validate permissions raises when directory exceeds allowed mask."""
    root = tmp_path / "guard"
    root.mkdir()
    # Set restrictive permissions first so guardrails accepts the root
    os.chmod(root, 0o700)

    policy = GuardPolicy(
        name="strict-posix",
        auto_create_root=False,
        enforce_permissions=True,
        max_permission_octal=0o700,
    )
    guard = PathGuardrails(root, policy=policy)

    # Create a subdirectory with excessive permissions
    subdir = root / "subdir"
    subdir.mkdir()
    os.chmod(subdir, 0o777)

    # Manually call validate to trigger the check
    with pytest.raises(PathSecurityError, match="exceeds allowed permissions"):
        guard._validate_permissions(subdir)


def test_relax_preserves_policy_when_none(tmp_path: Path) -> None:
    """relax() preserves allow_external when passed None."""
    root = tmp_path / "guard"
    root.mkdir()

    base_guard = PathGuardrails(root, policy=RELAXED_POLICY)
    relaxed = base_guard.relax(allow_external=None)

    assert relaxed.policy.allow_external == base_guard.policy.allow_external


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission semantics only")
def test_permission_hardening_skips_when_compliant(tmp_path: Path) -> None:
    """Guardrails should not modify permissions if already compliant."""
    root = tmp_path / "guard"
    root.mkdir()
    os.chmod(root, 0o700)

    policy = GuardPolicy(
        name="strict-posix",
        auto_create_root=False,
        enforce_permissions=True,
        max_permission_octal=0o700,
    )

    guard = PathGuardrails(root, policy=policy)
    mode = stat.S_IMODE(guard.root.stat().st_mode)

    # Should remain at 0o700 since it's already compliant
    assert mode == 0o700


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission semantics only")
def test_permission_validation_on_subdirectory(tmp_path: Path) -> None:
    """Validation on subdirectory should work correctly."""
    root = tmp_path / "guard"
    root.mkdir()
    os.chmod(root, 0o700)

    policy = GuardPolicy(
        name="strict-posix",
        auto_create_root=False,
        enforce_permissions=True,
        max_permission_octal=0o700,
    )
    guard = PathGuardrails(root, policy=policy)

    # Create compliant subdirectory
    subdir = root / "compliant"
    subdir.mkdir()
    os.chmod(subdir, 0o700)

    # Should pass validation without exception
    guard._validate_permissions(subdir)

    # Create non-compliant subdirectory
    bad_subdir = root / "noncompliant"
    bad_subdir.mkdir()
    os.chmod(bad_subdir, 0o755)

    # Should fail validation
    with pytest.raises(PathSecurityError, match="exceeds allowed permissions"):
        guard._validate_permissions(bad_subdir)


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission semantics only")
def test_permission_hardening_with_group_and_other_bits(tmp_path: Path) -> None:
    """Guardrails should remove group and other bits when hardening."""
    root = tmp_path / "guard"
    root.mkdir()
    os.chmod(root, 0o755)  # rwxr-xr-x

    policy = GuardPolicy(
        name="strict-posix",
        auto_create_root=False,
        enforce_permissions=True,
        max_permission_octal=0o700,  # rwx------
    )

    guard = PathGuardrails(root, policy=policy)
    mode = stat.S_IMODE(guard.root.stat().st_mode)

    # Should be hardened to 0o700
    assert mode == 0o700
