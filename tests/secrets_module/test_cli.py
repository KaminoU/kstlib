"""Tests for the secrets CLI commands."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from subprocess import CompletedProcess
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

# Mark all tests in this module as CLI tests (excluded from main tox/CI runs)
# Run with: tox -e cli OR pytest -m cli
pytestmark = pytest.mark.cli

from kstlib.cli.commands.secrets import secrets_app
from kstlib.cli.commands.secrets.common import (
    EncryptCommandOptions,
    SecureDeleteCLIOptions,
    _get_secure_delete_settings,
    _normalize_method,
    _resolve_secure_delete_settings,
    resolve_sops_binary,
    run_sops_command,
    shred_file,
)
from kstlib.cli.commands.secrets.decrypt import _build_decrypt_args
from kstlib.cli.commands.secrets.doctor import (
    _check_age_key,
    _check_sops_config,
    _create_sops_config,
    _ensure_age_key,
    _ensure_sops_config,
    _generate_age_key,
    _get_default_sops_paths,
    _read_existing_public_key,
)
from kstlib.cli.commands.secrets.encrypt import (
    _build_encrypt_args,
    _maybe_print_encrypt_output,
)
from kstlib.cli.common import exit_error
from kstlib.config.exceptions import ConfigNotLoadedError
from kstlib.utils.secure_delete import SecureDeleteMethod, SecureDeleteReport

# Import modules directly to avoid shadowing by __init__.py exports (for monkeypatching)
secrets_common_mod = importlib.import_module("kstlib.cli.commands.secrets.common")
decrypt_mod = importlib.import_module("kstlib.cli.commands.secrets.decrypt")
doctor_mod = importlib.import_module("kstlib.cli.commands.secrets.doctor")
encrypt_mod = importlib.import_module("kstlib.cli.commands.secrets.encrypt")
shred_mod = importlib.import_module("kstlib.cli.commands.secrets.shred")
cli_common_mod = importlib.import_module("kstlib.cli.common")


@pytest.fixture(name="runner")
def runner_fixture() -> CliRunner:
    return CliRunner()


def test_doctor_reports_ready(monkeypatch: pytest.MonkeyPatch, runner: CliRunner, tmp_path: Any) -> None:
    """Test doctor reports ready when all age components are available."""
    monkeypatch.setattr(doctor_mod.shutil, "which", lambda _: "/usr/bin/sops")

    class DummyBackend:  # pylint: disable=too-few-public-methods
        pass

    dummy_keyring = SimpleNamespace(get_keyring=lambda: DummyBackend())
    monkeypatch.setitem(sys.modules, "keyring", dummy_keyring)

    fake_config = SimpleNamespace(secrets=SimpleNamespace(to_dict=lambda: {"providers": []}))
    monkeypatch.setattr(doctor_mod, "get_config", lambda: fake_config)

    # Create a mock .sops.yaml with age backend
    sops_config = tmp_path / ".sops.yaml"
    sops_config.write_text("creation_rules:\n  - age: age1test\n", encoding="utf-8")
    monkeypatch.setattr(doctor_mod, "_find_sops_config_path", lambda: sops_config)

    # Mock all subsystem checks to return "available" status
    monkeypatch.setattr(
        doctor_mod,
        "_check_sops_config",
        lambda: {"component": "sops_config", "status": "available", "details": "/mock/.sops.yaml"},
    )
    monkeypatch.setattr(
        doctor_mod,
        "_check_age_key",
        lambda: {"component": "age_key", "status": "available", "details": "/mock/keys.txt"},
    )
    monkeypatch.setattr(
        doctor_mod,
        "_check_age_key_consistency",
        lambda: {"component": "age_consistency", "status": "available", "details": "Key matches .sops.yaml recipient"},
    )
    # Note: GPG and KMS checks are no longer called when only age backend is detected

    result = runner.invoke(secrets_app, ["doctor"])

    assert result.exit_code == 0
    assert "Secrets subsystem ready (backend: age)." in result.stdout


def test_doctor_uses_configured_sops_binary(monkeypatch: pytest.MonkeyPatch, runner: CliRunner) -> None:
    captured: list[str] = []

    def fake_which(binary: str) -> str | None:
        captured.append(binary)
        if binary == "age-keygen":
            return "/usr/bin/age-keygen"
        return "/usr/bin/sops"

    monkeypatch.setattr(doctor_mod.shutil, "which", fake_which)

    class DummyBackend:  # pylint: disable=too-few-public-methods
        pass

    dummy_keyring = SimpleNamespace(get_keyring=lambda: DummyBackend())
    monkeypatch.setitem(sys.modules, "keyring", dummy_keyring)

    fake_config = SimpleNamespace(secrets=SimpleNamespace(to_dict=lambda: {"sops": {"binary": "custom-sops"}}))
    monkeypatch.setattr(secrets_common_mod, "get_config", lambda: fake_config)

    monkeypatch.setattr(
        doctor_mod,
        "_check_sops_config",
        lambda: {"component": "sops_config", "status": "available", "details": "/mock/.sops.yaml"},
    )
    monkeypatch.setattr(
        doctor_mod,
        "_check_age_key",
        lambda: {"component": "age_key", "status": "available", "details": "/mock/keys.txt"},
    )

    result = runner.invoke(secrets_app, ["doctor"])

    assert result.exit_code == 0
    assert "custom-sops" in captured


def test_doctor_fails_when_sops_missing(monkeypatch: pytest.MonkeyPatch, runner: CliRunner) -> None:
    monkeypatch.setattr(doctor_mod.shutil, "which", lambda _: None)
    monkeypatch.setattr(doctor_mod, "get_config", lambda: SimpleNamespace(secrets=None))

    original_import = __import__

    def fake_import(name: str, *args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        if name == "keyring":
            raise ImportError
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    result = runner.invoke(secrets_app, ["doctor"])

    assert result.exit_code == 1
    assert "Executable" in result.stdout


def test_encrypt_writes_to_stdout(monkeypatch: pytest.MonkeyPatch, runner: CliRunner, tmp_path: Any) -> None:
    cleartext = tmp_path / "secrets.yml"
    cleartext.write_text("token: plain", encoding="utf-8")

    completed = CompletedProcess(["sops"], 0, stdout="encrypted-data\n", stderr="")
    monkeypatch.setattr(encrypt_mod, "run_sops_command", lambda *args, **kwargs: completed)

    result = runner.invoke(secrets_app, ["encrypt", str(cleartext)])

    assert result.exit_code == 0
    assert "Encrypted secrets written to stdout." in result.stdout
    assert "Cleartext source" in result.stdout
    assert "encrypted-data" in result.stdout


def test_encrypt_errors_when_sops_missing(monkeypatch: pytest.MonkeyPatch, runner: CliRunner, tmp_path: Any) -> None:
    cleartext = tmp_path / "secrets.yml"
    cleartext.write_text("token: plain", encoding="utf-8")

    monkeypatch.setattr(
        encrypt_mod,
        "run_sops_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("sops")),
    )

    result = runner.invoke(secrets_app, ["encrypt", str(cleartext)])

    assert result.exit_code == 1
    assert "SOPS binary" in result.stdout


def test_decrypt_writes_to_stdout(monkeypatch: pytest.MonkeyPatch, runner: CliRunner, tmp_path: Any) -> None:
    encrypted = tmp_path / "secrets.sops.yml"
    encrypted.write_text("dummy", encoding="utf-8")

    completed = CompletedProcess(["sops"], 0, stdout="plain-data\n", stderr="")
    monkeypatch.setattr(decrypt_mod, "run_sops_command", lambda *args, **kwargs: completed)

    result = runner.invoke(secrets_app, ["decrypt", str(encrypted)])

    assert result.exit_code == 0
    assert "Decrypted secrets written to stdout." in result.stdout
    assert "plain-data" in result.stdout


def test_decrypt_errors_when_sops_missing(monkeypatch: pytest.MonkeyPatch, runner: CliRunner, tmp_path: Any) -> None:
    encrypted = tmp_path / "secrets.sops.yml"
    encrypted.write_text("dummy", encoding="utf-8")

    monkeypatch.setattr(
        decrypt_mod,
        "run_sops_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("sops")),
    )

    result = runner.invoke(secrets_app, ["decrypt", str(encrypted)])

    assert result.exit_code == 1
    assert "SOPS binary" in result.stdout


def test_doctor_warns_when_config_missing(monkeypatch: pytest.MonkeyPatch, runner: CliRunner) -> None:
    monkeypatch.setattr(doctor_mod.shutil, "which", lambda _: "/usr/bin/sops")

    class DummyBackend:  # pylint: disable=too-few-public-methods
        pass

    dummy_keyring = SimpleNamespace(get_keyring=lambda: DummyBackend())
    dummy_boto3 = SimpleNamespace(__version__="1.34.0")

    def fake_import(name: str, package: str | None = None) -> Any:  # pylint: disable=unused-argument
        if name == "keyring":
            return dummy_keyring
        if name == "boto3":
            return dummy_boto3
        raise ImportError(f"No module named '{name}'")

    monkeypatch.setattr(doctor_mod.importlib, "import_module", fake_import)
    monkeypatch.setattr(doctor_mod, "get_config", lambda: (_ for _ in ()).throw(ConfigNotLoadedError()))
    # Mock GPG checks to return available (to avoid subprocess calls)
    monkeypatch.setattr(
        doctor_mod,
        "_check_gpg_binary",
        lambda: {"component": "gpg", "status": "available", "details": "/usr/bin/gpg"},
    )
    monkeypatch.setattr(
        doctor_mod,
        "_check_gpg_keys",
        lambda: {"component": "gpg_keys", "status": "available", "details": "1 secret key(s)"},
    )
    monkeypatch.setattr(
        doctor_mod,
        "_check_aws_credentials",
        lambda: {"component": "aws_credentials", "status": "available", "details": "env vars"},
    )

    result = runner.invoke(secrets_app, ["doctor"])

    assert result.exit_code == 0
    assert "Secrets subsystem issues" in result.stdout
    assert "warning" in result.stdout.lower()


def test_encrypt_refuses_to_overwrite_without_force(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    tmp_path: Any,
) -> None:
    cleartext = tmp_path / "secrets.yml"
    cleartext.write_text("token: plain", encoding="utf-8")
    output = tmp_path / "encrypted.sops.yml"
    output.write_text("existing", encoding="utf-8")

    monkeypatch.setattr(
        encrypt_mod,
        "run_sops_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not run")),
    )

    result = runner.invoke(secrets_app, ["encrypt", str(cleartext), "--out", str(output)])

    assert result.exit_code == 1
    assert "Refuse to overwrite" in result.stdout


def test_encrypt_reports_non_zero_exit(monkeypatch: pytest.MonkeyPatch, runner: CliRunner, tmp_path: Any) -> None:
    cleartext = tmp_path / "secrets.yml"
    cleartext.write_text("token: plain", encoding="utf-8")

    completed = CompletedProcess(["sops"], 2, stdout="", stderr="boom")
    monkeypatch.setattr(encrypt_mod, "run_sops_command", lambda *args, **kwargs: completed)

    result = runner.invoke(secrets_app, ["encrypt", str(cleartext)])

    assert result.exit_code == 1
    assert "boom" in result.stdout


def test_decrypt_refuses_to_overwrite_without_force(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    tmp_path: Any,
) -> None:
    encrypted = tmp_path / "secrets.sops.yml"
    encrypted.write_text("encrypted", encoding="utf-8")
    output = tmp_path / "decrypted.yml"
    output.write_text("existing", encoding="utf-8")

    monkeypatch.setattr(
        decrypt_mod,
        "run_sops_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not run")),
    )

    result = runner.invoke(secrets_app, ["decrypt", str(encrypted), "--out", str(output)])

    assert result.exit_code == 1
    assert "Refuse to overwrite" in result.stdout


def test_decrypt_reports_non_zero_exit(monkeypatch: pytest.MonkeyPatch, runner: CliRunner, tmp_path: Any) -> None:
    encrypted = tmp_path / "secrets.sops.yml"
    encrypted.write_text("encrypted", encoding="utf-8")

    completed = CompletedProcess(["sops"], 3, stdout="", stderr="bad decrypt")
    monkeypatch.setattr(decrypt_mod, "run_sops_command", lambda *args, **kwargs: completed)

    result = runner.invoke(secrets_app, ["decrypt", str(encrypted)])

    assert result.exit_code == 1
    assert "bad decrypt" in result.stdout


def test_encrypt_quiet_suppresses_output(monkeypatch: pytest.MonkeyPatch, runner: CliRunner, tmp_path: Any) -> None:
    cleartext = tmp_path / "secrets.yml"
    cleartext.write_text("token: plain", encoding="utf-8")

    completed = CompletedProcess(["sops"], 0, stdout="ignored\n", stderr="")
    monkeypatch.setattr(encrypt_mod, "run_sops_command", lambda *args, **kwargs: completed)

    result = runner.invoke(secrets_app, ["encrypt", str(cleartext), "--quiet"])

    assert result.exit_code == 0
    assert result.stdout.strip() == ""


def test_encrypt_with_shred_removes_cleartext(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    tmp_path: Any,
) -> None:
    cleartext = tmp_path / "secrets.yml"
    cleartext.write_text("token: plain", encoding="utf-8")

    completed = CompletedProcess(["sops"], 0, stdout="", stderr="")
    monkeypatch.setattr(encrypt_mod, "run_sops_command", lambda *args, **kwargs: completed)

    result = runner.invoke(
        secrets_app,
        [
            "encrypt",
            str(cleartext),
            "--shred",
            "--quiet",
            "--shred-passes",
            "1",
        ],
    )

    assert result.exit_code == 0
    assert not cleartext.exists()
    assert result.stdout.strip() == ""


def test_shred_command_requires_confirmation(runner: CliRunner, tmp_path: Any) -> None:
    target = tmp_path / "secrets.yml"
    target.write_text("token", encoding="utf-8")

    result = runner.invoke(secrets_app, ["shred", str(target)], input="n\n")

    assert result.exit_code == 1
    assert target.exists()
    assert "Shred aborted" in result.stdout


def test_shred_command_force(runner: CliRunner, tmp_path: Any) -> None:
    target = tmp_path / "secrets.yml"
    target.write_text("token", encoding="utf-8")

    result = runner.invoke(secrets_app, ["shred", str(target), "--force"])

    assert result.exit_code == 0
    assert not target.exists()
    assert "Secret file" in result.stdout


def test_shred_command_reports_failure(monkeypatch: pytest.MonkeyPatch, runner: CliRunner, tmp_path: Any) -> None:
    target = tmp_path / "secrets.yml"
    target.write_text("token", encoding="utf-8")

    monkeypatch.setattr(
        shred_mod,
        "shred_file",
        lambda *args, **kwargs: SecureDeleteReport(
            success=False,
            method=SecureDeleteMethod.AUTO,
            passes=3,
            message="Failed intentionally",
        ),
    )

    result = runner.invoke(secrets_app, ["shred", str(target), "--force"])

    assert result.exit_code == 1
    assert "Failed intentionally" in result.stdout


def test_encrypt_shred_failure_aborts(monkeypatch: pytest.MonkeyPatch, runner: CliRunner, tmp_path: Any) -> None:
    cleartext = tmp_path / "secrets.yml"
    cleartext.write_text("token: plain", encoding="utf-8")

    completed = CompletedProcess(["sops"], 0, stdout="", stderr="")
    monkeypatch.setattr(encrypt_mod, "run_sops_command", lambda *args, **kwargs: completed)

    monkeypatch.setattr(
        encrypt_mod,
        "shred_file",
        lambda *args, **kwargs: SecureDeleteReport(
            success=False,
            method=SecureDeleteMethod.OVERWRITE,
            passes=3,
            message="boom",
        ),
    )

    result = runner.invoke(secrets_app, ["encrypt", str(cleartext), "--shred"])

    assert result.exit_code == 1
    assert "Failed to remove cleartext source" in result.stdout


def test_encrypt_shred_passes_options(monkeypatch: pytest.MonkeyPatch, runner: CliRunner, tmp_path: Any) -> None:
    cleartext = tmp_path / "secrets.yml"
    cleartext.write_text("token: plain", encoding="utf-8")

    completed = CompletedProcess(["sops"], 0, stdout="", stderr="")
    monkeypatch.setattr(encrypt_mod, "run_sops_command", lambda *args, **kwargs: completed)

    captured: dict[str, Any] = {}

    def fake_shred(
        _target: Any,
        *,
        method: str | None = None,
        passes: int | None = None,
        zero_last_pass: bool | None = None,
        chunk_size: int | None = None,
    ) -> SecureDeleteReport:
        captured.update(
            {
                "method": method,
                "passes": passes,
                "zero_last_pass": zero_last_pass,
                "chunk_size": chunk_size,
            }
        )
        return SecureDeleteReport(
            success=True,
            method=SecureDeleteMethod.OVERWRITE,
            passes=passes or 1,
        )

    monkeypatch.setattr(encrypt_mod, "shred_file", fake_shred)

    result = runner.invoke(
        secrets_app,
        [
            "encrypt",
            str(cleartext),
            "--shred",
            "--shred-method",
            "overwrite",
            "--shred-passes",
            "5",
            "--shred-no-zero-last-pass",
            "--shred-chunk-size",
            "2048",
        ],
    )

    assert result.exit_code == 0
    assert captured == {
        "method": "overwrite",
        "passes": 5,
        "zero_last_pass": False,
        "chunk_size": 2048,
    }


def test_encrypt_uses_config_option(monkeypatch: pytest.MonkeyPatch, runner: CliRunner, tmp_path: Any) -> None:
    cleartext = tmp_path / "secrets.yml"
    cleartext.write_text("token: plain", encoding="utf-8")
    config_path = tmp_path / "custom.sops.yaml"
    config_path.write_text("creation_rules: []", encoding="utf-8")

    captured: dict[str, Any] = {}

    def fake_run(_binary: str, arguments: list[str]) -> CompletedProcess[str]:
        captured["arguments"] = arguments
        return CompletedProcess(["sops"], 0, stdout="", stderr="")

    monkeypatch.setattr(encrypt_mod, "run_sops_command", fake_run)

    result = runner.invoke(
        secrets_app,
        ["encrypt", str(cleartext), "--config", str(config_path), "--quiet"],
    )

    assert result.exit_code == 0
    assert captured["arguments"][:3] == ["--config", str(config_path), "--encrypt"]


def test_encrypt_uses_default_config_when_present(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    tmp_path: Any,
) -> None:
    cleartext = tmp_path / "secrets.yml"
    cleartext.write_text("token: plain", encoding="utf-8")
    default_config = tmp_path / ".sops.yaml"
    default_config.write_text("creation_rules: []", encoding="utf-8")

    captured: dict[str, Any] = {}

    def fake_run(_binary: str, arguments: list[str]) -> CompletedProcess[str]:
        captured["arguments"] = arguments
        return CompletedProcess(["sops"], 0, stdout="", stderr="")

    monkeypatch.setattr(encrypt_mod, "run_sops_command", fake_run)
    monkeypatch.setattr(encrypt_mod.Path, "home", lambda: tmp_path)

    result = runner.invoke(
        secrets_app,
        ["encrypt", str(cleartext), "--quiet"],
    )

    assert result.exit_code == 0
    assert captured["arguments"][:3] == ["--config", str(default_config), "--encrypt"]


def test_shred_command_passes_options(monkeypatch: pytest.MonkeyPatch, runner: CliRunner, tmp_path: Any) -> None:
    target = tmp_path / "secrets.yml"
    target.write_text("token", encoding="utf-8")

    captured: dict[str, Any] = {}

    def fake_shred(
        _target: Any,
        *,
        method: str | None = None,
        passes: int | None = None,
        zero_last_pass: bool | None = None,
        chunk_size: int | None = None,
    ) -> SecureDeleteReport:
        captured.update(
            {
                "method": method,
                "passes": passes,
                "zero_last_pass": zero_last_pass,
                "chunk_size": chunk_size,
            }
        )
        return SecureDeleteReport(
            success=True,
            method=SecureDeleteMethod.COMMAND,
            passes=passes or 3,
            command=["shred"],
        )

    monkeypatch.setattr(shred_mod, "shred_file", fake_shred)

    result = runner.invoke(
        secrets_app,
        [
            "shred",
            str(target),
            "--force",
            "--method",
            "command",
            "--passes",
            "7",
            "--no-zero-last-pass",
            "--chunk-size",
            "4096",
        ],
    )

    assert result.exit_code == 0
    assert captured == {
        "method": "command",
        "passes": 7,
        "zero_last_pass": False,
        "chunk_size": 4096,
    }
    # Rich may wrap text across lines, so check key parts separately
    assert "removed" in result.stdout
    assert "(7 passes)" in result.stdout
    assert "shred" in result.stdout


def test_doctor_reports_missing_keyring(monkeypatch: pytest.MonkeyPatch, runner: CliRunner) -> None:
    monkeypatch.setattr(doctor_mod.shutil, "which", lambda _: "/usr/bin/sops")

    def fake_import(name: str) -> Any:
        if name == "keyring":
            raise ImportError
        return None

    monkeypatch.setattr(doctor_mod.importlib, "import_module", fake_import)
    fake_config = SimpleNamespace(secrets=None)
    monkeypatch.setattr(doctor_mod, "get_config", lambda: fake_config)

    result = runner.invoke(secrets_app, ["doctor"])

    assert result.exit_code == 1
    assert "keyring" in result.stdout.lower()


def test_run_sops_command_raises_when_binary_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(secrets_common_mod.shutil, "which", lambda _: None)

    with pytest.raises(FileNotFoundError):
        run_sops_command("sops", ["--version"])


def test_run_sops_command_invokes_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(secrets_common_mod.shutil, "which", lambda _: "/usr/bin/sops")

    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **_: Any) -> CompletedProcess[str]:
        captured["command"] = command
        return CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(secrets_common_mod, "run", fake_run)

    result = run_sops_command("sops", ["--help"])

    assert result.returncode == 0
    assert captured["command"] == ["/usr/bin/sops", "--help"]


def test_build_encrypt_args_includes_optional_flags(tmp_path: Any) -> None:
    source = Path(tmp_path) / "input.yml"
    out = Path(tmp_path) / "output.sops.yml"
    options = EncryptCommandOptions(
        out=out,
        binary="sops",
        config=None,
        formats=("yaml", "json"),
        force=False,
        quiet=False,
        shred=SecureDeleteCLIOptions(
            enabled=False,
            method=None,
            passes=None,
            zero_last_pass=None,
            chunk_size=None,
        ),
        age_recipients=("age1", "age2"),
        kms_keys=("arn:aws:kms:region:account:key/key-id",),
        data_keys=("alias/sops",),
    )

    args = _build_encrypt_args(source, options)

    assert args == [
        "--encrypt",
        "--output",
        str(out),
        "--input-type",
        "yaml",
        "--output-type",
        "json",
        "--age",
        "age1",
        "--age",
        "age2",
        "--kms",
        "arn:aws:kms:region:account:key/key-id",
        "--key",
        "alias/sops",
        str(source),
    ]


def test_build_encrypt_args_includes_config(tmp_path: Any) -> None:
    source = Path(tmp_path) / "input.yml"
    config = Path(tmp_path) / "config.yaml"
    options = EncryptCommandOptions(
        out=None,
        binary="sops",
        config=config,
        formats=("auto", "auto"),
        force=False,
        quiet=False,
        shred=SecureDeleteCLIOptions(
            enabled=False,
            method=None,
            passes=None,
            zero_last_pass=None,
            chunk_size=None,
        ),
        age_recipients=(),
        kms_keys=(),
        data_keys=(),
    )

    args = _build_encrypt_args(source, options)

    assert args[:3] == ["--config", str(config), "--encrypt"]
    assert args[-1] == str(source)


def test_build_decrypt_args_includes_output(tmp_path: Any) -> None:
    source = Path(tmp_path) / "secrets.sops.yml"
    out = Path(tmp_path) / "plain.yml"

    args = _build_decrypt_args(source, out)

    assert args == ["--decrypt", "--output", str(out), str(source)]


def test_encrypt_quiet_error_uses_plain_output(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    tmp_path: Any,
) -> None:
    """Ensure quiet encrypt errors bypass Rich rendering."""

    def fail_render(*_: Any, **__: Any) -> None:
        raise AssertionError("render_result should not run")

    monkeypatch.setattr(encrypt_mod, "render_result", fail_render)

    cleartext = tmp_path / "secrets.yml"
    cleartext.write_text("token: plain", encoding="utf-8")
    output = tmp_path / "secrets.sops.yml"
    output.write_text("existing", encoding="utf-8")

    result = runner.invoke(
        secrets_app,
        ["encrypt", str(cleartext), "--out", str(output), "--quiet"],
    )

    assert result.exit_code == 1
    assert "Refuse to overwrite" in result.stdout


def test_decrypt_quiet_mode_suppresses_rendering(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    tmp_path: Any,
) -> None:
    """Ensure decrypt quiet exits early without rendering panels."""

    def fail_render(*_: Any, **__: Any) -> None:
        raise AssertionError("render_result should not run")

    monkeypatch.setattr(decrypt_mod, "render_result", fail_render)

    encrypted = tmp_path / "secrets.sops.yml"
    encrypted.write_text("encrypted", encoding="utf-8")

    completed = CompletedProcess(["sops"], 0, stdout="plain-data\n", stderr="")
    monkeypatch.setattr(decrypt_mod, "run_sops_command", lambda *args, **kwargs: completed)

    result = runner.invoke(secrets_app, ["decrypt", str(encrypted), "--quiet"])

    assert result.exit_code == 0
    assert result.stdout.strip() == ""


def test_shred_quiet_mode_exits_cleanly(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    tmp_path: Any,
) -> None:
    """Ensure shred quiet mode does not trigger Rich rendering."""

    def fail_render(*_: Any, **__: Any) -> None:
        raise AssertionError("render_result should not run")

    monkeypatch.setattr(shred_mod, "render_result", fail_render)

    target = tmp_path / "secrets.yml"
    target.write_text("token", encoding="utf-8")

    result = runner.invoke(secrets_app, ["shred", str(target), "--force", "--quiet"])

    assert result.exit_code == 0
    assert result.stdout.strip() == ""
    assert not target.exists()


def test_maybe_print_encrypt_output_skips_when_out(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """Ensure stdout from sops is ignored when an output file is set."""

    captured: list[str] = []
    monkeypatch.setattr(encrypt_mod.console, "print", lambda *args, **kwargs: captured.append(str(args[0])))

    options = EncryptCommandOptions(
        out=tmp_path / "encrypted.sops.yml",
        binary="sops",
        config=None,
        formats=("auto", "auto"),
        force=False,
        quiet=False,
        shred=SecureDeleteCLIOptions(
            enabled=False,
            method=None,
            passes=None,
            zero_last_pass=None,
            chunk_size=None,
        ),
        age_recipients=(),
        kms_keys=(),
        data_keys=(),
    )
    completed = CompletedProcess(["sops"], 0, stdout="ciphertext\n", stderr="")

    _maybe_print_encrypt_output(completed, options)

    assert not captured


def test_check_sops_config_warns_for_missing_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """Ensure SOPS_CONFIG pointing to a missing file reports a warning."""

    missing = tmp_path / "missing.sops.yaml"
    monkeypatch.setenv("SOPS_CONFIG", str(missing))
    monkeypatch.setattr(doctor_mod.Path, "home", lambda: tmp_path)

    result = _check_sops_config()

    assert result["status"] == "warning"
    assert "missing" in result["details"]


def test_check_sops_config_uses_default_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """Ensure the default ~/.sops.yaml is detected when present."""
    # Create home config
    default_config = tmp_path / ".sops.yaml"
    default_config.write_text("creation_rules: []", encoding="utf-8")

    # Create a subdir to work from (walk-up will find config at tmp_path)
    subdir = tmp_path / "project"
    subdir.mkdir()

    monkeypatch.delenv("SOPS_CONFIG", raising=False)
    monkeypatch.chdir(subdir)

    with patch("pathlib.Path.home", return_value=tmp_path):
        result = _check_sops_config()

    assert result["status"] == "available"
    assert str(default_config) in result["details"]


def test_check_age_key_warns_for_missing_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """Ensure SOPS_AGE_KEY_FILE pointing to a missing file emits a warning."""

    missing = tmp_path / "missing-age-key"
    monkeypatch.setenv("SOPS_AGE_KEY_FILE", str(missing))
    monkeypatch.delenv("APPDATA", raising=False)  # Disable Windows path check
    monkeypatch.setattr(doctor_mod.Path, "home", lambda: tmp_path)

    result = _check_age_key()

    assert result["status"] == "warning"
    assert "missing file" in result["details"]


def test_check_age_key_detects_default_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """Ensure ~/.config/sops/age/keys.txt is detected when present."""

    keys_path = tmp_path / ".config" / "sops" / "age" / "keys.txt"
    keys_path.parent.mkdir(parents=True, exist_ok=True)
    keys_path.write_text("age-key", encoding="utf-8")
    monkeypatch.delenv("SOPS_AGE_KEY_FILE", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)  # Disable Windows path check
    monkeypatch.setattr(doctor_mod.Path, "home", lambda: tmp_path)

    result = _check_age_key()

    assert result["status"] == "available"
    assert str(keys_path) in result["details"]


def test_shred_file_reports_invalid_passes(tmp_path: Any) -> None:
    """Ensure shred_file reports invalid secure delete passes."""

    target = tmp_path / "secrets.yml"
    target.write_text("token", encoding="utf-8")

    report = shred_file(target, passes=0)

    assert report.success is False
    assert "passes" in (report.message or "")


def test_shred_file_reports_secure_delete_value_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """Ensure shred_file propagates secure_delete errors as reports."""

    target = tmp_path / "secrets.yml"
    target.write_text("token", encoding="utf-8")

    def fail_secure_delete(*_: Any, **__: Any) -> SecureDeleteReport:
        raise ValueError("boom")

    monkeypatch.setattr(secrets_common_mod, "secure_delete", fail_secure_delete)

    report = shred_file(target)

    assert report.success is False
    assert report.message == "boom"


def test_resolve_secure_delete_settings_rejects_invalid_passes() -> None:
    """Ensure passes lower than one are rejected."""

    with pytest.raises(ValueError):
        _resolve_secure_delete_settings(
            method=None,
            passes=0,
            zero_last_pass=None,
            chunk_size=None,
        )


def test_resolve_secure_delete_settings_rejects_invalid_chunk_size() -> None:
    """Ensure chunk sizes lower than one raise errors."""

    with pytest.raises(ValueError):
        _resolve_secure_delete_settings(
            method=None,
            passes=1,
            zero_last_pass=None,
            chunk_size=0,
        )


def test_normalize_method_variants() -> None:
    """Ensure _normalize_method handles enums, strings, and errors."""

    assert _normalize_method(None) is SecureDeleteMethod.AUTO
    assert _normalize_method(SecureDeleteMethod.COMMAND) is SecureDeleteMethod.COMMAND
    assert _normalize_method("overwrite") is SecureDeleteMethod.OVERWRITE
    with pytest.raises(ValueError):
        _normalize_method("invalid")


def test_get_secure_delete_settings_handles_missing_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure missing global config returns an empty mapping."""

    monkeypatch.setattr(
        secrets_common_mod,
        "get_config",
        lambda: (_ for _ in ()).throw(ConfigNotLoadedError()),
    )

    assert not _get_secure_delete_settings()


