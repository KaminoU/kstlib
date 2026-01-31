"""SMTP transport backend with TRACE-level debugging.

When the logger level is set to TRACE, this transport logs detailed
information about the SMTP session including:
- Connection and EHLO exchange
- STARTTLS negotiation and SSL/TLS cipher details
- Authentication flow (credentials redacted)
- Message envelope (MAIL FROM, RCPT TO)

Enable trace logging via configuration:
    logger:
      preset: trace_mail  # Or set level: TRACE directly
"""

from __future__ import annotations

# pylint: disable=too-many-instance-attributes,too-many-arguments,too-few-public-methods
import io
import logging
import smtplib
import ssl
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from kstlib.logging import TRACE_LEVEL
from kstlib.mail.exceptions import MailTransportError
from kstlib.mail.transport import MailTransport

if TYPE_CHECKING:
    from collections.abc import Iterator
    from email.message import EmailMessage

# Module logger - uses kstlib hierarchy for config-driven trace
log = logging.getLogger(__name__)


@contextmanager
def _capture_smtp_debug() -> Iterator[io.StringIO]:
    """Capture smtplib debug output to a StringIO buffer.

    smtplib.set_debuglevel() writes to stderr. This context manager
    temporarily redirects stderr to capture the debug output.

    Yields:
        StringIO buffer containing captured debug output.
    """
    buffer = io.StringIO()
    old_stderr = sys.stderr
    try:
        sys.stderr = buffer
        yield buffer
    finally:
        sys.stderr = old_stderr


def _extract_cn_from_cert_field(field: Any) -> str | None:
    """Extract commonName from a certificate subject or issuer field.

    Certificate fields (subject, issuer) are nested tuples of RDNs (Relative
    Distinguished Names), each containing attribute tuples like ('commonName', 'value').

    Args:
        field: Nested tuple structure from peer_cert['subject'] or ['issuer'].

    Returns:
        The commonName value if found, None otherwise.
    """
    if not field or not isinstance(field, tuple):
        return None
    for rdn in field:
        if not isinstance(rdn, tuple):
            continue
        for attr in rdn:
            if isinstance(attr, tuple) and len(attr) >= 2 and attr[0] == "commonName":
                return str(attr[1])
    return None


def _extract_cipher_info(sock: ssl.SSLSocket) -> dict[str, Any]:
    """Extract cipher information from SSL socket.

    Args:
        sock: The SSL socket after handshake.

    Returns:
        Dictionary with cipher_name, cipher_protocol, cipher_bits.
    """
    info: dict[str, Any] = {}
    try:
        cipher = sock.cipher()
        if cipher:
            info["cipher_name"] = cipher[0]
            info["cipher_protocol"] = cipher[1]
            info["cipher_bits"] = cipher[2]
    except Exception:  # pylint: disable=broad-exception-caught
        pass
    return info


def _extract_cert_info(sock: ssl.SSLSocket) -> dict[str, Any]:
    """Extract peer certificate information from SSL socket.

    Args:
        sock: The SSL socket after handshake.

    Returns:
        Dictionary with peer_cn, issuer_cn, valid_from, valid_until.
    """
    info: dict[str, Any] = {}
    try:
        peer_cert = sock.getpeercert()
        if peer_cert:
            peer_cn = _extract_cn_from_cert_field(peer_cert.get("subject"))
            if peer_cn:
                info["peer_cn"] = peer_cn
            issuer_cn = _extract_cn_from_cert_field(peer_cert.get("issuer"))
            if issuer_cn:
                info["issuer_cn"] = issuer_cn
            if "notBefore" in peer_cert:
                info["valid_from"] = peer_cert["notBefore"]
            if "notAfter" in peer_cert:
                info["valid_until"] = peer_cert["notAfter"]
    except Exception:  # pylint: disable=broad-exception-caught
        pass
    return info


def _extract_ssl_info(sock: ssl.SSLSocket | None) -> dict[str, Any]:
    """Extract SSL/TLS session information for trace logging.

    Args:
        sock: The SSL socket after handshake.

    Returns:
        Dictionary with SSL session details (version, cipher, peer cert).
    """
    if sock is None:
        return {}

    info: dict[str, Any] = {}

    try:
        info["version"] = sock.version()
    except Exception:  # pylint: disable=broad-exception-caught
        info["version"] = "unknown"

    info.update(_extract_cipher_info(sock))
    info.update(_extract_cert_info(sock))

    return info


def _log_ssl_info(client: smtplib.SMTP | smtplib.SMTP_SSL, protocol_label: str) -> None:
    """Log SSL/TLS session information at TRACE level.

    Args:
        client: The SMTP client with an SSL socket.
        protocol_label: Label for the protocol (e.g., "SSL" or "TLS").
    """
    ssl_sock = getattr(client, "sock", None)
    if ssl_sock is None or not hasattr(ssl_sock, "version"):
        return

    ssl_info = _extract_ssl_info(ssl_sock)
    if not ssl_info:
        return

    log.log(
        TRACE_LEVEL,
        "[SMTP] %s: %s, cipher=%s (%d bits)",
        protocol_label,
        ssl_info.get("version", "unknown"),
        ssl_info.get("cipher_name", "unknown"),
        ssl_info.get("cipher_bits", 0),
    )
    if "peer_cn" in ssl_info:
        log.log(
            TRACE_LEVEL,
            "[SMTP] %s peer: CN=%s, issuer=%s",
            protocol_label,
            ssl_info.get("peer_cn", "unknown"),
            ssl_info.get("issuer_cn", "unknown"),
        )


