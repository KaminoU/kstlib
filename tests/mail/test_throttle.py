"""Unit tests for kstlib.mail.throttle (25 scenarios).

Coverage targets:

- Modes (raise / warn / default-when-not-specified)
- Token bucket refill behavior
- Cascade resolution (preset > mail > defaults)
- Kwarg overrides (False, dict, None)
- Singleton per preset
- Hard limit rejections
- Builder integration (.send and @notify, including strict count contract)
- Logging instrumentation (DEBUG cascade + WARNING [SECURITY])

"""

from __future__ import annotations

import logging
from email.message import EmailMessage
from typing import TYPE_CHECKING, Any

import pytest
from box import Box

from kstlib.limits import (
    DEFAULT_MAIL_THROTTLE_PER,
    DEFAULT_MAIL_THROTTLE_RATE,
    HARD_MAX_THROTTLE_PER,
    HARD_MAX_THROTTLE_RATE,
)
from kstlib.mail import MailBuilder, MailConfigurationError, MailThrottle, MailThrottledError
from kstlib.mail.throttle import (
    _reset_registry,
    get_or_create_throttle,
)
from kstlib.mail.transport import MailTransport

if TYPE_CHECKING:
    from collections.abc import Callable


class _StubTransport(MailTransport):
    """Minimal MailTransport double that records sent messages."""

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        """Record the message instead of sending it."""
        self.sent.append(message)


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    """Reset the singleton throttle registry before each test."""
    _reset_registry()


@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> Callable[[float], None]:
    """Replace ``time.monotonic`` in the rate limiter with a controllable clock.

    The rate_limiter module's name collides with the ``rate_limiter``
    function re-exported from ``kstlib.resilience.__init__``, so we use
    ``importlib`` to obtain the actual module object rather than relying
    on attribute lookup.
    """
    import importlib
    import time as _real_time
    import types

    rl_mod = importlib.import_module("kstlib.resilience.rate_limiter")

    current = [0.0]

    def fake_monotonic() -> float:
        return current[0]

    fake_time = types.SimpleNamespace(
        monotonic=fake_monotonic,
        sleep=_real_time.sleep,
    )
    monkeypatch.setattr(rl_mod, "time", fake_time)

    def advance(seconds: float) -> None:
        current[0] += seconds

    return advance


