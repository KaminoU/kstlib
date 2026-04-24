"""Tests for ``_normalize_includes`` in :mod:`kstlib.config.loader`.

Covers the hardening of the ``include`` YAML key against the
``TypeError: 'NoneType' object is not iterable`` foot-gun that
previously surfaced when an author left ``include:`` with an empty
body (or commented out every sub-item). See
fix-circular-import-mail (2026-04-24) bundle.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from kstlib.config.exceptions import ConfigFormatError
from kstlib.config.loader import _normalize_includes

_SOURCE_PATH = Path("/tmp/corporate.yml")


# ----------------------------------------------------------------------------
# Silent (no warning, no error, returns empty list)
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        "",
        "   ",
    ],
    ids=[
        "none",
        "empty_list",
        "empty_string",
        "whitespace_only_string",
    ],
)
def test_silent_empty_cases_return_empty_list(
    raw: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Empty/missing ``include`` values produce ``[]`` with no log output."""
    with caplog.at_level(logging.WARNING, logger="kstlib.config.loader"):
        result = _normalize_includes(raw, _SOURCE_PATH)
    assert result == []
    assert caplog.records == []


def test_absent_key_returns_empty_list() -> None:
    """``data.pop('include', [])`` on an absent key produces ``[]``.

    Simulates the call-site pattern where the YAML does not declare an
    ``include`` key at all.
    """
    data: dict[str, Any] = {"app": {"name": "demo"}}
    raw = data.pop("include", [])
    assert _normalize_includes(raw, _SOURCE_PATH) == []


# ----------------------------------------------------------------------------
# Nominal
# ----------------------------------------------------------------------------


def test_single_string_wrapped_as_list() -> None:
    """A non-empty string is wrapped into a single-element list."""
    assert _normalize_includes("sub.yml", _SOURCE_PATH) == ["sub.yml"]


def test_single_string_is_stripped() -> None:
    """Leading/trailing whitespace in a string value is stripped."""
    assert _normalize_includes("  sub.yml  ", _SOURCE_PATH) == ["sub.yml"]


def test_list_of_strings_preserved() -> None:
    """A clean list of strings is returned unchanged except for stripping."""
    assert _normalize_includes(["a.yml", "b.yml"], _SOURCE_PATH) == [
        "a.yml",
        "b.yml",
    ]


def test_list_entries_are_stripped() -> None:
    """Individual list entries are stripped of surrounding whitespace."""
    assert _normalize_includes(["  a.yml", "b.yml  ", " c.yml "], _SOURCE_PATH) == [
        "a.yml",
        "b.yml",
        "c.yml",
    ]


# ----------------------------------------------------------------------------
# Warning + filter
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (["a.yml", None, "b.yml"], ["a.yml", "b.yml"]),
        (["a.yml", "", "b.yml"], ["a.yml", "b.yml"]),
        (["a.yml", "   ", "b.yml"], ["a.yml", "b.yml"]),
    ],
    ids=[
        "none_middle",
        "empty_string_middle",
        "whitespace_middle",
    ],
)
def test_single_dropped_entry_logs_warning(
    raw: list[Any],
    expected: list[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Dropping one empty entry yields the cleaned list and one warning."""
    with caplog.at_level(logging.WARNING, logger="kstlib.config.loader"):
        result = _normalize_includes(raw, _SOURCE_PATH)
    assert result == expected
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.WARNING
    message = record.getMessage()
    assert str(_SOURCE_PATH) in message
    assert "dropped 1 empty entries" in message
    assert "[1]" in message


def test_multiple_dropped_entries_reports_all_indices(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Warning message reports the count and every original drop index."""
    raw = ["a.yml", None, "b.yml", "", "c.yml", "   "]
    with caplog.at_level(logging.WARNING, logger="kstlib.config.loader"):
        result = _normalize_includes(raw, _SOURCE_PATH)
    assert result == ["a.yml", "b.yml", "c.yml"]
    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "dropped 3 empty entries" in message
    assert "[1, 3, 5]" in message
    assert str(_SOURCE_PATH) in message


# ----------------------------------------------------------------------------
# ConfigFormatError (illegitimate types)
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected_type_name"),
    [
        (42, "int"),
        (3.14, "float"),
        ({"foo": "bar"}, "dict"),
        ((1, 2), "tuple"),
    ],
    ids=["int", "float", "dict", "tuple"],
)
def test_illegitimate_top_level_type_raises(raw: Any, expected_type_name: str) -> None:
    """Top-level values that are not ``None``, ``str``, or ``list`` raise."""
    with pytest.raises(ConfigFormatError) as exc:
        _normalize_includes(raw, _SOURCE_PATH)
    message = str(exc.value)
    assert "include must be string or list" in message
    assert expected_type_name in message
    assert str(_SOURCE_PATH) in message


def test_non_string_list_item_raises_with_index() -> None:
    """A non-string list item raises ``ConfigFormatError`` naming its index."""
    with pytest.raises(ConfigFormatError) as exc:
        _normalize_includes(["a.yml", 42, "b.yml"], _SOURCE_PATH)
    message = str(exc.value)
    assert "include[1]" in message
    assert "int" in message
    assert str(_SOURCE_PATH) in message


def test_dict_list_item_raises_with_index() -> None:
    """A dict inside the include list also triggers the indexed error."""
    with pytest.raises(ConfigFormatError) as exc:
        _normalize_includes(["a.yml", {"bad": "thing"}, "b.yml"], _SOURCE_PATH)
    message = str(exc.value)
    assert "include[1]" in message
    assert "dict" in message


def test_illegitimate_item_raises_before_subsequent_validation() -> None:
    """The first illegitimate item raises immediately (no partial list)."""
    with pytest.raises(ConfigFormatError):
        _normalize_includes([42, "b.yml"], _SOURCE_PATH)


# ----------------------------------------------------------------------------
# Integration with _load_with_includes call site (regression for the empty include bug)
# ----------------------------------------------------------------------------


def test_load_with_includes_survives_empty_include_key(tmp_path: Path) -> None:
    """The original footgun: ``include:`` with empty body no longer explodes.

    Before the fix, this YAML raised ``TypeError: 'NoneType' object is
    not iterable`` deep inside ``_load_with_includes``. The fix routes the
    raw value through ``_normalize_includes``, which maps ``None`` to ``[]``
    silently.
    """
    from kstlib.config.loader import _load_with_includes

    config_file = tmp_path / "corporate.yml"
    config_file.write_text(
        "include:\napp:\n  name: demo\n",
        encoding="utf-8",
    )
    result = _load_with_includes(config_file)
    assert result == {"app": {"name": "demo"}}


def test_load_with_includes_warns_on_null_list_item(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """End-to-end check: null list items get dropped with a single warning."""
    from kstlib.config.loader import _load_with_includes

    sub_a = tmp_path / "a.yml"
    sub_a.write_text("a_key: 1\n", encoding="utf-8")
    sub_b = tmp_path / "b.yml"
    sub_b.write_text("b_key: 2\n", encoding="utf-8")

    config_file = tmp_path / "corporate.yml"
    config_file.write_text(
        "include:\n  - a.yml\n  -\n  - b.yml\napp:\n  name: demo\n",
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger="kstlib.config.loader"):
        result = _load_with_includes(config_file)

    assert result == {"a_key": 1, "b_key": 2, "app": {"name": "demo"}}
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "dropped 1 empty entries" in warnings[0].getMessage()
    assert "[1]" in warnings[0].getMessage()
