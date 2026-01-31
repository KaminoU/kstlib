"""Demonstrate different animation types: spin, bounce, and color_wave."""

from __future__ import annotations

import time

from kstlib.ui.spinner import Spinner, SpinnerAnimationType


def demo_spin_animation() -> None:
    """Classic spinning character animation."""
    print("\n=== Spin Animation (default) ===\n")

    with Spinner("Classic spin animation...", animation_type=SpinnerAnimationType.SPIN):
        time.sleep(2)


def demo_bounce_animation() -> None:
    """Bouncing bar animation."""
    print("\n=== Bounce Animation ===\n")

    with Spinner(
        "Bouncing progress bar...",
        animation_type=SpinnerAnimationType.BOUNCE,
        spinner_style="yellow",
    ):
        time.sleep(3)


def demo_color_wave_animation() -> None:
    """Color wave flowing through text."""
    print("\n=== Color Wave Animation ===\n")

    with Spinner(
        "Rainbow wave through text...",
        animation_type=SpinnerAnimationType.COLOR_WAVE,
        interval=0.1,
    ):
        time.sleep(3)


def demo_animation_by_name() -> None:
    """Use animation type names as strings."""
    print("\n=== Using String Animation Names ===\n")

    for anim in ["spin", "bounce", "color_wave"]:
        with Spinner(f"Animation: {anim}", animation_type=anim):
            time.sleep(2)


def main() -> None:
    """Run animation type demonstrations."""
    print("=" * 50)
    print("Spinner Animation Types")
    print("=" * 50)

    demo_spin_animation()
    demo_bounce_animation()
    demo_color_wave_animation()
    demo_animation_by_name()

    print("\n" + "=" * 50)
    print("Done!")


if __name__ == "__main__":
    main()
