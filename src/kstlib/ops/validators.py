"""Input validation for kstlib.ops module.

This module provides validation functions for all user-exposed values
in the ops module, implementing deep defense against malformed or
malicious input.

Hard limits are enforced to prevent resource exhaustion and ensure
predictable behavior across all backends.
"""

from __future__ import annotations

import re

# ============================================================================
# Constants - Hard Limits
# ============================================================================

# Session name limits
MAX_SESSION_NAME_LENGTH = 64
SESSION_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")

# Container image limits
MAX_IMAGE_NAME_LENGTH = 256
# OCI image name: registry/path:tag@digest format
IMAGE_NAME_PATTERN = re.compile(
    r"^[a-z0-9]([a-z0-9._-]*[a-z0-9])?(/[a-z0-9]([a-z0-9._-]*[a-z0-9])?)*"
    r"(:[a-zA-Z0-9._-]+)?(@sha256:[a-f0-9]{64})?$"
)

# Volume limits
MAX_VOLUMES = 20
VOLUME_PATTERN = re.compile(r"^[^:]+:[^:]+(:ro|:rw)?$")

# Port limits
MAX_PORTS = 50
PORT_PATTERN = re.compile(r"^(\d{1,5}:)?\d{1,5}(/tcp|/udp)?$")

# Environment variable limits
MAX_ENV_VARS = 100
MAX_ENV_KEY_LENGTH = 128
MAX_ENV_VALUE_LENGTH = 32768  # 32KB

# Command limits
MAX_COMMAND_LENGTH = 4096

# Dangerous patterns to block in commands
DANGEROUS_PATTERNS = [
    r";\s*rm\s+-rf",  # rm -rf after semicolon
    r"\$\(.*\)",  # Command substitution
    r"`.*`",  # Backtick substitution
    r"\|\s*sh\b",  # Pipe to shell
    r"\|\s*bash\b",  # Pipe to bash
]


# ============================================================================
# Validation Functions
# ============================================================================


def validate_session_name(name: str) -> str:
    """Validate and return session name.

    Rules:
    - Cannot be empty
    - Max 64 characters (hard limit)
    - Must start with letter
    - Only alphanumeric, underscore, hyphen allowed
    - No shell metacharacters

    Args:
        name: Session name to validate.

    Returns:
        The validated session name (unchanged).

    Raises:
        ValueError: If name is invalid.

    Examples:
        >>> validate_session_name("mybot")
        'mybot'
        >>> validate_session_name("my-bot_01")
        'my-bot_01'
        >>> validate_session_name("")
        Traceback (most recent call last):
            ...
        ValueError: Session name cannot be empty
    """
    if not name:
        raise ValueError("Session name cannot be empty")
    if len(name) > MAX_SESSION_NAME_LENGTH:
        raise ValueError(f"Session name too long (max {MAX_SESSION_NAME_LENGTH} chars)")
    if not SESSION_NAME_PATTERN.match(name):
        raise ValueError(
            "Session name must start with letter and contain only alphanumeric, underscore, or hyphen characters"
        )
    return name


def validate_image_name(image: str) -> str:
    """Validate container image name.

    Rules:
    - Max 256 characters
    - Valid Docker/OCI image format
    - No shell injection characters

    Args:
        image: Container image name to validate.

    Returns:
        The validated image name (unchanged).

    Raises:
        ValueError: If image name is invalid.

    Examples:
        >>> validate_image_name("python:3.10-slim")
        'python:3.10-slim'
        >>> validate_image_name("registry.io/path/image:tag")
        'registry.io/path/image:tag'
    """
    if not image:
        raise ValueError("Image name cannot be empty")
    if len(image) > MAX_IMAGE_NAME_LENGTH:
        raise ValueError(f"Image name too long (max {MAX_IMAGE_NAME_LENGTH} chars)")
    if not IMAGE_NAME_PATTERN.match(image):
        raise ValueError(f"Invalid image name format: {image}")
    return image


