"""Animated spinner utilities for CLI feedback during long operations."""

from __future__ import annotations

import functools
import io
import sys
import threading
import time
from collections import deque
from enum import Enum
from typing import IO, TYPE_CHECKING, Any, ParamSpec, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

from rich.console import Console
from rich.text import Text
from typing_extensions import Self

from kstlib.config import ConfigNotLoadedError, get_config
from kstlib.ui.exceptions import SpinnerError

if TYPE_CHECKING:
    import types

    from rich.style import Style

P = ParamSpec("P")
R = TypeVar("R")


class SpinnerStyle(Enum):
    """Predefined spinner animation families.

    Each style defines a sequence of frames that cycle during animation.
    """

    BRAILLE = ("⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷")
    DOTS = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
    LINE = ("|", "/", "-", "\\")
    ARROW = ("←", "↖", "↑", "↗", "→", "↘", "↓", "↙")
    BLOCKS = ("▁", "▂", "▃", "▄", "▅", "▆", "▇", "█", "▇", "▆", "▅", "▄", "▃", "▂")
    CIRCLE = ("◐", "◓", "◑", "◒")
    SQUARE = ("◰", "◳", "◲", "◱")
    MOON = ("🌑", "🌒", "🌓", "🌔", "🌕", "🌖", "🌗", "🌘")
    CLOCK = ("🕐", "🕑", "🕒", "🕓", "🕔", "🕕", "🕖", "🕗", "🕘", "🕙", "🕚", "🕛")


class SpinnerPosition(Enum):
    """Position of the spinner relative to the message text."""

    BEFORE = "before"
    AFTER = "after"


class SpinnerAnimationType(Enum):
    """Type of animation to display."""

    SPIN = "spin"
    BOUNCE = "bounce"
    COLOR_WAVE = "color_wave"


# Default configuration
DEFAULT_SPINNER_CONFIG: dict[str, Any] = {
    "defaults": {
        "style": "BRAILLE",
        "position": "before",
        "animation_type": "spin",
        "interval": 0.08,
        "spinner_style": "cyan",
        "text_style": None,
        "done_character": "✓",
        "done_style": "green",
        "fail_character": "✗",
        "fail_style": "red",
    },
    "presets": {
        "minimal": {
            "style": "LINE",
            "spinner_style": "dim white",
            "interval": 0.1,
        },
        "fancy": {
            "style": "BRAILLE",
            "spinner_style": "bold cyan",
            "interval": 0.06,
        },
        "blocks": {
            "style": "BLOCKS",
            "spinner_style": "blue",
            "interval": 0.05,
        },
        "bounce": {
            "animation_type": "bounce",
            "interval": 0.08,
            "spinner_style": "yellow",
        },
        "color_wave": {
            "animation_type": "color_wave",
            "interval": 0.1,
        },
    },
}

# Color wave palette
COLOR_WAVE_COLORS = [
    "bright_blue",
    "cyan",
    "bright_cyan",
    "white",
    "bright_cyan",
    "cyan",
]

# Bounce bar width
BOUNCE_WIDTH = 20
BOUNCE_CHAR = "="
BOUNCE_BRACKET_LEFT = "["
BOUNCE_BRACKET_RIGHT = "]"


def _load_spinner_config() -> dict[str, Any]:
    """Load spinner configuration from kstlib.conf.yml with fallback to defaults."""
    try:
        config = get_config().to_dict()
        ui_config = config.get("ui", {})
        spinners_config = ui_config.get("spinners", {})
        if spinners_config:
            # Merge with defaults to ensure all keys exist
            merged: dict[str, Any] = {
                "defaults": {**DEFAULT_SPINNER_CONFIG["defaults"]},
                "presets": {**DEFAULT_SPINNER_CONFIG["presets"]},
            }
            if "defaults" in spinners_config:
                merged["defaults"].update(spinners_config["defaults"])
            if "presets" in spinners_config:
                for preset_name, preset_vals in spinners_config["presets"].items():
                    if preset_name in merged["presets"]:
                        merged["presets"][preset_name].update(preset_vals)
                    else:
                        merged["presets"][preset_name] = dict(preset_vals)
            return merged
    except ConfigNotLoadedError:
        pass
    return DEFAULT_SPINNER_CONFIG


