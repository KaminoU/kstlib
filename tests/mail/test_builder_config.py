"""Tests for config-driven transport resolution in MailBuilder."""

from __future__ import annotations

from email.message import EmailMessage
from typing import TYPE_CHECKING, Any

import pytest
from box import Box

from kstlib.mail import MailBuilder, MailConfigurationError
from kstlib.mail.builder import (
    _build_resend_transport,
    _build_smtp_transport,
    _build_transport_from_preset,
)
from kstlib.mail.transport import MailTransport
from kstlib.mail.transports.resend import ResendTransport
from kstlib.mail.transports.smtp import SMTPTransport

if TYPE_CHECKING:
    from collections.abc import Callable


class _StubTransport(MailTransport):
    """Minimal MailTransport double used to verify explicit-transport mode."""

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        """Record the message."""
        self.sent.append(message)


def _mock_mail_config(monkeypatch: pytest.MonkeyPatch, mail_section: dict[str, Any] | None) -> None:
    """Replace _load_mail_config with a stub returning the given section.

    Uses default_box_attr=None so that missing-key lookups return None,
    matching the shape of the real kstlib.config.get_config() output.
    """
    import kstlib.mail.builder as builder_mod

    box_section = Box(mail_section, default_box=True, default_box_attr=None) if mail_section is not None else None

    def fake_loader() -> Any:
        return box_section

    monkeypatch.setattr(builder_mod, "_load_mail_config", fake_loader)


