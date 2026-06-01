"""Tests for kstlib.secure.passwords (Argon2id hashing)."""

from __future__ import annotations

from typing import NoReturn

import pytest
from argon2.exceptions import HashingError

from kstlib.config.exceptions import ConfigNotLoadedError, KstlibError
from kstlib.secure import passwords
from kstlib.secure.passwords import (
    DEFAULT_HASH_LEN,
    DEFAULT_MEMORY_COST,
    DEFAULT_PARALLELISM,
    DEFAULT_SALT_LEN,
    DEFAULT_TIME_COST,
    MAX_PASSWORD_LENGTH,
    MIN_HASH_LEN,
    MIN_MEMORY_COST,
    MIN_PARALLELISM,
    MIN_SALT_LEN,
    MIN_TIME_COST,
    InvalidPasswordHashError,
    PasswordError,
    hash_password,
    needs_rehash,
    verify_password,
)

# Cheap-but-valid cost parameters (at the security floor) to keep tests fast.
FAST_TIME = 2
FAST_MEMORY = MIN_MEMORY_COST
FAST_PAR = 1


def _raise_not_loaded() -> NoReturn:
    """Stand-in for get_config when no kstlib config is loaded."""
    raise ConfigNotLoadedError("no config loaded in test")


def _fast_hash(password: str | bytes) -> str:
    """Hash with floor-level parameters to keep the test suite fast."""
    return hash_password(password, time_cost=FAST_TIME, memory_cost=FAST_MEMORY, parallelism=FAST_PAR)


class _BoomHasher:
    """Fake PasswordHasher whose hash() always raises HashingError."""

    def __init__(self, **kwargs: object) -> None:
        self._kwargs = kwargs

    def hash(self, secret: str | bytes) -> str:
        """Always fail, simulating a backend hashing error."""
        raise HashingError("boom")


class TestRoundtrip:
    """Hashing then verifying the same password succeeds."""

    def test_roundtrip_str(self) -> None:
        """A str password verifies against its own hash."""
        stored = _fast_hash("correct-horse")
        assert verify_password("correct-horse", stored) is True

    def test_roundtrip_bytes(self) -> None:
        """A bytes password verifies against its own hash."""
        stored = _fast_hash(b"correct-horse")
        assert verify_password(b"correct-horse", stored) is True

    def test_str_and_bytes_interchangeable(self) -> None:
        """The same password verifies whether passed as str or bytes."""
        stored = _fast_hash("p4ssword")
        assert verify_password(b"p4ssword", stored) is True

    def test_hash_is_argon2id_phc(self) -> None:
        """The returned value is an Argon2id PHC string."""
        assert _fast_hash("p").startswith("$argon2id$")

    def test_two_hashes_differ(self) -> None:
        """Hashing the same password twice yields different hashes (random salt)."""
        assert _fast_hash("p") != _fast_hash("p")

    def test_wrong_password_returns_false(self) -> None:
        """A wrong password returns False rather than raising."""
        stored = _fast_hash("right")
        assert verify_password("wrong", stored) is False


class TestInvalidHash:
    """Corrupt or malformed stored hashes raise InvalidPasswordHashError."""

    @pytest.mark.parametrize("bad", ["", "not-a-hash", "$argon2id$garbage", "1234"])
    def test_verify_corrupt_hash_raises(self, bad: str) -> None:
        """Verifying against a malformed hash raises InvalidPasswordHashError."""
        with pytest.raises(InvalidPasswordHashError):
            verify_password("p", bad)

    def test_needs_rehash_corrupt_raises(self) -> None:
        """needs_rehash on a malformed hash raises InvalidPasswordHashError."""
        with pytest.raises(InvalidPasswordHashError):
            needs_rehash("not-a-hash")


