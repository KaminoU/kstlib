#!/usr/bin/env python3
"""Run Astro Bot in a container (podman/docker).

This example demonstrates using SessionManager with the container backend
for production deployments. The bot runs in a persistent container that
survives terminal disconnection and system reboots (with restart policy).

Usage:
    # Build the image first
    podman build -t astro-bot .
    # or: docker build -t astro-bot .

    # Start the bot
    python run_container.py

    # Or via CLI
    kstlib ops start astro --backend container --image astro-bot

After starting:
    - The bot runs in background
    - Attach with: kstlib ops attach astro
    - Detach with: Ctrl+P Ctrl+Q
    - View logs: kstlib ops logs astro --lines 50
    - Stop: kstlib ops stop astro

Requirements:
    - podman or docker installed
    - Image built: podman build -t astro-bot .
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add examples to path for direct execution
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from kstlib.ops import SessionManager
from kstlib.ops.exceptions import ContainerRuntimeNotFoundError, SessionExistsError


def main() -> None:
    """Start Astro bot in container."""
    session_name = "astro"
    image_name = "astro-bot"

    print(f"[*] Starting Astro bot in container '{session_name}'...")

    try:
        # Create session manager with container backend
        # Runtime auto-detected (podman first, then docker)
        session = SessionManager(
            session_name,
            backend="container",
            image=image_name,
            # Optional: mount volume for persistent data
            # volumes=["./data:/app/data"],
        )

        # Start the container
        # Command is defined in Dockerfile CMD, no need to specify here
        status = session.start()

        print("[OK] Astro bot started!")
        print(f"     Container: {status.name}")
        print(f"     Backend: {status.backend}")
        print(f"     State: {status.state}")
        if status.image:
            print(f"     Image: {status.image}")
        print()
        print("Commands:")
        print(f"  Attach:  kstlib ops attach {session_name}")
        print(f"  Logs:    kstlib ops logs {session_name} --lines 50")
        print(f"  Status:  kstlib ops status {session_name} --json")
        print(f"  Stop:    kstlib ops stop {session_name}")
        print()
        print("In container: Ctrl+P Ctrl+Q to detach (bot keeps running)")

    except ContainerRuntimeNotFoundError:
        print("[ERROR] No container runtime found!")
        print("        Install podman: https://podman.io/getting-started/installation")
        print("        Or docker: https://docs.docker.com/get-docker/")
        sys.exit(1)

    except SessionExistsError:
        print(f"[INFO] Container '{session_name}' already exists.")
        print(f"       Attach with: kstlib ops attach {session_name}")
        print(f"       Or stop with: kstlib ops stop {session_name}")

    except Exception as e:
        if "image not found" in str(e).lower() or "no such image" in str(e).lower():
            print(f"[ERROR] Image '{image_name}' not found!")
            print("        Build it first:")
            print(f"        cd {Path(__file__).parent}")
            print(f"        podman build -t {image_name} .")
            sys.exit(1)
        raise


if __name__ == "__main__":
    main()
