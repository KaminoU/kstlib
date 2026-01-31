"""Utility helpers shared across kstlib modules."""

# pylint: disable=duplicate-code
from kstlib.utils.dict import deep_merge
from kstlib.utils.formatting import (
    format_bytes,
    format_count,
    format_duration,
    format_time_delta,
    format_timestamp,
    parse_size_string,
)
from kstlib.utils.http_trace import (
    DEFAULT_SENSITIVE_KEYS,
    HTTPTraceLogger,
    create_trace_event_hooks,
)
from kstlib.utils.lazy import lazy_factory
from kstlib.utils.secure_delete import SecureDeleteMethod, SecureDeleteReport, secure_delete
from kstlib.utils.text import replace_placeholders
from kstlib.utils.validators import (
    EmailAddress,
    ValidationError,
    normalize_address_list,
    parse_email_address,
)

__all__ = [
    "DEFAULT_SENSITIVE_KEYS",
    "EmailAddress",
    "HTTPTraceLogger",
    "SecureDeleteMethod",
    "SecureDeleteReport",
    "ValidationError",
    "create_trace_event_hooks",
    "deep_merge",
    "format_bytes",
    "format_count",
    "format_duration",
    "format_time_delta",
    "format_timestamp",
    "lazy_factory",
    "normalize_address_list",
    "parse_email_address",
    "parse_size_string",
    "replace_placeholders",
    "secure_delete",
]
