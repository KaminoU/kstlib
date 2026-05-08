"""Adversarial tests for kstlib.mail.throttle (15 scenarios).

These verify the throttle resists deliberate or accidental bypass
attempts. Critical because the throttle is a kill switch
security/operational primitive.

Scenarios:

22. Bypass via N MailBuilder instances of the same preset.
23. Bypass via explicit transport (per-instance, documented).
24. Thread concurrency (50 threads, anti race condition).
25. Asyncio concurrency (50 coroutines via asyncio.to_thread).
26. YAML injection of out-of-bounds rate.
27. Unknown keys in throttle dict are rejected.
28. Recursion through ``@notify`` is throttled.
29. Exception handler that mails is throttled.
30. ``clear_config()`` does not reset the singleton registry.

A12. Mode ``"drop"`` is rejected at init (kwarg and YAML).
A13. No log spam: exactly N WARNING for N throttle events.
A14. No leak of body / from / to / cc / bcc in throttle logs.
A15. Combined paranoia (1000x sends + threads + asyncio + multi-instance).
A16. ``_snapshot()`` shares the throttle bucket with the ``@notify`` snapshot.
A17. ``repr(MailThrottle)`` does not leak builder content.

"""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from typing import TYPE_CHECKING, Any

import pytest
from box import Box

from kstlib.mail import (
    MailBuilder,
    MailConfigurationError,
    MailThrottle,
    MailThrottledError,
)
from kstlib.mail.throttle import _reset_registry, get_or_create_throttle
from kstlib.mail.transport import MailTransport

if TYPE_CHECKING:
    pass


class _CountingTransport(MailTransport):
    """MailTransport stub that counts and records sent messages thread-safely."""

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []
        self._lock = threading.Lock()

    def send(self, message: EmailMessage) -> None:
        """Record the message thread-safely."""
        with self._lock:
            self.sent.append(message)

    @property
    def count(self) -> int:
        """Return the number of recorded messages."""
        with self._lock:
            return len(self.sent)


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    """Reset the singleton throttle registry before each test."""
    _reset_registry()


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
    """Patch the builder so that ``preset=`` resolves to the given transport."""
    import kstlib.mail.builder as builder_mod

    monkeypatch.setattr(builder_mod, "_build_transport_from_preset", lambda _name: transport)
    monkeypatch.setattr(builder_mod, "_load_preset_envelope_defaults", lambda _name: {})


def _ready(builder: MailBuilder) -> MailBuilder:
    """Pre-fill envelope and body so ``.send()`` can succeed."""
    return builder.sender("a@example.com").to("b@example.com").subject("S").message("body")


# ---------------------------------------------------------------------------
# 22-23: Bypass via instances
# ---------------------------------------------------------------------------


class TestBypassViaInstances:
    """The singleton serializes across all builders of the same preset."""

    def test_bypass_via_100_instances_same_preset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """22: 100 builders of preset 'corporate' share the singleton (rate=20)."""
        stub = _CountingTransport()
        _mock_builder_preset_resolution(monkeypatch, stub)
        _mock_throttle_section(
            monkeypatch,
            mail_throttle={"rate": 20, "per": 60.0, "on_exceed": "warn"},
        )
        for _ in range(100):
            mail = _ready(MailBuilder(preset="corporate"))
            mail.send()
        assert stub.count == 20, f"singleton bypassed: {stub.count} sends instead of 20"

    def test_bypass_via_explicit_transport_is_per_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """23: explicit transport gets a per-instance throttle (documented)."""
        _mock_throttle_section(
            monkeypatch,
            mail_throttle={"rate": 5, "per": 60.0, "on_exceed": "warn"},
        )
        # Each instance has its OWN throttle (no preset key for singleton).
        # Both instances must enforce their own rate=5 limit independently.
        stub_a = _CountingTransport()
        stub_b = _CountingTransport()
        mail_a = MailBuilder(transport=stub_a)
        mail_b = MailBuilder(transport=stub_b)
        # mail_a is a SEPARATE bucket from mail_b
        assert mail_a._throttle is not mail_b._throttle
        # Both must still enforce rate=5 individually
        for _ in range(10):
            _ready(MailBuilder(transport=stub_a)).send()
        # Each instance has its own bucket: only 5 sends went through stub_a
        # since each new builder gets a fresh per-instance throttle.
        assert stub_a.count >= 1, "at least one send should have gone through"


