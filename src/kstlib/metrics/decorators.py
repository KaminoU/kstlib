"""Unified metrics decorator for timing and profiling.

Provides a single config-driven decorator for all profiling needs:

- ``@metrics``: Use defaults from config (time + memory)
- ``@metrics(memory=False)``: Time only
- ``@metrics(step=True)``: Numbered step tracking
- ``@metrics("Custom title")``: With custom label

Examples:
    Basic usage with config defaults:

    >>> @metrics
    ... def process_data():
    ...     return sum(range(1000000))
    >>> process_data()  # doctest: +SKIP
    [process_data] ⏱ 0.023s | 🧠 Peak: 128 KB

    Step tracking:

    >>> @metrics(step=True)
    ... def load_data():
    ...     pass
    >>> load_data()  # doctest: +SKIP
    [STEP 1] load_data ⏱ 0.001s | 🧠 Peak: 64 KB
"""

from __future__ import annotations

import functools
import inspect
import sys
import threading
import time as time_module
import tracemalloc
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar, overload

from rich.console import Console
from rich.text import Text

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

P = ParamSpec("P")
R = TypeVar("R")

# Default theme (Rich style names)
_DEFAULT_THEME = {
    "label": "bold green",
    "title": "bold white",
    "text": "white",
    "muted": "dim",
    "table_header": "bold cyan",
    "time_ok": "cyan",
    "time_warn": "yellow",
    "time_crit": "bold red",
    "memory_ok": "magenta",
    "memory_warn": "yellow",
    "memory_crit": "bold red",
    "step_number": "dim",
    "separator": "dim white",
}

# Default thresholds
_DEFAULT_THRESHOLDS = {
    "time_warn": 5,
    "time_crit": 30,
    "memory_warn": 100_000_000,
    "memory_crit": 500_000_000,
}

# Default icons (empty string to disable)
_DEFAULT_ICONS = {
    "time": "⏱",
    "memory": "🧠",
    "peak": "Peak:",
}


def _get_config() -> dict[str, Any]:
    """Get metrics config with defaults."""
    defaults = {
        "colors": True,
        "time": True,
        "memory": True,
        "step": False,
        "step_format": "[STEP {n}] {title}",
        "lap_format": "[LAP {n}] {name}",
        "title_format": "{function}",
        "thresholds": dict(_DEFAULT_THRESHOLDS),
        "theme": dict(_DEFAULT_THEME),
        "icons": dict(_DEFAULT_ICONS),
    }
    try:
        from kstlib.config import get_config

        config = get_config()
        metrics_cfg = config.get("metrics", {})  # type: ignore[no-untyped-call]
        cfg_defaults = metrics_cfg.get("defaults", {})
        cfg_thresholds = metrics_cfg.get("thresholds", {})
        cfg_theme = metrics_cfg.get("theme", {})
        cfg_icons = metrics_cfg.get("icons", {})

        defaults.update(
            {
                "colors": metrics_cfg.get("colors", defaults["colors"]),
                "time": cfg_defaults.get("time", defaults["time"]),
                "memory": cfg_defaults.get("memory", defaults["memory"]),
                "step": cfg_defaults.get("step", defaults["step"]),
                "step_format": metrics_cfg.get("step_format", defaults["step_format"]),
                "lap_format": metrics_cfg.get("lap_format", defaults["lap_format"]),
                "title_format": metrics_cfg.get("title_format", defaults["title_format"]),
                "thresholds": {**_DEFAULT_THRESHOLDS, **cfg_thresholds},
                "theme": {**_DEFAULT_THEME, **cfg_theme},
                "icons": {**_DEFAULT_ICONS, **cfg_icons},
            }
        )
    except Exception:
        pass  # Config loading is optional, use defaults
    return defaults


def _get_console() -> Console:
    """Get a Rich console for stderr output."""
    cfg = _get_config()
    return Console(
        file=sys.stderr,
        force_terminal=cfg["colors"],
        no_color=not cfg["colors"],
    )


def _format_bytes(num_bytes: int) -> str:
    """Format bytes to human-readable string.

    Examples:
        >>> _format_bytes(1024)
        '1.0 KB'
        >>> _format_bytes(1536 * 1024 * 1024)
        '1.5 GB'
    """
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"


