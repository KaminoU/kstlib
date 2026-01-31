#!/usr/bin/env python3
"""
Run All Configuration Examples
===============================

This script runs all configuration examples in sequence,
providing a comprehensive demonstration of kstlib's config module features.
"""
# pylint: disable=broad-exception-caught,import-outside-toplevel
# Reason: Catch all exceptions to report example failures gracefully
# Reason: Import inside function to load examples dynamically

import sys
from pathlib import Path

# Add parent directory to path to import examples
example_dir = Path(__file__).parent
sys.path.insert(0, str(example_dir))


def run_example(example_name: str, module_path: Path) -> bool:
    """
    Run a single example and report results.

    Args:
        example_name: Display name of the example
        module_path: Path to the example module

    Returns:
        True if example ran successfully, False otherwise
    """
    print("\n" + "=" * 70)
    print(f"🚀 Running: {example_name}")
    print("=" * 70)

    try:
        # Import and run the example
        import importlib.util

        spec = importlib.util.spec_from_file_location("example", module_path)
        if spec is None:
            raise ImportError(f"Could not load spec for {module_path}")

        if spec.loader is None:
            raise ImportError(f"Spec has no loader for {module_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if hasattr(module, "main"):
            module.main()

        print(f"\n✅ {example_name} completed successfully!")
        return True

    except Exception as e:
        print(f"\n❌ {example_name} failed with error:")
        print(f"   {type(e).__name__}: {e}")
        return False


def main() -> int:
    """Run all configuration examples."""
    examples = [
        ("01. Basic Usage", "01_basic_usage.py"),
        ("02. Configuration with Includes", "02_includes.py"),
        ("03. Cascading Search", "03_cascading_search.py"),
        ("04. Environment Variables", "04_env_variable.py"),
        ("05. Strict Format Mode", "05_strict_format.py"),
        ("06. Error Handling", "06_error_handling.py"),
        ("07. Deep Merge", "07_deep_merge.py"),
        ("08. Multi-Environment Pattern", "08_multi_environment.py"),
        ("09. Auto-Discovery Presets", "09_auto_discovery.py"),
    ]

    print("=" * 70)
    print("🎯 KSTLIB Configuration Module - All Examples")
    print("=" * 70)
    print(f"\nTotal examples to run: {len(examples)}")

    results = []
    for name, filename in examples:
        module_path = example_dir / filename
        if not module_path.exists():
            print(f"\n⚠️  Skipping {name}: File not found")
            results.append(False)
            continue

        success = run_example(name, module_path)
        results.append(success)

    # Summary
    print("\n" + "=" * 70)
    print("📊 SUMMARY")
    print("=" * 70)

    passed = sum(results)
    failed = len(results) - passed

    print(f"\n✅ Passed: {passed}/{len(examples)}")
    print(f"❌ Failed: {failed}/{len(examples)}")

    if failed == 0:
        print("\n🎉 All examples completed successfully!")
        return 0
    else:
        print(f"\n⚠️  {failed} example(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
