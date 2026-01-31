"""Tests for human-friendly formatting utilities."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from kstlib.utils.formatting import (
    format_bytes,
    format_count,
    format_duration,
    format_time_delta,
    format_timestamp,
    parse_size_string,
)


class TestFormatBytes:
    """Tests for format_bytes function."""

    def test_format_bytes_binary_default(self) -> None:
        """Format bytes using binary units (KiB, MiB) by default."""
        result = format_bytes(1024)
        assert "Ki" in result or "1.0" in result

    def test_format_bytes_binary_explicit(self) -> None:
        """Format bytes using explicit binary units."""
        result = format_bytes(25 * 1024 * 1024, binary=True)
        assert "MiB" in result or "25" in result

    def test_format_bytes_si_units(self) -> None:
        """Format bytes using SI units (KB, MB)."""
        result = format_bytes(25 * 1000 * 1000, binary=False)
        assert "MB" in result or "25" in result

    def test_format_bytes_zero(self) -> None:
        """Format zero bytes."""
        result = format_bytes(0)
        assert "0" in result or "Byte" in result

    def test_format_bytes_large_value(self) -> None:
        """Format very large byte counts."""
        result = format_bytes(1024**4)  # 1 TiB
        assert "Ti" in result or "1.0" in result


class TestFormatCount:
    """Tests for format_count function."""

    def test_format_count_simple(self) -> None:
        """Format a count with comma separators."""
        result = format_count(1000000)
        assert result == "1,000,000"

    def test_format_count_small(self) -> None:
        """Format a small count without separators."""
        result = format_count(100)
        assert result == "100"

    def test_format_count_zero(self) -> None:
        """Format zero."""
        result = format_count(0)
        assert result == "0"

    def test_format_count_negative(self) -> None:
        """Format a negative count."""
        result = format_count(-1000)
        assert result == "-1,000"


class TestFormatDuration:
    """Tests for format_duration function."""

    def test_format_duration_minutes(self) -> None:
        """Format duration in minutes."""
        result = format_duration(300)  # 5 minutes
        assert "minute" in result.lower()

    def test_format_duration_hours(self) -> None:
        """Format duration in hours."""
        result = format_duration(3600)  # 1 hour
        assert "hour" in result.lower()

    def test_format_duration_seconds(self) -> None:
        """Format duration in seconds."""
        result = format_duration(45)
        assert "second" in result.lower()

    def test_format_duration_days(self) -> None:
        """Format duration in days."""
        result = format_duration(86400 * 3)  # 3 days
        assert "day" in result.lower()


class TestFormatTimeDelta:
    """Tests for format_time_delta function."""

    def test_format_time_delta_past(self) -> None:
        """Format a past datetime."""
        past = datetime.now() - timedelta(hours=2)
        result = format_time_delta(past)
        assert "ago" in result.lower() or "hour" in result.lower()

    def test_format_time_delta_future(self) -> None:
        """Format a future datetime."""
        future = datetime.now() + timedelta(days=3)
        result = format_time_delta(future)
        assert "from now" in result.lower() or "day" in result.lower()

    def test_format_time_delta_with_reference(self) -> None:
        """Format a datetime relative to a specific reference time."""
        base = datetime(2024, 1, 1, 12, 0, 0)
        target = datetime(2024, 1, 1, 10, 0, 0)  # 2 hours before base
        result = format_time_delta(target, other=base)
        assert "hour" in result.lower() or "ago" in result.lower()


class TestParseSizeString:
    """Tests for parse_size_string function."""

    def test_parse_size_integer(self) -> None:
        """Parse an integer value directly."""
        assert parse_size_string(1024) == 1024

    def test_parse_size_float(self) -> None:
        """Parse a float value directly."""
        assert parse_size_string(1024.5) == 1024

    def test_parse_size_string_with_unit_m(self) -> None:
        """Parse size string with M unit."""
        assert parse_size_string("25M") == 25 * 1024**2

    def test_parse_size_string_with_unit_mib(self) -> None:
        """Parse size string with MiB unit."""
        assert parse_size_string("100 MiB") == 100 * 1024**2

    def test_parse_size_string_with_unit_gb(self) -> None:
        """Parse size string with GB unit."""
        assert parse_size_string("1.5GB") == int(1.5 * 1024**3)

    def test_parse_size_string_with_unit_kb(self) -> None:
        """Parse size string with KB unit."""
        assert parse_size_string("512KB") == 512 * 1024

    def test_parse_size_string_with_unit_tb(self) -> None:
        """Parse size string with TB unit."""
        assert parse_size_string("1TB") == 1024**4

    def test_parse_size_string_with_unit_b(self) -> None:
        """Parse size string with B unit."""
        assert parse_size_string("100B") == 100

    def test_parse_size_string_without_unit(self) -> None:
        """Parse size string without unit suffix."""
        assert parse_size_string("1024") == 1024

    def test_parse_size_string_with_spaces(self) -> None:
        """Parse size string with surrounding spaces."""
        assert parse_size_string("  512  ") == 512

    def test_parse_size_string_case_insensitive(self) -> None:
        """Parse size string with different case units."""
        assert parse_size_string("10mb") == parse_size_string("10MB")

    def test_parse_size_string_invalid_format(self) -> None:
        """Reject invalid size format."""
        with pytest.raises(ValueError, match="Invalid size format"):
            parse_size_string("invalid")

    def test_parse_size_string_unknown_unit(self) -> None:
        """Reject unknown size unit."""
        with pytest.raises(ValueError, match="Unknown size unit"):
            parse_size_string("100XB")

    def test_parse_size_string_empty(self) -> None:
        """Reject empty string."""
        with pytest.raises(ValueError, match="Invalid size format"):
            parse_size_string("")

    def test_parse_size_string_kib(self) -> None:
        """Parse size string with KiB unit."""
        assert parse_size_string("1KiB") == 1024

    def test_parse_size_string_gib(self) -> None:
        """Parse size string with GiB unit."""
        assert parse_size_string("2GiB") == 2 * 1024**3

    def test_parse_size_string_tib(self) -> None:
        """Parse size string with TiB unit."""
        assert parse_size_string("1TiB") == 1024**4

    def test_parse_size_string_k_shorthand(self) -> None:
        """Parse size string with K shorthand."""
        assert parse_size_string("64K") == 64 * 1024

    def test_parse_size_string_g_shorthand(self) -> None:
        """Parse size string with G shorthand."""
        assert parse_size_string("1G") == 1024**3

    def test_parse_size_string_t_shorthand(self) -> None:
        """Parse size string with T shorthand."""
        assert parse_size_string("1T") == 1024**4

    def test_parse_size_string_invalid_numeric(self) -> None:
        """Reject invalid numeric value (e.g., multiple dots)."""
        with pytest.raises(ValueError, match="Invalid numeric value"):
            parse_size_string("1.2.3MB")


class TestFormatTimestamp:
    """Tests for format_timestamp function."""

    def test_format_timestamp_valid_epoch(self) -> None:
        """Format a valid epoch timestamp."""
        result = format_timestamp(1706234567, tz="UTC")
        assert "2024-01-26" in result
        assert "02:02:47" in result

    def test_format_timestamp_string_epoch(self) -> None:
        """Format an epoch passed as string."""
        result = format_timestamp("1706234567", tz="UTC")
        assert "2024-01-26" in result

    def test_format_timestamp_float_epoch(self) -> None:
        """Format an epoch with decimal seconds."""
        result = format_timestamp(1706234567.5, tz="UTC")
        assert "2024-01-26" in result

    def test_format_timestamp_none(self) -> None:
        """Return invalid for None input."""
        assert format_timestamp(None) == "(invalid)"

    def test_format_timestamp_empty_string(self) -> None:
        """Return invalid for empty string."""
        assert format_timestamp("") == "(invalid)"

    def test_format_timestamp_invalid_string(self) -> None:
        """Return invalid for non-numeric string."""
        assert format_timestamp("not_a_number") == "(invalid)"

    def test_format_timestamp_custom_format(self) -> None:
        """Use custom datetime format."""
        result = format_timestamp(1706234567, fmt="DD/MM/YYYY", tz="UTC")
        assert result == "26/01/2024"

    def test_format_timestamp_utc_timezone(self) -> None:
        """Explicitly use UTC timezone."""
        result = format_timestamp(1706234567, tz="UTC")
        assert "02:02:47" in result

    def test_format_timestamp_epoch_at_zero(self) -> None:
        """Format epoch at Unix epoch start (1970-01-01)."""
        result = format_timestamp(0, tz="UTC")
        assert "1970-01-01" in result

    def test_format_timestamp_negative_epoch(self) -> None:
        """Reject negative epoch (before 1970)."""
        assert format_timestamp(-1) == "(invalid)"

    def test_format_timestamp_epoch_out_of_bounds(self) -> None:
        """Reject epoch beyond year 2100."""
        result = format_timestamp(9999999999999)
        assert result == "(invalid)"

    def test_format_timestamp_format_too_long(self) -> None:
        """Fallback to default when format string too long."""
        long_fmt = "Y" * 100
        result = format_timestamp(1706234567, fmt=long_fmt, tz="UTC")
        # Should use default format, not the long one
        assert "2024-01-26" in result

    def test_format_timestamp_invalid_format_chars(self) -> None:
        """Fallback to default when format has invalid chars."""
        result = format_timestamp(1706234567, fmt="YYYY<script>", tz="UTC")
        # Should use default format due to invalid chars
        assert "2024-01-26" in result

    def test_format_timestamp_invalid_timezone(self) -> None:
        """Use local timezone when invalid timezone provided."""
        result = format_timestamp(1706234567, tz="Invalid/Timezone")
        # Should still produce valid output using local timezone
        assert "2024" in result

    def test_format_timestamp_timezone_too_long(self) -> None:
        """Use local timezone when timezone string too long."""
        long_tz = "X" * 100
        result = format_timestamp(1706234567, tz=long_tz)
        # Should still produce valid output using local timezone
        assert "2024" in result

    def test_format_timestamp_empty_format(self) -> None:
        """Empty format string falls back to default."""
        result = format_timestamp(1706234567, fmt="", tz="UTC")
        # Should use default format
        assert "2024-01-26" in result

    def test_format_timestamp_empty_timezone(self) -> None:
        """Empty timezone string falls back to local."""
        result = format_timestamp(1706234567, tz="")
        # Should still produce valid output using local timezone
        assert "2024" in result


class TestFormattingConfigFallbacks:
    """Tests for config loading fallbacks in formatting module."""

    def test_format_timestamp_pendulum_exception(self) -> None:
        """Handle pendulum exception during formatting."""
        from unittest.mock import patch

        import pendulum

        # Patch pendulum.from_timestamp to raise an exception
        with patch.object(pendulum, "from_timestamp", side_effect=Exception("Pendulum error")):
            from kstlib.utils.formatting import format_timestamp

            result = format_timestamp(1706234567, tz="UTC")
            assert result == "(invalid)"


class TestValidateFunctions:
    """Tests for internal validation functions."""

    def test_validate_format_string_none(self) -> None:
        """None format returns default."""
        from kstlib.utils.formatting import DEFAULT_DATETIME_FORMAT, _validate_format_string

        # Testing runtime behavior with wrong type (deep defense)
        result = _validate_format_string(None)  # type: ignore[arg-type]
        assert result == DEFAULT_DATETIME_FORMAT

    def test_validate_format_string_non_string(self) -> None:
        """Non-string format returns default."""
        from kstlib.utils.formatting import DEFAULT_DATETIME_FORMAT, _validate_format_string

        # Testing runtime behavior with wrong type (deep defense)
        result = _validate_format_string(123)  # type: ignore[arg-type]
        assert result == DEFAULT_DATETIME_FORMAT

    def test_validate_timezone_none(self) -> None:
        """None timezone returns local."""
        from kstlib.utils.formatting import _validate_timezone

        # Testing runtime behavior with wrong type (deep defense)
        result = _validate_timezone(None)  # type: ignore[arg-type]
        assert result == "local"

    def test_validate_timezone_non_string(self) -> None:
        """Non-string timezone returns local."""
        from kstlib.utils.formatting import _validate_timezone

        # Testing runtime behavior with wrong type (deep defense)
        result = _validate_timezone(123)  # type: ignore[arg-type]
        assert result == "local"
