"""Demonstrate spinner presets for quick configuration."""

from __future__ import annotations

import time

from kstlib.ui.spinner import Spinner


def demo_builtin_presets() -> None:
    """Use built-in presets for common use cases."""
    print("\n=== Built-in Presets ===\n")

    presets = [
        ("minimal", "Minimal style for subtle feedback"),
        ("fancy", "Fancy braille with bold cyan"),
        ("blocks", "Blue block animation"),
        ("bounce", "Yellow bouncing bar"),
        ("color_wave", "Rainbow wave effect"),
    ]

    for preset_name, description in presets:
        spinner = Spinner.from_preset(preset_name, f"{description}...")
        with spinner:
            time.sleep(2)


def demo_preset_with_overrides() -> None:
    """Override preset values for customization."""
    print("\n=== Preset with Overrides ===\n")

    # Start from 'fancy' preset but change the style
    spinner = Spinner.from_preset(
        "fancy",
        "Custom fancy with MOON style...",
        style="MOON",
        interval=0.15,
    )
    with spinner:
        time.sleep(2)

    # Start from 'bounce' but make it cyan
    spinner = Spinner.from_preset(
        "bounce",
        "Cyan bounce bar...",
        spinner_style="cyan",
    )
    with spinner:
        time.sleep(2)


def main() -> None:
    """Run preset demonstrations."""
    print("=" * 50)
    print("Spinner Presets")
    print("=" * 50)

    demo_builtin_presets()
    demo_preset_with_overrides()

    print("\n" + "=" * 50)
    print("Done!")


if __name__ == "__main__":
    main()
