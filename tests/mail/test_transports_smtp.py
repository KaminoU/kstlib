"""Tests for the SMTP transport backend."""

from __future__ import annotations

import io
import logging
from email.message import EmailMessage
from smtplib import SMTPException
from typing import Any, ClassVar

import pytest

from kstlib.logging import TRACE_LEVEL
from kstlib.mail import MailTransportError
from kstlib.mail.transports.smtp import (
    SMTPCredentials,
    SMTPSecurity,
    SMTPTransport,
    _capture_smtp_debug,
    _extract_ssl_info,
    _log_smtp_debug_output,
)


class DummySMTP:
    """Minimal SMTP client capturing invocations."""

    created: ClassVar[list[DummySMTP]] = []
    last_instance: ClassVar[DummySMTP | None] = None
    supports_starttls: ClassVar[bool] = True

    def __init__(self, **kwargs: Any) -> None:
        """Capture constructor kwargs and initialise tracking state."""
        self.kwargs = kwargs
        self.ehlo_called = 0
        self.starttls_called = False
        self.login_calls: list[tuple[str | None, str | None]] = []
        self.sent_messages: list[EmailMessage] = []
        self.closed = False
        self.starttls_context: Any | None = None
        DummySMTP.created.append(self)

    def __enter__(self) -> DummySMTP:
        """Register instance as the last active client."""
        DummySMTP.last_instance = self
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> None:  # pragma: no cover - trivial
        """Mark the client as closed when leaving the context manager."""
        self.closed = True

    def ehlo(self) -> None:
        """Record EHLO invocations."""
        self.ehlo_called += 1

    def has_extn(self, name: str) -> bool:
        """Report supported SMTP extensions."""
        return name == "STARTTLS" and self.supports_starttls

    def starttls(self, *, context: Any) -> None:
        """Flag that STARTTLS was invoked and capture its context."""
        self.starttls_called = True
        self.starttls_context = context

    def login(self, username: str | None, password: str | None) -> None:
        """Track login attempts."""
        self.login_calls.append((username, password))

    def send_message(self, message: EmailMessage) -> None:
        """Collect outgoing messages for later inspection."""
        self.sent_messages.append(message)

    def set_debuglevel(self, level: int) -> None:
        """Accept debug level setting (used by TRACE logging)."""
        self.debug_level = level


class ExplodingSMTP(DummySMTP):
    """Dummy SMTP client that raises on send."""

    def send_message(self, message: EmailMessage) -> None:  # pragma: no cover - raises
        """Always raise an SMTPException to simulate transport errors."""
        raise SMTPException("boom")


@pytest.fixture(name="email_message")
def _email_message() -> EmailMessage:
    message = EmailMessage()
    message["From"] = "sender@example.com"
    message["To"] = "user@example.com"
    message.set_content("Hello")
    return message


def _reset_dummy() -> None:
    """Reset dummy class state between tests."""
    DummySMTP.created.clear()
    DummySMTP.last_instance = None
    DummySMTP.supports_starttls = True


def test_starttls_and_login(monkeypatch: pytest.MonkeyPatch, email_message: EmailMessage) -> None:
    """Upgrade to STARTTLS and authenticate before sending."""
    _reset_dummy()
    monkeypatch.setattr("kstlib.mail.transports.smtp.smtplib.SMTP", DummySMTP)

    credentials = SMTPCredentials(username="user", password="pass")
    transport = SMTPTransport("smtp.example.com", credentials=credentials)
    transport.send(email_message)

    client = DummySMTP.last_instance
    assert client is not None
    assert client.kwargs["host"] == "smtp.example.com"
    assert client.kwargs["port"] == 587
    assert "timeout" in client.kwargs
    assert client.starttls_called is True
    assert client.ehlo_called == 2  # once before and once after STARTTLS
    assert client.login_calls == [("user", "pass")]
    assert client.sent_messages == [email_message]
    assert client.closed is True


def test_use_ssl_prefers_smtps(monkeypatch: pytest.MonkeyPatch, email_message: EmailMessage) -> None:
    """Select SMTP_SSL when explicit SSL is requested."""
    _reset_dummy()

    class ForbiddenSMTP(DummySMTP):
        """Fail if the plain SMTP client is initialised."""

        def __init__(self, **kwargs: Any) -> None:  # pragma: no cover - ensures SMTP is unused
            super().__init__(**kwargs)
            pytest.fail("Plain SMTP client must not be initialised when use_ssl=True")

    monkeypatch.setattr("kstlib.mail.transports.smtp.smtplib.SMTP", ForbiddenSMTP)
    monkeypatch.setattr("kstlib.mail.transports.smtp.smtplib.SMTP_SSL", DummySMTP)

    security = SMTPSecurity(use_ssl=True, use_starttls=True)
    transport = SMTPTransport("smtp.example.com", port=465, security=security)
    transport.send(email_message)

    client = DummySMTP.last_instance
    assert isinstance(client, DummySMTP)
    assert client.starttls_called is False  # STARTTLS disabled when using SSL
    assert client.ehlo_called == 1  # only the initial EHLO runs


