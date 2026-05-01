"""Tests for the NotifyCollector class."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest

from kstlib.mail import NotifyCollector, NotifyResult
from kstlib.monitoring import MonitorTable, StatusCell


def _make_result(
    *,
    name: str = "fn",
    success: bool = True,
    duration_ms: float = 10.0,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    return_value: object = None,
    exception: BaseException | None = None,
    traceback_str: str | None = None,
) -> NotifyResult:
    """Build a NotifyResult with sensible defaults for tests."""
    started = started_at or datetime(2026, 4, 25, 12, 0, 0, tzinfo=timezone.utc)
    ended = ended_at or started + timedelta(milliseconds=duration_ms)
    return NotifyResult(
        function_name=name,
        success=success,
        started_at=started,
        ended_at=ended,
        duration_ms=duration_ms,
        return_value=return_value,
        exception=exception,
        traceback_str=traceback_str,
    )


class TestInit:
    """Tests for NotifyCollector construction."""

    def test_default_maxsize(self) -> None:
        """Default maxsize is 1000."""
        collector = NotifyCollector()
        assert collector.maxsize == 1000

    def test_custom_maxsize(self) -> None:
        """Custom maxsize is honored."""
        collector = NotifyCollector(maxsize=42)
        assert collector.maxsize == 42

    def test_zero_maxsize_rejected(self) -> None:
        """Maxsize must be positive (zero rejected)."""
        with pytest.raises(ValueError, match="positive"):
            NotifyCollector(maxsize=0)

    def test_negative_maxsize_rejected(self) -> None:
        """Maxsize must be positive (negative rejected)."""
        with pytest.raises(ValueError, match="positive"):
            NotifyCollector(maxsize=-5)

    def test_non_int_maxsize_rejected(self) -> None:
        """Maxsize must be an int."""
        with pytest.raises(ValueError, match="positive"):
            NotifyCollector(maxsize="100")  # type: ignore[arg-type]


class TestAdd:
    """Tests for the add method."""

    def test_add_single_result(self) -> None:
        """add records a result and increments total_count."""
        collector = NotifyCollector()
        collector.add(_make_result())
        assert collector.total_count == 1

    def test_add_respects_maxsize_fifo(self) -> None:
        """When maxsize reached, oldest entries are evicted FIFO."""
        collector = NotifyCollector(maxsize=3)
        for i in range(5):
            collector.add(_make_result(name=f"fn{i}"))
        names = [r.function_name for r in collector.results]
        assert names == ["fn2", "fn3", "fn4"]
        assert collector.total_count == 3


class TestReset:
    """Tests for the reset method."""

    def test_reset_clears(self) -> None:
        """reset removes every recorded result."""
        collector = NotifyCollector()
        collector.add(_make_result())
        collector.add(_make_result())
        collector.reset()
        assert collector.total_count == 0
        assert collector.results == []


class TestResultsSnapshot:
    """Tests for the results property."""

    def test_results_is_snapshot_copy(self) -> None:
        """Mutating the returned list does not affect the collector."""
        collector = NotifyCollector()
        collector.add(_make_result(name="a"))
        snapshot = collector.results
        snapshot.clear()
        assert collector.total_count == 1
        assert collector.results[0].function_name == "a"

    def test_results_in_insertion_order(self) -> None:
        """results preserves insertion order."""
        collector = NotifyCollector()
        for name in ["c", "a", "b"]:
            collector.add(_make_result(name=name))
        assert [r.function_name for r in collector.results] == ["c", "a", "b"]


class TestCounts:
    """Tests for ok_count / ko_count."""

    def test_ok_ko_counts(self) -> None:
        """ok_count and ko_count reflect the recorded results."""
        collector = NotifyCollector()
        collector.add(_make_result(name="a", success=True))
        collector.add(_make_result(name="b", success=False, exception=ValueError("x")))
        collector.add(_make_result(name="c", success=True))
        assert collector.ok_count == 2
        assert collector.ko_count == 1
        assert collector.total_count == 3

    def test_counts_empty(self) -> None:
        """Empty collector reports zero counts."""
        collector = NotifyCollector()
        assert collector.ok_count == 0
        assert collector.ko_count == 0
        assert collector.total_count == 0


class TestThreadSafety:
    """Stress tests for thread-safety."""

    def test_concurrent_adds_no_loss(self) -> None:
        """100 threads x 50 adds yields exactly 5000 entries (within bounded size)."""
        n_threads = 100
        per_thread = 50
        total = n_threads * per_thread
        collector = NotifyCollector(maxsize=total + 10)

        def worker(idx: int) -> None:
            for j in range(per_thread):
                collector.add(_make_result(name=f"t{idx}-{j}"))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert collector.total_count == total


class TestRenderHtml:
    """Tests for render_html."""

    def test_render_html_contains_function_names(self) -> None:
        """render_html includes function names, statuses, and durations.

        Uses redact_user_data=False to assert the legacy verbatim detail.
        See TestRedactUserData below for the default behaviour.
        """
        collector = NotifyCollector(redact_user_data=False)
        collector.add(_make_result(name="check_a", success=True, duration_ms=12.5))
        collector.add(_make_result(name="check_b", success=False, exception=ValueError("boom")))
        out = collector.render_html()
        assert "check_a" in out
        assert "check_b" in out
        assert "OK" in out
        assert "FAILED" in out
        assert "12.50" in out
        assert "ValueError: boom" in out

    def test_render_html_escapes_function_names(self) -> None:
        """render_html escapes HTML characters in function names."""
        collector = NotifyCollector()
        collector.add(_make_result(name="<script>", success=True))
        out = collector.render_html()
        assert "<script>" not in out
        assert "&lt;script&gt;" in out

    def test_render_html_includes_tracebacks_block(self) -> None:
        """render_html appends tracebacks block when failures carry one.

        Tracebacks expose user-code locals so they are suppressed by
        default; opt-out via redact_user_data=False to view them.
        """
        collector = NotifyCollector(redact_user_data=False)
        collector.add(
            _make_result(
                name="failing",
                success=False,
                exception=RuntimeError("nope"),
                traceback_str="Traceback (most recent call last):\n  File ...",
            )
        )
        out = collector.render_html()
        assert "<details" in out
        assert "Tracebacks" in out
        assert "Traceback (most recent call last)" in out

    def test_render_html_no_tracebacks_when_disabled(self) -> None:
        """Tracebacks block is omitted when include_tracebacks=False."""
        collector = NotifyCollector(redact_user_data=False)
        collector.add(
            _make_result(
                name="failing",
                success=False,
                exception=RuntimeError("nope"),
                traceback_str="Traceback...",
            )
        )
        out = collector.render_html(include_tracebacks=False)
        assert "<details" not in out
        assert "Tracebacks" not in out

    def test_render_html_truncates_long_detail(self) -> None:
        """Long exception messages are truncated with ellipsis."""
        long_msg = "x" * 500
        collector = NotifyCollector(redact_user_data=False)
        collector.add(_make_result(success=False, exception=ValueError(long_msg)))
        out = collector.render_html()
        assert "..." in out
        assert "x" * 500 not in out


class TestRenderPlain:
    """Tests for render_plain."""

    def test_render_plain_contains_summary_and_rows(self) -> None:
        """render_plain produces a header summary and one line per result.

        Uses redact_user_data=False to keep verbatim exception detail
        for assertion. See TestRedactUserData for the default behaviour.
        """
        collector = NotifyCollector(redact_user_data=False)
        collector.add(_make_result(name="ok_fn", success=True, duration_ms=5.0))
        collector.add(_make_result(name="ko_fn", success=False, exception=ValueError("x")))
        out = collector.render_plain()
        assert "Summary: 2 total (OK: 1, FAILED: 1)" in out
        assert "[OK] ok_fn" in out
        assert "[FAILED] ko_fn" in out
        assert "ValueError: x" in out


class TestToMonitorTable:
    """Tests for to_monitor_table."""

    def test_to_monitor_table_returns_valid_table(self) -> None:
        """to_monitor_table returns a populated MonitorTable."""
        collector = NotifyCollector()
        collector.add(_make_result(name="a", success=True, duration_ms=1.0))
        collector.add(_make_result(name="b", success=False, exception=ValueError("x")))

        table = collector.to_monitor_table()
        assert isinstance(table, MonitorTable)
        assert table.headers == ["Function", "Status", "Started", "Duration (ms)", "Detail"]
        assert table.row_count == 2
        rendered = table.render()
        assert "a" in rendered
        assert "b" in rendered

    def test_to_monitor_table_uses_status_cells(self) -> None:
        """Status column uses StatusCell instances with proper levels."""
        from kstlib.monitoring import StatusLevel

        collector = NotifyCollector()
        collector.add(_make_result(name="ok", success=True))
        collector.add(_make_result(name="ko", success=False, exception=RuntimeError("x")))

        table = collector.to_monitor_table()
        rows = table._rows  # noqa: SLF001 - checking internal state in test only
        assert isinstance(rows[0][1], StatusCell)
        assert rows[0][1].level == StatusLevel.OK
        assert isinstance(rows[1][1], StatusCell)
        assert rows[1][1].level == StatusLevel.ERROR


class TestToContext:
    """Tests for to_context."""

    def test_to_context_shape_complete(self) -> None:
        """to_context exposes every documented key with correct values."""
        t1 = datetime(2026, 4, 25, 10, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 4, 25, 11, 0, 0, tzinfo=timezone.utc)
        collector = NotifyCollector()
        collector.add(
            _make_result(
                name="a",
                success=True,
                duration_ms=100.0,
                started_at=t1,
                ended_at=t1 + timedelta(milliseconds=100),
            )
        )
        collector.add(
            _make_result(
                name="b",
                success=False,
                exception=ValueError("x"),
                duration_ms=200.0,
                started_at=t2,
                ended_at=t2 + timedelta(milliseconds=200),
            )
        )

        ctx = collector.to_context()
        assert ctx["ok_count"] == 1
        assert ctx["ko_count"] == 1
        assert ctx["total_count"] == 2
        assert ctx["ok_ratio"] == 0.5
        assert ctx["started_at"] == t1
        assert ctx["ended_at"] == t2 + timedelta(milliseconds=200)
        assert ctx["total_duration_ms"] == 300.0
        assert len(ctx["results"]) == 2

    def test_to_context_empty(self) -> None:
        """Empty collector yields zero counts and None timestamps."""
        ctx = NotifyCollector().to_context()
        assert ctx["total_count"] == 0
        assert ctx["ok_count"] == 0
        assert ctx["ko_count"] == 0
        assert ctx["ok_ratio"] == 0.0
        assert ctx["started_at"] is None
        assert ctx["ended_at"] is None
        assert ctx["total_duration_ms"] == 0.0
        assert ctx["results"] == []

    def test_to_context_surfaces_redact_user_data_flag(self) -> None:
        """to_context() exposes the collector's redact_user_data setting."""
        assert NotifyCollector().to_context()["redact_user_data"] is True
        assert NotifyCollector(redact_user_data=False).to_context()["redact_user_data"] is False


