"""Basic logging usage examples.

This script demonstrates the basic usage of kstlib.logging module:
- Using different log levels (trace, debug, info, success, warning, error, critical)
- Structured logging with context key=value pairs
- Different output modes (console, file, both)
- Log file rotation

Run this script:
    python examples/logging/basic_usage.py
"""

from __future__ import annotations

import asyncio
import random

from kstlib.logging import LogManager

# pylint: disable=invalid-name
# Reason: Example files use numbered naming convention


# Example 1: Basic logging levels
def demo_basic_logging() -> None:
    """Demonstrate basic logging with all levels."""
    print("\n=== Basic Logging Demo ===\n")

    # Create logger with default config (console + file)
    logger = LogManager(name="basic_demo")

    # Log different levels (TRACE is the most verbose, below DEBUG)
    logger.trace("This is a trace message")  # Ultra-verbose, for HTTP debugging
    logger.debug("This is a debug message")
    logger.info("This is an info message")
    logger.success("This is a success message")  # Custom level
    logger.warning("This is a warning message")
    logger.error("This is an error message")
    logger.critical("This is a critical message")

    print("\n✅ Check ./logs/kstlib.log for file output\n")


# Example 2: Structured logging
def demo_structured_logging() -> None:
    """Demonstrate structured logging with context."""
    print("\n=== Structured Logging Demo ===\n")

    logger = LogManager(name="structured_demo")

    # Log with context key=value pairs
    logger.info("Server started", host="localhost", port=8080)
    logger.success("Connection established", client_id=12345, ip="192.168.1.100")
    logger.warning("High memory usage", usage_percent=85, threshold=80)
    logger.error(
        "Database connection failed",
        db_host="localhost",
        db_port=5432,
        retry_count=3,
    )

    print("\n✅ Structured logging adds context to messages\n")


# Example 3: Preset usage
def demo_presets() -> None:
    """Demonstrate logging presets (dev, prod, debug)."""
    print("\n=== Presets Demo ===\n")

    # Dev preset: console only, DEBUG level, show path
    print("1. Dev preset (console only, DEBUG):")
    dev_logger = LogManager(name="dev", preset="dev")
    dev_logger.debug("Dev mode debug message")
    dev_logger.info("Dev mode info message")

    # Prod preset: file only, INFO level, no path
    print("\n2. Prod preset (file only, INFO):")
    prod_logger = LogManager(name="prod", preset="prod")
    prod_logger.debug("This won't show (DEBUG < INFO)")
    prod_logger.info("Prod mode info message (file only)")
    print("   → Check logs/kstlib.log (no console output)")

    # Debug preset: both console+file, DEBUG level, show locals in tracebacks
    print("\n3. Debug preset (both, DEBUG, show locals):")
    debug_logger = LogManager(name="debug", preset="debug")
    debug_logger.debug("Debug mode with full tracebacks")
    debug_logger.info("Debug mode info message")

    print("\n✅ Presets configure logger for different environments\n")


# Example 4: Custom runtime configuration
def demo_custom_config() -> None:
    """Demonstrate custom configuration."""
    print("\n=== Custom Config Demo ===\n")

    # Custom config with specific settings
    custom_config = {
        "output": "console",  # Console only
        "icons": {"show": False},  # Hide icons
        "console": {
            "level": "WARNING",  # Only show WARNING and above
            "show_path": False,
        },
    }

    logger = LogManager(name="custom", config=custom_config)

    logger.debug("This won't show (DEBUG < WARNING)")
    logger.info("This won't show (INFO < WARNING)")
    logger.warning("This shows (WARNING >= WARNING)")
    logger.error("This shows (ERROR > WARNING)")

    print("\n✅ Custom config allows fine-grained control\n")


# Example 5: Rich traceback integration
def demo_exception_traceback() -> None:
    """Demonstrate Rich traceback with exception."""
    print("\n=== Exception Traceback Demo ===\n")

    logger = LogManager(name="traceback_demo")

    try:
        # Simulate an error
        _ = 10 / 0
    except ZeroDivisionError as e:
        logger.error("Division by zero error occurred", operation="10/0")
        logger.traceback(e)  # Rich traceback with locals

    print("\n✅ Rich traceback shows locals and context\n")


# Example 6: Async logging integration
async def demo_async_logging() -> None:
    """Demonstrate the async logging helpers inside an asyncio workflow."""
    print("\n=== Async Logging Demo ===\n")

    logger = LogManager(name="async_demo", config={"output": "console"})

    jitter = (0.05, 0.3)

    async def simulate_task(task_name: str, duration: float) -> None:
        await logger.ainfo("Task started", task=task_name, duration=duration)
        await asyncio.sleep(duration + random.uniform(*jitter))
        await logger.asuccess("Task finished", task=task_name)

    await asyncio.gather(
        simulate_task("cache-refresh", 0.2),
        simulate_task("price-feed", 0.1),
        simulate_task("heartbeat", 0.05),
    )

    try:
        raise RuntimeError("Websocket disconnected")
    except RuntimeError as exc:
        await logger.aerror("Background worker failed", reason=str(exc))

    print("\n✅ Async helpers let you log without blocking the event loop\n")


# Example 7: HTTP trace logging
def demo_trace_logging() -> None:
    """Demonstrate TRACE level for HTTP debugging."""
    print("\n=== TRACE Level Demo ===\n")

    # TRACE level is below DEBUG - for ultra-verbose protocol logging
    logger = LogManager(
        name="trace_demo",
        config={
            "output": "console",
            "console": {"level": "TRACE"},  # Enable TRACE
        },
    )

    # Simulate HTTP request/response logging
    logger.trace("HTTP Request", method="POST", url="https://auth.example.com/token")
    logger.trace("Request headers", content_type="application/json", accept="*/*")
    logger.trace("Request body", grant_type="authorization_code", code="abc123")

    logger.debug("Sending token request...")

    logger.trace("HTTP Response", status=200, content_type="application/json")
    logger.trace("Response body", access_token="***", expires_in=3600)

    logger.info("Token obtained successfully")

    print("\n✅ TRACE level helps debug HTTP/OAuth flows\n")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("KSTLIB LOGGING - BASIC USAGE EXAMPLES")
    print("=" * 60)

    demo_basic_logging()
    demo_structured_logging()
    demo_presets()
    demo_custom_config()
    demo_exception_traceback()
    demo_trace_logging()
    asyncio.run(demo_async_logging())

    print("=" * 60)
    print("All demos completed! Check ./logs/kstlib.log for file output.")
    print("=" * 60 + "\n")
