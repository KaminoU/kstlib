"""Tests for the 4-level SSL cascade on SMTP mail presets.

Scenarios cover the spec in feat-mail-preset-ssl-config:
    - Cascade base (preset, mail.ssl, root, default)
    - Independent cascade of the two keys (verify and ca_bundle)
    - Invalid ca_bundle path raises MailConfigurationError
    - Non-bool verify raises TypeError
    - Implicit TLS (use_ssl=True) still honors the SSL context
    - Backward compatibility when no SSL keys are set anywhere
"""

from __future__ import annotations

# pylint: disable=protected-access,import-outside-toplevel,line-too-long
# Reason: tests inspect internal state on transport, inline imports for focus.

import logging
import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from box import Box
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

import kstlib.mail.builder as builder_mod
from kstlib.mail.builder import (
    _build_smtp_ssl_context,
    _build_smtp_transport,
    _resolve_mail_ssl_config,
)
from kstlib.mail.exceptions import MailConfigurationError


def _generate_self_signed_pem() -> bytes:
    """Generate a minimal self-signed CA certificate in PEM format.

    Produced PEMs are accepted both by ``validate_ca_bundle_path`` (header,
    size, PEM format) and by ``ssl.create_default_context(cafile=...)``
    which actually parses the X.509 structure.
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "kstlib-test-ca")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM)


@pytest.fixture(scope="session")
def _session_ca_pem() -> bytes:
    """Cache the self-signed PEM for the whole test session (RSA 2048 is slow)."""
    return _generate_self_signed_pem()


@pytest.fixture
def valid_ca_bundle(tmp_path: Path, _session_ca_pem: bytes) -> str:
    """Write the session-scoped PEM to a fresh file and return its path."""
    ca_path = tmp_path / "ca.pem"
    ca_path.write_bytes(_session_ca_pem)
    return str(ca_path)


def _mock_mail_section(monkeypatch: pytest.MonkeyPatch, mail_section: dict[str, Any] | None) -> None:
    """Stub ``_load_mail_section`` to return the provided mail section."""
    box_section = Box(mail_section, default_box=True, default_box_attr=None) if mail_section is not None else None

    def fake_loader() -> Any:
        return box_section

    monkeypatch.setattr(builder_mod, "_load_mail_section", fake_loader)


def _mock_root_ssl(monkeypatch: pytest.MonkeyPatch, verify: bool, ca_bundle: str | None) -> None:
    """Stub ``kstlib.ssl.get_ssl_config`` used by _resolve_mail_ssl_config."""
    from kstlib.ssl import SSLConfig

    def fake_get() -> SSLConfig:
        return SSLConfig(verify=verify, ca_bundle=ca_bundle)

    monkeypatch.setattr(builder_mod, "get_ssl_config", fake_get)


def _mock_root_ssl_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub root SSL to the safe default (verify=True, no ca_bundle)."""
    _mock_root_ssl(monkeypatch, verify=True, ca_bundle=None)


def _preset(**fields: Any) -> Any:
    """Build a preset Box with the given fields."""
    return Box(fields, default_box=True, default_box_attr=None)


# ---------------------------------------------------------------------------
# Cascade base scenarios (1-6)
# ---------------------------------------------------------------------------


