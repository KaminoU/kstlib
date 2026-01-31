"""Human-friendly formatting utilities powered by humanize and pendulum."""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import TYPE_CHECKING

import humanize
import pendulum

if TYPE_CHECKING:
    from datetime import datetime

log = logging.getLogger(__name__)

# Hard limits for datetime formatting (defined here to avoid circular import)
# These values match the ones in limits.py for consistency
_HARD_MAX_DATETIME_FORMAT_LENGTH = 64
_HARD_MAX_TIMEZONE_LENGTH = 64
_HARD_MIN_EPOCH_TIMESTAMP = 0  # Unix epoch start
_HARD_MAX_EPOCH_TIMESTAMP = 4102444800  # Year 2100

__all__ = [
    "format_bytes",
    "format_count",
    "format_duration",
    "format_time_delta",
    "format_timestamp",
    "parse_size_string",
]

#: Default datetime format (ISO-like).
DEFAULT_DATETIME_FORMAT = "YYYY-MM-DD HH:mm:ss"

#: Allowed characters in datetime format strings (deep defense).
_DATETIME_FORMAT_PATTERN = re.compile(r"^[a-zA-Z0-9\s\-/:.,\[\]()]+$")


def _get_datetime_config() -> tuple[str, str]:
    """Get datetime format and timezone from config (lazy load).

    Returns:
        Tuple of (format_string, timezone_string).
    """
    try:
        from kstlib.config import get_config
        from kstlib.config.exceptions import ConfigNotLoadedError
    except ImportError:
        return DEFAULT_DATETIME_FORMAT, "local"

    try:
        config = get_config()
        dt_config = config.get("datetime", {})  # type: ignore[no-untyped-call]
        fmt = dt_config.get("format", DEFAULT_DATETIME_FORMAT)
        tz = dt_config.get("timezone", "local")
        return str(fmt), str(tz)
    except ConfigNotLoadedError:
        return DEFAULT_DATETIME_FORMAT, "local"


def _validate_format_string(fmt: str) -> str:
    """Validate and sanitize datetime format string (deep defense).

    Args:
        fmt: Format string to validate.

    Returns:
        Validated format string, or default if invalid.
    """
    if not fmt or not isinstance(fmt, str):
        return DEFAULT_DATETIME_FORMAT

    if len(fmt) > _HARD_MAX_DATETIME_FORMAT_LENGTH:
        log.warning(
            "Datetime format too long (%d > %d), using default",
            len(fmt),
            _HARD_MAX_DATETIME_FORMAT_LENGTH,
        )
        return DEFAULT_DATETIME_FORMAT

    if not _DATETIME_FORMAT_PATTERN.match(fmt):
        log.warning("Datetime format contains invalid characters, using default")
        return DEFAULT_DATETIME_FORMAT

    return fmt


def _validate_timezone(tz: str) -> str:
    """Validate timezone string (deep defense).

    Args:
        tz: Timezone string to validate.

    Returns:
        Validated timezone string, or "local" if invalid.
    """
    if not tz or not isinstance(tz, str):
        return "local"

    if len(tz) > _HARD_MAX_TIMEZONE_LENGTH:
        log.warning(
            "Timezone string too long (%d > %d), using local",
            len(tz),
            _HARD_MAX_TIMEZONE_LENGTH,
        )
        return "local"

    if tz.lower() == "local":
        return "local"

    # Validate against pendulum's known timezones
    try:
        pendulum.timezone(tz)
        return tz
    except Exception:
        log.warning("Unknown timezone '%s', using local", tz)
        return "local"


def format_timestamp(
    epoch: float | str | None,
    fmt: str | None = None,
    tz: str | None = None,
) -> str:
    """Format an epoch timestamp as a human-readable datetime string.

    Converts Unix epoch timestamps to formatted datetime strings using
    pendulum for timezone-aware formatting. Configuration can be loaded
    from kstlib.conf.yml or provided explicitly.

    Args:
        epoch: Unix timestamp (seconds since 1970-01-01 UTC).
            Accepts int, float, or string representation.
            Returns "(invalid)" if None or unparseable.
        fmt: Datetime format string (pendulum tokens).
            If None, uses config value or "YYYY-MM-DD HH:mm:ss".
        tz: Timezone for display ("local", "UTC", or IANA name).
            If None, uses config value or "local".

    Returns:
        Formatted datetime string, or "(invalid)" on error.

    Examples:
        >>> format_timestamp(1706234567, tz="UTC")
        '2024-01-26 02:02:47'
        >>> format_timestamp(1706234567, fmt="DD/MM/YYYY", tz="UTC")
        '26/01/2024'
        >>> format_timestamp(None)
        '(invalid)'
    """
    # Handle None or empty
    if epoch is None or epoch == "":
        return "(invalid)"

    # Convert string to numeric
    if isinstance(epoch, str):
        try:
            epoch = float(epoch)
        except ValueError:
            log.warning("Cannot parse epoch string: %r", epoch)
            return "(invalid)"

    # Validate epoch bounds (deep defense)
    if epoch < _HARD_MIN_EPOCH_TIMESTAMP or epoch > _HARD_MAX_EPOCH_TIMESTAMP:
        log.warning(
            "Epoch timestamp out of bounds: %s (valid: %d-%d)",
            epoch,
            _HARD_MIN_EPOCH_TIMESTAMP,
            _HARD_MAX_EPOCH_TIMESTAMP,
        )
        return "(invalid)"

    # Get config values if not provided
    config_fmt, config_tz = _get_datetime_config()
    fmt = _validate_format_string(fmt or config_fmt)
    tz = _validate_timezone(tz or config_tz)

    try:
        # Create pendulum datetime from epoch
        dt = pendulum.from_timestamp(epoch)

        # Convert to target timezone
        # pendulum.local_timezone is a module, not a function - use tz.local_timezone()
        from pendulum.tz import local_timezone

        local_tz = local_timezone()
        dt = dt.in_timezone(tz) if tz != "local" else dt.in_timezone(local_tz)

        return dt.format(fmt)
    except Exception as e:
        log.warning("Error formatting timestamp %s: %s", epoch, e)
        return "(invalid)"


