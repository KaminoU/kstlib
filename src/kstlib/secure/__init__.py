"""Security helpers (filesystem guardrails, policies, and errors)."""

from kstlib.secure import fs as _fs
from kstlib.secure import permissions as _perms

RELAXED_POLICY = _fs.RELAXED_POLICY
STRICT_POLICY = _fs.STRICT_POLICY
GuardPolicy = _fs.GuardPolicy
PathGuardrails = _fs.PathGuardrails
PathSecurityError = _fs.PathSecurityError

DirectoryPermissions = _perms.DirectoryPermissions
FilePermissions = _perms.FilePermissions

__all__ = [
    "RELAXED_POLICY",
    "STRICT_POLICY",
    "DirectoryPermissions",
    "FilePermissions",
    "GuardPolicy",
    "PathGuardrails",
    "PathSecurityError",
]
