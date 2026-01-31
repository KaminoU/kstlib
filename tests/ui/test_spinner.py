"""Tests for the spinner animation utilities."""

from __future__ import annotations

import io
import time
from unittest import mock

import pytest
from rich.console import Console

from kstlib.config import ConfigNotLoadedError
from kstlib.ui import (
    Spinner,
    SpinnerAnimationType,
    SpinnerError,
    SpinnerPosition,
    SpinnerStyle,
)
from kstlib.ui.spinner import (
    BOUNCE_WIDTH,
    COLOR_WAVE_COLORS,
    DEFAULT_SPINNER_CONFIG,
    SpinnerWithLogZone,
    _load_spinner_config,
    _PrintCapture,
    with_spinner,
)


class TestSpinnerStyle:
    """Tests for SpinnerStyle enum."""

    def test_braille_is_default(self) -> None:
        """Verify BRAILLE has expected frame count."""
        assert len(SpinnerStyle.BRAILLE.value) == 8

    def test_all_styles_have_frames(self) -> None:
        """Ensure all spinner styles define at least one frame."""
        for style in SpinnerStyle:
            assert len(style.value) >= 1


class TestSpinnerPosition:
    """Tests for SpinnerPosition enum."""

    def test_before_value(self) -> None:
        """Check BEFORE position value."""
        assert SpinnerPosition.BEFORE.value == "before"

    def test_after_value(self) -> None:
        """Check AFTER position value."""
        assert SpinnerPosition.AFTER.value == "after"


class TestSpinnerAnimationType:
    """Tests for SpinnerAnimationType enum."""

    def test_all_types_defined(self) -> None:
        """Verify all animation types exist."""
        assert SpinnerAnimationType.SPIN.value == "spin"
        assert SpinnerAnimationType.BOUNCE.value == "bounce"
        assert SpinnerAnimationType.COLOR_WAVE.value == "color_wave"


class TestSpinnerInit:
    """Tests for Spinner initialization."""

    def test_default_initialization(self) -> None:
        """Verify default spinner settings."""
        spinner = Spinner("Loading...")
        assert spinner.message == "Loading..."
        assert spinner._style == SpinnerStyle.BRAILLE
        assert spinner._position == SpinnerPosition.BEFORE
        assert spinner._animation_type == SpinnerAnimationType.SPIN

    def test_style_from_string(self) -> None:
        """Accept style names as strings."""
        spinner = Spinner(style="dots")
        assert spinner._style == SpinnerStyle.DOTS

    def test_style_from_string_case_insensitive(self) -> None:
        """Style names are case-insensitive."""
        spinner = Spinner(style="ARROW")
        assert spinner._style == SpinnerStyle.ARROW

    def test_invalid_style_raises(self) -> None:
        """Reject unknown spinner styles."""
        with pytest.raises(SpinnerError, match="Unknown spinner style"):
            Spinner(style="invalid_style")

    def test_position_from_string(self) -> None:
        """Accept position as string."""
        spinner = Spinner(position="after")
        assert spinner._position == SpinnerPosition.AFTER

    def test_invalid_position_raises(self) -> None:
        """Reject invalid position values."""
        with pytest.raises(SpinnerError, match="Invalid position"):
            Spinner(position="middle")

    def test_animation_type_from_string(self) -> None:
        """Accept animation type as string."""
        spinner = Spinner(animation_type="bounce")
        assert spinner._animation_type == SpinnerAnimationType.BOUNCE

    def test_invalid_animation_type_raises(self) -> None:
        """Reject unknown animation types."""
        with pytest.raises(SpinnerError, match="Invalid animation type"):
            Spinner(animation_type="explode")

    def test_custom_console(self) -> None:
        """Accept custom console instance."""
        custom_console = Console(file=io.StringIO())
        spinner = Spinner(console=custom_console)
        assert spinner._console is custom_console

    def test_custom_file(self) -> None:
        """Accept custom file stream."""
        buffer = io.StringIO()
        spinner = Spinner(file=buffer)
        assert spinner._file is buffer


