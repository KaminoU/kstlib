#!/usr/bin/env python3
"""Demonstrate RAPI error handling and retry behavior.

This example shows:
- Handling HTTP errors (4xx, 5xx)
- Timeout handling
- Retry behavior with exponential backoff
- Custom error handling

Uses httpbin.org error simulation endpoints.

Usage:
    python examples/rapi/03_error_handling.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from kstlib.rapi import (
    EndpointNotFoundError,
    RapiClient,
    RapiConfigManager,
    RequestError,
)


def create_config() -> RapiConfigManager:
    """Create config manager with error-testing endpoints."""
    config = {
        "api": {
            "httpbin": {
                "base_url": "https://httpbin.org",
                "endpoints": {
                    # Status code simulation
                    "status": {
                        "path": "/status/{code}",
                    },
                    # Delayed response (for timeout testing)
                    "delay": {
                        "path": "/delay/{seconds}",
                    },
                    # Normal endpoint for comparison
                    "uuid": {
                        "path": "/uuid",
                    },
                },
            }
        }
    }
    return RapiConfigManager(config)


def demo_http_errors() -> None:
    """Demonstrate handling of HTTP error status codes."""
    print("=" * 70)
    print("HTTP ERROR HANDLING")
    print("=" * 70)

    config_manager = create_config()
    client = RapiClient(config_manager=config_manager)

    # =========================================================================
    # Client Errors (4xx) - Not retried
    # =========================================================================
    print("\n" + "-" * 70)
    print("Client Errors (4xx) - Not Retried")
    print("-" * 70)

    error_codes = [400, 401, 403, 404, 422, 429]

    for code in error_codes:
        response = client.call("httpbin.status", code)
        print(f"  {code}: ok={response.ok}, status={response.status_code}")

    # =========================================================================
    # Server Errors (5xx) - Would be retried
    # =========================================================================
    print("\n" + "-" * 70)
    print("Server Errors (5xx)")
    print("-" * 70)
    print("(Note: httpbin.org returns immediate 5xx, so retries won't help)")

    # Create client with minimal retries for faster demo
    from kstlib.limits import RapiLimits

    client._limits = RapiLimits(
        timeout=10.0,
        max_response_size=10_000_000,
        max_retries=1,  # Only 1 retry
        retry_delay=0.1,
        retry_backoff=1.5,
    )

    server_codes = [500, 502, 503, 504]

    for code in server_codes:
        start = time.time()
        response = client.call("httpbin.status", code)
        elapsed = time.time() - start
        print(f"  {code}: ok={response.ok}, elapsed={elapsed:.2f}s")


def demo_timeout_handling() -> None:
    """Demonstrate timeout handling."""
    print("\n" + "=" * 70)
    print("TIMEOUT HANDLING")
    print("=" * 70)

    config_manager = create_config()

    # Create client with short timeout
    from kstlib.limits import RapiLimits

    client = RapiClient(config_manager=config_manager)
    client._limits = RapiLimits(
        timeout=2.0,  # 2 second timeout
        max_response_size=10_000_000,
        max_retries=1,
        retry_delay=0.1,
        retry_backoff=1.0,
    )

    print("\n" + "-" * 70)
    print("Request within timeout (1s delay, 2s timeout)")
    print("-" * 70)

    response = client.call("httpbin.delay", 1)
    print(f"Status: {response.status_code}")
    print(f"Elapsed: {response.elapsed:.2f}s")

    print("\n" + "-" * 70)
    print("Request exceeding timeout (5s delay, 2s timeout)")
    print("-" * 70)

    try:
        start = time.time()
        response = client.call("httpbin.delay", 5)
        print(f"Unexpected success: {response.status_code}")
    except RequestError as e:
        elapsed = time.time() - start
        print(f"RequestError caught: {e}")
        print(f"Total elapsed (with retry): {elapsed:.2f}s")


def demo_endpoint_resolution_errors() -> None:
    """Demonstrate endpoint resolution error handling."""
    print("\n" + "=" * 70)
    print("ENDPOINT RESOLUTION ERRORS")
    print("=" * 70)

    config_manager = create_config()
    client = RapiClient(config_manager=config_manager)

    # =========================================================================
    # Unknown endpoint
    # =========================================================================
    print("\n" + "-" * 70)
    print("Unknown Endpoint")
    print("-" * 70)

    try:
        client.call("httpbin.nonexistent_endpoint")
    except EndpointNotFoundError as e:
        print(f"EndpointNotFoundError: {e}")
        print(f"  endpoint_ref: {e.endpoint_ref}")
        print(f"  searched_apis: {e.searched_apis}")

    # =========================================================================
    # Unknown API
    # =========================================================================
    print("\n" + "-" * 70)
    print("Unknown API")
    print("-" * 70)

    try:
        client.call("unknown_api.some_endpoint")
    except EndpointNotFoundError as e:
        print(f"EndpointNotFoundError: {e}")
        print(f"  endpoint_ref: {e.endpoint_ref}")


def demo_response_checking() -> None:
    """Demonstrate response status checking patterns."""
    print("\n" + "=" * 70)
    print("RESPONSE STATUS CHECKING PATTERNS")
    print("=" * 70)

    config_manager = create_config()
    client = RapiClient(config_manager=config_manager)

    print("\n" + "-" * 70)
    print("Pattern 1: Using response.ok")
    print("-" * 70)

    response = client.call("httpbin.status", 200)
    if response.ok:
        print("Success! Processing response...")
    else:
        print(f"Request failed with status {response.status_code}")

    response = client.call("httpbin.status", 404)
    if response.ok:
        print("Success! Processing response...")
    else:
        print(f"Request failed with status {response.status_code}")

    print("\n" + "-" * 70)
    print("Pattern 2: Checking specific status codes")
    print("-" * 70)

    response = client.call("httpbin.status", 201)

    if response.status_code == 200:
        print("OK - Resource retrieved")
    elif response.status_code == 201:
        print("Created - New resource created")
    elif response.status_code == 204:
        print("No Content - Operation successful, no body")
    elif response.status_code == 404:
        print("Not Found - Resource doesn't exist")
    elif response.status_code >= 500:
        print("Server Error - Retry later")

    print("\n" + "-" * 70)
    print("Pattern 3: Handling with try/except")
    print("-" * 70)

    def safe_api_call(endpoint: str, *args: object) -> dict[str, Any] | None:
        """Make API call with error handling."""
        try:
            response = client.call(endpoint, *args)
            if response.ok:
                return response.data  # type: ignore[no-any-return]
            print(f"API error: {response.status_code}")
            return None
        except RequestError as e:
            print(f"Request failed: {e}")
            return None
        except EndpointNotFoundError as e:
            print(f"Endpoint not found: {e}")
            return None

    # Test the pattern
    result = safe_api_call("httpbin.uuid")
    if result:
        print(f"Got UUID: {result.get('uuid')}")

    result = safe_api_call("httpbin.status", 500)
    if result is None:
        print("Handled 500 error gracefully")


if __name__ == "__main__":
    demo_http_errors()
    demo_timeout_handling()
    demo_endpoint_resolution_errors()
    demo_response_checking()

    print("\n" + "=" * 70)
    print("All error handling examples completed!")
    print("=" * 70)
