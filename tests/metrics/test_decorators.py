"""Tests for the unified metrics decorator module."""

from __future__ import annotations

import threading
import time

import pytest

from kstlib.metrics import (
    CallStats,
    MetricsRecord,
    Stopwatch,
    call_stats,
    clear_metrics,
    get_all_call_stats,
    get_call_stats,
    get_metrics,
    metrics,
    metrics_context,
    metrics_summary,
    reset_all_call_stats,
)


class TestMetricsDecorator:
    """Tests for the @metrics decorator."""

    def test_decorator_without_args(self) -> None:
        """Decorator works without arguments."""

        @metrics
        def my_func() -> int:
            return 42

        result = my_func()
        assert result == 42

    def test_decorator_with_memory_disabled(self) -> None:
        """Decorator works with memory disabled."""

        @metrics(memory=False, print_result=False)
        def my_func() -> int:
            return 42

        result = my_func()
        assert result == 42

    def test_decorator_with_custom_title(self) -> None:
        """Decorator works with custom title."""

        @metrics("Custom Title", print_result=False)
        def my_func() -> int:
            return 42

        result = my_func()
        assert result == 42

    def test_decorator_with_keyword_title(self) -> None:
        """Decorator works with title as keyword."""

        @metrics(title="Keyword Title", print_result=False)
        def my_func() -> int:
            return 42

        result = my_func()
        assert result == 42

    def test_decorator_preserves_function_metadata(self) -> None:
        """Decorator preserves function name and docstring."""

        @metrics(print_result=False)
        def documented_func() -> None:
            """This is a docstring."""

        assert documented_func.__name__ == "documented_func"
        assert documented_func.__doc__ == "This is a docstring."


class TestMetricsContextManager:
    """Tests for the metrics_context context manager."""

    def test_measures_elapsed_time(self) -> None:
        """Measure elapsed time in context."""
        with metrics_context("test", print_result=False) as m:
            time.sleep(0.02)
        assert m.elapsed_seconds >= 0.01

    def test_result_has_formatted_time(self) -> None:
        """Result has formatted elapsed time."""
        with metrics_context("test", print_result=False) as m:
            pass
        assert isinstance(m.elapsed_formatted, str)
        assert "s" in m.elapsed_formatted

    def test_measures_peak_memory(self) -> None:
        """Measure peak memory in context."""
        with metrics_context("test", memory=True, print_result=False) as m:
            data = [0] * 10000
            del data
        assert m.peak_memory_bytes is not None
        assert m.peak_memory_bytes > 0

    def test_result_has_formatted_memory(self) -> None:
        """Result has formatted memory."""
        with metrics_context("test", memory=True, print_result=False) as m:
            data = [0] * 1000
            del data
        assert m.peak_memory_formatted is not None
        assert "B" in m.peak_memory_formatted or "KB" in m.peak_memory_formatted


class TestStepTracking:
    """Tests for step tracking with @metrics(step=True)."""

    def setup_method(self) -> None:
        """Clear metrics before each test."""
        clear_metrics()

    def test_step_without_title(self) -> None:
        """Step works without custom title."""

        @metrics(step=True, print_result=False)
        def my_step() -> int:
            return 42

        result = my_step()
        assert result == 42

        records = get_metrics()
        assert len(records) == 1
        assert records[0].number == 1
        assert records[0].function == "my_step"

    def test_step_with_title(self) -> None:
        """Step works with custom title."""

        @metrics(step=True, title="Load Data", print_result=False)
        def load_data() -> None:
            pass

        load_data()

        records = get_metrics()
        assert len(records) == 1
        assert records[0].title == "Load Data"

    def test_step_with_positional_title(self) -> None:
        """Step works with positional title."""

        @metrics("Process Records", step=True, print_result=False)
        def process() -> None:
            pass

        process()

        records = get_metrics()
        assert records[0].title == "Process Records"

    def test_multiple_steps_numbered(self) -> None:
        """Multiple steps are numbered sequentially."""

        @metrics(step=True, print_result=False)
        def step1() -> None:
            pass

        @metrics(step=True, print_result=False)
        def step2() -> None:
            pass

        @metrics(step=True, print_result=False)
        def step3() -> None:
            pass

        step1()
        step2()
        step3()

        records = get_metrics()
        assert len(records) == 3
        assert [r.number for r in records] == [1, 2, 3]

    def test_step_tracks_elapsed_time(self) -> None:
        """Step tracks elapsed time."""

        @metrics(step=True, print_result=False)
        def slow_step() -> None:
            time.sleep(0.05)

        slow_step()

        records = get_metrics()
        # Allow 10% tolerance for timing variance (especially on Windows)
        assert records[0].elapsed_seconds >= 0.045

    def test_clear_metrics_resets_counter(self) -> None:
        """clear_metrics resets the step counter."""

        @metrics(step=True, print_result=False)
        def my_step() -> None:
            pass

        my_step()
        clear_metrics()
        my_step()

        records = get_metrics()
        assert len(records) == 1
        assert records[0].number == 1

    def test_get_metrics_returns_copy(self) -> None:
        """get_metrics returns a copy of the list."""

        @metrics(step=True, print_result=False)
        def my_step() -> None:
            pass

        my_step()

        records1 = get_metrics()
        records2 = get_metrics()
        assert records1 is not records2


