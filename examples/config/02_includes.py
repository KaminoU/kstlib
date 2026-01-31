"""
Configuration with Includes
============================

This example demonstrates how to use the 'include' feature to compose
configuration from multiple files in different formats (YAML, TOML, JSON, INI).

Features covered:
- Including other config files using the 'include' key
- Multi-format support (YAML, TOML, JSON, INI)
- Deep merge of configurations
- Overriding included values

This example uses the recommended `ConfigLoader.from_file()` factory method.
"""
# pylint: disable=invalid-name
# Reason: Example files use numbered naming convention (02_includes.py)

from pathlib import Path

from kstlib.config import ConfigLoader

# Define the example config file path
example_dir = Path(__file__).parent
config_file = example_dir / "configs" / "with_includes.yml"


def main() -> None:
    """Load configuration with includes and display merged result."""
    print("=" * 60)
    print("Configuration with Includes Example")
    print("=" * 60)

    # Load main config that includes other files
    config = ConfigLoader.from_file(config_file)

    print("\n📦 Merged Configuration:")
    print("-" * 60)

    # Values from main YAML file
    print("\nFrom main YAML:")
    print(f"  App Name: {config.app.name}")
    print(f"  Environment: {config.app.environment}")

    # Values from included TOML file (database.toml)
    print("\nFrom included TOML (database.toml):")
    print(f"  DB Host: {config.database.host}")
    print(f"  DB Port: {config.database.port}")
    print(f"  DB Name: {config.database.name}")

    # Values from included JSON file (features.json)
    print("\nFrom included JSON (features.json):")
    print(f"  Feature Flags: {dict(config.features)}")

    # Values from included INI file (server.ini)
    print("\nFrom included INI (server.ini):")
    print(f"  Server Host: {config.server.host}")
    print(f"  Server Port: {config.server.port}")

    # Override demonstration
    print("\n🔄 Override example:")
    print(f"  Debug (overridden in main): {config.app.debug}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
