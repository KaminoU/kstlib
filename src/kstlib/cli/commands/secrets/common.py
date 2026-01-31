"""Shared utilities for secrets CLI commands."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from subprocess import CompletedProcess, run
from typing import TYPE_CHECKING, Any

import typer

from kstlib.config.exceptions import ConfigNotLoadedError
from kstlib.config.loader import get_config
from kstlib.utils.secure_delete import (
    DEFAULT_CHUNK_SIZE,
    SecureDeleteMethod,
    SecureDeleteReport,
    secure_delete,
)

if TYPE_CHECKING:
    from pathlib import Path
else:  # pragma: no cover - runtime alias for Typer conversions
    import pathlib

    Path = pathlib.Path

CheckEntry = dict[str, Any]

# =============================================================================
# Typer Options and Arguments
# =============================================================================

CONFIG_OPTION = typer.Option(
    None,
    "--config",
    help="Path to a SOPS configuration file.",
    exists=True,
    file_okay=True,
    dir_okay=False,
    readable=True,
)
FORCE_OPTION = typer.Option(False, "--force", "-f", help="Overwrite the output file if it already exists.")
FORMATS_OPTION = typer.Option(
    ("auto", "auto"),
    "--format",
    "-F",
    help="Input and output format (auto|json|yaml|text). Provide two values: input then output.",
    metavar="INPUT OUTPUT",
    show_default=True,
)
ENCRYPT_SOURCE_ARG = typer.Argument(
    ...,
    exists=True,
    dir_okay=False,
    help="Path to the cleartext secrets file.",
)
DECRYPT_SOURCE_ARG = typer.Argument(
    ...,
    exists=True,
    dir_okay=False,
    help="Path to the encrypted SOPS file.",
)
OUT_OPTION = typer.Option(None, "--out", "-o", help="Target path for the resulting file.")
QUIET_OPTION = typer.Option(
    False,
    "--quiet",
    help="Suppress Rich output; rely on the exit code only.",
)
SHRED_OPTION = typer.Option(
    False,
    "--shred",
    help="Remove the cleartext source file after a successful run.",
)
SHRED_METHOD_OPTION = typer.Option(
    None,
    "--shred-method",
    help="Secure delete method when shredding (auto|command|overwrite).",
)
SHRED_PASSES_OPTION = typer.Option(
    None,
    "--shred-passes",
    help="Number of overwrite passes when shredding.",
)
SHRED_ZERO_LAST_OPTION = typer.Option(
    None,
    "--shred-zero-last-pass/--shred-no-zero-last-pass",
    help="Control whether the last overwrite pass writes zeros.",
)
SHRED_CHUNK_SIZE_OPTION = typer.Option(
    None,
    "--shred-chunk-size",
    help="Chunk size in bytes used for overwrite operations.",
)
AGE_RECIPIENT_OPTION = typer.Option(
    None,
    "--age-recipient",
    help="Add an age public key recipient (option can be repeated).",
)
KMS_KEY_OPTION = typer.Option(
    None,
    "--kms-key",
    help="Add an AWS KMS key ARN (option can be repeated).",
)
DATA_KEY_OPTION = typer.Option(
    None,
    "--key",
    help="Provide a raw data key or provider-specific key flag understood by sops (option can be repeated).",
)
SHRED_TARGET_ARG = typer.Argument(
    ...,
    exists=True,
    dir_okay=False,
    help="Path to the secrets file that must be removed.",
)
SHRED_FORCE_OPTION = typer.Option(
    False,
    "--force",
    "-f",
    help="Skip the confirmation prompt when shredding secrets.",
)
SHRED_CMD_METHOD_OPTION = typer.Option(
    None,
    "--method",
    help="Secure delete method (auto|command|overwrite). Overrides configuration.",
)
SHRED_CMD_PASSES_OPTION = typer.Option(
    None,
    "--passes",
    help="Number of overwrite passes to perform.",
)
SHRED_CMD_ZERO_LAST_OPTION = typer.Option(
    None,
    "--zero-last-pass/--no-zero-last-pass",
    help="Control whether the last overwrite pass writes zeros.",
)
SHRED_CMD_CHUNK_SIZE_OPTION = typer.Option(
    None,
    "--chunk-size",
    help="Chunk size in bytes used for overwrite operations.",
)
SHRED_CMD_QUIET_OPTION = typer.Option(
    False,
    "--quiet",
    help="Suppress Rich output when shredding directly.",
)
INIT_LOCAL_OPTION = typer.Option(
    False,
    "--local",
    "-l",
    help="Create config in current directory instead of user home.",
)
INIT_FORCE_OPTION = typer.Option(
    False,
    "--force",
    "-f",
    help="Overwrite existing files.",
)

# =============================================================================
# Dataclasses
# =============================================================================


@dataclass(slots=True)
class SecureDeleteCLIOptions:
    """Secure delete options supplied through the CLI."""

    enabled: bool
    method: str | None
    passes: int | None
    zero_last_pass: bool | None
    chunk_size: int | None


@dataclass(slots=True)
class EncryptCommandOptions:  # pylint: disable=too-many-instance-attributes
    """Container for encrypt command options."""

    out: Path | None
    binary: str
    config: Path | None
    formats: tuple[str, str]
    force: bool
    quiet: bool
    shred: SecureDeleteCLIOptions
    age_recipients: tuple[str, ...]
    kms_keys: tuple[str, ...]
    data_keys: tuple[str, ...]


@dataclass(slots=True)
class ShredCommandOptions:
    """Container for shred command options."""

    force: bool
    method: str | None
    passes: int | None
    zero_last_pass: bool | None
    chunk_size: int | None
    quiet: bool


# =============================================================================
# SOPS Command Execution
# =============================================================================


def run_sops_command(binary: str, arguments: list[str]) -> CompletedProcess[str]:
    """Execute the sops binary with the provided arguments."""
    binary_path = shutil.which(binary)
    if binary_path is None:
        raise FileNotFoundError(binary)
    command = [binary_path, *arguments]
    return run(
        command,
        capture_output=True,
        text=True,
        check=False,
        shell=False,
    )


def resolve_sops_binary() -> str:
    """Return the configured sops binary name if set, otherwise the default."""
    default_binary = "sops"
    try:
        config = get_config()
    except ConfigNotLoadedError:
        return default_binary

    secrets_config = getattr(config, "secrets", None)
    if secrets_config is None or not hasattr(secrets_config, "to_dict"):
        return default_binary

    data = secrets_config.to_dict()
    if not isinstance(data, Mapping):
        return default_binary

    sops_config = data.get("sops")
    if isinstance(sops_config, Mapping):
        binary = sops_config.get("binary")
        if isinstance(binary, str) and binary:
            return binary

        settings = sops_config.get("settings")
        if isinstance(settings, Mapping):
            settings_binary = settings.get("binary")
            if isinstance(settings_binary, str) and settings_binary:
                return settings_binary

    return default_binary


def format_arguments(input_format: str, output_format: str) -> list[str]:
    """Build format arguments for sops command."""
    arguments: list[str] = []
    if input_format.lower() != "auto":
        arguments.extend(["--input-type", input_format])
    if output_format.lower() != "auto":
        arguments.extend(["--output-type", output_format])
    return arguments


# =============================================================================
# Secure Delete Helpers
# =============================================================================


def shred_file(
    target: Path,
    *,
    method: str | None = None,
    passes: int | None = None,
    zero_last_pass: bool | None = None,
    chunk_size: int | None = None,
) -> SecureDeleteReport:
    """Remove a file from disk using secure deletion semantics."""
    try:
        settings = _resolve_secure_delete_settings(
            method=method,
            passes=passes,
            zero_last_pass=zero_last_pass,
            chunk_size=chunk_size,
        )
    except ValueError as error:
        return SecureDeleteReport(
            success=False,
            method=SecureDeleteMethod.AUTO,
            passes=passes or 0,
            message=str(error),
        )

    try:
        return secure_delete(
            target,
            method=settings["method"],
            passes=settings["passes"],
            zero_last_pass=settings["zero_last_pass"],
            chunk_size=settings["chunk_size"],
        )
    except ValueError as error:
        return SecureDeleteReport(
            success=False,
            method=settings["method"],
            passes=settings["passes"],
            message=str(error),
        )


def _resolve_secure_delete_settings(
    *,
    method: str | SecureDeleteMethod | None,
    passes: int | None,
    zero_last_pass: bool | None,
    chunk_size: int | None,
) -> dict[str, Any]:
    """Resolve secure deletion settings from configuration and overrides."""
    config_settings = _get_secure_delete_settings()

    method_value = method if method is not None else config_settings.get("method")
    resolved_method = _normalize_method(method_value)

    resolved_passes = passes if passes is not None else int(config_settings.get("passes", 3))
    if resolved_passes < 1:
        raise ValueError("Secure delete passes must be >= 1.")

    resolved_chunk_size = (
        chunk_size if chunk_size is not None else int(config_settings.get("chunk_size", DEFAULT_CHUNK_SIZE))
    )
    if resolved_chunk_size < 1:
        raise ValueError("Secure delete chunk size must be >= 1.")

    resolved_zero_last = (
        zero_last_pass if zero_last_pass is not None else bool(config_settings.get("zero_last_pass", True))
    )

    return {
        "method": resolved_method,
        "passes": resolved_passes,
        "zero_last_pass": resolved_zero_last,
        "chunk_size": resolved_chunk_size,
    }


def _normalize_method(value: str | SecureDeleteMethod | None) -> SecureDeleteMethod:
    """Normalise user-provided secure delete method values."""
    if value is None:
        return SecureDeleteMethod.AUTO
    if isinstance(value, SecureDeleteMethod):
        return value
    try:
        return SecureDeleteMethod(str(value).lower())
    except ValueError as error:
        raise ValueError(f"Unsupported secure delete method '{value}'.") from error


def _get_secure_delete_settings() -> dict[str, Any]:
    """Return secure delete settings from the loaded configuration."""
    try:
        config = get_config()
    except ConfigNotLoadedError:
        return {}

    result: dict[str, Any] = {}
    candidates: list[Any] = []

    utilities = getattr(config, "utilities", None)
    if utilities is not None:
        candidates.append(getattr(utilities, "secure_delete", None))

    secrets_config = getattr(config, "secrets", None)
    if secrets_config is not None:
        candidates.append(getattr(secrets_config, "secure_delete", None))

    for node in candidates:
        if node is None:
            continue
        if hasattr(node, "to_dict"):
            data = node.to_dict()
        elif isinstance(node, dict):
            data = node
        else:
            continue
        result.update({k: v for k, v in data.items() if v is not None})

    return result


__all__ = [
    "AGE_RECIPIENT_OPTION",
    "CONFIG_OPTION",
    "DATA_KEY_OPTION",
    "DECRYPT_SOURCE_ARG",
    "ENCRYPT_SOURCE_ARG",
    "FORCE_OPTION",
    "FORMATS_OPTION",
    "INIT_FORCE_OPTION",
    "INIT_LOCAL_OPTION",
    "KMS_KEY_OPTION",
    "OUT_OPTION",
    "QUIET_OPTION",
    "SHRED_CHUNK_SIZE_OPTION",
    "SHRED_CMD_CHUNK_SIZE_OPTION",
    "SHRED_CMD_METHOD_OPTION",
    "SHRED_CMD_PASSES_OPTION",
    "SHRED_CMD_QUIET_OPTION",
    "SHRED_CMD_ZERO_LAST_OPTION",
    "SHRED_FORCE_OPTION",
    "SHRED_METHOD_OPTION",
    "SHRED_OPTION",
    "SHRED_PASSES_OPTION",
    "SHRED_TARGET_ARG",
    "SHRED_ZERO_LAST_OPTION",
    "CheckEntry",
    "EncryptCommandOptions",
    "Path",
    "SecureDeleteCLIOptions",
    "ShredCommandOptions",
    "format_arguments",
    "resolve_sops_binary",
    "run_sops_command",
    "shred_file",
]