def test_get_secure_delete_settings_skips_unknown_nodes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure nodes without dict/to_dict are ignored while merging settings."""

    utilities = SimpleNamespace(secure_delete=object())
    secrets = SimpleNamespace(secure_delete=SimpleNamespace(to_dict=lambda: {"passes": 7}))
    monkeypatch.setattr(
        secrets_common_mod,
        "get_config",
        lambda: SimpleNamespace(utilities=utilities, secrets=secrets),
    )

    result = _get_secure_delete_settings()

    assert result == {"passes": 7}


# =============================================================================
# Tests for init command and helpers
# =============================================================================


class TestGetDefaultSopsPaths:
    """Tests for _get_default_sops_paths."""

    def test_local_paths(self) -> None:
        """Local mode returns paths in current directory."""
        key_path, config_path = _get_default_sops_paths(local=True)

        assert key_path == Path(".age-key.txt")
        assert config_path == Path(".sops.yaml")

    def test_global_unix_paths(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        """Global mode on Unix returns ~/.config/sops/age/keys.txt."""
        monkeypatch.delenv("APPDATA", raising=False)
        monkeypatch.setattr(doctor_mod.Path, "home", lambda: tmp_path)

        key_path, config_path = _get_default_sops_paths(local=False)

        assert key_path == tmp_path / ".config" / "sops" / "age" / "keys.txt"
        assert config_path == tmp_path / ".sops.yaml"

    @pytest.mark.skipif(os.name != "nt", reason="Windows-specific path test")
    def test_global_windows_paths(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        """Global mode on Windows: keys in %APPDATA%, config in HOME."""
        appdata = tmp_path / "AppData" / "Roaming"
        appdata.mkdir(parents=True)
        home_dir = tmp_path / "Users" / "testuser"
        home_dir.mkdir(parents=True)
        monkeypatch.setenv("APPDATA", str(appdata))
        monkeypatch.setattr(doctor_mod.os, "name", "nt")
        monkeypatch.setattr(doctor_mod.Path, "home", lambda: home_dir)

        key_path, config_path = _get_default_sops_paths(local=False)

        assert key_path == appdata / "sops" / "age" / "keys.txt"
        assert config_path == home_dir / ".sops.yaml"  # Config in HOME, not APPDATA


class TestGenerateAgeKey:
    """Tests for _generate_age_key."""

    def test_success_returns_public_key_from_stderr(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        """Successful generation extracts public key from stderr."""
        key_path = tmp_path / "keys.txt"
        public_key = "age1abc123xyz"

        def fake_run(*_args: Any, **_kwargs: Any) -> CompletedProcess[str]:
            key_path.write_text(f"# public key: {public_key}\nAGE-SECRET-KEY-xxx\n")
            return CompletedProcess([], 0, stdout="", stderr=f"Public key: {public_key}\n")

        monkeypatch.setattr(doctor_mod.shutil, "which", lambda _: "/usr/bin/age-keygen")
        monkeypatch.setattr(doctor_mod, "run", fake_run)

        result = _generate_age_key(key_path)

        assert result == public_key

    def test_success_returns_public_key_from_file(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        """Falls back to reading public key from file when not in stderr."""
        key_path = tmp_path / "keys.txt"
        public_key = "age1fallback"

        def fake_run(*_args: Any, **_kwargs: Any) -> CompletedProcess[str]:
            key_path.write_text(f"# public key: {public_key}\nAGE-SECRET-KEY-xxx\n")
            return CompletedProcess([], 0, stdout="", stderr="")

        monkeypatch.setattr(doctor_mod.shutil, "which", lambda _: "/usr/bin/age-keygen")
        monkeypatch.setattr(doctor_mod, "run", fake_run)

        result = _generate_age_key(key_path)

        assert result == public_key

    def test_missing_binary_returns_none(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        """Missing age-keygen binary returns None."""
        monkeypatch.setattr(doctor_mod.shutil, "which", lambda _: None)

        result = _generate_age_key(tmp_path / "keys.txt")

        assert result is None

    def test_failed_command_returns_none(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        """Failed keygen command returns None."""
        monkeypatch.setattr(doctor_mod.shutil, "which", lambda _: "/usr/bin/age-keygen")
        monkeypatch.setattr(
            doctor_mod,
            "run",
            lambda *a, **k: CompletedProcess([], 1, stdout="", stderr="error"),
        )

        result = _generate_age_key(tmp_path / "keys.txt")

        assert result is None


class TestCreateSopsConfig:
    """Tests for _create_sops_config."""

    def test_creates_config_file(self, tmp_path: Any) -> None:
        """Creates .sops.yaml with correct content."""
        config_path = tmp_path / ".sops.yaml"
        public_key = "age1testkey123"

        result = _create_sops_config(config_path, public_key)

        assert result is True
        assert config_path.exists()
        content = config_path.read_text()
        assert public_key in content
        assert "encrypted_regex" in content

    def test_creates_parent_directories(self, tmp_path: Any) -> None:
        """Creates parent directories if needed."""
        config_path = tmp_path / "nested" / "dir" / ".sops.yaml"

        result = _create_sops_config(config_path, "age1key")

        assert result is True
        assert config_path.exists()

    def test_returns_false_on_oserror(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        """Returns False when write fails."""
        config_path = tmp_path / ".sops.yaml"

        def fail_write(*_: Any, **__: Any) -> None:
            raise OSError("Permission denied")

        monkeypatch.setattr(Path, "write_text", fail_write)

        result = _create_sops_config(config_path, "age1key")

        assert result is False


class TestReadExistingPublicKey:
    """Tests for _read_existing_public_key."""

    def test_reads_public_key(self, tmp_path: Any) -> None:
        """Extracts public key from age key file."""
        key_path = tmp_path / "keys.txt"
        key_path.write_text("# public key: age1abc123\nAGE-SECRET-KEY-xxx\n")

        result = _read_existing_public_key(key_path)

        assert result == "age1abc123"

    def test_returns_none_for_missing_file(self, tmp_path: Any) -> None:
        """Returns None when file doesn't exist."""
        result = _read_existing_public_key(tmp_path / "missing.txt")

        assert result is None

    def test_returns_none_when_no_public_key(self, tmp_path: Any) -> None:
        """Returns None when file exists but has no public key line."""
        key_path = tmp_path / "keys.txt"
        key_path.write_text("AGE-SECRET-KEY-xxx\n")

        result = _read_existing_public_key(key_path)

        assert result is None


