"""Argon2id password hashing helpers.

This module wraps the optional ``argon2-cffi`` backend (install via
``pip install kstlib[passwords]``) to provide password hashing and
verification with safe, OWASP-aligned defaults.

Cost parameters follow a ``kwargs > kstlib config > defaults`` cascade. Any
resolved parameter below the security floor is clamped up and a ``[SECURITY]``
warning is logged. Passwords and hashes are never written to the logs.

Example:
    >>> from kstlib.secure import hash_password, verify_password
    >>> stored = hash_password("correct horse battery staple")  # doctest: +SKIP
    >>> verify_password("correct horse battery staple", stored)  # doctest: +SKIP
    True

"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from kstlib.config.exceptions import KstlibError
from kstlib.logging import get_logger

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import (
        HashingError,
        InvalidHashError,
        VerificationError,
        VerifyMismatchError,
    )
except ImportError:  # pragma: no cover - argon2-cffi is an optional extra
    _ARGON2_AVAILABLE = False
else:
    _ARGON2_AVAILABLE = True

log = get_logger(__name__)

__all__ = [
    "DEFAULT_HASH_LEN",
    "DEFAULT_MEMORY_COST",
    "DEFAULT_PARALLELISM",
    "DEFAULT_SALT_LEN",
    "DEFAULT_TIME_COST",
    "MAX_PASSWORD_LENGTH",
    "MIN_HASH_LEN",
    "MIN_MEMORY_COST",
    "MIN_PARALLELISM",
    "MIN_SALT_LEN",
    "MIN_TIME_COST",
    "InvalidPasswordHashError",
    "PasswordError",
    "hash_password",
    "needs_rehash",
    "verify_password",
]

# Baseline cost parameters: mirror the argon2-cffi 25.x PasswordHasher defaults
# (RFC 9106 low-memory profile), which already track the OWASP recommendation.
DEFAULT_TIME_COST: Final = 3
DEFAULT_MEMORY_COST: Final = 65536  # KiB (64 MiB)
DEFAULT_PARALLELISM: Final = 4
DEFAULT_HASH_LEN: Final = 32  # bytes
DEFAULT_SALT_LEN: Final = 16  # bytes

# Security floors: a resolved parameter below these is clamped up. The floor is
# the OWASP "minimum configuration" baseline (19 MiB / t=2 / p=1); the defaults
# sit well above it, so the floor only blocks a deliberate downgrade.
MIN_TIME_COST: Final = 2
MIN_MEMORY_COST: Final = 19456  # KiB (19 MiB, OWASP minimum baseline)
MIN_PARALLELISM: Final = 1
MIN_HASH_LEN: Final = 16  # bytes
MIN_SALT_LEN: Final = 16  # bytes

# Hardening: cap the accepted password size so a multi-megabyte input cannot be
# used as a CPU/memory denial-of-service vector against the hasher.
MAX_PASSWORD_LENGTH: Final = 4096  # bytes


class PasswordError(KstlibError, RuntimeError):
    """Raised when a password hashing operation cannot be completed."""


class InvalidPasswordHashError(PasswordError):
    """Raised when a stored value is not a valid Argon2 hash."""


@dataclass(frozen=True, slots=True)
class _CostParams:
    """Resolved and clamped Argon2 cost parameters."""

    time_cost: int
    memory_cost: int
    parallelism: int
    hash_len: int
    salt_len: int


def _ensure_available() -> None:
    """Raise a clear error when the optional argon2-cffi backend is missing."""
    if not _ARGON2_AVAILABLE:
        raise PasswordError("password hashing requires argon2-cffi: pip install kstlib[passwords]")


def _encode_password(password: str | bytes) -> bytes:
    """Return *password* as UTF-8 bytes, rejecting unexpected types."""
    if isinstance(password, str):
        return password.encode("utf-8")
    if isinstance(password, bytes):
        return password
    raise PasswordError("password must be str or bytes")


def _pick(override: int | None, section: Any, key: str, default: int) -> int:
    """Resolve one cost value via the kwargs > config > default cascade."""
    if override is not None:
        return override
    value: Any = section.get(key) if hasattr(section, "get") else None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


def _clamp_value(name: str, value: int, floor: int) -> int:
    """Clamp *value* up to *floor*, logging a security warning when it does."""
    if value < floor:
        log.warning(
            "[SECURITY] argon2 %s=%d is below the security floor %d; clamped to floor",
            name,
            value,
            floor,
        )
        return floor
    return value


def _load_password_config() -> Any:
    """Return the ``secure.passwords`` config section, or an empty mapping.

    Falls back to an empty mapping when no kstlib configuration is loaded, so
    hashing works standalone without any ``kstlib.conf.yml`` present.
    """
    try:
        from kstlib.config import get_config
        from kstlib.config.exceptions import ConfigNotLoadedError
    except ImportError:  # pragma: no cover - kstlib.config is always present
        return {}
    try:
        cfg: Any = get_config()
    except ConfigNotLoadedError:
        return {}
    except Exception:  # any loader failure falls back to safe defaults
        log.debug("Could not load kstlib config; using default argon2 parameters")
        return {}
    secure_section: Any = cfg.get("secure", {}) if hasattr(cfg, "get") else {}
    passwords_section: Any = secure_section.get("passwords", {}) if hasattr(secure_section, "get") else {}
    return passwords_section if hasattr(passwords_section, "get") else {}


def _resolve_params(
    *,
    time_cost: int | None,
    memory_cost: int | None,
    parallelism: int | None,
    hash_len: int | None,
    salt_len: int | None,
) -> _CostParams:
    """Resolve cost parameters (kwargs > config > defaults) and clamp to floors."""
    section = _load_password_config()
    return _CostParams(
        time_cost=_clamp_value("time_cost", _pick(time_cost, section, "time_cost", DEFAULT_TIME_COST), MIN_TIME_COST),
        memory_cost=_clamp_value(
            "memory_cost",
            _pick(memory_cost, section, "memory_cost", DEFAULT_MEMORY_COST),
            MIN_MEMORY_COST,
        ),
        parallelism=_clamp_value(
            "parallelism",
            _pick(parallelism, section, "parallelism", DEFAULT_PARALLELISM),
            MIN_PARALLELISM,
        ),
        hash_len=_clamp_value("hash_len", _pick(hash_len, section, "hash_len", DEFAULT_HASH_LEN), MIN_HASH_LEN),
        salt_len=_clamp_value("salt_len", _pick(salt_len, section, "salt_len", DEFAULT_SALT_LEN), MIN_SALT_LEN),
    )


def hash_password(
    password: str | bytes,
    *,
    time_cost: int | None = None,
    memory_cost: int | None = None,
    parallelism: int | None = None,
) -> str:
    """Hash a password with Argon2id and return the encoded PHC string.

    The cost knobs (``time_cost``, ``memory_cost``, ``parallelism``) resolve as
    ``kwargs > kstlib config > defaults`` and are clamped to the security floors
    (``time_cost>=2``, ``memory_cost>=19456`` KiB, ``parallelism>=1``). Defaults
    track the argon2-cffi 25.x / OWASP recommendation (``time_cost=3``,
    ``memory_cost=65536`` KiB, ``parallelism=4``).

    Output sizing (``hash_len``, ``salt_len``) is intentionally not a per-call
    argument: it must stay consistent across all stored hashes. Configure it once
    via ``secure.passwords.hash_len`` / ``secure.passwords.salt_len`` in
    ``kstlib.conf.yml`` (defaults ``hash_len=32``, ``salt_len=16``; floors
    ``hash_len>=16``, ``salt_len>=16``).

    Args:
        password: Plaintext password as ``str`` (UTF-8 encoded) or ``bytes``.
        time_cost: Number of iterations. Defaults to the cascade value.
        memory_cost: Memory usage in KiB. Defaults to the cascade value.
        parallelism: Number of parallel lanes. Defaults to the cascade value.

    Returns:
        The Argon2id hash encoded as a PHC string (``$argon2id$...``).

    Raises:
        PasswordError: If argon2-cffi is not installed, the password is not
            ``str`` or ``bytes``, the password exceeds ``MAX_PASSWORD_LENGTH``,
            or the underlying hashing operation fails.

    Example:
        >>> from kstlib.secure import hash_password
        >>> hash_password("s3cret")  # doctest: +SKIP
        '$argon2id$v=19$m=65536,t=3,p=4$...'

    """
    _ensure_available()
    secret = _encode_password(password)
    if len(secret) > MAX_PASSWORD_LENGTH:
        raise PasswordError(f"password exceeds maximum length of {MAX_PASSWORD_LENGTH} bytes")
    params = _resolve_params(
        time_cost=time_cost,
        memory_cost=memory_cost,
        parallelism=parallelism,
        hash_len=None,
        salt_len=None,
    )
    hasher = PasswordHasher(
        time_cost=params.time_cost,
        memory_cost=params.memory_cost,
        parallelism=params.parallelism,
        hash_len=params.hash_len,
        salt_len=params.salt_len,
    )
    try:
        return hasher.hash(secret)
    except HashingError as exc:
        raise PasswordError(f"argon2 hashing failed: {exc}") from exc


def verify_password(password: str | bytes, stored_hash: str) -> bool:
    """Verify a password against a stored Argon2id hash in constant time.

    Args:
        password: Plaintext password to check (``str`` or ``bytes``).
        stored_hash: Previously stored PHC hash string.

    Returns:
        ``True`` if the password matches, ``False`` otherwise (including when
        the password exceeds ``MAX_PASSWORD_LENGTH``).

    Raises:
        PasswordError: If argon2-cffi is not installed or the password is not
            ``str`` or ``bytes``.
        InvalidPasswordHashError: If ``stored_hash`` is not a valid Argon2 hash.

    Example:
        >>> from kstlib.secure import hash_password, verify_password
        >>> stored = hash_password("s3cret")  # doctest: +SKIP
        >>> verify_password("s3cret", stored)  # doctest: +SKIP
        True

    """
    _ensure_available()
    secret = _encode_password(password)
    if len(secret) > MAX_PASSWORD_LENGTH:
        # An oversized candidate cannot match a hash of a bounded password.
        # Return False (no raise) to avoid leaking the rejection via an
        # exception and to keep the constant-time-ish verification contract.
        return False
    hasher = PasswordHasher()
    try:
        hasher.verify(stored_hash, secret)
    except VerifyMismatchError:
        return False
    except (InvalidHashError, VerificationError) as exc:
        raise InvalidPasswordHashError("stored value is not a valid argon2 hash") from exc
    return True


def needs_rehash(stored_hash: str) -> bool:
    """Return whether a stored hash should be recomputed with current parameters.

    Compares the parameters embedded in *stored_hash* against the currently
    resolved policy (kstlib config or defaults). Returns ``True`` when the stored
    hash is weaker than the current parameters and should be upgraded on the next
    successful login.

    Args:
        stored_hash: Previously stored PHC hash string.

    Returns:
        ``True`` if the hash should be regenerated, ``False`` otherwise.

    Raises:
        PasswordError: If argon2-cffi is not installed.
        InvalidPasswordHashError: If ``stored_hash`` is not a valid Argon2 hash.

    """
    _ensure_available()
    params = _resolve_params(time_cost=None, memory_cost=None, parallelism=None, hash_len=None, salt_len=None)
    hasher = PasswordHasher(
        time_cost=params.time_cost,
        memory_cost=params.memory_cost,
        parallelism=params.parallelism,
        hash_len=params.hash_len,
        salt_len=params.salt_len,
    )
    try:
        return hasher.check_needs_rehash(stored_hash)
    except InvalidHashError as exc:
        raise InvalidPasswordHashError("stored value is not a valid argon2 hash") from exc
