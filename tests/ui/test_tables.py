"""Tests for the table builder helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from box import Box
from rich.console import Console
from rich.text import Text

from kstlib.config import ConfigNotLoadedError
from kstlib.ui import TableBuilder, TableRenderingError


class ExposedTableBuilder(TableBuilder):
    """Expose selected helpers for white-box testing."""

    @staticmethod
    def normalize_overrides(overrides: Mapping[str, Any]) -> dict[str, Any]:
        """Proxy to the protected normalization logic for coverage-friendly assertions."""

        return TableBuilder._normalize_overrides(overrides)


class TestTableBuilder:
    """Behavioural tests for the TableBuilder utility."""

    def test_render_table_with_default_config(self) -> None:
        """Ensure default configuration renders key/value layout."""
        builder = TableBuilder()
        table = builder.render_table(data=[{"key": "status", "value": "ready"}, {"key": "items", "value": 3}])

        assert len(table.columns) == 2
        assert table.columns[0].header == "Key"
        assert table.columns[1].header == "Value"

        console = Console(record=True)
        console.print(table)
        output = console.export_text()
        assert "status" in output
        assert "ready" in output

    def test_render_table_with_runtime_columns_and_data(self) -> None:
        """Validate runtime column overrides and dotted key resolution."""
        builder = TableBuilder()
        columns = [
            {"header": "Name", "key": "name"},
            {"header": "Price", "key": "metadata.price", "justify": "right"},
        ]
        data = [
            {"name": "Widget", "metadata": {"price": 9.99}},
            {"name": "Gadget", "metadata": {"price": 4.5}},
        ]

        table = builder.render_table(columns=columns, data=data)

        assert len(table.columns) == 2
        assert table.columns[1].justify == "right"

        console = Console(record=True)
        console.print(table)
        output = console.export_text()
        assert "Widget" in output
        assert "9.99" in output
        assert "4.5" in output

    def test_render_table_with_explicit_column_widths(self) -> None:
        """Forward width constraints to Rich column definitions."""
        builder = TableBuilder()
        columns = [
            {"header": "Name", "key": "name", "width": 12},
            {"header": "Region", "key": "region", "min_width": 10, "max_width": 16},
        ]
        data = [
            {"name": "alpha", "region": "eu-west-1"},
            {"name": "beta", "region": "us-east-2"},
        ]

        table = builder.render_table(columns=columns, data=data)

        assert table.columns[0].width == 12
        assert table.columns[1].min_width == 10
        assert table.columns[1].max_width == 16

    def test_render_table_with_explicit_rows(self) -> None:
        """Render explicit rows without column metadata."""
        builder = TableBuilder()
        table = builder.render_table(rows=[["alpha", 1], ["beta", 2]])

        console = Console(record=True)
        console.print(table)
        output = console.export_text()
        assert "alpha" in output
        assert "2" in output

    def test_preset_configuration_merges(self) -> None:
        """Confirm preset configuration merges with defaults."""
        user_config = {
            "ui": {
                "tables": {
                    "presets": {
                        "summary": {
                            "table": {"title": "Summary", "box": "SQUARE"},
                            "columns": [
                                {"header": "Metric", "key": "metric", "style": "bold"},
                                {"header": "Value", "key": "value"},
                            ],
                        }
                    }
                }
            }
        }

        builder = TableBuilder(config=user_config)
        table = builder.render_table(kind="summary", data=[{"metric": "uptime", "value": "99%"}])

        assert table.title == "Summary"
        assert table.columns[0].header == "Metric"
        assert table.columns[0].style == "bold"

    def test_print_table_uses_provided_console(self) -> None:
        """Verify print helper uses supplied console instance."""
        console = Console(record=True)
        builder = TableBuilder()
        builder.print_table(rows=[["x", "y"]], console=console)
        output = console.export_text()
        assert "x" in output
        assert "y" in output

    def test_missing_data_raises(self) -> None:
        """Require data or rows when rendering a table."""
        builder = TableBuilder()
        with pytest.raises(TableRenderingError):
            builder.render_table()

    def test_builder_handles_missing_runtime_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Gracefully fall back to defaults when global config is unavailable."""

        monkeypatch.setattr("kstlib.ui.tables.get_config", lambda: (_ for _ in ()).throw(ConfigNotLoadedError()))

        builder = TableBuilder()
        table = builder.render_table(data=[{"key": "status", "value": "missing"}])

        assert table.columns[0].header == "Key"

    def test_non_mapping_ui_config_is_ignored(self) -> None:
        """Reject configurations where the ui subtree is not a mapping."""

        builder = TableBuilder(config={"ui": "nope"})
        table = builder.render_table(data=[{"key": "status", "value": "ok"}])

        assert table.columns[0].header == "Key"

    def test_tables_config_box_is_converted(self) -> None:
        """Accept Box instances under the tables subtree."""

        box_tables = Box({"defaults": {"table": {"caption": "from box"}}})
        builder = TableBuilder(config={"ui": {"tables": box_tables}})

        table = builder.render_table(data=[{"key": "status", "value": "ok"}])

        assert table.caption == "from box"

    def test_tables_config_non_mapping_is_ignored(self) -> None:
        """Fallback to defaults when tables configuration is not a mapping."""

        builder = TableBuilder(config={"ui": {"tables": "invalid"}})
        table = builder.render_table(data=[{"key": "status", "value": "ok"}])

        assert table.columns[0].header == "Key"

    @pytest.mark.asyncio
    async def test_async_print_table(self) -> None:
        """Ensure async printer delegates to worker thread."""
        console = Console(record=True)
        builder = TableBuilder()

        table = await builder.print_table_async(rows=[["async", "row"]], console=console)
        assert table.columns[0].header == "Key"
        assert "async" in console.export_text()

    def test_invalid_defaults_configuration_raises(self) -> None:
        """Reject user configs that replace defaults with non-mappings."""
        user_config = {"ui": {"tables": {"defaults": ["not", "a", "mapping"]}}}
        builder = TableBuilder(config=user_config)

        with pytest.raises(TableRenderingError):
            builder.render_table(data=[{"key": "status", "value": "ready"}])

    def test_box_based_config_merges(self) -> None:
        """Load configuration from Box instances."""
        box_config = Box({"ui": {"tables": {"defaults": {"table": {"caption": "FromBox"}}}}})
        builder = TableBuilder(config=box_config)

        table = builder.render_table(data=[{"key": "status", "value": "ok"}])

        assert table.caption == "FromBox"

    def test_render_table_applies_table_overrides(self) -> None:
        """Merge per-call overrides into the table configuration."""
        builder = TableBuilder()
        columns = [{"header": "Only", "key": "only", "justify": "center"}]
        data = [{"only": "value"}]

        table = builder.render_table(columns=columns, data=data, table={"title": "Override"}, highlight=True)

        assert table.title == "Override"
        assert table.highlight is True
        assert table.columns[0].justify == "center"

    def test_override_columns_sequence_is_normalized(self) -> None:
        """Allow ``columns`` overrides to replace config columns."""

        result = ExposedTableBuilder.normalize_overrides(
            {
                "columns": [{"header": "Runtime", "key": "runtime", "ratio": 2}],
                "table": {"title": "ignored"},
            }
        )

        columns_override = result.get("columns")
        assert isinstance(columns_override, list)
        first_column = columns_override[0]
        assert isinstance(first_column, dict)
        assert first_column["header"] == "Runtime"

    def test_header_fallback_when_key_missing(self) -> None:
        """Use the header name when no explicit key is provided."""
        builder = TableBuilder()
        columns = [{"header": "Status"}]
        data = [{"Status": "OK"}]

        table = builder.render_table(columns=columns, data=data)
        console = Console(record=True)
        console.print(table)

        assert "OK" in console.export_text()

    def test_dotted_key_handles_non_mapping_segments(self) -> None:
        """Return empty string when dotted lookup hits a non-mapping value."""
        builder = TableBuilder()
        columns = [{"header": "Region", "key": "metadata.region"}]
        data = [{"metadata": None}]

        table = builder.render_table(columns=columns, data=data)
        console = Console(record=True)
        console.print(table)
        output = console.export_text()

        assert "None" not in output
        assert "Region" in output

    def test_render_cell_preserves_text_instances(self) -> None:
        """Keep Text instances intact when rendering explicit rows."""
        builder = TableBuilder()
        text_value = Text("keep me")

        table = builder.render_table(rows=[[text_value, None]])

        console = Console(record=True)
        console.print(table)
        output = console.export_text()

        assert "keep me" in output
        assert output.count("keep me") == 1
        assert "None" not in output

    def test_print_table_creates_console_when_missing(self) -> None:
        """Lazily create a console when none was provided."""
        builder = TableBuilder()

        builder.print_table(rows=[["lazy", "console"]])

        assert builder.console is not None

    def test_render_table_allows_empty_columns(self) -> None:
        """Skip column creation when an explicit empty sequence is provided."""

        builder = TableBuilder()
        table = builder.render_table(columns=[], data=[{}])

        assert len(table.columns) == 0

    def test_column_ratio_is_forwarded(self) -> None:
        """Ensure ratio metadata is propagated to Rich columns."""

        builder = TableBuilder()
        columns = [{"header": "Name", "key": "name", "ratio": 2}]
        data = [{"name": "alpha"}]

        table = builder.render_table(columns=columns, data=data)

        assert table.columns[0].ratio == 2

    def test_blank_column_definition_returns_empty_string(self) -> None:
        """Fallback to empty strings when both key and header are missing."""

        builder = TableBuilder()
        columns: list[dict[str, Any]] = [{}]
        data: list[dict[str, Any]] = [{}]

        table = builder.render_table(columns=columns, data=data)
        column = table.columns[0]

        cells = list(column.cells)
        assert cells
        first_cell = cells[0]
        assert isinstance(first_cell, Text)
        assert first_cell.plain == ""

    def test_deep_merge_combines_nested_mappings(self) -> None:
        """Apply deep merge when combining defaults and preset configuration."""
        user_config = {
            "ui": {
                "tables": {
                    "defaults": {"table": {"title": "Base", "caption": "Default", "row_styles": ["even", "odd"]}},
                    "presets": {
                        "custom": {
                            "table": {"caption": "Preset", "highlight": True},
                            "columns": (
                                {"header": "Metric", "key": "metric", "style": "bold"},
                                {"header": "Value", "key": "value"},
                            ),
                        }
                    },
                }
            }
        }

        builder = TableBuilder(config=user_config)
        table = builder.render_table(kind="custom", data=[{"metric": "uptime", "value": "99%"}])

        assert table.title == "Base"
        assert table.caption == "Preset"
        assert table.highlight is True
        assert len(table.columns) == 2
