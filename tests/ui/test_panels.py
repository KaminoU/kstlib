"""Tests for the panel rendering utilities."""

from __future__ import annotations

import asyncio
from typing import cast

import pytest
from box import Box
from rich import box as rich_box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from kstlib.config import ConfigNotLoadedError
from kstlib.ui import PanelManager, PanelRenderingError
from kstlib.ui import panels as panels_module
from kstlib.ui.panels import DEFAULT_PANEL_CONFIG, PanelPayload


def _base_config() -> dict[str, object]:
    return {
        "ui": {
            "panels": {
                "presets": {
                    "success": {
                        "panel": {
                            "border_style": "green",
                        },
                    }
                }
            }
        }
    }


def test_render_panel_honors_presets_and_overrides() -> None:
    """Ensure presets and explicit overrides both shape the panel output."""
    console = Console(record=True, width=80)
    manager = PanelManager(config=_base_config(), console=console)

    panel = manager.render_panel(
        "success",
        {"duration": "5s", "lines": 42},
        panel={"title": "Done", "icon": None},
        content={"sort_keys": True},
    )

    assert panel.border_style == "green"
    assert panel.title == "Done"
    assert isinstance(panel.renderable, Table)

    console.print(panel)
    output = console.export_text(clear=True)
    assert "duration" in output and "lines" in output
    assert output.index("duration") < output.index("lines")


def test_print_panel_records_output() -> None:
    """Verify synchronous rendering writes content to the bound console."""
    console = Console(record=True, width=80)
    manager = PanelManager(config={}, console=console)

    manager.print_panel("info", "[bold]Finished[/bold]")
    output = console.export_text(clear=True)
    assert "Finished" in output


def test_print_panel_async_uses_executor() -> None:
    """Confirm the async helper delegates to the executor-backed printer."""
    console = Console(record=True, width=80)
    manager = PanelManager(config={}, console=console)

    async def _invoke() -> None:
        await manager.print_panel_async("info", "Done async")

    asyncio.run(_invoke())
    output = console.export_text(clear=True)
    assert "Done async" in output


def test_render_panel_rejects_unsupported_payload() -> None:
    """Validate that unexpected payload types raise a rendering error."""
    manager = PanelManager(config={})

    with pytest.raises(PanelRenderingError):
        manager.render_panel(payload=cast(PanelPayload, object()))


def test_render_panel_merges_box_config() -> None:
    """Check that Box-derived defaults merge with call-level overrides."""
    config = Box(
        {
            "ui": {
                "panels": {
                    "defaults": {
                        "panel": {"border_style": "magenta", "padding": [0, 1]},
                        "content": {"value_style": "bold magenta"},
                    }
                }
            }
        }
    )
    manager = PanelManager(config=config)

    panel = manager.render_panel(
        payload={"answer": 42},
        panel={"style": "dim"},
    )

    assert panel.border_style == "magenta"
    assert panel.padding == (0, 1)
    assert panel.style is not None


def test_render_panel_handles_sequence_payload_and_numeric_values() -> None:
    """Ensure sequence payloads and non-string values render in tables."""
    console = Console(record=True, width=80)
    manager = PanelManager(config={}, console=console)

    panel = manager.render_panel(
        payload=[("count", 3), ("flag", False)],
        content={"value_style": "italic", "use_markup": False},
    )

    assert isinstance(panel.renderable, Table)
    console.print(panel)
    output = console.export_text(clear=True)
    assert "count" in output and "3" in output


def test_render_panel_pretty_and_repr_paths() -> None:
    """Cover both pretty-print and repr modes for structured payloads."""
    console = Console(record=True, width=80)
    manager = PanelManager(config={}, console=console)

    panel_pretty = manager.render_panel(
        payload={"numbers": [1, 2, 3]},
        content={"pretty_indent": 4},
    )
    console.print(panel_pretty)
    pretty_output = console.export_text(clear=True)
    assert "[" in pretty_output

    panel_repr = manager.render_panel(
        payload={"data": {"a": 1}},
        content={"use_pretty": False},
    )
    console.print(panel_repr)
    repr_output = console.export_text(clear=True)
    assert "{'a': 1}" in repr_output


