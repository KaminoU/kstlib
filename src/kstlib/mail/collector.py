"""Thread-safe bounded collector for notify results.

Used in conjunction with :meth:`kstlib.mail.MailBuilder.notify` to accumulate
:class:`~kstlib.mail.NotifyResult` instances across multiple decorated calls,
then render a summary email at run end via
:meth:`kstlib.mail.MailBuilder.send_summary`.
"""

from __future__ import annotations

import html
import threading
from collections import deque
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from kstlib.mail.builder import NotifyResult
    from kstlib.monitoring import MonitorTable


_DEFAULT_MAXSIZE = 1000
_DETAIL_MAX_CHARS = 200


def _truncate(text: str, limit: int = _DETAIL_MAX_CHARS) -> str:
    """Return ``text`` truncated to ``limit`` characters with ellipsis if needed."""
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


_REDACTED_DETAIL = "[REDACTED] (NotifyCollector(redact_user_data=False) to view)"


def _format_detail(result: NotifyResult, *, redact: bool = True) -> str:
    """Build the Detail column string for a result.

    KO: ``"{ExcType}: {msg}"`` truncated.
    OK with return_value: ``repr(return_value)`` truncated.
    OK without return_value: empty string.

    When ``redact`` is True (default), exception messages and return
    values are replaced with a redaction placeholder. The exception type
    name is still surfaced for KO rows so the failure mode stays visible.
    """
    if not result.success and result.exception is not None:
        exc_type = type(result.exception).__name__
        if redact:
            return f"{exc_type}: {_REDACTED_DETAIL}"
        return _truncate(f"{exc_type}: {result.exception}")
    if result.success and result.return_value is not None:
        if redact:
            return _REDACTED_DETAIL
        return _truncate(repr(result.return_value))
    return ""


