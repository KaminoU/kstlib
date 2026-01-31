"""
Environment Variable Configuration
===================================

This example demonstrates loading configuration from a path specified
in an environment variable, which is useful for containerized applications
and different deployment environments.

Features covered:
- Loading config from environment variable using `ConfigLoader.from_env()`
- Custom environment variable names
- Error handling for missing environment variables

This example uses the recommended `ConfigLoader.from_env()` factory method.
"""

import os
from pathlib import Path

from kstlib.config import ConfigFileNotFoundError, ConfigLoader


def main() -> None:
    """Load configuration from environment variable."""
    print("=" * 60)
    print("Environment Variable Configuration Example")
    print("=" * 60)

    # Setup: Set environment variable pointing to config file
    example_dir = Path(__file__).parent
    config_file = example_dir / "configs" / "basic.yml"

    # Method 1: Using default CONFIG_PATH environment variable
    print("\n📍 Method 1: Default CONFIG_PATH variable")
    os.environ["CONFIG_PATH"] = str(config_file)

    try:
        config = ConfigLoader.from_env()
        print("✅ Loaded from CONFIG_PATH")
        print(f"   App Name: {config.app.name}")
        print(f"   Version: {config.app.version}")
    except ValueError as e:
        print(f"❌ Error: {e}")
    finally:
        del os.environ["CONFIG_PATH"]

    # Method 2: Using custom environment variable
    print("\n📍 Method 2: Custom MYAPP_CONFIG variable")
    os.environ["MYAPP_CONFIG"] = str(config_file)

    try:
        config = ConfigLoader.from_env("MYAPP_CONFIG")
        print("✅ Loaded from MYAPP_CONFIG")
        print(f"   App Name: {config.app.name}")
        print(f"   Database: {config.database.name}")
    except ValueError as e:
        print(f"❌ Error: {e}")
    finally:
        del os.environ["MYAPP_CONFIG"]

    # Method 3: Error handling for missing environment variable
    print("\n📍 Method 3: Error handling")
    try:
        config = ConfigLoader.from_env("NONEXISTENT_VAR")
    except ValueError as e:
        print(f"✅ Caught expected error: {e}")

    # Method 4: Error handling for invalid path
    print("\n📍 Method 4: Invalid path in environment variable")
    os.environ["CONFIG_PATH"] = "/nonexistent/config.yml"

    try:
        config = ConfigLoader.from_env()
    except ConfigFileNotFoundError:
        print("✅ Caught expected error: Config file not found")
    finally:
        del os.environ["CONFIG_PATH"]

    print("\n" + "=" * 60)
    print("💡 Tip: Use environment variables for Docker/K8s deployments")
    print("=" * 60)


if __name__ == "__main__":
    main()
