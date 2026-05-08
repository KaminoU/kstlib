"""Mail throttle (anti-spam kill switch) with config cascade and singleton per preset.

Wraps :class:`kstlib.resilience.RateLimiter` with mail-specific exception
type, on_exceed policy, security logging, and a singleton registry per
preset to prevent bypass via multiple builder instances.

Hard limits are shared with the alerts module
(``HARD_MIN/MAX_THROTTLE_RATE`` and ``HARD_MIN/MAX_THROTTLE_PER`` in
:mod:`kstlib.limits`). Mode ``"drop"`` is intentionally rejected at init:
a security event (rate-limit exceeded) must never be silent.

Resolution cascade (most specific first):

1. ``mail.presets.<preset_name>.throttle.<key>`` (preset-level)
2. ``mail.throttle.<key>`` (mail-level)
3. Defaults from :mod:`kstlib.limits`

Each key (``enabled``, ``rate``, ``per``, ``on_exceed``) cascades
independently, mirroring the SSL cascade pattern in the mail builder.

Examples:
    Default throttle (config-driven)::

        from kstlib.mail import MailBuilder
        mail = MailBuilder(preset="corporate")
        mail.sender("a@x.com").to("b@x.com").subject("Hi").message("...").send()

    Disable per builder (tests, single-shot scripts)::

        mail = MailBuilder(preset="corporate", throttle=False)

    Custom override per builder::

        mail = MailBuilder(
            preset="corporate",
            throttle={"rate": 100, "per": 3600.0, "on_exceed": "warn"},
        )

"""

from __future__ import annotations

import threading
from typing import Any, Literal

from kstlib.limits import (
    DEFAULT_MAIL_THROTTLE_ON_EXCEED,
    DEFAULT_MAIL_THROTTLE_PER,
    DEFAULT_MAIL_THROTTLE_RATE,
    HARD_MAX_THROTTLE_PER,
    HARD_MAX_THROTTLE_RATE,
    HARD_MAX_THROTTLE_REGISTRY_SIZE,
    HARD_MIN_THROTTLE_PER,
    HARD_MIN_THROTTLE_RATE,
)
from kstlib.logging import get_logger
from kstlib.mail._helpers import _load_mail_section
from kstlib.mail.exceptions import MailConfigurationError, MailThrottledError
from kstlib.resilience import RateLimiter

log = get_logger(__name__)

OnExceedMode = Literal["raise", "warn"]

_VALID_ON_EXCEED: frozenset[str] = frozenset({"raise", "warn"})
_REJECTED_ON_EXCEED: frozenset[str] = frozenset({"drop"})
_VALID_THROTTLE_KEYS: frozenset[str] = frozenset({"enabled", "rate", "per", "on_exceed"})

_MAX_SUBJECT_LOG_LEN = 80
_SUBJECT_NOT_SET = "<subject not set>"
_SUBJECT_NULL_BYTE = "<subject contains null byte>"

_throttle_registry: dict[str, MailThrottle] = {}
_registry_lock = threading.Lock()


