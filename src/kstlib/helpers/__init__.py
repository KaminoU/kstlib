"""Helper utilities for time-based operations.

This module provides utilities for time-based triggering and scheduling:

- **TimeTrigger**: Detect time boundaries (modulo-based) for periodic operations

Examples:
    Check if current time is at a 4-hour boundary:

    >>> from kstlib.helpers import TimeTrigger
    >>> trigger = TimeTrigger("4h")
    >>> trigger.is_at_boundary()  # doctest: +SKIP
    True  # If current time is 00:00, 04:00, 08:00, etc.

    Get time until next boundary:

    >>> trigger.time_until_next()  # doctest: +SKIP
    3542.5  # Seconds until next 4-hour mark

    Use with WebSocket for periodic restart:

    >>> trigger = TimeTrigger("8h")
    >>> if trigger.should_trigger(margin=60):  # doctest: +SKIP
    ...     await ws.shutdown()
    ...     await ws.connect()
"""

from kstlib.helpers.exceptions import InvalidModuloError, TimeTriggerError
from kstlib.helpers.time_trigger import TimeTrigger

__all__ = [
    "InvalidModuloError",
    "TimeTrigger",
    "TimeTriggerError",
]