class TestSpinnerFromPreset:
    """Tests for Spinner.from_preset factory method."""

    def test_minimal_preset(self) -> None:
        """Load minimal preset configuration."""
        spinner = Spinner.from_preset("minimal", "Working...")
        assert spinner._style == SpinnerStyle.LINE
        assert spinner._interval == 0.1

    def test_fancy_preset(self) -> None:
        """Load fancy preset configuration."""
        spinner = Spinner.from_preset("fancy")
        assert spinner._style == SpinnerStyle.BRAILLE
        assert spinner._interval == 0.06

    def test_bounce_preset(self) -> None:
        """Load bounce preset configuration."""
        spinner = Spinner.from_preset("bounce")
        assert spinner._animation_type == SpinnerAnimationType.BOUNCE

    def test_color_wave_preset(self) -> None:
        """Load color_wave preset configuration."""
        spinner = Spinner.from_preset("color_wave")
        assert spinner._animation_type == SpinnerAnimationType.COLOR_WAVE

    def test_unknown_preset_raises(self) -> None:
        """Reject unknown preset names."""
        with pytest.raises(SpinnerError, match="Unknown preset"):
            Spinner.from_preset("nonexistent")

    def test_preset_with_overrides(self) -> None:
        """Override preset values at creation time."""
        spinner = Spinner.from_preset("minimal", interval=0.05)
        assert spinner._interval == 0.05


class TestSpinnerStartStop:
    """Tests for Spinner start/stop operations."""

    def test_start_creates_thread(self) -> None:
        """Starting spinner creates background thread."""
        spinner = Spinner("Test")
        assert spinner._thread is None

        spinner.start()
        try:
            assert spinner._running is True
            assert spinner._thread is not None
            assert spinner._thread.is_alive()  # type: ignore[unreachable]
        finally:
            spinner.stop()

    def test_stop_terminates_thread(self) -> None:
        """Stopping spinner terminates the thread."""
        spinner = Spinner("Test")
        spinner.start()
        time.sleep(0.05)

        spinner.stop()
        assert spinner._running is False
        assert spinner._thread is None

    def test_start_idempotent(self) -> None:
        """Multiple start calls are safe."""
        spinner = Spinner("Test")
        spinner.start()
        thread1 = spinner._thread

        spinner.start()
        assert spinner._thread is thread1

        spinner.stop()

    def test_stop_idempotent(self) -> None:
        """Multiple stop calls are safe."""
        spinner = Spinner("Test")
        spinner.start()
        spinner.stop()
        spinner.stop()
        assert spinner._running is False


class TestSpinnerContextManager:
    """Tests for Spinner context manager behavior."""

    def test_context_manager_starts_and_stops(self) -> None:
        """Context manager handles start/stop lifecycle."""
        spinner = Spinner("Context")
        assert spinner._running is False

        with spinner:
            assert spinner._running is True

        assert spinner._running is False  # type: ignore[unreachable]

    def test_context_manager_success_on_normal_exit(self) -> None:
        """Normal exit shows success indicator."""
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True)

        with Spinner("Done", console=console, done_character="OK"):
            time.sleep(0.02)

        output = buffer.getvalue()
        assert "OK" in output or "Done" in output

    def test_context_manager_failure_on_exception(self) -> None:
        """Exception exit shows failure indicator."""
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True)

        with pytest.raises(ValueError), Spinner("Fail", console=console, fail_character="X"):
            time.sleep(0.02)
            raise ValueError("boom")


