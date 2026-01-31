"""
Auto-Discovery Configuration Workflows
======================================

Showcase dedicated ``AutoDiscoveryConfig`` presets that drive ``ConfigLoader``
without legacy keyword arguments.

Features covered:
- Building dataclass presets for file, environment, and manual workflows
- Hydrating configurations automatically via the ``auto`` parameter
- Reusing presets to keep discovery policies consistent across services
"""
# pylint: disable=invalid-name
# Reason: Example files use numbered naming convention (09_auto_discovery.py)

from __future__ import annotations

import os
from pathlib import Path

from kstlib.config import CONFIG_FILENAME, ConfigLoader
from kstlib.config.loader import AutoDiscoveryConfig


def build_file_auto(path: Path) -> AutoDiscoveryConfig:
    """Return a preset that always loads the provided file.

    Args:
        path: Configuration file path.

    Returns:
        AutoDiscoveryConfig: Dataclass configured for ``source="file"``.

    Example:
        >>> build_file_auto(Path("config.yml"))
    """
    return AutoDiscoveryConfig(
        enabled=True,
        source="file",
        filename=path.name,
        env_var="CONFIG_PATH",
        path=path.resolve(),
    )


def build_env_auto(variable: str, *, filename: str = CONFIG_FILENAME) -> AutoDiscoveryConfig:
    """Return a preset that consumes the given environment variable.

    Args:
        variable: Environment variable containing the config path.
        filename: Fallback filename when the variable is missing.

    Returns:
        AutoDiscoveryConfig: Dataclass configured for ``source="env"``.

    Example:
        >>> build_env_auto("MY_APP_CONFIG")
    """
    return AutoDiscoveryConfig(
        enabled=True,
        source="env",
        filename=filename,
        env_var=variable,
        path=None,
    )


def build_manual_auto() -> AutoDiscoveryConfig:
    """Return a preset that defers IO until ``load_from_file`` is called.

    Returns:
        AutoDiscoveryConfig: Dataclass with ``enabled`` set to False.

    Example:
        >>> build_manual_auto()
    """
    return AutoDiscoveryConfig(
        enabled=False,
        source="cascading",
        filename=CONFIG_FILENAME,
        env_var="CONFIG_PATH",
        path=None,
    )


def main() -> None:
    """Demonstrate three auto-discovery presets."""
    print("=" * 70)
    print("Auto-Discovery Configuration Workflows")
    print("=" * 70)

    example_dir = Path(__file__).parent
    configs_dir = example_dir / "configs"
    config_path = configs_dir / "basic.yml"

    # -------------------------------------------------------------------
    # 1) File-bound preset
    # -------------------------------------------------------------------
    print("\n📁 File-bound preset")
    file_auto = build_file_auto(config_path)
    file_config = ConfigLoader(auto=file_auto).config
    print(f"File preset loaded: {config_path}")
    print(f"Application: {file_config.app.name} v{file_config.app.version}")

    # -------------------------------------------------------------------
    # 2) Environment-driven preset
    # -------------------------------------------------------------------
    print("\n🌍 Environment variable preset")
    env_var = "APP_CONFIG_AUTO_DISCOVERY"
    os.environ[env_var] = str(config_path)
    env_auto = build_env_auto(env_var)
    env_config = ConfigLoader(auto=env_auto).config
    print(f"Environment variable {env_var} resolved to: {config_path}")
    print(f"Database host: {env_config.database.host}")
    del os.environ[env_var]

    # -------------------------------------------------------------------
    # 3) Manual preset that opts out of auto-loading
    # -------------------------------------------------------------------
    print("\n⏸ Manual control preset")
    manual_auto = build_manual_auto()
    manual_loader = ConfigLoader(auto=manual_auto)
    config_manual = manual_loader.load_from_file(config_path)
    print("Auto-loading disabled. Manual load succeeded:")
    print(f"Allowed hosts: {', '.join(config_manual.app.allowed_hosts)}")

    print("\n" + "=" * 70)
    print("Presets can be serialized or shipped across services to centralize")
    print("discovery policies while keeping the loading code minimal.")
    print("=" * 70)


if __name__ == "__main__":
    main()
