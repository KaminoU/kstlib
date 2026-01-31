"""Metrics and timing utilities for measuring execution performance.

This module provides a unified decorator and tools for:

- **Time Measurement**: Track execution time of functions and code blocks
- **Memory Tracking**: Monitor peak memory usage with tracemalloc
- **Call Statistics**: Track call count, avg/min/max durations
- **Step Tracking**: Numbered step tracking with summary

All behavior is config-driven with sensible defaults.

Examples:
    Unified metrics decorator (config defaults):

    >>> from kstlib.metrics import metrics
    >>> @metrics
    ... def slow_function():
    ...     return sum(range(1000000))
    >>> slow_function()  # doctest: +SKIP
    [slow_function] ⏱ 0.023s | 🧠 Peak: 128 KB

    Step tracking for pipelines:

    >>> from kstlib.metrics import metrics, metrics_summary, clear_metrics
    >>> @metrics(step=True)
    ... def load_data():
    ...     pass
    >>> @metrics(step=True, title="Process records")
    ... def process():
    ...     pass
    >>> load_data()  # doctest: +SKIP
    [STEP 1] load_data ⏱ 0.001s
    >>> process()  # doctest: +SKIP
    [STEP 2] Process records ⏱ 0.002s
    >>> metrics_summary()  # doctest: +SKIP
    # Displays summary table with all steps

    Context manager usage:

    >>> from kstlib.metrics import metrics_context
    >>> with metrics_context("Data loading"):  # doctest: +SKIP
    ...     data = load_large_file()
    [Data loading] ⏱ 2.34s | 🧠 Peak: 512 MB

    Manual stopwatch:

    >>> from kstlib.metrics import Stopwatch
    >>> sw = Stopwatch("Pipeline")
    >>> sw.start()  # doctest: +SKIP
    >>> # ... work ...
    >>> sw.lap("Step 1")  # doctest: +SKIP
    >>> sw.stop()  # doctest: +SKIP
    >>> sw.summary()  # doctest: +SKIP
"""

from kstlib.metrics.decorators import (
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
    print_all_call_stats,
    reset_all_call_stats,
)
from kstlib.metrics.exceptions import MetricsError

__all__ = [
    "CallStats",
    "MetricsError",
    "MetricsRecord",
    "Stopwatch",
    "call_stats",
    "clear_metrics",
    "get_all_call_stats",
    "get_call_stats",
    "get_metrics",
    "metrics",
    "metrics_context",
    "metrics_summary",
    "print_all_call_stats",
    "reset_all_call_stats",
]