class MailThrottle:
    """Token-bucket throttle for mail sends, config-driven.

    Singleton per preset (or per builder for explicit transports). Wraps
    :class:`kstlib.resilience.RateLimiter` with mail-specific exception
    type and on_exceed behavior.

    The throttle is a kill switch against accidental or buggy mail spam:
    runaway batch loops, recursion, exception handlers that mail, the
    ``@mail.notify`` decorator on a hot function. It is enforced before
    the transport is invoked.

    Mode ``"drop"`` (silent) is intentionally rejected at init: a security
    event must never be silent. Valid modes are ``"raise"`` and ``"warn"``,
    and both emit a ``WARNING [SECURITY]`` log per blocked send.

    Args:
        rate: Maximum mails per period. Must be ``int`` in
            ``[HARD_MIN_THROTTLE_RATE, HARD_MAX_THROTTLE_RATE]``.
        per: Period in seconds. Must be ``int`` or ``float`` in
            ``[HARD_MIN_THROTTLE_PER, HARD_MAX_THROTTLE_PER]``.
        on_exceed: Policy when the bucket is empty. ``"raise"`` raises
            :class:`~kstlib.mail.MailThrottledError` after the security
            warning; ``"warn"`` logs the warning and returns silently.

    Raises:
        MailConfigurationError: If a parameter is out of bounds, of a
            wrong type, or if ``on_exceed`` is ``"drop"`` (rejected).

    Examples:
        Strict mode (default)::

            throttle = MailThrottle(rate=20, per=60.0)
            if throttle.consume(subject_for_log="Daily report"):
                send_mail()
            # MailThrottledError raised on the 21st call within 60s

        Warn-only mode (operational critical channels)::

            throttle = MailThrottle(rate=5, per=60.0, on_exceed="warn")
            allowed = throttle.consume("Critical alert")
            if not allowed:
                pass  # silently dropped, [SECURITY] logged

        Inspect the resolved configuration on a fresh instance:

        >>> throttle = MailThrottle(rate=20, per=60.0)
        >>> throttle.rate
        20
        >>> throttle.per
        60.0
        >>> throttle.on_exceed
        'raise'

    """

    __slots__ = ("_limiter", "_on_exceed", "_per", "_rate")

    def __init__(
        self,
        *,
        rate: int = DEFAULT_MAIL_THROTTLE_RATE,
        per: float = DEFAULT_MAIL_THROTTLE_PER,
        on_exceed: OnExceedMode = DEFAULT_MAIL_THROTTLE_ON_EXCEED,
    ) -> None:
        """Validate parameters and build the underlying RateLimiter."""
        self._validate_on_exceed(on_exceed)
        self._validate_rate(rate)
        self._validate_per(per)

        self._limiter = RateLimiter(rate=float(rate), per=float(per))
        self._on_exceed: OnExceedMode = on_exceed
        self._rate: int = rate
        self._per: float = float(per)

    @staticmethod
    def _validate_on_exceed(on_exceed: Any) -> None:
        """Reject 'drop' explicitly and any other unknown value."""
        if on_exceed in _REJECTED_ON_EXCEED:
            msg = (
                f"throttle.on_exceed={on_exceed!r} is rejected: silent drop "
                f"is forbidden by kstlib logging convention (security "
                f"events must never be silent). "
                f"Valid modes: {sorted(_VALID_ON_EXCEED)}."
            )
            raise MailConfigurationError(msg)
        if on_exceed not in _VALID_ON_EXCEED:
            msg = f"throttle.on_exceed must be one of {sorted(_VALID_ON_EXCEED)}, got {on_exceed!r}."
            raise MailConfigurationError(msg)

    @staticmethod
    def _validate_rate(rate: Any) -> None:
        """Reject non-int rate and out-of-bounds values."""
        # bool is a subclass of int in Python, exclude it explicitly.
        if isinstance(rate, bool) or not isinstance(rate, int):
            msg = f"throttle.rate must be int, got {type(rate).__name__}: {rate!r}."
            raise MailConfigurationError(msg)
        if rate < HARD_MIN_THROTTLE_RATE:
            msg = f"throttle.rate must be >= {HARD_MIN_THROTTLE_RATE}, got {rate}."
            raise MailConfigurationError(msg)
        if rate > HARD_MAX_THROTTLE_RATE:
            msg = f"throttle.rate {rate} exceeds HARD_MAX {HARD_MAX_THROTTLE_RATE}."
            raise MailConfigurationError(msg)

    @staticmethod
    def _validate_per(per: Any) -> None:
        """Reject non-numeric per and out-of-bounds values."""
        if isinstance(per, bool) or not isinstance(per, (int, float)):
            msg = f"throttle.per must be int or float, got {type(per).__name__}: {per!r}."
            raise MailConfigurationError(msg)
        if per < HARD_MIN_THROTTLE_PER:
            msg = f"throttle.per must be >= {HARD_MIN_THROTTLE_PER}, got {per}."
            raise MailConfigurationError(msg)
        if per > HARD_MAX_THROTTLE_PER:
            msg = f"throttle.per {per} exceeds HARD_MAX {HARD_MAX_THROTTLE_PER}."
            raise MailConfigurationError(msg)

    @property
    def rate(self) -> int:
        """Configured rate (mails per period)."""
        return self._rate

    @property
    def per(self) -> float:
        """Configured period in seconds."""
        return self._per

    @property
    def on_exceed(self) -> OnExceedMode:
        """Configured policy when the bucket is empty."""
        return self._on_exceed

    def consume(self, subject_for_log: str | None = None) -> bool:
        """Try to consume one token, applying the on_exceed policy on failure.

        Args:
            subject_for_log: Optional subject of the mail being sent.
                Truncated to 80 chars in the log; if it contains a null
                byte, replaced by a placeholder. Used for debug only,
                never for routing.

        Returns:
            ``True`` if the caller should proceed with the send, ``False``
            if the send should be dropped silently (``warn`` mode only).

        Raises:
            MailThrottledError: If throttled and ``on_exceed='raise'``.

        """
        if self._limiter.try_acquire():
            return True
        safe_subject = self._sanitize_subject(subject_for_log)
        if self._on_exceed == "raise":
            log.warning(
                "[SECURITY] Mail throttle exceeded (rate=%d, per=%.1fs). "
                "Raising MailThrottledError. Subject dropped: %s",
                self._rate,
                self._per,
                safe_subject,
            )
            msg = f"Mail throttle exceeded: {self._rate} sends per {self._per}s. Subject dropped: {safe_subject}"
            raise MailThrottledError(msg)
        log.warning(
            "[SECURITY] Mail throttle exceeded (rate=%d, per=%.1fs). Mail dropped silently (mode=warn). Subject: %s",
            self._rate,
            self._per,
            safe_subject,
        )
        return False

    @staticmethod
    def _sanitize_subject(raw: str | None) -> str:
        """Sanitize a subject for log (truncate, null-byte, None handling).

        Hardening for log injection / terminal escape / log size blowup.
        Subject is debug-only; it never affects routing or delivery.
        """
        if raw is None or raw == "":
            return _SUBJECT_NOT_SET
        if "\x00" in raw:
            return _SUBJECT_NULL_BYTE
        if len(raw) > _MAX_SUBJECT_LOG_LEN:
            return raw[:_MAX_SUBJECT_LOG_LEN] + "..."
        return raw

    def __repr__(self) -> str:
        """Return a non-sensitive repr (no builder content, no recipients)."""
        return f"MailThrottle(rate={self._rate}, per={self._per}, on_exceed={self._on_exceed!r})"


