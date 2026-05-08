"""Internal helpers for the mail subpackage.

Single source of truth for the ``mail`` configuration section access
shared by :mod:`kstlib.mail.builder` (cascade transport / SSL / preset
resolution) and :mod:`kstlib.mail.throttle` (anti-spam kill switch
init).
"""

from __future__ import annotations

from typing import Any

from kstlib.mail.exceptions import MailConfigurationError


def _load_mail_section(*, silent: bool = False) -> Any:
    """Read the ``mail`` section from the kstlib configuration.

    Two distinct contracts share this implementation:

    - ``silent=False`` (used by :mod:`kstlib.mail.builder`):
      preserves the legacy single-exception-type contract. Every loader
      failure (``ImportError``, ``ConfigNotLoadedError``, ``YAMLError``,
      ``OSError``, ``RuntimeError``, ...) is wrapped in
      :class:`~kstlib.mail.MailConfigurationError`. Existing builder
      callers and tests rely on this wrap.

    - ``silent=True`` (used by :mod:`kstlib.mail.throttle`):
      narrow catch. Only "config absent / not loaded" errors
      (``ImportError``, ``ConfigNotLoadedError``,
      ``MailConfigurationError``) are suppressed and return ``None``.
      Real corruption (``YAMLError``, ``OSError``, ``RuntimeError``,
      ...) propagates so the throttle init crashes explicitly rather
      than silently disabling.

    The asymmetry is intentional: the throttle is an operational
    kill switch, surfacing corruption is preferable to silently
    weakening the safety net. Full unification (narrow catch on both
    paths) would be a breaking change for the builder API and is
    deferred to a future major release.

    Args:
        silent: If ``True``, suppress "config not loaded" errors and
            return ``None``. Real corruption errors always propagate.

    Returns:
        The mail section as a Box / dict, or ``None`` if the section
        is missing or (``silent=True``) the config is not loaded.

    Raises:
        MailConfigurationError: If ``silent=False`` and the config
            cannot be loaded for any reason. The original exception is
            chained via ``__cause__``.

    """
    try:
        from kstlib.config import get_config
        from kstlib.config.exceptions import ConfigNotLoadedError
    except ImportError as exc:  # pragma: no cover - config is always present
        if silent:
            return None
        raise MailConfigurationError("kstlib.config is not available") from exc

    try:
        cfg: Any = get_config()
    except (ConfigNotLoadedError, MailConfigurationError) as exc:
        if silent:
            return None
        raise MailConfigurationError(f"Failed to load kstlib configuration: not loaded ({exc})") from exc
    except Exception as exc:
        # Real loader corruption (YAMLError, OSError, RuntimeError, ...).
        # silent path: propagate to surface the bug at builder/throttle init.
        # non-silent path: wrap into MailConfigurationError to preserve the
        # legacy single-exception API that existing builder callers rely on.
        if silent:
            raise
        raise MailConfigurationError(f"Failed to load kstlib configuration: {exc}") from exc

    if not hasattr(cfg, "get"):
        return None
    return cfg.get("mail")
