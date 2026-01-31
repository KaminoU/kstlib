"""Fluent mail builder with transport-agnostic delivery."""

from __future__ import annotations

# pylint: disable=too-many-instance-attributes
import contextlib
import copy
import functools
import html
import inspect
import mimetypes
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import TYPE_CHECKING, Any, Literal, ParamSpec, TypeVar, overload

from kstlib.limits import MailLimits, get_mail_limits
from kstlib.mail.exceptions import MailConfigurationError, MailTransportError, MailValidationError
from kstlib.mail.filesystem import MailFilesystemGuards
from kstlib.utils import (
    EmailAddress,
    ValidationError,
    format_bytes,
    normalize_address_list,
    parse_email_address,
    replace_placeholders,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping
    from pathlib import Path

    from kstlib.mail.transport import MailTransport

P = ParamSpec("P")
R = TypeVar("R")


_DEFAULT_ENCODING = "utf-8"


@dataclass(frozen=True, slots=True)
class _InlineResource:
    cid: str
    path: Path


@dataclass(slots=True)
class NotifyResult:
    """Result of a notified function execution.

    Attributes:
        function_name: Name of the decorated function.
        success: Whether the function completed without exception.
        started_at: UTC timestamp when execution started.
        ended_at: UTC timestamp when execution ended.
        duration_ms: Execution duration in milliseconds.
        return_value: Function return value (if success and include_return=True).
        exception: Exception raised (if failure).
        traceback_str: Formatted traceback string (if failure and include_traceback=True).
    """

    function_name: str
    success: bool
    started_at: datetime
    ended_at: datetime
    duration_ms: float
    return_value: Any = None
    exception: BaseException | None = None
    traceback_str: str | None = None


class MailBuilder:
    """Compose and send emails using a fluent interface.

    Supports plain text and HTML bodies, file attachments, inline images,
    and template-based content with placeholder substitution.

    Example:
        Build an email without sending (useful for inspection)::

            >>> from kstlib.mail import MailBuilder
            >>> mail = (
            ...     MailBuilder()
            ...     .sender("noreply@example.com")
            ...     .to("user@example.com")
            ...     .subject("Welcome!")
            ...     .message("<h1>Hello</h1>", content_type="html")
            ... )
            >>> msg = mail.build()
            >>> msg["Subject"]
            'Welcome!'

        With a configured transport for actual delivery::

            >>> from kstlib.mail import MailBuilder
            >>> from kstlib.mail.transports import SMTPTransport
            >>> transport = SMTPTransport(host="smtp.example.com", port=587)
            >>> mail = MailBuilder(transport=transport)
            >>> # mail.sender(...).to(...).subject(...).message(...).send()
    """

    def __init__(
        self,
        *,
        transport: MailTransport | None = None,
        encoding: str = _DEFAULT_ENCODING,
        filesystem: MailFilesystemGuards | None = None,
        limits: MailLimits | None = None,
    ) -> None:
        """Initialise the builder with optional transport, charset, and guardrails."""
        self._transport = transport
        self._encoding = encoding
        self._filesystem = filesystem or MailFilesystemGuards.default()
        self._limits = limits or get_mail_limits()
        self._sender: EmailAddress | None = None
        self._reply_to: EmailAddress | None = None
        self._to: list[EmailAddress] = []
        self._cc: list[EmailAddress] = []
        self._bcc: list[EmailAddress] = []
        self._subject: str = ""
        self._plain_body: str | None = None
        self._html_body: str | None = None
        self._attachments: list[Path] = []
        self._inline: list[_InlineResource] = []

    # ------------------------------------------------------------------
    # Addressing
    # ------------------------------------------------------------------

    def transport(self, transport: MailTransport) -> MailBuilder:
        """Attach a transport backend to this builder."""
        self._transport = transport
        return self

    def sender(self, value: str) -> MailBuilder:
        """Set the sender address."""
        self._sender = self._parse_address(value)
        return self

    def reply_to(self, value: str | None) -> MailBuilder:
        """Set an optional reply-to address."""
        self._reply_to = self._parse_address(value) if value else None
        return self

    def to(self, *values: str) -> MailBuilder:
        """Append recipients to the ``To`` header."""
        self._to.extend(self._parse_addresses(values))
        return self

    def cc(self, *values: str) -> MailBuilder:
        """Append recipients to the ``Cc`` header."""
        self._cc.extend(self._parse_addresses(values))
        return self

    def bcc(self, *values: str) -> MailBuilder:
        """Append recipients to the ``Bcc`` header."""
        self._bcc.extend(self._parse_addresses(values))
        return self

    # ------------------------------------------------------------------
    # Content
    # ------------------------------------------------------------------

    def subject(self, value: str) -> MailBuilder:
        """Set the message subject."""
        self._subject = value
        return self

    def message(
        self,
        content: str | None = None,
        *,
        content_type: Literal["plain", "html"] = "html",
        template: str | Path | None = None,
        placeholders: Mapping[str, Any] | None = None,
        **extra_placeholders: Any,
    ) -> MailBuilder:
        """Populate the message body either via raw content or a template.

        Raises:
            MailValidationError: If content_type is unsupported.
        """
        body = self._resolve_body(content, template, placeholders, extra_placeholders)

        if content_type == "html":
            self._html_body = body
        elif content_type == "plain":
            self._plain_body = body
        else:  # pragma: no cover - defensive guard
            raise MailValidationError(f"Unsupported content type: {content_type}")
        return self

    def attach(self, *paths: str | Path) -> MailBuilder:
        """Attach binary files to the message.

        Args:
            *paths: One or more file paths to attach.

        Returns:
            Self for method chaining.

        Raises:
            MailValidationError: If no paths provided, attachment limit exceeded,
                or file size exceeds configured limits.
        """
        if not paths:
            raise MailValidationError("attach() expects at least one file path")
        for raw in paths:
            path = self._filesystem.resolve_attachment(raw)
            # Validate attachment count
            if len(self._attachments) >= self._limits.max_attachments:
                raise MailValidationError(f"Maximum of {self._limits.max_attachments} attachments exceeded")
            # Validate file size
            file_size = path.stat().st_size
            if file_size > self._limits.max_attachment_size:
                raise MailValidationError(
                    f"Attachment '{path.name}' exceeds size limit "
                    f"({format_bytes(file_size)} > {self._limits.max_attachment_size_display})"
                )
            self._attachments.append(path)
        return self

    def attach_inline(self, cid: str, path: str | Path) -> MailBuilder:
        """Attach an inline resource (e.g. image referenced with ``cid:``).

        Raises:
            MailValidationError: If cid is empty or file size exceeds limits.
        """
        if not cid:
            raise MailValidationError("Inline resources require a non-empty content ID")
        resource_path = self._filesystem.resolve_inline(path)
        # Validate file size for inline resources
        file_size = resource_path.stat().st_size
        if file_size > self._limits.max_attachment_size:
            raise MailValidationError(
                f"Inline resource '{resource_path.name}' exceeds size limit "
                f"({format_bytes(file_size)} > {self._limits.max_attachment_size_display})"
            )
        self._inline.append(_InlineResource(cid=cid, path=resource_path))
        return self

    # ------------------------------------------------------------------
    # Build & send
    # ------------------------------------------------------------------

    def build(self) -> EmailMessage:
        """Assemble and return an :class:`EmailMessage` without sending it.

        Raises:
            MailValidationError: If sender, recipient, or body is missing.
        """
        sender = self._validate_ready()
        message = self._initialise_message(sender)
        self._apply_inline_resources(message)
        self._apply_file_attachments(message)
        return message

    def send(self) -> EmailMessage:
        """Build and send the email using the configured transport.

        Returns:
            The constructed EmailMessage after successful delivery.

        Raises:
            MailConfigurationError: If no transport has been configured.
            MailTransportError: If the transport fails to deliver the message.
        """
        if self._transport is None:
            raise MailConfigurationError("No mail transport configured")

        message = self.build()
        try:
            self._transport.send(message)
        except MailTransportError:
            raise
        except Exception as exc:  # pragma: no cover - defensive guard
            raise MailTransportError("Unexpected error during delivery") from exc
        return message

    # ------------------------------------------------------------------
    # Notification decorator
    # ------------------------------------------------------------------

    def _snapshot(self) -> MailBuilder:
        """Create an independent copy of this builder for decoration.

        Returns a copy that shares the transport but has independent
        message state, so decorated functions don't interfere with each other.
        """
        # Save transport before deepcopy (transports should not be copied)
        transport = self._transport
        self._transport = None
        try:
            snapshot = copy.deepcopy(self)
        finally:
            self._transport = transport
        snapshot._transport = transport  # noqa: SLF001
        return snapshot

    @overload
    def notify(
        self,
        func: Callable[P, R],
        /,
    ) -> Callable[P, R]: ...

    @overload
    def notify(
        self,
        func: None = None,
        /,
        *,
        subject: str | None = None,
        on_error_only: bool = False,
        include_return: bool = False,
        include_traceback: bool = True,
    ) -> Callable[[Callable[P, R]], Callable[P, R]]: ...

    def notify(
        self,
        func: Callable[P, R] | None = None,
        /,
        *,
        subject: str | None = None,
        on_error_only: bool = False,
        include_return: bool = False,
        include_traceback: bool = True,
    ) -> Callable[P, R] | Callable[[Callable[P, R]], Callable[P, R]]:
        """Decorator to send email notifications on function execution.

        Sends a notification email after the decorated function completes,
        reporting success or failure with execution metrics.

        Can be used with or without parentheses::

            @mail.notify
            def task(): ...

            @mail.notify(subject="Step 1", on_error_only=True)
            def task(): ...

        Args:
            func: The function to decorate (when used without parentheses).
            subject: Override the builder's subject for this notification.
            on_error_only: Only send notification if the function raises.
            include_return: Include return value in success notifications.
            include_traceback: Include traceback in failure notifications.

        Returns:
            Decorated function that sends notifications.

        Example:
            >>> from kstlib.mail import MailBuilder
            >>> mail = MailBuilder().sender("bot@x.com").to("admin@x.com")
            >>> _ = mail.subject("Daily ETL")
            >>> @mail.notify(on_error_only=True)
            ... def extract():
            ...     return {"rows": 100}
        """

        def decorator(fn: Callable[P, R]) -> Callable[P, R]:
            builder = self._snapshot()
            effective_subject = subject if subject is not None else builder._subject  # noqa: SLF001

            if inspect.iscoroutinefunction(fn):

                @functools.wraps(fn)
                async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                    start = time.perf_counter()
                    started_at = datetime.now(timezone.utc)
                    try:
                        result = await fn(*args, **kwargs)
                        ended_at = datetime.now(timezone.utc)
                        duration_ms = (time.perf_counter() - start) * 1000

                        if not on_error_only:
                            notify_result = NotifyResult(
                                function_name=fn.__name__,
                                success=True,
                                started_at=started_at,
                                ended_at=ended_at,
                                duration_ms=duration_ms,
                                return_value=result if include_return else None,
                            )
                            builder._send_notification(  # noqa: SLF001
                                notify_result, effective_subject, include_return
                            )
                        return result  # type: ignore[no-any-return]
                    except BaseException as exc:
                        ended_at = datetime.now(timezone.utc)
                        duration_ms = (time.perf_counter() - start) * 1000
                        tb_str = traceback.format_exc() if include_traceback else None

                        notify_result = NotifyResult(
                            function_name=fn.__name__,
                            success=False,
                            started_at=started_at,
                            ended_at=ended_at,
                            duration_ms=duration_ms,
                            exception=exc,
                            traceback_str=tb_str,
                        )
                        builder._send_notification(  # noqa: SLF001
                            notify_result, effective_subject, include_return
                        )
                        raise

                return async_wrapper  # type: ignore[return-value]

            @functools.wraps(fn)
            def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                start = time.perf_counter()
                started_at = datetime.now(timezone.utc)
                try:
                    result = fn(*args, **kwargs)
                    ended_at = datetime.now(timezone.utc)
                    duration_ms = (time.perf_counter() - start) * 1000

                    if not on_error_only:
                        notify_result = NotifyResult(
                            function_name=fn.__name__,
                            success=True,
                            started_at=started_at,
                            ended_at=ended_at,
                            duration_ms=duration_ms,
                            return_value=result if include_return else None,
                        )
                        builder._send_notification(  # noqa: SLF001
                            notify_result, effective_subject, include_return
                        )
                    return result
                except BaseException as exc:
                    ended_at = datetime.now(timezone.utc)
                    duration_ms = (time.perf_counter() - start) * 1000
                    tb_str = traceback.format_exc() if include_traceback else None

                    notify_result = NotifyResult(
                        function_name=fn.__name__,
                        success=False,
                        started_at=started_at,
                        ended_at=ended_at,
                        duration_ms=duration_ms,
                        exception=exc,
                        traceback_str=tb_str,
                    )
                    builder._send_notification(  # noqa: SLF001
                        notify_result, effective_subject, include_return
                    )
                    raise

            return sync_wrapper

        if func is not None:
            return decorator(func)
        return decorator

    def _send_notification(
        self,
        result: NotifyResult,
        subject: str,
        include_return: bool,
    ) -> None:
        """Send the notification email based on execution result."""
        if result.success:
            body = self._format_success_body(result, include_return)
            full_subject = f"[OK] {subject} - {result.function_name}"
        else:
            body = self._format_failure_body(result)
            full_subject = f"[FAILED] {subject} - {result.function_name}"

        # Create fresh message with notification content
        self._subject = full_subject
        self._html_body = body
        self._plain_body = None
        self._attachments = []
        self._inline = []

        # Don't let notification failure crash the decorated function
        with contextlib.suppress(MailTransportError):
            self.send()

    def _format_success_body(self, result: NotifyResult, include_return: bool) -> str:
        """Format HTML body for successful execution notification."""
        parts = [
            "<h2>Function completed successfully</h2>",
            f"<p><strong>Function:</strong> <code>{html.escape(result.function_name)}</code></p>",
            f"<p><strong>Started:</strong> {result.started_at.isoformat()}</p>",
            f"<p><strong>Ended:</strong> {result.ended_at.isoformat()}</p>",
            f"<p><strong>Duration:</strong> {result.duration_ms:.2f} ms</p>",
        ]

        if include_return and result.return_value is not None:
            escaped_value = html.escape(repr(result.return_value))
            parts.append(f"<p><strong>Return value:</strong></p><pre>{escaped_value}</pre>")

        return "\n".join(parts)

    def _format_failure_body(self, result: NotifyResult) -> str:
        """Format HTML body for failed execution notification."""
        exc_type = type(result.exception).__name__ if result.exception else "Unknown"
        exc_msg = str(result.exception) if result.exception else "No message"

        parts = [
            "<h2>Function execution failed</h2>",
            f"<p><strong>Function:</strong> <code>{html.escape(result.function_name)}</code></p>",
            f"<p><strong>Started:</strong> {result.started_at.isoformat()}</p>",
            f"<p><strong>Ended:</strong> {result.ended_at.isoformat()}</p>",
            f"<p><strong>Duration:</strong> {result.duration_ms:.2f} ms</p>",
            f"<p><strong>Exception:</strong> {html.escape(exc_type)}: {html.escape(exc_msg)}</p>",
        ]

        if result.traceback_str:
            escaped_tb = html.escape(result.traceback_str)
            parts.append(f"<h3>Traceback</h3><pre>{escaped_tb}</pre>")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_address(self, value: str) -> EmailAddress:
        try:
            return parse_email_address(value)
        except ValidationError as exc:
            raise MailValidationError(str(exc)) from exc

    def _parse_addresses(self, values: Iterable[str]) -> list[EmailAddress]:
        try:
            return normalize_address_list(values)
        except ValidationError as exc:
            raise MailValidationError(str(exc)) from exc

    def _resolve_body(
        self,
        content: str | None,
        template: str | Path | None,
        placeholders: Mapping[str, Any] | None,
        extra_placeholders: Mapping[str, Any],
    ) -> str:
        if template is not None:
            template_path = self._filesystem.resolve_template(template)
            content = template_path.read_text(encoding=self._encoding)

        if content is None:
            raise MailValidationError("Message content cannot be empty")

        merged: dict[str, Any] = {}
        if placeholders:
            merged.update(dict(placeholders))
        if extra_placeholders:
            merged.update(extra_placeholders)
        if merged:
            content = replace_placeholders(content, merged)
        return content

    def _validate_ready(self) -> EmailAddress:
        if self._sender is None:
            raise MailValidationError("Sender must be provided")
        if not (self._to or self._cc or self._bcc):
            raise MailValidationError("At least one recipient must be specified")
        if self._plain_body is None and self._html_body is None:
            raise MailValidationError("Message body is empty")
        return self._sender

    def _initialise_message(self, sender: EmailAddress) -> EmailMessage:
        message = EmailMessage()
        message["From"] = sender.formatted
        if self._reply_to:
            message["Reply-To"] = self._reply_to.formatted
        if self._to:
            message["To"] = ", ".join(addr.formatted for addr in self._to)
        if self._cc:
            message["Cc"] = ", ".join(addr.formatted for addr in self._cc)
        if self._bcc:
            message["Bcc"] = ", ".join(addr.formatted for addr in self._bcc)
        if self._subject:
            message["Subject"] = self._subject

        plain = self._plain_body if self._plain_body is not None else ""
        message.set_content(plain, subtype="plain", charset=self._encoding)
        if self._html_body is not None:
            message.add_alternative(self._html_body, subtype="html", charset=self._encoding)
        return message

    def _apply_inline_resources(self, message: EmailMessage) -> None:
        if not self._inline:
            return
        html_part = message.get_body("html")
        if html_part is None:
            raise MailValidationError("Inline resources require an HTML body")
        for resource in self._inline:
            data = resource.path.read_bytes()
            maintype, subtype = _detect_mime(resource.path)
            html_part.add_related(
                data,
                maintype=maintype,
                subtype=subtype,
                cid=f"<{resource.cid}>",
                filename=resource.path.name,
            )

    def _apply_file_attachments(self, message: EmailMessage) -> None:
        for attachment in self._attachments:
            data = attachment.read_bytes()
            maintype, subtype = _detect_mime(attachment)
            message.add_attachment(
                data,
                maintype=maintype,
                subtype=subtype,
                filename=attachment.name,
            )


def _detect_mime(path: Path) -> tuple[str, str]:
    guessed, _ = mimetypes.guess_type(path.name)
    if not guessed:
        return "application", "octet-stream"
    maintype, subtype = guessed.split("/", 1)
    return maintype, subtype


__all__ = ["MailBuilder", "NotifyResult"]
