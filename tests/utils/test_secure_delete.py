"""Tests for the secure delete utilities."""

# pylint: disable=missing-function-docstring,protected-access

from __future__ import annotations

import importlib
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any

import pytest

from kstlib.utils.secure_delete import SecureDeleteMethod, SecureDeleteReport, secure_delete

SECURE_DELETE_MODULE = importlib.import_module("kstlib.utils.secure_delete")


def test_secure_delete_noop_when_missing(tmp_path: Path) -> None:
    """Return a successful no-op report when the target file does not exist."""
    target = tmp_path / "missing.txt"

    report = secure_delete(target)

    assert report.success is True
    assert report.method is SecureDeleteMethod.AUTO
    assert report.message == "Target already removed."


def test_secure_delete_overwrite_removes_file(tmp_path: Path) -> None:
    """Overwrite method removes the file and reports success."""
    target = tmp_path / "secret.bin"
    target.write_bytes(b"classified")

    report = secure_delete(target, method=SecureDeleteMethod.OVERWRITE, passes=1, chunk_size=2)

    assert report.success is True
    assert report.method is SecureDeleteMethod.OVERWRITE
    assert report.passes == 1
    assert not target.exists()


def test_secure_delete_uses_shred_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Invoke shred on Linux when AUTO method is selected."""
    target = tmp_path / "secret.bin"
    target.write_bytes(b"classified")

    commands: list[list[str]] = []

    monkeypatch.setattr(SECURE_DELETE_MODULE.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        SECURE_DELETE_MODULE.shutil,
        "which",
        lambda name: "/usr/bin/shred" if name == "shred" else None,
    )

    def fake_run(command: list[str], **_: Any) -> CompletedProcess[str]:
        commands.append(command)
        target.unlink(missing_ok=True)
        return CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(SECURE_DELETE_MODULE.subprocess, "run", fake_run)

    report = secure_delete(target, method=SecureDeleteMethod.AUTO, passes=2, zero_last_pass=False)

    assert report.success is True
    assert report.method is SecureDeleteMethod.COMMAND
    assert commands and commands[0][0] == "/usr/bin/shred"
    assert not target.exists()


def test_secure_delete_command_zero_last_pass(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Pass --zero flag to shred when zero_last_pass is enabled."""
    target = tmp_path / "secret.bin"
    target.write_bytes(b"classified")

    commands: list[list[str]] = []

    monkeypatch.setattr(SECURE_DELETE_MODULE.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        SECURE_DELETE_MODULE.shutil,
        "which",
        lambda name: "/usr/bin/shred" if name == "shred" else None,
    )

    def fake_run(command: list[str], **_: Any) -> CompletedProcess[str]:
        commands.append(command)
        target.unlink(missing_ok=True)
        return CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(SECURE_DELETE_MODULE.subprocess, "run", fake_run)

    report = secure_delete(target, method=SecureDeleteMethod.AUTO, passes=1)

    assert report.success is True
    assert "--zero" in commands[0]


def test_secure_delete_uses_srm_on_darwin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Invoke srm on macOS with the expected flags when AUTO method is selected."""
    target = tmp_path / "secret.bin"
    target.write_bytes(b"classified")

    commands: list[list[str]] = []

    monkeypatch.setattr(SECURE_DELETE_MODULE.platform, "system", lambda: "Darwin")

    def fake_which(name: str) -> str | None:
        return {"shred": None, "srm": "/usr/bin/srm"}.get(name)

    monkeypatch.setattr(SECURE_DELETE_MODULE.shutil, "which", fake_which)

    def fake_run(command: list[str], **_: Any) -> CompletedProcess[str]:
        commands.append(command)
        target.unlink(missing_ok=True)
        return CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(SECURE_DELETE_MODULE.subprocess, "run", fake_run)

    report = secure_delete(target, method=SecureDeleteMethod.AUTO, passes=2)

    assert report.success is True
    assert commands and commands[0][0] == "/usr/bin/srm"
    assert "-m" in commands[0]
    assert "-z" in commands[0]


def test_secure_delete_command_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Report failure and preserve the file when the shred command exits non-zero."""
    target = tmp_path / "secret.bin"
    target.write_bytes(b"classified")

    monkeypatch.setattr(SECURE_DELETE_MODULE.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        SECURE_DELETE_MODULE.shutil,
        "which",
        lambda name: "/usr/bin/shred" if name == "shred" else None,
    )

    def fake_run(command: list[str], **_: Any) -> CompletedProcess[str]:
        return CompletedProcess(command, 1, stdout="", stderr="shred failure")

    monkeypatch.setattr(SECURE_DELETE_MODULE.subprocess, "run", fake_run)

    report = secure_delete(target, method=SecureDeleteMethod.COMMAND, passes=2)

    assert report.success is False
    assert report.method is SecureDeleteMethod.COMMAND
    assert "shred failure" in (report.message or "")
    assert target.exists()