def _must_not_load_config(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    """Wire _load_mail_config to a spy that fails the test if invoked."""
    import kstlib.mail.builder as builder_mod

    def spy() -> Any:
        pytest.fail("_load_mail_config should not be called when transport= is explicit")

    monkeypatch.setattr(builder_mod, "_load_mail_config", spy)
    return spy


class TestExplicitTransport:
    """Explicit ``transport=`` must fully short-circuit preset resolution."""

    def test_mailbuilder_explicit_transport_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """transport= kwarg keeps legacy behaviour and never touches config."""
        _must_not_load_config(monkeypatch)
        stub = _StubTransport()
        mail = MailBuilder(transport=stub)
        assert mail._transport is stub  # noqa: SLF001


class TestNamedPreset:
    """MailBuilder(preset=...) resolves presets from configuration."""

    def test_mailbuilder_named_preset_smtp(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Named smtp preset is resolved into an SMTPTransport with correct params."""
        _mock_mail_config(
            monkeypatch,
            {
                "default": None,
                "presets": {
                    "corporate": {
                        "transport": "smtp",
                        "host": "smtp.corp.local",
                        "port": 25,
                        "login": "svc",
                        "password": "s3cret",
                        "starttls": False,
                        "ssl": False,
                        "timeout": 42,
                    }
                },
            },
        )

        mail = MailBuilder(preset="corporate")
        assert isinstance(mail._transport, SMTPTransport)  # noqa: SLF001
        smtp = mail._transport  # noqa: SLF001
        assert smtp._host == "smtp.corp.local"  # noqa: SLF001
        assert smtp._port == 25  # noqa: SLF001
        assert smtp._username == "svc"  # noqa: SLF001
        assert smtp._password == "s3cret"  # noqa: SLF001
        assert smtp._use_starttls is False  # noqa: SLF001
        assert smtp._use_ssl is False  # noqa: SLF001
        assert smtp._timeout == 42.0  # noqa: SLF001

    def test_mailbuilder_named_preset_resend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Named resend preset is resolved into a ResendTransport."""
        _mock_mail_config(
            monkeypatch,
            {
                "default": None,
                "presets": {
                    "transactional": {
                        "transport": "resend",
                        "api_key": "re_test_123",
                        "timeout": 15,
                    }
                },
            },
        )

        mail = MailBuilder(preset="transactional")
        assert isinstance(mail._transport, ResendTransport)  # noqa: SLF001
        resend = mail._transport  # noqa: SLF001
        assert resend._api_key == "re_test_123"  # noqa: SLF001
        assert resend._timeout == 15.0  # noqa: SLF001

    def test_mailbuilder_default_preset_from_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """mail.default drives auto-resolution when neither kwarg is provided."""
        _mock_mail_config(
            monkeypatch,
            {
                "default": "corporate",
                "presets": {
                    "corporate": {
                        "transport": "smtp",
                        "host": "smtp.corp.local",
                        "port": 587,
                    }
                },
            },
        )

        mail = MailBuilder()
        assert isinstance(mail._transport, SMTPTransport)  # noqa: SLF001
        assert mail._transport._host == "smtp.corp.local"  # noqa: SLF001

    def test_mailbuilder_unknown_preset_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unknown preset name raises MailConfigurationError listing available keys."""
        _mock_mail_config(
            monkeypatch,
            {
                "default": None,
                "presets": {"corporate": {"transport": "smtp", "host": "h"}},
            },
        )

        with pytest.raises(MailConfigurationError) as exc_info:
            MailBuilder(preset="inexistant")
        message = str(exc_info.value)
        assert "inexistant" in message
        assert "corporate" in message

    def test_mailbuilder_no_transport_no_config_send_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without preset/default/transport, build() works but send() raises."""
        _mock_mail_config(monkeypatch, {"default": None, "presets": {}})

        mail = MailBuilder().sender("a@x.com").to("b@x.com").message("hi", content_type="plain")
        built = mail.build()
        assert isinstance(built, EmailMessage)

        with pytest.raises(MailConfigurationError):
            mail.send()


class TestPresetValidation:
    """Preset-level validation errors are raised eagerly at init time."""

    def test_mailbuilder_smtp_missing_host_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """smtp preset without host raises a MailConfigurationError mentioning host."""
        _mock_mail_config(
            monkeypatch,
            {"default": None, "presets": {"broken": {"transport": "smtp", "port": 25}}},
        )

        with pytest.raises(MailConfigurationError, match="host"):
            MailBuilder(preset="broken")

    def test_mailbuilder_resend_missing_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """resend preset without api_key raises a MailConfigurationError mentioning api_key."""
        _mock_mail_config(
            monkeypatch,
            {"default": None, "presets": {"broken": {"transport": "resend"}}},
        )

        with pytest.raises(MailConfigurationError, match="api_key"):
            MailBuilder(preset="broken")

    def test_mailbuilder_unknown_transport_type_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unknown transport type lists supported types in the error."""
        _mock_mail_config(
            monkeypatch,
            {"default": None, "presets": {"odd": {"transport": "fax"}}},
        )

        with pytest.raises(MailConfigurationError) as exc_info:
            MailBuilder(preset="odd")
        message = str(exc_info.value)
        assert "fax" in message
        assert "smtp" in message
        assert "resend" in message

    def test_mailbuilder_preset_missing_transport_field_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Preset without 'transport' field is rejected with a clear message."""
        _mock_mail_config(
            monkeypatch,
            {"default": None, "presets": {"p": {"host": "x"}}},
        )

        with pytest.raises(MailConfigurationError, match="transport"):
            MailBuilder(preset="p")

    def test_mailbuilder_preset_without_mail_section(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When mail.presets section is absent, preset resolution raises."""
        _mock_mail_config(monkeypatch, None)

        with pytest.raises(MailConfigurationError, match="mail"):
            MailBuilder(preset="whatever")


class TestSMTPFactory:
    """Direct unit tests for ``_build_smtp_transport``."""

    def test_build_smtp_transport_starttls_default(self) -> None:
        """When starttls is absent, default to True."""
        cfg = Box({"host": "smtp.x.com"}, default_box=True, default_box_attr=None)
        transport = _build_smtp_transport(cfg)
        assert transport._use_starttls is True  # noqa: SLF001
        assert transport._use_ssl is False  # noqa: SLF001

    def test_build_smtp_transport_with_credentials(self) -> None:
        """login + password present -> SMTPCredentials populated."""
        cfg = Box(
            {"host": "smtp.x.com", "login": "u", "password": "p"},
            default_box=True,
            default_box_attr=None,
        )
        transport = _build_smtp_transport(cfg)
        assert transport._username == "u"  # noqa: SLF001
        assert transport._password == "p"  # noqa: SLF001

    def test_build_smtp_transport_no_credentials(self) -> None:
        """No login/password -> credentials stays None."""
        cfg = Box({"host": "smtp.x.com"}, default_box=True, default_box_attr=None)
        transport = _build_smtp_transport(cfg)
        assert transport._username is None  # noqa: SLF001
        assert transport._password is None  # noqa: SLF001

    def test_build_smtp_transport_ssl_flag(self) -> None:
        """ssl=True disables starttls and flips use_ssl."""
        cfg = Box({"host": "smtp.x.com", "ssl": True}, default_box=True, default_box_attr=None)
        transport = _build_smtp_transport(cfg)
        assert transport._use_ssl is True  # noqa: SLF001
        assert transport._use_starttls is False  # noqa: SLF001


class TestResendFactory:
    """Direct unit tests for ``_build_resend_transport``."""

    def test_build_resend_transport_defaults(self) -> None:
        """Default timeout is 30.0 when absent."""
        cfg = Box({"api_key": "re_abc"}, default_box=True, default_box_attr=None)
        transport = _build_resend_transport(cfg)
        assert transport._api_key == "re_abc"  # noqa: SLF001
        assert transport._timeout == 30.0  # noqa: SLF001


class TestDirectPresetBuilder:
    """Direct unit tests for ``_build_transport_from_preset``."""

    def test_empty_presets_lists_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When no presets exist, the error reports an empty list."""
        _mock_mail_config(monkeypatch, {"default": None, "presets": {}})

        with pytest.raises(MailConfigurationError) as exc_info:
            _build_transport_from_preset("any")
        assert "Available: []" in str(exc_info.value)


class TestConfigLoaderErrors:
    """Defensive branches around config loading."""

    def test_load_mail_config_wraps_loader_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_config() raising bubbles up as MailConfigurationError."""
        import kstlib.config as config_mod

        def explode(*_a: Any, **_kw: Any) -> Any:
            raise RuntimeError("disk exploded")

        monkeypatch.setattr(config_mod, "get_config", explode)

        from kstlib.mail.builder import _load_mail_config

        with pytest.raises(MailConfigurationError, match="Failed to load"):
            _load_mail_config()

    def test_load_mail_config_returns_none_for_non_mapping(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When get_config returns an object without .get, loader yields None."""
        import kstlib.config as config_mod

        monkeypatch.setattr(config_mod, "get_config", lambda *a, **kw: object())

        from kstlib.mail.builder import _load_mail_config

        assert _load_mail_config() is None

    def test_default_transport_swallows_loader_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """MailBuilder() with broken config lands with transport=None, not an exception."""
        import kstlib.mail.builder as builder_mod

        def explode() -> Any:
            raise MailConfigurationError("simulated loader failure")

        monkeypatch.setattr(builder_mod, "_load_mail_config", explode)

        mail = MailBuilder()
        assert mail._transport is None  # noqa: SLF001

    def test_default_transport_none_when_mail_cfg_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """MailBuilder() with absent mail section yields transport=None."""
        _mock_mail_config(monkeypatch, None)
        mail = MailBuilder()
        assert mail._transport is None  # noqa: SLF001


# ============================================================================
# Preset envelope defaults (feat-mail-preset-envelope-defaults)
# ============================================================================


def _preset_with_defaults(defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a minimal smtp preset dict with optional ``defaults`` section."""
    preset: dict[str, Any] = {"transport": "smtp", "host": "smtp-secure.corp.local"}
    if defaults is not None:
        preset["defaults"] = defaults
    return preset


class TestPresetEnvelopeDefaults:
    """4-scenario base cascade for ``defaults.sender`` and ``defaults.reply_to``."""

    def test_sender_default_applied_from_named_preset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Preset declares defaults.sender -> pre-filled on MailBuilder(preset=...)."""
        _mock_mail_config(
            monkeypatch,
            {
                "presets": {
                    "corporate": _preset_with_defaults(
                        {"sender": "Service Notifications <notify@corp.local>"},
                    ),
                },
            },
        )
        mail = MailBuilder(preset="corporate")
        assert mail._sender is not None  # noqa: SLF001
        assert mail._sender.formatted == "Service Notifications <notify@corp.local>"  # noqa: SLF001
        assert mail._reply_to is None  # noqa: SLF001

    def test_reply_to_default_applied_from_named_preset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Preset declares defaults.reply_to -> pre-filled on MailBuilder(preset=...)."""
        _mock_mail_config(
            monkeypatch,
            {
                "presets": {
                    "corporate": _preset_with_defaults(
                        {"reply_to": "Support Desk <support@corp.local>"},
                    ),
                },
            },
        )
        mail = MailBuilder(preset="corporate")
        assert mail._reply_to is not None  # noqa: SLF001
        assert mail._reply_to.formatted == "Support Desk <support@corp.local>"  # noqa: SLF001
        assert mail._sender is None  # noqa: SLF001

    def test_both_defaults_applied_together(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Both defaults.sender and defaults.reply_to set -> both applied."""
        _mock_mail_config(
            monkeypatch,
            {
                "presets": {
                    "corporate": _preset_with_defaults(
                        {
                            "sender": "Service Notifications <notify@corp.local>",
                            "reply_to": "Support Desk <support@corp.local>",
                        },
                    ),
                },
            },
        )
        mail = MailBuilder(preset="corporate")
        assert mail._sender is not None  # noqa: SLF001
        assert mail._reply_to is not None  # noqa: SLF001
        assert mail._sender.formatted == "Service Notifications <notify@corp.local>"  # noqa: SLF001
        assert mail._reply_to.formatted == "Support Desk <support@corp.local>"  # noqa: SLF001

    def test_preset_without_defaults_leaves_addresses_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Preset without defaults section -> sender and reply_to remain None."""
        _mock_mail_config(
            monkeypatch,
            {"presets": {"corporate": _preset_with_defaults(None)}},
        )
        mail = MailBuilder(preset="corporate")
        assert mail._sender is None  # noqa: SLF001
        assert mail._reply_to is None  # noqa: SLF001

    def test_empty_defaults_section_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """defaults: {} -> behaves like a preset with no defaults section."""
        _mock_mail_config(
            monkeypatch,
            {"presets": {"corporate": _preset_with_defaults({})}},
        )
        mail = MailBuilder(preset="corporate")
        assert mail._sender is None  # noqa: SLF001
        assert mail._reply_to is None  # noqa: SLF001


class TestPresetEnvelopeDefaultsUserOverride:
    """User-provided values via .sender() / .reply_to() always win."""

    def test_user_sender_overrides_preset_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """.sender('other@z') overrides the preset default sender."""
        _mock_mail_config(
            monkeypatch,
            {
                "presets": {
                    "corporate": _preset_with_defaults(
                        {"sender": "Service Notifications <notify@corp.local>"},
                    ),
                },
            },
        )
        mail = MailBuilder(preset="corporate").sender("other@corp.local")
        assert mail._sender is not None  # noqa: SLF001
        assert mail._sender.formatted == "other@corp.local"  # noqa: SLF001

    def test_user_reply_to_overrides_preset_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """.reply_to('rr@z') overrides the preset default reply_to."""
        _mock_mail_config(
            monkeypatch,
            {
                "presets": {
                    "corporate": _preset_with_defaults(
                        {"reply_to": "Support Desk <support@corp.local>"},
                    ),
                },
            },
        )
        mail = MailBuilder(preset="corporate").reply_to("explicit@corp.local")
        assert mail._reply_to is not None  # noqa: SLF001
        assert mail._reply_to.formatted == "explicit@corp.local"  # noqa: SLF001

    def test_partial_override_keeps_unset_field_as_preset_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """User sets only sender -> reply_to stays the preset default."""
        _mock_mail_config(
            monkeypatch,
            {
                "presets": {
                    "corporate": _preset_with_defaults(
                        {
                            "sender": "Service Notifications <notify@corp.local>",
                            "reply_to": "Support Desk <support@corp.local>",
                        },
                    ),
                },
            },
        )
        mail = MailBuilder(preset="corporate").sender("explicit@corp.local")
        assert mail._sender is not None  # noqa: SLF001
        assert mail._reply_to is not None  # noqa: SLF001
        assert mail._sender.formatted == "explicit@corp.local"  # noqa: SLF001
        assert mail._reply_to.formatted == "Support Desk <support@corp.local>"  # noqa: SLF001


class TestPresetEnvelopeDefaultsResolution:
    """How defaults are (or are not) applied depending on builder constructor args."""

    def test_no_preset_and_no_mail_default_yields_no_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """MailBuilder() with neither preset= nor mail.default -> no defaults applied."""
        _mock_mail_config(monkeypatch, {"presets": {}})
        mail = MailBuilder()
        assert mail._sender is None  # noqa: SLF001
        assert mail._reply_to is None  # noqa: SLF001

    def test_mail_default_preset_defaults_are_applied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """mail.default='corporate' with defaults -> defaults applied on MailBuilder()."""
        _mock_mail_config(
            monkeypatch,
            {
                "default": "corporate",
                "presets": {
                    "corporate": _preset_with_defaults(
                        {"sender": "Service Notifications <notify@corp.local>"},
                    ),
                },
            },
        )
        mail = MailBuilder()
        assert mail._sender is not None  # noqa: SLF001
        assert mail._sender.formatted == "Service Notifications <notify@corp.local>"  # noqa: SLF001

    def test_explicit_transport_short_circuits_preset_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """MailBuilder(transport=X) must NOT apply preset defaults, even if mail.default is set."""
        _mock_mail_config(
            monkeypatch,
            {
                "default": "corporate",
                "presets": {
                    "corporate": _preset_with_defaults(
                        {"sender": "Service Notifications <notify@corp.local>"},
                    ),
                },
            },
        )
        stub = _StubTransport()
        mail = MailBuilder(transport=stub)
        assert mail._transport is stub  # noqa: SLF001
        assert mail._sender is None  # noqa: SLF001
        assert mail._reply_to is None  # noqa: SLF001


class TestPresetEnvelopeDefaultsErrorPaths:
    """Invalid inputs surface as clear errors at builder init time, not at send time."""

    def test_unparseable_sender_raises_mail_validation_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """defaults.sender with invalid email format -> MailValidationError at init."""
        from kstlib.mail.exceptions import MailValidationError

        _mock_mail_config(
            monkeypatch,
            {
                "presets": {
                    "corporate": _preset_with_defaults({"sender": "not-an-email-at-all"}),
                },
            },
        )
        with pytest.raises(MailValidationError):
            MailBuilder(preset="corporate")

    def test_non_string_sender_raises_mail_configuration_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """defaults.sender holding a non-string (dict, int, list) -> MailConfigurationError."""
        _mock_mail_config(
            monkeypatch,
            {
                "presets": {
                    "corporate": _preset_with_defaults(
                        {"sender": {"name": "svc", "email": "notify@corp.local"}},
                    ),
                },
            },
        )
        with pytest.raises(MailConfigurationError, match="defaults.sender must be a string"):
            MailBuilder(preset="corporate")


class TestPresetEnvelopeDefaultsBackwardCompat:
    """Pre-existing presets without a defaults section must keep behaving identically."""

    def test_existing_preset_without_defaults_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A preset without defaults -> same sender/reply_to state as before the feature."""
        _mock_mail_config(
            monkeypatch,
            {
                "presets": {
                    "corporate": {
                        "transport": "smtp",
                        "host": "smtp-secure.corp.local",
                        "port": 25,
                        "login": "svc_mail",
                        "password": "secret",
                        "starttls": True,
                    },
                },
            },
        )
        mail = MailBuilder(preset="corporate")
        assert mail._sender is None  # noqa: SLF001
        assert mail._reply_to is None  # noqa: SLF001
        assert mail._transport is not None  # noqa: SLF001


class TestPresetEnvelopeDefaultsUnknownKeys:
    """Unsupported keys under defaults are logged once and ignored (forward compat)."""

    def test_unknown_defaults_keys_logged_and_ignored(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Unknown keys (e.g. 'subject', 'to') -> single WARNING + ignored, known keys applied."""
        import logging

        _mock_mail_config(
            monkeypatch,
            {
                "presets": {
                    "corporate": _preset_with_defaults(
                        {
                            "sender": "Service Notifications <notify@corp.local>",
                            "subject": "pre-filled subject (unsupported)",
                            "to": "oncall@corp.local (unsupported)",
                        },
                    ),
                },
            },
        )
        with caplog.at_level(logging.WARNING, logger="kstlib.mail.builder"):
            mail = MailBuilder(preset="corporate")

        assert mail._sender is not None  # noqa: SLF001
        assert mail._sender.formatted == "Service Notifications <notify@corp.local>"  # noqa: SLF001
        assert mail._to == []  # noqa: SLF001
        assert mail._subject == ""  # noqa: SLF001

        warnings = [rec for rec in caplog.records if "unsupported defaults keys" in rec.message]
        assert len(warnings) == 1
        message = warnings[0].getMessage()
        assert "subject" in message
        assert "to" in message
        assert "'corporate'" in message
