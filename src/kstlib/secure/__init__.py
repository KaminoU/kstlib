"""Security helpers (filesystem guardrails, policies, password hashing, errors)."""

from kstlib.secure import fs as _fs
from kstlib.secure import passwords as _passwords
from kstlib.secure import permissions as _perms

RELAXED_POLICY = _fs.RELAXED_POLICY
STRICT_POLICY = _fs.STRICT_POLICY
GuardPolicy = _fs.GuardPolicy
PathGuardrails = _fs.PathGuardrails
PathSecurityError = _fs.PathSecurityError

DirectoryPermissions = _perms.DirectoryPermissions
FilePermissions = _perms.FilePermissions

InvalidPasswordHashError = _passwords.InvalidPasswordHashError
PasswordError = _passwords.PasswordError
hash_password = _passwords.hash_password
needs_rehash = _passwords.needs_rehash
verify_password = _passwords.verify_password

__all__ = [
    "RELAXED_POLICY",
    "STRICT_POLICY",
    "DirectoryPermissions",
    "FilePermissions",
    "GuardPolicy",
    "InvalidPasswordHashError",
    "PasswordError",
    "PathGuardrails",
    "PathSecurityError",
    "hash_password",
    "needs_rehash",
    "verify_password",
]