def test_secure_delete_auto_falls_back_to_overwrite(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Fall back to OVERWRITE and succeed when the shred command fails in AUTO mode."""
    target = tmp_path / "secret.bin"
    target.write_bytes(b"classified")

    monkeypatch.setattr(SECURE_DELETE_MODULE.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        SECURE_DELETE_MODULE.shutil,
        "which",
        lambda name: "/usr/bin/shred" if name == "shred" else None,
    )

    def fake_run(command: list[str], **_: Any) -> CompletedProcess[str]:
        return CompletedProcess(command, 1, stdout="", stderr="shred failure")

    monkeypatch.setattr(SECURE_DELETE_MODULE.subprocess, "run", fake_run)

    report = secure_delete(target, method=SecureDeleteMethod.AUTO, passes=1)

    assert report.success is True
    assert report.method is SecureDeleteMethod.OVERWRITE
    assert not target.exists()


def test_secure_delete_rejects_invalid_passes(tmp_path: Path) -> None:
    """Raise ValueError when passes is less than one."""
    target = tmp_path / "secret.bin"
    target.write_bytes(b"classified")

    with pytest.raises(ValueError):
        secure_delete(target, passes=0)


def test_secure_delete_requires_regular_file(tmp_path: Path) -> None:
    """Raise ValueError when the target path is a directory rather than a file."""
    directory = tmp_path / "folder"
    directory.mkdir()

    with pytest.raises(ValueError):
        secure_delete(directory)


def test_secure_delete_removes_zero_length_file(tmp_path: Path) -> None:
    """Remove a zero-length file and report the dedicated success message."""
    target = tmp_path / "empty.bin"
    target.touch()

    report = secure_delete(target, method=SecureDeleteMethod.OVERWRITE, passes=1)

    assert report.success is True
    assert report.message == "Zero-length file removed."
    assert not target.exists()


def test_secure_delete_reports_overwrite_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Report OVERWRITE failure and keep the file when fsync raises OSError."""
    target = tmp_path / "secret.bin"
    target.write_bytes(b"classified")

    def fail_fsync(_descriptor: int) -> None:  # pragma: no cover - simple helper
        raise OSError("fsync failed")

    monkeypatch.setattr(SECURE_DELETE_MODULE.os, "fsync", fail_fsync)

    report = secure_delete(target, method=SecureDeleteMethod.OVERWRITE, passes=1)

    assert report.success is False
    assert report.method is SecureDeleteMethod.OVERWRITE
    assert report.message == "fsync failed"
    assert target.exists()


def test_secure_delete_command_fallback_preserves_method(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Ensure COMMAND mode keeps its method when overwrite fallback fails."""

    target = tmp_path / "secret.bin"
    target.write_bytes(b"classified")

    monkeypatch.setattr(SECURE_DELETE_MODULE, "_build_platform_command", lambda *_, **__: None)

    def fake_overwrite(*_: Any, **__: Any) -> SecureDeleteReport:
        return SecureDeleteReport(
            success=False,
            method=SecureDeleteMethod.OVERWRITE,
            passes=1,
            message="overwrite failed",
        )

    monkeypatch.setattr(SECURE_DELETE_MODULE, "_overwrite_and_remove", fake_overwrite)

    report = secure_delete(target, method=SecureDeleteMethod.COMMAND, passes=1)

    assert report.success is False
    assert report.method is SecureDeleteMethod.COMMAND
    assert report.message == "overwrite failed"


def test_build_platform_command_returns_none_without_tools(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Ensure _build_platform_command returns None when no helper binaries exist."""

    monkeypatch.setattr(SECURE_DELETE_MODULE.platform, "system", lambda: "Linux")
    monkeypatch.setattr(SECURE_DELETE_MODULE.shutil, "which", lambda _: None)

    command = SECURE_DELETE_MODULE._build_platform_command(tmp_path / "secret.bin", passes=1, zero_last_pass=True)

    assert command is None
