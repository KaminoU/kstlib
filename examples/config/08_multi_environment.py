"""
Multi-Environment Configuration Pattern
========================================

This example demonstrates a real-world pattern for managing configurations
across multiple environments (development, staging, production).

Features covered:
- Multiple independent ConfigLoader instances
- Environment-specific configuration loading
- Configuration validation per environment
- Practical patterns for production use

Use case:
- Load different configs based on environment
- Strict validation in production, lenient in development
- Independent configuration instances to avoid side effects
"""
# pylint: disable=invalid-name
# Reason: Example files use numbered naming convention (08_multi_environment.py)

import os
from pathlib import Path

from kstlib.config import ConfigLoader


def main() -> None:
    """Demonstrate multi-environment configuration pattern."""
    print("=" * 70)
    print("Multi-Environment Configuration Pattern")
    print("=" * 70)

    example_dir = Path(__file__).parent
    configs_dir = example_dir / "configs"

    # =======================================================================
    # Pattern 1: Environment-Specific Loaders
    # =======================================================================
    print("\n📦 Pattern 1: Environment-Specific Configuration Loaders")
    print("-" * 70)

    # Development: Lenient, allows mixed formats
    print("\n🔧 Development Environment:")
    dev_loader = ConfigLoader(strict_format=False, encoding="utf-8")
    dev_config = dev_loader.load_from_file(configs_dir / "basic.yml")
    print(f"   App Name: {dev_config.app.name}")
    print(f"   Debug Mode: {dev_config.app.debug}")
    print("   Environment: Development (strict_format=False)")

    # Production: Strict, enforces format consistency
    print("\n🚀 Production Environment:")
    prod_loader = ConfigLoader(strict_format=True, encoding="utf-8")
    prod_config = prod_loader.load_from_file(configs_dir / "basic.yml")
    print(f"   App Name: {prod_config.app.name}")
    print(f"   Debug Mode: {prod_config.app.debug}")
    print("   Environment: Production (strict_format=True)")

    # =======================================================================
    # Pattern 2: Factory Methods for Quick Setup
    # =======================================================================
    print("\n\n📦 Pattern 2: Factory Methods (One-Liner Convenience)")
    print("-" * 70)

    # Quick config loading with factory method
    config = ConfigLoader.from_file(configs_dir / "basic.yml")
    print("\n✅ Loaded with ConfigLoader.from_file():")
    print(f"   Database: {config.database.host}:{config.database.port}")
    print(f"   Database Name: {config.database.name}")

    # =======================================================================
    # Pattern 3: Environment Variable Based Loading
    # =======================================================================
    print("\n\n📦 Pattern 3: Environment Variable Configuration")
    print("-" * 70)

    # Simulate environment variable
    config_path = str(configs_dir / "basic.yml")
    os.environ["APP_CONFIG"] = config_path

    print("\n🌍 Loading from environment variable 'APP_CONFIG':")
    print(f"   APP_CONFIG={config_path}")

    env_config = ConfigLoader.from_env("APP_CONFIG")
    print(f"   ✅ Loaded: {env_config.app.name} v{env_config.app.version}")

    # Cleanup
    del os.environ["APP_CONFIG"]

    # =======================================================================
    # Pattern 4: Cascading Configuration (Multi-Location Search)
    # =======================================================================
    print("\n\n📦 Pattern 4: Cascading Configuration Search")
    print("-" * 70)

    print("\n🔍 Search locations (priority from lowest to highest):")
    print("   1. Package default config")
    print("   2. User config dir (~/.config/)")
    print("   3. User home directory (~)")
    print("   4. Current working directory (highest priority)")

    # Note: This would search multiple locations in real usage
    print("\n   Using ConfigLoader.from_cascading() for automatic discovery")
    print("   (Would merge configs from all found locations)")

    # =======================================================================
    # Pattern 5: Multiple Independent Instances
    # =======================================================================
    print("\n\n📦 Pattern 5: Independent Configuration Instances")
    print("-" * 70)

    # Create two completely independent loaders
    loader_a = ConfigLoader()
    loader_b = ConfigLoader()

    config_a = loader_a.load_from_file(configs_dir / "basic.yml")
    config_b = loader_b.load_from_file(configs_dir / "basic.yml")

    print("\n✅ Two independent instances created:")
    print(f"   Config A: {config_a.app.name}")
    print(f"   Config B: {config_b.app.name}")
    print(f"   Same content: {config_a.app.name == config_b.app.name}")
    print(f"   Different objects: {config_a is not config_b}")

    # =======================================================================
    # Pattern 6: Reusable Loader with Consistent Settings
    # =======================================================================
    print("\n\n📦 Pattern 6: Reusable Loader Pattern")
    print("-" * 70)

    # Create a loader with specific settings, reuse for multiple files
    strict_loader = ConfigLoader(strict_format=True, encoding="utf-8")

    print("\n🔧 Loading multiple configs with same loader:")
    config1 = strict_loader.load_from_file(configs_dir / "basic.yml")
    print(f"   ✅ Config 1: {config1.app.name}")

    config2 = strict_loader.load_from_file(configs_dir / "merge_base.yml")
    print(f"   ✅ Config 2: {config2.app.name} (cache backend: {config2.cache.backend.host})")

    print("\n   Both loaded with strict_format=True enforcement")

    # =======================================================================
    # Summary
    # =======================================================================
    print("\n\n" + "=" * 70)
    print("✨ Summary: When to Use Each Pattern")
    print("=" * 70)
    print("""
🎯 Pattern 1 (Environment-Specific Loaders):
   → Use when you need different validation rules per environment
   → Example: Strict in prod, lenient in dev

🎯 Pattern 2 (Factory Methods):
   → Use for quick one-off config loading
   → Example: Simple scripts, small applications

🎯 Pattern 3 (Environment Variables):
   → Use in containerized/cloud environments
   → Example: Docker, Kubernetes, 12-factor apps

🎯 Pattern 4 (Cascading Search):
   → Use for user-overridable defaults
   → Example: CLI tools, desktop applications

🎯 Pattern 5 (Independent Instances):
   → Use when testing or managing multiple configs
   → Example: Unit tests, multi-tenant applications

🎯 Pattern 6 (Reusable Loader):
   → Use when loading many files with same settings
   → Example: Batch processing, migration scripts
""")

    print("\n💡 Comparison: Class-based vs Functional API")
    print("-" * 70)
    print("""
🆕 New (Recommended for new projects):
   from kstlib.config import ConfigLoader
   config = ConfigLoader.from_file('config.yml')

🔙 Old (Still supported, backward compatible):
   from kstlib.config import load_from_file
   config = load_from_file('config.yml')

Both APIs work! Choose based on your needs:
   • New projects → ConfigLoader (more flexible)
   • Legacy code → Functional API (simpler)
   • Testing → ConfigLoader (better isolation)
""")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
