"""Dictionary utilities."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any


def deep_merge(
    base: dict[str, Any],
    updates: Mapping[str, Any],
    *,
    deep_copy: bool = False,
) -> dict[str, Any]:
    """Recursively merge updates into base dictionary (in place).

    Args:
        base: Base dictionary to update (modified in place).
        updates: Dictionary with updates to merge.
        deep_copy: If True, deep copy values before assignment.

    Returns:
        The modified base dictionary (for chaining).

    Examples:
        >>> base = {"a": {"x": 1}, "b": 2}
        >>> deep_merge(base, {"a": {"y": 2}, "c": 3})
        {'a': {'x': 1, 'y': 2}, 'b': 2, 'c': 3}
    """
    for key, value in updates.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, Mapping):
            deep_merge(base[key], value, deep_copy=deep_copy)
        else:
            base[key] = copy.deepcopy(value) if deep_copy else value
    return base
