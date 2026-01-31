"""Deep defense tests for XSS prevention in monitoring render types.

Every user-controlled string that enters HTML output is tested against
a battery of XSS payloads. Each render type is tested in both class
and inline CSS modes, since the code paths differ.

Attack surface inventory:
    - StatusCell.label
    - MonitorMetric.value, .label, .unit
    - MonitorKV.title, .items keys, .items values
    - MonitorList.title, .items
    - MonitorTable.title, .headers, cell values
"""

from __future__ import annotations

import re

import pytest

from kstlib.monitoring.cell import StatusCell
from kstlib.monitoring.kv import MonitorKV
from kstlib.monitoring.list import MonitorList
from kstlib.monitoring.metric import MonitorMetric
from kstlib.monitoring.table import MonitorTable
from kstlib.monitoring.types import StatusLevel

# ---------------------------------------------------------------------------
# XSS payload battery
# ---------------------------------------------------------------------------

#: Payloads containing HTML markup that must be escaped via html.escape().
#: These all contain ``<``, ``>``, ``"``, ``'``, or ``&`` which html.escape()
#: neutralizes.  Protocol-based payloads like ``javascript:`` are NOT dangerous
#: in text content (only in href/src attributes, which we never generate from
#: user input).
XSS_TAG_PAYLOADS: list[str] = [
    "<script>alert('xss')</script>",
    '<img src=x onerror="alert(1)">',
    "<svg/onload=alert(1)>",
    '"><script>alert(1)</script>',
    "' onclick='alert(1)",
    "<iframe src='javascript:alert(1)'>",
    "<body onload=alert(1)>",
    '<input onfocus=alert(1) autofocus="">',
    "<marquee onstart=alert(1)>",
]

#: Regex matching raw (unescaped) HTML tags in output.
#: Allows only the safe tags our renderers produce.
RAW_TAG_RE = re.compile(r"<(?!/?(?:span|div|table|thead|tbody|tr|th|td|dl|dt|dd|ul|ol|li|h3|style)\b)[a-zA-Z]")


def _assert_no_raw_payload(output: str, payload: str) -> None:
    """Assert that the raw payload does not appear unescaped in the output.

    Checks that:
    1. The literal payload string is not present.
    2. No unexpected HTML tags snuck through.
    """
    assert payload not in output, f"Raw XSS payload found in output: {payload!r}"
    # Ensure no unexpected tags (only our known safe tags)
    unexpected = RAW_TAG_RE.findall(output)
    for tag_start in unexpected:
        raise AssertionError(f"Unexpected HTML tag fragment in output: {tag_start!r}")


# ============================================================================
# StatusCell XSS
# ============================================================================


class TestStatusCellXSS:
    """XSS prevention for StatusCell.label."""

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_label_class_mode(self, payload: str) -> None:
        """Malicious label is escaped in class mode."""
        cell = StatusCell(payload, StatusLevel.OK)
        output = cell.render(inline_css=False)
        _assert_no_raw_payload(output, payload)

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_label_inline_mode(self, payload: str) -> None:
        """Malicious label is escaped in inline mode."""
        cell = StatusCell(payload, StatusLevel.OK)
        output = cell.render(inline_css=True)
        _assert_no_raw_payload(output, payload)


# ============================================================================
# MonitorMetric XSS
# ============================================================================


class TestMonitorMetricXSS:
    """XSS prevention for MonitorMetric.value, .label, .unit."""

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_value_class_mode(self, payload: str) -> None:
        """Malicious value is escaped in class mode."""
        m = MonitorMetric(payload)
        output = m.render(inline_css=False)
        _assert_no_raw_payload(output, payload)

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_value_inline_mode(self, payload: str) -> None:
        """Malicious value is escaped in inline mode."""
        m = MonitorMetric(payload)
        output = m.render(inline_css=True)
        _assert_no_raw_payload(output, payload)

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_label_class_mode(self, payload: str) -> None:
        """Malicious label is escaped in class mode."""
        m = MonitorMetric(0, label=payload)
        output = m.render(inline_css=False)
        _assert_no_raw_payload(output, payload)

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_label_inline_mode(self, payload: str) -> None:
        """Malicious label is escaped in inline mode."""
        m = MonitorMetric(0, label=payload)
        output = m.render(inline_css=True)
        _assert_no_raw_payload(output, payload)

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_unit_class_mode(self, payload: str) -> None:
        """Malicious unit is escaped in class mode."""
        m = MonitorMetric(0, unit=payload)
        output = m.render(inline_css=False)
        _assert_no_raw_payload(output, payload)

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_unit_inline_mode(self, payload: str) -> None:
        """Malicious unit is escaped in inline mode."""
        m = MonitorMetric(0, unit=payload)
        output = m.render(inline_css=True)
        _assert_no_raw_payload(output, payload)