def _mock_throttle_section(
    monkeypatch: pytest.MonkeyPatch,
    *,
    mail_throttle: dict[str, Any] | None = None,
    presets: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Patch ``_load_mail_section`` in the throttle module."""
    import kstlib.mail.throttle as throttle_mod

    section: dict[str, Any] = {}
    if mail_throttle is not None:
        section["throttle"] = mail_throttle
    if presets is not None:
        section["presets"] = presets

    box_section = Box(section, default_box=True, default_box_attr=None) if section else None

    def fake_loader(*, silent: bool = False) -> Any:
        # silent is accepted for signature compatibility with the real
        # _load_mail_section helper but ignored: tests deterministically
        # return the patched section.
        del silent
        return box_section

    monkeypatch.setattr(throttle_mod, "_load_mail_section", fake_loader)


def _mock_builder_preset_resolution(monkeypatch: pytest.MonkeyPatch, transport: MailTransport) -> None:
    """Patch the builder so that ``preset=`` resolves to the given stub transport."""
    import kstlib.mail.builder as builder_mod

    monkeypatch.setattr(builder_mod, "_build_transport_from_preset", lambda _name: transport)
    monkeypatch.setattr(builder_mod, "_load_preset_envelope_defaults", lambda _name: {})


def _make_ready_builder(builder: MailBuilder) -> MailBuilder:
    """Pre-populate envelope and body so that ``.send()`` succeeds."""
    return builder.sender("a@example.com").to("b@example.com").subject("S").message("body")


# ---------------------------------------------------------------------------
# T1-T3: on_exceed modes
# ---------------------------------------------------------------------------


class TestModes:
    """Behavior of each on_exceed mode (raise, warn, default=raise)."""

    def test_raise_mode_blocks_after_quota(self) -> None:
        """T1: rate=10/per=60 raises MailThrottledError on the 11th consume."""
        throttle = MailThrottle(rate=10, per=60.0, on_exceed="raise")
        for _ in range(10):
            assert throttle.consume("daily") is True
        with pytest.raises(MailThrottledError) as exc:
            throttle.consume("daily")
        assert "10" in str(exc.value)
        assert "60.0" in str(exc.value)

    def test_warn_mode_returns_false_after_quota(self, caplog: pytest.LogCaptureFixture) -> None:
        """T2: warn mode returns False on overflow and emits WARNING [SECURITY]."""
        throttle = MailThrottle(rate=2, per=60.0, on_exceed="warn")
        assert throttle.consume("ok") is True
        assert throttle.consume("ok") is True
        with caplog.at_level(logging.WARNING, logger="kstlib.mail.throttle"):
            assert throttle.consume("over") is False
        assert any("[SECURITY]" in rec.getMessage() for rec in caplog.records)
        assert any("mode=warn" in rec.getMessage() for rec in caplog.records)

    def test_default_on_exceed_is_raise(self) -> None:
        """T3: omitting on_exceed uses the code default (``raise``)."""
        throttle = MailThrottle(rate=1, per=60.0)
        assert throttle.consume() is True
        with pytest.raises(MailThrottledError):
            throttle.consume()
        assert throttle.on_exceed == "raise"


# ---------------------------------------------------------------------------
# T4: Token bucket refill
# ---------------------------------------------------------------------------


class TestRefill:
    """Token bucket replenishes after the configured period."""

    def test_bucket_refills_after_period(self, fake_clock: Callable[[float], None]) -> None:
        """T4: after ``per`` seconds, the bucket is back to full capacity."""
        throttle = MailThrottle(rate=2, per=1.0, on_exceed="raise")
        assert throttle.consume() is True
        assert throttle.consume() is True
        # Bucket is empty
        with pytest.raises(MailThrottledError):
            throttle.consume()
        # Advance past the full period
        fake_clock(1.5)
        # Bucket fully refilled, capped at rate=2
        assert throttle.consume() is True
        assert throttle.consume() is True
        with pytest.raises(MailThrottledError):
            throttle.consume()


# ---------------------------------------------------------------------------
# T5-T7: Cascade resolution (preset > mail > defaults)
# ---------------------------------------------------------------------------


class TestCascade:
    """Each key cascades independently across preset / mail / defaults."""

    def test_preset_throttle_wins_over_mail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """T5: preset.throttle.rate=5 overrides mail.throttle.rate=20."""
        _mock_throttle_section(
            monkeypatch,
            mail_throttle={"rate": 20, "per": 60.0},
            presets={"corporate": {"throttle": {"rate": 5}}},
        )
        throttle = get_or_create_throttle("corporate", None)
        assert throttle is not None
        assert throttle.rate == 5

    def test_mail_throttle_used_when_preset_has_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """T6: preset without throttle falls back to mail.throttle."""
        _mock_throttle_section(
            monkeypatch,
            mail_throttle={"rate": 20, "per": 60.0},
            presets={"corporate": {}},
        )
        throttle = get_or_create_throttle("corporate", None)
        assert throttle is not None
        assert throttle.rate == 20

    def test_defaults_when_no_yaml(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """T7: empty mail config produces the code defaults."""
        _mock_throttle_section(monkeypatch)
        throttle = get_or_create_throttle("corporate", None)
        assert throttle is not None
        assert throttle.rate == DEFAULT_MAIL_THROTTLE_RATE
        assert throttle.per == DEFAULT_MAIL_THROTTLE_PER
        assert throttle.on_exceed == "raise"


# ---------------------------------------------------------------------------
# T8-T9: Kwarg overrides
# ---------------------------------------------------------------------------


class TestKwargOverride:
    """``MailBuilder(throttle=...)`` precedence over the cascade."""

    def test_throttle_false_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """T8: ``throttle=False`` returns None even with strict YAML config."""
        _mock_throttle_section(monkeypatch, mail_throttle={"rate": 1, "per": 60.0})
        assert get_or_create_throttle("corporate", False) is None

    def test_throttle_dict_custom(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """T9: ``throttle=dict`` builds a per-instance MailThrottle."""
        _mock_throttle_section(monkeypatch, mail_throttle={"rate": 5, "per": 60.0})
        throttle = get_or_create_throttle("corporate", {"rate": 100, "per": 3600.0, "on_exceed": "warn"})
        assert throttle is not None
        assert throttle.rate == 100
        assert throttle.per == 3600.0
        assert throttle.on_exceed == "warn"


# ---------------------------------------------------------------------------
# T10: Singleton per preset
# ---------------------------------------------------------------------------


class TestSingleton:
    """A single MailThrottle is reused across builders of the same preset."""

    def test_singleton_per_preset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """T10: two get_or_create_throttle("X", None) return the same instance."""
        _mock_throttle_section(monkeypatch, mail_throttle={"rate": 5, "per": 60.0})
        first = get_or_create_throttle("corporate", None)
        second = get_or_create_throttle("corporate", None)
        assert first is second


# ---------------------------------------------------------------------------
# T11-T17: Hard limit / config error rejections
# ---------------------------------------------------------------------------


class TestHardLimits:
    """The constructor rejects out-of-bounds and ill-typed parameters."""

    def test_rate_zero_rejected(self) -> None:
        """T11: rate=0 raises MailConfigurationError."""
        with pytest.raises(MailConfigurationError, match="rate must be >="):
            MailThrottle(rate=0, per=60.0)

    def test_rate_negative_rejected(self) -> None:
        """T12: rate=-5 raises MailConfigurationError."""
        with pytest.raises(MailConfigurationError, match="rate must be >="):
            MailThrottle(rate=-5, per=60.0)

    def test_rate_above_hard_max_rejected(self) -> None:
        """T13: rate above HARD_MAX raises MailConfigurationError."""
        with pytest.raises(MailConfigurationError, match="exceeds HARD_MAX"):
            MailThrottle(rate=HARD_MAX_THROTTLE_RATE + 1, per=60.0)

    def test_per_below_hard_min_rejected(self) -> None:
        """T14: per=0.5 (below HARD_MIN=1.0) raises MailConfigurationError."""
        with pytest.raises(MailConfigurationError, match="per must be >="):
            MailThrottle(rate=10, per=0.5)

    def test_per_above_hard_max_rejected(self) -> None:
        """T15: per above HARD_MAX raises MailConfigurationError."""
        with pytest.raises(MailConfigurationError, match="exceeds HARD_MAX"):
            MailThrottle(rate=10, per=HARD_MAX_THROTTLE_PER + 1)

    def test_on_exceed_invalid_rejected(self) -> None:
        """T16: on_exceed='invalid' raises MailConfigurationError."""
        with pytest.raises(MailConfigurationError, match="on_exceed must be one of"):
            MailThrottle(rate=10, per=60.0, on_exceed="invalid")  # type: ignore[arg-type]

    def test_rate_non_int_rejected(self) -> None:
        """T17: rate='abc' (not int) raises MailConfigurationError."""
        with pytest.raises(MailConfigurationError, match="rate must be int"):
            MailThrottle(rate="abc", per=60.0)  # type: ignore[arg-type]

    def test_per_non_numeric_rejected(self) -> None:
        """T27: per='abc' (not int/float) raises MailConfigurationError.

        Covers throttle.py:175-176 (the type guard branch in _validate_per).
        """
        with pytest.raises(MailConfigurationError, match="per must be int or float"):
            MailThrottle(rate=10, per="abc")  # type: ignore[arg-type]


class TestSanitizeSubject:
    """Direct tests on the private subject sanitizer (log injection hardening)."""

    def test_null_byte_subject_is_replaced(self) -> None:
        """T28: a subject containing a null byte returns the placeholder.

        Covers throttle.py:247. Uses the private staticmethod directly to
        validate the internal invariant, hence the SLF001 suppression.
        """
        result = MailThrottle._sanitize_subject("danger\x00here")  # noqa: SLF001  # reason: testing internal sanitizer invariant directly
        assert result == "<subject contains null byte>"

    def test_long_subject_is_truncated(self) -> None:
        """T29: a subject longer than 80 chars is truncated to '...' tail.

        Covers throttle.py:249. Same SLF001 caveat as T28.
        """
        long_subject = "a" * 100
        result = MailThrottle._sanitize_subject(long_subject)  # noqa: SLF001  # reason: testing internal sanitizer invariant directly
        assert result.endswith("...")
        assert len(result) == 83  # 80 + len("...")


# ---------------------------------------------------------------------------
# T18-T21: MailBuilder integration
# ---------------------------------------------------------------------------


class TestBuilderIntegration:
    """End-to-end through MailBuilder.send and @notify."""

    def test_send_blocks_after_rate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """T18: 21 sends with rate=20 -> 20 OK then MailThrottledError."""
        stub = _StubTransport()
        _mock_builder_preset_resolution(monkeypatch, stub)
        _mock_throttle_section(monkeypatch, mail_throttle={"rate": 20, "per": 60.0})
        for _ in range(20):
            mail = _make_ready_builder(MailBuilder(preset="corporate"))
            mail.send()
        with pytest.raises(MailThrottledError):
            mail = _make_ready_builder(MailBuilder(preset="corporate"))
            mail.send()
        assert len(stub.sent) == 20

    def test_notify_decorator_throttled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """T19: @notify on a function called 21 times -> 20 mails sent, 21st throttled (warn)."""
        stub = _StubTransport()
        _mock_builder_preset_resolution(monkeypatch, stub)
        _mock_throttle_section(
            monkeypatch,
            mail_throttle={"rate": 20, "per": 60.0, "on_exceed": "warn"},
        )
        mail = MailBuilder(preset="corporate").sender("a@x.com").to("b@x.com").subject("S")

        @mail.notify
        def step(i: int) -> int:
            return i

        for i in range(21):
            step(i)
        # Only 20 mails actually sent through the transport
        assert len(stub.sent) == 20

    def test_backward_compat_no_throttle_section(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """T20: a preset without ``throttle:`` still gets the code defaults (Changed in 2.7.0)."""
        stub = _StubTransport()
        _mock_builder_preset_resolution(monkeypatch, stub)
        _mock_throttle_section(monkeypatch, presets={"corporate": {}})
        mail = MailBuilder(preset="corporate")
        assert mail._throttle is not None
        assert mail._throttle.rate == DEFAULT_MAIL_THROTTLE_RATE

    def test_yaml_disable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """T21: ``mail.throttle.enabled: false`` disables the throttle entirely."""
        stub = _StubTransport()
        _mock_builder_preset_resolution(monkeypatch, stub)
        _mock_throttle_section(monkeypatch, mail_throttle={"enabled": False, "rate": 5, "per": 60.0})
        mail = MailBuilder(preset="corporate")
        assert mail._throttle is None

    def test_init_is_kwargs_only(self) -> None:
        """T26: positional MailThrottle(20, 60.0) raises TypeError post-M5.

        Locks the kwargs-only contract on the constructor signature so a
        future positional reordering cannot silently break callers.
        """
        with pytest.raises(TypeError):
            MailThrottle(20, 60.0)  # type: ignore[misc]

    def test_notify_in_loop_with_throttle_warn_strict_count(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """T25: ``@notify`` in a 5-call loop with throttle warn rate=3 -> 5 returns, 3 sends.

        Locks the exact contract that the decorated function ALWAYS runs to
        completion (returning its value), regardless of whether the post-run
        notification mail is dropped by the throttle. Complements T19 which
        only checks the send count.
        """
        stub = _StubTransport()
        _mock_builder_preset_resolution(monkeypatch, stub)
        _mock_throttle_section(
            monkeypatch,
            mail_throttle={"rate": 3, "per": 60.0, "on_exceed": "warn"},
        )
        mail = MailBuilder(preset="corporate").sender("a@x.com").to("b@x.com").subject("S")

        @mail.notify
        def step(i: int) -> int:
            return i * 2

        results = [step(i) for i in range(5)]
        assert results == [0, 2, 4, 6, 8], "decorated function must run all 5 times"
        assert len(stub.sent) == 3, f"throttle rate=3 violated: {len(stub.sent)} sends"


# ---------------------------------------------------------------------------
# T22-T24: Logging instrumentation (mandatory, code-rules.md s10)
# ---------------------------------------------------------------------------


class TestLogging:
    """Required log coverage for the throttle (cascade DEBUG + [SECURITY] WARNING)."""

    def test_debug_cascade_resolved_logged(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """T22: a DEBUG line is emitted at builder init with the source level."""
        stub = _StubTransport()
        _mock_builder_preset_resolution(monkeypatch, stub)
        _mock_throttle_section(
            monkeypatch,
            mail_throttle={"rate": 20, "per": 60.0},
            presets={"corporate": {"throttle": {"rate": 5}}},
        )
        with caplog.at_level(logging.DEBUG, logger="kstlib.mail.throttle"):
            MailBuilder(preset="corporate")
        debug_messages = [rec.getMessage() for rec in caplog.records if rec.levelno == logging.DEBUG]
        assert any("Mail throttle resolved" in m and "source=preset" in m for m in debug_messages)

    def test_warning_security_on_raise_mode(self, caplog: pytest.LogCaptureFixture) -> None:
        """T23: in raise mode, a WARNING [SECURITY] log precedes each MailThrottledError."""
        throttle = MailThrottle(rate=1, per=60.0, on_exceed="raise")
        assert throttle.consume("ok") is True
        with caplog.at_level(logging.WARNING, logger="kstlib.mail.throttle"):
            with pytest.raises(MailThrottledError):
                throttle.consume("blocked")
        warnings = [rec for rec in caplog.records if rec.levelno == logging.WARNING]
        assert len(warnings) == 1
        msg = warnings[0].getMessage()
        assert "[SECURITY]" in msg
        assert "Raising MailThrottledError" in msg

    def test_warning_security_on_warn_mode(self, caplog: pytest.LogCaptureFixture) -> None:
        """T24: in warn mode, a WARNING [SECURITY] log fires once per blocked send (no exception)."""
        throttle = MailThrottle(rate=1, per=60.0, on_exceed="warn")
        assert throttle.consume("ok") is True
        with caplog.at_level(logging.WARNING, logger="kstlib.mail.throttle"):
            assert throttle.consume("blocked") is False
        warnings = [rec for rec in caplog.records if rec.levelno == logging.WARNING]
        assert len(warnings) == 1
        msg = warnings[0].getMessage()
        assert "[SECURITY]" in msg
        assert "mode=warn" in msg

    def test_dict_enabled_false_emits_debug_log(self, caplog: pytest.LogCaptureFixture) -> None:
        """T30: kwarg dict ``{"enabled": False}`` emits a DEBUG log and returns None.

        Covers throttle.py:311-315 (the early-return debug log branch in
        ``_build_from_dict``).
        """
        with caplog.at_level(logging.DEBUG, logger="kstlib.mail.throttle"):
            throttle = get_or_create_throttle("corporate", {"enabled": False, "rate": 5})
        assert throttle is None
        debug_messages = [rec.getMessage() for rec in caplog.records if rec.levelno == logging.DEBUG]
        assert any("Mail throttle disabled" in m and "dict enabled=false" in m for m in debug_messages)


class TestYAMLEdgeCases:
    """Coverage for defensive YAML branches in the cascade resolver."""

    def test_preset_cfg_scalar_falls_back_silently(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """T31: a malformed YAML preset (scalar instead of dict) is ignored.

        Covers throttle.py:441 (the ``not hasattr(preset_cfg, 'get')`` defensive
        branch in ``_read_preset_throttle``). A user who writes
        ``mail.presets.corporate: "smtp"`` (a scalar) instead of a dict must not
        crash the throttle resolver; the cascade simply skips the preset level
        and falls through to the mail-level / defaults.
        """
        # Build a Box where presets.corporate is a string scalar, not a dict.
        # The cascade must skip it and use mail.throttle.rate=7.
        section: dict[str, Any] = {
            "throttle": {"rate": 7, "per": 60.0, "on_exceed": "warn"},
            "presets": {"corporate": "scalar-not-a-dict"},
        }
        box_section = Box(section, default_box=True, default_box_attr=None)
        import kstlib.mail.throttle as throttle_mod

        def fake_loader(*, silent: bool = False) -> Any:
            del silent
            return box_section

        monkeypatch.setattr(throttle_mod, "_load_mail_section", fake_loader)
        throttle = get_or_create_throttle("corporate", None)
        assert throttle is not None
        assert throttle.rate == 7  # mail-level kicks in, preset scalar ignored

    def test_preset_yaml_unknown_key_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """T32: YAML preset throttle with unknown key raises with source='preset'.

        Covers throttle.py:486-489 (the source != 'kwarg' branch of
        ``_reject_unknown_throttle_keys``). Test 27 already covers the
        kwarg path; this test exercises the YAML preset path.
        """
        _mock_throttle_section(
            monkeypatch,
            mail_throttle={"rate": 20, "per": 60.0},
            presets={"corporate": {"throttle": {"rate": 5, "WHATEVER": "hack"}}},
        )
        with pytest.raises(MailConfigurationError) as exc:
            get_or_create_throttle("corporate", None)
        msg = str(exc.value)
        assert "preset" in msg
        assert "WHATEVER" in msg
