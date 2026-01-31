"""Config-driven helpers for rendering Rich panels."""

from __future__ import annotations

# pylint: disable=duplicate-code
import asyncio
import copy
from collections.abc import Iterable, Mapping, Sequence
from numbers import Number
from typing import Any, TypeGuard, cast

from box import Box
from rich import box as rich_box
from rich.console import Console, RenderableType
from rich.panel import Panel
from rich.pretty import Pretty
from rich.table import Table
from rich.text import Text

from kstlib.config import ConfigNotLoadedError, get_config
from kstlib.ui.exceptions import PanelRenderingError
from kstlib.utils.dict import deep_merge

PanelPayload = RenderableType | Mapping[str, Any] | Sequence[tuple[Any, Any]] | str | None

PAIR_ENTRY_LENGTH = 2
DEFAULT_PADDING: tuple[int, int] = (1, 2)
VALID_PADDING_LENGTHS = {1, 2, 4}
DEFAULT_PRETTY_INDENT = 2

DEFAULT_PANEL_CONFIG: dict[str, Any] = {
    "defaults": {
        "panel": {
            "border_style": "bright_blue",
            "title_align": "left",
            "subtitle_align": "left",
            "padding": [1, 2],
            "expand": True,
            "highlight": False,
            "box": "ROUNDED",
            "icon": None,
            "width": None,
        },
        "content": {
            "box": "SIMPLE",
            "expand": True,
            "show_header": False,
            "key_label": "Key",
            "value_label": "Value",
            "key_style": "bold white",
            "value_style": None,
            "header_style": "bold",
            "pad_edge": False,
            "sort_keys": False,
            "use_markup": True,
            "use_pretty": True,
            "pretty_indent": 2,
        },
    },
    "presets": {
        "info": {
            "panel": {
                "border_style": "cyan",
                "title": "Information",
                "icon": "[i]",
            },
        },
        "success": {
            "panel": {
                "border_style": "sea_green3",
                "title": "Success",
                "icon": "[ok]",
            },
        },
        "warning": {
            "panel": {
                "border_style": "orange3",
                "title": "Warning",
                "icon": "[!]",
            },
        },
        "error": {
            "panel": {
                "border_style": "red3",
                "title": "Error",
                "icon": "[x]",
            },
        },
        "summary": {
            "panel": {
                "border_style": "blue_violet",
                "title": "Execution Summary",
                "icon": "[summary]",
            },
            "content": {
                "sort_keys": True,
                "key_style": "bold cyan",
                "value_style": "bold white",
            },
        },
    },
}


