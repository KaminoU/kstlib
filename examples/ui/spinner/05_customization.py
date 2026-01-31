"""Demonstrate advanced spinner customization options."""

from __future__ import annotations

import time

from kstlib.ui.spinner import Spinner, SpinnerPosition, SpinnerStyle


def demo_position() -> None:
    """Control spinner position relative to text."""
    print("\n=== Spinner Position ===\n")

    with Spinner("Spinner BEFORE text (default)", position=SpinnerPosition.BEFORE):
        time.sleep(1.5)

    with Spinner("Spinner AFTER text", position=SpinnerPosition.AFTER):
        time.sleep(1.5)


def demo_styling() -> None:
    """Customize spinner and text styles."""
    print("\n=== Custom Styling ===\n")

    with Spinner(
        "Bold magenta spinner...",
        spinner_style="bold magenta",
        text_style="italic white",
    ):
        time.sleep(1.5)

    with Spinner(
        "Red spinner, yellow text...",
        spinner_style="red",
        text_style="bold yellow",
    ):
        time.sleep(1.5)


def demo_custom_done_fail() -> None:
    """Customize success/failure characters and styles."""
    print("\n=== Custom Done/Fail Characters ===\n")

    # Custom success character
    spinner = Spinner(
        "Custom success marker...",
        done_character="[OK]",
        done_style="bold green",
    )
    with spinner:
        time.sleep(1.5)

    # Custom failure character
    spinner = Spinner(
        "Custom failure marker...",
        fail_character="[FAIL]",
        fail_style="bold red",
    )
    spinner.start()
    time.sleep(1.5)
    spinner.stop(success=False)


def demo_interval() -> None:
    """Control animation speed with interval."""
    print("\n=== Animation Speed ===\n")

    with Spinner("Slow animation (0.2s)...", interval=0.2):
        time.sleep(2)

    with Spinner("Fast animation (0.03s)...", interval=0.03):
        time.sleep(2)


def demo_combined() -> None:
    """Combine multiple customization options."""
    print("\n=== Combined Customization ===\n")

    with Spinner(
        "Fully customized spinner",
        style=SpinnerStyle.CLOCK,
        position=SpinnerPosition.AFTER,
        spinner_style="bold blue",
        text_style="dim white",
        interval=0.15,
        done_character="[DONE]",
        done_style="bold cyan",
    ):
        time.sleep(3)


def main() -> None:
    """Run customization demonstrations."""
    print("=" * 50)
    print("Spinner Customization Options")
    print("=" * 50)

    demo_position()
    demo_styling()
    demo_custom_done_fail()
    demo_interval()
    demo_combined()

    print("\n" + "=" * 50)
    print("Done!")


if __name__ == "__main__":
    main()