class TestCascadeBase:
    """Cascade scenarios for each level in isolation."""

    def test_preset_ssl_verify_false_yields_cert_none(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Preset ssl_verify=False -> CERT_NONE, check_hostname False, WARNING with source 'preset'."""
        _mock_mail_section(monkeypatch, None)
        _mock_root_ssl_default(monkeypatch)

        cfg = _preset(host="smtp-secure.corp.local", ssl_verify=False)
        with caplog.at_level(logging.WARNING, logger="kstlib.mail.builder"):
            transport = _build_smtp_transport(cfg)

        assert transport._ssl_context.verify_mode == ssl.CERT_NONE
        assert transport._ssl_context.check_hostname is False
        assert any("source: preset" in rec.message for rec in caplog.records)

    def test_preset_ca_bundle_keeps_cert_required(self, monkeypatch: pytest.MonkeyPatch, valid_ca_bundle: str) -> None:
        """Preset ssl_ca_bundle -> context uses this CA, verify_mode stays CERT_REQUIRED."""
        _mock_mail_section(monkeypatch, None)
        _mock_root_ssl_default(monkeypatch)

        cfg = _preset(host="smtp-secure.corp.local", ssl_ca_bundle=valid_ca_bundle)
        transport = _build_smtp_transport(cfg)

        assert transport._ssl_context.verify_mode == ssl.CERT_REQUIRED
        assert transport._ssl_context.check_hostname is True

    def test_mail_ssl_verify_false_cascades_to_preset(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Preset has no ssl_* keys, mail.ssl.verify=False -> CERT_NONE, WARNING source 'mail.ssl'."""
        _mock_mail_section(monkeypatch, {"ssl": {"verify": False}})
        _mock_root_ssl_default(monkeypatch)

        cfg = _preset(host="smtp-secure.corp.local")
        with caplog.at_level(logging.WARNING, logger="kstlib.mail.builder"):
            transport = _build_smtp_transport(cfg)

        assert transport._ssl_context.verify_mode == ssl.CERT_NONE
        assert any("source: mail.ssl" in rec.message for rec in caplog.records)

    def test_mail_ssl_ca_bundle_cascades_to_preset(self, monkeypatch: pytest.MonkeyPatch, valid_ca_bundle: str) -> None:
        """Preset has no ssl_*, mail.ssl.ca_bundle=/path -> context uses this CA."""
        _mock_mail_section(monkeypatch, {"ssl": {"ca_bundle": valid_ca_bundle}})
        _mock_root_ssl_default(monkeypatch)

        cfg = _preset(host="smtp-secure.corp.local")
        transport = _build_smtp_transport(cfg)

        assert transport._ssl_context.verify_mode == ssl.CERT_REQUIRED

    def test_root_ssl_verify_false_reaches_mail_when_upper_levels_silent(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Preset silent, mail.ssl silent, root ssl.verify=False -> CERT_NONE, WARNING source 'ssl (root)'."""
        _mock_mail_section(monkeypatch, None)
        _mock_root_ssl(monkeypatch, verify=False, ca_bundle=None)

        cfg = _preset(host="smtp-secure.corp.local")
        with caplog.at_level(logging.WARNING, logger="kstlib.mail.builder"):
            transport = _build_smtp_transport(cfg)

        assert transport._ssl_context.verify_mode == ssl.CERT_NONE
        assert any("source: ssl (root)" in rec.message for rec in caplog.records)

    def test_default_strict_when_nothing_configured(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Preset silent, mail.ssl silent, root silent -> default strict context, no WARNING."""
        _mock_mail_section(monkeypatch, None)
        _mock_root_ssl_default(monkeypatch)

        cfg = _preset(host="smtp-secure.corp.local")
        with caplog.at_level(logging.WARNING, logger="kstlib.mail.builder"):
            transport = _build_smtp_transport(cfg)

        assert transport._ssl_context.verify_mode == ssl.CERT_REQUIRED
        assert transport._ssl_context.check_hostname is True
        assert not any("SECURITY" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# Independent cascade (7, 8)
# ---------------------------------------------------------------------------


class TestIndependentCascade:
    """Each key (verify, ca_bundle) cascades independently."""

    def test_preset_verify_false_plus_mail_ca_bundle(
        self, monkeypatch: pytest.MonkeyPatch, valid_ca_bundle: str
    ) -> None:
        """Preset sets ssl_verify=False, mail.ssl sets ca_bundle -> ca_bundle wins (CERT_REQUIRED).

        Precedence note: ssl_ca_bundle is stricter than ssl_verify=False, so
        when both are set the context verifies against the bundle.
        """
        _mock_mail_section(monkeypatch, {"ssl": {"ca_bundle": valid_ca_bundle}})
        _mock_root_ssl_default(monkeypatch)

        cfg = _preset(host="smtp-secure.corp.local", ssl_verify=False)
        verify, ca_bundle = _resolve_mail_ssl_config(cfg)
        assert verify is False
        assert ca_bundle == valid_ca_bundle

        transport = _build_smtp_transport(cfg)
        assert transport._ssl_context.verify_mode == ssl.CERT_REQUIRED

    def test_preset_ca_bundle_plus_mail_verify_false(
        self, monkeypatch: pytest.MonkeyPatch, valid_ca_bundle: str
    ) -> None:
        """Preset sets ssl_ca_bundle, mail.ssl sets verify=False -> ca_bundle wins."""
        _mock_mail_section(monkeypatch, {"ssl": {"verify": False}})
        _mock_root_ssl_default(monkeypatch)

        cfg = _preset(host="smtp-secure.corp.local", ssl_ca_bundle=valid_ca_bundle)
        verify, ca_bundle = _resolve_mail_ssl_config(cfg)
        assert verify is False
        assert ca_bundle == valid_ca_bundle

        transport = _build_smtp_transport(cfg)
        assert transport._ssl_context.verify_mode == ssl.CERT_REQUIRED


# ---------------------------------------------------------------------------
# Error paths (9, 10)
# ---------------------------------------------------------------------------


class TestErrorPaths:
    """Invalid inputs surface clearly at build time."""

    def test_missing_ca_bundle_file_raises_mail_configuration_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Preset ssl_ca_bundle pointing to a non-existent file raises MailConfigurationError."""
        _mock_mail_section(monkeypatch, None)
        _mock_root_ssl_default(monkeypatch)

        cfg = _preset(host="smtp-secure.corp.local", ssl_ca_bundle=str(tmp_path / "no-such-file.pem"))
        with pytest.raises(MailConfigurationError, match="ssl_ca_bundle"):
            _build_smtp_transport(cfg)

    def test_non_bool_ssl_verify_raises_type_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """YAML-style string 'yes' for ssl_verify is rejected, not silently coerced."""
        _mock_mail_section(monkeypatch, None)
        _mock_root_ssl_default(monkeypatch)

        cfg = _preset(host="smtp-secure.corp.local", ssl_verify="yes")
        with pytest.raises(TypeError, match="must be bool"):
            _build_smtp_transport(cfg)


# ---------------------------------------------------------------------------
# Implicit TLS (11) and backward compat (12)
# ---------------------------------------------------------------------------


class TestImplicitTlsAndBackwardCompat:
    """Cases around ssl: true (implicit TLS) and pristine backward compat."""

    def test_implicit_tls_honors_cert_none_when_verify_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Preset with ssl: true + ssl_verify: false -> implicit TLS uses CERT_NONE context."""
        _mock_mail_section(monkeypatch, None)
        _mock_root_ssl_default(monkeypatch)

        cfg = _preset(host="smtp-secure.corp.local", ssl=True, starttls=False, ssl_verify=False)
        transport = _build_smtp_transport(cfg)

        assert transport._use_ssl is True
        assert transport._use_starttls is False
        assert transport._ssl_context.verify_mode == ssl.CERT_NONE

    def test_backward_compat_no_ssl_keys_anywhere(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Preset without new SSL keys, mail.ssl absent, root default -> strict context, no WARNING.

        This mirrors the pre-feature behaviour: a preset that does not
        mention ssl_verify nor ssl_ca_bundle must keep behaving as before.
        """
        _mock_mail_section(monkeypatch, None)
        _mock_root_ssl_default(monkeypatch)

        cfg = _preset(host="smtp-secure.corp.local", port=587, starttls=True)
        with caplog.at_level(logging.WARNING, logger="kstlib.mail.builder"):
            transport = _build_smtp_transport(cfg)

        assert transport._ssl_context.verify_mode == ssl.CERT_REQUIRED
        assert transport._ssl_context.check_hostname is True
        assert not any("SECURITY" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# Pure helper _build_smtp_ssl_context
# ---------------------------------------------------------------------------


class TestBuildSmtpSslContextPureFunction:
    """_build_smtp_ssl_context is pure: no config reads, no warnings."""

    def test_ca_bundle_wins_over_verify_false(self, valid_ca_bundle: str) -> None:
        """Explicit precedence documented: ca_bundle takes priority over verify=False."""
        ctx = _build_smtp_ssl_context(ssl_verify=False, ssl_ca_bundle=valid_ca_bundle)
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname is True

    def test_verify_false_with_no_bundle_gives_cert_none(self) -> None:
        """verify=False and no bundle: context explicitly disables hostname check and verify."""
        ctx = _build_smtp_ssl_context(ssl_verify=False, ssl_ca_bundle=None)
        assert ctx.verify_mode == ssl.CERT_NONE
        assert ctx.check_hostname is False

    def test_default_context_when_verify_true_no_bundle(self) -> None:
        """Safe default: verify=True, no bundle -> Python's default strict context."""
        ctx = _build_smtp_ssl_context(ssl_verify=True, ssl_ca_bundle=None)
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname is True

    def test_invalid_ca_bundle_wraps_as_mail_configuration_error(self, tmp_path: Path) -> None:
        """Invalid CA bundle path is wrapped in MailConfigurationError for the mail layer."""
        bogus = str(tmp_path / "missing.pem")
        with pytest.raises(MailConfigurationError, match="ssl_ca_bundle"):
            _build_smtp_ssl_context(ssl_verify=True, ssl_ca_bundle=bogus)
