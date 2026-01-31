"""Circuit Breaker examples - fault tolerance for external services.

The circuit breaker pattern prevents cascading failures by:
1. CLOSED: Normal operation, requests pass through
2. OPEN: After N failures, requests fail immediately (fast-fail)
3. HALF-OPEN: After timeout, allow one request to test recovery

Run: python examples/resilience/01_circuit_breaker.py
"""

from __future__ import annotations

import random
import time

from kstlib.resilience import CircuitBreaker, CircuitOpenError, CircuitState, circuit_breaker

# =============================================================================
# Example 1: Basic circuit breaker as decorator
# =============================================================================


@circuit_breaker(max_failures=3, reset_timeout=5)
def call_external_api(endpoint: str) -> dict[str, str]:
    """Simulate an unreliable external API call."""
    # Simulate 50% failure rate
    if random.random() < 0.5:
        raise ConnectionError(f"Failed to connect to {endpoint}")
    return {"status": "ok", "endpoint": endpoint}


def demo_decorator() -> None:
    """Demonstrate circuit breaker as decorator."""
    print("Making API calls (50% failure rate)...")
    print("Circuit will open after 3 consecutive failures.\n")

    for i in range(10):
        try:
            result = call_external_api("/api/data")
            print(f"  Call {i + 1}: SUCCESS - {result}")
        except CircuitOpenError:
            print(f"  Call {i + 1}: BLOCKED - Circuit is OPEN (fast-fail)")
        except ConnectionError as e:
            print(f"  Call {i + 1}: FAILED - {e}")

        time.sleep(0.3)


# =============================================================================
# Example 2: Circuit breaker with manual control
# =============================================================================


def demo_manual_control() -> None:
    """Demonstrate manual circuit breaker usage."""
    cb = CircuitBreaker(max_failures=2, reset_timeout=3, name="payment-service")

    def make_payment(amount: float) -> str:
        """Simulate payment processing."""
        if amount > 1000:
            raise ValueError("Amount exceeds limit")
        return f"Payment of ${amount:.2f} processed"

    print(f"Circuit breaker: {cb.name}")
    print(f"Initial state: {cb.state.name}\n")

    # Simulate some failures
    test_amounts = [100, 50, 2000, 2000, 2000, 75, 200]

    for amount in test_amounts:
        try:
            result = cb.call(make_payment, amount)
            print(f"  ${amount}: {result}")
        except CircuitOpenError:
            print(f"  ${amount}: BLOCKED - Circuit OPEN")
        except ValueError as e:
            print(f"  ${amount}: FAILED - {e}")

        print(f"    -> State: {cb.state.name}, Failures: {cb.failure_count}")

    # Show statistics
    print("\nStatistics:")
    print(f"  Total calls: {cb.stats.total_calls}")
    print(f"  Successful: {cb.stats.successful_calls}")
    print(f"  Failed: {cb.stats.failed_calls}")
    print(f"  Rejected: {cb.stats.rejected_calls}")


# =============================================================================
# Example 3: Circuit breaker state transitions
# =============================================================================


def demo_state_transitions() -> None:
    """Demonstrate circuit breaker state machine."""
    cb = CircuitBreaker(max_failures=2, reset_timeout=2)

    def flaky_service(should_fail: bool) -> str:
        if should_fail:
            raise RuntimeError("Service unavailable")
        return "OK"

    print("Demonstrating state transitions:\n")

    # Start CLOSED
    print(f"1. Initial state: {cb.state.name}")
    assert cb.state == CircuitState.CLOSED

    # Cause failures to open circuit
    print("\n2. Causing 2 failures to open circuit...")
    for i in range(2):
        try:
            cb.call(flaky_service, should_fail=True)
        except RuntimeError:
            print(f"   Failure {i + 1}: State = {cb.state.name}")

    # Circuit should be OPEN
    print(f"\n3. After failures: {cb.state.name}")
    # mypy narrows state type after first assert; state mutation not tracked
    assert cb.state == CircuitState.OPEN  # type: ignore[comparison-overlap]

    # Calls should be rejected immediately
    print("\n4. Attempting call while OPEN...")  # type: ignore[unreachable]
    try:
        cb.call(flaky_service, should_fail=False)
    except CircuitOpenError:
        print(f"   Call rejected (fast-fail): State = {cb.state.name}")

    # Wait for reset timeout (2s as configured above)
    reset_timeout = 2
    print(f"\n5. Waiting {reset_timeout}s for reset timeout...")
    time.sleep(reset_timeout + 0.1)

    # Circuit should be HALF-OPEN
    print(f"   State after timeout: {cb.state.name}")
    assert cb.state == CircuitState.HALF_OPEN

    # Successful call should close circuit
    print("\n6. Making successful call in HALF-OPEN state...")
    result = cb.call(flaky_service, should_fail=False)
    print(f"   Result: {result}")
    print(f"   State after success: {cb.state.name}")
    assert cb.state == CircuitState.CLOSED

    print("\nCircuit breaker recovered successfully!")


