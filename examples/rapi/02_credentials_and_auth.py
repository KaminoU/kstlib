#!/usr/bin/env python3
"""Demonstrate RAPI credentials and authentication.

This example shows how to use different credential types:
- Environment variables
- Bearer token authentication
- Basic authentication

Uses httpbin.org authentication endpoints for testing.

Usage:
    # Set environment variable for bearer auth test
    export HTTPBIN_TOKEN="my-test-token"

    python examples/rapi/02_credentials_and_auth.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from kstlib.rapi import CredentialResolver, RapiClient, RapiConfigManager


def demo_credential_resolver() -> None:
    """Demonstrate CredentialResolver with different sources."""
    print("=" * 70)
    print("CREDENTIAL RESOLVER DEMO")
    print("=" * 70)

    # =========================================================================
    # Example 1: Environment variable credentials
    # =========================================================================
    print("\n" + "-" * 70)
    print("Example 1: Environment Variable Credentials")
    print("-" * 70)

    # Set up test environment variable
    os.environ["TEST_API_TOKEN"] = "secret-token-12345"

    cred_config = {
        "test_api": {
            "type": "env",
            "var": "TEST_API_TOKEN",
        }
    }

    resolver = CredentialResolver(cred_config)
    record = resolver.resolve("test_api")

    print(f"Source: {record.source}")
    print(f"Value: {record.value[:10]}... (truncated)")
    print(f"Secret: {record.secret}")

    # =========================================================================
    # Example 2: Key + Secret from environment
    # =========================================================================
    print("\n" + "-" * 70)
    print("Example 2: Key + Secret Pair from Environment")
    print("-" * 70)

    os.environ["API_KEY"] = "my-api-key"
    os.environ["API_SECRET"] = "my-api-secret"

    cred_config = {
        "api_with_secret": {
            "type": "env",
            "var_key": "API_KEY",
            "var_secret": "API_SECRET",
        }
    }

    resolver = CredentialResolver(cred_config)
    record = resolver.resolve("api_with_secret")

    print(f"Source: {record.source}")
    print(f"Key: {record.value}")
    print(f"Secret: {record.secret}")

    # =========================================================================
    # Example 3: jq-like path extraction
    # =========================================================================
    print("\n" + "-" * 70)
    print("Example 3: jq-like Path Extraction")
    print("-" * 70)

    # Create a test JSON file
    import json
    import tempfile

    test_data = {
        "auth": {
            "tokens": [
                {"name": "prod", "value": "prod-token-xyz"},
                {"name": "dev", "value": "dev-token-abc"},
            ]
        },
        "api_key": "root-level-key",
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(test_data, f)
        temp_file = f.name

    try:
        # Extract nested token using jq-like path
        cred_config = {
            "dev_token": {
                "type": "file",
                "path": temp_file,
                "token_path": ".auth.tokens[1].value",
            }
        }

        resolver = CredentialResolver(cred_config)
        record = resolver.resolve("dev_token")

        print("Path: .auth.tokens[1].value")
        print(f"Extracted value: {record.value}")
        print(f"Source: {record.source}")

        # Extract root level key
        cred_config = {
            "root_key": {
                "type": "file",
                "path": temp_file,
                "key_field": "api_key",
            }
        }

        resolver = CredentialResolver(cred_config)
        record = resolver.resolve("root_key")

        print("\nPath: .api_key")
        print(f"Extracted value: {record.value}")

    finally:
        os.unlink(temp_file)

    # Cleanup
    del os.environ["TEST_API_TOKEN"]
    del os.environ["API_KEY"]
    del os.environ["API_SECRET"]


def demo_bearer_auth() -> None:
    """Demonstrate Bearer token authentication with httpbin.org."""
    print("\n" + "=" * 70)
    print("BEARER AUTHENTICATION DEMO")
    print("=" * 70)

    # Set up bearer token
    os.environ["HTTPBIN_BEARER_TOKEN"] = "my-secret-bearer-token"

    try:
        # Config with bearer auth
        rapi_config = {
            "api": {
                "httpbin_auth": {
                    "base_url": "https://httpbin.org",
                    "credentials": "httpbin_bearer",
                    "auth_type": "bearer",
                    "endpoints": {
                        "bearer_test": {
                            "path": "/bearer",
                        },
                        "headers": {
                            "path": "/headers",
                        },
                    },
                }
            }
        }

        cred_config = {
            "httpbin_bearer": {
                "type": "env",
                "var": "HTTPBIN_BEARER_TOKEN",
            }
        }

        config_manager = RapiConfigManager(rapi_config)
        client = RapiClient(
            config_manager=config_manager,
            credentials_config=cred_config,
        )

        print("\n" + "-" * 70)
        print("Testing Bearer Authentication")
        print("-" * 70)

        # Call the bearer endpoint (httpbin validates Bearer token format)
        response = client.call("httpbin_auth.bearer_test")
        print(f"Status: {response.status_code}")
        print(f"Response: {response.data}")

        # Check headers to verify Authorization was sent
        print("\n" + "-" * 70)
        print("Verifying Authorization Header")
        print("-" * 70)

        response = client.call("httpbin_auth.headers")
        auth_header = response.data.get("headers", {}).get("Authorization", "")
        print(f"Authorization header: {auth_header[:30]}... (truncated)")

    finally:
        del os.environ["HTTPBIN_BEARER_TOKEN"]


def demo_basic_auth() -> None:
    """Demonstrate Basic authentication with httpbin.org."""
    print("\n" + "=" * 70)
    print("BASIC AUTHENTICATION DEMO")
    print("=" * 70)

    # Set up basic auth credentials
    os.environ["HTTPBIN_USER"] = "testuser"
    os.environ["HTTPBIN_PASS"] = "testpass123"

    try:
        # Config with basic auth
        rapi_config = {
            "api": {
                "httpbin_basic": {
                    "base_url": "https://httpbin.org",
                    "credentials": "httpbin_basic_creds",
                    "auth_type": "basic",
                    "endpoints": {
                        "basic_test": {
                            # httpbin validates credentials at this endpoint
                            "path": "/basic-auth/testuser/testpass123",
                        },
                        "headers": {
                            "path": "/headers",
                        },
                    },
                }
            }
        }

        cred_config = {
            "httpbin_basic_creds": {
                "type": "env",
                "var_key": "HTTPBIN_USER",
                "var_secret": "HTTPBIN_PASS",
            }
        }

        config_manager = RapiConfigManager(rapi_config)
        client = RapiClient(
            config_manager=config_manager,
            credentials_config=cred_config,
        )

        print("\n" + "-" * 70)
        print("Testing Basic Authentication")
        print("-" * 70)

        # Call the basic-auth endpoint (httpbin validates credentials)
        response = client.call("httpbin_basic.basic_test")
        print(f"Status: {response.status_code}")
        print(f"Authenticated: {response.data.get('authenticated', False)}")
        print(f"User: {response.data.get('user', 'N/A')}")

        # Check headers to verify Authorization was sent
        print("\n" + "-" * 70)
        print("Verifying Authorization Header")
        print("-" * 70)

        response = client.call("httpbin_basic.headers")
        auth_header = response.data.get("headers", {}).get("Authorization", "")
        print(f"Authorization header: {auth_header}")

    finally:
        del os.environ["HTTPBIN_USER"]
        del os.environ["HTTPBIN_PASS"]


def demo_api_key_auth() -> None:
    """Demonstrate API Key authentication."""
    print("\n" + "=" * 70)
    print("API KEY AUTHENTICATION DEMO")
    print("=" * 70)

    os.environ["MY_API_KEY"] = "super-secret-api-key-xyz"

    try:
        # Config with API key auth
        rapi_config = {
            "api": {
                "httpbin_apikey": {
                    "base_url": "https://httpbin.org",
                    "credentials": "my_api_key",
                    "auth_type": "api_key",
                    "endpoints": {
                        "headers": {
                            "path": "/headers",
                        },
                    },
                }
            }
        }

        cred_config = {
            "my_api_key": {
                "type": "env",
                "var": "MY_API_KEY",
            }
        }

        config_manager = RapiConfigManager(rapi_config)
        client = RapiClient(
            config_manager=config_manager,
            credentials_config=cred_config,
        )

        print("\n" + "-" * 70)
        print("Testing API Key Authentication")
        print("-" * 70)

        response = client.call("httpbin_apikey.headers")
        api_key_header = response.data.get("headers", {}).get("X-Api-Key", "")
        print(f"X-API-Key header: {api_key_header}")

    finally:
        del os.environ["MY_API_KEY"]


if __name__ == "__main__":
    demo_credential_resolver()
    demo_bearer_auth()
    demo_basic_auth()
    demo_api_key_auth()

    print("\n" + "=" * 70)
    print("All authentication examples completed!")
    print("=" * 70)