def get_or_create_throttle(
    preset_name: str | None,
    config: dict[str, Any] | bool | None,
) -> MailThrottle | None:
    """Resolve the throttle for a builder, applying the cascade and singleton.

    Resolution order (most specific first):

    1. Explicit kwarg ``throttle=False`` -> disabled (returns ``None``).
    2. Explicit kwarg ``throttle=dict`` -> per-instance throttle (no
       singleton; unknown keys rejected; missing keys filled from defaults).
    3. ``throttle=None`` (default) -> YAML cascade:

       a. ``mail.presets.<preset_name>.throttle.<key>`` (preset-level)
       b. ``mail.throttle.<key>`` (mail-level)
       c. Defaults from :mod:`kstlib.limits`

    If ``enabled=False`` at the most-specific cascade level, returns
    ``None``. Otherwise, builds (and caches as singleton) a
    :class:`MailThrottle` keyed on ``preset_name``.

    For an explicit transport (``preset_name=None``), the preset-level
    cascade is skipped, and the resulting throttle is per-instance (no
    singleton, no shared state across builders).

    Args:
        preset_name: Preset name or ``None`` for an explicit transport.
        config: Builder ``throttle=`` kwarg: ``False`` to disable,
            a ``dict`` for a per-instance custom throttle, or ``None``
            for config-driven cascade.

    Returns:
        :class:`MailThrottle` to enforce, or ``None`` if disabled.

    Raises:
        MailConfigurationError: If a dict has unknown keys, or if any
            cascade-resolved value violates hard limits.

    """
    if config is False:
        log.debug(
            "Mail throttle disabled (kwarg throttle=False), preset=%s",
            preset_name or "<none>",
        )
        return None
    if isinstance(config, dict):
        return _build_from_dict(config, preset_name=preset_name)
    return _resolve_cascade(preset_name)


