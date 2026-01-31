"""Heartbeat examples - process liveness signaling.

The Heartbeat class provides:
1. Periodic file-based heartbeat signals
2. State persistence (PID, hostname, metadata)
3. Stale process detection (via timestamp comparison)
4. Integration with monitoring systems

Run: python examples/resilience/03_heartbeat.py
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from kstlib.resilience import Heartbeat


def get_age(timestamp_str: str) -> float:
    """Calculate age in seconds from ISO timestamp."""
    ts = datetime.fromisoformat(timestamp_str)
    now = datetime.now(tz=timezone.utc)
    return (now - ts).total_seconds()


def is_stale(timestamp_str: str, max_age: float) -> bool:
    """Check if a heartbeat timestamp is stale."""
    return get_age(timestamp_str) > max_age


# =============================================================================
# Example 1: Basic heartbeat
# =============================================================================


def demo_basic_heartbeat() -> None:
    """Demonstrate basic heartbeat usage."""
    # Use temp file for demo
    state_file = Path(tempfile.gettempdir()) / "demo_heartbeat.json"

    heartbeat = Heartbeat(
        state_file=state_file,
        interval=1.0,  # Beat every second
    )

    print(f"State file: {state_file}")
    print(f"Interval: {heartbeat.interval}s")
    print(f"Process ID: {os.getpid()}")

    print("\nStarting heartbeat...")
    heartbeat.start()

    # Let it beat a few times
    for i in range(3):
        time.sleep(1.1)
        print(f"  Beat {i + 1}: heartbeat written")

    print("\nStopping heartbeat...")
    heartbeat.stop()

    # Clean up
    if state_file.exists():
        state_file.unlink()

    print("Heartbeat stopped!")


# =============================================================================
# Example 2: Reading heartbeat state
# =============================================================================


def demo_read_state() -> None:
    """Demonstrate reading heartbeat state from file."""
    state_file = Path(tempfile.gettempdir()) / "demo_state.json"

    # Start a heartbeat
    heartbeat = Heartbeat(state_file=state_file, interval=0.5)
    heartbeat.start()
    time.sleep(0.6)  # Let it write once

    # Read the state
    state = Heartbeat.read_state(state_file)

    if state:
        age = get_age(state.timestamp)
        print("Heartbeat state read from file:")
        print(f"  PID: {state.pid}")
        print(f"  Hostname: {state.hostname}")
        print(f"  Timestamp: {state.timestamp}")
        print(f"  Age: {age:.2f}s ago")
        print(f"  Is stale (>10s): {is_stale(state.timestamp, max_age=10)}")
    else:
        print("No heartbeat state found")

    heartbeat.stop()
    if state_file.exists():
        state_file.unlink()


# =============================================================================
# Example 3: Heartbeat with metadata
# =============================================================================


def demo_heartbeat_metadata() -> None:
    """Demonstrate heartbeat with custom metadata."""
    state_file = Path(tempfile.gettempdir()) / "demo_metadata.json"

    # Custom metadata to include in heartbeat
    metadata = {
        "service": "trading-bot",
        "version": "1.2.3",
        "environment": "production",
        "pairs": ["BTC/USDT", "ETH/USDT"],
    }

    heartbeat = Heartbeat(
        state_file=state_file,
        interval=1.0,
        metadata=metadata,
    )

    print("Starting heartbeat with metadata...")
    heartbeat.start()
    time.sleep(1.1)

    # Read and display metadata
    state = Heartbeat.read_state(state_file)
    if state and state.metadata:
        print("\nMetadata in heartbeat:")
        for key, value in state.metadata.items():
            print(f"  {key}: {value}")

    heartbeat.stop()
    if state_file.exists():
        state_file.unlink()


# =============================================================================
# Example 4: Stale heartbeat detection
# =============================================================================


def demo_stale_detection() -> None:
    """Demonstrate detecting stale (dead) processes."""
    state_file = Path(tempfile.gettempdir()) / "demo_stale.json"

    heartbeat = Heartbeat(state_file=state_file, interval=0.5)

    print("Starting heartbeat...")
    heartbeat.start()
    time.sleep(0.6)

    print("Stopping heartbeat (simulating process death)...")
    heartbeat.stop()

    print("\nWaiting for heartbeat to become stale...")
    time.sleep(2.5)

    # Check if stale
    state = Heartbeat.read_state(state_file)
    if state:
        age = get_age(state.timestamp)
        print(f"\nHeartbeat age: {age:.1f}s")
        print(f"Is stale (max_age=2s): {is_stale(state.timestamp, max_age=2)}")
        print(f"Is stale (max_age=5s): {is_stale(state.timestamp, max_age=5)}")

        if is_stale(state.timestamp, max_age=2):
            print("\nProcess appears dead - heartbeat is stale!")

    if state_file.exists():
        state_file.unlink()


# =============================================================================
# Example 5: Monitoring multiple processes
# =============================================================================


def demo_multi_process_monitoring() -> None:
    """Demonstrate monitoring multiple processes via heartbeats."""
    temp_dir = Path(tempfile.gettempdir())

    # Simulate multiple services
    services = ["api-server", "worker-1", "worker-2", "scheduler"]
    heartbeats = []

    print("Starting multiple service heartbeats...")
    for service in services:
        state_file = temp_dir / f"demo_{service}.json"
        hb = Heartbeat(
            state_file=state_file,
            interval=0.5,
            metadata={"service": service},
        )
        hb.start()
        heartbeats.append((service, state_file, hb))
        print(f"  Started: {service}")

    time.sleep(0.6)

    # Stop one to simulate failure
    print("\nSimulating worker-2 failure...")
    heartbeats[2][2].stop()
    time.sleep(2.5)

    # Check all heartbeats
    print("\nService health check:")
    print("-" * 40)
    for service, state_file, _hb in heartbeats:
        state = Heartbeat.read_state(state_file)
        if state:
            stale = is_stale(state.timestamp, max_age=2)
            status = "DEAD" if stale else "ALIVE"
            age = f"{get_age(state.timestamp):.1f}s"
        else:
            status = "UNKNOWN"
            age = "N/A"
        print(f"  {service:12} | {status:7} | last seen: {age} ago")

    # Cleanup
    print("\nCleaning up...")
    for _service, state_file, hb in heartbeats:
        hb.stop()
        if state_file.exists():
            state_file.unlink()


# =============================================================================
# Example 6: Async heartbeat
# =============================================================================


async def demo_async_heartbeat() -> None:
    """Demonstrate async heartbeat context manager."""
    state_file = Path(tempfile.gettempdir()) / "demo_async.json"

    heartbeat = Heartbeat(state_file=state_file, interval=0.5)

    print("Using heartbeat as async context manager...")

    async with heartbeat:
        print("  Heartbeat started automatically")

        # Simulate async work
        for i in range(3):
            await asyncio.sleep(0.6)
            state = Heartbeat.read_state(state_file)
            if state:
                age = get_age(state.timestamp)
                print(f"  Iteration {i + 1}: age={age:.2f}s")

    print("  Heartbeat stopped automatically on exit")

    if state_file.exists():
        state_file.unlink()


# =============================================================================
# Example 7: Heartbeat integration pattern
# =============================================================================


def demo_integration_pattern() -> None:
    """Demonstrate typical heartbeat integration in a service."""
    print("Typical service integration pattern:")
    print("-" * 40)

    print("""
    import tempfile
    from pathlib import Path
    from kstlib.resilience import Heartbeat, GracefulShutdown

    class TradingBot:
        def __init__(self):
            # Cross-platform: use temp directory
            state_file = Path(tempfile.gettempdir()) / "tradingbot.heartbeat"
            self.heartbeat = Heartbeat(
                state_file=state_file,
                interval=10,  # Beat every 10 seconds
                metadata={"version": "1.0.0"}
            )
            self.shutdown = GracefulShutdown()
            self.shutdown.register("heartbeat", self.heartbeat.stop, priority=100)

        async def run(self):
            self.heartbeat.start()
            try:
                while not self.shutdown.is_shutting_down:
                    await self.process_trades()
            finally:
                self.shutdown.trigger()

    # External monitor can check:
    state_file = Path(tempfile.gettempdir()) / "tradingbot.heartbeat"
    state = Heartbeat.read_state(state_file)
    if state:
        from datetime import datetime, timezone
        ts = datetime.fromisoformat(state.timestamp)
        age = (datetime.now(tz=timezone.utc) - ts).total_seconds()
        if age > 30:
            alert("Trading bot appears dead!")
    """)

    print("\nThis pattern provides:")
    print("  1. Liveness signaling for external monitors")
    print("  2. Clean shutdown integration")
    print("  3. Metadata for debugging (version, status, etc.)")


# =============================================================================
# Main
# =============================================================================


def main() -> None:
    """Run all heartbeat examples."""
    print("=" * 60)
    print("HEARTBEAT EXAMPLES")
    print("=" * 60)

    print("\n1. Basic Heartbeat")
    print("-" * 40)
    demo_basic_heartbeat()

    print("\n\n2. Reading State")
    print("-" * 40)
    demo_read_state()

    print("\n\n3. Heartbeat with Metadata")
    print("-" * 40)
    demo_heartbeat_metadata()

    print("\n\n4. Stale Detection")
    print("-" * 40)
    demo_stale_detection()

    print("\n\n5. Multi-Process Monitoring")
    print("-" * 40)
    demo_multi_process_monitoring()

    print("\n\n6. Async Heartbeat")
    print("-" * 40)
    asyncio.run(demo_async_heartbeat())

    print("\n\n7. Integration Pattern")
    print("-" * 40)
    demo_integration_pattern()

    print("\n" + "=" * 60)
    print("Examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
