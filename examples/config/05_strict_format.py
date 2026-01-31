"""
Strict Format Mode
==================

This example demonstrates the strict_format mode, which enforces that
all included files must have the same format as the parent file.

Features covered:
- Strict format enforcement using `ConfigLoader`
- Format validation across includes
- Error handling for format mismatches

This example uses `ConfigLoader.from_file(path, strict_format=True)`.
"""

from pathlib import Path

from kstlib.config import ConfigFormatError, ConfigLoader


def main() -> None:
    """Demonstrate strict format mode."""
    print("=" * 60)
    print("Strict Format Mode Example")
    print("=" * 60)

    example_dir = Path(__file__).parent

    # Example 1: Normal mode (mixed formats allowed)
    print("\n📦 Example 1: Normal Mode (mixed formats OK)")
    print("-" * 60)

    mixed_config = example_dir / "configs" / "with_includes.yml"
    try:
        # strict_format=False is the default
        config = ConfigLoader.from_file(mixed_config, strict_format=False)
        print("✅ Loaded successfully with mixed formats")
        print("   YAML + TOML + JSON + INI merged")
        print(f"   App: {config.app.name}")
        print(f"   Database: {config.database.name}")
    except ConfigFormatError as e:
        print(f"❌ Error: {e}")

    # Example 2: Strict mode with matching formats
    print("\n📦 Example 2: Strict Mode (YAML only)")
    print("-" * 60)

    yaml_only_config = example_dir / "configs" / "strict_yaml.yml"
    try:
        config = ConfigLoader.from_file(yaml_only_config, strict_format=True)
        print("✅ Loaded successfully (all YAML)")
        print(f"   Base: {config.base.value}")
        print(f"   Extended: {config.extended.value}")
    except ConfigFormatError as e:
        print(f"❌ Error: {e}")

    # Example 3: Strict mode with format mismatch (will fail)
    print("\n📦 Example 3: Strict Mode with Mismatch")
    print("-" * 60)

    try:
        # This will fail because with_includes.yml includes non-YAML files
        config = ConfigLoader.from_file(mixed_config, strict_format=True)
        print("✅ Loaded successfully")
    except ConfigFormatError as e:
        print("✅ Caught expected format mismatch error:")
        print(f"   {e}")

    print("\n" + "=" * 60)
    print("💡 Use strict_format=True for:")
    print("   - Enforcing config style consistency")
    print("   - Preventing accidental mixed formats")
    print("   - Simplifying config management in large projects")
    print("=" * 60)


if __name__ == "__main__":
    main()
