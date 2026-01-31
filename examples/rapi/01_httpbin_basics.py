#!/usr/bin/env python3
"""Demonstrate basic RAPI usage with httpbin.org.

This example shows how to use the RapiClient to make HTTP requests
to a config-driven API using httpbin.org as a test server.

httpbin.org is a simple HTTP Request & Response Service that echoes
back request data, making it perfect for testing HTTP clients.

Each example shows both Python API and CLI equivalent.

Usage:
    python examples/rapi/01_httpbin_basics.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from kstlib.rapi import RapiClient, RapiConfigManager


def create_httpbin_config() -> RapiConfigManager:
    """Create a config manager with httpbin.org endpoints."""
    config = {
        "api": {
            "httpbin": {
                "base_url": "https://httpbin.org",
                "endpoints": {
                    # Simple GET - returns origin IP
                    "get_ip": {
                        "path": "/ip",
                    },
                    # GET with query parameters
                    "get_args": {
                        "path": "/get",
                    },
                    # POST with JSON body
                    "post_data": {
                        "path": "/post",
                        "method": "POST",
                    },
                    # PUT request
                    "put_data": {
                        "path": "/put",
                        "method": "PUT",
                    },
                    # DELETE request
                    "delete_data": {
                        "path": "/delete",
                        "method": "DELETE",
                    },
                    # Path parameter: /delay/{seconds}
                    "delay": {
                        "path": "/delay/{seconds}",
                    },
                    # Status codes: /status/{code}
                    "status": {
                        "path": "/status/{code}",
                    },
                    # Echo headers
                    "headers": {
                        "path": "/headers",
                    },
                    # User-Agent
                    "user_agent": {
                        "path": "/user-agent",
                    },
                    # UUID generation
                    "uuid": {
                        "path": "/uuid",
                    },
                },
            }
        }
    }
    return RapiConfigManager(config)


def main() -> None:
    """Run httpbin.org examples."""
    print("=" * 70)
    print("RAPI MODULE - httpbin.org Examples (Python + CLI)")
    print("=" * 70)

    # Create client with httpbin config
    config_manager = create_httpbin_config()
    client = RapiClient(config_manager=config_manager)

    # =========================================================================
    # Example 1: Simple GET request
    # =========================================================================
    print("\n" + "-" * 70)
    print("Example 1: Simple GET - Get IP Address")
    print("-" * 70)
    print("CLI: kstlib rapi call httpbin.get_ip")
    print()

    response = client.call("httpbin.get_ip")
    print(f"Status: {response.status_code}")
    print(f"Data: {response.data}")
    print(f"Elapsed: {response.elapsed:.3f}s")

    # =========================================================================
    # Example 2: GET with query parameters
    # =========================================================================
    print("\n" + "-" * 70)
    print("Example 2: GET with Query Parameters")
    print("-" * 70)
    print("CLI: kstlib rapi call httpbin.get_args foo=bar count=42 active=true")
    print()

    response = client.call("httpbin.get_args", foo="bar", count=42, active=True)
    print(f"Status: {response.status_code}")
    print(f"Args received by server: {response.data.get('args', {})}")

    # =========================================================================
    # Example 3: POST with JSON body
    # =========================================================================
    print("\n" + "-" * 70)
    print("Example 3: POST with JSON Body")
    print("-" * 70)
    print('CLI: kstlib rapi call httpbin.post_data --body \'{"user": "john_doe", "email": "john@example.com"}\'')
    print()

    payload = {
        "user": "john_doe",
        "email": "john@example.com",
        "preferences": {"theme": "dark", "notifications": True},
    }
    response = client.call("httpbin.post_data", body=payload)
    print(f"Status: {response.status_code}")
    print(f"JSON sent: {response.data.get('json', {})}")

    # =========================================================================
    # Example 4: Path parameters
    # =========================================================================
    print("\n" + "-" * 70)
    print("Example 4: Path Parameters - Delayed Response")
    print("-" * 70)

    # Using positional argument
    print("CLI: kstlib rapi call httpbin.delay 1")
    print()
    print("Calling /delay/1 (positional arg)...")
    response = client.call("httpbin.delay", 1)
    print(f"Status: {response.status_code}")
    print(f"Elapsed: {response.elapsed:.3f}s (should be ~1s)")

    # Using keyword argument
    print("\nCLI: kstlib rapi call httpbin.delay seconds=2")
    print()
    print("Calling /delay/2 (keyword arg)...")
    response = client.call("httpbin.delay", seconds=2)
    print(f"Status: {response.status_code}")
    print(f"Elapsed: {response.elapsed:.3f}s (should be ~2s)")

    # =========================================================================
    # Example 5: Custom headers
    # =========================================================================
    print("\n" + "-" * 70)
    print("Example 5: Custom Headers (Runtime Override)")
    print("-" * 70)
    print('CLI: kstlib rapi call httpbin.headers -H "X-Custom-Header: my-value" -H "X-Request-ID: abc-123-xyz"')
    print()

    custom_headers = {
        "X-Custom-Header": "my-value",
        "X-Request-ID": "abc-123-xyz",
    }
    response = client.call("httpbin.headers", headers=custom_headers)
    print(f"Status: {response.status_code}")
    print("Headers received by server:")
    for key, value in response.data.get("headers", {}).items():
        if key.startswith("X-"):
            print(f"  {key}: {value}")

    # =========================================================================
    # Example 6: HTTP Status codes
    # =========================================================================
    print("\n" + "-" * 70)
    print("Example 6: HTTP Status Codes")
    print("-" * 70)
    print("CLI: kstlib rapi call httpbin.status 200")
    print("     kstlib rapi call httpbin.status 404")
    print()

    for code in [200, 201, 204, 400, 404]:
        response = client.call("httpbin.status", code)
        print(f"  /status/{code} -> {response.status_code} (ok={response.ok})")

    # =========================================================================
    # Example 7: UUID generation
    # =========================================================================
    print("\n" + "-" * 70)
    print("Example 7: UUID Generation")
    print("-" * 70)
    print("CLI: kstlib rapi call httpbin.uuid")
    print()

    response = client.call("httpbin.uuid")
    print(f"Generated UUID: {response.data.get('uuid')}")

    # =========================================================================
    # Example 8: Short reference (endpoint name only)
    # =========================================================================
    print("\n" + "-" * 70)
    print("Example 8: Short Reference Resolution")
    print("-" * 70)
    print("CLI: kstlib rapi call get_ip  # Same as httpbin.get_ip")
    print()

    # Since 'get_ip' is unique across all APIs, we can use short reference
    response = client.call("get_ip")  # Same as "httpbin.get_ip"
    print(f"Short reference 'get_ip' resolved to: {response.endpoint_ref}")
    print(f"Data: {response.data}")

    # =========================================================================
    # Example 9: Output formats
    # =========================================================================
    print("\n" + "-" * 70)
    print("Example 9: CLI Output Formats")
    print("-" * 70)
    print("CLI: kstlib rapi call httpbin.get_ip                    # JSON (default)")
    print("     kstlib rapi call httpbin.get_ip --output text      # Raw text")
    print("     kstlib rapi call httpbin.get_ip --output full      # Full metadata")
    print("     kstlib rapi call httpbin.get_ip --quiet            # Quiet mode")
    print()
    print("(See CLI output for demonstration)")

    print("\n" + "=" * 70)
    print("All examples completed successfully!")
    print("=" * 70)


async def async_example() -> None:
    """Demonstrate async API calls."""
    print("\n" + "=" * 70)
    print("ASYNC EXAMPLE")
    print("=" * 70)
    print("Note: CLI does not support async directly, use Python for concurrent calls")
    print()

    config_manager = create_httpbin_config()
    client = RapiClient(config_manager=config_manager)

    # Make concurrent requests
    print("Making 3 concurrent requests...")

    results = await asyncio.gather(
        client.call_async("httpbin.uuid"),
        client.call_async("httpbin.uuid"),
        client.call_async("httpbin.uuid"),
    )

    print("UUIDs generated concurrently:")
    for i, response in enumerate(results, 1):
        print(f"  {i}. {response.data.get('uuid')}")


if __name__ == "__main__":
    main()

    # Run async example
    asyncio.run(async_example())