class TestCallStats:
    """Tests for the CallStats class."""

    def test_record_call(self) -> None:
        """Record call duration."""
        stats = CallStats("test")
        stats.record(1.0)
        stats.record(2.0)
        assert stats.call_count == 2
        assert stats.total_time == 3.0
        assert stats.avg_time == 1.5
        assert stats.min_time == 1.0
        assert stats.max_time == 2.0

    def test_reset_stats(self) -> None:
        """Reset statistics."""
        stats = CallStats("test")
        stats.record(1.0)
        stats.reset()
        assert stats.call_count == 0
        assert stats.total_time == 0.0

    def test_str_representation(self) -> None:
        """String representation is readable."""
        stats = CallStats("test_func")
        stats.record(0.5)
        s = str(stats)
        assert "test_func" in s
        assert "1 calls" in s


class TestCallStatsDecorator:
    """Tests for the call_stats decorator."""

    def setup_method(self) -> None:
        """Reset registry before each test."""
        reset_all_call_stats()

    def test_decorator_tracks_calls(self) -> None:
        """Decorator tracks function calls."""

        @call_stats
        def tracked_func() -> int:
            return 42

        tracked_func()
        tracked_func()
        tracked_func()

        stats = get_call_stats("tracked_func")
        assert stats is not None
        assert stats.call_count == 3

    def test_decorator_with_custom_name(self) -> None:
        """Decorator accepts custom name."""

        @call_stats(name="custom_name")
        def my_func() -> None:
            pass

        my_func()

        stats = get_call_stats("custom_name")
        assert stats is not None
        assert stats.call_count == 1

    def test_get_all_call_stats(self) -> None:
        """Get all tracked stats."""

        @call_stats
        def func_a() -> None:
            pass

        @call_stats
        def func_b() -> None:
            pass

        func_a()
        func_b()

        all_stats = get_all_call_stats()
        assert "func_a" in all_stats
        assert "func_b" in all_stats


class TestMetricsRecord:
    """Tests for the MetricsRecord class."""

    def test_elapsed_formatted(self) -> None:
        """Elapsed time is formatted correctly."""
        record = MetricsRecord(number=None, title="test", elapsed_seconds=1.5)
        assert record.elapsed_formatted == "1.500s"

    def test_peak_memory_formatted(self) -> None:
        """Peak memory is formatted correctly."""
        record = MetricsRecord(number=None, title="test", peak_memory_bytes=1024 * 1024)
        assert record.peak_memory_formatted == "1.0 MB"

    def test_peak_memory_formatted_none(self) -> None:
        """Peak memory formatted returns None when not set."""
        record = MetricsRecord(number=None, title="test")
        assert record.peak_memory_formatted is None


class TestStopwatch:
    """Tests for the Stopwatch class."""

    def test_start_and_stop(self) -> None:
        """Start and stop the stopwatch."""
        sw = Stopwatch("Test")
        sw.start()
        time.sleep(0.05)
        elapsed = sw.stop()
        # Use tolerance for timing variations on Windows
        assert elapsed >= 0.04

    def test_lap_recording(self) -> None:
        """Record laps."""
        sw = Stopwatch("Test")
        sw.start()
        time.sleep(0.01)
        sw.lap("First", print_result=False)
        time.sleep(0.01)
        sw.lap("Second", print_result=False)

        laps = sw.laps
        assert len(laps) == 2
        assert laps[0][0] == "First"
        assert laps[1][0] == "Second"

    def test_total_elapsed(self) -> None:
        """Get total elapsed time."""
        sw = Stopwatch("Test")
        sw.start()
        time.sleep(0.05)
        # Use tolerance for timing variations on Windows
        assert sw.total_elapsed >= 0.04

    def test_reset(self) -> None:
        """Reset the stopwatch."""
        sw = Stopwatch("Test")
        sw.start()
        sw.lap("Test", print_result=False)
        sw.reset()

        assert sw.laps == []
        assert sw.total_elapsed == 0.0

    def test_chained_start(self) -> None:
        """Start returns self for chaining."""
        sw = Stopwatch("Test").start()
        assert isinstance(sw, Stopwatch)


