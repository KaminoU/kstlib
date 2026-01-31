"""Config-driven limits with hard-coded deep defense maximums.

This module provides configurable resource limits that users can customize
via kstlib.conf.yml, while enforcing hard maximums in code for deep defense
against misconfiguration or malicious input.

Example:
    >>> from kstlib.limits import get_mail_limits, get_cache_limits
    >>> mail_limits = get_mail_limits()
    >>> mail_limits.max_attachment_size
    26214400
    >>> mail_limits.max_attachment_size_display
    '25.0 MiB'
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from kstlib.utils.formatting import format_bytes, parse_size_string

__all__ = [
    "HARD_MAX_DATETIME_FORMAT_LENGTH",
    "HARD_MAX_DISPLAY_VALUE_LENGTH",
    "HARD_MAX_ENDPOINT_REF_LENGTH",
    "HARD_MAX_EPOCH_TIMESTAMP",
    "HARD_MAX_TIMEZONE_LENGTH",
    "HARD_MIN_EPOCH_TIMESTAMP",
    "AlertsLimits",
    "CacheLimits",
    "DatabaseLimits",
    "MailLimits",
    "RapiLimits",
    "RapiRenderConfig",
    "ResilienceLimits",
    "SopsLimits",
    "WebSocketLimits",
    "clamp_with_limits",
    "get_alerts_limits",
    "get_cache_limits",
    "get_db_limits",
    "get_mail_limits",
    "get_rapi_limits",
    "get_rapi_render_config",
    "get_resilience_limits",
    "get_sops_limits",
    "get_websocket_limits",
]

# =============================================================================
# Hard limits (deep defense - cannot be exceeded via config)
# =============================================================================

#: Absolute maximum attachment size (25 MiB) - protects against memory exhaustion.
HARD_MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024

#: Absolute maximum attachments per message - protects against resource exhaustion.
HARD_MAX_ATTACHMENTS = 50

#: Absolute maximum cache file size (100 MiB) - protects against OOM.
HARD_MAX_CACHE_FILE_SIZE = 100 * 1024 * 1024

#: Absolute maximum SOPS cache entries - protects against memory exhaustion.
HARD_MAX_SOPS_CACHE_ENTRIES = 256

#: Heartbeat interval bounds (seconds) - protects against too frequent or stale checks.
HARD_MIN_HEARTBEAT_INTERVAL = 1
HARD_MAX_HEARTBEAT_INTERVAL = 300  # 5 minutes

#: Shutdown timeout bounds (seconds) - protects against hanging or too fast shutdowns.
HARD_MIN_SHUTDOWN_TIMEOUT = 5
HARD_MAX_SHUTDOWN_TIMEOUT = 300  # 5 minutes

#: Circuit breaker failure count bounds - protects against trivial or impossible thresholds.
HARD_MIN_CIRCUIT_FAILURES = 1
HARD_MAX_CIRCUIT_FAILURES = 100

#: Circuit breaker reset timeout bounds (seconds) - protects against too short or too long cooldowns.
HARD_MIN_CIRCUIT_RESET_TIMEOUT = 1
HARD_MAX_CIRCUIT_RESET_TIMEOUT = 3600  # 1 hour

#: Circuit breaker half-open calls bounds - protects against trivial or too aggressive testing.
HARD_MIN_HALF_OPEN_CALLS = 1
HARD_MAX_HALF_OPEN_CALLS = 10

#: Watchdog timeout bounds (seconds) - protects against too short or impossibly long timeouts.
HARD_MIN_WATCHDOG_TIMEOUT = 1
HARD_MAX_WATCHDOG_TIMEOUT = 3600  # 1 hour

#: Database pool min_size bounds - protects against invalid pool configuration.
#: min_size=0 is valid (lazy pool, connections created on demand).
HARD_MIN_POOL_MIN_SIZE = 0
HARD_MAX_POOL_MIN_SIZE = 10

#: Database pool max_size bounds - protects against resource exhaustion.
HARD_MIN_POOL_MAX_SIZE = 1
HARD_MAX_POOL_MAX_SIZE = 100

#: Database pool acquire timeout bounds (seconds) - protects against deadlocks or no-wait.
HARD_MIN_POOL_ACQUIRE_TIMEOUT = 1.0
HARD_MAX_POOL_ACQUIRE_TIMEOUT = 300.0  # 5 minutes

#: Database retry attempts bounds - protects against infinite retries or no retry.
HARD_MIN_DB_MAX_RETRIES = 1
HARD_MAX_DB_MAX_RETRIES = 10

#: Database retry delay bounds (seconds) - protects against too fast or too slow retries.
HARD_MIN_DB_RETRY_DELAY = 0.1
HARD_MAX_DB_RETRY_DELAY = 60.0

#: RAPI timeout bounds (seconds) - protects against too short or infinite waits.
HARD_MIN_RAPI_TIMEOUT = 1.0
HARD_MAX_RAPI_TIMEOUT = 300.0  # 5 minutes

#: RAPI max response size (100 MiB) - protects against memory exhaustion.
HARD_MAX_RAPI_RESPONSE_SIZE = 100 * 1024 * 1024

#: RAPI retry attempts bounds - protects against infinite retries.
HARD_MIN_RAPI_RETRIES = 0
HARD_MAX_RAPI_RETRIES = 10

#: RAPI retry delay bounds (seconds) - protects against too fast or too slow retries.
HARD_MIN_RAPI_RETRY_DELAY = 0.1
HARD_MAX_RAPI_RETRY_DELAY = 60.0

#: RAPI backoff multiplier bounds - protects against too aggressive or too slow backoff.
HARD_MIN_RAPI_BACKOFF = 1.0
HARD_MAX_RAPI_BACKOFF = 5.0

#: Alert throttle rate bounds - protects against too permissive or impossible thresholds.
HARD_MIN_THROTTLE_RATE = 1
HARD_MAX_THROTTLE_RATE = 1000

#: Alert throttle period bounds (seconds) - protects against too short or impossibly long periods.
HARD_MIN_THROTTLE_PER = 1.0
HARD_MAX_THROTTLE_PER = 86400.0  # 1 day

#: Alert channel timeout bounds (seconds) - protects against too short or hanging requests.
HARD_MIN_CHANNEL_TIMEOUT = 1.0
HARD_MAX_CHANNEL_TIMEOUT = 120.0

#: Alert channel retry bounds - protects against infinite retries.
HARD_MIN_CHANNEL_RETRIES = 0
HARD_MAX_CHANNEL_RETRIES = 5

#: WebSocket ping interval bounds (seconds) - protects against too frequent or stale checks.
HARD_MIN_WS_PING_INTERVAL = 5.0
HARD_MAX_WS_PING_INTERVAL = 60.0

#: WebSocket ping timeout bounds (seconds) - protects against too short or too long timeouts.
HARD_MIN_WS_PING_TIMEOUT = 5.0
HARD_MAX_WS_PING_TIMEOUT = 30.0

#: WebSocket connection timeout bounds (seconds) - protects against too short or infinite waits.
HARD_MIN_WS_CONNECTION_TIMEOUT = 5.0
HARD_MAX_WS_CONNECTION_TIMEOUT = 120.0

#: WebSocket reconnect delay bounds (seconds) - immediate allowed, max 5 minutes.
HARD_MIN_WS_RECONNECT_DELAY = 0.0
HARD_MAX_WS_RECONNECT_DELAY = 300.0

#: WebSocket max reconnect delay bounds (seconds) - for exponential backoff cap.
HARD_MIN_WS_MAX_RECONNECT_DELAY = 1.0
HARD_MAX_WS_MAX_RECONNECT_DELAY = 600.0

#: WebSocket max reconnect attempts bounds - 0 means no retry.
HARD_MIN_WS_RECONNECT_ATTEMPTS = 0
HARD_MAX_WS_RECONNECT_ATTEMPTS = 100

#: WebSocket message queue size bounds - 0 means unlimited.
HARD_MIN_WS_QUEUE_SIZE = 0
HARD_MAX_WS_QUEUE_SIZE = 10000

#: WebSocket disconnect check interval bounds (seconds) - for proactive control.
HARD_MIN_WS_DISCONNECT_CHECK = 1.0
HARD_MAX_WS_DISCONNECT_CHECK = 60.0

#: WebSocket reconnect check interval bounds (seconds) - for proactive control.
HARD_MIN_WS_RECONNECT_CHECK = 0.5
HARD_MAX_WS_RECONNECT_CHECK = 60.0

#: WebSocket proactive disconnect margin bounds (seconds) - before platform limits.
HARD_MIN_WS_DISCONNECT_MARGIN = 60.0
HARD_MAX_WS_DISCONNECT_MARGIN = 3600.0

#: Maximum endpoint reference length (api.endpoint format) - protects against DoS.
HARD_MAX_ENDPOINT_REF_LENGTH = 256

#: Maximum display length for values in rapi show (truncate long strings).
HARD_MAX_DISPLAY_VALUE_LENGTH = 200

#: Maximum datetime format string length - protects against DoS.
HARD_MAX_DATETIME_FORMAT_LENGTH = 64

#: Maximum timezone string length - protects against DoS.
HARD_MAX_TIMEZONE_LENGTH = 64

#: Minimum valid epoch timestamp (1970-01-01 00:00:00 UTC).
HARD_MIN_EPOCH_TIMESTAMP = 0

#: Maximum valid epoch timestamp (year 2100) - protects against overflow.
HARD_MAX_EPOCH_TIMESTAMP = 4102444800

# =============================================================================
# Default limits (used when config is not available)
# =============================================================================

DEFAULT_MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024  # 25 MiB
DEFAULT_MAX_ATTACHMENTS = 20
DEFAULT_MAX_CACHE_FILE_SIZE = 50 * 1024 * 1024  # 50 MiB
DEFAULT_MAX_SOPS_CACHE_ENTRIES = 64

DEFAULT_HEARTBEAT_INTERVAL = 10  # seconds
DEFAULT_SHUTDOWN_TIMEOUT = 30  # seconds
DEFAULT_CIRCUIT_MAX_FAILURES = 5
DEFAULT_CIRCUIT_RESET_TIMEOUT = 60  # seconds
DEFAULT_HALF_OPEN_MAX_CALLS = 1
DEFAULT_WATCHDOG_TIMEOUT = 30  # seconds

DEFAULT_POOL_MIN_SIZE = 1
DEFAULT_POOL_MAX_SIZE = 10
DEFAULT_POOL_ACQUIRE_TIMEOUT = 30.0  # seconds
DEFAULT_DB_MAX_RETRIES = 3
DEFAULT_DB_RETRY_DELAY = 0.5  # seconds

DEFAULT_RAPI_TIMEOUT = 30.0  # seconds
DEFAULT_RAPI_MAX_RESPONSE_SIZE = 10 * 1024 * 1024  # 10 MiB
DEFAULT_RAPI_MAX_RETRIES = 3
DEFAULT_RAPI_RETRY_DELAY = 1.0  # seconds
DEFAULT_RAPI_BACKOFF = 2.0

DEFAULT_THROTTLE_RATE = 10  # alerts per period
DEFAULT_THROTTLE_PER = 60.0  # seconds
DEFAULT_THROTTLE_BURST = 5  # initial capacity
DEFAULT_CHANNEL_TIMEOUT = 30.0  # seconds
DEFAULT_CHANNEL_RETRIES = 2

DEFAULT_WS_PING_INTERVAL = 20.0  # seconds
DEFAULT_WS_PING_TIMEOUT = 10.0  # seconds
DEFAULT_WS_CONNECTION_TIMEOUT = 30.0  # seconds
DEFAULT_WS_RECONNECT_DELAY = 1.0  # seconds
DEFAULT_WS_MAX_RECONNECT_DELAY = 60.0  # seconds
DEFAULT_WS_RECONNECT_ATTEMPTS = 10
DEFAULT_WS_QUEUE_SIZE = 1000  # messages
DEFAULT_WS_DISCONNECT_CHECK = 10.0  # seconds
DEFAULT_WS_RECONNECT_CHECK = 5.0  # seconds
DEFAULT_WS_DISCONNECT_MARGIN = 300.0  # seconds (5 minutes before 24h limit)


@dataclass(frozen=True, slots=True)
class MailLimits:
    """Resolved mail resource limits."""

    max_attachment_size: int
    max_attachments: int

    @property
    def max_attachment_size_display(self) -> str:
        """Human-readable attachment size limit."""
        return format_bytes(self.max_attachment_size)


@dataclass(frozen=True, slots=True)
class CacheLimits:
    """Resolved cache resource limits."""

    max_file_size: int

    @property
    def max_file_size_display(self) -> str:
        """Human-readable cache file size limit."""
        return format_bytes(self.max_file_size)


@dataclass(frozen=True, slots=True)
class SopsLimits:
    """Resolved SOPS provider limits."""

    max_cache_entries: int


def _load_config() -> Mapping[str, Any] | None:
    """Attempt to load the global configuration."""
    # pylint: disable=import-outside-toplevel
    try:
        # Lazy imports to avoid circular dependencies
        from kstlib.config import get_config
        from kstlib.config.exceptions import ConfigNotLoadedError
    except ImportError:  # pragma: no cover - defensive branch
        return None  # pragma: no cover - defensive branch

    try:
        return get_config()
    except ConfigNotLoadedError:  # pragma: no cover - defensive branch
        return None  # pragma: no cover - defensive branch


def _get_nested(config: Mapping[str, Any] | None, *keys: str, default: Any = None) -> Any:
    """Safely traverse nested config keys."""
    if config is None:
        return default
    current: Any = config
    for key in keys:
        if not isinstance(current, Mapping):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def _parse_float_config(raw_value: Any, default: float, hard_min: float, hard_max: float) -> float:
    """Parse a float config value with clamping."""
    if raw_value is None:
        return clamp_with_limits(default, hard_min, hard_max)
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        value = default
    return clamp_with_limits(value, hard_min, hard_max)


def _parse_int_config(raw_value: Any, default: int, hard_min: int, hard_max: int) -> int:
    """Parse an int config value with clamping."""
    if raw_value is None:
        return int(clamp_with_limits(default, hard_min, hard_max))
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = default
    return int(clamp_with_limits(value, hard_min, hard_max))


def get_mail_limits(config: Mapping[str, Any] | None = None) -> MailLimits:
    """Resolve mail limits from config with hard limit enforcement.

    Args:
        config: Optional config mapping. If None, loads from get_config().

    Returns:
        MailLimits with resolved values clamped to hard maximums.
    """
    if config is None:
        config = _load_config()

    # Read configured values
    raw_size = _get_nested(config, "mail", "limits", "max_attachment_size")
    raw_count = _get_nested(config, "mail", "limits", "max_attachments")

    # Parse and clamp attachment size
    if raw_size is not None:
        try:
            configured_size = parse_size_string(raw_size)
        except ValueError:
            configured_size = DEFAULT_MAX_ATTACHMENT_SIZE
    else:
        configured_size = DEFAULT_MAX_ATTACHMENT_SIZE

    max_attachment_size = min(configured_size, HARD_MAX_ATTACHMENT_SIZE)

    # Parse and clamp attachment count
    if raw_count is not None:
        try:
            configured_count = int(raw_count)
        except (TypeError, ValueError):
            configured_count = DEFAULT_MAX_ATTACHMENTS
    else:
        configured_count = DEFAULT_MAX_ATTACHMENTS

    max_attachments = min(max(1, configured_count), HARD_MAX_ATTACHMENTS)

    return MailLimits(
        max_attachment_size=max_attachment_size,
        max_attachments=max_attachments,
    )


def get_cache_limits(config: Mapping[str, Any] | None = None) -> CacheLimits:
    """Resolve cache limits from config with hard limit enforcement.

    Args:
        config: Optional config mapping. If None, loads from get_config().

    Returns:
        CacheLimits with resolved values clamped to hard maximums.
    """
    if config is None:
        config = _load_config()

    raw_size = _get_nested(config, "cache", "file", "max_file_size")

    if raw_size is not None:
        try:
            configured_size = parse_size_string(raw_size)
        except ValueError:
            configured_size = DEFAULT_MAX_CACHE_FILE_SIZE
    else:
        configured_size = DEFAULT_MAX_CACHE_FILE_SIZE

    max_file_size = min(configured_size, HARD_MAX_CACHE_FILE_SIZE)

    return CacheLimits(max_file_size=max_file_size)


def get_sops_limits(config: Mapping[str, Any] | None = None) -> SopsLimits:
    """Resolve SOPS limits from config with hard limit enforcement.

    Args:
        config: Optional config mapping. If None, loads from get_config().

    Returns:
        SopsLimits with resolved values clamped to hard maximums.
    """
    if config is None:
        config = _load_config()

    raw_entries = _get_nested(config, "secrets", "sops", "max_cache_entries")

    if raw_entries is not None:
        try:
            configured_entries = int(raw_entries)
        except (TypeError, ValueError):
            configured_entries = DEFAULT_MAX_SOPS_CACHE_ENTRIES
    else:
        configured_entries = DEFAULT_MAX_SOPS_CACHE_ENTRIES

    max_cache_entries = min(max(1, configured_entries), HARD_MAX_SOPS_CACHE_ENTRIES)

    return SopsLimits(max_cache_entries=max_cache_entries)


@dataclass(frozen=True, slots=True)
class ResilienceLimits:
    """Resolved resilience configuration limits.

    Attributes:
        heartbeat_interval: Seconds between heartbeats.
        shutdown_timeout: Total timeout for cleanup callbacks.
        circuit_max_failures: Failures before opening circuit.
        circuit_reset_timeout: Cooldown before recovery attempt.
        circuit_half_open_calls: Calls allowed in half-open state.
        watchdog_timeout: Seconds before watchdog triggers timeout.
    """

    heartbeat_interval: float
    shutdown_timeout: float
    circuit_max_failures: int
    circuit_reset_timeout: float
    circuit_half_open_calls: int
    watchdog_timeout: float


def clamp_with_limits(value: float, hard_min: float, hard_max: float) -> float:
    """Clamp a value between hard minimum and maximum bounds.

    Utility function for applying hard limits to user-provided values.
    Used throughout the resilience module for defensive programming.

    Args:
        value: The value to clamp.
        hard_min: Minimum allowed value (inclusive).
        hard_max: Maximum allowed value (inclusive).

    Returns:
        The clamped value within [hard_min, hard_max].

    Examples:
        >>> clamp_with_limits(50, 1, 100)
        50
        >>> clamp_with_limits(0, 1, 100)
        1
        >>> clamp_with_limits(200, 1, 100)
        100
    """
    return max(hard_min, min(value, hard_max))


def get_resilience_limits(
    config: Mapping[str, Any] | None = None,
) -> ResilienceLimits:
    """Resolve resilience limits from config with hard limit enforcement.

    Args:
        config: Optional config mapping. If None, loads from get_config().

    Returns:
        ResilienceLimits with resolved values clamped to hard bounds.

    Examples:
        >>> limits = get_resilience_limits()
        >>> int(limits.heartbeat_interval)
        10
        >>> limits.circuit_max_failures
        5
    """
    if config is None:
        config = _load_config()

    return ResilienceLimits(
        heartbeat_interval=_parse_float_config(
            _get_nested(config, "resilience", "heartbeat", "interval"),
            DEFAULT_HEARTBEAT_INTERVAL,
            HARD_MIN_HEARTBEAT_INTERVAL,
            HARD_MAX_HEARTBEAT_INTERVAL,
        ),
        shutdown_timeout=_parse_float_config(
            _get_nested(config, "resilience", "shutdown", "timeout"),
            DEFAULT_SHUTDOWN_TIMEOUT,
            HARD_MIN_SHUTDOWN_TIMEOUT,
            HARD_MAX_SHUTDOWN_TIMEOUT,
        ),
        circuit_max_failures=_parse_int_config(
            _get_nested(config, "resilience", "circuit_breaker", "max_failures"),
            DEFAULT_CIRCUIT_MAX_FAILURES,
            HARD_MIN_CIRCUIT_FAILURES,
            HARD_MAX_CIRCUIT_FAILURES,
        ),
        circuit_reset_timeout=_parse_float_config(
            _get_nested(config, "resilience", "circuit_breaker", "reset_timeout"),
            DEFAULT_CIRCUIT_RESET_TIMEOUT,
            HARD_MIN_CIRCUIT_RESET_TIMEOUT,
            HARD_MAX_CIRCUIT_RESET_TIMEOUT,
        ),
        circuit_half_open_calls=_parse_int_config(
            _get_nested(config, "resilience", "circuit_breaker", "half_open_max_calls"),
            DEFAULT_HALF_OPEN_MAX_CALLS,
            HARD_MIN_HALF_OPEN_CALLS,
            HARD_MAX_HALF_OPEN_CALLS,
        ),
        watchdog_timeout=_parse_float_config(
            _get_nested(config, "resilience", "watchdog", "timeout"),
            DEFAULT_WATCHDOG_TIMEOUT,
            HARD_MIN_WATCHDOG_TIMEOUT,
            HARD_MAX_WATCHDOG_TIMEOUT,
        ),
    )


@dataclass(frozen=True, slots=True)
class DatabaseLimits:
    """Resolved database configuration limits.

    Attributes:
        pool_min_size: Minimum connections to maintain in pool.
        pool_max_size: Maximum connections allowed in pool.
        pool_acquire_timeout: Timeout for acquiring a connection (seconds).
        max_retries: Retry attempts on connection failure.
        retry_delay: Delay between retries (seconds).
    """

    pool_min_size: int
    pool_max_size: int
    pool_acquire_timeout: float
    max_retries: int
    retry_delay: float


def get_db_limits(
    config: Mapping[str, Any] | None = None,
) -> DatabaseLimits:
    """Resolve database limits from config with hard limit enforcement.

    Args:
        config: Optional config mapping. If None, loads from get_config().

    Returns:
        DatabaseLimits with resolved values clamped to hard bounds.

    Examples:
        >>> limits = get_db_limits()
        >>> limits.pool_min_size
        1
        >>> limits.pool_max_size
        10
    """
    if config is None:
        config = _load_config()

    pool_min = _parse_int_config(
        _get_nested(config, "db", "pool", "min_size"),
        DEFAULT_POOL_MIN_SIZE,
        HARD_MIN_POOL_MIN_SIZE,
        HARD_MAX_POOL_MIN_SIZE,
    )
    pool_max = _parse_int_config(
        _get_nested(config, "db", "pool", "max_size"),
        DEFAULT_POOL_MAX_SIZE,
        HARD_MIN_POOL_MAX_SIZE,
        HARD_MAX_POOL_MAX_SIZE,
    )

    # Ensure min_size <= max_size
    pool_min = min(pool_min, pool_max)

    return DatabaseLimits(
        pool_min_size=pool_min,
        pool_max_size=pool_max,
        pool_acquire_timeout=_parse_float_config(
            _get_nested(config, "db", "pool", "acquire_timeout"),
            DEFAULT_POOL_ACQUIRE_TIMEOUT,
            HARD_MIN_POOL_ACQUIRE_TIMEOUT,
            HARD_MAX_POOL_ACQUIRE_TIMEOUT,
        ),
        max_retries=_parse_int_config(
            _get_nested(config, "db", "retry", "max_attempts"),
            DEFAULT_DB_MAX_RETRIES,
            HARD_MIN_DB_MAX_RETRIES,
            HARD_MAX_DB_MAX_RETRIES,
        ),
        retry_delay=_parse_float_config(
            _get_nested(config, "db", "retry", "delay"),
            DEFAULT_DB_RETRY_DELAY,
            HARD_MIN_DB_RETRY_DELAY,
            HARD_MAX_DB_RETRY_DELAY,
        ),
    )


@dataclass(frozen=True, slots=True)
class RapiLimits:
    """Resolved RAPI configuration limits.

    Attributes:
        timeout: Request timeout in seconds.
        max_response_size: Maximum response size in bytes.
        max_retries: Maximum retry attempts.
        retry_delay: Delay between retries in seconds.
        retry_backoff: Backoff multiplier for exponential retry.
    """

    timeout: float
    max_response_size: int
    max_retries: int
    retry_delay: float
    retry_backoff: float

    @property
    def max_response_size_display(self) -> str:
        """Human-readable response size limit."""
        return format_bytes(self.max_response_size)


def get_rapi_limits(
    config: Mapping[str, Any] | None = None,
) -> RapiLimits:
    """Resolve RAPI limits from config with hard limit enforcement.

    Args:
        config: Optional config mapping. If None, loads from get_config().

    Returns:
        RapiLimits with resolved values clamped to hard bounds.

    Examples:
        >>> limits = get_rapi_limits()
        >>> limits.timeout
        30.0
        >>> limits.max_retries
        3
    """
    if config is None:
        config = _load_config()

    # Parse max_response_size (supports human-readable strings like "10M")
    raw_response_size = _get_nested(config, "rapi", "limits", "max_response_size")
    if raw_response_size is not None:
        try:
            configured_size = parse_size_string(raw_response_size)
        except ValueError:
            configured_size = DEFAULT_RAPI_MAX_RESPONSE_SIZE
    else:
        configured_size = DEFAULT_RAPI_MAX_RESPONSE_SIZE

    max_response_size = min(configured_size, HARD_MAX_RAPI_RESPONSE_SIZE)

    return RapiLimits(
        timeout=_parse_float_config(
            _get_nested(config, "rapi", "limits", "timeout"),
            DEFAULT_RAPI_TIMEOUT,
            HARD_MIN_RAPI_TIMEOUT,
            HARD_MAX_RAPI_TIMEOUT,
        ),
        max_response_size=max_response_size,
        max_retries=_parse_int_config(
            _get_nested(config, "rapi", "limits", "max_retries"),
            DEFAULT_RAPI_MAX_RETRIES,
            HARD_MIN_RAPI_RETRIES,
            HARD_MAX_RAPI_RETRIES,
        ),
        retry_delay=_parse_float_config(
            _get_nested(config, "rapi", "limits", "retry_delay"),
            DEFAULT_RAPI_RETRY_DELAY,
            HARD_MIN_RAPI_RETRY_DELAY,
            HARD_MAX_RAPI_RETRY_DELAY,
        ),
        retry_backoff=_parse_float_config(
            _get_nested(config, "rapi", "limits", "retry_backoff"),
            DEFAULT_RAPI_BACKOFF,
            HARD_MIN_RAPI_BACKOFF,
            HARD_MAX_RAPI_BACKOFF,
        ),
    )


#: Default JSON indentation for pretty-print (spaces)
DEFAULT_RAPI_JSON_INDENT = 2

#: Default XML pretty-print enabled
DEFAULT_RAPI_XML_PRETTY = True


@dataclass(frozen=True, slots=True)
class RapiRenderConfig:
    """RAPI CLI output rendering configuration.

    Attributes:
        json_indent: JSON indentation (spaces). None or 0 to disable pretty-print.
        xml_pretty: Whether to enable XML pretty-printing.
    """

    json_indent: int | None
    xml_pretty: bool


def get_rapi_render_config(
    config: Mapping[str, Any] | None = None,
) -> RapiRenderConfig:
    """Resolve RAPI rendering config for CLI output.

    Args:
        config: Optional config mapping. If None, loads from get_config().

    Returns:
        RapiRenderConfig with resolved values.

    Examples:
        >>> render_config = get_rapi_render_config()
        >>> render_config.json_indent
        2
        >>> render_config.xml_pretty
        True
    """
    if config is None:
        config = _load_config()

    # Parse JSON indent (int or None)
    raw_json = _get_nested(config, "rapi", "pretty_render", "json")
    if raw_json is None:
        json_indent: int | None = DEFAULT_RAPI_JSON_INDENT
    elif raw_json == 0:
        json_indent = None
    else:
        try:
            json_indent = int(raw_json)
            # Clamp to reasonable bounds (1-8 spaces)
            json_indent = max(1, min(json_indent, 8))
        except (TypeError, ValueError):
            json_indent = DEFAULT_RAPI_JSON_INDENT

    # Parse XML pretty (bool)
    raw_xml = _get_nested(config, "rapi", "pretty_render", "xml")
    xml_pretty = DEFAULT_RAPI_XML_PRETTY if raw_xml is None else bool(raw_xml)

    return RapiRenderConfig(
        json_indent=json_indent,
        xml_pretty=xml_pretty,
    )


@dataclass(frozen=True, slots=True)
class AlertsLimits:
    """Resolved alerts configuration limits.

    Attributes:
        throttle_rate: Maximum alerts per period.
        throttle_per: Period duration in seconds.
        throttle_burst: Initial burst capacity.
        channel_timeout: Timeout for sending alerts (seconds).
        channel_retries: Retry attempts on delivery failure.
    """

    throttle_rate: int
    throttle_per: float
    throttle_burst: int
    channel_timeout: float
    channel_retries: int


def get_alerts_limits(
    config: Mapping[str, Any] | None = None,
) -> AlertsLimits:
    """Resolve alerts limits from config with hard limit enforcement.

    Args:
        config: Optional config mapping. If None, loads from get_config().

    Returns:
        AlertsLimits with resolved values clamped to hard bounds.

    Examples:
        >>> limits = get_alerts_limits()
        >>> limits.throttle_rate
        10
        >>> limits.throttle_per
        60.0
    """
    if config is None:
        config = _load_config()

    rate = _parse_int_config(
        _get_nested(config, "alerts", "throttle", "rate"),
        DEFAULT_THROTTLE_RATE,
        HARD_MIN_THROTTLE_RATE,
        HARD_MAX_THROTTLE_RATE,
    )

    per = _parse_float_config(
        _get_nested(config, "alerts", "throttle", "per"),
        DEFAULT_THROTTLE_PER,
        HARD_MIN_THROTTLE_PER,
        HARD_MAX_THROTTLE_PER,
    )

    # Burst defaults to rate if not specified, clamped to [1, rate]
    raw_burst = _get_nested(config, "alerts", "throttle", "burst")
    burst = rate if raw_burst is None else _parse_int_config(raw_burst, rate, 1, rate)

    return AlertsLimits(
        throttle_rate=rate,
        throttle_per=per,
        throttle_burst=burst,
        channel_timeout=_parse_float_config(
            _get_nested(config, "alerts", "channels", "timeout"),
            DEFAULT_CHANNEL_TIMEOUT,
            HARD_MIN_CHANNEL_TIMEOUT,
            HARD_MAX_CHANNEL_TIMEOUT,
        ),
        channel_retries=_parse_int_config(
            _get_nested(config, "alerts", "channels", "max_retries"),
            DEFAULT_CHANNEL_RETRIES,
            HARD_MIN_CHANNEL_RETRIES,
            HARD_MAX_CHANNEL_RETRIES,
        ),
    )


@dataclass(frozen=True, slots=True)
class WebSocketLimits:
    """Resolved WebSocket configuration limits.

    Includes settings for connection management, reconnection behavior,
    and proactive control features.

    Attributes:
        ping_interval: Seconds between ping frames.
        ping_timeout: Seconds to wait for pong response.
        connection_timeout: Timeout for initial connection.
        reconnect_delay: Initial delay between reconnect attempts.
        max_reconnect_delay: Maximum delay for exponential backoff.
        max_reconnect_attempts: Maximum consecutive reconnection attempts.
        queue_size: Maximum messages in queue (0 = unlimited).
        disconnect_check_interval: Seconds between should_disconnect checks.
        reconnect_check_interval: Seconds between should_reconnect checks.
        disconnect_margin: Seconds before platform limit to disconnect.
    """

    ping_interval: float
    ping_timeout: float
    connection_timeout: float
    reconnect_delay: float
    max_reconnect_delay: float
    max_reconnect_attempts: int
    queue_size: int
    disconnect_check_interval: float
    reconnect_check_interval: float
    disconnect_margin: float


def get_websocket_limits(
    config: Mapping[str, Any] | None = None,
) -> WebSocketLimits:
    """Resolve WebSocket limits from config with hard limit enforcement.

    Args:
        config: Optional config mapping. If None, loads from get_config().

    Returns:
        WebSocketLimits with resolved values clamped to hard bounds.

    Examples:
        >>> limits = get_websocket_limits()
        >>> limits.ping_interval
        20.0
        >>> limits.max_reconnect_attempts
        10
    """
    if config is None:
        config = _load_config()

    return WebSocketLimits(
        ping_interval=_parse_float_config(
            _get_nested(config, "websocket", "ping", "interval"),
            DEFAULT_WS_PING_INTERVAL,
            HARD_MIN_WS_PING_INTERVAL,
            HARD_MAX_WS_PING_INTERVAL,
        ),
        ping_timeout=_parse_float_config(
            _get_nested(config, "websocket", "ping", "timeout"),
            DEFAULT_WS_PING_TIMEOUT,
            HARD_MIN_WS_PING_TIMEOUT,
            HARD_MAX_WS_PING_TIMEOUT,
        ),
        connection_timeout=_parse_float_config(
            _get_nested(config, "websocket", "connection", "timeout"),
            DEFAULT_WS_CONNECTION_TIMEOUT,
            HARD_MIN_WS_CONNECTION_TIMEOUT,
            HARD_MAX_WS_CONNECTION_TIMEOUT,
        ),
        reconnect_delay=_parse_float_config(
            _get_nested(config, "websocket", "reconnect", "delay"),
            DEFAULT_WS_RECONNECT_DELAY,
            HARD_MIN_WS_RECONNECT_DELAY,
            HARD_MAX_WS_RECONNECT_DELAY,
        ),
        max_reconnect_delay=_parse_float_config(
            _get_nested(config, "websocket", "reconnect", "max_delay"),
            DEFAULT_WS_MAX_RECONNECT_DELAY,
            HARD_MIN_WS_MAX_RECONNECT_DELAY,
            HARD_MAX_WS_MAX_RECONNECT_DELAY,
        ),
        max_reconnect_attempts=_parse_int_config(
            _get_nested(config, "websocket", "reconnect", "max_attempts"),
            DEFAULT_WS_RECONNECT_ATTEMPTS,
            HARD_MIN_WS_RECONNECT_ATTEMPTS,
            HARD_MAX_WS_RECONNECT_ATTEMPTS,
        ),
        queue_size=_parse_int_config(
            _get_nested(config, "websocket", "queue", "size"),
            DEFAULT_WS_QUEUE_SIZE,
            HARD_MIN_WS_QUEUE_SIZE,
            HARD_MAX_WS_QUEUE_SIZE,
        ),
        disconnect_check_interval=_parse_float_config(
            _get_nested(config, "websocket", "proactive", "disconnect_check_interval"),
            DEFAULT_WS_DISCONNECT_CHECK,
            HARD_MIN_WS_DISCONNECT_CHECK,
            HARD_MAX_WS_DISCONNECT_CHECK,
        ),
        reconnect_check_interval=_parse_float_config(
            _get_nested(config, "websocket", "proactive", "reconnect_check_interval"),
            DEFAULT_WS_RECONNECT_CHECK,
            HARD_MIN_WS_RECONNECT_CHECK,
            HARD_MAX_WS_RECONNECT_CHECK,
        ),
        disconnect_margin=_parse_float_config(
            _get_nested(config, "websocket", "proactive", "disconnect_margin"),
            DEFAULT_WS_DISCONNECT_MARGIN,
            HARD_MIN_WS_DISCONNECT_MARGIN,
            HARD_MAX_WS_DISCONNECT_MARGIN,
        ),
    )
