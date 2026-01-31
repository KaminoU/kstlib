"""Tests for the sensitive secrets context manager."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from kstlib.secrets import CachePurgeProtocol, SecretRecord, SecretSource, sensitive


class DummyProvider:
    """Provider stub capturing purge requests."""

    def __init__(self) -> None:
        self.calls: list[Path | str | None] = []

    def purge_cache(self, *, path: str | Path | None = None) -> None:
        """Record the purge call with the given path hint."""
        self.calls.append(path)


class LegacyProvider:
    """Provider stub with positional purge signature."""

    def __init__(self) -> None:
        self.invoked = False

    def purge_cache(self) -> None:
        """Mark that the legacy purge method was called."""
        self.invoked = True


class ValueErrorProvider:
    """Provider that raises during purge to exercise defensive logging."""

    def purge_cache(self, *, path: str | Path | None = None) -> None:  # pragma: no cover - executed via tests
        """Raise a ValueError to simulate a purge failure."""
        raise ValueError(f"cannot purge {path}")


class NonCallableProvider:
    """Provider-like object whose purge attribute is not callable."""

    purge_cache: str | None = None


def test_sensitive_scrubs_bytearray_payload() -> None:
    """Ensure bytearray secrets are zeroed out after use."""
    buffer = bytearray(b"super-secret")
    record = SecretRecord(value=buffer, source=SecretSource.SOPS, metadata={})

    with sensitive(record) as secret:
        assert secret is buffer
        assert secret.startswith(b"super")

    assert record.value is None
    assert all(byte == 0 for byte in buffer)


def test_sensitive_clears_string_reference() -> None:
    """Ensure string secrets are cleared from the record after use."""
    record = SecretRecord(value="super-secret", source=SecretSource.KEYRING, metadata={})

    with sensitive(record) as secret:
        assert secret == "super-secret"

    assert record.value is None


def test_sensitive_purges_provider_cache_with_path_hint() -> None:
    """Ensure provider cache purge is called with path hint from metadata."""
    provider = DummyProvider()
    secret_path = Path("secrets.enc.yaml")
    record = SecretRecord(value="token", source=SecretSource.SOPS, metadata={"path": secret_path})

    with sensitive(record, providers=[cast(CachePurgeProtocol, provider)]):
        pass

    assert provider.calls == [secret_path]


def test_sensitive_calls_legacy_purge_signature() -> None:
    """Ensure legacy provider purge signature is supported."""
    legacy_provider = LegacyProvider()
    record = SecretRecord(value="token", source=SecretSource.SOPS, metadata={})

    with sensitive(record, providers=[cast(CachePurgeProtocol, legacy_provider)]):
        pass

    assert legacy_provider.invoked


def test_sensitive_scrubs_memoryview_payload() -> None:
    """Ensure memoryview buffers are zeroed and released."""
    buffer = bytearray(b"secret")
    view = memoryview(buffer)
    record = SecretRecord(value=view, source=SecretSource.SOPS, metadata={})

    with sensitive(record) as secret:
        assert secret is view

    assert record.value is None
    assert all(byte == 0 for byte in buffer)


def test_sensitive_scrubs_mutable_sequence_payload() -> None:
    """Ensure mutable sequences with clear/__setitem__ are scrubbed."""

    class MutableSequence:
        """A simple mutable sequence supporting __setitem__ and clear()."""

        def __init__(self) -> None:
            self.data = [1, 2, 3]

        def __len__(self) -> int:
            return len(self.data)

        def __setitem__(self, index: int, value: Any) -> None:
            self.data[index] = value

        def clear(self) -> None:
            """Clear all items from the sequence."""
            self.data.clear()

    sequence = MutableSequence()
    record = SecretRecord(value=sequence, source=SecretSource.KEYRING, metadata={})

    with sensitive(record):
        pass

    assert record.value is None
    assert not sequence.data


def test_sensitive_skips_non_callable_purge_attribute() -> None:
    """Ensure provider entries without callable purge attributes are ignored."""
    provider = cast(CachePurgeProtocol, NonCallableProvider())
    record = SecretRecord(value="token", source=SecretSource.SOPS, metadata={})

    with sensitive(record, providers=[provider]):
        pass


def test_sensitive_logs_provider_errors(caplog: pytest.LogCaptureFixture) -> None:
    """Ensure provider purge failures are logged without raising."""
    provider = ValueErrorProvider()
    record = SecretRecord(value="token", source=SecretSource.SOPS, metadata={"path": Path("secret.yml")})

    with caplog.at_level("DEBUG"), sensitive(record, providers=[cast(CachePurgeProtocol, provider)]):
        pass

    assert "Provider cache purge failed" in caplog.text


def test_sensitive_handles_none_value() -> None:
    """Ensure secrets set to None do not trigger scrubbing work."""

    record = SecretRecord(value=None, source=SecretSource.KWARGS, metadata={})

    with sensitive(record):
        pass

    assert record.value is None


def test_sensitive_scrubs_partial_sequences() -> None:
    """Ensure fallback assignments run when integer writes fail."""

    class PartiallyMutable:
        """Sequence rejecting integer assignments but accepting None."""

        def __init__(self) -> None:
            self.data = ["secret"]
            self.assignments: list[Any] = []

        def __len__(self) -> int:
            return len(self.data)

        def __setitem__(self, index: int, value: Any) -> None:
            if isinstance(value, int):
                raise ValueError("reject ints")
            self.assignments.append((index, value))

        def clear(self) -> None:
            """Clear all items from the sequence."""
            self.assignments.append("cleared")
            self.data.clear()

    buffer = PartiallyMutable()
    record = SecretRecord(value=buffer, source=SecretSource.SOPS, metadata={})

    with sensitive(record):
        pass

    assert (0, None) in buffer.assignments
    assert "cleared" in buffer.assignments
    assert record.value is None