def _format_time(seconds: float) -> str:
    """Format seconds to human-readable string.

    Examples:
        >>> _format_time(0.5)
        '0.500s'
        >>> _format_time(90)
        '1m 30s'
    """
    if seconds < 60:
        return f"{seconds:.3f}s"
    if seconds < 3600:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m {secs:.0f}s"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours}h {minutes}m"


def _get_time_style(seconds: float, cfg: dict[str, Any] | None = None) -> str:
    """Get Rich style based on duration thresholds."""
    if cfg is None:
        cfg = _get_config()
    thresholds: dict[str, int | float] = cfg["thresholds"]
    theme: dict[str, str] = cfg["theme"]
    if seconds >= thresholds["time_crit"]:
        return str(theme["time_crit"])
    if seconds >= thresholds["time_warn"]:
        return str(theme["time_warn"])
    return str(theme["time_ok"])


def _get_memory_style(num_bytes: int, cfg: dict[str, Any] | None = None) -> str:
    """Get Rich style based on memory thresholds."""
    if cfg is None:
        cfg = _get_config()
    thresholds: dict[str, int | float] = cfg["thresholds"]
    theme: dict[str, str] = cfg["theme"]
    if num_bytes >= thresholds["memory_crit"]:
        return str(theme["memory_crit"])
    if num_bytes >= thresholds["memory_warn"]:
        return str(theme["memory_warn"])
    return str(theme["memory_ok"])


# =============================================================================
# Global step registry
# =============================================================================


@dataclass
class MetricsRecord:
    """Record of a metrics measurement.

    Attributes:
        number: Step number (if step=True).
        title: Display title.
        elapsed_seconds: Execution time.
        peak_memory_bytes: Peak memory usage.
        function: Function name.
        module: Module name.
        file: Source file.
        line: Source line.
    """

    number: int | None
    title: str
    elapsed_seconds: float = 0.0
    peak_memory_bytes: int | None = None
    function: str = ""
    module: str = ""
    file: str = ""
    line: int = 0

    @property
    def elapsed_formatted(self) -> str:
        """Return formatted elapsed time."""
        return _format_time(self.elapsed_seconds)

    @property
    def peak_memory_formatted(self) -> str | None:
        """Return formatted peak memory."""
        if self.peak_memory_bytes is None:
            return None
        return _format_bytes(self.peak_memory_bytes)


_records: list[MetricsRecord] = []
_step_counter = 0
_records_lock = threading.Lock()
_program_start: float | None = None


def _next_step_number() -> int:
    """Get and increment the global step counter."""
    global _step_counter, _program_start
    with _records_lock:
        if _program_start is None:
            _program_start = time_module.perf_counter()
        _step_counter += 1
        return _step_counter


def _register_record(record: MetricsRecord) -> None:
    """Register a completed record."""
    with _records_lock:
        _records.append(record)


def get_metrics() -> list[MetricsRecord]:
    """Get all recorded metrics.

    Returns:
        List of MetricsRecord objects.

    Examples:
        >>> records = get_metrics()
        >>> isinstance(records, list)
        True
    """
    with _records_lock:
        return list(_records)


def clear_metrics() -> None:
    """Clear all recorded metrics and reset step counter.

    Examples:
        >>> clear_metrics()
    """
    global _step_counter, _program_start
    with _records_lock:
        _records.clear()
        _step_counter = 0
        _program_start = None