def test_render_panel_padding_and_box_variants() -> None:
    """Assert padding coercion works and rejects invalid box selections."""
    manager = PanelManager(config={})

    panel_default = manager.render_panel(payload="ok", panel={"padding": None, "box": None})
    assert panel_default.padding == (1, 2)
    assert panel_default.box is rich_box.ROUNDED

    panel_single = manager.render_panel(payload="ok", panel={"padding": [4]})
    assert panel_single.padding == (4,)

    panel_pair = manager.render_panel(payload="ok", panel={"padding": [1, 3]})
    assert panel_pair.padding == (1, 3)

    panel_quad = manager.render_panel(payload="ok", panel={"padding": [1, 1, 1, 1]})
    assert panel_quad.padding == (1, 1, 1, 1)

    panel_scalar = manager.render_panel(payload="ok", panel={"padding": 3})
    assert panel_scalar.padding == (3, 3)

    with pytest.raises(PanelRenderingError):
        manager.render_panel(payload="oops", panel={"padding": [1, 2, 3]})

    with pytest.raises(PanelRenderingError):
        manager.render_panel(payload="oops", panel={"box": "NOT_A_STYLE"})


def test_print_panel_uses_override_console() -> None:
    """Prove callers can supply a custom console for targeted output."""
    manager = PanelManager(config={})
    custom_console = Console(record=True, width=60)

    panel = manager.print_panel(payload="hello", console=custom_console)
    assert panel is not None
    output = custom_console.export_text(clear=True)
    assert "hello" in output


