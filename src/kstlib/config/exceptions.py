"""
Exception hierarchy for kstlib.

All kstlib exceptions inherit from KstlibError, allowing users to catch
all kstlib-specific errors with a single except clause.

Example:
    try:
        config = load_config()
    except KstlibError as e:
        # Catch any kstlib error
        print(f"Error: {e}")
"""


class KstlibError(Exception):
    """
    Base exception for all kstlib errors.

    All kstlib-specific exceptions inherit from this class,
    allowing for easy catching of any kstlib error.
    """


# ============================================================================
# Configuration module exceptions
# ============================================================================


class ConfigError(KstlibError):
    """
    Base exception for configuration-related errors.

    All config module exceptions inherit from this class.
    """


class ConfigFileNotFoundError(ConfigError, FileNotFoundError):
    """
    Configuration file not found at specified location.

    Raised when attempting to load a config file that doesn't exist.
    """


class ConfigFormatError(ConfigError, ValueError):
    """
    Invalid configuration format or unsupported file type.

    Raised when:
    - File extension is not supported (.xml, etc.)
    - Format mismatch in strict mode (YAML including JSON)
    - Invalid content that cannot be parsed
    """


class ConfigCircularIncludeError(ConfigError, ValueError):
    """
    Circular include detected in configuration files.

    Raised when an include chain creates a cycle (A includes B, B includes A).
    """


class ConfigIncludeDepthError(ConfigError, ValueError):
    """
    Include depth limit exceeded.

    Raised when config includes are nested too deeply, which may indicate
    a misconfiguration or an attempt to exhaust resources.
    """


class ConfigNotLoadedError(ConfigError, RuntimeError):
    """
    Configuration not loaded yet.

    Raised by require_config() when attempting to access config
    before it has been loaded via get_config() or load_config().
    """


class ConfigSopsError(ConfigError):
    """
    SOPS decryption failed for a configuration file.

    Raised when SOPS binary fails to decrypt a .sops.* file.
    """


class ConfigSopsNotAvailableError(ConfigSopsError):
    """
    SOPS binary not installed or not found in PATH.

    Raised when attempting to decrypt a .sops.* file but the SOPS
    binary is not available. Install from https://github.com/getsops/sops
    """


__all__ = [
    "ConfigCircularIncludeError",
    "ConfigError",
    "ConfigFileNotFoundError",
    "ConfigFormatError",
    "ConfigIncludeDepthError",
    "ConfigNotLoadedError",
    "ConfigSopsError",
    "ConfigSopsNotAvailableError",
    "KstlibError",
]