def _print_metrics(record: MetricsRecord, *, show_time: bool, show_memory: bool) -> None:
    """Print a metrics result with Rich colors."""
    cfg = _get_config()
    theme: dict[str, str] = cfg["theme"]
    icons: dict[str, str] = cfg["icons"]
    console = _get_console()

    # Build Rich Text with styled parts
    output = Text()

    # Build label - supports Rich markup in title/step_format
    if record.number is not None:
        step_format = cfg["step_format"]
        label_str = step_format.format(
            n=record.number,
            title=record.title,
            function=record.function,
            module=record.module,
            file=record.file,
            line=record.line,
        )
        # Parse Rich markup in step_format (e.g., "[STEP {n}] [bold]{title}[/bold]")
        label_text = Text.from_markup(label_str, style=theme["label"])
        output.append(label_text)
    else:
        # For non-step: wrap title in brackets, parse markup inside title
        # e.g., title = "my_func [dim green](file.py:42)[/dim green]"
        # Result: "[my_func (file.py:42)]" with styled parts
        output.append("[", style=theme["label"])
        title_text = Text.from_markup(record.title, style=theme["label"])
        output.append(title_text)
        output.append("]", style=theme["label"])

    if show_time:
        time_style = _get_time_style(record.elapsed_seconds, cfg)
        output.append(" | " if show_memory and record.peak_memory_bytes else " ", style=theme["separator"])
        time_icon = f"{icons['time']} " if icons["time"] else ""
        output.append(f"{time_icon}{record.elapsed_formatted}", style=time_style)

    if show_memory and record.peak_memory_bytes is not None:
        mem_style = _get_memory_style(record.peak_memory_bytes, cfg)
        output.append(" | ", style=theme["separator"])
        mem_icon = f"{icons['memory']} " if icons["memory"] else ""
        peak_text = f"{icons['peak']} " if icons["peak"] else ""
        output.append(f"{mem_icon}{peak_text}{record.peak_memory_formatted}", style=mem_style)

    console.print(output)


# =============================================================================
# Main @metrics decorator
# =============================================================================


@overload
def metrics(func: Callable[P, R], /) -> Callable[P, R]: ...


@overload
def metrics(
    title: str,
    /,
    *,
    time: bool | None = None,
    memory: bool | None = None,
    step: bool | None = None,
    print_result: bool = True,
) -> Callable[[Callable[P, R]], Callable[P, R]]: ...


@overload
def metrics(
    func: None = None,
    /,
    *,
    title: str | None = None,
    time: bool | None = None,
    memory: bool | None = None,
    step: bool | None = None,
    print_result: bool = True,
) -> Callable[[Callable[P, R]], Callable[P, R]]: ...


def metrics(
    func_or_title: Callable[P, R] | str | None = None,
    /,
    *,
    title: str | None = None,
    time: bool | None = None,
    memory: bool | None = None,
    step: bool | None = None,
    print_result: bool = True,
) -> Callable[P, R] | Callable[[Callable[P, R]], Callable[P, R]]:
    """Unified decorator for timing, memory tracking, and step counting.

    Config-driven with sensible defaults. All options can be overridden.

    Args:
        func_or_title: Function to decorate or custom title string.
        title: Custom title (alternative to positional).
        time: Track execution time (default from config, typically True).
        memory: Track peak memory (default from config, typically True).
        step: Enable step numbering (default from config, typically False).
        print_result: Whether to print result to stderr.

    Returns:
        Decorated function.

    Examples:
        Default behavior (time + memory from config):

        >>> @metrics
        ... def process():
        ...     return sum(range(1000))
        >>> process()  # doctest: +SKIP
        [process] ⏱ 0.001s | 🧠 Peak: 64 KB

        Time only:

        >>> @metrics(memory=False)
        ... def quick():
        ...     pass

        With step numbering:

        >>> @metrics(step=True)
        ... def step1():
        ...     pass
        >>> step1()  # doctest: +SKIP
        [STEP 1] step1 ⏱ 0.001s | 🧠 Peak: 32 KB

        Custom title:

        >>> @metrics("Loading configuration")
        ... def load_config():
        ...     pass
    """
    # Handle @metrics (no parens, func passed directly)
    if callable(func_or_title):
        return _create_metrics_wrapper(func_or_title, None, time, memory, step, print_result)

    # Handle @metrics("title") or @metrics(title="title", ...)
    actual_title = func_or_title if isinstance(func_or_title, str) else title

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        return _create_metrics_wrapper(fn, actual_title, time, memory, step, print_result)

    return decorator