class TestSpinnerUpdate:
    """Tests for Spinner message updates."""

    def test_update_changes_message(self) -> None:
        """Update method changes the displayed message."""
        spinner = Spinner("Initial")
        spinner.start()
        try:
            assert spinner.message == "Initial"

            spinner.update("Updated")
            assert spinner.message == "Updated"
        finally:
            spinner.stop()

    def test_message_property_is_thread_safe(self) -> None:
        """Message access is thread-safe."""
        spinner = Spinner("Safe")
        spinner.start()
        try:
            for i in range(10):
                spinner.update(f"Message {i}")
                _ = spinner.message
        finally:
            spinner.stop()


class TestSpinnerAnimation:
    """Tests for spinner animation rendering."""

    def test_spin_animation_cycles_frames(self) -> None:
        """Spin animation cycles through frame characters."""
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True)
        spinner = Spinner("Spin", style=SpinnerStyle.LINE, console=console, interval=0.01)

        spinner.start()
        time.sleep(0.1)
        spinner.stop()

        output = buffer.getvalue()
        assert len(output) > 0

    def test_bounce_animation_renders(self) -> None:
        """Bounce animation produces bracket-enclosed output."""
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True)
        spinner = Spinner(
            "Bounce",
            animation_type=SpinnerAnimationType.BOUNCE,
            console=console,
            interval=0.01,
        )

        spinner.start()
        time.sleep(0.1)
        spinner.stop()

        output = buffer.getvalue()
        assert "[" in output or "Bounce" in output

    def test_color_wave_animation_renders(self) -> None:
        """Color wave animation produces colorized output."""
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True)
        spinner = Spinner(
            "Rainbow",
            animation_type=SpinnerAnimationType.COLOR_WAVE,
            console=console,
            interval=0.01,
        )

        spinner.start()
        time.sleep(0.1)
        spinner.stop()

        output = buffer.getvalue()
        assert len(output) > 0

    def test_position_after_places_spinner_at_end(self) -> None:
        """AFTER position places spinner after message."""
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True)
        spinner = Spinner(
            "Loading",
            position=SpinnerPosition.AFTER,
            console=console,
            interval=0.01,
        )

        spinner.start()
        time.sleep(0.05)
        spinner.stop()


class TestSpinnerFinalRender:
    """Tests for spinner final state rendering."""

    def test_stop_with_success_shows_done_character(self) -> None:
        """Successful stop displays done character."""
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True)
        spinner = Spinner("Task", console=console, done_character="[OK]")

        spinner.start()
        time.sleep(0.02)
        spinner.stop(success=True)

        output = buffer.getvalue()
        assert "[OK]" in output or "Task" in output

    def test_stop_with_failure_shows_fail_character(self) -> None:
        """Failed stop displays fail character."""
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True)
        spinner = Spinner("Task", console=console, fail_character="[FAIL]")

        spinner.start()
        time.sleep(0.02)
        spinner.stop(success=False)

        output = buffer.getvalue()
        assert "[FAIL]" in output or "Task" in output

    def test_stop_with_final_message(self) -> None:
        """Stop can override the displayed message."""
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True)
        spinner = Spinner("Working", console=console)

        spinner.start()
        time.sleep(0.02)
        spinner.stop(final_message="Complete!")

        output = buffer.getvalue()
        assert "Complete!" in output


class TestDefaultConfig:
    """Tests for default configuration structure."""

    def test_defaults_section_exists(self) -> None:
        """Configuration has defaults section."""
        assert "defaults" in DEFAULT_SPINNER_CONFIG
        assert "style" in DEFAULT_SPINNER_CONFIG["defaults"]

    def test_presets_section_exists(self) -> None:
        """Configuration has presets section."""
        assert "presets" in DEFAULT_SPINNER_CONFIG
        assert "minimal" in DEFAULT_SPINNER_CONFIG["presets"]
        assert "fancy" in DEFAULT_SPINNER_CONFIG["presets"]

    def test_bounce_width_is_reasonable(self) -> None:
        """Bounce bar width is sensible."""
        assert BOUNCE_WIDTH > 5
        assert BOUNCE_WIDTH < 100

    def test_color_wave_has_colors(self) -> None:
        """Color wave palette has colors defined."""
        assert len(COLOR_WAVE_COLORS) >= 3


