"""Alert throttling using rate limiting.

Provides rate limiting for alerts to prevent flooding channels during
incident storms. Wraps :class:`kstlib.resilience.rate_limiter.RateLimiter`.

Configuration is read from ``kstlib.conf.yml`` under the ``alerts.throttle``
section, with hard limits enforced for deep defense.

Examples:
    Config-driven (recommended)::

        from kstlib.alerts.throttle import AlertThrottle

        # Uses alerts.throttle from kstlib.conf.yml
        throttle = AlertThrottle()

        if throttle.try_acquire():
            await channel.send(alert)

    Explicit override::

        # Override config values
        throttle = AlertThrottle(rate=5, per=30.0)

    With async context::

        throttle = AlertThrottle()

        async with throttle:
            await channel.send(alert)  # Waits if rate limit hit
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kstlib.alerts.exceptions import AlertThrottledError
from kstlib.limits import (
    HARD_MAX_THROTTLE_PER,
    HARD_MAX_THROTTLE_RATE,
    HARD_MIN_THROTTLE_PER,
    HARD_MIN_THROTTLE_RATE,
    clamp_with_limits,
    get_alerts_limits,
)
from kstlib.resilience.rate_limiter import RateLimiter

if TYPE_CHECKING:
    from typing_extensions import Self

__all__ = ["AlertThrottle"]


class AlertThrottle:
    """Rate limiter for alert delivery.

    Wraps :class:`kstlib.resilience.rate_limiter.RateLimiter` with
    alert-specific behavior and config-driven defaults.

    All parameters are optional. If not provided, values are read from
    ``kstlib.conf.yml`` under ``alerts.throttle``. Hard limits are enforced
    for deep defense against misconfiguration.

    Args:
        rate: Maximum alerts per period. If None, uses config value.
            Hard limits: [1, 1000].
        per: Period duration in seconds. If None, uses config value.
            Hard limits: [1.0, 86400.0] (1 day).
        burst: Initial capacity. If None, defaults to rate value.
            Hard limits: [1, rate].
        name: Optional name for identification.

    Examples:
        Config-driven (recommended)::

            throttle = AlertThrottle()  # Uses kstlib.conf.yml

        Explicit values::

            throttle = AlertThrottle(rate=10, per=60.0)

        Per-hour limiting with burst::

            throttle = AlertThrottle(rate=100, per=3600.0, burst=20)

        Non-blocking check::

            if throttle.try_acquire():
                send_alert()
            else:
                log.warning("Alert throttled")
    """

    def __init__(
        self,
        rate: float | None = None,
        per: float | None = None,
        *,
        burst: float | None = None,
        name: str | None = None,
    ) -> None:
        """Initialize AlertThrottle.

        Args:
            rate: Maximum alerts per period. If None, uses config.
            per: Period duration in seconds. If None, uses config.
            burst: Initial token count. If None, defaults to rate.
            name: Optional name for identification.
        """
        # Load config defaults
        limits = get_alerts_limits()

        # Apply kwargs > config > defaults pattern with hard limit clamping
        resolved_rate = clamp_with_limits(
            rate if rate is not None else limits.throttle_rate,
            HARD_MIN_THROTTLE_RATE,
            HARD_MAX_THROTTLE_RATE,
        )
        resolved_per = clamp_with_limits(
            per if per is not None else limits.throttle_per,
            HARD_MIN_THROTTLE_PER,
            HARD_MAX_THROTTLE_PER,
        )

        # Burst: kwargs > config > rate, clamped to [1, rate]
        if burst is not None:
            resolved_burst = clamp_with_limits(burst, 1, resolved_rate)
        else:
            resolved_burst = clamp_with_limits(limits.throttle_burst, 1, resolved_rate)

        self._limiter = RateLimiter(
            rate=resolved_rate,
            per=resolved_per,
            burst=resolved_burst,
            name=name,
        )

    @property
    def rate(self) -> float:
        """Maximum alerts per period."""
        return self._limiter.rate

    @property
    def per(self) -> float:
        """Period duration in seconds."""
        return self._limiter.per

    @property
    def available(self) -> float:
        """Current available tokens (alerts allowed)."""
        return self._limiter.tokens

    @property
    def time_until_available(self) -> float:
        """Seconds until next alert can be sent."""
        return self._limiter.time_until_token()

    def try_acquire(self) -> bool:
        """Try to acquire permission to send an alert.

        Returns:
            True if alert can be sent, False if throttled.

        Examples:
            >>> throttle = AlertThrottle(rate=2, per=1.0)
            >>> throttle.try_acquire()
            True
            >>> throttle.try_acquire()
            True
            >>> throttle.try_acquire()  # Throttled
            False
        """
        return self._limiter.try_acquire()

    def acquire(self, *, timeout: float | None = None) -> None:
        """Acquire permission to send an alert, blocking if needed.

        Args:
            timeout: Maximum time to wait in seconds.

        Raises:
            AlertThrottledError: If timeout exceeded.

        Examples:
            >>> throttle = AlertThrottle(rate=10, per=60.0)
            >>> throttle.acquire()  # Blocks if needed
        """
        try:
            self._limiter.acquire(blocking=True, timeout=timeout)
        except Exception:
            raise AlertThrottledError(
                "Alert rate limit exceeded",
                retry_after=self.time_until_available,
            ) from None

    async def acquire_async(self, *, timeout: float | None = None) -> None:
        """Acquire permission asynchronously, waiting if needed.

        Args:
            timeout: Maximum time to wait in seconds.

        Raises:
            AlertThrottledError: If timeout exceeded.

        Examples:
            >>> import asyncio
            >>> throttle = AlertThrottle(rate=10, per=60.0)
            >>> asyncio.run(throttle.acquire_async())
        """
        try:
            await self._limiter.acquire_async(timeout=timeout)
        except Exception:
            raise AlertThrottledError(
                "Alert rate limit exceeded",
                retry_after=self.time_until_available,
            ) from None

    def reset(self) -> None:
        """Reset throttle to full capacity.

        Examples:
            >>> throttle = AlertThrottle(rate=1, per=60.0)
            >>> throttle.try_acquire()
            True
            >>> throttle.try_acquire()
            False
            >>> throttle.reset()
            >>> throttle.try_acquire()
            True
        """
        self._limiter.reset()

    def __enter__(self) -> Self:
        """Enter context manager, acquiring permission."""
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Exit context manager."""
        pass

    async def __aenter__(self) -> Self:
        """Enter async context manager, acquiring permission."""
        await self.acquire_async()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Exit async context manager."""
        pass

    def __repr__(self) -> str:
        """Return string representation."""
        return f"AlertThrottle(rate={self.rate}, per={self.per})"
