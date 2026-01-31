"""Rate Limiter examples - token bucket algorithm for request throttling.

The rate limiter controls request throughput by:
1. Maintaining a bucket of tokens that refill at a constant rate
2. Each request consumes one token
3. Requests wait (blocking) or fail (non-blocking) when bucket is empty

Run: python examples/resilience/04_rate_limiter.py
"""

from __future__ import annotations

import time

from kstlib.resilience import RateLimiter, RateLimitExceededError, rate_limiter

# =============================================================================
# Example 1: Basic rate limiter
# =============================================================================


def demo_basic() -> None:
    """Demonstrate basic rate limiter usage."""
    # 5 requests per second
    limiter = RateLimiter(rate=5, per=1.0)

    print("Making 10 requests with rate limit of 5/second...")
    print("First 5 should be instant, next 5 will be throttled.\n")

    start = time.monotonic()

    for i in range(10):
        limiter.acquire()  # Blocks until token available
        elapsed = time.monotonic() - start
        print(f"  Request {i + 1}: completed at {elapsed:.2f}s")

    total = time.monotonic() - start
    print(f"\nTotal time: {total:.2f}s (expected ~2s for 10 requests at 5/s)")


# =============================================================================
# Example 2: Non-blocking mode
# =============================================================================


def demo_non_blocking() -> None:
    """Demonstrate non-blocking rate limiter."""
    limiter = RateLimiter(rate=3, per=1.0)

    print("Non-blocking mode: try_acquire() returns False instead of waiting.\n")

    for i in range(6):
        if limiter.try_acquire():
            print(f"  Request {i + 1}: ALLOWED")
        else:
            print(f"  Request {i + 1}: REJECTED (no token available)")


# =============================================================================
# Example 3: Burst capacity
# =============================================================================


def demo_burst() -> None:
    """Demonstrate burst capacity."""
    # Rate of 2/s but allow bursts up to 5
    limiter = RateLimiter(rate=2, per=1.0, burst=5)

    print("Burst capacity: rate=2/s, burst=5")
    print("Allows 5 immediate requests, then throttles to 2/s.\n")

    start = time.monotonic()

    for i in range(8):
        limiter.acquire()
        elapsed = time.monotonic() - start
        print(f"  Request {i + 1}: completed at {elapsed:.2f}s")

    total = time.monotonic() - start
    print(f"\nTotal time: {total:.2f}s")


# =============================================================================
# Example 4: Timeout mode
# =============================================================================


def demo_timeout() -> None:
    """Demonstrate acquire with timeout."""
    limiter = RateLimiter(rate=1, per=1.0)

    print("Timeout mode: acquire(timeout=0.5) waits max 0.5 seconds.\n")

    # Consume the only token
    limiter.acquire()
    print("  First request: SUCCESS (consumed token)")

    # Try to acquire with short timeout
    try:
        limiter.acquire(timeout=0.3)
        print("  Second request: SUCCESS")
    except RateLimitExceededError as e:
        print(f"  Second request: TIMEOUT after 0.3s (retry in {e.retry_after:.2f}s)")


# =============================================================================
# Example 5: Decorator usage
# =============================================================================


@rate_limiter(rate=3, per=1.0)
def api_call_blocking(endpoint: str) -> str:
    """Simulated API call with blocking rate limit."""
    return f"Response from {endpoint}"


@rate_limiter(rate=2, per=1.0, blocking=False)
def api_call_non_blocking(endpoint: str) -> str:
    """Simulated API call with non-blocking rate limit."""
    return f"Response from {endpoint}"


def demo_decorator() -> None:
    """Demonstrate rate limiter decorator."""
    print("Decorator usage:\n")

    # Blocking decorator
    print("@rate_limiter(rate=3, blocking=True):")
    start = time.monotonic()
    for i in range(5):
        result = api_call_blocking("/api/data")
        elapsed = time.monotonic() - start
        print(f"  Call {i + 1}: {result} at {elapsed:.2f}s")

    print("\n@rate_limiter(rate=2, blocking=False):")
    for i in range(4):
        try:
            result = api_call_non_blocking("/api/data")
            print(f"  Call {i + 1}: {result}")
        except RateLimitExceededError:
            print(f"  Call {i + 1}: RATE LIMITED")


# =============================================================================
# Example 6: Statistics
# =============================================================================


def demo_statistics() -> None:
    """Demonstrate rate limiter statistics."""
    limiter = RateLimiter(rate=5, per=1.0)

    print("Statistics tracking:\n")

    # Make some successful requests
    for _ in range(3):
        limiter.acquire()

    # Try some that will be rejected (non-blocking)
    for _ in range(3):
        limiter.try_acquire()

    stats = limiter.stats
    print(f"  Requests acquired: {stats.total_acquired}")
    print(f"  Requests rejected: {stats.total_rejected}")
    print(f"  Total wait time: {stats.total_waited:.3f}s")
    print(f"  Available tokens: {limiter.tokens:.1f}")


# =============================================================================
# Example 7: Async usage
# =============================================================================


async def demo_async() -> None:
    """Demonstrate async rate limiter."""
    import asyncio

    limiter = RateLimiter(rate=5, per=1.0)

    async def fetch_data(item_id: int) -> str:
        await limiter.acquire_async()
        await asyncio.sleep(0.1)  # Simulate async work
        return f"Data for item {item_id}"

    print("Async rate limiter:\n")

    start = time.monotonic()
    tasks = [fetch_data(i) for i in range(8)]
    results = await asyncio.gather(*tasks)

    for i, result in enumerate(results):
        print(f"  Task {i + 1}: {result}")

    total = time.monotonic() - start
    print(f"\nTotal time: {total:.2f}s")


# =============================================================================
# Main
# =============================================================================


def main() -> None:
    """Run all rate limiter examples."""
    import asyncio

    print("=" * 60)
    print("RATE LIMITER EXAMPLES")
    print("=" * 60)

    print("\n1. Basic Rate Limiting")
    print("-" * 40)
    demo_basic()

    print("\n\n2. Non-Blocking Mode")
    print("-" * 40)
    demo_non_blocking()

    print("\n\n3. Burst Capacity")
    print("-" * 40)
    demo_burst()

    print("\n\n4. Timeout Mode")
    print("-" * 40)
    demo_timeout()

    print("\n\n5. Decorator Usage")
    print("-" * 40)
    demo_decorator()

    print("\n\n6. Statistics")
    print("-" * 40)
    demo_statistics()

    print("\n\n7. Async Usage")
    print("-" * 40)
    asyncio.run(demo_async())

    print("\n" + "=" * 60)
    print("Examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