class TestNeedsRehash:
    """needs_rehash detects hashes weaker than the current policy."""

    def test_false_for_current_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A hash made with current defaults does not need a rehash."""
        monkeypatch.setattr("kstlib.config.get_config", _raise_not_loaded)
        stored = hash_password("pw")
        assert needs_rehash(stored) is False

    def test_true_for_weaker_params(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A hash made with weaker params needs a rehash against defaults."""
        monkeypatch.setattr("kstlib.config.get_config", _raise_not_loaded)
        weaker = _fast_hash("pw")
        assert needs_rehash(weaker) is True


class TestResolveParams:
    """The kwargs > config > defaults cascade and floor clamping."""

    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With no kwargs and no config, code defaults apply."""
        monkeypatch.setattr("kstlib.config.get_config", _raise_not_loaded)
        params = passwords._resolve_params(
            time_cost=None, memory_cost=None, parallelism=None, hash_len=None, salt_len=None
        )
        actual = (
            params.time_cost,
            params.memory_cost,
            params.parallelism,
            params.hash_len,
            params.salt_len,
        )
        assert actual == (
            DEFAULT_TIME_COST,
            DEFAULT_MEMORY_COST,
            DEFAULT_PARALLELISM,
            DEFAULT_HASH_LEN,
            DEFAULT_SALT_LEN,
        )

    def test_kwargs_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit kwargs take priority over defaults."""
        monkeypatch.setattr("kstlib.config.get_config", _raise_not_loaded)
        params = passwords._resolve_params(time_cost=5, memory_cost=20000, parallelism=2, hash_len=24, salt_len=20)
        actual = (
            params.time_cost,
            params.memory_cost,
            params.parallelism,
            params.hash_len,
            params.salt_len,
        )
        assert actual == (5, 20000, 2, 24, 20)

    def test_config_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """kstlib config overrides defaults when no kwargs are given."""
        monkeypatch.setattr(
            "kstlib.config.get_config",
            lambda: {"secure": {"passwords": {"time_cost": 6, "memory_cost": 30000}}},
        )
        params = passwords._resolve_params(
            time_cost=None, memory_cost=None, parallelism=None, hash_len=None, salt_len=None
        )
        assert params.time_cost == 6
        assert params.memory_cost == 30000
        assert params.parallelism == DEFAULT_PARALLELISM

    def test_kwargs_beat_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """kwargs take priority over config values."""
        monkeypatch.setattr(
            "kstlib.config.get_config",
            lambda: {"secure": {"passwords": {"time_cost": 6}}},
        )
        params = passwords._resolve_params(
            time_cost=9, memory_cost=None, parallelism=None, hash_len=None, salt_len=None
        )
        assert params.time_cost == 9

    def test_invalid_config_type_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A non-integer config value falls back to the default."""
        monkeypatch.setattr(
            "kstlib.config.get_config",
            lambda: {"secure": {"passwords": {"time_cost": "bad"}}},
        )
        params = passwords._resolve_params(
            time_cost=None, memory_cost=None, parallelism=None, hash_len=None, salt_len=None
        )
        assert params.time_cost == DEFAULT_TIME_COST


class TestClamp:
    """Parameters below the security floor are clamped up with a warning."""

    def test_clamps_all_floors(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        """Every below-floor parameter is clamped and warned about."""
        monkeypatch.setattr("kstlib.config.get_config", _raise_not_loaded)
        with caplog.at_level("WARNING", logger="kstlib.secure.passwords"):
            params = passwords._resolve_params(time_cost=1, memory_cost=100, parallelism=0, hash_len=1, salt_len=2)
        actual = (
            params.time_cost,
            params.memory_cost,
            params.parallelism,
            params.hash_len,
            params.salt_len,
        )
        assert actual == (MIN_TIME_COST, MIN_MEMORY_COST, MIN_PARALLELISM, MIN_HASH_LEN, MIN_SALT_LEN)
        security = [r for r in caplog.records if "[SECURITY]" in r.getMessage()]
        assert len(security) == 5

    def test_no_clamp_no_warning(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        """Valid parameters above the floors emit no security warning."""
        monkeypatch.setattr("kstlib.config.get_config", _raise_not_loaded)
        with caplog.at_level("WARNING", logger="kstlib.secure.passwords"):
            passwords._resolve_params(time_cost=2, memory_cost=MIN_MEMORY_COST, parallelism=1, hash_len=16, salt_len=16)
        assert not [r for r in caplog.records if "[SECURITY]" in r.getMessage()]


class TestHashEmbedsParams:
    """The real argon2 backend embeds the resolved parameters in the PHC string."""

    def test_default_params(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default parameters appear in the encoded hash."""
        monkeypatch.setattr("kstlib.config.get_config", _raise_not_loaded)
        assert "m=65536,t=3,p=4" in hash_password("pw")

    def test_kwargs_params(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Override kwargs appear in the encoded hash."""
        monkeypatch.setattr("kstlib.config.get_config", _raise_not_loaded)
        stored = hash_password("pw", time_cost=4, memory_cost=MIN_MEMORY_COST, parallelism=1)
        assert "m=19456,t=4,p=1" in stored

    def test_clamped_params(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        """A below-floor kwarg is clamped before reaching the backend."""
        monkeypatch.setattr("kstlib.config.get_config", _raise_not_loaded)
        with caplog.at_level("WARNING", logger="kstlib.secure.passwords"):
            stored = hash_password("pw", time_cost=1, memory_cost=MIN_MEMORY_COST, parallelism=1)
        assert "m=19456,t=2,p=1" in stored
        assert [r for r in caplog.records if "[SECURITY]" in r.getMessage()]


class TestMaxLength:
    """Oversized passwords are rejected (anti-DoS hardening)."""

    def test_hash_rejects_too_long(self) -> None:
        """hash_password rejects a password over MAX_PASSWORD_LENGTH."""
        long_pw = "a" * (MAX_PASSWORD_LENGTH + 1)
        with pytest.raises(PasswordError, match="maximum length") as exc_info:
            hash_password(long_pw)
        assert long_pw not in str(exc_info.value)

    def test_verify_too_long_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """verify_password returns False (no raise) for an oversized candidate."""
        monkeypatch.setattr("kstlib.config.get_config", _raise_not_loaded)
        stored = _fast_hash("pw")
        assert verify_password("a" * (MAX_PASSWORD_LENGTH + 1), stored) is False


class TestImportGuard:
    """A clear error is raised when argon2-cffi is unavailable."""

    def test_hash_requires_argon2(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """hash_password raises a clear PasswordError when argon2 is missing."""
        monkeypatch.setattr(passwords, "_ARGON2_AVAILABLE", False)
        with pytest.raises(PasswordError, match="argon2-cffi"):
            hash_password("pw")

    def test_verify_requires_argon2(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """verify_password raises a clear PasswordError when argon2 is missing."""
        monkeypatch.setattr(passwords, "_ARGON2_AVAILABLE", False)
        with pytest.raises(PasswordError, match="argon2-cffi"):
            verify_password("pw", "$argon2id$dummy")

    def test_needs_rehash_requires_argon2(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """needs_rehash raises a clear PasswordError when argon2 is missing."""
        monkeypatch.setattr(passwords, "_ARGON2_AVAILABLE", False)
        with pytest.raises(PasswordError, match="argon2-cffi"):
            needs_rehash("$argon2id$dummy")


class TestInputTypes:
    """Non str/bytes passwords are rejected."""

    def test_hash_rejects_bad_type(self) -> None:
        """hash_password rejects a non str/bytes password."""
        with pytest.raises(PasswordError, match="str or bytes"):
            hash_password(12345)  # type: ignore[arg-type]

    def test_verify_rejects_bad_type(self) -> None:
        """verify_password rejects a non str/bytes password."""
        with pytest.raises(PasswordError, match="str or bytes"):
            verify_password(12345, "$argon2id$dummy")  # type: ignore[arg-type]


class TestLoadConfig:
    """The config loader degrades gracefully to an empty section."""

    def test_empty_when_not_loaded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A missing config yields an empty section."""
        monkeypatch.setattr("kstlib.config.get_config", _raise_not_loaded)
        assert passwords._load_password_config() == {}

    def test_empty_on_loader_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A loader failure yields an empty section."""

        def _boom() -> NoReturn:
            raise RuntimeError("corrupt config")

        monkeypatch.setattr("kstlib.config.get_config", _boom)
        assert passwords._load_password_config() == {}

    def test_empty_when_cfg_not_mapping(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A non-mapping config object yields an empty section."""
        monkeypatch.setattr("kstlib.config.get_config", lambda: 42)
        assert passwords._load_password_config() == {}

    def test_empty_when_secure_not_mapping(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A non-mapping secure section yields an empty section."""
        monkeypatch.setattr("kstlib.config.get_config", lambda: {"secure": 5})
        assert passwords._load_password_config() == {}

    def test_empty_when_section_not_mapping(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A non-mapping passwords section yields an empty section."""
        monkeypatch.setattr("kstlib.config.get_config", lambda: {"secure": {"passwords": 5}})
        assert passwords._load_password_config() == {}

    def test_returns_section(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A well-formed passwords section is returned as-is."""
        monkeypatch.setattr("kstlib.config.get_config", lambda: {"secure": {"passwords": {"time_cost": 7}}})
        assert passwords._load_password_config() == {"time_cost": 7}


class TestNoSecretLeak:
    """Passwords and hashes never appear in the logs."""

    def test_secrets_never_logged(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        """Neither the password nor the hash is written to any log record."""
        monkeypatch.setattr("kstlib.config.get_config", _raise_not_loaded)
        password = "topsecret-deadbeef-cafe"
        with caplog.at_level("DEBUG"):
            stored = hash_password(password, time_cost=1, memory_cost=MIN_MEMORY_COST, parallelism=1)
            assert verify_password(password, stored) is True
        assert password not in caplog.text
        assert stored not in caplog.text


class TestHashingError:
    """A backend HashingError is wrapped into PasswordError."""

    def test_hashing_error_wrapped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """hash_password wraps argon2 HashingError into PasswordError."""
        monkeypatch.setattr("kstlib.config.get_config", _raise_not_loaded)
        monkeypatch.setattr(passwords, "PasswordHasher", _BoomHasher)
        with pytest.raises(PasswordError, match="argon2 hashing failed"):
            hash_password("pw", time_cost=FAST_TIME, memory_cost=FAST_MEMORY, parallelism=FAST_PAR)


class TestPublicApi:
    """Public re-exports and exception hierarchy."""

    def test_reexported_from_secure(self) -> None:
        """The public symbols are re-exported from kstlib.secure."""
        import kstlib.secure as secure_pkg

        assert secure_pkg.hash_password is hash_password
        assert secure_pkg.verify_password is verify_password
        assert secure_pkg.needs_rehash is needs_rehash
        assert secure_pkg.PasswordError is PasswordError
        assert secure_pkg.InvalidPasswordHashError is InvalidPasswordHashError
        assert "hash_password" in secure_pkg.__all__

    def test_exception_hierarchy(self) -> None:
        """PasswordError and InvalidPasswordHashError have the expected bases."""
        assert issubclass(PasswordError, KstlibError)
        assert issubclass(PasswordError, RuntimeError)
        assert issubclass(InvalidPasswordHashError, PasswordError)

    def test_floors_not_above_defaults(self) -> None:
        """Security floors never exceed the defaults."""
        assert MIN_TIME_COST <= DEFAULT_TIME_COST
        assert MIN_MEMORY_COST <= DEFAULT_MEMORY_COST
        assert MIN_PARALLELISM <= DEFAULT_PARALLELISM
        assert MIN_HASH_LEN <= DEFAULT_HASH_LEN
        assert MIN_SALT_LEN <= DEFAULT_SALT_LEN
        assert MAX_PASSWORD_LENGTH > 0
