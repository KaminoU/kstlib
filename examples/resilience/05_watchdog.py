"""Watchdog examples - detect thread/process freezes and hangs.

The watchdog monitors code health by:
1. Requiring periodic ping() calls to reset the timer
2. Triggering a callback if no ping received within timeout
3. Supporting both sync and async operations

Run: python examples/resilience/05_watchdog.py
"""

from __future__ import annotations

import threading
import time

from kstlib.resilience import Watchdog, watchdog_context

# =============================================================================
# Example 1: Basic watchdog with callback
# =============================================================================


def demo_basic() -> None:
    """Demonstrate basic watchdog usage."""
    triggered = threading.Event()

    def on_freeze() -> None:
        print("  [CALLBACK] Watchdog triggered! Thread appears frozen.")
        triggered.set()

    print("Starting watchdog with 2-second timeout...")
    print("Will ping for 1.5s, then stop pinging to trigger timeout.\n")

    watchdog = Watchdog(timeout=2, on_timeout=on_freeze)
    watchdog.start()

    try:
        # Ping regularly for 1.5 seconds
        start = time.monotonic()
        while time.monotonic() - start < 1.5:
            watchdog.ping()
            elapsed = time.monotonic() - start
            print(f"  Ping at {elapsed:.1f}s - timer reset")
            time.sleep(0.3)

        # Stop pinging - watchdog will trigger
        print("\n  Stopped pinging... waiting for timeout...")

        # Wait for callback
        if triggered.wait(timeout=3.0):
            print("  Watchdog detected inactivity!")
        else:
            print("  Timeout waiting for callback (unexpected)")

    finally:
        watchdog.stop()
        print("\nWatchdog stopped.")


# =============================================================================
# Example 2: Context manager usage
# =============================================================================


def demo_context_manager() -> None:
    """Demonstrate watchdog as context manager."""
    print("Using watchdog as context manager:\n")

    work_items = ["item_1", "item_2", "item_3", "item_4", "item_5"]

    def on_freeze() -> None:
        print("  [WARNING] Processing appears stuck!")

    with Watchdog(timeout=2, on_timeout=on_freeze, name="processor") as wd:
        print(f"  Watchdog '{wd.name}' started")

        for item in work_items:
            wd.ping()  # Reset timer before each item
            print(f"  Processing {item}...")
            time.sleep(0.3)  # Simulate work

        print("\n  All items processed successfully!")
        print(f"  Total pings: {wd.stats.pings_total}")

    print("  Watchdog stopped automatically (context manager)")


# =============================================================================
# Example 3: watchdog_context convenience function
# =============================================================================


def demo_watchdog_context() -> None:
    """Demonstrate watchdog_context helper."""
    print("Using watchdog_context() helper:\n")

    # Simple usage
    wd = watchdog_context(timeout=5, name="simple")
    print(f"  Created watchdog: timeout={wd.timeout}s, name={wd.name}")

    # With raise_on_timeout
    print("\n  With raise_on_timeout=True:")
    wd_raise = watchdog_context(timeout=1, raise_on_timeout=True)
    wd_raise.start()

    try:
        # Don't ping - let it timeout
        print("  Waiting for timeout (not pinging)...")
        time.sleep(1.5)

        # Check if triggered
        if wd_raise.is_triggered:
            print("  Watchdog triggered (would have raised in callback)")

    finally:
        wd_raise.stop()


# =============================================================================
# Example 4: Statistics and monitoring
# =============================================================================


def demo_statistics() -> None:
    """Demonstrate watchdog statistics."""
    print("Watchdog statistics:\n")

    watchdog = Watchdog(timeout=5)
    watchdog.start()

    try:
        # Make some pings
        for _ in range(5):
            watchdog.ping()
            time.sleep(0.1)

        stats = watchdog.stats
        print(f"  Pings total: {stats.pings_total}")
        print(f"  Timeouts triggered: {stats.timeouts_triggered}")
        print(f"  Uptime: {stats.uptime:.2f}s")
        print(f"  Last ping: {stats.last_ping_time:.2f} (monotonic)")
        print(f"  Seconds since ping: {watchdog.seconds_since_ping:.3f}s")
        print(f"  Is running: {watchdog.is_running}")
        print(f"  Is triggered: {watchdog.is_triggered}")

    finally:
        watchdog.stop()


