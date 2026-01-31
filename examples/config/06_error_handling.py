"""
Error Handling
==============

This example demonstrates comprehensive error handling for various
configuration loading scenarios using the modern `ConfigLoader` API.

Features covered:
- ConfigFileNotFoundError handling
- ConfigFormatError handling
- ConfigCircularIncludeError handling
- Best practices for error handling

Note: Error handling works identically with both functional and class APIs,
but this example is updated to use the `ConfigLoader` for consistency.
"""

from pathlib import Path

from kstlib.config import (
    ConfigCircularIncludeError,
    ConfigFileNotFoundError,
    ConfigFormatError,
    ConfigLoader,
    KstlibError,
)


def example_file_not_found() -> None:
    """Demonstrate handling of missing config files."""
    print("\n📍 Example 1: File Not Found")
    print("-" * 60)

    try:
        _config = ConfigLoader.from_file("/nonexistent/config.yml")
    except ConfigFileNotFoundError as e:
        print("✅ Caught ConfigFileNotFoundError:")
        print(f"   {e}")


def example_unsupported_format() -> None:
    """Demonstrate handling of unsupported file formats."""
    print("\n📍 Example 2: Unsupported Format")
    print("-" * 60)

    example_dir = Path(__file__).parent
    bad_config = example_dir / "configs" / "bad_format.xml"

    # Create a dummy XML file
    bad_config.parent.mkdir(exist_ok=True)
    if not bad_config.exists():
        bad_config.write_text("<config><app>test</app></config>")

    try:
        _config = ConfigLoader.from_file(bad_config)
    except ConfigFormatError as e:
        print("✅ Caught ConfigFormatError:")
        print(f"   {e}")
    finally:
        if bad_config.exists():
            bad_config.unlink()


def example_circular_include() -> None:
    """Demonstrate handling of circular includes."""
    print("\n📍 Example 3: Circular Include")
    print("-" * 60)

    example_dir = Path(__file__).parent
    circular1 = example_dir / "configs" / "circular1.yml"
    circular2 = example_dir / "configs" / "circular2.yml"

    # Create circular reference configs
    circular1.write_text("include: circular2.yml\nkey1: value1")
    circular2.write_text("include: circular1.yml\nkey2: value2")

    try:
        _config = ConfigLoader.from_file(circular1)
    except ConfigCircularIncludeError as e:
        print("✅ Caught ConfigCircularIncludeError:")
        print(f"   {e}")
    finally:
        circular1.unlink()
        circular2.unlink()


def example_catch_all() -> None:
    """Demonstrate catching all kstlib errors."""
    print("\n📍 Example 4: Catch All KstlibError")
    print("-" * 60)

    try:
        _config = ConfigLoader.from_file("/nonexistent/config.yml")
    except KstlibError as e:
        print("✅ Caught generic KstlibError:")
        print(f"   Type: {type(e).__name__}")
        print(f"   Message: {e}")


def main() -> None:
    """Run all error handling examples."""
    print("=" * 60)
    print("Error Handling Examples")
    print("=" * 60)

    example_file_not_found()
    example_unsupported_format()
    example_circular_include()
    example_catch_all()

    print("\n" + "=" * 60)
    print("💡 Best Practice: Use specific exceptions for precise handling")
    print("   or catch KstlibError to handle all kstlib errors")
    print("=" * 60)


if __name__ == "__main__":
    main()
