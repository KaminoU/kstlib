"""
Cascading Configuration Search
===============================

This example demonstrates the cascading configuration search feature,
where kstlib searches for config files in multiple locations and merges them.

Search order (highest priority first):
1. Current working directory
2. User's home directory
3. User's config directory (~/.config)
4. Package default config

Features covered:
- Cascading configuration search using `ConfigLoader.from_cascading()`
- Automatic discovery of config files
- Priority-based merging

This example uses the recommended `ConfigLoader.from_cascading()` factory method.
"""

from pathlib import Path

from kstlib.config import ConfigLoader


def demonstrate_cascading() -> None:
    """Demonstrate cascading config search."""
    print("=" * 60)
    print("Cascading Configuration Search Example")
    print("=" * 60)

    # Create a temporary config in current directory for demonstration
    # This file will have the highest priority in the cascading search
    example_dir = Path(__file__).parent
    temp_config_name = "kstlib.cascading.yml"
    temp_config = example_dir / temp_config_name

    temp_config.write_text("""
app:
  name: "Cascading Demo"
  version: "1.0.0"

demo:
  message: "Loaded from cascading search!"
  location: "current directory"
""")

    try:
        # Load config using cascading search for a specific filename
        config = ConfigLoader.from_cascading(temp_config_name)

        print("\n✅ Configuration loaded successfully!")
        if hasattr(config, "app") and config.app and hasattr(config.app, "name"):
            print(f"   App Name: {config.app.name}")
        if hasattr(config, "demo") and config.demo and hasattr(config.demo, "message"):
            print(f"   Demo Message: {config.demo.message}")
            print(f"   Location: {config.demo.location}")

    finally:
        # Cleanup the temporary file
        if temp_config.exists():
            temp_config.unlink()

    print("\n" + "=" * 60)


def main() -> None:
    """Run the cascading configuration demo."""
    demonstrate_cascading()


if __name__ == "__main__":
    main()