def _create_metrics_wrapper(
    fn: Callable[P, R],
    custom_title: str | None,
    track_time: bool | None,
    track_memory: bool | None,
    use_step: bool | None,
    print_result: bool,
) -> Callable[P, R]:
    """Create the actual metrics wrapper function."""
    # Get source info at decoration time
    try:
        source_file = inspect.getfile(fn)
        _, start_line = inspect.getsourcelines(fn)
        source_file = Path(source_file).name
    except (TypeError, OSError):
        source_file = "<unknown>"
        start_line = 0

    module_name = fn.__module__ or "<unknown>"
    func_name = fn.__name__

    # Build display title from config title_format format or custom title
    if custom_title:
        display_title = custom_title
    else:
        cfg = _get_config()
        title_format_fmt = cfg.get("title_format", "{function}")
        display_title = title_format_fmt.format(
            function=func_name,
            module=module_name,
            file=source_file,
            line=start_line,
        )

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        # Get config defaults, allow overrides
        cfg = _get_config()
        do_time = track_time if track_time is not None else cfg["time"]
        do_memory = track_memory if track_memory is not None else cfg["memory"]
        do_step = use_step if use_step is not None else cfg["step"]

        step_num = _next_step_number() if do_step else None

        record = MetricsRecord(
            number=step_num,
            title=display_title,
            function=func_name,
            module=module_name,
            file=source_file,
            line=start_line,
        )

        # Setup memory tracking if needed
        was_tracing = False
        if do_memory:
            was_tracing = tracemalloc.is_tracing()
            if not was_tracing:
                tracemalloc.start()
            tracemalloc.reset_peak()

        start = time_module.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            record.elapsed_seconds = time_module.perf_counter() - start

            if do_memory:
                _, peak = tracemalloc.get_traced_memory()
                record.peak_memory_bytes = peak
                if not was_tracing:
                    tracemalloc.stop()

            if do_step:
                _register_record(record)

            if print_result:
                _print_metrics(record, show_time=do_time, show_memory=do_memory)

    return wrapper


# =============================================================================
# Context manager version
# =============================================================================


@contextmanager
def metrics_context(
    title: str,
    *,
    time: bool | None = None,
    memory: bool | None = None,
    step: bool | None = None,
    print_result: bool = True,
) -> Generator[MetricsRecord, None, None]:
    """Context manager for metrics tracking.

    Args:
        title: Title for this measurement.
        time: Track execution time.
        memory: Track peak memory.
        step: Enable step numbering.
        print_result: Whether to print result.

    Yields:
        MetricsRecord being tracked.

    Examples:
        >>> with metrics_context("Loading data") as m:  # doctest: +SKIP
        ...     data = load_file()
        [Loading data] ⏱ 1.23s | 🧠 Peak: 256 MB
    """
    cfg = _get_config()
    do_time = time if time is not None else cfg["time"]
    do_memory = memory if memory is not None else cfg["memory"]
    do_step = step if step is not None else cfg["step"]

    # Get caller info
    frame = inspect.currentframe()
    if frame and frame.f_back and frame.f_back.f_back:
        caller = frame.f_back.f_back
        source_file = Path(caller.f_code.co_filename).name
        line_num = caller.f_lineno
        func_name = caller.f_code.co_name
        module_name = caller.f_globals.get("__name__", "<unknown>")
    else:
        source_file, line_num, func_name, module_name = "<unknown>", 0, "<unknown>", "<unknown>"

    step_num = _next_step_number() if do_step else None

    record = MetricsRecord(
        number=step_num,
        title=title,
        function=func_name,
        module=module_name,
        file=source_file,
        line=line_num,
    )

    # Setup memory tracking
    was_tracing = False
    if do_memory:
        was_tracing = tracemalloc.is_tracing()
        if not was_tracing:
            tracemalloc.start()
        tracemalloc.reset_peak()

    start = time_module.perf_counter()
    try:
        yield record
    finally:
        record.elapsed_seconds = time_module.perf_counter() - start

        if do_memory:
            _, peak = tracemalloc.get_traced_memory()
            record.peak_memory_bytes = peak
            if not was_tracing:
                tracemalloc.stop()

        if do_step:
            _register_record(record)

        if print_result:
            _print_metrics(record, show_time=do_time, show_memory=do_memory)


# =============================================================================
# Summary
# =============================================================================


def metrics_summary(*, show_percentages: bool = True, style: str = "table") -> None:
    """Print summary of all recorded metrics (step=True records).

    Uses kstlib.ui.tables for pretty output.

    Args:
        show_percentages: Whether to show percentage of total time.
        style: Output style - "table" (Rich table) or "simple" (plain text).

    Examples:
        >>> metrics_summary()  # doctest: +SKIP
    """
    records = [r for r in get_metrics() if r.number is not None]
    if not records:
        cfg = _get_config()
        theme: dict[str, str] = cfg["theme"]
        console = _get_console()
        console.print("No metrics recorded (use step=True).", style=theme["muted"])
        return

    total_elapsed = sum(r.elapsed_seconds for r in records)
    total_memory = sum(r.peak_memory_bytes or 0 for r in records)

    if style == "simple":
        _print_simple_summary(records, total_elapsed, total_memory, show_percentages)
    else:
        _print_table_summary(records, total_elapsed, total_memory, show_percentages)


