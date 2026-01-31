"""Graceful Shutdown examples - clean process termination.

The GracefulShutdown class provides:
1. Priority-based callback ordering (lower = earlier)
2. Signal handling (SIGTERM, SIGINT)
3. Both sync and async callback support
4. Configurable timeouts

Run: python examples/resilience/02_graceful_shutdown.py
"""

from __future__ import annotations

import asyncio
import threading
import time

from kstlib.resilience import GracefulShutdown

# =============================================================================
# Example 1: Basic shutdown with priorities
# =============================================================================


def demo_basic_priorities() -> None:
    """Demonstrate priority-based callback execution."""
    shutdown = GracefulShutdown()

    # Register callbacks with different priorities
    shutdown.register("database", lambda: print("  3. Database connections closed"), priority=30)
    shutdown.register("cache", lambda: print("  2. Cache flushed"), priority=20)
    shutdown.register("logger", lambda: print("  4. Logger finalized"), priority=40)
    shutdown.register("metrics", lambda: print("  1. Metrics exported"), priority=10)

    print("Registered callbacks (will execute in priority order):")
    print("  - metrics (priority=10)")
    print("  - cache (priority=20)")
    print("  - database (priority=30)")
    print("  - logger (priority=40)")

    print("\nTriggering shutdown...")
    shutdown.trigger()

    print("\nShutdown complete!")


# =============================================================================
# Example 2: Async callbacks
# =============================================================================


async def demo_async_callbacks() -> None:
    """Demonstrate async callback support."""
    shutdown = GracefulShutdown()

    async def async_cleanup() -> None:
        print("  Starting async cleanup...")
        await asyncio.sleep(0.5)  # Simulate async operation
        print("  Async cleanup done!")

    async def flush_buffers() -> None:
        print("  Flushing buffers...")
        await asyncio.sleep(0.3)
        print("  Buffers flushed!")

    # Register async callbacks
    shutdown.register("async_cleanup", async_cleanup, priority=10)
    shutdown.register("buffers", flush_buffers, priority=20)

    print("Triggering async shutdown...")
    await shutdown.atrigger()
    print("Async shutdown complete!")


# =============================================================================
# Example 3: Mixed sync and async callbacks
# =============================================================================


async def demo_mixed_callbacks() -> None:
    """Demonstrate mixing sync and async callbacks."""
    shutdown = GracefulShutdown()

    def sync_cleanup() -> None:
        print("  Sync: Closing file handles")
        time.sleep(0.2)

    async def async_cleanup() -> None:
        print("  Async: Notifying services")
        await asyncio.sleep(0.3)

    shutdown.register("files", sync_cleanup, priority=10)
    shutdown.register("notify", async_cleanup, priority=20)
    shutdown.register("log", lambda: print("  Sync: Final log entry"), priority=30)

    print("Mixed shutdown (sync + async callbacks):")
    await shutdown.atrigger()
    print("Mixed shutdown complete!")


# =============================================================================
# Example 4: Shutdown with timeout
# =============================================================================


def demo_timeout_handling() -> None:
    """Demonstrate callback timeout handling."""
    shutdown = GracefulShutdown()

    def fast_cleanup() -> None:
        print("  Fast cleanup: done immediately")

    def slow_cleanup() -> None:
        print("  Slow cleanup: starting (takes 2 seconds)...")
        time.sleep(2)
        print("  Slow cleanup: finished")

    shutdown.register("fast", fast_cleanup, priority=10)
    shutdown.register("slow", slow_cleanup, priority=20, timeout=1.0)  # 1s timeout
    shutdown.register("final", lambda: print("  Final: always runs"), priority=30)

    print("Triggering shutdown with 1s timeout on slow callback...")
    print("(slow callback takes 2s, so it will be interrupted)\n")
    shutdown.trigger()

    print("\nShutdown completed (slow callback may have timed out)")


