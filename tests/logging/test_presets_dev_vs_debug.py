"""Tests for the differentiation between the 'dev' and 'debug' presets.

The two presets target distinct workflows:

- ``dev`` is the everyday iteration preset: console only, DEBUG level. Fast,
  no file I/O, does not pollute the working tree.
- ``debug`` is the investigation preset: both console and file, TRACE level.
  Persists logs to disk so they survive the terminal session and can be
  grepped or shared, and captures HTTP traces and per-item diagnostics.

These tests guard the contract so a future refactor cannot accidentally
collapse the two presets back into the same configuration.
"""

from __future__ import annotations

from kstlib.logging.manager import FALLBACK_PRESETS, LogManager


class TestFallbackPresets:
    """Built-in (no-config-file) fallback presets keep the contract."""

    def test_dev_is_console_debug(self) -> None:
        """Built-in dev preset: console only, DEBUG."""
        dev = FALLBACK_PRESETS["dev"]
        assert dev["output"] == "console"
        assert dev["console"]["level"] == "DEBUG"

    def test_debug_is_both_trace(self) -> None:
        """Built-in debug preset: console + file, TRACE on both handlers."""
        dbg = FALLBACK_PRESETS["debug"]
        assert dbg["output"] == "both"
        assert dbg["console"]["level"] == "TRACE"
        assert dbg["file"]["level"] == "TRACE"

    def test_dev_and_debug_are_distinct(self) -> None:
        """The two presets must differ on at least output OR console level.

        If they ever match (output AND console level identical), the split
        loses its purpose and the rest of the convention falls apart.
        """
        dev = FALLBACK_PRESETS["dev"]
        dbg = FALLBACK_PRESETS["debug"]
        assert (dev["output"], dev["console"]["level"]) != (
            dbg["output"],
            dbg["console"]["level"],
        )


class TestLogManagerWithPresets:
    """LogManager picks up the differentiated config when a preset is requested."""

    def test_dev_preset_resolves_console_debug(self) -> None:
        """LogManager(preset='dev') -> output=console, console.level=DEBUG."""
        mgr = LogManager(preset="dev", register=False)
        assert mgr._config.output == "console"
        assert mgr._config.console.level == "DEBUG"

    def test_debug_preset_resolves_both_trace(self) -> None:
        """LogManager(preset='debug') -> output=both, console+file at TRACE."""
        mgr = LogManager(preset="debug", register=False)
        assert mgr._config.output == "both"
        assert mgr._config.console.level == "TRACE"
        assert mgr._config.file.level == "TRACE"

    def test_dev_handler_only_console(self) -> None:
        """dev preset wires only a console handler (no file rotation)."""
        mgr = LogManager(preset="dev", register=False)
        # output=console -> _setup_console_handler runs, _setup_file_handler does not.
        # Handlers attached to the LogManager instance reflect this.
        handler_classes = [type(h).__name__ for h in mgr.handlers]
        assert "RichHandler" in handler_classes
        assert "TimedRotatingFileHandler" not in handler_classes

    def test_debug_handler_has_both(self) -> None:
        """debug preset wires both a console handler AND a file handler."""
        mgr = LogManager(preset="debug", register=False)
        handler_classes = [type(h).__name__ for h in mgr.handlers]
        assert "RichHandler" in handler_classes
        assert "TimedRotatingFileHandler" in handler_classes

    def test_debug_preset_file_format_contains_caller_context(self) -> None:
        """debug preset file format includes filename:lineno funcName for incident debugging."""
        mgr = LogManager(preset="debug", register=False)
        fmt = mgr._config.file.format
        assert "%(filename)s" in fmt
        assert "%(lineno)d" in fmt
        assert "%(funcName)s" in fmt

    def test_trace_preset_file_format_contains_caller_context(self) -> None:
        """trace preset file format includes filename:lineno funcName for incident debugging."""
        mgr = LogManager(preset="trace", register=False)
        fmt = mgr._config.file.format
        assert "%(filename)s" in fmt
        assert "%(lineno)d" in fmt
        assert "%(funcName)s" in fmt

    def test_prod_preset_file_format_unchanged(self) -> None:
        """prod preset file format must NOT include caller context (preserve clean prod logs)."""
        mgr = LogManager(preset="prod", register=False)
        fmt = mgr._config.file.format
        assert "%(filename)s" not in fmt
        assert "%(funcName)s" not in fmt