class TestExitError:
    """Tests for exit_error."""

    def test_raises_typer_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Raises typer.Exit with code 1."""
        import typer

        monkeypatch.setattr(cli_common_mod, "render_result", lambda _: None)

        with pytest.raises(typer.Exit) as exc_info:
            exit_error("test error")

        assert exc_info.value.exit_code == 1


class TestEnsureAgeKey:
    """Tests for _ensure_age_key."""

    def test_uses_existing_key(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        """Uses existing key when present and not forced."""
        key_path = tmp_path / "keys.txt"
        key_path.write_text("# public key: age1existing\nAGE-SECRET-KEY-xxx\n")
        monkeypatch.setattr(doctor_mod.console, "print", lambda *a, **k: None)

        public_key, created = _ensure_age_key(key_path, force=False)

        assert public_key == "age1existing"
        assert created is False

    def test_generates_new_key(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        """Generates new key when none exists."""
        key_path = tmp_path / "keys.txt"

        def fake_generate(path: Path) -> str:
            path.write_text("# public key: age1new\nAGE-SECRET-KEY-xxx\n")
            return "age1new"

        monkeypatch.setattr(doctor_mod, "_generate_age_key", fake_generate)

        public_key, created = _ensure_age_key(key_path, force=False)

        assert public_key == "age1new"
        assert created is True

    def test_force_regenerates_key(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        """Force flag regenerates existing key."""
        key_path = tmp_path / "keys.txt"
        key_path.write_text("# public key: age1old\nAGE-SECRET-KEY-xxx\n")

        def fake_generate(path: Path) -> str:
            path.write_text("# public key: age1new\nAGE-SECRET-KEY-xxx\n")
            return "age1new"

        monkeypatch.setattr(doctor_mod, "_generate_age_key", fake_generate)

        public_key, created = _ensure_age_key(key_path, force=True)

        assert public_key == "age1new"
        assert created is True


class TestEnsureSopsConfig:
    """Tests for _ensure_sops_config."""

    def test_creates_new_config(self, tmp_path: Any) -> None:
        """Creates config when none exists."""
        config_path = tmp_path / ".sops.yaml"

        created = _ensure_sops_config(config_path, "age1key", force=False)

        assert created is True
        assert config_path.exists()

    def test_skips_existing_config(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        """Skips creation when config exists and not forced."""
        config_path = tmp_path / ".sops.yaml"
        config_path.write_text("existing config")
        monkeypatch.setattr(doctor_mod.console, "print", lambda *a, **k: None)

        created = _ensure_sops_config(config_path, "age1key", force=False)

        assert created is False
        assert config_path.read_text() == "existing config"

    def test_force_overwrites_config(self, tmp_path: Any) -> None:
        """Force flag overwrites existing config."""
        config_path = tmp_path / ".sops.yaml"
        config_path.write_text("old config")

        created = _ensure_sops_config(config_path, "age1newkey", force=True)

        assert created is True
        assert "age1newkey" in config_path.read_text()


class TestInitCommand:
    """Tests for the init CLI command."""

    def test_init_missing_age_keygen(self, monkeypatch: pytest.MonkeyPatch, runner: CliRunner) -> None:
        """Fails gracefully when age-keygen is not installed."""
        monkeypatch.setattr(doctor_mod.shutil, "which", lambda _: None)

        result = runner.invoke(secrets_app, ["init"])

        assert result.exit_code == 1
        assert "age-keygen not found" in result.stdout

    def test_init_local_creates_files(self, monkeypatch: pytest.MonkeyPatch, runner: CliRunner, tmp_path: Any) -> None:
        """Init --local creates files in current directory."""
        monkeypatch.setattr(doctor_mod.shutil, "which", lambda _: "/usr/bin/age-keygen")
        monkeypatch.chdir(tmp_path)

        def fake_generate(path: Path) -> str:
            path.write_text("# public key: age1local\nAGE-SECRET-KEY-xxx\n")
            return "age1local"

        monkeypatch.setattr(doctor_mod, "_generate_age_key", fake_generate)

        result = runner.invoke(secrets_app, ["init", "--local"])

        assert result.exit_code == 0
        assert (tmp_path / ".age-key.txt").exists()
        assert (tmp_path / ".sops.yaml").exists()
        assert "age1local" in result.stdout

    def test_init_warns_existing_files(self, monkeypatch: pytest.MonkeyPatch, runner: CliRunner, tmp_path: Any) -> None:
        """Warns when all files already exist."""
        monkeypatch.setattr(doctor_mod.shutil, "which", lambda _: "/usr/bin/age-keygen")
        monkeypatch.chdir(tmp_path)

        # Create existing files
        (tmp_path / ".age-key.txt").write_text("# public key: age1exists\nKEY\n")
        (tmp_path / ".sops.yaml").write_text("existing")

        result = runner.invoke(secrets_app, ["init", "--local"])

        assert result.exit_code == 0
        assert "already exist" in result.stdout

    def test_init_force_overwrites(self, monkeypatch: pytest.MonkeyPatch, runner: CliRunner, tmp_path: Any) -> None:
        """Init --force overwrites existing files."""
        monkeypatch.setattr(doctor_mod.shutil, "which", lambda _: "/usr/bin/age-keygen")
        monkeypatch.chdir(tmp_path)

        # Create existing files
        (tmp_path / ".age-key.txt").write_text("# public key: age1old\nOLD\n")
        (tmp_path / ".sops.yaml").write_text("old config")

        def fake_generate(path: Path) -> str:
            path.write_text("# public key: age1new\nAGE-SECRET-KEY-xxx\n")
            return "age1new"

        monkeypatch.setattr(doctor_mod, "_generate_age_key", fake_generate)

        result = runner.invoke(secrets_app, ["init", "--local", "--force"])

        assert result.exit_code == 0
        assert "age1new" in (tmp_path / ".sops.yaml").read_text()


# =============================================================================
# Tests for GPG checks
# =============================================================================


class TestCheckGpgBinary:
    """Tests for _check_gpg_binary."""

    def test_gpg_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns available when gpg is found."""
        from kstlib.cli.commands.secrets.doctor import _check_gpg_binary

        monkeypatch.setattr(doctor_mod.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "gpg" else None)
        monkeypatch.setattr(
            doctor_mod,
            "run",
            lambda *a, **k: CompletedProcess([], 0, stdout="gpg (GnuPG) 2.4.0\n", stderr=""),
        )

        result = _check_gpg_binary()

        assert result["status"] == "available"
        assert "gpg" in result["details"].lower()

    def test_gpg2_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns available when gpg2 is found (gpg not available)."""
        from kstlib.cli.commands.secrets.doctor import _check_gpg_binary

        def which(name: str) -> str | None:
            return "/usr/bin/gpg2" if name == "gpg2" else None

        monkeypatch.setattr(doctor_mod.shutil, "which", which)
        monkeypatch.setattr(
            doctor_mod,
            "run",
            lambda *a, **k: CompletedProcess([], 0, stdout="gpg (GnuPG) 2.4.0\n", stderr=""),
        )

        result = _check_gpg_binary()

        assert result["status"] == "available"

    def test_gpg_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns warning when GPG is not installed."""
        from kstlib.cli.commands.secrets.doctor import _check_gpg_binary

        monkeypatch.setattr(doctor_mod.shutil, "which", lambda _: None)

        result = _check_gpg_binary()

        assert result["status"] == "warning"
        assert "not found" in result["details"].lower()