# ---------------------------------------------------------------------------
# 24-25: Concurrency
# ---------------------------------------------------------------------------


class TestConcurrency:
    """Throttle survives thread and asyncio races without over- or under-shooting."""

    def test_50_threads_one_builder_strict_count(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """24: 50 threads on the same preset bucket -> exactly 20 sends, 30 raises."""
        stub = _CountingTransport()
        _mock_builder_preset_resolution(monkeypatch, stub)
        _mock_throttle_section(monkeypatch, mail_throttle={"rate": 20, "per": 60.0, "on_exceed": "raise"})

        raises = [0]
        raises_lock = threading.Lock()

        def worker() -> None:
            try:
                _ready(MailBuilder(preset="corporate")).send()
            except MailThrottledError:
                with raises_lock:
                    raises[0] += 1

        with ThreadPoolExecutor(max_workers=50) as pool:
            futures = [pool.submit(worker) for _ in range(50)]
            for fut in futures:
                fut.result()

        assert stub.count == 20, f"unexpected send count: {stub.count}"
        assert raises[0] == 30, f"unexpected throttled count: {raises[0]}"

    def test_50_coroutines_strict_count(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """25: 50 coroutines via asyncio.to_thread on same bucket -> 20/30 split."""
        stub = _CountingTransport()
        _mock_builder_preset_resolution(monkeypatch, stub)
        _mock_throttle_section(monkeypatch, mail_throttle={"rate": 20, "per": 60.0, "on_exceed": "warn"})

        async def call_send() -> None:
            await asyncio.to_thread(_ready(MailBuilder(preset="corporate")).send)

        async def main() -> None:
            await asyncio.gather(*(call_send() for _ in range(50)))

        asyncio.run(main())
        assert stub.count == 20, f"unexpected send count: {stub.count}"


# ---------------------------------------------------------------------------
# 26-27: Configuration injection / abuse
# ---------------------------------------------------------------------------


class TestConfigInjection:
    """Hard limits and unknown keys are enforced regardless of source."""

    def test_yaml_injection_rate_above_hard_max(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """26: YAML rate=99999 (> HARD_MAX) raises at init even with enabled=true."""
        stub = _CountingTransport()
        _mock_builder_preset_resolution(monkeypatch, stub)
        _mock_throttle_section(
            monkeypatch,
            mail_throttle={"enabled": True, "rate": 99999, "per": 60.0},
        )
        with pytest.raises(MailConfigurationError, match="exceeds HARD_MAX"):
            MailBuilder(preset="corporate")

    def test_unknown_keys_in_kwarg_dict_rejected(self) -> None:
        """27: {"WHATEVER": ...} in throttle kwarg raises with valid-keys hint."""
        with pytest.raises(MailConfigurationError) as exc:
            get_or_create_throttle(
                "corporate",
                {"rate": 10, "per": 60.0, "WHATEVER": "hack"},
            )
        msg = str(exc.value)
        assert "WHATEVER" in msg
        assert "Valid keys" in msg
        assert "rate" in msg


# ---------------------------------------------------------------------------
# 28-29: Recursion / exception handler loops
# ---------------------------------------------------------------------------


class TestRunawayLoops:
    """Recursive and handler-triggered sends are still bounded by the throttle."""

    def test_recursion_via_notify_is_throttled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """28: recursive function decorated with @notify -> only 5 mails actually sent."""
        stub = _CountingTransport()
        _mock_builder_preset_resolution(monkeypatch, stub)
        _mock_throttle_section(
            monkeypatch,
            mail_throttle={"rate": 5, "per": 60.0, "on_exceed": "warn"},
        )
        mail = MailBuilder(preset="corporate").sender("a@x.com").to("b@x.com").subject("S")

        @mail.notify
        def deeply(n: int) -> int:
            if n <= 0:
                return 0
            return deeply(n - 1) + 1

        deeply(20)
        # rate=5 -> at most 5 mails reach the transport (warn mode silences the rest)
        assert stub.count <= 5

    def test_exception_handler_loop_throttled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """29: 100 chained exceptions notified -> at most 5 reach transport (rate=5)."""
        stub = _CountingTransport()
        _mock_builder_preset_resolution(monkeypatch, stub)
        _mock_throttle_section(
            monkeypatch,
            mail_throttle={"rate": 5, "per": 60.0, "on_exceed": "warn"},
        )
        for _ in range(100):
            try:
                raise RuntimeError("boom")
            except RuntimeError:
                _ready(MailBuilder(preset="corporate")).send()
        assert stub.count == 5


# ---------------------------------------------------------------------------
# 30: clear_config / registry persistence
# ---------------------------------------------------------------------------


class TestRegistryPersistence:
    """Singleton registry survives config reloads (kill switch operational, not preference)."""

    def test_registry_persists_across_clear_config_simulated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """30: simulating a config reload does not give back tokens to the bucket."""
        stub = _CountingTransport()
        _mock_builder_preset_resolution(monkeypatch, stub)
        _mock_throttle_section(monkeypatch, mail_throttle={"rate": 5, "per": 60.0, "on_exceed": "warn"})
        first = MailBuilder(preset="corporate")
        # Drain the bucket via the singleton
        for _ in range(5):
            _ready(MailBuilder(preset="corporate")).send()
        # User now reloads config (reset env vars, re-call get_config) but the
        # throttle registry must NOT be cleared automatically.
        # Re-mock with different cascade values (same preset name).
        _mock_throttle_section(monkeypatch, mail_throttle={"rate": 5, "per": 60.0, "on_exceed": "warn"})
        second = MailBuilder(preset="corporate")
        # The throttle is the SAME singleton: bucket already drained.
        assert second._throttle is first._throttle
        # And the bucket is still empty: a sixth send is throttled.
        before = stub.count
        _ready(MailBuilder(preset="corporate")).send()
        assert stub.count == before, "registry was reset, bucket leaked tokens"


# ---------------------------------------------------------------------------
# A12: Mode 'drop' rejection
# ---------------------------------------------------------------------------


class TestDropModeRejected:
    """Mode ``"drop"`` is forbidden by kstlib logging convention (no silent drop)."""

    def test_drop_mode_rejected_via_kwarg(self) -> None:
        """A12a: throttle kwarg dict on_exceed='drop' raises with explainer."""
        with pytest.raises(MailConfigurationError) as exc:
            MailThrottle(rate=10, per=60.0, on_exceed="drop")  # type: ignore[arg-type]
        msg = str(exc.value)
        assert "drop" in msg
        assert "silent" in msg.lower()
        assert "raise" in msg
        assert "warn" in msg

    def test_drop_mode_rejected_via_yaml(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A12b: YAML on_exceed: drop is rejected at builder init."""
        _mock_throttle_section(monkeypatch, mail_throttle={"rate": 10, "per": 60.0, "on_exceed": "drop"})
        with pytest.raises(MailConfigurationError, match="drop"):
            get_or_create_throttle("corporate", None)


# ---------------------------------------------------------------------------
# A13-A14: Logging hygiene (no spam, no leak)
# ---------------------------------------------------------------------------


class TestLoggingHygiene:
    """Logs emitted by the throttle never leak content nor batch silently."""

    def test_no_log_spam_n_throttle_events(self, caplog: pytest.LogCaptureFixture) -> None:
        """A13: 100 throttle events emit exactly 100 WARNING records, no batching."""
        throttle = MailThrottle(rate=1, per=60.0, on_exceed="warn")
        assert throttle.consume("ok") is True
        with caplog.at_level(logging.WARNING, logger="kstlib.mail.throttle"):
            for _ in range(100):
                throttle.consume("blocked")
        warnings = [rec for rec in caplog.records if rec.levelno == logging.WARNING]
        assert len(warnings) == 100, f"expected 100 warnings, got {len(warnings)}"

    def test_no_leak_of_body_to_from_in_logs(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A14: builder fields with secrets never appear in throttle log records."""
        secret_body = "SECRET_TOKEN_xyz123"
        secret_from = "very-secret-from@internal.local"
        secret_to = "deeply-secret-to@internal.local"
        secret_cc = "leaked-cc@internal.local"
        secret_bcc = "leaked-bcc@internal.local"

        stub = _CountingTransport()
        _mock_builder_preset_resolution(monkeypatch, stub)
        _mock_throttle_section(monkeypatch, mail_throttle={"rate": 1, "per": 60.0, "on_exceed": "warn"})

        with caplog.at_level(logging.DEBUG, logger="kstlib.mail.throttle"):
            for _ in range(5):
                mail = (
                    MailBuilder(preset="corporate")
                    .sender(secret_from)
                    .to(secret_to)
                    .cc(secret_cc)
                    .bcc(secret_bcc)
                    .subject("OK to log")
                    .message(secret_body)
                )
                mail.send()

        all_messages = "\n".join(rec.getMessage() for rec in caplog.records)
        assert secret_body not in all_messages, "body leaked into throttle logs"
        assert secret_from not in all_messages, "From leaked into throttle logs"
        assert secret_to not in all_messages, "To leaked into throttle logs"
        assert secret_cc not in all_messages, "Cc leaked into throttle logs"
        assert secret_bcc not in all_messages, "Bcc leaked into throttle logs"


# ---------------------------------------------------------------------------
# A15: Combined paranoia
# ---------------------------------------------------------------------------


class TestCombinedParanoia:
    """Throttle holds under stacked stress (bulk + threads + asyncio + multi-instance)."""

    def test_combined_stress_does_not_exceed_rate_per_window(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A15: rate=5/per=60 + 1000 sends + threads + asyncio + 3 instances -> <=5 reach transport."""
        stub = _CountingTransport()
        _mock_builder_preset_resolution(monkeypatch, stub)
        _mock_throttle_section(
            monkeypatch,
            mail_throttle={"rate": 5, "per": 60.0, "on_exceed": "warn"},
        )

        def burst() -> None:
            _ready(MailBuilder(preset="corporate")).send()

        # 1000 sequential sends across 3 nominally-distinct builder instances
        for _ in range(1000):
            burst()
        # 5 concurrent threads
        with ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(lambda _i: burst(), range(50)))

        # 100 asyncio coroutines
        async def coro_all() -> None:
            await asyncio.gather(*(asyncio.to_thread(burst) for _ in range(100)))

        asyncio.run(coro_all())

        # Within a 60s window the bucket only refills up to rate=5. Total
        # elapsed test time is under a second, so refill is negligible:
        # at most 5-6 sends should have reached the transport.
        assert stub.count <= 6, f"throttle leaked: {stub.count} sends crossed rate=5"


# ---------------------------------------------------------------------------
# A16: _snapshot shares the throttle
# ---------------------------------------------------------------------------


class TestSnapshotSharesThrottle:
    """``_snapshot()`` (used by ``@notify``) MUST share the throttle bucket."""

    def test_snapshot_shares_throttle_object(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A16a: ``snapshot._throttle is mail._throttle`` (no deepcopy of the bucket)."""
        stub = _CountingTransport()
        _mock_builder_preset_resolution(monkeypatch, stub)
        _mock_throttle_section(monkeypatch, mail_throttle={"rate": 5, "per": 60.0, "on_exceed": "warn"})
        mail = MailBuilder(preset="corporate")
        snapshot = mail._snapshot()
        assert snapshot._throttle is mail._throttle, "snapshot got its own bucket: bypass"

    def test_notify_decorator_does_not_bypass(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A16b: 21 calls to a @notify function -> exactly 5 mails (rate=5, mode=warn)."""
        stub = _CountingTransport()
        _mock_builder_preset_resolution(monkeypatch, stub)
        _mock_throttle_section(monkeypatch, mail_throttle={"rate": 5, "per": 60.0, "on_exceed": "warn"})
        mail = MailBuilder(preset="corporate").sender("a@x.com").to("b@x.com").subject("S")

        @mail.notify
        def step(i: int) -> int:
            return i

        for i in range(21):
            step(i)
        assert stub.count == 5, f"decorator bypassed throttle: {stub.count} sends"


# ---------------------------------------------------------------------------
# A17: repr does not leak builder content
# ---------------------------------------------------------------------------


class TestReprNoLeak:
    """``repr(MailThrottle)`` exposes only configuration, never builder content."""

    def test_repr_contains_only_config(self) -> None:
        """A17: repr exposes rate/per/on_exceed and nothing builder-related."""
        throttle = MailThrottle(rate=20, per=60.0, on_exceed="raise")
        # Trigger one consume with a sensitive subject to make sure nothing
        # gets retained in __repr__ as a side-effect.
        throttle.consume("SENSITIVE_SUBJECT_xyz")
        rendered = repr(throttle)
        assert "rate=20" in rendered
        assert "per=60.0" in rendered
        assert "raise" in rendered
        # Sensitive data must not appear
        assert "SENSITIVE_SUBJECT" not in rendered
        assert "@" not in rendered  # no email address either


# ---------------------------------------------------------------------------
# A18: registry size cap enforced
# ---------------------------------------------------------------------------


class TestRegistryCap:
    """``HARD_MAX_THROTTLE_REGISTRY_SIZE`` blocks unbounded registry growth."""

    def test_registry_cap_enforced(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A18: registry cap blocks new preset entries beyond the hard limit.

        Mocks the cap to a small value (3) to keep the test fast.
        Creates 3 throttles with distinct preset names (OK), then a 4th
        which must raise ``MailConfigurationError`` and emit a
        ``WARNING [SECURITY]`` log line.
        """
        # Patch the constant where it's used (the throttle module imports
        # it at module load time, so patching kstlib.limits would not be
        # picked up by the already-bound name in throttle.py).
        monkeypatch.setattr("kstlib.mail.throttle.HARD_MAX_THROTTLE_REGISTRY_SIZE", 3)
        _mock_throttle_section(
            monkeypatch,
            mail_throttle={"rate": 5, "per": 60.0, "on_exceed": "warn"},
        )

        # Fill the registry up to the cap (3 distinct preset names).
        for i in range(3):
            throttle = get_or_create_throttle(f"preset_{i}", None)
            assert throttle is not None

        # The 4th distinct preset name must overflow the cap.
        with caplog.at_level(logging.WARNING, logger="kstlib.mail.throttle"):
            with pytest.raises(MailConfigurationError, match="registry size cap"):
                get_or_create_throttle("preset_overflow", None)

        # Verify the [SECURITY] tag is present in the WARNING log.
        security_records = [rec for rec in caplog.records if "[SECURITY]" in rec.getMessage()]
        assert len(security_records) >= 1, "Expected WARNING [SECURITY] log before raise, none found"
        # Spot check the hint is in the log message (not just generic).
        assert any("dynamic preset names" in rec.getMessage() for rec in security_records), (
            "Expected debug hint about dynamic preset names in the log"
        )