class TestRedactUserData:
    """Default redaction of user-code exception messages, return values, tracebacks."""

    _SECRET = "FakeUserCodeSecret_xyz123"

    def test_render_html_redacts_exception_message_by_default(self) -> None:
        """The Detail column hides the exception message; the type stays visible."""
        collector = NotifyCollector()
        collector.add(_make_result(success=False, exception=ValueError(self._SECRET)))
        out = collector.render_html()
        assert self._SECRET not in out
        assert "ValueError" in out
        assert "REDACTED" in out

    def test_render_html_redacts_return_value_by_default(self) -> None:
        """The Detail column hides the return_value repr."""
        collector = NotifyCollector()
        collector.add(_make_result(success=True, return_value=self._SECRET))
        out = collector.render_html()
        assert self._SECRET not in out
        assert "REDACTED" in out

    def test_render_html_suppresses_tracebacks_by_default(self) -> None:
        """include_tracebacks=True is overridden when redact_user_data is True."""
        collector = NotifyCollector()
        collector.add(
            _make_result(
                success=False,
                exception=RuntimeError("boom"),
                traceback_str=f"Traceback...\n  raise ValueError('{self._SECRET}')",
            )
        )
        out = collector.render_html(include_tracebacks=True)
        assert self._SECRET not in out
        assert "<details" not in out

    def test_render_plain_redacts_by_default(self) -> None:
        """render_plain uses _format_detail with redact=True."""
        collector = NotifyCollector()
        collector.add(_make_result(success=False, exception=ValueError(self._SECRET)))
        out = collector.render_plain()
        assert self._SECRET not in out
        assert "ValueError" in out

    def test_to_monitor_table_redacts_by_default(self) -> None:
        """to_monitor_table uses _format_detail with redact=True."""
        collector = NotifyCollector()
        collector.add(_make_result(success=False, exception=ValueError(self._SECRET)))
        rendered = collector.to_monitor_table().render()
        assert self._SECRET not in rendered

    def test_opt_out_restores_legacy_behaviour(self) -> None:
        """redact_user_data=False keeps the exception message verbatim."""
        collector = NotifyCollector(redact_user_data=False)
        collector.add(_make_result(success=False, exception=ValueError(self._SECRET)))
        out = collector.render_plain()
        assert self._SECRET in out