def test_wraps_smtplib_errors(monkeypatch: pytest.MonkeyPatch, email_message: EmailMessage) -> None:
    """Translate smtplib exceptions into MailTransportError."""
    _reset_dummy()
    monkeypatch.setattr("kstlib.mail.transports.smtp.smtplib.SMTP", ExplodingSMTP)

    security = SMTPSecurity(use_starttls=False)
    transport = SMTPTransport("smtp.example.com", security=security)

    with pytest.raises(MailTransportError, match="boom"):
        transport.send(email_message)


# ---------------------------------------------------------------------------
# Tests for _capture_smtp_debug context manager
# ---------------------------------------------------------------------------


def test_capture_smtp_debug_captures_stderr() -> None:
    """Context manager captures stderr output."""
    import sys

    with _capture_smtp_debug() as buffer:
        print("debug output", file=sys.stderr)
    assert "debug output" in buffer.getvalue()


def test_capture_smtp_debug_restores_stderr() -> None:
    """Context manager restores original stderr after exit."""
    import sys

    original_stderr = sys.stderr
    with _capture_smtp_debug():
        pass
    assert sys.stderr is original_stderr


# ---------------------------------------------------------------------------
# Tests for _extract_ssl_info
# ---------------------------------------------------------------------------


def test_extract_ssl_info_returns_empty_for_none() -> None:
    """Return empty dict when socket is None."""
    result = _extract_ssl_info(None)
    assert result == {}