class PanelManager:
    """Render Rich panels using config-driven presets.

    Panel definitions are composed of defaults, named presets, and runtime overrides.
    The merge order is ``kwargs > config preset > defaults``. Payloads can be plain
    text, existing Rich renderables, mappings (rendered as two-column tables), or
    sequences of ``(key, value)`` pairs.

    Args:
        config: Optional configuration mapping (typically output of ``get_config()``).
        console: Optional Rich console used for printing panels.

    Attributes:
        console: Console instance used for synchronous printing.

    Examples:
        Create a panel manager:

        >>> pm = PanelManager()
        >>> pm.console is None
        True

        Render a simple text panel:

        >>> panel = pm.render_panel(payload="Hello, World!")
        >>> panel.title is None
        True

        Render with a preset:

        >>> panel = pm.render_panel("info", payload="System status: OK")
        >>> "Information" in str(panel.title)
        True

        Render a mapping as a table:

        >>> panel = pm.render_panel(payload={"name": "Alice", "age": 30})

        Override preset values:

        >>> panel = pm.render_panel("error", payload="Oops!", title="Custom Title")
        >>> "Custom Title" in str(panel.title)
        True
    """

    def __init__(self, config: Mapping[str, Any] | Box | None = None, console: Console | None = None) -> None:
        """Initialize the manager with optional config and console."""
        self.console = console
        self._config = self._prepare_config(config)

    def render_panel(
        self,
        kind: str | None = None,
        payload: PanelPayload = None,
        **overrides: Any,
    ) -> Panel:
        """Build a ``Panel`` instance without printing it.

        Args:
            kind: Name of the preset to use. If not found, defaults are used.
            payload: Panel body (text, Rich renderable, mapping, or sequence of pairs).
            **overrides: Runtime overrides applied on top of preset/default values.

        Returns:
            Configured Rich ``Panel`` ready for rendering.

        Raises:
            PanelRenderingError: If the payload type is unsupported.
        """
        panel_config = self._resolve_panel_config(kind, overrides)
        renderable = self._build_renderable(payload, panel_config["content"])
        panel_parameters = panel_config["panel"]

        padding = self._coerce_padding(panel_parameters.get("padding"))
        panel_box = self._resolve_box(panel_parameters.get("box"))
        icon = panel_parameters.get("icon")
        title = panel_parameters.get("title")
        panel_title = self._compose_title(title, icon)

        panel_kwargs: dict[str, Any] = {
            "title": panel_title,
            "title_align": panel_parameters.get("title_align", "left"),
            "subtitle": panel_parameters.get("subtitle"),
            "subtitle_align": panel_parameters.get("subtitle_align", "left"),
            "border_style": panel_parameters.get("border_style"),
            "padding": padding,
            "expand": panel_parameters.get("expand", True),
            "highlight": panel_parameters.get("highlight", False),
            "box": panel_box,
            "width": panel_parameters.get("width"),
        }

        style_override = panel_parameters.get("style")
        if style_override is not None:
            panel_kwargs["style"] = style_override

        try:
            return Panel(renderable, **panel_kwargs)
        except Exception as exc:  # pragma: no cover - defensive guard
            raise PanelRenderingError("Failed to render panel") from exc

    def print_panel(
        self,
        kind: str | None = None,
        payload: PanelPayload = None,
        *,
        console: Console | None = None,
        **overrides: Any,
    ) -> Panel:
        """Render and print a panel synchronously.

        Args:
            kind: Name of the preset to use.
            payload: Panel body.
            console: Optional console overriding the manager-level console.
            **overrides: Runtime overrides applied on top of preset/default values.

        Returns:
            The rendered ``Panel``.
        """
        target_console = self._ensure_console(console)
        panel = self.render_panel(kind=kind, payload=payload, **overrides)
        target_console.print(panel)
        return panel

    async def print_panel_async(
        self,
        kind: str | None = None,
        payload: PanelPayload = None,
        *,
        console: Console | None = None,
        **overrides: Any,
    ) -> Panel:
        """Render and print a panel using an executor for async compatibility.

        Args:
            kind: Name of the preset to use.
            payload: Panel body.
            console: Optional console overriding the manager-level console.
            **overrides: Runtime overrides applied on top of preset/default values.

        Returns:
            The rendered ``Panel``.
        """
        target_console = self._ensure_console(console)
        return await asyncio.to_thread(
            self.print_panel,
            kind,
            payload,
            console=target_console,
            **overrides,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _prepare_config(self, config: Mapping[str, Any] | Box | None) -> dict[str, Any]:
        base_config = copy.deepcopy(DEFAULT_PANEL_CONFIG)
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

        panels_config = ui_config.get("panels", {})
        if isinstance(panels_config, Box):
            return panels_config.to_dict()
        if isinstance(panels_config, Mapping):
            return dict(panels_config)
        return {}

    def _resolve_panel_config(self, kind: str | None, overrides: Mapping[str, Any]) -> dict[str, Any]:
        defaults = copy.deepcopy(self._config["defaults"])
        if not isinstance(defaults, dict):
            raise PanelRenderingError("Panel defaults configuration must be a mapping")
        config: dict[str, Any] = defaults

        preset: Mapping[str, Any] = {}
        raw_presets = self._config.get("presets", {})
        if isinstance(raw_presets, Mapping):
            candidate = raw_presets.get(kind or "", {})
            if isinstance(candidate, Mapping):
                preset = candidate

        deep_merge(config, preset)
        if overrides:
            normalized = self._normalize_overrides(overrides)
            deep_merge(config, normalized)
        return config

    def _normalize_overrides(self, overrides: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        normalized: dict[str, dict[str, Any]] = {"panel": {}, "content": {}}
        panel_overrides = normalized["panel"]
        content_overrides = normalized["content"]
        direct_panel_keys = {
            "title",
            "title_align",
            "subtitle",
            "subtitle_align",
            "border_style",
            "padding",
            "expand",
            "highlight",
            "box",
            "icon",
            "width",
            "style",
        }
        direct_content_keys = {
            "box",
            "expand",
            "show_header",
            "key_label",
            "value_label",
            "key_style",
            "value_style",
            "header_style",
            "pad_edge",
            "sort_keys",
            "use_markup",
            "use_pretty",
            "pretty_indent",
        }
        for key, value in overrides.items():
            if key in ("panel", "content") and isinstance(value, Mapping):
                deep_merge(normalized[key], value)
                continue
            if key in direct_panel_keys:
                panel_overrides[key] = value
            elif key in direct_content_keys:
                content_overrides[key] = value
        return normalized

    def _build_renderable(self, payload: PanelPayload, content_config: dict[str, Any]) -> RenderableType:
        if payload is None:
            return Text("")
        if self._is_renderable(payload):
            return payload
        if isinstance(payload, str):
            if content_config.get("use_markup", True):
                return Text.from_markup(payload)
            return Text(payload)
        if isinstance(payload, Mapping):
            return self._mapping_to_table(payload, content_config)
        if isinstance(payload, Sequence):
            pairs = [tuple(item) for item in payload]
            if all(len(pair) == PAIR_ENTRY_LENGTH for pair in pairs):
                return self._pairs_to_table(pairs, content_config)
        raise PanelRenderingError(f"Unsupported payload type: {type(payload)!r}")

    def _mapping_to_table(self, payload: Mapping[str, Any], content_config: dict[str, Any]) -> Table:
        items: Iterable[tuple[str, Any]] = payload.items()
        if content_config.get("sort_keys", False):
            items = sorted(items, key=lambda item: str(item[0]))
        return self._pairs_to_table(list(items), content_config)

    def _pairs_to_table(self, pairs: Sequence[tuple[Any, Any]], content_config: dict[str, Any]) -> Table:
        table_box = self._resolve_box(content_config.get("box"), default="SIMPLE")
        table = Table(
            show_header=content_config.get("show_header", False),
            header_style=content_config.get("header_style"),
            box=table_box,
            expand=content_config.get("expand", True),
            pad_edge=content_config.get("pad_edge", False),
        )

        key_label = content_config.get("key_label", "Key")
        value_label = content_config.get("value_label", "Value")
        key_style = cast("str | None", content_config.get("key_style"))
        value_style = cast("str | None", content_config.get("value_style"))
        table.add_column(key_label, style=key_style)
        table.add_column(value_label, style=value_style)

        for key, value in pairs:
            key_renderable = self._to_text(key, key_style)
            value_renderable = self._render_value(value, content_config)
            table.add_row(key_renderable, value_renderable)
        return table

    def _render_value(self, value: Any, content_config: dict[str, Any]) -> RenderableType:
        if self._is_renderable(value):
            return value
        value_style = cast("str | None", content_config.get("value_style"))
        if isinstance(value, str):
            return self._render_string_value(value, value_style, content_config)
        if isinstance(value, Number):
            return self._render_numeric_value(value, value_style)
        if content_config.get("use_pretty", True):
            indent = content_config.get("pretty_indent", DEFAULT_PRETTY_INDENT)
            return Pretty(value, indent_guides=indent)
        return self._render_repr_value(value, value_style)

    @staticmethod
    def _render_string_value(value: str, value_style: str | None, content_config: dict[str, Any]) -> Text:
        use_markup = content_config.get("use_markup", True)
        if use_markup:
            if value_style:
                return Text.from_markup(value, style=value_style)
            return Text.from_markup(value)
        if value_style:
            return Text(value, style=value_style)
        return Text(value)

    @staticmethod
    def _render_numeric_value(value: Number, value_style: str | None) -> Text:
        formatted = Text(str(value))
        if value_style:
            formatted.stylize(value_style)
        return formatted

    @staticmethod
    def _render_repr_value(value: Any, value_style: str | None) -> Text:
        representation = repr(value)
        if value_style:
            return Text(representation, style=value_style)
        return Text(representation)

    @staticmethod
    def _to_text(value: Any, style: str | None = None) -> Text:
        text = Text(str(value))
        if style:
            text.stylize(style)
        return text

    @staticmethod
    def _compose_title(title: str | None, icon: str | None) -> str | None:
        if title and icon:
            return f"{icon} {title}"
        if icon:
            return icon
        return title

    @staticmethod
    def _is_renderable(candidate: Any) -> TypeGuard[RenderableType]:
        return hasattr(candidate, "__rich_console__") or hasattr(candidate, "__rich__")

    @staticmethod
    def _coerce_padding(padding: Any) -> tuple[int, ...]:
        if padding is None:
            return DEFAULT_PADDING
        if isinstance(padding, list | tuple):
            coerced = tuple(int(part) for part in padding)
            if len(coerced) in VALID_PADDING_LENGTHS:
                return coerced
            raise PanelRenderingError("Padding must contain 1, 2, or 4 integers.")
        value = int(padding)
        return (value, value)

    @staticmethod
    def _resolve_box(box_name: str | None, default: str = "ROUNDED") -> rich_box.Box:
        if not box_name:
            box_name = default
        try:
            return cast("rich_box.Box", getattr(rich_box, box_name))
        except AttributeError as exc:
            raise PanelRenderingError(f"Unknown box style '{box_name}'") from exc

    def _ensure_console(self, console: Console | None) -> Console:
        if console is not None:
            return console
        if self.console is None:
            self.console = Console()
        if self.console is None:  # pragma: no cover - defensive guard
            raise PanelRenderingError("Console instance could not be created")
        return self.console
