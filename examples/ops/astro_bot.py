#!/usr/bin/env python3
"""Astro Bot - Simple persistent bot demo for kstlib.ops.

This bot prints a greeting every minute with a cyclic counter (0-999).
It demonstrates persistent sessions: you can detach and reattach later
from any terminal (local or SSH) to see the bot still running.

Usage:
    # Direct execution (for testing)
    python astro_bot.py

    # Via tmux (recommended for dev)
    python run_tmux.py

    # Via container (recommended for prod)
    python run_container.py
"""

from __future__ import annotations

import signal
import time
from datetime import datetime

from kstlib.ui.spinner import Spinner

# Graceful shutdown handling
_shutdown_requested = False


def _handle_signal(signum: int, frame: object) -> None:
    """Handle shutdown signals gracefully."""
    global _shutdown_requested  # noqa: PLW0603
    _shutdown_requested = True


def _format_greeting(counter: int) -> str:
    """Format the greeting message with current date/time."""
    now = datetime.now()
    date_str = now.strftime("%A %d %B %Y")
    time_str = now.strftime("%H:%M")
    return f"[{counter:03d}] Hello! I'm Astro. Today is {date_str}, it's {time_str}."


def main() -> None:
    """Run Astro bot main loop with kstlib spinner."""
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    print("[Astro] Starting up...")
    print("[Astro] Press Ctrl+C to stop (or send SIGTERM)")
    print("[Astro] In tmux: Ctrl+B D to detach (bot keeps running)")
    print("[Astro] In container: Ctrl+P Ctrl+Q to detach")
    print("-" * 60)

    counter = 0
    max_counter = 999

    # Use kstlib spinner for nice visual feedback
    spinner = Spinner(_format_greeting(counter))
    spinner.start()

    try:
        while not _shutdown_requested:
            # Update spinner with current greeting
            spinner.update(_format_greeting(counter))

            # Increment counter (cyclic 0-999)
            counter = (counter + 1) % (max_counter + 1)

            # Wait 60 seconds (check for shutdown every second)
            for _ in range(60):
                if _shutdown_requested:
                    break
                time.sleep(1)

    finally:
        spinner.stop(final_message="[Astro] Goodbye!")


if __name__ == "__main__":
    main()