# =============================================================================
# Example 5: Thread monitoring
# =============================================================================


def demo_thread_monitoring() -> None:
    """Demonstrate watchdog for worker thread monitoring."""
    print("Monitoring a worker thread:\n")

    worker_frozen = threading.Event()
    worker_done = threading.Event()

    def on_worker_freeze() -> None:
        print("  [ALERT] Worker thread appears frozen!")
        worker_frozen.set()

    def worker_task(watchdog: Watchdog, freeze_after: int) -> None:
        """Worker that processes items, freezing after N items."""
        for i in range(10):
            if i == freeze_after:
                print(f"  Worker: Simulating freeze at item {i}...")
                time.sleep(3)  # Simulate freeze

            watchdog.ping()
            print(f"  Worker: Processing item {i}")
            time.sleep(0.2)

        worker_done.set()

    watchdog = Watchdog(timeout=1, on_timeout=on_worker_freeze, name="worker")
    watchdog.start()

    try:
        # Start worker that will freeze after 3 items
        thread = threading.Thread(target=worker_task, args=(watchdog, 3))
        thread.start()

        # Wait for either completion or freeze detection
        while not worker_done.is_set() and not worker_frozen.is_set():
            time.sleep(0.1)

        if worker_frozen.is_set():
            print("\n  Main: Detected worker freeze via watchdog!")

        thread.join(timeout=5)

    finally:
        watchdog.stop()


# =============================================================================
# Example 6: Async watchdog
# =============================================================================


async def demo_async() -> None:
    """Demonstrate async watchdog usage."""
    import asyncio

    print("Async watchdog:\n")

    triggered = asyncio.Event()

    async def on_timeout() -> None:
        print("  [ASYNC CALLBACK] Timeout detected!")
        triggered.set()

    async with Watchdog(timeout=1, on_timeout=on_timeout) as wd:
        print("  Async watchdog started")

        # Ping a few times
        for i in range(3):
            await wd.aping()
            print(f"  Async ping {i + 1}")
            await asyncio.sleep(0.2)

        print("\n  Stopping pings, waiting for timeout...")
        await asyncio.sleep(1.5)

        if triggered.is_set():
            print("  Async callback was invoked!")

    print("  Async watchdog stopped")


# =============================================================================
# Example 7: Reset functionality
# =============================================================================


def demo_reset() -> None:
    """Demonstrate watchdog reset functionality."""
    print("Watchdog reset:\n")

    triggered_count = [0]

    def on_timeout() -> None:
        triggered_count[0] += 1
        print(f"  [TRIGGERED] Count: {triggered_count[0]}")

    watchdog = Watchdog(timeout=1, on_timeout=on_timeout)
    watchdog.start()

    try:
        # Let it trigger once
        print("  Waiting for first timeout...")
        time.sleep(1.5)
        print(f"  Is triggered: {watchdog.is_triggered}")

        # Reset and continue
        print("\n  Calling reset()...")
        watchdog.reset()
        print(f"  Is triggered after reset: {watchdog.is_triggered}")

        # Ping to keep alive
        print("\n  Pinging to prevent second timeout...")
        for _ in range(5):
            watchdog.ping()
            time.sleep(0.3)

        print(f"\n  Final trigger count: {triggered_count[0]}")

    finally:
        watchdog.stop()


# =============================================================================
# Main
# =============================================================================


def main() -> None:
    """Run all watchdog examples."""
    import asyncio

    print("=" * 60)
    print("WATCHDOG EXAMPLES")
    print("=" * 60)

    print("\n1. Basic Watchdog")
    print("-" * 40)
    demo_basic()

    print("\n\n2. Context Manager")
    print("-" * 40)
    demo_context_manager()

    print("\n\n3. watchdog_context Helper")
    print("-" * 40)
    demo_watchdog_context()

    print("\n\n4. Statistics")
    print("-" * 40)
    demo_statistics()

    print("\n\n5. Thread Monitoring")
    print("-" * 40)
    demo_thread_monitoring()

    print("\n\n6. Async Usage")
    print("-" * 40)
    asyncio.run(demo_async())

    print("\n\n7. Reset Functionality")
    print("-" * 40)
    demo_reset()

    print("\n" + "=" * 60)
    print("Examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