def _log_smtp_debug_output(buffer: io.StringIO) -> None:
    """Parse and log captured smtplib debug output at TRACE level.

    Args:
        buffer: StringIO containing captured debug output.
    """
    if not log.isEnabledFor(TRACE_LEVEL):
        return

    content = buffer.getvalue()
    if not content:
        return

    for line in content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # smtplib debug format: "send: 'EHLO ...'" or "reply: retcode (...);"
        if line.startswith("send:"):
            log.log(TRACE_LEVEL, "[SMTP] >>> %s", line[5:].strip().strip("'\""))
        elif line.startswith("reply:"):
            log.log(TRACE_LEVEL, "[SMTP] <<< %s", line[6:].strip())
        else:
            log.log(TRACE_LEVEL, "[SMTP] %s", line)


@dataclass(frozen=True, slots=True)
class SMTPCredentials:
    """SMTP authentication bundle."""

    username: str
    password: str | None = None


@dataclass(frozen=True, slots=True)
class SMTPSecurity:
    """SMTP security preferences."""

    use_ssl: bool = False
    use_starttls: bool = True
    ssl_context: ssl.SSLContext | None = None


class SMTPTransport(MailTransport):
    """Deliver messages using the standard SMTP protocol."""

    def __init__(
        self,
        host: str,
        port: int = 587,
        *,
        credentials: SMTPCredentials | None = None,
        security: SMTPSecurity | None = None,
        timeout: float | None = None,
    ) -> None:
        """Configure connection parameters for the SMTP backend."""
        self._host = host
        self._port = port
        self._timeout = timeout

        self._username = credentials.username if credentials else None
        self._password = credentials.password if credentials else None

        effective_security = security or SMTPSecurity()
        self._use_ssl = effective_security.use_ssl
        self._use_starttls = effective_security.use_starttls if not effective_security.use_ssl else False
        self._ssl_context = effective_security.ssl_context or ssl.create_default_context()

    def send(self, message: EmailMessage) -> None:
        """Send *message* through the configured SMTP server.

        When TRACE logging is enabled, detailed session information is logged
        including SMTP commands, SSL/TLS handshake details, and message envelope.
        """
        trace_enabled = log.isEnabledFor(TRACE_LEVEL)
        client_kwargs: dict[str, Any] = {"host": self._host, "port": self._port, "timeout": self._timeout}
        client_cls = smtplib.SMTP_SSL if self._use_ssl else smtplib.SMTP
        protocol = "SMTP_SSL" if self._use_ssl else "SMTP"

        if trace_enabled:
            log.log(TRACE_LEVEL, "[SMTP] Connecting to %s:%d (%s)", self._host, self._port, protocol)

        try:
            with _capture_smtp_debug() as debug_buffer, client_cls(**client_kwargs) as client:
                # Enable smtplib debug if trace is on
                if trace_enabled:
                    client.set_debuglevel(2)

                # Initial EHLO
                client.ehlo()

                # Log initial SSL info for SMTP_SSL
                if trace_enabled and self._use_ssl:
                    _log_ssl_info(client, "SSL")

                # STARTTLS upgrade
                if self._use_starttls and client.has_extn("STARTTLS"):
                    if trace_enabled:
                        log.log(TRACE_LEVEL, "[SMTP] Upgrading to TLS via STARTTLS")
                    client.starttls(context=self._ssl_context)
                    client.ehlo()

                    # Log SSL info after STARTTLS
                    if trace_enabled:
                        _log_ssl_info(client, "TLS")

                # Authentication
                if self._username:
                    if trace_enabled:
                        log.log(TRACE_LEVEL, "[SMTP] Authenticating as: %s", self._username)
                    client.login(self._username, self._password or "")
                    if trace_enabled:
                        log.log(TRACE_LEVEL, "[SMTP] Authentication successful")

                # Send message
                if trace_enabled:
                    sender = message.get("From", "unknown")
                    recipients = message.get("To", "unknown")
                    subject = message.get("Subject", "(no subject)")
                    log.log(TRACE_LEVEL, "[SMTP] MAIL FROM: %s", sender)
                    log.log(TRACE_LEVEL, "[SMTP] RCPT TO: %s", recipients)
                    log.log(TRACE_LEVEL, "[SMTP] Subject: %s", subject)

                client.send_message(message)

                if trace_enabled:
                    log.log(TRACE_LEVEL, "[SMTP] Message sent successfully")

            # Log captured smtplib debug output
            if trace_enabled:
                _log_smtp_debug_output(debug_buffer)

        except smtplib.SMTPException as exc:  # pragma: no cover - network dependent
            if trace_enabled:
                log.log(TRACE_LEVEL, "[SMTP] Error: %s", exc)
            raise MailTransportError(str(exc)) from exc


__all__ = ["SMTPCredentials", "SMTPSecurity", "SMTPTransport"]