class NotifyCollector:
    """Thread-safe bounded collector of :class:`NotifyResult` instances.

    Designed to be passed to :meth:`kstlib.mail.MailBuilder.notify` via the
    ``collector=`` kwarg, accumulating results across multiple decorated
    function calls. Provides several rendering helpers for summary emails.

    Capacity is bounded to ``maxsize`` items with FIFO eviction when full.

    Args:
        maxsize: Maximum number of results to retain. Older entries are
            evicted FIFO when the bound is reached. Must be positive.

    Raises:
        ValueError: If ``maxsize`` is not a positive integer.

    Examples:
        >>> from kstlib.mail import NotifyCollector
        >>> collector = NotifyCollector(maxsize=500)
        >>> collector.ok_count
        0
        >>> collector.ko_count
        0

    """

    def __init__(
        self,
        *,
        maxsize: int = _DEFAULT_MAXSIZE,
        redact_user_data: bool = True,
    ) -> None:
        """Initialize the NotifyCollector.

        Args:
            maxsize: Maximum number of results retained (FIFO eviction).
            redact_user_data: When True (default), exception messages,
                return values, and tracebacks from the decorated user
                functions are replaced with a redaction placeholder
                before they appear in the rendered summary. Set to
                False to opt-in to the legacy verbatim behaviour --
                only do so if the decorated functions never raise with
                sensitive content in their messages and never return
                objects whose ``repr()`` would expose secrets.

        """
        if not isinstance(maxsize, int) or maxsize <= 0:
            msg = f"maxsize must be a positive integer, got: {maxsize!r}"
            raise ValueError(msg)
        self._maxsize = maxsize
        self._lock = threading.Lock()
        self._results: deque[NotifyResult] = deque(maxlen=maxsize)
        self._redact_user_data = redact_user_data

    def add(self, result: NotifyResult) -> None:
        """Append a result to the collector (thread-safe, FIFO bounded).

        Args:
            result: The notify result to record.

        """
        with self._lock:
            self._results.append(result)

    def reset(self) -> None:
        """Remove every recorded result (thread-safe)."""
        with self._lock:
            self._results.clear()

    @property
    def maxsize(self) -> int:
        """Return the configured maximum capacity."""
        return self._maxsize

    @property
    def results(self) -> list[NotifyResult]:
        """Return a snapshot copy of recorded results in insertion order."""
        with self._lock:
            return list(self._results)

    @property
    def ok_count(self) -> int:
        """Return the number of successful results."""
        with self._lock:
            return sum(1 for r in self._results if r.success)

    @property
    def ko_count(self) -> int:
        """Return the number of failed results."""
        with self._lock:
            return sum(1 for r in self._results if not r.success)

    @property
    def total_count(self) -> int:
        """Return the total number of recorded results."""
        with self._lock:
            return len(self._results)

    def render_html(self, *, include_tracebacks: bool = True) -> str:
        """Render results as a standalone HTML table with inline CSS.

        Produces a self-contained HTML fragment suitable for embedding in an
        email body. Each row is colored green for success or red for failure
        on the Status column. When ``include_tracebacks`` is true and any
        failure carries a traceback, a collapsible ``<details>`` block lists
        them under the table.

        Args:
            include_tracebacks: Whether to append a collapsible block with
                the full traceback of each failed result.

        Returns:
            HTML string with the summary table (and optional traceback block).

        """
        snapshot = self.results
        ok_count = sum(1 for r in snapshot if r.success)
        ko_count = len(snapshot) - ok_count

        rows: list[str] = []
        for r in snapshot:
            if r.success:
                status_label = "OK"
                status_bg = "#16a34a"
            else:
                status_label = "FAILED"
                status_bg = "#dc2626"
            status_cell = (
                f'<td style="padding:6px 10px;border-bottom:1px solid #e5e7eb">'
                f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
                f'background:{status_bg};color:#fff;font-weight:600">{status_label}</span>'
                f"</td>"
            )
            cells_style = "padding:6px 10px;border-bottom:1px solid #e5e7eb"
            rows.append(
                "<tr>"
                f'<td style="{cells_style}"><code>{html.escape(r.function_name)}</code></td>'
                f"{status_cell}"
                f'<td style="{cells_style}">{r.started_at.isoformat()}</td>'
                f'<td style="{cells_style};text-align:right">{r.duration_ms:.2f}</td>'
                f'<td style="{cells_style}">{html.escape(_format_detail(r, redact=self._redact_user_data))}</td>'
                "</tr>"
            )

        header_style = (
            "padding:8px 10px;background:#1f2937;color:#fff;"
            "text-align:left;font-weight:600;border-bottom:1px solid #111827"
        )
        table_style = 'style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:13px;width:100%"'
        summary = (
            f'<p style="font-family:Arial,sans-serif;font-size:13px;margin:0 0 8px 0">'
            f"<strong>Total:</strong> {len(snapshot)} "
            f'(<span style="color:#16a34a">OK: {ok_count}</span>, '
            f'<span style="color:#dc2626">FAILED: {ko_count}</span>)'
            f"</p>"
        )
        table_html = (
            f"{summary}"
            f"<table {table_style}>"
            f"<thead><tr>"
            f'<th style="{header_style}">Function</th>'
            f'<th style="{header_style}">Status</th>'
            f'<th style="{header_style}">Started</th>'
            f'<th style="{header_style};text-align:right">Duration (ms)</th>'
            f'<th style="{header_style}">Detail</th>'
            f"</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            f"</table>"
        )

        if include_tracebacks and not self._redact_user_data:
            # Tracebacks may carry user-code locals / exception payloads;
            # they are suppressed when redact_user_data is True regardless
            # of the include_tracebacks flag. The opt-out path requires the
            # caller to set redact_user_data=False explicitly.
            tb_blocks: list[str] = [
                (
                    f"<h4 style='font-family:Arial,sans-serif;margin:12px 0 4px 0'>"
                    f"<code>{html.escape(r.function_name)}</code></h4>"
                    f"<pre style='background:#f3f4f6;padding:10px;border-radius:4px;"
                    f"font-size:12px;overflow:auto'>{html.escape(r.traceback_str)}</pre>"
                )
                for r in snapshot
                if not r.success and r.traceback_str
            ]
            if tb_blocks:
                table_html += (
                    "<details style='margin-top:16px;font-family:Arial,sans-serif'>"
                    "<summary style='cursor:pointer;font-weight:600'>Tracebacks</summary>"
                    f"{''.join(tb_blocks)}"
                    "</details>"
                )

        return table_html

    def render_plain(self) -> str:
        """Render results as a plain text summary.

        Returns:
            Plain text string with header, per-result rows, and totals.

        """
        snapshot = self.results
        ok_count = sum(1 for r in snapshot if r.success)
        ko_count = len(snapshot) - ok_count

        lines = [
            f"Summary: {len(snapshot)} total (OK: {ok_count}, FAILED: {ko_count})",
            "",
        ]
        for r in snapshot:
            status = "OK" if r.success else "FAILED"
            detail = _format_detail(r, redact=self._redact_user_data)
            base = f"[{status}] {r.function_name} (started={r.started_at.isoformat()}, duration={r.duration_ms:.2f} ms)"
            lines.append(f"{base} - {detail}" if detail else base)
        return "\n".join(lines)

    def to_monitor_table(self) -> MonitorTable:
        """Build a :class:`~kstlib.monitoring.MonitorTable` of the recorded results.

        Imports are routed through the public ``kstlib.monitoring`` API to
        avoid cross-feature private imports.

        Returns:
            A populated MonitorTable with five columns
            (Function, Status, Started, Duration (ms), Detail).

        """
        from kstlib.monitoring import MonitorTable, StatusCell, StatusLevel

        table = MonitorTable(headers=["Function", "Status", "Started", "Duration (ms)", "Detail"])
        for r in self.results:
            status_cell = StatusCell("OK", StatusLevel.OK) if r.success else StatusCell("FAILED", StatusLevel.ERROR)
            table.add_row(
                [
                    r.function_name,
                    status_cell,
                    r.started_at.isoformat(),
                    f"{r.duration_ms:.2f}",
                    _format_detail(r, redact=self._redact_user_data),
                ]
            )
        return table

    def to_context(self) -> dict[str, Any]:
        """Build a Jinja-friendly context dict from the recorded results.

        Returns:
            Dict with keys: ``results``, ``ok_count``, ``ko_count``,
            ``total_count``, ``ok_ratio``, ``started_at``, ``ended_at``,
            ``total_duration_ms``.

        """
        snapshot = self.results
        ok_count = sum(1 for r in snapshot if r.success)
        total = len(snapshot)
        ko_count = total - ok_count

        if snapshot:
            started_at = min(r.started_at for r in snapshot)
            ended_at = max(r.ended_at for r in snapshot)
            total_duration_ms = sum(r.duration_ms for r in snapshot)
        else:
            started_at = None
            ended_at = None
            total_duration_ms = 0.0

        ok_ratio = (ok_count / total) if total else 0.0

        return {
            "results": snapshot,
            "ok_count": ok_count,
            "ko_count": ko_count,
            "total_count": total,
            "ok_ratio": ok_ratio,
            "started_at": started_at,
            "ended_at": ended_at,
            "total_duration_ms": total_duration_ms,
            # Surface the redaction flag so templates can choose whether to
            # render ``{{ result.exception }}`` etc. The raw NotifyResult
            # objects under ``results`` are not modified : custom templates
            # remain free to read user-provided fields directly. The
            # built-in render_html / render_plain / to_monitor_table all
            # honour this flag automatically.
            "redact_user_data": self._redact_user_data,
        }


__all__ = ["NotifyCollector"]
