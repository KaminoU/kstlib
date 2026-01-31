"""
Deep Merge Demonstration
=========================

This example demonstrates how kstlib's deep merge works when combining
configurations from multiple sources.

Features covered:
- Deep merging of nested dictionaries
- List handling in merges
- Override priorities

This example uses the recommended `ConfigLoader.from_file()` factory method.
"""

from pathlib import Path

from kstlib.config import ConfigLoader


def main() -> None:
    """Demonstrate deep merge behavior."""
    print("=" * 60)
    print("Deep Merge Demonstration")
    print("=" * 60)

    example_dir = Path(__file__).parent

    # Load config with deep merge
    config_file = example_dir / "configs" / "merge_demo.yml"
    config = ConfigLoader.from_file(config_file)

    print("\n📦 Deep Merge Result:")
    print("-" * 60)

    # Show how nested dictionaries are merged
    print("\nDatabase configuration (merged from multiple sources):")
    print(f"  Host: {config.database.host}")
    print(f"  Port: {config.database.port}")
    print(f"  Pool Size: {config.database.pool_size}")
    print(f"  Timeout: {config.database.timeout}")
    print(f"  SSL Mode: {config.database.ssl_mode}")

    # Show override behavior
    print("\nOverride demonstration:")
    print(f"  App Name (final): {config.app.name}")
    print(f"  Debug (overridden): {config.app.debug}")

    # Show list handling
    print("\nList handling:")
    print(f"  Allowed Hosts: {config.app.allowed_hosts}")

    # Show nested object merge
    print("\nNested merge example:")
    print(f"  Cache Type: {config.cache.type}")
    print(f"  Cache TTL: {config.cache.ttl}")
    print(f"  Cache Backend Host: {config.cache.backend.host}")
    print(f"  Cache Backend Port: {config.cache.backend.port}")

    print("\n" + "=" * 60)
    print("💡 Merge Rules:")
    print("   - Nested dicts are recursively merged")
    print("   - Lists are replaced (not merged)")
    print("   - Later values override earlier ones")
    print("   - Last config file has highest priority")
    print("=" * 60)


if __name__ == "__main__":
    main()
