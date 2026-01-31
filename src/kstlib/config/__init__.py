"""Configuration management module.

This module provides flexible configuration loading from various file formats
with support for includes, environment variables, and cascading search.

SOPS Integration:
    Files with .sops.yml, .sops.yaml, .sops.json, or .sops.toml extensions
    are automatically decrypted via the SOPS binary when loaded.
"""

# pylint: disable=duplicate-code
from kstlib.config.exceptions import (
    ConfigCircularIncludeError,
    ConfigError,
    ConfigFileNotFoundError,
    ConfigFormatError,
    ConfigIncludeDepthError,
    ConfigNotLoadedError,
    ConfigSopsError,
    ConfigSopsNotAvailableError,
    KstlibError,
)
from kstlib.config.export import (
    ConfigExportError,
    ConfigExportOptions,
    ConfigExportResult,
    export_configuration,
)
from kstlib.config.loader import (
    CONFIG_FILENAME,
    ConfigLoader,
    clear_config,
    get_config,
    load_config,
    load_from_env,
    load_from_file,
    require_config,
)
from kstlib.config.sops import (
    SopsDecryptor,
    get_decryptor,
    get_real_extension,
    has_encrypted_values,
    is_sops_file,
    reset_decryptor,
)

__all__ = [
    "CONFIG_FILENAME",
    "ConfigCircularIncludeError",
    "ConfigError",
    "ConfigExportError",
    "ConfigExportOptions",
    "ConfigExportResult",
    "ConfigFileNotFoundError",
    "ConfigFormatError",
    "ConfigIncludeDepthError",
    "ConfigLoader",
    "ConfigNotLoadedError",
    "ConfigSopsError",
    "ConfigSopsNotAvailableError",
    "KstlibError",
    "SopsDecryptor",
    "clear_config",
    "export_configuration",
    "get_config",
    "get_decryptor",
    "get_real_extension",
    "has_encrypted_values",
    "is_sops_file",
    "load_config",
    "load_from_env",
    "load_from_file",
    "require_config",
    "reset_decryptor",
]