class TestMetricsSummary:
    """Tests for metrics_summary function."""

    def setup_method(self) -> None:
        """Clear metrics before each test."""
        clear_metrics()

    def test_summary_with_no_records(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Summary handles no records gracefully."""
        metrics_summary()
        # Should not raise

    def test_summary_simple_style(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Summary works with simple style."""

        @metrics(step=True, print_result=False)
        def my_step() -> None:
            pass

        my_step()
        metrics_summary(style="simple")
        # Should not raise


class TestThreadSafety:
    """Tests for thread safety of metrics."""

    def test_call_stats_thread_safe(self) -> None:
        """CallStats is thread-safe."""
        stats = CallStats("concurrent")
        threads = []

        def record_calls() -> None:
            for _ in range(100):
                stats.record(0.001)

        for _ in range(10):
            t = threading.Thread(target=record_calls)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert stats.call_count == 1000


class TestFormatFunctions:
    """Tests for internal formatting functions."""

    def test_format_bytes_petabytes(self) -> None:
        """Format bytes handles petabyte values."""
        from kstlib.metrics.decorators import _format_bytes

        result = _format_bytes(2 * 1024**5)
        assert "PB" in result

    def test_format_time_minutes(self) -> None:
        """Format time handles minutes."""
        from kstlib.metrics.decorators import _format_time

        result = _format_time(90)
        assert result == "1m 30s"

    def test_format_time_hours(self) -> None:
        """Format time handles hours."""
        from kstlib.metrics.decorators import _format_time

        result = _format_time(3725)
        assert result == "1h 2m"


class TestThresholdStyles:
    """Tests for time and memory threshold styles."""

    def test_time_style_ok(self) -> None:
        """Time style for fast operations."""
        from kstlib.metrics.decorators import _get_time_style

        style = _get_time_style(1.0)
        assert style is not None

    def test_time_style_warning(self) -> None:
        """Time style for slow operations (warning)."""
        from kstlib.metrics.decorators import _get_time_style

        style = _get_time_style(10.0)
        assert style is not None

    def test_time_style_critical(self) -> None:
        """Time style for very slow operations (critical)."""
        from kstlib.metrics.decorators import _get_time_style

        style = _get_time_style(60.0)
        assert style is not None

    def test_memory_style_ok(self) -> None:
        """Memory style for low usage."""
        from kstlib.metrics.decorators import _get_memory_style

        style = _get_memory_style(1000)
        assert style is not None

    def test_memory_style_warning(self) -> None:
        """Memory style for high usage (warning)."""
        from kstlib.metrics.decorators import _get_memory_style

        style = _get_memory_style(200_000_000)
        assert style is not None

    def test_memory_style_critical(self) -> None:
        """Memory style for very high usage (critical)."""
        from kstlib.metrics.decorators import _get_memory_style

        style = _get_memory_style(600_000_000)
        assert style is not None


class TestPrintMetrics:
    """Tests for _print_metrics function."""

    def setup_method(self) -> None:
        """Clear metrics before each test."""
        clear_metrics()

    def test_print_step_record(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Print record with step number."""

        @metrics(step=True, print_result=True)
        def my_step() -> None:
            pass

        my_step()
        captured = capsys.readouterr()
        assert "STEP" in captured.err or "1" in captured.err

    def test_print_record_with_memory(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Print record with memory tracking."""

        @metrics(memory=True, print_result=True)
        def my_func() -> None:
            data = [0] * 1000
            del data

        my_func()
        captured = capsys.readouterr()
        assert captured.err  # Something was printed


class TestWrapperExceptionHandling:
    """Tests for wrapper exception handling."""

    def test_wrapper_handles_builtin_function(self) -> None:
        """Wrapper handles functions without source info."""
        from kstlib.metrics.decorators import _create_metrics_wrapper

        # Wrap a built-in that has no source file
        wrapped = _create_metrics_wrapper(len, None, True, False, False, False)
        result = wrapped([1, 2, 3])
        assert result == 3


class TestMetricsSummaryTable:
    """Tests for metrics_summary table output."""

    def setup_method(self) -> None:
        """Clear metrics before each test."""
        clear_metrics()

    def test_summary_table_style(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Summary works with table style (default)."""

        @metrics(step=True, print_result=False)
        def step1() -> None:
            pass

        @metrics(step=True, print_result=False, memory=True)
        def step2() -> None:
            data = [0] * 1000
            del data

        step1()
        step2()
        metrics_summary(style="table")
        captured = capsys.readouterr()
        assert captured.err  # Table was printed

    def test_summary_without_percentages(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Summary works without percentages."""

        @metrics(step=True, print_result=False)
        def my_step() -> None:
            pass

        my_step()
        metrics_summary(show_percentages=False)
        # Should not raise


class TestStopwatchExtended:
    """Extended tests for Stopwatch class."""

    def test_lap_auto_starts(self) -> None:
        """Lap auto-starts stopwatch if not started."""
        sw = Stopwatch("Test")
        elapsed = sw.lap("First", print_result=False)
        assert elapsed >= 0

    def test_lap_with_memory_tracking(self) -> None:
        """Lap can track memory when tracemalloc is active."""
        import tracemalloc

        sw = Stopwatch("Test")
        sw.start()
        tracemalloc.start()
        try:
            sw.lap("With Memory", print_result=False, track_memory=True)
            laps = sw.laps
            assert len(laps) == 1
            # Memory tracking may or may not capture depending on timing
        finally:
            tracemalloc.stop()

    def test_lap_prints_result(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Lap prints result when print_result=True."""
        sw = Stopwatch("Test")
        sw.start()
        sw.lap("Printed Lap", print_result=True)
        captured = capsys.readouterr()
        assert "LAP" in captured.err or "Printed" in captured.err

    def test_stop_without_start(self) -> None:
        """Stop returns 0 if never started."""
        sw = Stopwatch("Test")
        elapsed = sw.stop()
        assert elapsed == 0.0

    def test_summary_no_laps(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Summary handles no laps gracefully."""
        sw = Stopwatch("Test")
        sw.start()
        sw.summary()
        captured = capsys.readouterr()
        assert "No laps" in captured.err

    def test_summary_with_laps(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Summary prints lap information."""
        sw = Stopwatch("Pipeline")
        sw.start()
        time.sleep(0.01)
        sw.lap("Step 1", print_result=False)
        time.sleep(0.01)
        sw.lap("Step 2", print_result=False)
        sw.stop()
        sw.summary(show_percentages=True)
        captured = capsys.readouterr()
        assert "Pipeline" in captured.err or "SUMMARY" in captured.err

    def test_summary_with_memory_in_laps(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Summary shows memory when laps have memory data."""
        import tracemalloc

        sw = Stopwatch("Memory Test")
        sw.start()
        tracemalloc.start()
        try:
            sw.lap("With Mem", print_result=False, track_memory=True)
        finally:
            tracemalloc.stop()
        sw.summary()
        # Should not raise


class TestCallStatsExtended:
    """Extended tests for CallStats."""

    def test_avg_time_no_calls(self) -> None:
        """Average time is 0 when no calls recorded."""
        stats = CallStats("empty")
        assert stats.avg_time == 0.0

    def test_str_no_calls(self) -> None:
        """String representation with no calls."""
        stats = CallStats("no_calls")
        s = str(stats)
        assert "No calls" in s

    def test_print_all_call_stats(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Print all call stats to stderr."""
        from kstlib.metrics.decorators import print_all_call_stats

        reset_all_call_stats()

        @call_stats
        def tracked() -> None:
            pass

        tracked()
        print_all_call_stats()
        captured = capsys.readouterr()
        assert "tracked" in captured.err

    def test_call_stats_print_on_call(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Call stats with print_on_call enabled."""
        reset_all_call_stats()

        @call_stats(print_on_call=True)
        def verbose_func() -> int:
            return 42

        result = verbose_func()
        assert result == 42
        captured = capsys.readouterr()
        assert "verbose_func" in captured.err


class TestMetricsContextExtended:
    """Extended tests for metrics_context."""

    def test_context_with_step(self) -> None:
        """Context manager with step tracking."""
        clear_metrics()
        with metrics_context("Test Step", step=True, print_result=False) as m:
            pass
        assert m.number is not None
        records = get_metrics()
        assert len(records) == 1

    def test_context_prints_result(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Context manager prints result."""
        with metrics_context("Printed", print_result=True):
            pass
        captured = capsys.readouterr()
        assert captured.err  # Something was printed
