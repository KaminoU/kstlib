"""Mail composition and transport helpers.

Provides a fluent interface for building and sending emails with support
for both sync and async transports.

Examples:
    Build and send via SMTP::

        from kstlib.mail import MailBuilder
        from kstlib.mail.transports import SMTPTransport

        transport = SMTPTransport(host="smtp.example.com", port=587)
        mail = MailBuilder(transport=transport)
        mail.sender("me@example.com").to("you@example.com").subject("Hi").message("Hello!").send()

    Async send via Resend::

        from kstlib.mail import MailBuilder
        from kstlib.mail.transports import ResendTransport

        transport = ResendTransport(api_key="re_123")
        # Use with async context
        await transport.send(message)
"""

from kstlib.mail.builder import MailBuilder, NotifyResult
from kstlib.mail.exceptions import MailConfigurationError, MailError, MailTransportError, MailValidationError
from kstlib.mail.filesystem import MailFilesystemGuards
from kstlib.mail.transport import AsyncMailTransport, AsyncTransportWrapper, MailTransport

__all__ = [
    "AsyncMailTransport",
    "AsyncTransportWrapper",
    "MailBuilder",
    "MailConfigurationError",
    "MailError",
    "MailFilesystemGuards",
    "MailTransport",
    "MailTransportError",
    "MailValidationError",
    "NotifyResult",
]
