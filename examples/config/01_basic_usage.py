"""
Basic Configuration Loading
============================

This example highlights the two most direct ways to read configuration with
kstlib's modern API.

Features covered:
- Instant cascading load with ``ConfigLoader()``
- File-specific load via ``ConfigLoader.from_file()`` and ``load_from_file()``
- Accessing configuration values through Box dot notation
"""
# pylint: disable=invalid-name
# Reason: Example files use numbered naming convention (01_basic_usage.py)

from pathlib import Path

from kstlib.config import ConfigLoader, load_from_file

# Define the example config file path
example_dir = Path(__file__).parent
config_file = example_dir / "configs" / "basic.yml"


def main() -> None:
    """Load and display basic configuration."""
    print("=" * 60)
    print("Basic Configuration Loading Example")
    print("=" * 60)

    print("\nCascading quickstart (package defaults):")
    cascading_config = ConfigLoader().config
    print(f"Default log output: {cascading_config.logger.defaults.output}")
    print(f"Default TTL seconds: {cascading_config.cache.ttl.default_seconds}")

    # Load configuration from a specific file using the modern class-based API
    config = ConfigLoader.from_file(config_file)

    # Access top-level properties
    print(f"\nApplication Name: {config.app.name}")
    print(f"Version: {config.app.version}")
    print(f"Debug Mode: {config.app.debug}")

    # Access nested properties using dot notation
    print(f"\nDatabase Host: {config.database.host}")
    print(f"Database Port: {config.database.port}")
    print(f"Database Name: {config.database.name}")

    # Access list items
    print(f"\nAllowed Hosts: {', '.join(config.app.allowed_hosts)}")

    print("\nFunctional shortcut (load_from_file):")
    config_via_function = load_from_file(config_file)
    print(f"App Name via function: {config_via_function.app.name}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
