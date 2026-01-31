"""Gmail API transport for async email delivery via OAuth2.

Send emails through the Gmail API using OAuth2 authentication. This transport
integrates with the kstlib.auth module for token management.

Requirements:
    pip install httpx

OAuth2 Scopes:
    https://www.googleapis.com/auth/gmail.send

API Documentation:
    https://developers.google.com/gmail/api/reference/rest/v1/users.messages/send

Examples:
    Using a Token directly::

        from kstlib.auth import Token
        from kstlib.mail.transports import GmailTransport

        token = Token(access_token="ya29.xxx", scope=["gmail.send"])
        transport = GmailTransport(token=token)
        await transport.send(message)

    Using TokenStorage from kstlib.auth::

        from kstlib.auth import OIDCProvider, AuthSession
        from kstlib.mail.transports import GmailTransport

        provider = OIDCProvider.from_config("google")
        with AuthSession(provider) as session:
            token = provider.get_token()
            transport = GmailTransport(token=token)
            await transport.send(message)
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from kstlib.logging import TRACE_LEVEL
from kstlib.mail.exceptions import MailConfigurationError, MailTransportError
from kstlib.mail.transport import AsyncMailTransport, handle_http_error_response
from kstlib.utils.http_trace import create_trace_event_hooks

if TYPE_CHECKING:
    from email.message import EmailMessage

    import httpx

    from kstlib.auth import Token

__all__ = ["GmailTransport"]

log = logging.getLogger(__name__)

GMAIL_API_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


@dataclass(frozen=True, slots=True)
class GmailResponse:
    """Response from Gmail API after sending an email.

    Attributes:
        id: The immutable ID of the sent message.
        thread_id: The ID of the thread the message belongs to.
        label_ids: List of label IDs applied to this message.
    """

    id: str
    thread_id: str
    label_ids: list[str]


class GmailTransport(AsyncMailTransport):
    """Async transport for sending emails via Gmail API.

    Uses OAuth2 Bearer token authentication. The token must have the
    'https://www.googleapis.com/auth/gmail.send' scope.

    Args:
        token: OAuth2 token from kstlib.auth module.
        base_url: API endpoint URL (default: Gmail send endpoint).
        timeout: Request timeout in seconds (default: 30.0).

    Raises:
        MailConfigurationError: If token is missing or invalid.

    Examples:
        Basic send::

            from kstlib.auth import Token
            from kstlib.mail.transports import GmailTransport

            token = Token(access_token="ya29.xxx")
            transport = GmailTransport(token=token)

            message = EmailMessage()
            message["From"] = "sender@gmail.com"
            message["To"] = "recipient@example.com"
            message["Subject"] = "Hello"
            message.set_content("Email body")

            await transport.send(message)

        With token refresh callback::

            async def refresh_token() -> Token:
                # Refresh logic using kstlib.auth
                return new_token

            transport = GmailTransport(
                token=token,
                on_token_refresh=refresh_token,
            )
    """

    def __init__(
        self,
        token: Token,
        *,
        base_url: str = GMAIL_API_URL,
        timeout: float = 30.0,
    ) -> None:
        """Initialize the Gmail transport.

        Args:
            token: OAuth2 token with gmail.send scope.
            base_url: API endpoint URL.
            timeout: Request timeout in seconds.

        Raises:
            MailConfigurationError: If token is None or has no access_token.
        """
        if token is None:
            raise MailConfigurationError("OAuth2 token is required for GmailTransport")

        if not token.access_token:
            raise MailConfigurationError("Token must have an access_token")

        self._token = token
        self._base_url = base_url
        self._timeout = timeout
        self._last_response: GmailResponse | None = None

    @property
    def token(self) -> Token:
        """Return the current OAuth2 token."""
        return self._token

    @property
    def last_response(self) -> GmailResponse | None:
        """Return the response from the last successful send."""
        return self._last_response

    def update_token(self, token: Token) -> None:
        """Update the OAuth2 token (e.g., after refresh).

        Args:
            token: New OAuth2 token.
        """
        self._token = token

    async def send(self, message: EmailMessage) -> None:
        """Send an email via the Gmail API.

        Encodes the EmailMessage in base64url format and posts it to the
        Gmail API. The sender must match the authenticated user's email
        address (or an alias).

        When TRACE logging is enabled, detailed HTTP request/response
        information is logged including headers and body.

        Args:
            message: The email message to send.

        Raises:
            MailTransportError: If the API request fails.
            MailConfigurationError: If httpx is not installed.
        """
        try:
            import httpx
        except ImportError as e:
            raise MailConfigurationError("httpx is required for GmailTransport. Install with: pip install httpx") from e

        # Check token expiration
        if self._token.is_expired:
            log.warning("OAuth2 token is expired, request may fail")

        # Encode message as base64url
        raw_message = self._encode_message(message)
        payload = {"raw": raw_message}

        headers = {
            "Authorization": f"Bearer {self._token.access_token}",
            "Content-Type": "application/json",
        }

        # Setup trace logging if enabled
        event_hooks, trace_enabled = create_trace_event_hooks(log, TRACE_LEVEL)
        if trace_enabled:
            log.log(TRACE_LEVEL, "[Gmail] Sending email via Gmail API")
            log.log(TRACE_LEVEL, "[Gmail] From: %s, To: %s", message.get("From"), message.get("To"))

        try:
            async with httpx.AsyncClient(timeout=self._timeout, event_hooks=event_hooks) as client:
                response = await client.post(
                    self._base_url,
                    json=payload,
                    headers=headers,
                )

                if response.status_code == 401:
                    raise MailTransportError("Gmail API authentication failed. Token may be expired or revoked.")

                if response.status_code >= 400:
                    self._handle_error_response(response)

                data = response.json()
                self._last_response = GmailResponse(
                    id=data.get("id", ""),
                    thread_id=data.get("threadId", ""),
                    label_ids=data.get("labelIds", []),
                )
                log.debug("Email sent via Gmail API: %s", self._last_response.id)
                if trace_enabled:
                    log.log(TRACE_LEVEL, "[Gmail] Message sent successfully, id=%s", self._last_response.id)

        except httpx.TimeoutException as e:
            if trace_enabled:
                log.log(TRACE_LEVEL, "[Gmail] Timeout error: %s", e)
            raise MailTransportError(f"Gmail API timeout: {e}") from e
        except httpx.RequestError as e:
            if trace_enabled:
                log.log(TRACE_LEVEL, "[Gmail] Request error: %s", e)
            raise MailTransportError(f"Gmail API request failed: {e}") from e

    def _encode_message(self, message: EmailMessage) -> str:
        """Encode EmailMessage to base64url string.

        Gmail API expects the raw RFC 2822 message encoded in base64url
        (URL-safe base64 without padding).

        Args:
            message: The email message.

        Returns:
            Base64url encoded message string.
        """
        raw_bytes = message.as_bytes()
        # base64url encoding (URL-safe, no padding)
        encoded = base64.urlsafe_b64encode(raw_bytes).decode("ascii")
        # Remove padding (Gmail API expects no padding)
        return encoded.rstrip("=")

    def _handle_error_response(self, response: httpx.Response) -> None:
        """Handle error response from Gmail API.

        Args:
            response: The HTTP response.

        Raises:
            MailTransportError: Always raises with error details.
        """
        handle_http_error_response(response, "Gmail", log, extract_code=True)