class TestCheckGpgKeys:
    """Tests for _check_gpg_keys."""

    def test_gpg_keys_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns available when secret keys are found."""
        from kstlib.cli.commands.secrets.doctor import _check_gpg_keys

        gpg_output = """
sec   rsa4096/ABCD1234 2024-01-01 [SC]
      Key fingerprint = ABCD 1234 5678 90AB CDEF
uid           [ultimate] Test User <test@example.com>
ssb   rsa4096/EFGH5678 2024-01-01 [E]
"""
        monkeypatch.setattr(doctor_mod.shutil, "which", lambda _: "/usr/bin/gpg")
        monkeypatch.setattr(
            doctor_mod,
            "run",
            lambda *a, **k: CompletedProcess([], 0, stdout=gpg_output, stderr=""),
        )

        result = _check_gpg_keys()

        assert result["status"] == "available"
        assert "1 secret key" in result["details"]

    def test_no_gpg_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns warning when no secret keys are found."""
        from kstlib.cli.commands.secrets.doctor import _check_gpg_keys

        monkeypatch.setattr(doctor_mod.shutil, "which", lambda _: "/usr/bin/gpg")
        monkeypatch.setattr(
            doctor_mod,
            "run",
            lambda *a, **k: CompletedProcess([], 0, stdout="", stderr=""),
        )

        result = _check_gpg_keys()

        assert result["status"] == "warning"
        assert "no gpg secret keys" in result["details"].lower()

    def test_gpg_not_installed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns warning when GPG is not installed."""
        from kstlib.cli.commands.secrets.doctor import _check_gpg_keys

        monkeypatch.setattr(doctor_mod.shutil, "which", lambda _: None)

        result = _check_gpg_keys()

        assert result["status"] == "warning"
        assert "gpg not installed" in result["details"].lower()


# =============================================================================
# Tests for KMS/AWS checks
# =============================================================================


class TestCheckBoto3:
    """Tests for _check_boto3."""

    def test_boto3_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns available when boto3 is installed."""
        from kstlib.cli.commands.secrets.doctor import _check_boto3

        fake_boto3 = SimpleNamespace(__version__="1.34.0")
        monkeypatch.setattr(doctor_mod.importlib, "import_module", lambda name: fake_boto3)

        result = _check_boto3()

        assert result["status"] == "available"
        assert "1.34.0" in result["details"]

    def test_boto3_not_installed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns warning when boto3 is not installed."""
        from kstlib.cli.commands.secrets.doctor import _check_boto3

        def raise_import_error(name: str) -> Any:
            raise ImportError("No module named 'boto3'")

        monkeypatch.setattr(doctor_mod.importlib, "import_module", raise_import_error)

        result = _check_boto3()

        assert result["status"] == "warning"
        assert "boto3 not installed" in result["details"].lower()


class TestCheckAwsCredentials:
    """Tests for _check_aws_credentials."""

    def test_env_credentials_detected(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        """Detects credentials from environment variables."""
        from kstlib.cli.commands.secrets.doctor import _check_aws_credentials

        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIATEST")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
        monkeypatch.delenv("AWS_PROFILE", raising=False)
        monkeypatch.setattr(doctor_mod.Path, "home", lambda: tmp_path)

        result = _check_aws_credentials()

        assert result["status"] == "available"
        assert "environment variables" in result["details"]

    def test_profile_detected(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        """Detects credentials from AWS_PROFILE."""
        from kstlib.cli.commands.secrets.doctor import _check_aws_credentials

        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        monkeypatch.setenv("AWS_PROFILE", "production")
        monkeypatch.setattr(doctor_mod.Path, "home", lambda: tmp_path)

        result = _check_aws_credentials()

        assert result["status"] == "available"
        assert "profile 'production'" in result["details"]

    def test_credentials_file_detected(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        """Detects credentials from ~/.aws/credentials file."""
        from kstlib.cli.commands.secrets.doctor import _check_aws_credentials

        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        monkeypatch.delenv("AWS_PROFILE", raising=False)

        aws_dir = tmp_path / ".aws"
        aws_dir.mkdir()
        (aws_dir / "credentials").write_text("[default]\naws_access_key_id = AKIA...\n")

        monkeypatch.setattr(doctor_mod.Path, "home", lambda: tmp_path)

        result = _check_aws_credentials()

        assert result["status"] == "available"
        assert "~/.aws/credentials" in result["details"]

    def test_no_credentials(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        """Returns warning when no credentials are detected."""
        from kstlib.cli.commands.secrets.doctor import _check_aws_credentials

        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        monkeypatch.delenv("AWS_PROFILE", raising=False)
        monkeypatch.setattr(doctor_mod.Path, "home", lambda: tmp_path)

        result = _check_aws_credentials()

        assert result["status"] == "warning"
        assert "no aws credentials" in result["details"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# resolve_sops_binary tests
# ─────────────────────────────────────────────────────────────────────────────


class TestResolveSopsBinary:
    """Tests for resolve_sops_binary function."""

    def test_returns_default_when_config_not_loaded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns 'sops' when config is not loaded."""
        monkeypatch.setattr(
            secrets_common_mod, "get_config", lambda: (_ for _ in ()).throw(ConfigNotLoadedError("test"))
        )

        result = resolve_sops_binary()

        assert result == "sops"

    def test_returns_default_when_no_secrets_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns 'sops' when secrets config is missing."""
        mock_config = SimpleNamespace(secrets=None)
        monkeypatch.setattr(secrets_common_mod, "get_config", lambda: mock_config)

        result = resolve_sops_binary()

        assert result == "sops"

    def test_returns_default_when_secrets_has_no_to_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns 'sops' when secrets config has no to_dict method."""
        mock_secrets = "not an object with to_dict"
        mock_config = SimpleNamespace(secrets=mock_secrets)
        monkeypatch.setattr(secrets_common_mod, "get_config", lambda: mock_config)

        result = resolve_sops_binary()

        assert result == "sops"

    def test_returns_default_when_data_not_mapping(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns 'sops' when to_dict returns non-mapping."""
        mock_secrets = SimpleNamespace(to_dict=lambda: "not a mapping")
        mock_config = SimpleNamespace(secrets=mock_secrets)
        monkeypatch.setattr(secrets_common_mod, "get_config", lambda: mock_config)

        result = resolve_sops_binary()

        assert result == "sops"

    def test_returns_binary_from_sops_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns binary from sops.binary config."""
        mock_secrets = SimpleNamespace(to_dict=lambda: {"sops": {"binary": "/usr/local/bin/sops"}})
        mock_config = SimpleNamespace(secrets=mock_secrets)
        monkeypatch.setattr(secrets_common_mod, "get_config", lambda: mock_config)

        result = resolve_sops_binary()

        assert result == "/usr/local/bin/sops"

    def test_returns_binary_from_nested_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns binary from sops.settings.binary config."""
        mock_secrets = SimpleNamespace(to_dict=lambda: {"sops": {"settings": {"binary": "/opt/sops/bin/sops"}}})
        mock_config = SimpleNamespace(secrets=mock_secrets)
        monkeypatch.setattr(secrets_common_mod, "get_config", lambda: mock_config)

        result = resolve_sops_binary()

        assert result == "/opt/sops/bin/sops"

    def test_returns_default_when_sops_config_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns 'sops' when sops config exists but has no binary."""
        mock_secrets = SimpleNamespace(to_dict=lambda: {"sops": {"other_key": "value"}})
        mock_config = SimpleNamespace(secrets=mock_secrets)
        monkeypatch.setattr(secrets_common_mod, "get_config", lambda: mock_config)

        result = resolve_sops_binary()

        assert result == "sops"


# ─────────────────────────────────────────────────────────────────────────────
# _get_secure_delete_settings tests (for line 383 coverage - dict branch)
# ─────────────────────────────────────────────────────────────────────────────


class TestGetSecureDeleteSettingsEdgeCases:
    """Tests for _get_secure_delete_settings to cover dict branch."""

    def test_handles_plain_dict_config_node(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Handles config node that is a plain dict (not object with to_dict)."""
        # Create config where secure_delete is a plain dict, not an object
        mock_secrets = SimpleNamespace(secure_delete={"method": "zero", "passes": 3})
        mock_config = SimpleNamespace(utilities=None, secrets=mock_secrets)
        monkeypatch.setattr(secrets_common_mod, "get_config", lambda: mock_config)

        result = _get_secure_delete_settings()

        assert result["method"] == "zero"
        assert result["passes"] == 3
