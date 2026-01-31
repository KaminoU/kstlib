"""Config-driven helpers for rendering Rich tables."""

from __future__ import annotations

# pylint: disable=too-many-arguments
import asyncio
import copy
from collections.abc import Mapping, Sequence
from typing import Any

from box import Box
from rich import box as rich_box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from kstlib.config import ConfigNotLoadedError, get_config
from kstlib.ui.exceptions import TableRenderingError
from kstlib.utils.dict import deep_merge

DEFAULT_TABLE_CONFIG: dict[str, Any] = {
    "defaults": {
        "table": {
            "title": None,
            "title_style": None,
            "caption": None,
            "caption_style": None,
            "box": "SIMPLE",
            "show_header": True,
            "header_style": "bold cyan",
            "show_lines": False,
            "row_styles": None,
            "expand": True,
            "pad_edge": False,
            "highlight": False,
        },
        "columns": [
            {
                "header": "Key",
                "key": "key",
                "justify": "left",
                "style": "bold white",
                "overflow": "fold",
                "no_wrap": False,
            },
            {
                "header": "Value",
                "key": "value",
                "justify": "left",
                "style": None,
                "overflow": "fold",
                "no_wrap": False,
            },
        ],
    },
    "presets": {
        "inventory": {
            "table": {
                "title": "Inventory",
                "box": "ROUNDED",
                "show_lines": True,
                "header_style": "bold yellow",
            },
        },
        "metrics": {
            "table": {
                "title": "Metrics",
                "box": "SIMPLE_HEAD",
                "header_style": "bold green",
            },
        },
    },
}