class Spinner:
    """Animated spinner for CLI feedback during long operations.

    Supports multiple animation styles including character spinners, bouncing bars,
    and color wave effects. Can be used as a context manager or controlled manually.

    Args:
        message: Text to display alongside the spinner.
        style: Spinner animation style (SpinnerStyle enum or string name).
        position: Where to place spinner relative to text (before/after).
        animation_type: Type of animation (spin/bounce/color_wave).
        interval: Seconds between animation frames.
        spinner_style: Rich style for the spinner character.
        text_style: Rich style for the message text.
        console: Optional Rich console instance.
        file: Output stream (defaults to sys.stderr).

    Examples:
        Create a spinner with default settings:

        >>> spinner = Spinner("Loading...")
        >>> spinner.message
        'Loading...'

        Create with custom style:

        >>> spinner = Spinner("Working", style=SpinnerStyle.DOTS)
        >>> spinner = Spinner("Building", style="BLOCKS", interval=0.1)

        Using as a context manager (terminal I/O):

        >>> with Spinner("Processing...") as s:  # doctest: +SKIP
        ...     do_long_operation()
        ...     s.update("Almost done...")

        Manual control:

        >>> spinner = Spinner("Working...")  # doctest: +SKIP
        >>> spinner.start()  # doctest: +SKIP
        >>> spinner.stop(success=True)  # doctest: +SKIP
    """

    def __init__(
        self,
        message: str = "",
        *,
        style: SpinnerStyle | str = SpinnerStyle.BRAILLE,
        position: SpinnerPosition | str = SpinnerPosition.BEFORE,
        animation_type: SpinnerAnimationType | str = SpinnerAnimationType.SPIN,
        interval: float = 0.08,
        spinner_style: str | Style | None = "cyan",
        text_style: str | Style | None = None,
        done_character: str = "✓",
        done_style: str | Style | None = "green",
        fail_character: str = "✗",
        fail_style: str | Style | None = "red",
        console: Console | None = None,
        file: IO[str] | None = None,
    ) -> None:
        """Initialize spinner with configuration."""
        self._message = message
        self._style = self._resolve_style(style)
        self._position = self._resolve_position(position)
        self._animation_type = self._resolve_animation_type(animation_type)
        self._interval = interval
        self._spinner_style = spinner_style
        self._text_style = text_style
        self._done_character = done_character
        self._done_style = done_style
        self._fail_character = fail_character
        self._fail_style = fail_style
        self._file = file or sys.stderr
        self._console = console or Console(file=self._file, force_terminal=True)

        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._frame_index = 0
        self._bounce_position = 0
        self._bounce_direction = 1
        self._color_offset = 0

    @classmethod
    def from_preset(
        cls,
        preset: str,
        message: str = "",
        *,
        console: Console | None = None,
        **overrides: Any,
    ) -> Spinner:
        """Create a spinner from a named preset.

        Args:
            preset: Name of the preset (e.g., "minimal", "fancy", "bounce").
            message: Text to display alongside the spinner.
            console: Optional Rich console instance.
            **overrides: Additional parameters to override preset values.

        Returns:
            Configured Spinner instance.

        Raises:
            SpinnerError: If preset name is not found.

        Examples:
            Create from a built-in preset:

            >>> spinner = Spinner.from_preset("minimal", "Loading...")
            >>> spinner = Spinner.from_preset("fancy", "Processing data")

            Override preset values:

            >>> spinner = Spinner.from_preset("bounce", "Building", interval=0.05)

            Invalid preset raises error:

            >>> Spinner.from_preset("nonexistent")  # doctest: +ELLIPSIS
            Traceback (most recent call last):
            ...
            kstlib.ui.exceptions.SpinnerError: Unknown preset 'nonexistent'. ...
        """
        config = _load_spinner_config()
        presets = config.get("presets", {})
        if preset not in presets:
            available = ", ".join(presets.keys())
            raise SpinnerError(f"Unknown preset '{preset}'. Available: {available}")

        defaults = config.get("defaults", {}).copy()
        preset_config = presets[preset].copy()
        merged = {**defaults, **preset_config, **overrides}

        return cls(
            message,
            style=merged.get("style", SpinnerStyle.BRAILLE),
            position=merged.get("position", SpinnerPosition.BEFORE),
            animation_type=merged.get("animation_type", SpinnerAnimationType.SPIN),
            interval=merged.get("interval", 0.08),
            spinner_style=merged.get("spinner_style"),
            text_style=merged.get("text_style"),
            done_character=merged.get("done_character", "✓"),
            done_style=merged.get("done_style", "green"),
            fail_character=merged.get("fail_character", "✗"),
            fail_style=merged.get("fail_style", "red"),
            console=console,
        )

    def start(self) -> None:
        """Start the spinner animation in a background thread."""
        if self._running:
            return

        self._running = True
        self._hide_cursor()
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def stop(self, *, success: bool = True, final_message: str | None = None) -> None:
        """Stop the spinner animation.

        Args:
            success: If True, show done character; if False, show fail character.
            final_message: Optional message to display after stopping.
        """
        if not self._running:
            return

        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

        self._clear_line()
        self._show_cursor()
        self._render_final(success=success, final_message=final_message)

    def update(self, message: str) -> None:
        """Update the spinner message while running.

        Args:
            message: New message to display.
        """
        with self._lock:
            self._message = message

    def log(self, message: str, style: str | None = None) -> None:
        """Print a message above the spinner without disrupting animation.

        Use this to display logs, progress info, or any output while the
        spinner continues running on the bottom line.

        Args:
            message: Text to print above the spinner.
            style: Optional Rich style for the message.
        """
        with self._lock:
            # Clear spinner line
            self._file.write("\r\033[K")
            self._file.flush()
            # Print the log message
            if style:
                self._console.print(f"[{style}]{message}[/{style}]")
            else:
                self._console.print(message)
            # Spinner will redraw on next frame

    @property
    def message(self) -> str:
        """Current spinner message."""
        with self._lock:
            return self._message

    def __enter__(self) -> Self:
        """Start spinner when entering context."""
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Stop spinner when exiting context."""
        success = exc_type is None
        self.stop(success=success)

    # ------------------------------------------------------------------
    # Animation loop
    # ------------------------------------------------------------------

    def _animate(self) -> None:
        """Main animation loop running in background thread."""
        while self._running:
            self._render_frame()
            time.sleep(self._interval)

    def _render_frame(self) -> None:
        """Render a single animation frame."""
        self._move_to_line_start()

        if self._animation_type == SpinnerAnimationType.SPIN:
            self._render_spin_frame()
        elif self._animation_type == SpinnerAnimationType.BOUNCE:
            self._render_bounce_frame()
        elif self._animation_type == SpinnerAnimationType.COLOR_WAVE:
            self._render_color_wave_frame()

    def _render_spin_frame(self) -> None:
        """Render classic spinner animation frame."""
        frames = self._style.value
        frame_char = frames[self._frame_index % len(frames)]
        self._frame_index += 1

        spinner_text = Text(frame_char, style=self._spinner_style or "")

        with self._lock:
            message = self._message

        message_text = self._styled_message(message)
        if self._position == SpinnerPosition.BEFORE:
            output = Text.assemble(spinner_text, " ", message_text)
        else:
            output = Text.assemble(message_text, " ", spinner_text)

        self._console.print(output, end="")

    def _render_bounce_frame(self) -> None:
        """Render bouncing bar animation frame."""
        # Build the bar: [=    ] with = bouncing
        bar_inner = [" "] * BOUNCE_WIDTH
        bar_inner[self._bounce_position] = BOUNCE_CHAR

        # Update bounce position
        self._bounce_position += self._bounce_direction
        if self._bounce_position >= BOUNCE_WIDTH - 1:
            self._bounce_direction = -1
        elif self._bounce_position <= 0:
            self._bounce_direction = 1

        bar = BOUNCE_BRACKET_LEFT + "".join(bar_inner) + BOUNCE_BRACKET_RIGHT
        bar_text = Text(bar, style=self._spinner_style or "")

        with self._lock:
            message = self._message

        message_text = self._styled_message(message)
        if self._position == SpinnerPosition.BEFORE:
            output = Text.assemble(bar_text, " ", message_text)
        else:
            output = Text.assemble(message_text, " ", bar_text)

        self._console.print(output, end="")

    def _render_color_wave_frame(self) -> None:
        """Render color wave animation through text."""
        with self._lock:
            message = self._message

        if not message:
            return

        output = Text()
        for i, char in enumerate(message):
            color_index = (i + self._color_offset) % len(COLOR_WAVE_COLORS)
            output.append(char, style=COLOR_WAVE_COLORS[color_index])

        self._color_offset += 1
        self._console.print(output, end="")

    def _render_final(self, *, success: bool, final_message: str | None) -> None:
        """Render final state after stopping."""
        if self._animation_type == SpinnerAnimationType.COLOR_WAVE:
            # For color wave, just print the message normally
            with self._lock:
                message = final_message or self._message
            if message:
                style = self._done_style if success else self._fail_style
                self._console.print(Text(message, style=style or ""))
            return

        char = self._done_character if success else self._fail_character
        char_style = self._done_style if success else self._fail_style
        final_char = Text(char, style=char_style or "")

        with self._lock:
            message = final_message or self._message

        message_text = self._styled_message(message)
        if self._position == SpinnerPosition.BEFORE:
            output = Text.assemble(final_char, " ", message_text)
        else:
            output = Text.assemble(message_text, " ", final_char)

        self._console.print(output)

    def _styled_message(self, message: str) -> Text:
        """Create a styled Text object for the message."""
        if self._text_style:
            return Text(message, style=self._text_style)
        return Text(message)

    def _move_to_line_start(self) -> None:
        """Move cursor to beginning of line without clearing."""
        self._file.write("\r")
        self._file.flush()

    def _clear_line(self) -> None:
        """Clear the current console line."""
        # Write ANSI sequences directly to file descriptor (Rich doesn't pass them through)
        self._file.write("\r\033[K")
        self._file.flush()

    def _hide_cursor(self) -> None:
        """Hide terminal cursor to reduce flickering."""
        self._file.write("\033[?25l")
        self._file.flush()

    def _show_cursor(self) -> None:
        """Show terminal cursor."""
        self._file.write("\033[?25h")
        self._file.flush()

    # ------------------------------------------------------------------
    # Resolution helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_style(style: SpinnerStyle | str) -> SpinnerStyle:
        """Convert string to SpinnerStyle enum if needed."""
        if isinstance(style, SpinnerStyle):
            return style
        try:
            return SpinnerStyle[style.upper()]
        except KeyError as exc:
            available = ", ".join(s.name for s in SpinnerStyle)
            raise SpinnerError(f"Unknown spinner style '{style}'. Available: {available}") from exc

    @staticmethod
    def _resolve_position(position: SpinnerPosition | str) -> SpinnerPosition:
        """Convert string to SpinnerPosition enum if needed."""
        if isinstance(position, SpinnerPosition):
            return position
        try:
            return SpinnerPosition(position.lower())
        except ValueError as exc:
            raise SpinnerError(f"Invalid position '{position}'. Use 'before' or 'after'.") from exc

    @staticmethod
    def _resolve_animation_type(animation_type: SpinnerAnimationType | str) -> SpinnerAnimationType:
        """Convert string to SpinnerAnimationType enum if needed."""
        if isinstance(animation_type, SpinnerAnimationType):
            return animation_type
        try:
            return SpinnerAnimationType(animation_type.lower())
        except ValueError as exc:
            available = ", ".join(t.value for t in SpinnerAnimationType)
            raise SpinnerError(f"Invalid animation type '{animation_type}'. Available: {available}") from exc


# ==============================================================================
# Decorator for capturing prints
# ==============================================================================


class _PrintCapture(io.StringIO):
    """Captures print output and redirects to spinner.log()."""

    def __init__(
        self,
        spinner: Spinner | SpinnerWithLogZone,
        style: str | None = None,
    ) -> None:
        super().__init__()
        self._spinner: Spinner | SpinnerWithLogZone = spinner
        self._style = style

    def write(self, text: str) -> int:
        """Intercept write calls and send to spinner.log()."""
        # Filter out empty strings and lone newlines
        stripped = text.rstrip("\n")
        if stripped:
            self._spinner.log(stripped, style=self._style)
        return len(text)


def with_spinner(
    message: str = "Processing...",
    *,
    style: SpinnerStyle | str = SpinnerStyle.BRAILLE,
    log_style: str | None = "dim",
    capture_prints: bool = True,
    log_zone_height: int | None = None,
    **spinner_kwargs: Any,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator that wraps a function with a spinner, capturing its prints.

    Args:
        message: Spinner message to display.
        style: Spinner animation style.
        log_style: Style for captured print output (None for no style).
        capture_prints: If True, redirect stdout to spinner.log().
        log_zone_height: If set, use SpinnerWithLogZone with fixed height.
            The spinner stays at top, logs scroll in bounded zone below.
        **spinner_kwargs: Additional arguments passed to Spinner.

    Returns:
        Decorated function.

    Examples:
        Basic decorator usage (terminal I/O):

        >>> @with_spinner("Loading data...")  # doctest: +SKIP
        ... def load_data():
        ...     return {"data": [1, 2, 3]}
        >>> result = load_data()  # doctest: +SKIP

        With log capture (prints appear above spinner):

        >>> @with_spinner("Processing...", log_style="cyan")  # doctest: +SKIP
        ... def process():
        ...     print("Step 1 complete")  # Appears above spinner
        ...     print("Step 2 complete")
        ...     return True

        Fixed log zone with bounded scrolling:

        >>> @with_spinner("Building...", log_zone_height=5)  # doctest: +SKIP
        ... def build():
        ...     for i in range(10):
        ...         print(f"Step {i}")  # Scrolls in 5-line zone
        ...     return True
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            # Choose spinner type based on log_zone_height
            if log_zone_height is not None:
                spinner: Spinner | SpinnerWithLogZone = SpinnerWithLogZone(
                    message,
                    style=style,
                    log_zone_height=log_zone_height,
                    **spinner_kwargs,
                )
            else:
                spinner = Spinner(message, style=style, **spinner_kwargs)

            with spinner:
                if capture_prints:
                    capture = _PrintCapture(spinner, style=log_style)
                    old_stdout = sys.stdout
                    sys.stdout = capture
                    try:
                        return func(*args, **kwargs)
                    finally:
                        sys.stdout = old_stdout
                else:
                    return func(*args, **kwargs)

        return wrapper

    return decorator


# ==============================================================================
# Spinner with fixed log zone
# ==============================================================================


class SpinnerWithLogZone:
    """Spinner with a fixed position and a scrollable log zone.

    The spinner stays fixed at the top while logs scroll in a zone below.
    When the zone is full, old logs are pushed out automatically.

    Args:
        message: Spinner message.
        log_zone_height: Number of lines for the log zone (default 10).
        style: Spinner animation style.
        spinner_style: Rich style for spinner character.
        console: Optional Rich console.
        **kwargs: Additional Spinner arguments.

    Examples:
        Create with custom log zone height:

        >>> sz = SpinnerWithLogZone("Building...", log_zone_height=5)
        >>> sz._log_zone_height
        5

        Usage as context manager (terminal I/O):

        >>> with SpinnerWithLogZone("Processing", log_zone_height=3) as sz:  # doctest: +SKIP
        ...     sz.log("Step 1 done")
        ...     sz.log("Step 2 done")
        ...     sz.update("Almost finished...")
    """

    def __init__(
        self,
        message: str = "",
        *,
        log_zone_height: int = 10,
        style: SpinnerStyle | str = SpinnerStyle.BRAILLE,
        spinner_style: str | None = "cyan",
        console: Console | None = None,
        file: IO[str] | None = None,
        interval: float = 0.08,
    ) -> None:
        self._message = message
        self._log_zone_height = log_zone_height
        self._style = Spinner._resolve_style(style)
        self._spinner_style = spinner_style
        self._interval = interval
        self._file = file or sys.stderr
        self._console = console or Console(file=self._file, force_terminal=True)

        self._logs: deque[str] = deque(maxlen=log_zone_height)
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._frame_index = 0
        self._initialized = False
        self._logs_dirty = False  # Track if logs need redraw
        self._last_message = ""  # Track message changes

    def start(self) -> None:
        """Start the spinner animation."""
        if self._running:
            return

        self._running = True
        self._setup_zone()
        self._hide_cursor()
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def stop(self, *, success: bool = True, final_message: str | None = None) -> None:
        """Stop the spinner and clean up the display."""
        if not self._running:
            return

        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

        self._show_cursor()
        self._render_final(success, final_message)

    def update(self, message: str) -> None:
        """Update the spinner message."""
        with self._lock:
            self._message = message

    def log(self, message: str, style: str | None = None) -> None:
        """Add a log entry to the scrolling zone."""
        with self._lock:
            if style:
                self._logs.append(f"[{style}]{message}[/{style}]")
            else:
                self._logs.append(message)
            self._logs_dirty = True

    def __enter__(self) -> Self:
        """Start spinner when entering context."""
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Stop spinner when exiting context."""
        self.stop(success=exc_type is None)

    def _setup_zone(self) -> None:
        """Reserve space for the log zone by printing newlines."""
        if self._initialized:
            return
        # Print empty lines to reserve space
        # +1 for spinner line at top
        self._file.write("\n" * (self._log_zone_height + 1))
        self._file.flush()
        self._initialized = True

    def _animate(self) -> None:
        """Animation loop."""
        while self._running:
            self._render_frame()
            time.sleep(self._interval)

    def _render_frame(self) -> None:
        """Render spinner and log zone (optimized: only redraw what changed)."""
        frames = self._style.value
        frame_char = frames[self._frame_index % len(frames)]
        self._frame_index += 1

        with self._lock:
            message = self._message
            logs_dirty = self._logs_dirty
            logs = list(self._logs) if logs_dirty else []
            message_changed = message != self._last_message
            self._logs_dirty = False
            self._last_message = message

        # Move cursor to spinner line (top of zone)
        total_lines = self._log_zone_height + 1
        self._file.write(f"\033[{total_lines}A")  # Move up

        # Always render spinner line (just overwrite, no clear needed for spinner char)
        self._file.write("\r")
        spinner_text = Text(frame_char, style=self._spinner_style or "")
        msg_text = Text(f" {message}")
        self._console.print(Text.assemble(spinner_text, msg_text), end="")

        # Pad with spaces if message got shorter
        if message_changed:
            self._file.write("\033[K")  # Clear rest of line

        # Only redraw logs if they changed
        if logs_dirty:
            self._file.write("\n")  # Move to first log line
            for i in range(self._log_zone_height):
                self._file.write("\033[K")  # Clear line
                if i < len(logs):
                    self._console.print(f"  {logs[i]}", end="")
                if i < self._log_zone_height - 1:
                    self._file.write("\n")
            self._file.write("\n")  # Final newline to position cursor at bottom
        else:
            # Just move cursor back to bottom without redrawing logs
            self._file.write(f"\033[{self._log_zone_height}B")  # Move down
            self._file.write("\n")

        self._file.flush()

    def _render_final(self, success: bool, final_message: str | None) -> None:
        """Render final state."""
        char = "✓" if success else "✗"
        char_style = "green" if success else "red"
        message = final_message or self._message

        with self._lock:
            logs = list(self._logs)

        # Move to top of zone
        total_lines = self._log_zone_height + 1
        self._file.write(f"\033[{total_lines}A")

        # Final spinner line
        self._file.write("\r\033[K")
        self._console.print(f"[{char_style}]{char}[/{char_style}] {message}")

        # Render remaining logs
        for i in range(self._log_zone_height):
            self._file.write("\033[K")
            if i < len(logs):
                self._console.print(f"  {logs[i]}", end="")
            self._file.write("\n")

        self._file.flush()

    def _hide_cursor(self) -> None:
        """Hide cursor."""
        self._file.write("\033[?25l")
        self._file.flush()

    def _show_cursor(self) -> None:
        """Show cursor."""
        self._file.write("\033[?25h")
        self._file.flush()