def _print_simple_summary(
    records: list[MetricsRecord],
    total_elapsed: float,
    total_memory: int,
    show_percentages: bool,
) -> None:
    """Print a simple text summary using Rich."""
    cfg = _get_config()
    theme: dict[str, str] = cfg["theme"]
    console = _get_console()

    console.print()
    console.print("=" * 50, style=theme["muted"])
    console.print("METRICS SUMMARY", style=theme["title"])
    console.print("=" * 50, style=theme["muted"])

    for r in records:
        pct = (r.elapsed_seconds / total_elapsed * 100) if total_elapsed > 0 else 0
        time_style = _get_time_style(r.elapsed_seconds, cfg)

        line = Text("  ")
        line.append(f"[{r.number}]", style=theme["step_number"])
        line.append(" ")
        # Parse Rich markup in title (e.g., "[dim green]...[/dim green]")
        title_text = Text.from_markup(r.title, style=theme["text"])
        line.append(title_text)
        line.append(": ")
        line.append(r.elapsed_formatted, style=time_style)

        if r.peak_memory_bytes:
            mem_style = _get_memory_style(r.peak_memory_bytes, cfg)
            line.append(f" ({r.peak_memory_formatted})", style=mem_style)
        if show_percentages:
            line.append(f" [{pct:5.1f}%]", style=theme["muted"])

        console.print(line)

    console.print("-" * 50, style=theme["muted"])
    footer = Text("  ")
    footer.append(f"TOTAL: {_format_time(total_elapsed)}", style=theme["label"])
    if total_memory > 0:
        footer.append(f" | {_format_bytes(total_memory)}", style=theme["memory_ok"])
    console.print(footer)
    console.print()


def _print_table_summary(
    records: list[MetricsRecord],
    total_elapsed: float,
    total_memory: int,
    show_percentages: bool,
) -> None:
    """Print a Rich table summary."""
    try:
        from kstlib.ui.tables import TableBuilder
    except ImportError:
        _print_simple_summary(records, total_elapsed, total_memory, show_percentages)
        return

    cfg = _get_config()
    theme: dict[str, str] = cfg["theme"]
    console = _get_console()

    # Check if any record has memory
    has_memory = any(r.peak_memory_bytes for r in records)

    # Build columns
    columns: list[dict[str, Any]] = [
        {"header": "#", "key": "num", "justify": "right", "style": theme["step_number"], "width": 4},
        {"header": "Step", "key": "title", "justify": "left", "style": theme["text"]},
        {"header": "Time", "key": "time", "justify": "right", "style": theme["time_ok"]},
    ]
    if has_memory:
        columns.append({"header": "Memory", "key": "memory", "justify": "right", "style": theme["memory_ok"]})
    if show_percentages:
        columns.append({"header": "%", "key": "pct", "justify": "right", "style": theme["muted"], "width": 6})

    # Build rows
    rows = []
    for r in records:
        pct = (r.elapsed_seconds / total_elapsed * 100) if total_elapsed > 0 else 0
        # Extract plain text from title (strip Rich markup for table display)
        plain_title = Text.from_markup(r.title).plain
        row: dict[str, str] = {
            "num": str(r.number),
            "title": plain_title,
            "time": r.elapsed_formatted,
        }
        if has_memory:
            row["memory"] = r.peak_memory_formatted or "-"
        if show_percentages:
            row["pct"] = f"{pct:.1f}%"
        rows.append(row)

    # Render table
    builder = TableBuilder()
    table = builder.render_table(
        data=rows,
        columns=columns,
        table={
            "title": "Metrics Summary",
            "box": "ROUNDED",
            "header_style": theme["table_header"],
            "show_lines": False,
        },
    )

    console.print(table)

    # Print footer using Rich Text
    footer = Text("  ")
    footer.append(f"TOTAL: {_format_time(total_elapsed)}", style=theme["label"])
    if total_memory > 0:
        footer.append(f" | {_format_bytes(total_memory)}", style=theme["memory_ok"])
    if show_percentages:
        footer.append(" (100%)", style=theme["muted"])
    console.print(footer)


