"""Demonstrate all available spinner styles."""

from __future__ import annotations

import time

from kstlib.ui.spinner import Spinner, SpinnerStyle


def demo_all_styles() -> None:
    """Show each SpinnerStyle in action."""
    print("\n=== All Spinner Styles ===\n")

    styles = [
        (SpinnerStyle.BRAILLE, "Braille dots (default)"),
        (SpinnerStyle.DOTS, "Unicode dots"),
        (SpinnerStyle.LINE, "Classic line"),
        (SpinnerStyle.ARROW, "Rotating arrow"),
        (SpinnerStyle.BLOCKS, "Growing blocks"),
        (SpinnerStyle.CIRCLE, "Quarter circle"),
        (SpinnerStyle.SQUARE, "Quarter square"),
        (SpinnerStyle.MOON, "Moon phases"),
        (SpinnerStyle.CLOCK, "Clock faces"),
    ]

    for style, description in styles:
        with Spinner(f"{description}...", style=style):
            time.sleep(2)


def demo_style_by_name() -> None:
    """Use style names as strings instead of enum."""
    print("\n=== Using String Style Names ===\n")

    # Styles can be specified as strings (case-insensitive)
    for style_name in ["braille", "DOTS", "Line", "ARROW"]:
        with Spinner(f"Style: {style_name}", style=style_name):
            time.sleep(1.5)


def main() -> None:
    """Run spinner style demonstrations."""
    print("=" * 50)
    print("Spinner Styles Gallery")
    print("=" * 50)

    demo_all_styles()
    demo_style_by_name()

    print("\n" + "=" * 50)
    print("Done!")


if __name__ == "__main__":
    main()