# ============================================================================
# MonitorKV XSS
# ============================================================================


class TestMonitorKVXSS:
    """XSS prevention for MonitorKV.title, .items keys, .items values."""

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_title_class_mode(self, payload: str) -> None:
        """Malicious title is escaped in class mode."""
        kv = MonitorKV({"k": "v"}, title=payload)
        output = kv.render(inline_css=False)
        _assert_no_raw_payload(output, payload)

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_title_inline_mode(self, payload: str) -> None:
        """Malicious title is escaped in inline mode."""
        kv = MonitorKV({"k": "v"}, title=payload)
        output = kv.render(inline_css=True)
        _assert_no_raw_payload(output, payload)

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_key_class_mode(self, payload: str) -> None:
        """Malicious key is escaped in class mode."""
        kv = MonitorKV({payload: "v"})
        output = kv.render(inline_css=False)
        _assert_no_raw_payload(output, payload)

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_key_inline_mode(self, payload: str) -> None:
        """Malicious key is escaped in inline mode."""
        kv = MonitorKV({payload: "v"})
        output = kv.render(inline_css=True)
        _assert_no_raw_payload(output, payload)

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_value_class_mode(self, payload: str) -> None:
        """Malicious value is escaped in class mode."""
        kv = MonitorKV({"k": payload})
        output = kv.render(inline_css=False)
        _assert_no_raw_payload(output, payload)

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_value_inline_mode(self, payload: str) -> None:
        """Malicious value is escaped in inline mode."""
        kv = MonitorKV({"k": payload})
        output = kv.render(inline_css=True)
        _assert_no_raw_payload(output, payload)


# ============================================================================
# MonitorList XSS
# ============================================================================


class TestMonitorListXSS:
    """XSS prevention for MonitorList.title, .items."""

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_title_class_mode(self, payload: str) -> None:
        """Malicious title is escaped in class mode."""
        ml = MonitorList(["a"], title=payload)
        output = ml.render(inline_css=False)
        _assert_no_raw_payload(output, payload)

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_title_inline_mode(self, payload: str) -> None:
        """Malicious title is escaped in inline mode."""
        ml = MonitorList(["a"], title=payload)
        output = ml.render(inline_css=True)
        _assert_no_raw_payload(output, payload)

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_item_class_mode(self, payload: str) -> None:
        """Malicious item is escaped in class mode."""
        ml = MonitorList([payload])
        output = ml.render(inline_css=False)
        _assert_no_raw_payload(output, payload)

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_item_inline_mode(self, payload: str) -> None:
        """Malicious item is escaped in inline mode."""
        ml = MonitorList([payload])
        output = ml.render(inline_css=True)
        _assert_no_raw_payload(output, payload)


# ============================================================================
# MonitorTable XSS
# ============================================================================


class TestMonitorTableXSS:
    """XSS prevention for MonitorTable.title, .headers, cell values."""

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_title_class_mode(self, payload: str) -> None:
        """Malicious title is escaped in class mode."""
        t = MonitorTable(headers=["A"], title=payload)
        output = t.render(inline_css=False)
        _assert_no_raw_payload(output, payload)

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_title_inline_mode(self, payload: str) -> None:
        """Malicious title is escaped in inline mode."""
        t = MonitorTable(headers=["A"], title=payload)
        output = t.render(inline_css=True)
        _assert_no_raw_payload(output, payload)

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_header_class_mode(self, payload: str) -> None:
        """Malicious header is escaped in class mode."""
        t = MonitorTable(headers=[payload])
        output = t.render(inline_css=False)
        _assert_no_raw_payload(output, payload)

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_header_inline_mode(self, payload: str) -> None:
        """Malicious header is escaped in inline mode."""
        t = MonitorTable(headers=[payload])
        output = t.render(inline_css=True)
        _assert_no_raw_payload(output, payload)

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_cell_class_mode(self, payload: str) -> None:
        """Malicious cell value is escaped in class mode."""
        t = MonitorTable(headers=["H"])
        t.add_row([payload])
        output = t.render(inline_css=False)
        _assert_no_raw_payload(output, payload)

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_cell_inline_mode(self, payload: str) -> None:
        """Malicious cell value is escaped in inline mode."""
        t = MonitorTable(headers=["H"])
        t.add_row([payload])
        output = t.render(inline_css=True)
        _assert_no_raw_payload(output, payload)


# ============================================================================
# Compound injection (XSS via StatusCell embedded in containers)
# ============================================================================


