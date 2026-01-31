"""Unit tests for filesystem guard helpers in the mail module."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from kstlib.mail.exceptions import MailValidationError
from kstlib.mail.filesystem import (
    MailExternalOverrides,
    MailFilesystemGuards,
    MailGuardRootsOverrides,
)
from kstlib.secure import RELAXED_POLICY


def test_mail_guards_from_sources_honor_config_section(tmp_path: Path) -> None:
    """Ensure configuration mappings set up guardrail roots correctly."""
    attachments_root = tmp_path / "cfg" / "attachments"
    inline_root = tmp_path / "cfg" / "inline"
    templates_root = tmp_path / "cfg" / "templates"
    config = {
        "filesystem": {
            "attachments_root": str(attachments_root),
            "inline_root": str(inline_root),
            "templates_root": str(templates_root),
        }
    }

    guards = MailFilesystemGuards.from_sources(config=config)

    attachments_file = attachments_root / "report.csv"
    attachments_file.parent.mkdir(parents=True, exist_ok=True)
    attachments_file.write_text("data", encoding="utf-8")

    assert guards.attachments_root == attachments_root.resolve()
    assert guards.inline_root == inline_root.resolve()
    assert guards.templates_root == templates_root.resolve()
    assert guards.resolve_attachment("report.csv") == attachments_file.resolve()


def test_mail_guards_overrides_and_external_flags(tmp_path: Path) -> None:
    """Ensure override dataclasses and external flags influence guardrails."""
    overrides = MailGuardRootsOverrides(
        attachments=tmp_path / "guards" / "attachments",
        inline=tmp_path / "guards" / "inline",
        templates=tmp_path / "guards" / "templates",
    )
    external = MailExternalOverrides(attachments=True, templates=False)
    guards = MailFilesystemGuards.from_sources(roots=overrides, external=external, policy=RELAXED_POLICY)

    outside_dir = tmp_path / "outside"
    outside_dir.mkdir(parents=True, exist_ok=True)
    inline_file = outside_dir / "inline.png"
    inline_file.write_text("inline", encoding="utf-8")
    template_file = outside_dir / "template.html"
    template_file.write_text("template", encoding="utf-8")

    attachments_override = cast(Path, overrides.attachments)
    assert guards.attachments_root == attachments_override.resolve()
    assert guards.resolve_inline(inline_file) == inline_file.resolve()
    with pytest.raises(MailValidationError):
        guards.resolve_template(template_file)


# ─────────────────────────────────────────────────────────────────────────────
# Edge case coverage tests
# ─────────────────────────────────────────────────────────────────────────────


def test_extract_section_invalid_filesystem_type() -> None:
    """_extract_section returns empty dict when filesystem is not a Mapping."""
    config = {"filesystem": "not a mapping - just a string"}

    result = MailFilesystemGuards._extract_section(config)

    assert result == {}


def test_load_config_section_when_get_config_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """_load_config_section returns None when get_config is None."""
    import kstlib.mail.filesystem as fs_mod

    monkeypatch.setattr(fs_mod, "get_config", None)

    result = MailFilesystemGuards._load_config_section()

    assert result is None


def test_load_config_section_when_config_not_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    """_load_config_section returns None when config not loaded."""
    import kstlib.mail.filesystem as fs_mod
    from kstlib.config.exceptions import ConfigNotLoadedError

    def raise_not_loaded() -> None:
        raise ConfigNotLoadedError("test")

    monkeypatch.setattr(fs_mod, "get_config", raise_not_loaded)

    result = MailFilesystemGuards._load_config_section()

    assert result is None


def test_load_config_section_no_mail_section(monkeypatch: pytest.MonkeyPatch) -> None:
    """_load_config_section returns None when no mail section in config."""
    from types import SimpleNamespace

    import kstlib.mail.filesystem as fs_mod

    mock_config = SimpleNamespace()
    mock_config.get = lambda key: None  # No mail section
    monkeypatch.setattr(fs_mod, "get_config", lambda: mock_config)

    result = MailFilesystemGuards._load_config_section()

    assert result is None


def test_load_config_section_no_filesystem_section(monkeypatch: pytest.MonkeyPatch) -> None:
    """_load_config_section returns None when no filesystem in mail config."""
    import kstlib.mail.filesystem as fs_mod

    mail_config = {"other_key": "value"}  # No filesystem key
    mock_config = {"mail": mail_config}
    monkeypatch.setattr(fs_mod, "get_config", lambda: mock_config)

    result = MailFilesystemGuards._load_config_section()

    assert result is None


def test_load_config_section_filesystem_not_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    """_load_config_section returns None when filesystem is not a Mapping."""
    import kstlib.mail.filesystem as fs_mod

    mail_config = {"filesystem": "string instead of dict"}
    mock_config = {"mail": mail_config}
    monkeypatch.setattr(fs_mod, "get_config", lambda: mock_config)

    result = MailFilesystemGuards._load_config_section()

    assert result is None