def validate_volumes(volumes: list[str]) -> list[str]:
    """Validate volume mappings.

    Rules:
    - Max 20 volumes
    - Valid format: host:container[:ro|:rw]
    - No path traversal (..)

    Args:
        volumes: List of volume mappings to validate.

    Returns:
        The validated volumes list (unchanged).

    Raises:
        ValueError: If volumes are invalid.

    Examples:
        >>> validate_volumes(["./data:/app/data"])
        ['./data:/app/data']
        >>> validate_volumes(["./logs:/app/logs:ro"])
        ['./logs:/app/logs:ro']
    """
    if len(volumes) > MAX_VOLUMES:
        raise ValueError(f"Too many volumes (max {MAX_VOLUMES})")
    for vol in volumes:
        if not VOLUME_PATTERN.match(vol):
            raise ValueError(f"Invalid volume format: {vol}")
        if ".." in vol:
            raise ValueError(f"Path traversal not allowed in volume: {vol}")
    return volumes


def validate_ports(ports: list[str]) -> list[str]:
    """Validate port mappings.

    Rules:
    - Max 50 ports
    - Valid format: [host:]container[/tcp|/udp]
    - Port numbers in range 1-65535

    Args:
        ports: List of port mappings to validate.

    Returns:
        The validated ports list (unchanged).

    Raises:
        ValueError: If ports are invalid.

    Examples:
        >>> validate_ports(["8080:80"])
        ['8080:80']
        >>> validate_ports(["8080"])
        ['8080']
        >>> validate_ports(["8080:80/tcp"])
        ['8080:80/tcp']
    """
    if len(ports) > MAX_PORTS:
        raise ValueError(f"Too many ports (max {MAX_PORTS})")
    for port in ports:
        if not PORT_PATTERN.match(port):
            raise ValueError(f"Invalid port format: {port}")
        # Validate port numbers are in valid range
        nums = re.findall(r"\d+", port)
        for num in nums:
            port_num = int(num)
            if port_num < 1 or port_num > 65535:
                raise ValueError(f"Port number out of range (1-65535): {num}")
    return ports


def validate_env(env: dict[str, str]) -> dict[str, str]:
    """Validate environment variables.

    Rules:
    - Max 100 env vars
    - Key max 128 characters
    - Value max 32KB
    - Key must be valid identifier

    Args:
        env: Dictionary of environment variables to validate.

    Returns:
        The validated env dict (unchanged).

    Raises:
        ValueError: If env vars are invalid.

    Examples:
        >>> validate_env({"APP_ENV": "production"})
        {'APP_ENV': 'production'}
    """
    if len(env) > MAX_ENV_VARS:
        raise ValueError(f"Too many env vars (max {MAX_ENV_VARS})")
    for key, value in env.items():
        if len(key) > MAX_ENV_KEY_LENGTH:
            raise ValueError(f"Env key too long (max {MAX_ENV_KEY_LENGTH}): {key[:20]}...")
        if len(value) > MAX_ENV_VALUE_LENGTH:
            raise ValueError(f"Env value too long (max {MAX_ENV_VALUE_LENGTH}) for key: {key}")
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            raise ValueError(f"Invalid env key format: {key}")
    return env


def validate_command(command: str | None) -> str | None:
    """Validate command string.

    Rules:
    - Max 4096 characters
    - No dangerous shell patterns

    Args:
        command: Command string to validate (can be None).

    Returns:
        The validated command (unchanged).

    Raises:
        ValueError: If command is invalid or contains dangerous patterns.

    Examples:
        >>> validate_command("python -m app")
        'python -m app'
        >>> validate_command(None) is None
        True
    """
    if command is None:
        return None
    if len(command) > MAX_COMMAND_LENGTH:
        raise ValueError(f"Command too long (max {MAX_COMMAND_LENGTH} chars)")
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            raise ValueError("Potentially dangerous command pattern detected")
    return command


__all__ = [
    "MAX_COMMAND_LENGTH",
    "MAX_ENV_KEY_LENGTH",
    "MAX_ENV_VALUE_LENGTH",
    "MAX_ENV_VARS",
    "MAX_IMAGE_NAME_LENGTH",
    "MAX_PORTS",
    "MAX_SESSION_NAME_LENGTH",
    "MAX_VOLUMES",
    "validate_command",
    "validate_env",
    "validate_image_name",
    "validate_ports",
    "validate_session_name",
    "validate_volumes",
]
