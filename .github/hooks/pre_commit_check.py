#!/usr/bin/env python3
"""Pre-commit hook: ensures tox passes before commit.

This script implements a "tox marker" system:
- If .github/.tox-passed exists: developer already ran tox manually (fast path)
- If marker doesn't exist: run full tox suite now (safety net)

Usage:
    Run `tox` before committing to create the marker (faster commits).
    Or just commit directly and the hook will run tox for you.
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

# Fix Windows console encoding for Unicode output
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Marker file location
MARKER = Path(__file__).parent.parent / ".tox-passed"


def check_lockfiles() -> int:
    """Verify lockfiles are in sync. Returns 0 on success."""
    print("  Checking uv.lock...")
    result = subprocess.run(["uv", "lock", "--check"], capture_output=True, text=True)
    if result.returncode != 0:
        print("❌ uv.lock is out of sync.")
        print("   Run: make lock")
        return 1

    print("  Checking pylock.toml...")
    # Export current state
    subprocess.run(
        ["uv", "export", "--format", "pylock.toml", "--all-extras", "-o", "pylock.check.toml"],
        capture_output=True,
    )

    # Compare bodies (skip first 2 lines which have timestamps)
    pylock_current = Path("pylock.toml")
    pylock_check = Path("pylock.check.toml")

    if not pylock_current.exists():
        print("❌ pylock.toml not found.")
        pylock_check.unlink(missing_ok=True)
        return 1

    try:
        current_lines = pylock_current.read_text().splitlines()[2:]
        check_lines = pylock_check.read_text().splitlines()[2:]

        if current_lines != check_lines:
            print("❌ pylock.toml is out of sync.")
            print("   Run: make lock")
            return 1
    finally:
        pylock_check.unlink(missing_ok=True)

    print("  ✓ Lock files are in sync.")
    return 0


def main() -> int:
    """Main entry point."""
    print("=" * 60)
    print("Pre-commit check")
    print("=" * 60)

    if MARKER.exists():
        print(f"✓ Tox marker found ({MARKER})")
        print("  Skipping tox, validating lockfiles only...")
        print()

        lock_result = check_lockfiles()

        # Always clean up marker (one-time use)
        MARKER.unlink()

        if lock_result != 0:
            print()
            print("❌ Lock check failed. Fix issues before committing.")
            return lock_result

        print()
        print("✓ All checks passed!")
        return 0

    else:
        print("⚠ No tox marker found.")
        print("  Running full tox suite (this may take a while)...")
        print()

        # Run tox with output visible
        result = subprocess.run(["tox"])

        if result.returncode != 0:
            print()
            print("=" * 60)
            print("❌ Tox failed. Fix issues before committing.")
            print("=" * 60)
            return result.returncode

        print()
        print("=" * 60)
        print("✓ Tox passed! Commit allowed.")
        print("=" * 60)
        print()
        print("TIP: Run 'make tox' before committing for faster commits.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