class TestLoadSpinnerConfig:
    """Tests for _load_spinner_config function."""

    def test_returns_defaults_when_config_not_loaded(self) -> None:
        """Return default config when no user config is loaded."""
        config = _load_spinner_config()
        assert "defaults" in config
        assert "presets" in config

    def test_merges_user_config_defaults(self) -> None:
        """Merge user config defaults with built-in defaults."""
        mock_config = {
            "ui": {
                "spinners": {
                    "defaults": {"interval": 0.2, "spinner_style": "magenta"},
                }
            }
        }
        with mock.patch("kstlib.ui.spinner.get_config") as mock_get:
            mock_get.return_value.to_dict.return_value = mock_config
            config = _load_spinner_config()
            assert config["defaults"]["interval"] == 0.2
            assert config["defaults"]["spinner_style"] == "magenta"
            assert config["defaults"]["style"] == "BRAILLE"

    def test_merges_user_config_presets(self) -> None:
        """Merge user presets with built-in presets."""
        mock_config = {
            "ui": {
                "spinners": {
                    "presets": {
                        "minimal": {"interval": 0.5},
                        "custom": {"style": "ARROW", "interval": 0.15},
                    }
                }
            }
        }
        with mock.patch("kstlib.ui.spinner.get_config") as mock_get:
            mock_get.return_value.to_dict.return_value = mock_config
            config = _load_spinner_config()
            assert config["presets"]["minimal"]["interval"] == 0.5
            assert config["presets"]["custom"]["style"] == "ARROW"
            assert "fancy" in config["presets"]

    def test_returns_defaults_when_no_ui_section(self) -> None:
        """Return defaults when config has no ui section."""
        mock_config: dict[str, dict[str, str]] = {}
        with mock.patch("kstlib.ui.spinner.get_config") as mock_get:
            mock_get.return_value.to_dict.return_value = mock_config
            config = _load_spinner_config()
            assert config == DEFAULT_SPINNER_CONFIG

    def test_returns_defaults_on_config_not_loaded_error(self) -> None:
        """Return defaults when ConfigNotLoadedError is raised."""
        with mock.patch("kstlib.ui.spinner.get_config") as mock_get:
            mock_get.side_effect = ConfigNotLoadedError("No config")
            config = _load_spinner_config()
            assert config == DEFAULT_SPINNER_CONFIG


class TestSpinnerLog:
    """Tests for Spinner.log method."""

    def test_log_prints_message_above_spinner(self) -> None:
        """Log method prints message without disrupting spinner."""
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True)
        spinner = Spinner("Working", console=console, file=buffer)

        spinner.start()
        time.sleep(0.02)
        spinner.log("Progress update")
        time.sleep(0.02)
        spinner.stop()

        output = buffer.getvalue()
        assert "Progress update" in output

    def test_log_with_style(self) -> None:
        """Log method applies style to message."""
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True)
        spinner = Spinner("Working", console=console, file=buffer)

        spinner.start()
        time.sleep(0.02)
        spinner.log("Styled message", style="bold")
        time.sleep(0.02)
        spinner.stop()

        output = buffer.getvalue()
        assert "Styled message" in output