class TableBuilder:
    """Render Rich tables from configuration presets.

    Tables follow the same configuration cascade used across kstlib:
    ``kwargs > config preset > defaults``. Column definitions can be specified in
    defaults, presets, or passed at runtime. Data may be provided as a sequence of
    mappings or explicit row sequences.

    Example:
        Render a simple table with data dictionaries::

            >>> from kstlib.ui.tables import TableBuilder
            >>> builder = TableBuilder()
            >>> data = [{"key": "Name", "value": "Alice"}, {"key": "Age", "value": "30"}]
            >>> table = builder.render_table(data=data)
            >>> table.row_count
            2

        Using a preset and custom columns::

            >>> columns = [
            ...     {"header": "Metric", "key": "metric"},
            ...     {"header": "Value", "key": "val", "justify": "right"},
            ... ]
            >>> data = [{"metric": "CPU", "val": "42%"}]
            >>> table = builder.render_table("metrics", data=data, columns=columns)
    """

    def __init__(self, config: Mapping[str, Any] | Box | None = None, console: Console | None = None) -> None:
        """Store optional console and resolve configuration cascade."""
        self.console = console
        self._config = self._prepare_config(config)

    def render_table(
        self,
        kind: str | None = None,
        *,
        data: Sequence[Mapping[str, Any]] | None = None,
        rows: Sequence[Sequence[Any]] | None = None,
        columns: Sequence[Mapping[str, Any]] | None = None,
        **overrides: Any,
    ) -> Table:
        """Build a ``Table`` instance according to the configuration cascade.

        Args:
            kind: Name of the preset to apply.
            data: Sequence of mapping-like objects used to populate the table.
            rows: Explicit rows as iterables; bypasses automatic extraction.
            columns: Runtime column definitions. Replaces configured columns when
                provided.
            **overrides: Additional overrides applied on top of the resolved config.

        Returns:
            Configured Rich ``Table`` instance.

        Raises:
            TableRenderingError: If neither ``data`` nor ``rows`` can populate the
                table.
        """
        resolved = self._resolve_table_config(kind, overrides, columns)
        table_config = resolved["table"]
        column_config = resolved.get("columns", [])

        table = self._create_table(table_config)
        self._add_columns(table, column_config)
        self._populate_rows(table, column_config, data=data, rows=rows)
        return table

    def print_table(
        self,
        kind: str | None = None,
        *,
        data: Sequence[Mapping[str, Any]] | None = None,
        rows: Sequence[Sequence[Any]] | None = None,
        columns: Sequence[Mapping[str, Any]] | None = None,
        console: Console | None = None,
        **overrides: Any,
    ) -> Table:
        """Render and print a table synchronously."""
        target_console = self._ensure_console(console)
        table = self.render_table(
            kind,
            data=data,
            rows=rows,
            columns=columns,
            **overrides,
        )
        target_console.print(table)
        return table

    async def print_table_async(
        self,
        kind: str | None = None,
        *,
        data: Sequence[Mapping[str, Any]] | None = None,
        rows: Sequence[Sequence[Any]] | None = None,
        columns: Sequence[Mapping[str, Any]] | None = None,
        console: Console | None = None,
        **overrides: Any,
    ) -> Table:
        """Render and print a table from an async context using a worker thread."""
        target_console = self._ensure_console(console)
        return await asyncio.to_thread(
            self.print_table,
            kind,
            data=data,
            rows=rows,
            columns=columns,
            console=target_console,
            **overrides,
        )

    # ------------------------------------------------------------------
    # Configuration resolution
    # ------------------------------------------------------------------

    def _prepare_config(self, config: Mapping[str, Any] | Box | None) -> dict[str, Any]:
        base_config = copy.deepcopy(DEFAULT_TABLE_CONFIG)
        user_config = self._load_runtime_config(config)
        if user_config:
            deep_merge(base_config, user_config)
        return base_config

    def _load_runtime_config(self, config: Mapping[str, Any] | Box | None) -> dict[str, Any]:
        if config is None:
            try:
                config = get_config()
            except ConfigNotLoadedError:
                return {}
        if isinstance(config, Box):
            config_mapping: Mapping[str, Any] = config.to_dict()
        else:
            config_mapping = dict(config)

        ui_config = config_mapping.get("ui", {})
        if not isinstance(ui_config, Mapping):
            return {}

        tables_config = ui_config.get("tables", {})
        if isinstance(tables_config, Box):
            return tables_config.to_dict()
        if isinstance(tables_config, Mapping):
            return dict(tables_config)
        return {}

    def _resolve_table_config(
        self,
        kind: str | None,
        overrides: Mapping[str, Any],
        runtime_columns: Sequence[Mapping[str, Any]] | None,
    ) -> dict[str, Any]:
        defaults = copy.deepcopy(self._config["defaults"])
        if not isinstance(defaults, dict):
            raise TableRenderingError("Table defaults configuration must be a mapping")

        config: dict[str, Any] = defaults
        preset: Mapping[str, Any] = {}
        raw_presets = self._config.get("presets", {})
        if isinstance(raw_presets, Mapping):
            candidate = raw_presets.get(kind or "", {})
            if isinstance(candidate, Mapping):
                preset = candidate

        deep_merge(config, preset)

        if runtime_columns is not None:
            config["columns"] = [dict(column) for column in runtime_columns]

        if overrides:
            normalized = self._normalize_overrides(overrides)
            deep_merge(config, normalized)

        return config

    @staticmethod
    def _normalize_overrides(overrides: Mapping[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {"table": {}, "columns": None}
        table_overrides = normalized["table"]

        for key, value in overrides.items():
            if key == "table" and isinstance(value, Mapping):
                table_overrides.update(dict(value))
                continue
            if key == "columns" and isinstance(value, Sequence):
                normalized["columns"] = [dict(column) for column in value]
                continue
            table_overrides[key] = value

        if normalized["columns"] is None:
            normalized.pop("columns", None)
        return normalized

    # ------------------------------------------------------------------
    # Table construction
    # ------------------------------------------------------------------

    def _create_table(self, table_config: Mapping[str, Any]) -> Table:
        box_name = table_config.get("box", "SIMPLE")
        box_obj = self._resolve_box(box_name)
        return Table(
            title=table_config.get("title"),
            caption=table_config.get("caption"),
            title_style=table_config.get("title_style"),
            caption_style=table_config.get("caption_style"),
            show_header=table_config.get("show_header", True),
            header_style=table_config.get("header_style"),
            show_lines=table_config.get("show_lines", False),
            row_styles=table_config.get("row_styles"),
            expand=table_config.get("expand", True),
            pad_edge=table_config.get("pad_edge", False),
            highlight=table_config.get("highlight", False),
            box=box_obj,
        )

    def _add_columns(self, table: Table, columns: Sequence[Mapping[str, Any]]) -> None:
        if not columns:
            return
        for column in columns:
            header = str(column.get("header", ""))
            column_kwargs: dict[str, Any] = {
                "style": column.get("style"),
                "no_wrap": column.get("no_wrap", False),
            }
            justify = column.get("justify")
            if justify is not None:
                column_kwargs["justify"] = justify
            overflow = column.get("overflow")
            if overflow is not None:
                column_kwargs["overflow"] = overflow
            ratio = column.get("ratio")
            if ratio is not None:
                column_kwargs["ratio"] = ratio
            width = column.get("width")
            if width is not None:
                column_kwargs["width"] = width
            min_width = column.get("min_width")
            if min_width is not None:
                column_kwargs["min_width"] = min_width
            max_width = column.get("max_width")
            if max_width is not None:
                column_kwargs["max_width"] = max_width
            table.add_column(header, **column_kwargs)

    def _populate_rows(
        self,
        table: Table,
        columns: Sequence[Mapping[str, Any]],
        *,
        data: Sequence[Mapping[str, Any]] | None,
        rows: Sequence[Sequence[Any]] | None,
    ) -> None:
        if rows is not None:
            for row in rows:
                table.add_row(*[self._render_cell(value) for value in row])
            return

        if data is None:
            raise TableRenderingError("Table requires either 'data' or 'rows'.")

        for item in data:
            rendered_row = [self._render_cell(self._extract_value(item, column)) for column in columns]
            table.add_row(*rendered_row)

    def _extract_value(self, item: Mapping[str, Any], column: Mapping[str, Any]) -> Any:
        key = column.get("key")
        if key is None:
            header = column.get("header")
            if header is None:
                return ""
            return item.get(str(header), "")

        if isinstance(key, str) and "." in key:
            return self._extract_dotted_key(item, key)
        return item.get(key, "")

    @staticmethod
    def _extract_dotted_key(item: Mapping[str, Any], key: str) -> Any:
        current: Any = item
        for part in key.split("."):
            if isinstance(current, Mapping):
                current = current.get(part)
            else:
                return ""
        return current

    @staticmethod
    def _render_cell(value: Any) -> Text:
        if isinstance(value, Text):
            return value
        return Text(str(value) if value is not None else "")

    @staticmethod
    def _resolve_box(box_name: str | None) -> Any:
        candidate = box_name or "SIMPLE"
        try:
            return getattr(rich_box, candidate)
        except AttributeError as exc:  # pragma: no cover - defensive guard
            raise TableRenderingError(f"Unknown box style '{candidate}'") from exc

    def _ensure_console(self, console: Console | None) -> Console:
        if console is not None:
            return console
        if self.console is None:
            self.console = Console()
        if self.console is None:  # pragma: no cover - defensive guard
            raise TableRenderingError("Console instance could not be created")
        return self.console