def test_prepare_config_missing_global_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure manager falls back to defaults when global config is absent."""

    def _raise() -> None:
        raise ConfigNotLoadedError("no config")

    monkeypatch.setattr(panels_module, "get_config", _raise)
    monkeypatch.setattr("kstlib.ui.panels.get_config", _raise)

    manager = PanelManager(config=None)
    panel = manager.render_panel(payload="checkpoint")
    assert panel.border_style == DEFAULT_PANEL_CONFIG["defaults"]["panel"]["border_style"]


def test_prepare_config_ignores_invalid_ui_section() -> None:
    """Ignore invalid UI sections in user-provided configuration."""

    manager_invalid_ui = PanelManager(config={"ui": "oops"})
    panel_invalid_ui = manager_invalid_ui.render_panel(payload="noop")
    assert panel_invalid_ui.border_style == DEFAULT_PANEL_CONFIG["defaults"]["panel"]["border_style"]

    manager_invalid_panels = PanelManager(config={"ui": {"panels": "invalid"}})
    panel_invalid_panels = manager_invalid_panels.render_panel(payload="noop")
    assert panel_invalid_panels.border_style == DEFAULT_PANEL_CONFIG["defaults"]["panel"]["border_style"]


def test_prepare_config_handles_box_panels() -> None:
    """Support Box instances for deeply nested panel configuration."""

    config_box = {
        "ui": {
            "panels": Box(
                {
                    "defaults": {
                        "panel": {
                            "border_style": "hot_pink",
                        }
                    }
                }
            )
        }
    }

    manager = PanelManager(config=config_box)
    panel = manager.render_panel(payload="color")
    assert panel.border_style == "hot_pink"


def test_render_panel_defaults_requires_mapping() -> None:
    """Raise when defaults section is not a mapping."""

    manager = PanelManager(config={"ui": {"panels": {"defaults": []}}})

    with pytest.raises(PanelRenderingError):
        manager.render_panel(payload="oops")


def test_resolve_panel_config_accepts_direct_keys() -> None:
    """Ensure direct override keys populate the proper sections."""

    manager = PanelManager(config={})
    panel = manager.render_panel(
        payload={"item": "value"},
        border_style="yellow",
        value_style="green",
    )

    assert panel.border_style == "yellow"
    table = cast(Table, panel.renderable)
    assert table.columns[1].style == "green"


def test_render_panel_none_payload_creates_blank_text() -> None:
    """Return empty text objects when the payload is missing."""

    manager = PanelManager(config={})
    panel = manager.render_panel(payload=None)

    assert isinstance(panel.renderable, Text)
    assert panel.renderable.plain == ""


def test_render_panel_renderable_payload_passthrough() -> None:
    """Reuse renderables that already satisfy the Rich protocol."""

    manager = PanelManager(config={})
    payload = Text("native")
    panel = manager.render_panel(payload=payload)

    assert panel.renderable is payload


def test_render_panel_string_respects_markup_flag() -> None:
    """Fallback to plain text when markup is disabled."""

    manager = PanelManager(config={})
    panel = manager.render_panel(payload="[bold]raw[/bold]", content={"use_markup": False})

    assert isinstance(panel.renderable, Text)
    assert panel.renderable.plain == "[bold]raw[/bold]"


def test_render_panel_table_preserves_renderable_values() -> None:
    """Keep pre-rendered values untouched inside tables."""

    manager = PanelManager(config={})
    value = Text("rich", style="bold")
    panel = manager.render_panel(payload=[("key", value)])
    table = cast(Table, panel.renderable)
    value_cell = next(iter(table.columns[1].cells))
    assert value_cell is value


def test_render_panel_table_applies_markup_value_style() -> None:
    """Apply markup styling when value markup is enabled."""

    manager = PanelManager(config={})
    panel = manager.render_panel(
        payload={"msg": "[bold]hi[/bold]"},
        content={"value_style": "italic", "show_header": False},
    )
    table = cast(Table, panel.renderable)
    value_cell = next(iter(table.columns[1].cells))

    assert isinstance(value_cell, Text)
    assert value_cell.style == "italic"
    assert value_cell.plain == "hi"


def test_render_panel_table_plain_value_style_without_markup() -> None:
    """Style plain text values when markup support is disabled."""

    manager = PanelManager(config={})
    panel = manager.render_panel(
        payload={"msg": "plain"},
        content={"use_markup": False, "value_style": "yellow"},
    )
    table = cast(Table, panel.renderable)
    value_cell = next(iter(table.columns[1].cells))

    assert isinstance(value_cell, Text)
    assert value_cell.style == "yellow"
    assert value_cell.plain == "plain"


def test_render_panel_table_plain_without_style() -> None:
    """Render plain text without styling when markup is disabled."""

    manager = PanelManager(config={})
    panel = manager.render_panel(
        payload={"msg": "bare"},
        content={"use_markup": False},
    )
    table = cast(Table, panel.renderable)
    value_cell = next(iter(table.columns[1].cells))

    assert isinstance(value_cell, Text)
    assert value_cell.style == ""
    assert value_cell.plain == "bare"


def test_render_panel_table_repr_style_when_pretty_disabled() -> None:
    """Render repr strings with styling when pretty formatting is off."""

    manager = PanelManager(config={})
    panel = manager.render_panel(
        payload={"data": {"a": 1}},
        content={"use_pretty": False, "value_style": "dim"},
    )
    table = cast(Table, panel.renderable)
    value_cell = next(iter(table.columns[1].cells))

    assert isinstance(value_cell, Text)
    assert value_cell.style == "dim"
    assert value_cell.plain == "{'a': 1}"


def test_render_panel_icon_only_title() -> None:
    """Render icon-only titles without an explicit heading."""

    manager = PanelManager(config={})
    panel = manager.render_panel(payload="hi", panel={"icon": "[warn]", "title": None})

    assert panel.title == "[warn]"


def test_print_panel_initializes_console() -> None:
    """Create a console lazily when none was supplied."""

    manager = PanelManager(config={})
    assert manager.console is None

    panel = manager.print_panel(payload="auto")

    assert isinstance(panel, Panel)
    assert manager.console is not None


def test_print_panel_raises_when_console_creation_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Propagate an error if the fallback console cannot be built."""

    manager = PanelManager(config={})

    monkeypatch.setattr("kstlib.ui.panels.Console", lambda: None)
    manager.console = None

    with pytest.raises(PanelRenderingError):
        manager.print_panel(payload="boom")


def test_render_panel_invalid_sequence_payload_raises() -> None:
    """Reject sequence payloads that do not contain key/value pairs."""

    manager = PanelManager(config={})

    with pytest.raises(PanelRenderingError):
        manager.render_panel(payload=cast(PanelPayload, [("solo",)]))