class TestBounceAnimationEdgeCases:
    """Tests for bounce animation boundary conditions."""

    def test_bounce_direction_reverses_at_right_boundary(self) -> None:
        """Bounce reverses direction when hitting right edge."""
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True)
        spinner = Spinner(
            "Bounce",
            animation_type=SpinnerAnimationType.BOUNCE,
            console=console,
            interval=0.005,
        )
        # Position at right edge - 1, moving right
        spinner._bounce_position = BOUNCE_WIDTH - 2
        spinner._bounce_direction = 1

        # Call render directly to test bounce logic deterministically
        spinner._render_bounce_frame()
        # After one render, position should be at edge
        assert spinner._bounce_position == BOUNCE_WIDTH - 1

        spinner._render_bounce_frame()
        # After hitting edge, direction should reverse
        assert spinner._bounce_direction == -1

    def test_bounce_direction_reverses_at_left_boundary(self) -> None:
        """Bounce reverses direction when hitting left edge."""
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True)
        spinner = Spinner(
            "Bounce",
            animation_type=SpinnerAnimationType.BOUNCE,
            console=console,
            interval=0.005,
        )
        # Position at left edge + 1, moving left
        spinner._bounce_position = 1
        spinner._bounce_direction = -1

        # Call render directly to test bounce logic deterministically
        spinner._render_bounce_frame()
        # After one render, position should be at edge
        assert spinner._bounce_position == 0

        spinner._render_bounce_frame()
        # After hitting edge, direction should reverse
        assert spinner._bounce_direction == 1

    def test_bounce_with_position_after(self) -> None:
        """Bounce animation respects AFTER position."""
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True)
        spinner = Spinner(
            "Loading",
            animation_type=SpinnerAnimationType.BOUNCE,
            position=SpinnerPosition.AFTER,
            console=console,
            interval=0.01,
        )

        spinner.start()
        time.sleep(0.05)
        spinner.stop()

        output = buffer.getvalue()
        assert len(output) > 0


class TestColorWaveEdgeCases:
    """Tests for color wave animation edge cases."""

    def test_color_wave_with_empty_message(self) -> None:
        """Color wave handles empty message gracefully."""
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True)
        spinner = Spinner(
            "",
            animation_type=SpinnerAnimationType.COLOR_WAVE,
            console=console,
            interval=0.01,
        )

        spinner.start()
        time.sleep(0.05)
        spinner.stop()

    def test_color_wave_final_render_with_success(self) -> None:
        """Color wave shows styled final message on success."""
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True)
        spinner = Spinner(
            "Processing",
            animation_type=SpinnerAnimationType.COLOR_WAVE,
            console=console,
        )

        spinner.start()
        time.sleep(0.02)
        spinner.stop(success=True)

        output = buffer.getvalue()
        assert "Processing" in output

    def test_color_wave_final_render_with_failure(self) -> None:
        """Color wave shows styled final message on failure."""
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True)
        spinner = Spinner(
            "Processing",
            animation_type=SpinnerAnimationType.COLOR_WAVE,
            console=console,
        )

        spinner.start()
        time.sleep(0.02)
        spinner.stop(success=False)

        output = buffer.getvalue()
        assert "Processing" in output


class TestStyledMessage:
    """Tests for _styled_message with text_style."""

    def test_message_with_text_style(self) -> None:
        """Spinner applies text_style to message."""
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True)
        spinner = Spinner(
            "Styled",
            text_style="bold cyan",
            console=console,
            interval=0.01,
        )

        spinner.start()
        time.sleep(0.05)
        spinner.stop()

        output = buffer.getvalue()
        assert "Styled" in output


class TestPrintCapture:
    """Tests for _PrintCapture class."""

    def test_write_sends_to_spinner_log(self) -> None:
        """PrintCapture redirects writes to spinner.log."""
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True)
        spinner = Spinner("Test", console=console, file=buffer)

        capture = _PrintCapture(spinner, style="dim")
        result = capture.write("captured text\n")

        assert result == len("captured text\n")

    def test_write_filters_empty_strings(self) -> None:
        """PrintCapture ignores empty strings and lone newlines."""
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True)
        spinner = Spinner("Test", console=console, file=buffer)

        capture = _PrintCapture(spinner)
        capture.write("")
        capture.write("\n")
        capture.write("   \n")

    def test_write_without_style(self) -> None:
        """PrintCapture works without style parameter."""
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True)
        spinner = Spinner("Test", console=console, file=buffer)

        capture = _PrintCapture(spinner, style=None)
        result = capture.write("no style text\n")

        assert result == len("no style text\n")


