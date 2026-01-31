"""File permission constants for secure file operations.

This module centralizes POSIX permission values to avoid magic numbers
scattered throughout the codebase.

Note:
    On Windows, only read-only vs read-write distinction is supported.
    ``0o400`` becomes ``0o444`` (read-only attribute).

Example:
    >>> from kstlib.secure.permissions import FilePermissions  # doctest: +SKIP
    >>> path.chmod(FilePermissions.READONLY)  # doctest: +SKIP
"""

# pylint: disable=too-few-public-methods
# Justification: These classes are namespace containers for POSIX permission
# constants, not behavioral objects. They exist to avoid magic numbers and
# provide grouped, documented constants (e.g., FilePermissions.READONLY).

from __future__ import annotations


class FilePermissions:
    """POSIX file permission constants.

    Attributes:
        READONLY: Owner read-only (0o400). Use for sensitive files like tokens,
            private keys, and secrets. File cannot be modified after creation.
        READONLY_ALL: Read-only for all users (0o444). Use for public documents
            like certificates, CSRs, and public keys.
        OWNER_RW: Owner read-write (0o600). Use for files that need to be
            modified, or temporarily to unlock read-only files before deletion.
        OWNER_RWX: Owner read-write-execute (0o700). Use for directories
            containing sensitive files.
    """

    # Read-only for owner only - private keys, tokens, secrets
    READONLY: int = 0o400

    # Read-only for everyone - certificates, public keys
    READONLY_ALL: int = 0o444

    # Owner read-write - general sensitive files, unlock for deletion
    OWNER_RW: int = 0o600

    # Owner full access - directories
    OWNER_RWX: int = 0o700


class DirectoryPermissions:
    """POSIX directory permission constants.

    Attributes:
        PRIVATE: Owner-only access (0o700). Use for directories containing
            sensitive files like tokens or secrets.
        SHARED_READ: Owner full, group/others read+execute (0o755).
            Use for directories with public content.
    """

    # Private directory - only owner can access
    PRIVATE: int = 0o700

    # Shared read - owner full, others can read/traverse
    SHARED_READ: int = 0o755


__all__ = [
    "DirectoryPermissions",
    "FilePermissions",
]
