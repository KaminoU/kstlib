"""Transport interfaces for mail delivery.

Provides both sync and async transport abstractions for sending emails.
Sync transports can be wrapped for async usage via :class:`AsyncTransportWrapper`.

Examples:
    Using a sync transport directly::

        from kstlib.mail.transports import SMTPTransport

        transport = SMTPTransport(host="smtp.example.com", port=587)
        transport.send(message)

    Wrapping a sync transport for async usage::

        from kstlib.mail.transport import AsyncTransportWrapper
        from kstlib.mail.transports import SMTPTransport

        smtp = SMTPTransport(host="smtp.example.com", port=587)
        async_transport = AsyncTransportWrapper(smtp)
        await async_transport.send(message)
"""

from __future__ import annotations

import asyncio
import logging  # noqa: TC003 - used for type hint in function signature
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from kstlib.mail.exceptions import MailTransportError

if TYPE_CHECKING:
    from concurrent.futures import ThreadPoolExecutor
    from email.message import EmailMessage

    import httpx


class MailTransport(ABC):
    """Abstract sync transport for delivering emails.

    Subclass this for synchronous transport implementations like SMTP.

    Examples:
        Implementing a custom sync transport::

            class MyTransport(MailTransport):
                def send(self, message: EmailMessage) -> None:
                    # Send the message
                    pass
    """

    @abstractmethod
    def send(self, message: EmailMessage) -> None:
        """Deliver the message to the underlying service.

        Args:
            message: The email message to send.

        Raises:
            MailTransportError: If delivery fails.
        """


class AsyncMailTransport(ABC):
    """Abstract async transport for delivering emails.

    Subclass this for asynchronous transport implementations like HTTP APIs.

    Examples:
        Implementing a custom async transport::

            class MyAsyncTransport(AsyncMailTransport):
                async def send(self, message: EmailMessage) -> None:
                    async with httpx.AsyncClient() as client:
                        await client.post(...)
    """

    @abstractmethod
    async def send(self, message: EmailMessage) -> None:
        """Deliver the message asynchronously.

        Args:
            message: The email message to send.

        Raises:
            MailTransportError: If delivery fails.
        """


class AsyncTransportWrapper(AsyncMailTransport):
    """Wrap a sync transport for async usage.

    Executes the sync transport's send method in a thread pool executor
    to avoid blocking the event loop.

    Args:
        transport: The sync transport to wrap.
        executor: Optional thread pool executor. If None, uses the default.

    Examples:
        Wrapping an SMTP transport::

            from kstlib.mail.transport import AsyncTransportWrapper
            from kstlib.mail.transports import SMTPTransport

            smtp = SMTPTransport(host="smtp.example.com", port=587)
            async_smtp = AsyncTransportWrapper(smtp)

            # Now usable in async context
            await async_smtp.send(message)

        With custom executor::

            from concurrent.futures import ThreadPoolExecutor

            executor = ThreadPoolExecutor(max_workers=2)
            async_smtp = AsyncTransportWrapper(smtp, executor=executor)
    """

    def __init__(
        self,
        transport: MailTransport,
        *,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        """Initialize the async wrapper.

        Args:
            transport: The sync transport to wrap.
            executor: Optional custom thread pool executor.
        """
        self._transport = transport
        self._executor = executor

    @property
    def transport(self) -> MailTransport:
        """Return the wrapped sync transport."""
        return self._transport

    async def send(self, message: EmailMessage) -> None:
        """Send message asynchronously via the wrapped transport.

        Runs the sync transport's send method in a thread pool to avoid
        blocking the async event loop.

        Args:
            message: The email message to send.

        Raises:
            MailTransportError: If the underlying transport fails.
        """
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            self._executor,
            self._transport.send,
            message,
        )


def handle_http_error_response(
    response: httpx.Response,
    service_name: str,
    logger: logging.Logger,
    *,
    extract_code: bool = False,
) -> None:
    """Parse HTTP error response and raise MailTransportError.

    Shared utility for HTTP-based mail transports (Gmail API, Resend, etc.).
    Extracts error details from JSON response body when available.

    Args:
        response: The HTTP error response from the API.
        service_name: Name of the service for error messages (e.g., "Gmail", "Resend").
        logger: Logger instance for warning messages.
        extract_code: If True, extract error code from response body (Gmail style).
            If False, use HTTP status code only (Resend style).

    Raises:
        MailTransportError: Always raises with extracted error details.

    Examples:
        >>> import httpx  # doctest: +SKIP
        >>> response = httpx.Response(400, json={"error": "Bad request"})  # doctest: +SKIP
        >>> handle_http_error_response(response, "MyAPI", logger)  # doctest: +SKIP
        Traceback (most recent call last):
            ...
        MailTransportError: MyAPI error: Bad request
    """
    error_msg: str
    error_code: int | str = response.status_code

    try:
        data: dict[str, Any] = response.json()

        if extract_code:
            # Gmail-style: nested error object with code and message
            error = data.get("error", {})
            if isinstance(error, dict):
                error_msg = error.get("message", str(error))
                error_code = error.get("code", response.status_code)
            else:
                error_msg = str(error)
        else:
            # Resend-style: flat structure with message or error key
            error_msg = data.get("message", data.get("error", "Unknown error"))
    except Exception:
        error_msg = response.text or f"HTTP {response.status_code}"

    logger.warning("%s API error: %s (code=%s)", service_name, error_msg, error_code)

    if extract_code:
        raise MailTransportError(f"{service_name} API error ({error_code}): {error_msg}")
    raise MailTransportError(f"{service_name} API error: {error_msg}")


__all__ = [
    "AsyncMailTransport",
    "AsyncTransportWrapper",
    "MailTransport",
    "handle_http_error_response",
]
