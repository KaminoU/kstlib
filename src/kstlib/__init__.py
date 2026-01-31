"""
##################################################################################################    ###    ###    ####
##################################################################################################    ###    ###    ####
##                                                                                                                    ##
##             ##################   .#######:     .######.     ##########################################             ##
##             ##################..#########.   .#########.    ##########################################             ##
##             ###           ########.         :###########:                                          ###             ##
##             ###           ######.           .##########:.                                          ###             ##
##             ###           ####.            .#########:.                                            ###             ##
##             ###           ##.            .#######                                                  ###             ##
##             ###           "            .######                                                     ###             ##
##             ###                     .:######                                           ###############             ##
##             ###                 .##########:.                .:#######.                ###############             ##
##             ###               :########################################.               ###                         ##
##             ###              :################# L I B ##################:              ###                         ##
##             ###               .########################################.               ###                         ##
##             ###                 :######:.                 ###########.                 ###                         ##
##             ###                                         :######:.                      ###                         ##
##             ###           .                           :######:.           .            ###                         ##
##             ###           ##                       .:######.             ##            ###                         ##
##             ###           ####                .:#########.              ###            ###                         ##
##             ###           ######             :###########:              ###            ###                         ##
##             ###           ########           :###########:              ###            ###                         ##
##             ##################..##########.  ":#########"               ##################                         ##
##             ##################  .#########:   ":######:"                ##################                         ##
##                                                                                                                    ##
###################################################################################################[ Michel TRUONG ]####
########################################################################################################################
kstlib package - PEP 562 lazy loading for fast imports.

All public symbols are loaded lazily on first access.
Import time target: < 100ms (from ~330ms with eager loading).
"""

# pylint: disable=global-statement,import-outside-toplevel,invalid-name

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

# Public API exports (sorted alphabetically)
__all__ = [
    "ConfigCircularIncludeError",
    "ConfigError",
    "ConfigFileNotFoundError",
    "ConfigFormatError",
    "ConfigLoader",
    "ConfigNotLoadedError",
    "KstlibError",
    "LogManager",
    "MonitoringError",
    "PanelManager",
    "PanelRenderingError",
    "alerts",
    "app",
    "auth",
    "cache",
    "clear_config",
    "db",
    "get_config",
    "install_rich_traceback",
    "load_config",
    "load_from_env",
    "load_from_file",
    "mail",
    "metrics",
    "monitoring",
    "rapi",
    "require_config",
    "resilience",
    "secrets",
    "secure",
    "ui",
    "utils",
    "websocket",
]

# Lazy-loaded submodules
_SUBMODULES: frozenset[str] = frozenset(
    {
        "alerts",
        "app",
        "auth",
        "cache",
        "db",
        "mail",
        "metrics",
        "monitoring",
        "rapi",
        "resilience",
        "secrets",
        "secure",
        "ui",
        "utils",
        "websocket",
    }
)

# Mapping of attribute names to their import paths
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    # Config exceptions and classes
    "ConfigCircularIncludeError": ("kstlib.config", "ConfigCircularIncludeError"),
    "ConfigError": ("kstlib.config", "ConfigError"),
    "ConfigFileNotFoundError": ("kstlib.config", "ConfigFileNotFoundError"),
    "ConfigFormatError": ("kstlib.config", "ConfigFormatError"),
    "ConfigLoader": ("kstlib.config", "ConfigLoader"),
    "ConfigNotLoadedError": ("kstlib.config.exceptions", "ConfigNotLoadedError"),
    "KstlibError": ("kstlib.config", "KstlibError"),
    # Config functional API
    "clear_config": ("kstlib.config.loader", "clear_config"),
    "get_config": ("kstlib.config.loader", "get_config"),
    "load_config": ("kstlib.config.loader", "load_config"),
    "load_from_env": ("kstlib.config.loader", "load_from_env"),
    "load_from_file": ("kstlib.config.loader", "load_from_file"),
    "require_config": ("kstlib.config.loader", "require_config"),
    # Logging
    "LogManager": ("kstlib.logging", "LogManager"),
    # Monitoring
    "MonitoringError": ("kstlib.monitoring", "MonitoringError"),
    # UI
    "PanelManager": ("kstlib.ui", "PanelManager"),
    "PanelRenderingError": ("kstlib.ui", "PanelRenderingError"),
}