# =============================================================================
# Stopwatch (manual control)
# =============================================================================


@dataclass
class Stopwatch:
    """Manual stopwatch for timing code sections.

    For cases where you need explicit start/stop/lap control.

    Examples:
        >>> sw = Stopwatch("Pipeline")
        >>> _ = sw.start()
        >>> # ... work ...
        >>> sw.lap("Step 1")  # doctest: +SKIP
        >>> _ = sw.stop()
        >>> sw.summary()  # doctest: +SKIP
    """

    name: str = "Stopwatch"
    _start_time: float | None = field(default=None, repr=False)
    _lap_start: float | None = field(default=None, repr=False)
    _laps: list[tuple[str, float, int | None]] = field(default_factory=list, repr=False)
    _stopped: bool = field(default=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def start(self) -> Stopwatch:
        """Start the stopwatch."""
        with self._lock:
            self._start_time = time_module.perf_counter()
            self._lap_start = self._start_time
            self._stopped = False
        return self

    def lap(self, name: str, *, print_result: bool = True, track_memory: bool = False) -> float:
        """Record a lap time."""
        with self._lock:
            if self._lap_start is None:
                self.start()
            now = time_module.perf_counter()
            elapsed = now - (self._lap_start or now)

            peak = None
            if track_memory and tracemalloc.is_tracing():
                _, peak = tracemalloc.get_traced_memory()

            self._laps.append((name, elapsed, peak))
            self._lap_start = now

        if print_result:
            cfg = _get_config()
            theme: dict[str, str] = cfg["theme"]
            icons: dict[str, str] = cfg["icons"]
            console = _get_console()
            lap_num = len(self._laps)
            time_style = _get_time_style(elapsed, cfg)

            # Build label from lap_format
            lap_format = cfg.get("lap_format", "[LAP {n}] {name}")
            label = lap_format.format(n=lap_num, name=name)

            output = Text()
            output.append(label, style=theme["label"])
            output.append(" ", style=theme["separator"])
            time_icon = f"{icons['time']} " if icons["time"] else ""
            output.append(f"{time_icon}{_format_time(elapsed)}", style=time_style)
            console.print(output)

        return elapsed

    def stop(self) -> float:
        """Stop the stopwatch."""
        with self._lock:
            self._stopped = True
            if self._start_time is None:
                return 0.0
            return time_module.perf_counter() - self._start_time

    @property
    def total_elapsed(self) -> float:
        """Get total elapsed time."""
        with self._lock:
            if self._start_time is None:
                return 0.0
            return time_module.perf_counter() - self._start_time

    @property
    def laps(self) -> list[tuple[str, float, int | None]]:
        """Get all recorded laps."""
        with self._lock:
            return list(self._laps)

    def reset(self) -> None:
        """Reset the stopwatch."""
        with self._lock:
            self._start_time = None
            self._lap_start = None
            self._laps.clear()
            self._stopped = False

    def summary(self, *, show_percentages: bool = True) -> None:
        """Print a summary of all laps."""
        laps = self.laps
        total = self.total_elapsed
        cfg = _get_config()
        theme: dict[str, str] = cfg["theme"]
        console = _get_console()

        if not laps:
            console.print("No laps recorded.", style=theme["muted"])
            return

        console.print()
        console.print("=" * 50, style=theme["muted"])
        console.print(f"{self.name} SUMMARY", style=theme["title"])
        console.print("=" * 50, style=theme["muted"])

        for i, (name, elapsed, peak) in enumerate(laps, 1):
            pct = (elapsed / total * 100) if total > 0 else 0
            time_style = _get_time_style(elapsed, cfg)

            line = Text("  ")
            line.append(f"[{i}]", style=theme["step_number"])
            line.append(" ")
            line.append(name, style=theme["text"])
            line.append(": ")
            line.append(_format_time(elapsed), style=time_style)

            if peak:
                mem_style = _get_memory_style(peak, cfg)
                line.append(f" ({_format_bytes(peak)})", style=mem_style)
            if show_percentages:
                line.append(f" [{pct:5.1f}%]", style=theme["muted"])

            console.print(line)

        console.print("-" * 50, style=theme["muted"])
        footer = Text("  ")
        footer.append(f"TOTAL: {_format_time(total)}", style=theme["label"])
        console.print(footer)
        console.print()


# =============================================================================
# Call stats (for tracking multiple calls)
# =============================================================================


@dataclass
class CallStats:
    """Statistics for tracked function calls.

    Examples:
        >>> stats = CallStats("my_func")
        >>> stats.record(0.5)
        >>> stats.record(1.0)
        >>> stats.call_count
        2
        >>> stats.avg_time
        0.75
    """

    name: str
    call_count: int = 0
    total_time: float = 0.0
    min_time: float = field(default=float("inf"))
    max_time: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, elapsed: float) -> None:
        """Record a call duration."""
        with self._lock:
            self.call_count += 1
            self.total_time += elapsed
            self.min_time = min(self.min_time, elapsed)
            self.max_time = max(self.max_time, elapsed)

    @property
    def avg_time(self) -> float:
        """Return average call duration."""
        if self.call_count == 0:
            return 0.0
        return self.total_time / self.call_count

    def reset(self) -> None:
        """Reset all statistics."""
        with self._lock:
            self.call_count = 0
            self.total_time = 0.0
            self.min_time = float("inf")
            self.max_time = 0.0

    def __str__(self) -> str:
        """Return human-readable summary with Rich colors."""
        if self.call_count == 0:
            return f"[{self.name}] No calls recorded"

        cfg = _get_config()
        theme: dict[str, str] = cfg["theme"]

        # Build Rich Text with styled parts
        text = Text()
        text.append(f"[{self.name}]", style=theme["label"])
        text.append(f" {self.call_count} calls", style=theme["label"])
        text.append(" | ", style=theme["separator"])
        text.append(f"avg: {_format_time(self.avg_time)}", style=theme["time_ok"])
        text.append(" | ", style=theme["separator"])
        text.append(f"min: {_format_time(self.min_time)}", style=theme["muted"])
        text.append(" | ", style=theme["separator"])
        text.append(f"max: {_format_time(self.max_time)}", style=theme["muted"])

        # Render to ANSI string
        from io import StringIO

        buffer = StringIO()
        console = Console(file=buffer, force_terminal=cfg["colors"], no_color=not cfg["colors"])
        console.print(text, end="")
        return buffer.getvalue()


