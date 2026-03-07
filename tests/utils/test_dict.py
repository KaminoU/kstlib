"""Tests for dictionary utilities."""

from typing import Any

import pytest

from kstlib.utils.dict import MAX_MERGE_DEPTH, deep_merge


class TestDeepMerge:
    """Tests for deep_merge function."""

    def test_basic_merge(self) -> None:
        """Merge two flat dictionaries."""
        base = {"a": 1, "b": 2}
        result = deep_merge(base, {"b": 3, "c": 4})
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self) -> None:
        """Merge nested dictionaries recursively."""
        base = {"a": {"x": 1}, "b": 2}
        result = deep_merge(base, {"a": {"y": 2}, "c": 3})
        assert result == {"a": {"x": 1, "y": 2}, "b": 2, "c": 3}

    def test_rejects_excessive_depth(self) -> None:
        """Raise RecursionError when nesting exceeds MAX_MERGE_DEPTH."""
        # Build a dict nested deeper than MAX_MERGE_DEPTH
        depth = MAX_MERGE_DEPTH + 5
        base: dict[str, Any] = {}
        updates: dict[str, Any] = {}
        current_base = base
        current_updates = updates
        for i in range(depth):
            current_base["level"] = {}
            current_updates["level"] = {}
            current_base = current_base["level"]
            current_updates = current_updates["level"]
        current_base["value"] = 1
        current_updates["value"] = 2

        with pytest.raises(RecursionError, match="maximum depth"):
            deep_merge(base, updates)

    def test_normal_depth_works(self) -> None:
        """Nesting within MAX_MERGE_DEPTH succeeds."""
        base: dict[str, Any] = {}
        updates: dict[str, Any] = {}
        current_base = base
        current_updates = updates
        for _ in range(10):
            current_base["level"] = {}
            current_updates["level"] = {}
            current_base = current_base["level"]
            current_updates = current_updates["level"]
        current_base["value"] = 1
        current_updates["value"] = 2

        result = deep_merge(base, updates)
        # Navigate to the deepest level
        node = result
        for _ in range(10):
            node = node["level"]
        assert node["value"] == 2