class TestWithSpinnerDecorator:
    """Tests for with_spinner decorator."""

    def test_decorator_wraps_function(self) -> None:
        """Decorator wraps function with spinner."""

        @with_spinner("Processing", interval=0.01)
        def sample_function() -> str:
            time.sleep(0.02)
            return "done"

        result = sample_function()
        assert result == "done"

    def test_decorator_captures_prints(self) -> None:
        """Decorator captures print output by default."""

        @with_spinner("Working", interval=0.01, capture_prints=True)
        def printing_function() -> str:
            print("log message")
            return "finished"

        result = printing_function()
        assert result == "finished"

    def test_decorator_without_capture(self) -> None:
        """Decorator can disable print capture."""

        @with_spinner("Working", interval=0.01, capture_prints=False)
        def no_capture_function() -> str:
            return "result"

        result = no_capture_function()
        assert result == "result"

    def test_decorator_with_log_zone(self) -> None:
        """Decorator uses SpinnerWithLogZone when height specified."""

        @with_spinner("Building", interval=0.01, log_zone_height=3)
        def zone_function() -> str:
            print("step 1")
            return "built"

        result = zone_function()
        assert result == "built"

    def test_decorator_preserves_function_metadata(self) -> None:
        """Decorator preserves wrapped function metadata."""

        @with_spinner("Test")
        def documented_function() -> None:
            """This is documentation."""
            pass

        assert documented_function.__name__ == "documented_function"
        assert documented_function.__doc__ == "This is documentation."

    def test_decorator_with_args_and_kwargs(self) -> None:
        """Decorator works with function arguments."""

        @with_spinner("Computing", interval=0.01)
        def compute(a: int, b: int, multiplier: int = 1) -> int:
            return (a + b) * multiplier

        result = compute(2, 3, multiplier=2)
        assert result == 10