class MockSSLSocket:
    """Mock SSL socket for testing _extract_ssl_info."""

    def __init__(
        self,
        *,
        version: str | None = "TLSv1.3",
        cipher: tuple[str, str, int] | None = ("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256),
        peer_cert: dict[str, Any] | None = None,
        raise_on_version: bool = False,
        raise_on_cipher: bool = False,
        raise_on_cert: bool = False,
    ) -> None:
        """Configure mock SSL socket behavior."""
        self._version = version
        self._cipher = cipher
        self._peer_cert = peer_cert
        self._raise_on_version = raise_on_version
        self._raise_on_cipher = raise_on_cipher
        self._raise_on_cert = raise_on_cert

    def version(self) -> str | None:
        """Return mock TLS version."""
        if self._raise_on_version:
            raise RuntimeError("version error")
        return self._version

    def cipher(self) -> tuple[str, str, int] | None:
        """Return mock cipher info."""
        if self._raise_on_cipher:
            raise RuntimeError("cipher error")
        return self._cipher

    def getpeercert(self) -> dict[str, Any] | None:
        """Return mock peer certificate."""
        if self._raise_on_cert:
            raise RuntimeError("cert error")
        return self._peer_cert


def test_extract_ssl_info_basic() -> None:
    """Extract version and cipher from SSL socket."""
    sock = MockSSLSocket()
    result = _extract_ssl_info(sock)  # type: ignore[arg-type]
    assert result["version"] == "TLSv1.3"
    assert result["cipher_name"] == "TLS_AES_256_GCM_SHA384"
    assert result["cipher_protocol"] == "TLSv1.3"
    assert result["cipher_bits"] == 256


def test_extract_ssl_info_with_peer_cert() -> None:
    """Extract peer certificate CN and issuer."""
    peer_cert = {
        "subject": ((("commonName", "mail.example.com"),),),
        "issuer": ((("commonName", "Let's Encrypt"),),),
        "notBefore": "Jan  1 00:00:00 2024 GMT",
        "notAfter": "Dec 31 23:59:59 2024 GMT",
    }
    sock = MockSSLSocket(peer_cert=peer_cert)
    result = _extract_ssl_info(sock)  # type: ignore[arg-type]
    assert result["peer_cn"] == "mail.example.com"
    assert result["issuer_cn"] == "Let's Encrypt"
    assert result["valid_from"] == "Jan  1 00:00:00 2024 GMT"
    assert result["valid_until"] == "Dec 31 23:59:59 2024 GMT"


def test_extract_ssl_info_handles_version_error() -> None:
    """Handle exception when getting TLS version."""
    sock = MockSSLSocket(raise_on_version=True)
    result = _extract_ssl_info(sock)  # type: ignore[arg-type]
    assert result["version"] == "unknown"


def test_extract_ssl_info_handles_cipher_error() -> None:
    """Handle exception when getting cipher info."""
    sock = MockSSLSocket(raise_on_cipher=True)
    result = _extract_ssl_info(sock)  # type: ignore[arg-type]
    assert "cipher_name" not in result


def test_extract_ssl_info_handles_cert_error() -> None:
    """Handle exception when getting peer certificate."""
    sock = MockSSLSocket(raise_on_cert=True)
    result = _extract_ssl_info(sock)  # type: ignore[arg-type]
    assert "peer_cn" not in result


def test_extract_ssl_info_no_cipher() -> None:
    """Handle None cipher gracefully."""
    sock = MockSSLSocket(cipher=None)
    result = _extract_ssl_info(sock)  # type: ignore[arg-type]
    assert "cipher_name" not in result


def test_extract_ssl_info_empty_peer_cert() -> None:
    """Handle empty peer certificate dict."""
    sock = MockSSLSocket(peer_cert={})
    result = _extract_ssl_info(sock)  # type: ignore[arg-type]
    assert "peer_cn" not in result


def test_extract_ssl_info_malformed_subject() -> None:
    """Handle malformed subject in peer certificate."""
    peer_cert = {
        "subject": "not a tuple",  # Invalid format
    }
    sock = MockSSLSocket(peer_cert=peer_cert)
    result = _extract_ssl_info(sock)  # type: ignore[arg-type]
    assert "peer_cn" not in result


def test_extract_ssl_info_malformed_issuer() -> None:
    """Handle malformed issuer in peer certificate."""
    peer_cert = {
        "subject": ((("commonName", "example.com"),),),
        "issuer": "not a tuple",  # Invalid format
    }
    sock = MockSSLSocket(peer_cert=peer_cert)
    result = _extract_ssl_info(sock)  # type: ignore[arg-type]
    assert result["peer_cn"] == "example.com"
    assert "issuer_cn" not in result


# ---------------------------------------------------------------------------
# Tests for _log_smtp_debug_output
# ---------------------------------------------------------------------------


def test_log_smtp_debug_output_skips_if_trace_disabled(caplog: pytest.LogCaptureFixture) -> None:
    """Skip logging when TRACE level is not enabled."""
    buffer = io.StringIO("send: 'EHLO example.com'\n")
    # Default log level is WARNING, so TRACE is disabled
    with caplog.at_level(logging.WARNING):
        _log_smtp_debug_output(buffer)
    assert len(caplog.records) == 0


def test_log_smtp_debug_output_parses_send_lines(caplog: pytest.LogCaptureFixture) -> None:
    """Parse and log smtplib 'send:' debug lines."""
    buffer = io.StringIO("send: 'EHLO example.com'\n")
    with caplog.at_level(TRACE_LEVEL, logger="kstlib.mail.transports.smtp"):
        _log_smtp_debug_output(buffer)
    assert any("[SMTP] >>>" in r.message and "EHLO example.com" in r.message for r in caplog.records)


def test_log_smtp_debug_output_parses_reply_lines(caplog: pytest.LogCaptureFixture) -> None:
    """Parse and log smtplib 'reply:' debug lines."""
    buffer = io.StringIO("reply: retcode (250); Msg: b'OK'\n")
    with caplog.at_level(TRACE_LEVEL, logger="kstlib.mail.transports.smtp"):
        _log_smtp_debug_output(buffer)
    assert any("[SMTP] <<<" in r.message for r in caplog.records)


def test_log_smtp_debug_output_handles_other_lines(caplog: pytest.LogCaptureFixture) -> None:
    """Log other debug lines without prefix."""
    buffer = io.StringIO("some other debug info\n")
    with caplog.at_level(TRACE_LEVEL, logger="kstlib.mail.transports.smtp"):
        _log_smtp_debug_output(buffer)
    assert any("[SMTP] some other debug info" in r.message for r in caplog.records)


def test_log_smtp_debug_output_skips_empty_buffer(caplog: pytest.LogCaptureFixture) -> None:
    """Skip logging when buffer is empty."""
    buffer = io.StringIO("")
    with caplog.at_level(TRACE_LEVEL, logger="kstlib.mail.transports.smtp"):
        _log_smtp_debug_output(buffer)
    assert len(caplog.records) == 0


def test_log_smtp_debug_output_skips_blank_lines(caplog: pytest.LogCaptureFixture) -> None:
    """Skip blank lines in debug output."""
    buffer = io.StringIO("\n\n   \n")
    with caplog.at_level(TRACE_LEVEL, logger="kstlib.mail.transports.smtp"):
        _log_smtp_debug_output(buffer)
    assert len(caplog.records) == 0


# ---------------------------------------------------------------------------
# Tests for SMTPTransport with TRACE logging enabled
# ---------------------------------------------------------------------------


class DummySMTPWithSSL(DummySMTP):
    """Dummy SMTP client with mock SSL socket."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize with mock SSL socket."""
        super().__init__(**kwargs)
        self.sock = MockSSLSocket(
            peer_cert={
                "subject": ((("commonName", "smtp.example.com"),),),
                "issuer": ((("commonName", "Test CA"),),),
            }
        )


def test_send_with_trace_logging_smtp_ssl(
    monkeypatch: pytest.MonkeyPatch,
    email_message: EmailMessage,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Log SSL info when using SMTP_SSL with TRACE enabled."""
    _reset_dummy()
    monkeypatch.setattr("kstlib.mail.transports.smtp.smtplib.SMTP_SSL", DummySMTPWithSSL)

    security = SMTPSecurity(use_ssl=True)
    transport = SMTPTransport("smtp.example.com", port=465, security=security)

    with caplog.at_level(TRACE_LEVEL, logger="kstlib.mail.transports.smtp"):
        transport.send(email_message)

    # Verify SSL logging occurred
    log_messages = [r.message for r in caplog.records]
    assert any("Connecting to" in m for m in log_messages)
    assert any("TLSv1.3" in m or "SSL:" in m for m in log_messages)


def test_send_with_trace_logging_starttls(
    monkeypatch: pytest.MonkeyPatch,
    email_message: EmailMessage,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Log TLS info after STARTTLS upgrade with TRACE enabled."""
    _reset_dummy()

    class DummySMTPWithStartTLS(DummySMTP):
        """Dummy SMTP that gains SSL socket after STARTTLS."""

        def starttls(self, *, context: Any) -> None:
            """Simulate STARTTLS by adding mock SSL socket."""
            super().starttls(context=context)
            self.sock = MockSSLSocket(
                peer_cert={
                    "subject": ((("commonName", "smtp.example.com"),),),
                    "issuer": ((("commonName", "Test CA"),),),
                }
            )

    monkeypatch.setattr("kstlib.mail.transports.smtp.smtplib.SMTP", DummySMTPWithStartTLS)

    transport = SMTPTransport("smtp.example.com")

    with caplog.at_level(TRACE_LEVEL, logger="kstlib.mail.transports.smtp"):
        transport.send(email_message)

    # Verify TLS logging occurred
    log_messages = [r.message for r in caplog.records]
    assert any("STARTTLS" in m for m in log_messages)
    assert any("TLS:" in m for m in log_messages)


def test_send_with_trace_logs_message_envelope(
    monkeypatch: pytest.MonkeyPatch,
    email_message: EmailMessage,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Log message envelope (From, To, Subject) with TRACE enabled."""
    _reset_dummy()
    monkeypatch.setattr("kstlib.mail.transports.smtp.smtplib.SMTP", DummySMTP)

    security = SMTPSecurity(use_starttls=False)
    transport = SMTPTransport("smtp.example.com", security=security)

    with caplog.at_level(TRACE_LEVEL, logger="kstlib.mail.transports.smtp"):
        transport.send(email_message)

    log_messages = [r.message for r in caplog.records]
    assert any("MAIL FROM:" in m for m in log_messages)
    assert any("RCPT TO:" in m for m in log_messages)
    assert any("Message sent successfully" in m for m in log_messages)


def test_send_with_trace_logs_authentication(
    monkeypatch: pytest.MonkeyPatch,
    email_message: EmailMessage,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Log authentication steps with TRACE enabled and credentials."""
    _reset_dummy()
    monkeypatch.setattr("kstlib.mail.transports.smtp.smtplib.SMTP", DummySMTP)

    credentials = SMTPCredentials(username="user@example.com", password="secret")
    security = SMTPSecurity(use_starttls=False)
    transport = SMTPTransport("smtp.example.com", credentials=credentials, security=security)

    with caplog.at_level(TRACE_LEVEL, logger="kstlib.mail.transports.smtp"):
        transport.send(email_message)

    log_messages = [r.message for r in caplog.records]
    assert any("Authenticating as:" in m for m in log_messages)
    assert any("Authentication successful" in m for m in log_messages)