def format_bytes(size: float, binary: bool = True) -> str:
    """Format a byte count as a human-readable string.

    Args:
        size: Size in bytes (int or float).
        binary: If True, use binary units (KiB, MiB). If False, use SI units (KB, MB).

    Returns:
        Human-readable size string (e.g., "25.0 MiB" or "25.0 MB").

    Examples:
        >>> format_bytes(25 * 1024 * 1024)
        '25.0 MiB'
        >>> format_bytes(25 * 1000 * 1000, binary=False)
        '25.0 MB'
    """
    return humanize.naturalsize(size, binary=binary)


def format_count(value: int) -> str:
    """Format a count with comma separators for readability.

    Args:
        value: Integer count to format.

    Returns:
        Comma-separated string (e.g., "1,000,000").

    Examples:
        >>> format_count(1000000)
        '1,000,000'
    """
    return humanize.intcomma(value)


def format_duration(seconds: float) -> str:
    """Format a duration in seconds as a human-readable string.

    Args:
        seconds: Duration in seconds.

    Returns:
        Human-readable duration (e.g., "5 minutes", "2 hours").

    Examples:
        >>> format_duration(300)
        '5 minutes'
        >>> format_duration(3661)
        'an hour'
    """
    delta = timedelta(seconds=seconds)
    return humanize.naturaldelta(delta)


def format_time_delta(dt: datetime, other: datetime | None = None) -> str:
    """Format a datetime as a relative time string.

    Args:
        dt: Target datetime.
        other: Reference datetime (defaults to now).

    Returns:
        Relative time string (e.g., "2 hours ago", "in 3 days").

    Examples:
        >>> from datetime import datetime, timedelta
        >>> past = datetime.now() - timedelta(hours=2)
        >>> format_time_delta(past)
        '2 hours ago'
    """
    return humanize.naturaltime(dt, when=other)


#: Size unit multipliers for parsing human-readable size strings.
_SIZE_UNITS: dict[str, int] = {
    "b": 1,
    "k": 1024,
    "kb": 1024,
    "kib": 1024,
    "m": 1024**2,
    "mb": 1024**2,
    "mib": 1024**2,
    "g": 1024**3,
    "gb": 1024**3,
    "gib": 1024**3,
    "t": 1024**4,
    "tb": 1024**4,
    "tib": 1024**4,
}

#: Regex pattern for parsing size strings like "25M", "100 MiB", "1.5GB".
_SIZE_PATTERN = __import__("re").compile(r"^\s*([\d.]+)\s*([a-zA-Z]*)\s*$")


def parse_size_string(value: str | float) -> int:
    """Parse a human-readable size string into bytes.

    Accepts raw integers, floats, or strings with optional units.
    Supported units: B, K, KB, KiB, M, MB, MiB, G, GB, GiB, T, TB, TiB.

    Args:
        value: Size as int, float, or string with optional unit suffix.

    Returns:
        Size in bytes as an integer.

    Raises:
        ValueError: If the string format is invalid or the unit is unknown.

    Examples:
        >>> parse_size_string(1024)
        1024
        >>> parse_size_string("25M")
        26214400
        >>> parse_size_string("100 MiB")
        104857600
        >>> parse_size_string("1.5GB")
        1610612736
    """
    # Handle numeric types directly
    if isinstance(value, int | float):
        return int(value)

    # Parse string format
    match = _SIZE_PATTERN.match(value)
    if not match:
        raise ValueError(f"Invalid size format: {value!r}")

    numeric_str, unit_str = match.groups()
    try:
        numeric_value = float(numeric_str)
    except ValueError as exc:
        raise ValueError(f"Invalid numeric value: {numeric_str!r}") from exc

    if not unit_str:
        return int(numeric_value)

    multiplier = _SIZE_UNITS.get(unit_str.lower())
    if multiplier is None:
        raise ValueError(f"Unknown size unit: {unit_str!r}")

    return int(numeric_value * multiplier)