class TestCompoundInjection:
    """XSS via StatusCell labels when embedded in container types."""

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_cell_in_table(self, payload: str) -> None:
        """Malicious StatusCell label is escaped inside MonitorTable."""
        cell = StatusCell(payload, StatusLevel.ERROR)
        t = MonitorTable(headers=["Status"])
        t.add_row([cell])
        output = t.render(inline_css=False)
        _assert_no_raw_payload(output, payload)

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_cell_in_table_inline(self, payload: str) -> None:
        """Malicious StatusCell label is escaped inside MonitorTable (inline)."""
        cell = StatusCell(payload, StatusLevel.ERROR)
        t = MonitorTable(headers=["Status"])
        t.add_row([cell])
        output = t.render(inline_css=True)
        _assert_no_raw_payload(output, payload)

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_cell_in_kv(self, payload: str) -> None:
        """Malicious StatusCell label is escaped inside MonitorKV."""
        cell = StatusCell(payload, StatusLevel.ERROR)
        kv = MonitorKV({"Status": cell})
        output = kv.render(inline_css=False)
        _assert_no_raw_payload(output, payload)

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_cell_in_kv_inline(self, payload: str) -> None:
        """Malicious StatusCell label is escaped inside MonitorKV (inline)."""
        cell = StatusCell(payload, StatusLevel.ERROR)
        kv = MonitorKV({"Status": cell})
        output = kv.render(inline_css=True)
        _assert_no_raw_payload(output, payload)

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_cell_in_list(self, payload: str) -> None:
        """Malicious StatusCell label is escaped inside MonitorList."""
        cell = StatusCell(payload, StatusLevel.ERROR)
        ml = MonitorList([cell])
        output = ml.render(inline_css=False)
        _assert_no_raw_payload(output, payload)

    @pytest.mark.parametrize("payload", XSS_TAG_PAYLOADS)
    def test_cell_in_list_inline(self, payload: str) -> None:
        """Malicious StatusCell label is escaped inside MonitorList (inline)."""
        cell = StatusCell(payload, StatusLevel.ERROR)
        ml = MonitorList([cell])
        output = ml.render(inline_css=True)
        _assert_no_raw_payload(output, payload)


# ============================================================================
# Multi-vector simultaneous injection
# ============================================================================


class TestMultiVectorInjection:
    """Simultaneous injection in multiple fields of the same object."""

    def test_table_all_fields(self) -> None:
        """XSS payloads in title + header + cell simultaneously."""
        payload_a = "<script>steal(document.cookie)</script>"
        payload_b = '<img src=x onerror="fetch(evil)">'
        payload_c = "<svg/onload=alert(1)>"
        t = MonitorTable(headers=[payload_b], title=payload_a)
        t.add_row([payload_c])
        for inline in (False, True):
            output = t.render(inline_css=inline)
            _assert_no_raw_payload(output, payload_a)
            _assert_no_raw_payload(output, payload_b)
            _assert_no_raw_payload(output, payload_c)

    def test_kv_all_fields(self) -> None:
        """XSS payloads in title + key + value simultaneously."""
        xss = "<script>alert(1)</script>"
        kv = MonitorKV({xss: xss}, title=xss)
        for inline in (False, True):
            output = kv.render(inline_css=inline)
            _assert_no_raw_payload(output, xss)

    def test_metric_all_fields(self) -> None:
        """XSS payloads in value + label + unit simultaneously."""
        xss = '<img onerror="alert(1)" src=x>'
        m = MonitorMetric(xss, label=xss, unit=xss)
        for inline in (False, True):
            output = m.render(inline_css=inline)
            _assert_no_raw_payload(output, xss)


# ============================================================================
# Attribute breakout attacks
# ============================================================================


class TestAttributeBreakout:
    """Attempts to break out of HTML attribute contexts."""

    def test_double_quote_breakout_cell(self) -> None:
        """Double-quote in label cannot escape span attribute."""
        cell = StatusCell('" onmouseover="alert(1)" x="', StatusLevel.OK)
        output = cell.render(inline_css=True)
        assert "onmouseover" not in output or "&quot;" in output
        assert output.count('onmouseover="alert(1)"') == 0

    def test_single_quote_breakout_cell(self) -> None:
        """Single-quote in label cannot escape span attribute."""
        cell = StatusCell("' onmouseover='alert(1)' x='", StatusLevel.OK)
        output = cell.render(inline_css=True)
        # html.escape with quote=True escapes both ' and "
        assert "&#x27;" in output or "&apos;" in output or "'" not in output.split("style=")[1].split(">")[1]

    def test_angle_bracket_breakout(self) -> None:
        """Angle brackets in label cannot create new tags."""
        cell = StatusCell("</span><script>alert(1)</script><span>", StatusLevel.OK)
        output = cell.render()
        assert "<script>" not in output
        assert "</span><script>" not in output
