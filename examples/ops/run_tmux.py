#!/usr/bin/env python3
"""Run Astro Bot in a tmux session.

This example demonstrates using SessionManager with the tmux backend
for local development. The bot runs in a persistent tmux session that
survives terminal disconnection.

Usage:
    # Start the bot
    python run_tmux.py

    # Or via CLI
    kstlib ops start astro --backend tmux --command "python astro_bot.py"

After starting:
    - The bot runs in background
    - Attach with: kstlib ops attach astro (or: tmux attach -t astro)
    - Detach with: Ctrl+B D
    - View logs: kstlib ops logs astro
    - Stop: kstlib ops stop astro

Requirements:
    - tmux installed (apt install tmux / brew install tmux)
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add examples to path for direct execution
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from kstlib.ops import SessionManager
from kstlib.ops.exceptions import SessionExistsError, TmuxNotFoundError


def main() -> None:
    """Start Astro bot in tmux session."""
    session_name = "astro"
    bot_script = Path(__file__).parent / "astro_bot.py"

    print(f"[*] Starting Astro bot in tmux session '{session_name}'...")

    try:
        # Create session manager with tmux backend
        session = SessionManager(session_name, backend="tmux")

        # Start the bot
        # working_dir ensures relative imports work
        status = session.start(
            command=f"python {bot_script}",
            working_dir=str(bot_script.parent),
        )

        print("[OK] Astro bot started!")
        print(f"     Session: {status.name}")
        print(f"     Backend: {status.backend}")
        print(f"     State: {status.state}")
        print()
        print("Commands:")
        print(f"  Attach:  kstlib ops attach {session_name}")
        print(f"  Logs:    kstlib ops logs {session_name}")
        print(f"  Status:  kstlib ops status {session_name}")
        print(f"  Stop:    kstlib ops stop {session_name}")
        print()
        print("In tmux: Ctrl+B D to detach (bot keeps running)")

    except TmuxNotFoundError:
        print("[ERROR] tmux not found!")
        print("        Install: apt install tmux (Linux) or brew install tmux (macOS)")
        sys.exit(1)

    except SessionExistsError:
        print(f"[INFO] Session '{session_name}' already exists.")
        print(f"       Attach with: kstlib ops attach {session_name}")
        print(f"       Or stop with: kstlib ops stop {session_name}")


if __name__ == "__main__":
    main()