# =============================================================================
# Example 4: Async circuit breaker
# =============================================================================


async def demo_async() -> None:
    """Demonstrate async circuit breaker usage."""
    import asyncio

    cb = CircuitBreaker(max_failures=2, reset_timeout=2)

    async def async_api_call(delay: float) -> str:
        await asyncio.sleep(delay)
        if delay > 0.5:
            raise TimeoutError("Request timed out")
        return f"Response in {delay}s"

    print("Async circuit breaker demo:\n")

    delays = [0.1, 0.2, 0.8, 0.9, 0.1, 0.1]

    for delay in delays:
        try:
            result = await cb.acall(async_api_call, delay)
            print(f"  delay={delay}s: {result}")
        except CircuitOpenError:
            print(f"  delay={delay}s: BLOCKED - Circuit OPEN")
        except TimeoutError as e:
            print(f"  delay={delay}s: FAILED - {e}")

        print(f"    -> State: {cb.state.name}")


# =============================================================================
# Example 5: Excluded exceptions
# =============================================================================


def demo_excluded_exceptions() -> None:
    """Demonstrate exceptions that don't trip the circuit."""
    # ValidationError won't count as a failure (user error, not service error)
    cb = CircuitBreaker(
        max_failures=2,
        excluded_exceptions=(ValueError,),
        name="validation-aware",
    )

    def process_order(order_id: int) -> str:
        if order_id < 0:
            raise ValueError("Invalid order ID")  # Won't trip circuit
        if order_id == 0:
            raise RuntimeError("Database error")  # Will trip circuit
        return f"Order {order_id} processed"

    print("Excluded exceptions demo:\n")
    print("ValueError is excluded (user error, won't trip circuit)")
    print("RuntimeError counts as failure (service error)\n")

    test_ids = [-1, -2, -3, 0, 0, 1]

    for order_id in test_ids:
        try:
            result = cb.call(process_order, order_id)
            print(f"  Order {order_id}: {result}")
        except CircuitOpenError:
            print(f"  Order {order_id}: BLOCKED - Circuit OPEN")
        except ValueError as e:
            print(f"  Order {order_id}: ValidationError - {e}")
        except RuntimeError as e:
            print(f"  Order {order_id}: ServiceError - {e}")

        print(f"    -> State: {cb.state.name}, Failures: {cb.failure_count}")


# =============================================================================
# Main
# =============================================================================


def main() -> None:
    """Run all circuit breaker examples."""
    import asyncio

    print("=" * 60)
    print("CIRCUIT BREAKER EXAMPLES")
    print("=" * 60)

    print("\n1. Decorator Usage")
    print("-" * 40)
    demo_decorator()

    print("\n\n2. Manual Control")
    print("-" * 40)
    demo_manual_control()

    print("\n\n3. State Transitions")
    print("-" * 40)
    demo_state_transitions()

    print("\n\n4. Async Usage")
    print("-" * 40)
    asyncio.run(demo_async())

    print("\n\n5. Excluded Exceptions")
    print("-" * 40)
    demo_excluded_exceptions()

    print("\n" + "=" * 60)
    print("Examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
