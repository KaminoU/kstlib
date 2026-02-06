"""AWS SES transport for async email delivery.

Sends emails via the AWS Simple Email Service (SES) using raw MIME messages.
The boto3 client is synchronous, so calls are wrapped with ``run_in_executor``
to avoid blocking the async event loop.

Requirements:
    pip install kstlib[ses]

Examples:
    Basic usage with default credential chain (recommended on EC2)::

        from kstlib.mail.transports import SesTransport

        transport = SesTransport(region="eu-west-3")

        # Use with MailBuilder
        mail = MailBuilder(transport=transport)
        await mail.sender("you@example.com").to("user@example.com").send_async()

    With explicit credentials::

        transport = SesTransport(
            region="us-east-1",
            aws_access_key_id="AKIA...",
            aws_secret_access_key="secret...",
        )
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from kstlib.logging import TRACE_LEVEL
from kstlib.mail.exceptions import MailConfigurationError, MailTransportError
from kstlib.mail.transport import AsyncMailTransport

if TYPE_CHECKING:
    from email.message import EmailMessage

__all__ = ["SesTransport"]

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SesResponse:
    """Response from AWS SES after sending an email.

    Attributes:
        message_id: The unique message ID assigned by SES.
    """

    message_id: str


class SesTransport(AsyncMailTransport):
    """Async transport for sending emails via AWS SES.

    Uses ``send_raw_email`` to pass the full MIME message directly to SES,
    which preserves all headers, attachments, and HTML content without
    conversion.

    Args:
        region: AWS region for the SES endpoint (default: ``eu-west-3``).
        aws_access_key_id: Explicit AWS access key. If omitted, boto3 uses
            its default credential chain (env vars, instance profile, etc.).
        aws_secret_access_key: Explicit AWS secret key. Must be provided
            together with *aws_access_key_id*.
        timeout: Boto3 connect/read timeout in seconds (default: 30.0).

    Raises:
        MailConfigurationError: If *region* is empty, *timeout* is not
            positive, or only one of the two credential arguments is given.

    Examples:
        Send with EC2 instance profile (no explicit credentials)::

            transport = SesTransport(region="eu-west-3")
            await transport.send(message)

        Send with explicit credentials::

            transport = SesTransport(
                region="us-east-1",
                aws_access_key_id="AKIA...",
                aws_secret_access_key="secret...",
            )
            await transport.send(message)
    """

    def __init__(
        self,
        *,
        region: str = "eu-west-3",
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not region:
            raise MailConfigurationError("AWS region is required")

        has_key = aws_access_key_id is not None
        has_secret = aws_secret_access_key is not None
        if has_key != has_secret:
            raise MailConfigurationError("Both aws_access_key_id and aws_secret_access_key must be provided together")

        if timeout <= 0:
            raise MailConfigurationError("Timeout must be greater than 0")

        self._region = region
        self._aws_access_key_id = aws_access_key_id
        self._aws_secret_access_key = aws_secret_access_key
        self._timeout = timeout
        self._last_response: SesResponse | None = None

    @property
    def last_response(self) -> SesResponse | None:
        """Return the response from the last successful send."""
        return self._last_response

    async def send(self, message: EmailMessage) -> None:
        """Send an email via AWS SES using ``send_raw_email``.

        The message is sent as raw MIME bytes, preserving all headers,
        body parts, and attachments exactly as built by :class:`EmailMessage`.

        Boto3 is synchronous, so the actual API call runs inside
        ``run_in_executor`` to keep the event loop free.

        When TRACE logging is enabled, request metadata is logged.

        Args:
            message: The email message to send.

        Raises:
            MailTransportError: If the SES API call fails.
            MailConfigurationError: If boto3 is not installed or AWS
                credentials cannot be resolved.
        """
        try:
            import boto3
            from botocore.config import Config as BotoConfig
            from botocore.exceptions import (
                ClientError,
                EndpointConnectionError,
                NoCredentialsError,
            )
        except ImportError as e:
            raise MailConfigurationError(
                "boto3 is required for SesTransport. Install with: pip install kstlib[ses]"
            ) from e

        trace_enabled = log.isEnabledFor(TRACE_LEVEL)
        if trace_enabled:
            log.log(TRACE_LEVEL, "[SES] Sending email via AWS SES (region=%s)", self._region)
            log.log(TRACE_LEVEL, "[SES] From: %s, To: %s", message.get("From"), message.get("To"))

        raw_message = self._build_raw_message(message)
        client = self._create_client(boto3, BotoConfig)

        loop = asyncio.get_running_loop()

        try:
            response: dict[str, Any] = await loop.run_in_executor(
                None,
                lambda: client.send_raw_email(RawMessage={"Data": raw_message}),
            )

            message_id = response.get("MessageId", "")
            self._last_response = SesResponse(message_id=message_id)
            log.debug("Email sent via SES: %s", message_id)
            if trace_enabled:
                log.log(TRACE_LEVEL, "[SES] Message sent successfully, MessageId=%s", message_id)

        except ClientError as e:
            error_msg = e.response.get("Error", {}).get("Message", str(e))
            if trace_enabled:
                log.log(TRACE_LEVEL, "[SES] ClientError: %s", error_msg)
            raise MailTransportError(f"SES API error: {error_msg}") from e
        except NoCredentialsError as e:
            if trace_enabled:
                log.log(TRACE_LEVEL, "[SES] NoCredentialsError: %s", e)
            raise MailConfigurationError(f"AWS credentials not found: {e}") from e
        except EndpointConnectionError as e:
            if trace_enabled:
                log.log(TRACE_LEVEL, "[SES] EndpointConnectionError: %s", e)
            raise MailTransportError(f"SES endpoint connection failed: {e}") from e

    def _build_raw_message(self, message: EmailMessage) -> bytes:
        """Convert an EmailMessage to raw MIME bytes for SES.

        Args:
            message: The email message.

        Returns:
            Raw MIME bytes suitable for ``send_raw_email``.
        """
        return message.as_bytes()

    def _create_client(self, boto3_module: Any, boto_config_cls: Any) -> Any:
        """Create a boto3 SES client with stored configuration.

        Args:
            boto3_module: The imported boto3 module.
            boto_config_cls: The botocore Config class.

        Returns:
            A boto3 SES client instance.
        """
        kwargs: dict[str, Any] = {
            "service_name": "ses",
            "region_name": self._region,
            "config": boto_config_cls(
                connect_timeout=self._timeout,
                read_timeout=self._timeout,
            ),
        }

        if self._aws_access_key_id is not None:
            kwargs["aws_access_key_id"] = self._aws_access_key_id
            kwargs["aws_secret_access_key"] = self._aws_secret_access_key

        return boto3_module.client(**kwargs)
