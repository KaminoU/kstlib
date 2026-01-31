"""Encrypt command for secrets subsystem."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer

from kstlib.cli.common import (
    CommandResult,
    CommandStatus,
    console,
    exit_with_result,
    render_result,
)

from .common import (
    AGE_RECIPIENT_OPTION,
    CONFIG_OPTION,
    DATA_KEY_OPTION,
    ENCRYPT_SOURCE_ARG,
    FORCE_OPTION,
    FORMATS_OPTION,
    KMS_KEY_OPTION,
    OUT_OPTION,
    QUIET_OPTION,
    SHRED_CHUNK_SIZE_OPTION,
    SHRED_METHOD_OPTION,
    SHRED_OPTION,
    SHRED_PASSES_OPTION,
    SHRED_ZERO_LAST_OPTION,
    EncryptCommandOptions,
    SecureDeleteCLIOptions,
    format_arguments,
    resolve_sops_binary,
    run_sops_command,
    shred_file,
)

if TYPE_CHECKING:
    from subprocess import CompletedProcess

    from kstlib.utils.secure_delete import SecureDeleteReport


def _ensure_encrypt_destination(options: EncryptCommandOptions) -> None:
    """Abort when the target output is not writable."""
    if options.out is None or not options.out.exists() or options.force:
        return

    result = CommandResult(
        status=CommandStatus.ERROR,
        message=f"Refuse to overwrite existing file: {options.out} (use --force).",
    )
    exit_with_result(result, options.quiet, exit_code=1)


def _run_encrypt_command(source: Path, options: EncryptCommandOptions) -> CompletedProcess[str]:
    """Execute the ``sops`` encryption command and handle failures."""
    try:
        completed = run_sops_command(
            options.binary,
            _build_encrypt_args(source, options),
        )
    except FileNotFoundError as exc:
        result = CommandResult(
            status=CommandStatus.ERROR,
            message=(f"SOPS binary '{options.binary}' not found. Install it or set secrets.sops.binary in the config."),
        )
        exit_with_result(result, options.quiet, exit_code=1, cause=exc)

    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "sops command failed"
        result = CommandResult(status=CommandStatus.ERROR, message=message)
        exit_with_result(result, options.quiet, exit_code=1)

    return completed


def _maybe_print_encrypt_output(completed: CompletedProcess[str], options: EncryptCommandOptions) -> None:
    """Display stdout emitted by ``sops`` when appropriate."""
    if options.out is not None:
        return
    if options.quiet or not completed.stdout:
        return
    console.print(completed.stdout.rstrip("\n"))


def _handle_shred_request(source: Path, options: EncryptCommandOptions) -> SecureDeleteReport | None:
    """Perform secure delete when requested, aborting on failure."""
    if not options.shred.enabled:
        return None

    shred_opts = options.shred
    report = shred_file(
        source,
        method=shred_opts.method,
        passes=shred_opts.passes,
        zero_last_pass=shred_opts.zero_last_pass,
        chunk_size=shred_opts.chunk_size,
    )

    if report.success:
        return report

    reason = f" {report.message}" if report.message else ""
    result = CommandResult(
        status=CommandStatus.ERROR,
        message=f"Failed to remove cleartext source '{source}'.{reason}",
    )
    return exit_with_result(result, options.quiet, exit_code=1)


def _compose_encrypt_success_message(
    source: Path,
    options: EncryptCommandOptions,
    report: SecureDeleteReport | None,
) -> str:
    """Return the final success message for ``encrypt``."""
    target_info = str(options.out) if options.out else "stdout"
    message = f"Encrypted secrets written to {target_info}."

    if report is not None:
        detail = f"{report.method.value} ({report.passes} passes)"
        if report.command:
            detail += f" via {' '.join(report.command)}"
        return message + f" Cleartext source '{source}' removed using {detail}."

    if not options.shred.enabled:
        message += f" Cleartext source '{source}' still exists; run 'kstlib secrets shred {source}' to remove it."

    return message


def _build_encrypt_args(
    source: Path,
    options: EncryptCommandOptions,
) -> list[str]:
    """Build arguments for ``sops --encrypt``."""
    arguments = _base_encrypt_args(options)
    arguments.extend(format_arguments(*options.formats))
    arguments.extend(_recipient_flags(options))
    arguments.extend(_key_flags(options))
    arguments.append(str(source))
    return arguments


def _base_encrypt_args(options: EncryptCommandOptions) -> list[str]:
    """Return base arguments shared by every encrypt invocation."""
    arguments: list[str] = []
    if options.config is not None:
        arguments.extend(["--config", str(options.config)])
    arguments.append("--encrypt")
    if options.out is not None:
        arguments.extend(["--output", str(options.out)])
    return arguments


def _recipient_flags(options: EncryptCommandOptions) -> list[str]:
    """Return age or KMS recipient flag arguments."""
    arguments: list[str] = []
    if options.age_recipients:
        for recipient in options.age_recipients:
            arguments.extend(["--age", recipient])
    if options.kms_keys:
        for kms_key in options.kms_keys:
            arguments.extend(["--kms", kms_key])
    return arguments


def _key_flags(options: EncryptCommandOptions) -> list[str]:
    """Return raw data key flag arguments."""
    arguments: list[str] = []
    if options.data_keys:
        for data_key in options.data_keys:
            arguments.extend(["--key", data_key])
    return arguments


def _execute_encrypt(source: Path, options: EncryptCommandOptions) -> None:
    """Perform the encryption workflow using the provided options."""
    _ensure_encrypt_destination(options)
    completed = _run_encrypt_command(source, options)
    _maybe_print_encrypt_output(completed, options)
    shred_report = _handle_shred_request(source, options)
    message = _compose_encrypt_success_message(source, options, shred_report)
    result = CommandResult(status=CommandStatus.OK, message=message)
    if options.quiet:
        raise typer.Exit(code=0)
    render_result(result)


# pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
def encrypt(
    source: Path = ENCRYPT_SOURCE_ARG,
    *,
    out: Path | None = OUT_OPTION,
    config: Path | None = CONFIG_OPTION,
    formats: tuple[str, str] = FORMATS_OPTION,
    force: bool = FORCE_OPTION,
    quiet: bool = QUIET_OPTION,
    shred_enabled: bool = SHRED_OPTION,
    shred_method: str | None = SHRED_METHOD_OPTION,
    shred_passes: int | None = SHRED_PASSES_OPTION,
    shred_zero_last_pass: bool | None = SHRED_ZERO_LAST_OPTION,
    shred_chunk_size: int | None = SHRED_CHUNK_SIZE_OPTION,
    age_recipient: list[str] | None = AGE_RECIPIENT_OPTION,
    kms_key: list[str] | None = KMS_KEY_OPTION,
    key: list[str] | None = DATA_KEY_OPTION,
) -> None:
    """Encrypt a cleartext file using sops."""
    binary = resolve_sops_binary()
    effective_config = config
    if effective_config is None:
        default_config = Path.home() / ".sops.yaml"
        if default_config.exists():
            effective_config = default_config

    options = EncryptCommandOptions(
        out=out,
        binary=binary,
        config=effective_config,
        formats=formats,
        force=force,
        quiet=quiet,
        shred=SecureDeleteCLIOptions(
            enabled=shred_enabled,
            method=shred_method,
            passes=shred_passes,
            zero_last_pass=shred_zero_last_pass,
            chunk_size=shred_chunk_size,
        ),
        age_recipients=tuple(age_recipient or []),
        kms_keys=tuple(kms_key or []),
        data_keys=tuple(key or []),
    )

    _execute_encrypt(source, options)


__all__ = ["encrypt"]