def _build_from_dict(config: dict[str, Any], *, preset_name: str | None) -> MailThrottle | None:
    """Build a per-instance throttle from a dict kwarg, validating keys."""
    _reject_unknown_throttle_keys(config, source="kwarg")
    if config.get("enabled") is False:
        log.debug(
            "Mail throttle disabled (dict enabled=false), preset=%s",
            preset_name or "<none>",
        )
        return None
    kwargs = {k: v for k, v in config.items() if k != "enabled"}
    throttle = MailThrottle(**kwargs)
    log.debug(
        "Mail throttle resolved: rate=%d, per=%.1fs, mode=%s, source=kwarg, preset=%s",
        throttle.rate,
        throttle.per,
        throttle.on_exceed,
        preset_name or "<none>",
    )
    return throttle


def _resolve_cascade(preset_name: str | None) -> MailThrottle | None:
    """Resolve via YAML cascade, returning a (cached) singleton or None."""
    mail_cfg = _load_mail_section(silent=True)
    preset_throttle = _read_preset_throttle(mail_cfg, preset_name)
    mail_throttle = _read_mail_throttle(mail_cfg)

    enabled = _resolve_key(preset_throttle, mail_throttle, "enabled", default=True)
    if enabled is False:
        log.debug(
            "Mail throttle disabled (cascade enabled=false), preset=%s",
            preset_name or "<none>",
        )
        return None

    rate = _resolve_key(preset_throttle, mail_throttle, "rate", default=DEFAULT_MAIL_THROTTLE_RATE)
    per = _resolve_key(preset_throttle, mail_throttle, "per", default=DEFAULT_MAIL_THROTTLE_PER)
    on_exceed = _resolve_key(
        preset_throttle,
        mail_throttle,
        "on_exceed",
        default=DEFAULT_MAIL_THROTTLE_ON_EXCEED,
    )
    source = _resolve_source(preset_throttle, mail_throttle)

    if preset_name is not None:
        with _registry_lock:
            cached = _throttle_registry.get(preset_name)
            if cached is not None:
                log.debug(
                    "Mail throttle reused (singleton): rate=%d, per=%.1fs, mode=%s, source=%s, preset=%s",
                    cached.rate,
                    cached.per,
                    cached.on_exceed,
                    source,
                    preset_name,
                )
                return cached
            if len(_throttle_registry) >= HARD_MAX_THROTTLE_REGISTRY_SIZE:
                log.warning(
                    "[SECURITY] Mail throttle registry size cap reached "
                    "(%d entries). Refusing new entry for preset=%s. "
                    "This usually indicates dynamic preset names "
                    "(e.g. UUID-suffixed); preset names should be a "
                    "small static set.",
                    HARD_MAX_THROTTLE_REGISTRY_SIZE,
                    preset_name,
                )
                msg = (
                    f"Mail throttle registry size cap reached "
                    f"({HARD_MAX_THROTTLE_REGISTRY_SIZE} entries). "
                    f"This usually indicates dynamic preset names "
                    f"(e.g. UUID-suffixed). Preset names should be a "
                    f"small static set; check your configuration."
                )
                raise MailConfigurationError(msg)
            throttle = MailThrottle(rate=rate, per=per, on_exceed=on_exceed)
            _throttle_registry[preset_name] = throttle
            log.debug(
                "Mail throttle resolved: rate=%d, per=%.1fs, mode=%s, source=%s, preset=%s",
                throttle.rate,
                throttle.per,
                throttle.on_exceed,
                source,
                preset_name,
            )
            return throttle

    throttle = MailThrottle(rate=rate, per=per, on_exceed=on_exceed)
    log.debug(
        "Mail throttle resolved (per-instance, no preset): rate=%d, per=%.1fs, mode=%s, source=%s",
        throttle.rate,
        throttle.per,
        throttle.on_exceed,
        source,
    )
    return throttle