# =============================================================================
# Example 5: Wait for shutdown from another thread
# =============================================================================


def demo_wait_shutdown() -> None:
    """Demonstrate waiting for shutdown from another thread."""
    shutdown = GracefulShutdown()

    def cleanup() -> None:
        print("  Cleanup running...")
        time.sleep(0.5)
        print("  Cleanup done!")

    shutdown.register("cleanup", cleanup)

    def trigger_thread() -> None:
        time.sleep(0.5)
        print("\nWorker: Triggering shutdown...")
        shutdown.trigger()

    def waiter_thread() -> None:
        print("Waiter: Waiting for shutdown signal...")
        completed = shutdown.wait(timeout=5.0)
        if completed:
            print("Waiter: Shutdown completed!")
        else:
            print("Waiter: Timeout waiting for shutdown")

    print("Starting threads...")
    waiter = threading.Thread(target=waiter_thread)
    trigger = threading.Thread(target=trigger_thread)

    waiter.start()
    trigger.start()

    waiter.join()
    trigger.join()


# =============================================================================
# Example 6: Signal handling (conceptual)
# =============================================================================


def demo_signal_handling() -> None:
    """Demonstrate signal handling setup (without actual signals)."""
    shutdown = GracefulShutdown()

    shutdown.register("cleanup", lambda: print("  Cleanup on signal"))

    print("Registering signal handlers...")
    # Note: install() registers for SIGTERM and SIGINT
    # In a real application, pressing Ctrl+C would trigger shutdown

    # Show what signals would be handled
    print("  - SIGTERM: Graceful termination request")
    print("  - SIGINT: Keyboard interrupt (Ctrl+C)")

    print("\nIn a real application:")
    print("  shutdown.install()")
    print("  # Now Ctrl+C or 'kill <pid>' triggers graceful shutdown")

    # For demo, just trigger manually
    print("\nSimulating signal-triggered shutdown:")
    shutdown.trigger()


# =============================================================================
# Example 7: Callback error handling
# =============================================================================


def demo_error_handling() -> None:
    """Demonstrate that errors in callbacks don't stop shutdown."""
    shutdown = GracefulShutdown()

    def good_cleanup() -> None:
        print("  1. Good cleanup: success")

    def bad_cleanup() -> None:
        print("  2. Bad cleanup: raising exception...")
        raise RuntimeError("Simulated error!")

    def final_cleanup() -> None:
        print("  3. Final cleanup: still runs despite previous error!")

    shutdown.register("good", good_cleanup, priority=10)
    shutdown.register("bad", bad_cleanup, priority=20)
    shutdown.register("final", final_cleanup, priority=30)

    print("Triggering shutdown (one callback will fail):")
    print("(Errors are caught - all callbacks still execute)\n")
    shutdown.trigger()

    print("\nAll callbacks executed despite the error!")


# =============================================================================
# Main
# =============================================================================


def main() -> None:
    """Run all graceful shutdown examples."""
    print("=" * 60)
    print("GRACEFUL SHUTDOWN EXAMPLES")
    print("=" * 60)

    print("\n1. Basic Priorities")
    print("-" * 40)
    demo_basic_priorities()

    print("\n\n2. Async Callbacks")
    print("-" * 40)
    asyncio.run(demo_async_callbacks())

    print("\n\n3. Mixed Sync/Async Callbacks")
    print("-" * 40)
    asyncio.run(demo_mixed_callbacks())

    print("\n\n4. Timeout Handling")
    print("-" * 40)
    demo_timeout_handling()

    print("\n\n5. Wait for Shutdown from Thread")
    print("-" * 40)
    demo_wait_shutdown()

    print("\n\n6. Signal Handling (Conceptual)")
    print("-" * 40)
    demo_signal_handling()

    print("\n\n7. Error Handling")
    print("-" * 40)
    demo_error_handling()

    print("\n" + "=" * 60)
    print("Examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
