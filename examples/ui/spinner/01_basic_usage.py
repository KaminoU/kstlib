"""Demonstrate basic spinner usage with context manager and manual control."""

from __future__ import annotations

import time

from kstlib.ui.spinner import Spinner


def demo_context_manager() -> None:
    """Use spinner as a context manager (recommended approach)."""
    print("\n=== Context Manager (auto start/stop) ===\n")

    with Spinner("Processing data..."):
        time.sleep(2)

    with Spinner("Connecting to server..."):
        time.sleep(1.5)


def demo_manual_control() -> None:
    """Use spinner with manual start/stop control."""
    print("\n=== Manual Control ===\n")

    spinner = Spinner("Initializing...")
    spinner.start()
    try:
        time.sleep(1)
        spinner.update("Loading modules...")
        time.sleep(1)
        spinner.update("Almost done...")
        time.sleep(1)
    finally:
        spinner.stop(final_message="Initialization complete")


def demo_success_failure() -> None:
    """Show success and failure states."""
    print("\n=== Success/Failure States ===\n")

    with Spinner("Task that succeeds..."):
        time.sleep(1)
    # Auto shows checkmark on success

    spinner = Spinner("Task that fails...")
    spinner.start()
    time.sleep(1)
    spinner.stop(success=False, final_message="Connection failed")


def main() -> None:
    """Run basic spinner demonstrations."""
    print("=" * 50)
    print("Spinner Basic Usage Examples")
    print("=" * 50)

    demo_context_manager()
    demo_manual_control()
    demo_success_failure()

    print("\n" + "=" * 50)
    print("Done!")


if __name__ == "__main__":
    main()