def _resolve_key(
    preset_throttle: dict[str, Any] | None,
    mail_throttle: dict[str, Any] | None,
    key: str,
    default: Any,
) -> Any:
    """Cascade lookup for a single key (preset > mail > default)."""
    if preset_throttle is not None and key in preset_throttle:
        return preset_throttle[key]
    if mail_throttle is not None and key in mail_throttle:
        return mail_throttle[key]
    return default


def _resolve_source(
    preset_throttle: dict[str, Any] | None,
    mail_throttle: dict[str, Any] | None,
) -> str:
    """Identify which cascade level provided values (for the debug log)."""
    if preset_throttle:
        return "preset"
    if mail_throttle:
        return "mail"
    return "default"


def _read_preset_throttle(mail_cfg: Any, preset_name: str | None) -> dict[str, Any] | None:
    """Extract ``mail.presets.<name>.throttle`` as a plain dict, or None."""
    if mail_cfg is None or preset_name is None or not hasattr(mail_cfg, "get"):
        return None
    presets = mail_cfg.get("presets")
    if presets is None or not hasattr(presets, "get"):
        return None
    preset_cfg = presets.get(preset_name)
    if preset_cfg is None or not hasattr(preset_cfg, "get"):
        return None
    raw = preset_cfg.get("throttle")
    if raw is None or not hasattr(raw, "items"):
        return None
    raw_dict = dict(raw.items())
    _reject_unknown_throttle_keys(raw_dict, source="preset")
    return raw_dict


def _read_mail_throttle(mail_cfg: Any) -> dict[str, Any] | None:
    """Extract ``mail.throttle`` as a plain dict, or None."""
    if mail_cfg is None or not hasattr(mail_cfg, "get"):
        return None
    raw = mail_cfg.get("throttle")
    if raw is None or not hasattr(raw, "items"):
        return None
    raw_dict = dict(raw.items())
    _reject_unknown_throttle_keys(raw_dict, source="mail")
    return raw_dict


def _reject_unknown_throttle_keys(raw: dict[str, Any], *, source: str) -> None:
    """Reject unknown keys in a throttle config dict (anti-typo).

    Shared by the three entry points:

    - ``_build_from_dict`` (kwarg ``MailBuilder(throttle={...})``)
    - ``_read_preset_throttle`` (YAML ``mail.presets.<name>.throttle``)
    - ``_read_mail_throttle`` (YAML ``mail.throttle``)

    Args:
        raw: The dict whose keys must be a subset of ``_VALID_THROTTLE_KEYS``.
        source: Origin label (``"kwarg"`` / ``"preset"`` / ``"mail"``)
            included in the error message to help the caller locate the
            typo.

    Raises:
        MailConfigurationError: If ``raw`` contains any key outside
            ``_VALID_THROTTLE_KEYS``.

    """
    unknown = set(raw.keys()) - _VALID_THROTTLE_KEYS
    if unknown:
        if source == "kwarg":
            msg = f"throttle config has unknown keys: {sorted(unknown)}. Valid keys: {sorted(_VALID_THROTTLE_KEYS)}."
        else:
            msg = (
                f"YAML mail throttle ({source}) has unknown keys: "
                f"{sorted(unknown)}. Valid keys: {sorted(_VALID_THROTTLE_KEYS)}."
            )
        raise MailConfigurationError(msg)


def _reset_registry() -> None:
    """Clear the singleton registry. Test helper, not for production use.

    The throttle is intentionally a kill switch: in production, the
    registry persists across :func:`kstlib.config.clear_config` calls
    so that a buggy caller cannot bypass the throttle by reloading
    configuration. This helper is exposed for unit tests only.
    """
    with _registry_lock:
        _throttle_registry.clear()


__all__ = [
    "MailThrottle",
    "OnExceedMode",
    "get_or_create_throttle",
]