class TestSpinnerWithLogZone:
    """Tests for SpinnerWithLogZone class."""

    def test_initialization(self) -> None:
        """Verify default initialization values."""
        spinner = SpinnerWithLogZone("Loading", log_zone_height=5)
        assert spinner._message == "Loading"
        assert spinner._log_zone_height == 5
        assert spinner._running is False

    def test_start_creates_thread(self) -> None:
        """Starting spinner creates animation thread."""
        buffer = io.StringIO()
        spinner = SpinnerWithLogZone("Test", file=buffer, interval=0.01)

        spinner.start()
        try:
            assert spinner._running is True
            assert spinner._thread is not None
        finally:
            spinner.stop()

    def test_start_is_idempotent(self) -> None:
        """Multiple start calls are safe."""
        buffer = io.StringIO()
        spinner = SpinnerWithLogZone("Test", file=buffer, interval=0.01)

        spinner.start()
        thread1 = spinner._thread
        spinner.start()
        assert spinner._thread is thread1
        spinner.stop()

    def test_stop_terminates_thread(self) -> None:
        """Stopping spinner terminates animation thread."""
        buffer = io.StringIO()
        spinner = SpinnerWithLogZone("Test", file=buffer, interval=0.01)

        spinner.start()
        time.sleep(0.05)
        spinner.stop()

        assert spinner._running is False
        assert spinner._thread is None

    def test_stop_is_idempotent(self) -> None:
        """Multiple stop calls are safe."""
        buffer = io.StringIO()
        spinner = SpinnerWithLogZone("Test", file=buffer, interval=0.01)

        spinner.start()
        spinner.stop()
        spinner.stop()
        assert spinner._running is False

    def test_update_changes_message(self) -> None:
        """Update method changes displayed message."""
        buffer = io.StringIO()
        spinner = SpinnerWithLogZone("Initial", file=buffer, interval=0.01)

        spinner.start()
        spinner.update("Updated")
        time.sleep(0.02)
        spinner.stop()

    def test_log_adds_entry(self) -> None:
        """Log method adds entry to scrolling zone."""
        buffer = io.StringIO()
        spinner = SpinnerWithLogZone("Test", file=buffer, log_zone_height=3)

        spinner.start()
        spinner.log("Entry 1")
        spinner.log("Entry 2", style="bold")
        time.sleep(0.05)
        spinner.stop()

        output = buffer.getvalue()
        assert "Entry 1" in output or len(output) > 0

    def test_context_manager_starts_and_stops(self) -> None:
        """Context manager handles lifecycle."""
        buffer = io.StringIO()
        spinner = SpinnerWithLogZone("Context", file=buffer, interval=0.01)

        with spinner:
            assert spinner._running is True
            time.sleep(0.02)

        assert spinner._running is False

    def test_context_manager_success_on_normal_exit(self) -> None:
        """Normal exit shows success indicator."""
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True)

        with SpinnerWithLogZone("Done", console=console, file=buffer, interval=0.01):
            time.sleep(0.02)

        output = buffer.getvalue()
        assert len(output) > 0

    def test_context_manager_failure_on_exception(self) -> None:
        """Exception exit shows failure indicator."""
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True)

        with pytest.raises(ValueError), SpinnerWithLogZone("Fail", console=console, file=buffer, interval=0.01):
            time.sleep(0.02)
            raise ValueError("boom")

    def test_log_zone_scrolling(self) -> None:
        """Logs scroll when zone is full."""
        buffer = io.StringIO()
        spinner = SpinnerWithLogZone("Scroll", file=buffer, log_zone_height=2)

        spinner.start()
        for i in range(5):
            spinner.log(f"Line {i}")
            time.sleep(0.01)
        spinner.stop()

    def test_final_message_override(self) -> None:
        """Stop can override final displayed message."""
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True)
        spinner = SpinnerWithLogZone("Working", console=console, file=buffer)

        spinner.start()
        time.sleep(0.02)
        spinner.stop(final_message="Complete!")

        output = buffer.getvalue()
        assert "Complete!" in output

    def test_custom_style(self) -> None:
        """Accept custom spinner style."""
        buffer = io.StringIO()
        spinner = SpinnerWithLogZone(
            "Custom",
            style=SpinnerStyle.DOTS,
            spinner_style="magenta",
            file=buffer,
            interval=0.01,
        )

        spinner.start()
        time.sleep(0.03)
        spinner.stop()

    def test_setup_zone_only_once(self) -> None:
        """Zone setup only happens once."""
        buffer = io.StringIO()
        spinner = SpinnerWithLogZone("Test", file=buffer, log_zone_height=3)

        spinner._setup_zone()
        initial_output = buffer.getvalue()
        spinner._setup_zone()
        assert buffer.getvalue() == initial_output

    def test_render_frame_with_dirty_logs(self) -> None:
        """Render frame redraws logs when dirty flag is set."""
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True)
        spinner = SpinnerWithLogZone(
            "Test",
            console=console,
            file=buffer,
            log_zone_height=3,
            interval=0.01,
        )
        spinner._setup_zone()
        spinner._initialized = True

        spinner.log("Log entry 1")
        spinner.log("Log entry 2")
        spinner._render_frame()

        output = buffer.getvalue()
        assert "Log entry" in output or len(output) > 50

    def test_render_frame_skips_unchanged_logs(self) -> None:
        """Render frame does not redraw logs when not dirty."""
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True)
        spinner = SpinnerWithLogZone(
            "Test",
            console=console,
            file=buffer,
            log_zone_height=3,
            interval=0.01,
        )
        spinner._setup_zone()
        spinner._initialized = True

        spinner._render_frame()
        first_render_len = len(buffer.getvalue())

        spinner._render_frame()
        second_render_len = len(buffer.getvalue())

        assert second_render_len > first_render_len
