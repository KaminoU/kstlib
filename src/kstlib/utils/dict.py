"""Dictionary utilities."""

from __future__ import annotations

__all__ = ["deep_merge"]

import copy
from collections.abc import Mapping
from typing import Any

#: Maximum recursion depth for deep_merge to prevent stack overflow on
#: pathological input (e.g. deeply nested YAML from untrusted sources).
MAX_MERGE_DEPTH = 32


def deep_merge(
    base: dict[str, Any],
    updates: Mapping[str, Any],
    *,
    deep_copy: bool = False,
    _depth: int = 0,
) -> dict[str, Any]:
    """Recursively merge updates into base dictionary (in place).

    Args:
        base: Base dictionary to update (modified in place).
        updates: Dictionary with updates to merge.
        deep_copy: If True, deep copy values before assignment.
        _depth: Internal recursion counter (do not set manually).

    Returns:
        The modified base dictionary (for chaining).

    Raises:
        RecursionError: If nesting exceeds MAX_MERGE_DEPTH.

    Examples:
        >>> base = {"a": {"x": 1}, "b": 2}
        >>> deep_merge(base, {"a": {"y": 2}, "c": 3})
        {'a': {'x': 1, 'y': 2}, 'b': 2, 'c': 3}
    """
    if _depth > MAX_MERGE_DEPTH:
        raise RecursionError(f"deep_merge exceeded maximum depth ({MAX_MERGE_DEPTH})")
    for key, value in updates.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, Mapping):
            deep_merge(base[key], value, deep_copy=deep_copy, _depth=_depth + 1)
        else:
            base[key] = copy.deepcopy(value) if deep_copy else value
    return base
