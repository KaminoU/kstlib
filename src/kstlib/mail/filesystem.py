"""Filesystem guard helpers dedicated to the mail module."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

from kstlib.mail.exceptions import MailValidationError
from kstlib.secure import RELAXED_POLICY, STRICT_POLICY, GuardPolicy, PathGuardrails

__all__ = [
    "MailExternalOverrides",
    "MailFilesystemGuards",
    "MailGuardRootsOverrides",
]


_DEFAULT_CACHE_ROOT = Path.home() / ".cache" / "kstlib" / "mail"
MappingSection = Mapping[str, Any] | MutableMapping[str, Any]
OptionalMappingSection = MappingSection | None
ConfigLoader = Callable[..., MappingSection | None]
ConfigNotLoadedError: type[Exception]


@dataclass(slots=True)
class MailGuardRootsOverrides:
    """Optional overrides for guardrail root directories."""

    attachments: str | Path | None = None
    inline: str | Path | None = None
    templates: str | Path | None = None


@dataclass(slots=True)
class MailExternalOverrides:
    """Optional overrides for external access allowances."""

    attachments: bool | None = None
    templates: bool | None = None


try:
    from kstlib.config import get_config as _imported_get_config
except ImportError:  # pragma: no cover - config module optional at import time
    get_config: ConfigLoader | None = None
else:
    get_config = cast("ConfigLoader", _imported_get_config)

try:
    from kstlib.config.exceptions import ConfigNotLoadedError as _ImportedConfigNotLoadedError
except ImportError:  # pragma: no cover - config module optional at import time

    class _FallbackConfigNotLoadedError(RuntimeError):
        """Fallback error raised when the config subsystem is unavailable."""

    ConfigNotLoadedError = _FallbackConfigNotLoadedError
else:
    ConfigNotLoadedError = _ImportedConfigNotLoadedError


class MailFilesystemGuards:
    """Resolve mail templates and attachments using secure guardrails.

    Example:
        >>> guards = MailFilesystemGuards.default()  # doctest: +SKIP
        >>> safe_attachment = guards.resolve_attachment("reports/daily.csv")  # doctest: +SKIP
    """

    def __init__(
        self,
        *,
        attachments: PathGuardrails,
        inline: PathGuardrails | None = None,
        templates: PathGuardrails | None = None,
    ) -> None:
        """Initialise guardrails, defaulting inline/templates to attachment settings."""
        self._attachments = attachments
        self._inline = inline or attachments
        self._templates = templates or attachments

    @property
    def attachments_root(self) -> Path:
        """Return the root used for attachments (resolved path)."""
        return self._attachments.root

    @property
    def inline_root(self) -> Path:
        """Return the root dedicated to inline resources."""
        return self._inline.root

    @property
    def templates_root(self) -> Path:
        """Return the root used for templates (resolved path)."""
        return self._templates.root

    @classmethod
    def default(cls) -> MailFilesystemGuards:
        """Construct guards from the loaded configuration or fallback defaults."""
        config = cls._load_config_section()
        return cls.from_sources(config=config)

    @classmethod
    def from_sources(
        cls,
        *,
        config: OptionalMappingSection = None,
        roots: MailGuardRootsOverrides | None = None,
        external: MailExternalOverrides | None = None,
        policy: GuardPolicy | None = None,
    ) -> MailFilesystemGuards:
        """Build guards from optional config mappings and overrides."""
        section = cls._extract_section(config)
        policy = cls._derive_policy(section, policy)
        attachments_guard, inline_guard, templates_guard = cls._build_guardrails(
            section=section,
            policy=policy,
            roots=roots,
            external=external,
        )
        return cls(attachments=attachments_guard, inline=inline_guard, templates=templates_guard)

    @classmethod
    def relaxed_for_testing(cls, root: Path) -> MailFilesystemGuards:
        """Helper for tests/examples that need a temporary relaxed environment."""
        policy = RELAXED_POLICY
        attachments_guard = PathGuardrails(root / "attachments", policy=policy)
        inline_guard = PathGuardrails(root / "inline", policy=policy)
        templates_guard = PathGuardrails(root / "templates", policy=policy)
        return cls(attachments=attachments_guard, inline=inline_guard, templates=templates_guard)

    def _resolve_path(self, guardrail: PathGuardrails, candidate: str | Path) -> Path:
        """Resolve *candidate* using the given guardrail, wrapping exceptions."""
        try:
            return guardrail.resolve_file(candidate)
        except Exception as exc:  # pragma: no cover - mapped error
            raise MailValidationError(str(exc)) from exc

    def resolve_attachment(self, candidate: str | Path) -> Path:
        """Resolve *candidate* as a secure attachment path."""
        return self._resolve_path(self._attachments, candidate)

    def resolve_inline(self, candidate: str | Path) -> Path:
        """Resolve *candidate* as a secure inline resource path."""
        return self._resolve_path(self._inline, candidate)

    def resolve_template(self, candidate: str | Path) -> Path:
        """Resolve *candidate* as a secure template file path."""
        return self._resolve_path(self._templates, candidate)

    @staticmethod
    def _extract_section(config: OptionalMappingSection) -> Mapping[str, Any]:
        if not config:
            return {}
        if "filesystem" in config:
            subsection = config["filesystem"]
            if not isinstance(subsection, Mapping | MutableMapping):
                return {}
            return dict(subsection)
        return dict(config)

    @staticmethod
    def _derive_policy(section: Mapping[str, Any], policy: GuardPolicy | None) -> GuardPolicy:
        baseline_policy = policy or STRICT_POLICY
        return replace(
            baseline_policy,
            auto_create_root=bool(section.get("auto_create_roots", baseline_policy.auto_create_root)),
            enforce_permissions=bool(section.get("enforce_permissions", baseline_policy.enforce_permissions)),
            max_permission_octal=int(section.get("max_permission_octal", baseline_policy.max_permission_octal)),
        )

    @staticmethod
    def _resolve_roots(
        section: Mapping[str, Any],
        overrides: MailGuardRootsOverrides | None,
    ) -> tuple[Path, Path, Path]:
        attachments_root = Path(
            (overrides.attachments if overrides else None)
            or section.get("attachments_root")
            or (_DEFAULT_CACHE_ROOT / "attachments")
        )
        inline_root = Path((overrides.inline if overrides else None) or section.get("inline_root") or attachments_root)
        templates_root = Path(
            (overrides.templates if overrides else None)
            or section.get("templates_root")
            or (_DEFAULT_CACHE_ROOT / "templates")
        )
        return attachments_root, inline_root, templates_root

    @staticmethod
    def _resolve_external_flags(
        section: Mapping[str, Any],
        overrides: MailExternalOverrides | None,
    ) -> tuple[bool, bool]:
        if overrides and overrides.attachments is not None:
            allow_attachments = bool(overrides.attachments)
        else:
            allow_attachments = bool(section.get("allow_external_attachments", False))

        if overrides and overrides.templates is not None:
            allow_templates = bool(overrides.templates)
        else:
            allow_templates = bool(section.get("allow_external_templates", False))

        return allow_attachments, allow_templates

    @staticmethod
    def _build_guardrails(
        *,
        section: Mapping[str, Any],
        policy: GuardPolicy,
        roots: MailGuardRootsOverrides | None,
        external: MailExternalOverrides | None,
    ) -> tuple[PathGuardrails, PathGuardrails, PathGuardrails]:
        """Compose guardrail instances while keeping calling sites lean."""
        attachments_root, inline_root, templates_root = MailFilesystemGuards._resolve_roots(section, roots)
        allow_external_attachments, allow_external_templates = MailFilesystemGuards._resolve_external_flags(
            section,
            external,
        )

        attachments_policy = replace(policy, allow_external=allow_external_attachments)
        inline_policy = replace(policy, allow_external=allow_external_attachments)
        templates_policy = replace(policy, allow_external=allow_external_templates)

        attachments_guard = PathGuardrails(attachments_root, policy=attachments_policy)
        inline_guard = PathGuardrails(inline_root, policy=inline_policy)
        templates_guard = PathGuardrails(templates_root, policy=templates_policy)
        return attachments_guard, inline_guard, templates_guard

    @staticmethod
    def _load_config_section() -> Mapping[str, Any] | None:
        if get_config is None:
            return None
        try:
            conf = get_config()
        except ConfigNotLoadedError:
            return None
        mail_conf = cast("OptionalMappingSection", conf.get("mail") if conf else None)
        if not mail_conf:
            return None
        fs_conf_raw = mail_conf.get("filesystem")
        if fs_conf_raw is None:
            return None
        if not isinstance(fs_conf_raw, Mapping | MutableMapping):
            return None
        return dict(fs_conf_raw)
