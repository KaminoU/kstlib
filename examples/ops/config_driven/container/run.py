#!/usr/bin/env python3
"""Config-driven container session example.

Demonstrates launching a session purely from kstlib.conf.yml configuration.
No hardcoded backend, image, or options in the script itself.

Usage:
    cd examples/ops/config_driven/container
    python run.py
    python run.py --status
    python run.py --stop

The session configuration is defined in kstlib.conf.yml (same directory).

Pre-requisite:
    cd examples/ops
    podman build -t astro-bot .
    # or: docker build -t astro-bot .

Requirements:
    - podman or docker installed
    - Image built (see above)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root to path for direct execution
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from kstlib.ops import SessionManager
from kstlib.ops.exceptions import (
    ContainerRuntimeNotFoundError,
    SessionExistsError,
    SessionNotFoundError,
)
from kstlib.ops.manager import SessionConfigError

SESSION_NAME = "astro-prod"


def start_session() -> None:
    """Start the session from config."""
    try:
        session = SessionManager.from_config(SESSION_NAME)
        status = session.start()

        print(f"[OK] Container '{status.name}' started!")
        print(f"     Backend: {status.backend}")
        print(f"     State: {status.state}")
        if status.image:
            print(f"     Image: {status.image}")
        print()
        print("Commands:")
        print(f"  Attach:  kstlib ops attach {SESSION_NAME}")
        print(f"  Logs:    kstlib ops logs {SESSION_NAME} --lines 50")
        print("  Status:  python run.py --status")
        print("  Stop:    python run.py --stop")
        print()
        print("In container: Ctrl+P Ctrl+Q to detach (bot keeps running)")

    except ContainerRuntimeNotFoundError:
        print("[ERROR] No container runtime found!")
        print("        Install podman: https://podman.io/getting-started/installation")
        print("        Or docker: https://docs.docker.com/get-docker/")
        sys.exit(1)

    except SessionExistsError:
        print(f"[INFO] Container '{SESSION_NAME}' already exists.")
        print(f"       Attach: kstlib ops attach {SESSION_NAME}")
        print("       Stop:   python run.py --stop")

    except SessionConfigError as e:
        print(f"[ERROR] Config error: {e}")
        sys.exit(1)

    except Exception as e:
        if "image not found" in str(e).lower() or "no such image" in str(e).lower():
            print("[ERROR] Image 'astro-bot' not found!")
            print("        Build it first:")
            print("        cd examples/ops")
            print("        podman build -t astro-bot .")
            sys.exit(1)
        raise


def show_status() -> None:
    """Show session status from config."""
    try:
        session = SessionManager.from_config(SESSION_NAME)
        status = session.status()

        print(f"Session: {status.name}")
        print(f"Backend: {status.backend}")
        print(f"State:   {status.state}")
        if status.image:
            print(f"Image:   {status.image}")
        if status.pid:
            print(f"PID:     {status.pid}")

    except SessionNotFoundError:
        print(f"[INFO] Container '{SESSION_NAME}' not found.")

    except SessionConfigError as e:
        print(f"[ERROR] Config error: {e}")
        sys.exit(1)


def stop_session() -> None:
    """Stop the session from config."""
    try:
        session = SessionManager.from_config(SESSION_NAME)
        session.stop()
        print(f"[OK] Container '{SESSION_NAME}' stopped.")

    except SessionNotFoundError:
        print(f"[INFO] Container '{SESSION_NAME}' not found (already stopped?).")

    except SessionConfigError as e:
        print(f"[ERROR] Config error: {e}")
        sys.exit(1)


def main() -> None:
    """Run config-driven container session example."""
    parser = argparse.ArgumentParser(
        description="Config-driven container session (reads kstlib.conf.yml)",
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