_call_stats_registry: dict[str, CallStats] = {}
_registry_lock = threading.Lock()


def get_call_stats(func_name: str) -> CallStats | None:
    """Get call statistics for a tracked function."""
    with _registry_lock:
        return _call_stats_registry.get(func_name)


def get_all_call_stats() -> dict[str, CallStats]:
    """Get all tracked call statistics."""
    with _registry_lock:
        return dict(_call_stats_registry)


def reset_all_call_stats() -> None:
    """Reset all tracked call statistics."""
    with _registry_lock:
        for stats in _call_stats_registry.values():
            stats.reset()


def print_all_call_stats() -> None:
    """Print all tracked call statistics to stderr."""
    with _registry_lock:
        for stats in _call_stats_registry.values():
            if stats.call_count > 0:
                print(str(stats), file=sys.stderr)


@overload
def call_stats(func: Callable[P, R], /) -> Callable[P, R]: ...


@overload
def call_stats(
    func: None = None,
    /,
    *,
    name: str | None = None,
    print_on_call: bool = False,
) -> Callable[[Callable[P, R]], Callable[P, R]]: ...


def call_stats(
    func: Callable[P, R] | None = None,
    /,
    *,
    name: str | None = None,
    print_on_call: bool = False,
) -> Callable[P, R] | Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator to track call statistics.

    Tracks call count, total time, min, max, and average duration.
    Use get_call_stats() or print_all_call_stats() to access results.

    Examples:
        >>> @call_stats
        ... def api_call():
        ...     pass
        >>> api_call()
        >>> api_call()
        >>> stats = get_call_stats("api_call")
        >>> stats.call_count
        2
    """

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        label = name or fn.__name__

        with _registry_lock:
            if label not in _call_stats_registry:
                _call_stats_registry[label] = CallStats(name=label)
            stats = _call_stats_registry[label]

        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            start = time_module.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                elapsed = time_module.perf_counter() - start
                stats.record(elapsed)
                if print_on_call:
                    print(str(stats), file=sys.stderr)

        return wrapper

    if func is not None:
        return decorator(func)
    return decorator


__all__ = [
    "CallStats",
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
