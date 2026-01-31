#!/usr/bin/env python3
"""Config-driven tmux session example.

Demonstrates launching a session purely from kstlib.conf.yml configuration.
No hardcoded backend, command, or options in the script itself.

Usage:
    cd examples/ops/config_driven/tmux
    python run.py
    python run.py --status
    python run.py --stop

The session configuration is defined in kstlib.conf.yml (same directory).

Requirements:
    - tmux installed (apt install tmux / brew install tmux)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root to path for direct execution
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from kstlib.ops import SessionManager
from kstlib.ops.exceptions import (
    SessionExistsError,
    SessionNotFoundError,
    TmuxNotFoundError,
)
from kstlib.ops.manager import SessionConfigError

SESSION_NAME = "astro-dev"


def start_session() -> None:
    """Start the session from config."""
    try:
        session = SessionManager.from_config(SESSION_NAME)
        status = session.start()

        print(f"[OK] Session '{status.name}' started!")
        print(f"     Backend: {status.backend}")
        print(f"     State: {status.state}")
        print()
        print("Commands:")
        print(f"  Attach:  kstlib ops attach {SESSION_NAME}")
        print(f"  Logs:    kstlib ops logs {SESSION_NAME}")
        print("  Status:  python run.py --status")
        print("  Stop:    python run.py --stop")
        print()
        print("In tmux: Ctrl+B D to detach (bot keeps running)")

    except TmuxNotFoundError:
        print("[ERROR] tmux not found!")
        print("        Install: apt install tmux (Linux) or brew install tmux (macOS)")
        sys.exit(1)

    except SessionExistsError:
        print(f"[INFO] Session '{SESSION_NAME}' already exists.")
        print(f"       Attach: kstlib ops attach {SESSION_NAME}")
        print("       Stop:   python run.py --stop")

    except SessionConfigError as e:
        print(f"[ERROR] Config error: {e}")
        sys.exit(1)


def show_status() -> None:
    """Show session status from config."""
    try:
        session = SessionManager.from_config(SESSION_NAME)
        status = session.status()

        print(f"Session: {status.name}")
        print(f"Backend: {status.backend}")
        print(f"State:   {status.state}")
        if status.pid:
            print(f"PID:     {status.pid}")

    except SessionNotFoundError:
        print(f"[INFO] Session '{SESSION_NAME}' not found.")

    except SessionConfigError as e:
        print(f"[ERROR] Config error: {e}")
        sys.exit(1)


def stop_session() -> None:
    """Stop the session from config."""
    try:
        session = SessionManager.from_config(SESSION_NAME)
        session.stop()
        print(f"[OK] Session '{SESSION_NAME}' stopped.")

    except SessionNotFoundError:
        print(f"[INFO] Session '{SESSION_NAME}' not found (already stopped?).")

    except SessionConfigError as e:
        print(f"[ERROR] Config error: {e}")
        sys.exit(1)


def main() -> None:
    """Run config-driven tmux session example."""
    parser = argparse.ArgumentParser(
        description="Config-driven tmux session (reads kstlib.conf.yml)",
    )
    parser.add_argument("--status", action="store_true", help="Show session status")
    parser.add_argument("--stop", action="store_true", help="Stop the session")
    args = parser.parse_args()

    if args.status:
        show_status()
    elif args.stop:
        stop_session()
    else:
        start_session()


if __name__ == "__main__":
    main()
