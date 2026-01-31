"""Secure file deletion utilities."""

from __future__ import annotations

import os
import platform
import secrets
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

DEFAULT_CHUNK_SIZE = 1024 * 1024


class SecureDeleteMethod(str, Enum):
    """Available strategies for securely deleting files."""

    AUTO = "auto"
    COMMAND = "command"
    OVERWRITE = "overwrite"


@dataclass(slots=True)
class SecureDeleteReport:
    """Summary result produced by :func:`secure_delete`."""

    success: bool
    method: SecureDeleteMethod
    passes: int
    command: Sequence[str] | None = None
    message: str | None = None


if TYPE_CHECKING:
    from collections.abc import Sequence


def secure_delete(
    target: Path | str,
    *,
    passes: int = 3,
    method: SecureDeleteMethod | str = SecureDeleteMethod.AUTO,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    zero_last_pass: bool = True,
) -> SecureDeleteReport:
    """Securely remove ``target`` from disk.

    Args:
        target: File path that must be removed.
        passes: Number of overwrite passes to perform when relying on the
            built-in overwrite implementation. Values lower than ``1`` raise
            ``ValueError``.
        method: Preferred strategy. ``auto`` attempts to use a platform shred
            command and falls back to overwriting when none is available or
            when the command fails. ``command`` forces the usage of a system
            command and reports an error if it is not available. ``overwrite``
            forces the Python overwrite implementation.
        chunk_size: Size, in bytes, of the chunks written during the overwrite
            loop. Defaults to 1 MiB.
        zero_last_pass: If ``True``, the final overwrite pass writes zeros
            instead of random data.

    Returns:
        A :class:`SecureDeleteReport` describing the outcome.

    Raises:
        ValueError: If ``passes`` is lower than ``1`` or if ``target`` does not
            reference a regular file.

    Example:
        Securely remove a cleartext file once it is no longer needed::

            >>> from pathlib import Path
            >>> from kstlib.utils.secure_delete import secure_delete, SecureDeleteMethod
            >>> path = Path("secret.txt")
            >>> _ = path.write_text("classified")  # doctest: +SKIP
            >>> report = secure_delete(path, method=SecureDeleteMethod.OVERWRITE, passes=1)  # doctest: +SKIP
            >>> report.success  # doctest: +SKIP
            True
    """
    path = Path(target)

    if passes < 1:
        raise ValueError("passes must be >= 1")

    if not path.exists():
        return SecureDeleteReport(
            success=True,
            method=SecureDeleteMethod(method),
            passes=passes,
            message="Target already removed.",
        )

    if not path.is_file():
        raise ValueError("secure_delete only supports regular files")

    resolved_method = SecureDeleteMethod(method)

    if resolved_method in {SecureDeleteMethod.AUTO, SecureDeleteMethod.COMMAND}:
        command = _build_platform_command(path, passes, zero_last_pass)
        if command is not None:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return SecureDeleteReport(
                    success=True,
                    method=SecureDeleteMethod.COMMAND,
                    passes=passes,
                    command=command,
                )

            if resolved_method == SecureDeleteMethod.COMMAND:
                message = result.stderr.strip() or result.stdout.strip() or "command failed"
                return SecureDeleteReport(
                    success=False,
                    method=SecureDeleteMethod.COMMAND,
                    passes=passes,
                    command=command,
                    message=message,
                )

    overwrite_report = _overwrite_and_remove(path, passes, chunk_size, zero_last_pass)
    if resolved_method == SecureDeleteMethod.COMMAND and not overwrite_report.success:
        overwrite_report.method = SecureDeleteMethod.COMMAND
    return overwrite_report


def _build_platform_command(path: Path, passes: int, zero_last_pass: bool) -> list[str] | None:
    """Return a platform-specific secure delete command when available."""
    system = platform.system().lower()
    shred_path = shutil.which("shred")
    if shred_path:
        command = [shred_path, "--force", "--remove"]
        if passes:
            command.append(f"--iterations={passes}")
        if zero_last_pass:
            command.append("--zero")
        command.append(str(path))
        return command

    if system == "darwin":
        srm_path = shutil.which("srm")
        if srm_path:
            command = [srm_path, "-f"]
            if passes > 1:
                command.append("-m")
            if zero_last_pass:
                command.append("-z")
            command.append(str(path))
            return command

    return None


def _overwrite_and_remove(
    path: Path,
    passes: int,
    chunk_size: int,
    zero_last_pass: bool,
) -> SecureDeleteReport:
    """Overwrite ``path`` with random data before unlinking it."""
    try:
        file_size = path.stat().st_size
        if file_size == 0:
            path.unlink(missing_ok=True)
            return SecureDeleteReport(
                success=True,
                method=SecureDeleteMethod.OVERWRITE,
                passes=passes,
                message="Zero-length file removed.",
            )

        with path.open("r+b", buffering=0) as handle:
            for index in range(passes):
                handle.seek(0)
                remaining = file_size
                while remaining > 0:
                    chunk = min(chunk_size, remaining)
                    data = bytes(chunk) if index == passes - 1 and zero_last_pass else secrets.token_bytes(chunk)
                    handle.write(data)
                    remaining -= chunk
                handle.flush()
                os.fsync(handle.fileno())

        path.unlink(missing_ok=True)
        return SecureDeleteReport(
            success=True,
            method=SecureDeleteMethod.OVERWRITE,
            passes=passes,
            message="File overwritten and removed.",
        )
    except OSError as error:
        return SecureDeleteReport(
            success=False,
            method=SecureDeleteMethod.OVERWRITE,
            passes=passes,
            message=str(error),
        )
