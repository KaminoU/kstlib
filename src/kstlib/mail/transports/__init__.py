"""Transport implementations for mail delivery.

Available transports:
    - SMTPTransport: Standard SMTP protocol (sync)
    - ResendTransport: Resend.com API (async)
    - GmailTransport: Gmail API with OAuth2 (async)
    - SesTransport: AWS SES raw email (async)
"""

from kstlib.mail.transports.gmail import GmailTransport
from kstlib.mail.transports.resend import ResendTransport
from kstlib.mail.transports.ses import SesTransport
from kstlib.mail.transports.smtp import SMTPCredentials, SMTPSecurity, SMTPTransport

__all__ = [
    "GmailTransport",
    "ResendTransport",
    "SMTPCredentials",
    "SMTPSecurity",
    "SMTPTransport",
    "SesTransport",
]
