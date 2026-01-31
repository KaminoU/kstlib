"""Resend.com API transport for async email delivery.

Resend is a modern email API for developers. This transport sends emails
via the Resend REST API using async HTTP requests.

Requirements:
    pip install httpx

API Documentation:
    https://resend.com/docs/api-reference/emails/send-email

Examples:
    Basic usage with API key::

        from kstlib.mail.transports import ResendTransport

        transport = ResendTransport(api_key="re_123456789")

        # Use with MailBuilder
        mail = MailBuilder(transport=transport)
        await mail.sender("you@example.com").to("user@example.com").send_async()

    With environment variable::

        import os
        transport = ResendTransport(api_key=os.environ["RESEND_API_KEY"])
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from kstlib.logging import TRACE_LEVEL
from kstlib.mail.exceptions import MailConfigurationError, MailTransportError
from kstlib.mail.transport import AsyncMailTransport, handle_http_error_response
from kstlib.utils.http_trace import create_trace_event_hooks

if TYPE_CHECKING:
    from email.message import EmailMessage

    import httpx

__all__ = ["ResendTransport"]

log = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


@dataclass(frozen=True, slots=True)
class ResendResponse:
    """Response from Resend API after sending an email.

    Attributes:
        id: The unique ID assigned to the sent email.
    """

    id: str


class ResendTransport(AsyncMailTransport):
    """Async transport for sending emails via Resend.com API.

    Resend provides a simple REST API for sending transactional emails.
    This transport converts EmailMessage objects to Resend's JSON format
    and sends them asynchronously using httpx.

    Args:
        api_key: Resend API key (starts with 're_').
        base_url: API base URL (default: https://api.resend.com/emails).
        timeout: Request timeout in seconds (default: 30.0).

    Examples:
        Basic send::

            transport = ResendTransport(api_key="re_123456789")

            message = EmailMessage()
            message["From"] = "sender@example.com"
            message["To"] = "recipient@example.com"
            message["Subject"] = "Hello"
            message.set_content("Plain text body")

            await transport.send(message)

        With HTML content::

            message = EmailMessage()
            message["From"] = "sender@example.com"
            message["To"] = "recipient@example.com"
            message["Subject"] = "Welcome"
            message.set_content("Plain text fallback")
            message.add_alternative("<h1>Welcome!</h1>", subtype="html")

            await transport.send(message)
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = RESEND_API_URL,
        timeout: float = 30.0,
    ) -> None:
        """Initialize the Resend transport.

        Args:
            api_key: Resend API key.
            base_url: API endpoint URL.
            timeout: Request timeout in seconds.

        Raises:
            MailConfigurationError: If api_key is empty.
        """
        if not api_key:
            raise MailConfigurationError("Resend API key is required")

        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout
        self._last_response: ResendResponse | None = None

    @property
    def last_response(self) -> ResendResponse | None:
        """Return the response from the last successful send."""
        return self._last_response

    async def send(self, message: EmailMessage) -> None:
        """Send an email via the Resend API.

        Converts the EmailMessage to Resend's JSON format and posts it
        to the API. Supports plain text, HTML, and attachments.

        When TRACE logging is enabled, detailed HTTP request/response
        information is logged including headers and body.

        Args:
            message: The email message to send.

        Raises:
            MailTransportError: If the API request fails.
            MailConfigurationError: If required fields are missing.
        """
        try:
            import httpx
        except ImportError as e:
            raise MailConfigurationError(
                "httpx is required for ResendTransport. Install with: pip install httpx"
            ) from e

        payload = self._build_payload(message)

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        # Setup trace logging if enabled
        event_hooks, trace_enabled = create_trace_event_hooks(log, TRACE_LEVEL)
        if trace_enabled:
            log.log(TRACE_LEVEL, "[Resend] Sending email via Resend API")
            log.log(TRACE_LEVEL, "[Resend] From: %s, To: %s", message.get("From"), message.get("To"))

        try:
            async with httpx.AsyncClient(timeout=self._timeout, event_hooks=event_hooks) as client:
                response = await client.post(
                    self._base_url,
                    json=payload,
                    headers=headers,
                )

                if response.status_code >= 400:
                    self._handle_error_response(response)

                data = response.json()
                self._last_response = ResendResponse(id=data.get("id", ""))
                log.debug("Email sent via Resend: %s", self._last_response.id)
                if trace_enabled:
                    log.log(TRACE_LEVEL, "[Resend] Message sent successfully, id=%s", self._last_response.id)

        except httpx.TimeoutException as e:
            if trace_enabled:
                log.log(TRACE_LEVEL, "[Resend] Timeout error: %s", e)
            raise MailTransportError(f"Resend API timeout: {e}") from e
        except httpx.RequestError as e:
            if trace_enabled:
                log.log(TRACE_LEVEL, "[Resend] Request error: %s", e)
            raise MailTransportError(f"Resend API request failed: {e}") from e

    def _build_payload(self, message: EmailMessage) -> dict[str, Any]:
        """Convert EmailMessage to Resend API payload.

        Args:
            message: The email message.

        Returns:
            Dict suitable for JSON serialization.

        Raises:
            MailConfigurationError: If required fields are missing.
        """
        from_addr = message.get("From")
        if not from_addr:
            raise MailConfigurationError("Email must have a From address")

        to_addrs = self._parse_recipients(message.get("To", ""))
        if not to_addrs:
            raise MailConfigurationError("Email must have at least one To address")

        payload: dict[str, Any] = {
            "from": from_addr,
            "to": to_addrs,
            "subject": message.get("Subject", ""),
        }

        # Add CC and BCC if present
        cc_addrs = self._parse_recipients(message.get("Cc", ""))
        if cc_addrs:
            payload["cc"] = cc_addrs

        bcc_addrs = self._parse_recipients(message.get("Bcc", ""))
        if bcc_addrs:
            payload["bcc"] = bcc_addrs

        # Add Reply-To if present
        reply_to = message.get("Reply-To")
        if reply_to:
            payload["reply_to"] = reply_to

        # Extract body content
        self._add_body_content(message, payload)

        # Extract attachments
        attachments = self._extract_attachments(message)
        if attachments:
            payload["attachments"] = attachments

        return payload

    def _parse_recipients(self, header_value: str) -> list[str]:
        """Parse comma-separated email addresses.

        Args:
            header_value: The header value (e.g., "a@x.com, b@x.com").

        Returns:
            List of email addresses.
        """
        if not header_value:
            return []
        return [addr.strip() for addr in header_value.split(",") if addr.strip()]

    def _add_body_content(self, message: EmailMessage, payload: dict[str, Any]) -> None:
        """Extract and add body content to payload.

        Args:
            message: The email message.
            payload: The API payload to update.
        """
        # Get the message body - handle multipart
        # Note: get_content() adds trailing newline, so we strip it
        if message.is_multipart():
            for part in message.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain" and "text" not in payload:
                    content = part.get_content()
                    if isinstance(content, str):
                        payload["text"] = content.rstrip("\n")
                elif content_type == "text/html" and "html" not in payload:
                    content = part.get_content()
                    if isinstance(content, str):
                        payload["html"] = content.rstrip("\n")
        else:
            # Simple message
            content = message.get_content()
            if isinstance(content, str):
                text = content.rstrip("\n")
                if message.get_content_type() == "text/html":
                    payload["html"] = text
                else:
                    payload["text"] = text

    def _extract_attachments(self, message: EmailMessage) -> list[dict[str, str]]:
        """Extract attachments from the email message.

        Args:
            message: The email message.

        Returns:
            List of attachment dicts with filename and base64 content.
        """
        attachments: list[dict[str, str]] = []

        if not message.is_multipart():
            return attachments

        for part in message.walk():
            content_disposition = part.get("Content-Disposition", "")
            if "attachment" in content_disposition:
                filename = part.get_filename() or "attachment"
                content = part.get_payload(decode=True)
                if isinstance(content, bytes):
                    attachments.append(
                        {
                            "filename": filename,
                            "content": base64.b64encode(content).decode("ascii"),
                        }
                    )

        return attachments

    def _handle_error_response(self, response: httpx.Response) -> None:
        """Handle error response from Resend API.

        Args:
            response: The HTTP response.

        Raises:
            MailTransportError: Always raises with error details.
        """
        handle_http_error_response(response, "Resend", log)
