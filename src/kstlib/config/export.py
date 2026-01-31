"""Configuration export helpers."""

from __future__ import annotations

import io
import json
import shutil
from configparser import ConfigParser
from dataclasses import dataclass
from importlib import import_module, resources
from pathlib import Path
from typing import Any, Final, cast

import yaml

from kstlib.config.loader import CONFIG_FILENAME

try:
    _TOMLI_W: Any = import_module("tomli_w")
except ModuleNotFoundError:  # pragma: no cover - dependency optional for tests until installed
    _TOMLI_W = None


_SUPPORTED_EXTENSIONS: Final[dict[str, str]] = {
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".ini": "ini",
}
_DEFAULT_FORMAT: Final[str] = "yaml"


class ConfigExportError(RuntimeError):
    """Raised when configuration export fails."""


@dataclass(frozen=True)
class ConfigExportOptions:
    """Options controlling the configuration export behavior."""

    section: str | None = None
    out_path: Path | None = None
    stdout: bool = False
    force: bool = False


@dataclass(frozen=True)
class ConfigExportResult:
    """Outcome of a configuration export."""

    destination: Path | None
    content: str | None
    format_name: str


def export_configuration(options: ConfigExportOptions) -> ConfigExportResult:
    """Export the packaged configuration to disk or stdout."""
    if options.stdout and options.out_path is not None:
        raise ConfigExportError("Cannot combine --stdout with --out; choose one destination.")

    resource = resources.files("kstlib").joinpath(CONFIG_FILENAME)
    with resources.as_file(resource) as source_path:
        if not source_path.is_file():
            raise ConfigExportError("Packaged configuration file is missing.")

        if options.section is None:
            return _export_full_config(source_path, options)

        data = _load_yaml(source_path)
        selected, path_parts = _select_section(data, options.section)
        wrapped = _wrap_with_path(selected, path_parts)
        format_name, destination = _resolve_output(options, _DEFAULT_FORMAT)

        serialized = _serialize_data(wrapped, format_name)

        if options.stdout:
            return ConfigExportResult(destination=None, content=serialized, format_name=format_name)

        _write_text(serialized, destination, options.force)
        return ConfigExportResult(destination=destination, content=None, format_name=format_name)


def _export_full_config(source_path: Path, options: ConfigExportOptions) -> ConfigExportResult:
    if options.stdout:
        return ConfigExportResult(
            destination=None,
            content=source_path.read_text(encoding="utf-8"),
            format_name=_DEFAULT_FORMAT,
        )

    format_name, destination = _resolve_output(options, _DEFAULT_FORMAT)

    if format_name == "yaml":
        _copy_file(source_path, destination, options.force)
        return ConfigExportResult(destination=destination, content=None, format_name=format_name)

    data = _load_yaml(source_path)
    serialized = _serialize_data(data, format_name)
    _write_text(serialized, destination, options.force)
    return ConfigExportResult(destination=destination, content=None, format_name=format_name)


def _serialize_data(data: Any, format_name: str) -> str:
    if format_name == "yaml":
        return yaml.safe_dump(data, sort_keys=False)
    if format_name == "json":
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if format_name == "toml":
        if _TOMLI_W is None:
            raise ConfigExportError("TOML export requires the 'tomli-w' package.")
        return cast("str", _TOMLI_W.dumps(data))
    if format_name == "ini":
        parser = ConfigParser()
        flattened = _flatten_for_ini(data)
        for section, values in flattened.items():
            parser[section] = values
        buffer = io.StringIO()
        parser.write(buffer)
        return buffer.getvalue()
    raise ConfigExportError(f"Unsupported output format '{format_name}'.")


def _flatten_for_ini(data: Any) -> dict[str, dict[str, str]]:
    if not isinstance(data, dict):
        raise ConfigExportError("INI export requires dictionary data.")

    result: dict[str, dict[str, str]] = {}
    for section, value in data.items():
        section_name = str(section)
        entries: dict[str, str] = {}
        if isinstance(value, dict):
            for key, item in _walk_items(value):
                entries[key] = _stringify(item)
        else:
            entries["value"] = _stringify(value)
        result[section_name] = entries
    return result


def _walk_items(value: Any, prefix: str | None = None) -> list[tuple[str, Any]]:
    if isinstance(value, dict):
        items: list[tuple[str, Any]] = []
        for key, child in value.items():
            sub_key = f"{prefix}.{key}" if prefix else str(key)
            items.extend(_walk_items(child, sub_key))
        return items
    if isinstance(value, list):
        return [(f"{prefix}[{idx}]", child) for idx, child in enumerate(value)]
    return [(prefix or "value", value)]


def _stringify(value: Any) -> str:
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _resolve_output(options: ConfigExportOptions, default_format: str) -> tuple[str, Path]:
    out_path = options.out_path
    if out_path is None:
        destination = Path.cwd() / CONFIG_FILENAME
    elif out_path.suffix and out_path.suffix in _SUPPORTED_EXTENSIONS:
        destination = out_path
    elif out_path.exists() and out_path.is_dir():
        destination = out_path / CONFIG_FILENAME
    elif out_path.suffix:
        # Unknown suffix, treat as file but default format
        destination = out_path
    else:
        destination = out_path / CONFIG_FILENAME

    suffix = destination.suffix.lower()
    format_name = _SUPPORTED_EXTENSIONS.get(suffix, default_format)

    if suffix and suffix.lower() not in _SUPPORTED_EXTENSIONS:
        if format_name != default_format:
            raise ConfigExportError(f"Unsupported file extension '{suffix}'.")
        destination = destination.with_suffix(f".{default_format}")

    return format_name, destination


def _copy_file(source: Path, destination: Path, force: bool) -> None:
    if destination.exists() and not force:
        raise ConfigExportError(f"Destination '{destination}' already exists. Use --force to overwrite.")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    shutil.copy2(source, destination)


def _write_text(content: str, destination: Path, force: bool) -> None:
    if destination.exists() and not force:
        raise ConfigExportError(f"Destination '{destination}' already exists. Use --force to overwrite.")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    destination.write_text(content, encoding="utf-8")


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _select_section(data: dict[str, Any], dotted_path: str) -> tuple[Any, list[str]]:
    path_parts = dotted_path.split(".")
    current: Any = data
    for part in path_parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        raise ConfigExportError(f"Section '{dotted_path}' not found in default configuration.")
    return current, path_parts


def _wrap_with_path(value: Any, path_parts: list[str]) -> Any:
    wrapped: Any = value
    for part in reversed(path_parts):
        wrapped = {part: wrapped}
    return wrapped


__all__: Final[tuple[str, ...]] = (
    "ConfigExportError",
    "ConfigExportOptions",
    "ConfigExportResult",
    "export_configuration",
)
