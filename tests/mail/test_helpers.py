"""Tests for kstlib.mail._helpers (silent-path coverage).

The helper :func:`_load_mail_section` exposes two distinct contracts:

- ``silent=False`` (used by :mod:`kstlib.mail.builder`): wrap every
  loader failure in :class:`MailConfigurationError`.
- ``silent=True`` (used by :mod:`kstlib.mail.throttle` kill switch):
  narrow catch returns ``None`` for "config not loaded" errors,
  propagates real corruption raw to surface the bug at init.

These tests cover the silent-path branches and the non-silent narrow
"not loaded" message branch that the builder-centric tests in
test_builder_config.py do not exercise.
"""

from __future__ import annotations

from typing import Any

import pytest

from kstlib.mail import MailConfigurationError


class TestSilentPaths:
    """Silent kill-switch branches of ``_load_mail_section``."""

    def test_silent_returns_none_on_config_not_loaded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """silent=True + ConfigNotLoadedError returns None (kill-switch fail-safe)."""
        import kstlib.config as config_mod
        from kstlib.config.exceptions import ConfigNotLoadedError

        def explode(*_a: Any, **_kw: Any) -> Any:
            raise ConfigNotLoadedError("config not yet initialized")

        monkeypatch.setattr(config_mod, "get_config", explode)

        from kstlib.mail._helpers import _load_mail_section

        assert _load_mail_section(silent=True) is None

    def test_silent_returns_none_on_mail_configuration_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """silent=True + MailConfigurationError returns None (narrow catch asymmetry)."""
        import kstlib.config as config_mod

        def explode(*_a: Any, **_kw: Any) -> Any:
            raise MailConfigurationError("mail subsystem error")

        monkeypatch.setattr(config_mod, "get_config", explode)

        from kstlib.mail._helpers import _load_mail_section

        assert _load_mail_section(silent=True) is None

    def test_silent_propagates_real_corruption(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """silent=True + RuntimeError propagates raw to surface bug at init."""
        import kstlib.config as config_mod

        def explode(*_a: Any, **_kw: Any) -> Any:
            raise RuntimeError("yaml corrupted")

        monkeypatch.setattr(config_mod, "get_config", explode)

        from kstlib.mail._helpers import _load_mail_section

        with pytest.raises(RuntimeError, match="yaml corrupted"):
            _load_mail_section(silent=True)


class TestNonSilentNarrowMessage:
    """Non-silent branch of the narrow "not loaded" catch."""

    def test_raises_not_loaded_on_config_not_loaded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """silent=False + ConfigNotLoadedError raises MailConfigurationError with 'not loaded' message."""
        import kstlib.config as config_mod
        from kstlib.config.exceptions import ConfigNotLoadedError

        def explode(*_a: Any, **_kw: Any) -> Any:
            raise ConfigNotLoadedError("never called load_config")

        monkeypatch.setattr(config_mod, "get_config", explode)

        from kstlib.mail._helpers import _load_mail_section

        with pytest.raises(MailConfigurationError, match="not loaded"):
            _load_mail_section()