# Cache for loaded modules/attributes
_loaded: dict[str, Any] = {}

# Flag to track if rich traceback has been installed
_traceback_installed: bool = False


def install_rich_traceback() -> None:
    """Install Rich enhanced tracebacks.

    Call this explicitly if you want enhanced tracebacks. By default, tracebacks
    are not installed to keep import time fast.

    To auto-install on import (legacy behavior), set KSTLIB_TRACEBACK=1:

    - Bash/zsh: export KSTLIB_TRACEBACK=1
    - PowerShell: $env:KSTLIB_TRACEBACK = "1"
    """
    global _traceback_installed
    if _traceback_installed:
        return

    import shutil

    from rich.traceback import install

    terminal_width = shutil.get_terminal_size(fallback=(120, 20)).columns
    install(
        show_locals=True,
        word_wrap=True,
        width=terminal_width,
        extra_lines=7,
    )
    _traceback_installed = True


def __getattr__(name: str) -> Any:
    """Lazily load modules and attributes on first access (PEP 562)."""
    # Check cache first
    if name in _loaded:
        return _loaded[name]

    # Handle submodules
    if name in _SUBMODULES:
        if name == "app":
            # Import the Typer app object, not the module
            module = importlib.import_module("kstlib.cli")
            _loaded[name] = module.app
            return module.app
        if name == "cache":
            module = importlib.import_module("kstlib.cache")
            _loaded[name] = module.cache
            return module.cache
        module = importlib.import_module(f"kstlib.{name}")
        _loaded[name] = module
        return module

    # Handle lazy imports
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        try:
            module = importlib.import_module(module_path)
            attr = getattr(module, attr_name)
            _loaded[name] = attr
            return attr
        except (ImportError, AttributeError):
            # ConfigNotLoadedError might not exist in minimal installs
            if name == "ConfigNotLoadedError":
                _loaded[name] = None
                return None
            raise

    raise AttributeError(f"module 'kstlib' has no attribute {name!r}")


# Auto-install rich traceback if KSTLIB_TRACEBACK=1 (opt-in for fast imports)
# Default changed from "1" to "0" for metricsormance - users must opt-in now
if TYPE_CHECKING:
    # For static analysis - provide type hints for lazy-loaded symbols
    # pylint: disable=useless-import-alias
    from kstlib import alerts as alerts
    from kstlib import auth as auth
    from kstlib import db as db
    from kstlib import mail as mail
    from kstlib import metrics as metrics
    from kstlib import monitoring as monitoring
    from kstlib import rapi as rapi
    from kstlib import resilience as resilience
    from kstlib import secrets as secrets
    from kstlib import secure as secure
    from kstlib import ui as ui
    from kstlib import utils as utils
    from kstlib import websocket as websocket
    from kstlib.cache import cache as cache
    from kstlib.cli import app as app  # Typer app object
    from kstlib.config import (
        ConfigCircularIncludeError as ConfigCircularIncludeError,
    )
    from kstlib.config import (
        ConfigError as ConfigError,
    )
    from kstlib.config import (
        ConfigFileNotFoundError as ConfigFileNotFoundError,
    )
    from kstlib.config import (
        ConfigFormatError as ConfigFormatError,
    )
    from kstlib.config import (
        ConfigLoader as ConfigLoader,
    )
    from kstlib.config import (
        KstlibError as KstlibError,
    )
    from kstlib.config.exceptions import ConfigNotLoadedError as ConfigNotLoadedError
    from kstlib.config.loader import (
        clear_config as clear_config,
    )
    from kstlib.config.loader import (
        get_config as get_config,
    )
    from kstlib.config.loader import (
        load_config as load_config,
    )
    from kstlib.config.loader import (
        load_from_env as load_from_env,
    )
    from kstlib.config.loader import (
        load_from_file as load_from_file,
    )
    from kstlib.config.loader import (
        require_config as require_config,
    )
    from kstlib.logging import LogManager as LogManager
    from kstlib.monitoring import MonitoringError as MonitoringError
    from kstlib.ui import PanelManager as PanelManager
    from kstlib.ui import PanelRenderingError as PanelRenderingError
else:
    import os as _os

    if _os.getenv("KSTLIB_TRACEBACK", "0") == "1":
        install_rich_traceback()
