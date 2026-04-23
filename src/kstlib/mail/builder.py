"""Fluent mail builder with transport-agnostic delivery."""

from __future__ import annotations

# pylint: disable=too-many-instance-attributes
import contextlib
import copy
import functools
import html
import inspect
import mimetypes
import ssl
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import TYPE_CHECKING, Any, Literal, ParamSpec, TypeVar, overload

from kstlib.limits import MailLimits, get_mail_limits
from kstlib.logging import get_logger
from kstlib.mail.exceptions import MailConfigurationError, MailTransportError, MailValidationError
from kstlib.mail.filesystem import MailFilesystemGuards
from kstlib.ssl import get_ssl_config, validate_ca_bundle_path
from kstlib.utils import (
    EmailAddress,
    ValidationError,
    format_bytes,
    normalize_address_list,
    parse_email_address,
    replace_placeholders,
)

log = get_logger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping
    from pathlib import Path

    from kstlib.mail.transport import AsyncMailTransport, MailTransport
    from kstlib.mail.transports.resend import ResendTransport
    from kstlib.mail.transports.smtp import SMTPTransport

    TransportLike = MailTransport | AsyncMailTransport

P = ParamSpec("P")
R = TypeVar("R")


_DEFAULT_ENCODING = "utf-8"

# Envelope fields that may appear under ``mail.presets.<name>.defaults``.
# Any other key is logged once as a WARNING and ignored (forward-compat).
_KNOWN_PRESET_ENVELOPE_DEFAULTS: frozenset[str] = frozenset({"sender", "reply_to"})


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

    Transport resolution cascade, highest priority first:

    1. ``transport=`` kwarg (explicit instance, backward compatible)
    2. ``preset=`` kwarg (named preset under ``mail.presets`` in config)
    3. ``mail.default`` in ``kstlib.conf.yml`` (auto-resolved preset name)
    4. ``None``: no transport. ``.build()`` still works. ``.send()`` raises
       ``MailConfigurationError``.

    Preset envelope defaults:
        A preset may declare a ``defaults`` subsection with ``sender`` and
        ``reply_to`` keys. These are applied automatically when the builder
        is initialised with ``preset=`` or when the config's ``mail.default``
        resolves to such a preset. User-provided values via ``.sender()`` or
        ``.reply_to()`` always override the preset defaults (user wins).

        Deliberately scoped to ``sender`` and ``reply_to`` only:
        ``to``/``cc``/``bcc`` are excluded on purpose to prevent silent
        accidental sends to the preset's audience. Unsupported keys inside
        ``defaults`` are logged once as a WARNING and ignored (forward
        compatibility).

        Example YAML::

            mail:
              presets:
                corporate:
                  transport: smtp
                  host: smtp-secure.corp.local
                  defaults:
                    sender: "Service Notifications <notify@corp.local>"
                    reply_to: "Service Notifications <notify@corp.local>"

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

        With a configured transport for actual delivery (explicit)::

            >>> from kstlib.mail import MailBuilder
            >>> from kstlib.mail.transports import SMTPTransport
            >>> transport = SMTPTransport(host="smtp.example.com", port=587)
            >>> mail = MailBuilder(transport=transport)
            >>> # mail.sender(...).to(...).subject(...).message(...).send()

        Config-driven via a named preset (defaults.sender is pre-filled)::

            >>> mail = MailBuilder(preset="corporate")  # doctest: +SKIP
            >>> # mail.to(...).subject(...).message(...).send()

        Config-driven via ``mail.default`` preset::

            >>> mail = MailBuilder()  # doctest: +SKIP
            >>> # Uses preset referenced by mail.default in kstlib.conf.yml

    """

    def __init__(
        self,
        *,
        transport: MailTransport | None = None,
        preset: str | None = None,
        encoding: str = _DEFAULT_ENCODING,
        filesystem: MailFilesystemGuards | None = None,
        limits: MailLimits | None = None,
    ) -> None:
        """Initialise the builder with optional transport, preset, charset, and guardrails.

        Args:
            transport: Explicit transport instance. Takes priority over ``preset``
                and the config default. Backward compatible: passing this is
                equivalent to the pre-preset API. When set, preset envelope
                defaults are **not** applied.
            preset: Name of a preset declared under ``mail.presets`` in
                ``kstlib.conf.yml``. Resolved immediately. Raises
                ``MailConfigurationError`` if the preset does not exist.
                Any ``defaults.sender`` / ``defaults.reply_to`` declared on
                the preset are applied right after transport resolution.
            encoding: Character encoding for message bodies (default: utf-8).
            filesystem: Filesystem guardrails for attachments, inline
                resources, and templates.
            limits: Message and attachment limits.

        Raises:
            MailConfigurationError: If ``preset`` is passed but does not
                resolve to a valid preset in configuration, or if a preset
                default has a non-string value.
            MailValidationError: If a preset default holds an unparseable
                email address.

        """
        resolved_preset_name: str | None
        if transport is not None:
            self._transport: TransportLike | None = transport
            resolved_preset_name = None
        elif preset is not None:
            self._transport = _build_transport_from_preset(preset)
            resolved_preset_name = preset
        else:
            self._transport = _resolve_default_transport()
            resolved_preset_name = _resolve_default_preset_name() if self._transport is not None else None
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

        if resolved_preset_name is not None:
            envelope_defaults = _load_preset_envelope_defaults(resolved_preset_name)
            if envelope_defaults:
                self._apply_preset_envelope_defaults(envelope_defaults)

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

        .. warning::
            HTML content is **not** sanitized. The caller is responsible for
            ensuring the HTML is safe. This is by design: mail templates are
            authored by the application developer, not by end users.

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
        from kstlib.mail.transport import AsyncMailTransport, MailTransport

        if self._transport is None:
            raise MailConfigurationError("No mail transport configured")
        if isinstance(self._transport, AsyncMailTransport):
            raise MailConfigurationError(
                f"Transport '{type(self._transport).__name__}' is async-only; "
                "use it directly via `await transport.send(message)` instead of "
                "MailBuilder.send()."
            )
        assert isinstance(self._transport, MailTransport)
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
        snapshot._transport = transport
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
        """Send email notifications on function execution.

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
            effective_subject = subject if subject is not None else builder._subject

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
                            builder._send_notification(notify_result, effective_subject, include_return)
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
                        builder._send_notification(notify_result, effective_subject, include_return)
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
                        builder._send_notification(notify_result, effective_subject, include_return)
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
                    builder._send_notification(notify_result, effective_subject, include_return)
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

    def _apply_preset_envelope_defaults(self, defaults: Mapping[str, Any]) -> None:
        """Seed ``_sender`` / ``_reply_to`` from a preset's ``defaults`` section.

        User-provided values via :meth:`sender` or :meth:`reply_to` overwrite
        these seeds by the natural assignment pattern - no extra bookkeeping
        required.

        Args:
            defaults: Envelope defaults dict, already filtered to the
                supported keys by :func:`_load_preset_envelope_defaults`.

        Raises:
            MailConfigurationError: If a supported key is present with a
                non-string value.
            MailValidationError: If a supported key holds an unparseable
                email address (propagated from :meth:`_parse_address`).

        """
        sender = defaults.get("sender")
        if sender is not None:
            if not isinstance(sender, str):
                msg = f"preset defaults.sender must be a string, got {type(sender).__name__}: {sender!r}"
                raise MailConfigurationError(msg)
            self._sender = self._parse_address(sender)

        reply_to = defaults.get("reply_to")
        if reply_to is not None:
            if not isinstance(reply_to, str):
                msg = f"preset defaults.reply_to must be a string, got {type(reply_to).__name__}: {reply_to!r}"
                raise MailConfigurationError(msg)
            self._reply_to = self._parse_address(reply_to)

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


# ----------------------------------------------------------------------
# Config-driven transport resolution
# ----------------------------------------------------------------------


_SUPPORTED_TRANSPORTS = ("smtp", "resend")


def _load_mail_config() -> Any:
    """Read ``mail`` section from kstlib configuration.

    Returns:
        The ``mail`` section as a Box/dict, or ``None`` if unavailable.

    Raises:
        MailConfigurationError: If the config loader cannot be imported or
            raises while reading.

    """
    try:
        from kstlib.config import get_config
    except ImportError as exc:  # pragma: no cover - config is always present
        raise MailConfigurationError("kstlib.config is not available") from exc

    try:
        cfg: Any = get_config()
    except Exception as exc:
        raise MailConfigurationError(f"Failed to load kstlib configuration: {exc}") from exc

    if not hasattr(cfg, "get"):
        return None
    return cfg.get("mail")


def _resolve_default_transport() -> TransportLike | None:
    """Resolve the transport from ``mail.default`` in configuration.

    Returns ``None`` when no default is configured or when the config is
    unavailable. The returned ``None`` preserves the legacy behaviour:
    ``.build()`` keeps working and ``.send()`` raises at call time.

    Raises:
        MailConfigurationError: If ``mail.default`` points to an unknown
            preset. This is a user-visible misconfiguration, so fail fast.

    """
    try:
        mail_cfg = _load_mail_config()
    except MailConfigurationError:
        return None

    if mail_cfg is None or not hasattr(mail_cfg, "get"):
        return None

    default_name = mail_cfg.get("default")
    if not default_name:
        return None
    return _build_transport_from_preset(str(default_name))


def _resolve_default_preset_name() -> str | None:
    """Return the preset name referenced by ``mail.default``, or ``None``.

    Swallows any config loading error and returns ``None`` so that
    ``MailBuilder()`` stays usable even when the config file is missing.
    Mirrors the silent-empty contract of :func:`_load_mail_config`.
    """
    try:
        mail_cfg = _load_mail_config()
    except MailConfigurationError:
        return None
    if mail_cfg is None or not hasattr(mail_cfg, "get"):
        return None
    default_name = mail_cfg.get("default")
    if not default_name:
        return None
    return str(default_name)


def _load_preset_envelope_defaults(preset_name: str) -> dict[str, Any]:
    """Read the ``defaults`` subsection of a named mail preset.

    Returns an empty dict silently when the config is unavailable, the
    preset does not exist, the preset has no ``defaults`` section, or the
    section is empty / of the wrong shape. Only keys in
    :data:`_KNOWN_PRESET_ENVELOPE_DEFAULTS` are returned; any other key is
    logged once as a WARNING (batched, one log per call) and ignored. This
    keeps old YAML files working when kstlib later adds new supported keys.

    Args:
        preset_name: Name of the preset declared under ``mail.presets``.

    Returns:
        Dict containing only the supported keys present in the preset
        defaults. Empty dict if nothing is configured.

    Examples:
        >>> _load_preset_envelope_defaults("corporate")  # doctest: +SKIP
        {'sender': 'Service Notifications <notify@corp.local>'}

    """
    try:
        mail_cfg = _load_mail_config()
    except MailConfigurationError:
        return {}
    if mail_cfg is None or not hasattr(mail_cfg, "get"):
        return {}
    presets = mail_cfg.get("presets")
    if presets is None or not hasattr(presets, "get"):
        return {}
    preset_cfg = presets.get(preset_name)
    if preset_cfg is None or not hasattr(preset_cfg, "get"):
        return {}
    raw_defaults = preset_cfg.get("defaults")
    if raw_defaults is None or not hasattr(raw_defaults, "items"):
        return {}

    known: dict[str, Any] = {}
    unknown: list[str] = []
    for key, value in raw_defaults.items():
        key_str = str(key)
        if key_str in _KNOWN_PRESET_ENVELOPE_DEFAULTS:
            known[key_str] = value
        else:
            unknown.append(key_str)

    if unknown:
        log.warning(
            "mail preset %r has unsupported defaults keys: %s. Supported keys are: %s. Unsupported keys are ignored.",
            preset_name,
            sorted(unknown),
            sorted(_KNOWN_PRESET_ENVELOPE_DEFAULTS),
        )

    return known


def _build_transport_from_preset(preset_name: str) -> TransportLike:
    """Build a transport from a named preset in the configuration.

    Args:
        preset_name: Name of the preset defined under ``mail.presets``.

    Returns:
        Configured ``MailTransport`` instance ready to use.

    Raises:
        MailConfigurationError: If the preset is not found, the transport
            field is missing or unsupported, or required fields are absent.

    """
    mail_cfg = _load_mail_config()
    if mail_cfg is None:
        raise MailConfigurationError(
            f"Preset '{preset_name}' cannot be resolved: 'mail' section missing from configuration"
        )

    presets = mail_cfg.get("presets") if hasattr(mail_cfg, "get") else None
    if not presets or preset_name not in presets:
        available = sorted(presets.keys()) if presets else []
        raise MailConfigurationError(f"Preset '{preset_name}' not found in mail.presets. Available: {available}")

    preset_cfg = presets[preset_name]
    transport_type = preset_cfg.get("transport") if hasattr(preset_cfg, "get") else None
    if not transport_type:
        raise MailConfigurationError(
            f"Preset '{preset_name}' is missing required field 'transport'. Supported: {list(_SUPPORTED_TRANSPORTS)}"
        )

    if transport_type == "smtp":
        return _build_smtp_transport(preset_cfg)
    if transport_type == "resend":
        return _build_resend_transport(preset_cfg)
    raise MailConfigurationError(
        f"Unknown transport type '{transport_type}' in preset '{preset_name}'. Supported: {list(_SUPPORTED_TRANSPORTS)}"
    )


def _load_mail_ssl_section() -> Any | None:
    """Return the ``mail.ssl`` section of the configuration, or ``None``.

    Isolates the defensive imports/lookups so :func:`_resolve_mail_ssl_config`
    stays readable. Returns ``None`` whenever the section is missing or the
    config loader cannot be reached.
    """
    try:
        mail_section = _load_mail_config()
    except MailConfigurationError:
        return None
    if mail_section is None or not hasattr(mail_section, "get"):
        return None
    ssl_section = mail_section.get("ssl")
    if ssl_section is None or not hasattr(ssl_section, "get"):
        return None
    return ssl_section


def _load_root_ssl_config() -> Any | None:
    """Return the root-level :class:`kstlib.ssl.SSLConfig`, or ``None``.

    Swallows any loading error (missing config, unreadable YAML) and yields
    ``None`` so the caller keeps cascading to the Python default.
    """
    try:
        return get_ssl_config()
    except Exception:  # pylint: disable=broad-exception-caught
        return None


def _cascade_mail_ssl_level(
    verify: Any,
    ca_bundle: Any,
    source: str | None,
) -> tuple[Any, Any, str | None]:
    """Apply the ``mail.ssl.*`` cascade level to a partial resolution."""
    if verify is not None and ca_bundle is not None:
        return verify, ca_bundle, source
    mail_ssl = _load_mail_ssl_section()
    if mail_ssl is None:
        return verify, ca_bundle, source
    if verify is None:
        candidate = mail_ssl.get("verify")
        if candidate is not None:
            verify = candidate
            source = "mail.ssl"
    if ca_bundle is None:
        ca_bundle = mail_ssl.get("ca_bundle")
    return verify, ca_bundle, source


def _cascade_root_ssl_level(
    verify: Any,
    ca_bundle: Any,
    source: str | None,
) -> tuple[Any, Any, str | None]:
    """Apply the root ``ssl.*`` cascade level to a partial resolution."""
    if verify is not None and ca_bundle is not None:
        return verify, ca_bundle, source
    root_ssl = _load_root_ssl_config()
    if root_ssl is None:
        return verify, ca_bundle, source
    if verify is None:
        verify = root_ssl.verify
        source = "ssl (root)"
    if ca_bundle is None:
        ca_bundle = root_ssl.ca_bundle
    return verify, ca_bundle, source


def _validate_mail_ssl_types(verify: Any, ca_bundle: Any) -> tuple[bool, str | None]:
    """Reject non-bool verify and non-str ca_bundle before SSLContext creation."""
    if not isinstance(verify, bool):
        msg = f"mail SSL verify must be bool, got {type(verify).__name__}: {verify!r}"
        raise TypeError(msg)
    if ca_bundle is not None and not isinstance(ca_bundle, str):
        msg = f"mail SSL ca_bundle must be str or null, got {type(ca_bundle).__name__}"
        raise TypeError(msg)
    return verify, ca_bundle


def _warn_if_mail_verify_disabled(verify: bool, source: str | None) -> None:
    """Emit a single source-tagged WARNING when verify resolved to ``False``."""
    if verify is False:
        log.warning(
            "[SECURITY] SSL certificate verification disabled for mail transport "
            "(source: %s). This exposes the SMTP session to MITM attacks. Use only "
            "in trusted environments, or provide ssl_ca_bundle to validate against a private CA.",
            source,
        )


def _resolve_mail_ssl_config(preset_cfg: Any) -> tuple[bool, str | None]:
    """Resolve SSL ``(verify, ca_bundle)`` via a 4-level cascade.

    Priority (highest to lowest):

    1. Preset level: ``preset_cfg.ssl_verify`` / ``preset_cfg.ssl_ca_bundle``
    2. Mail level:   ``config.mail.ssl.verify`` / ``config.mail.ssl.ca_bundle``
    3. Root level:   ``config.ssl.verify`` / ``config.ssl.ca_bundle``
       (read via :func:`kstlib.ssl.get_ssl_config`)
    4. Python defaults: ``True`` / ``None``

    The two keys cascade **independently**: ``ssl_verify`` can come from the
    preset while ``ssl_ca_bundle`` comes from ``mail.ssl``, for example.

    When the resolved ``ssl_verify`` is ``False``, a single WARNING is logged
    naming the source level (``"preset"``, ``"mail.ssl"``, ``"ssl (root)"``
    or ``"default"``) to help operators debug misconfigured relays.

    Args:
        preset_cfg: Preset configuration section (Box or dict) for the
            SMTP transport being built.

    Returns:
        Tuple ``(ssl_verify, ssl_ca_bundle)``. ``ssl_verify`` is always a
        bool. ``ssl_ca_bundle`` is either the raw path string (path
        validation is performed downstream in
        :func:`_build_smtp_ssl_context`) or ``None``.

    Raises:
        TypeError: If a resolved ``ssl_verify`` value is not a bool, or if
            ``ssl_ca_bundle`` is not a string. YAML may emit ``"yes"`` or
            other non-bool scalars; we reject rather than silently coerce.

    """
    verify: Any = preset_cfg.get("ssl_verify") if hasattr(preset_cfg, "get") else None
    ca_bundle: Any = preset_cfg.get("ssl_ca_bundle") if hasattr(preset_cfg, "get") else None
    source: str | None = "preset" if verify is not None else None

    verify, ca_bundle, source = _cascade_mail_ssl_level(verify, ca_bundle, source)
    verify, ca_bundle, source = _cascade_root_ssl_level(verify, ca_bundle, source)

    if verify is None:
        verify = True
        source = "default"

    resolved_verify, resolved_ca_bundle = _validate_mail_ssl_types(verify, ca_bundle)
    _warn_if_mail_verify_disabled(resolved_verify, source)
    return resolved_verify, resolved_ca_bundle


def _build_smtp_ssl_context(ssl_verify: bool, ssl_ca_bundle: str | None) -> ssl.SSLContext:
    """Build a stdlib :class:`ssl.SSLContext` from resolved cascade values.

    Precedence rule: ``ssl_ca_bundle`` takes priority over ``ssl_verify``.
    Providing a CA bundle expresses intent to verify (against that bundle),
    so the returned context keeps ``verify_mode=CERT_REQUIRED`` and
    ``check_hostname=True``. Only when no CA bundle is set and
    ``ssl_verify`` is ``False`` does the context fall back to ``CERT_NONE``.

    This function is **pure**: it does not read configuration nor emit log
    warnings. The cascade and the security warning live in
    :func:`_resolve_mail_ssl_config`.

    Args:
        ssl_verify: Resolved verify flag (bool).
        ssl_ca_bundle: Resolved CA bundle path, or ``None``.

    Returns:
        Configured :class:`ssl.SSLContext` suitable for
        :meth:`smtplib.SMTP.starttls` or :class:`smtplib.SMTP_SSL`.

    Raises:
        MailConfigurationError: If ``ssl_ca_bundle`` is set but invalid
            (path traversal, null byte, missing file, non-PEM content,
            unreadable, etc.). Validation is delegated to
            :func:`kstlib.ssl.validate_ca_bundle_path`.

    """
    if ssl_ca_bundle is not None:
        try:
            validated_path = validate_ca_bundle_path(ssl_ca_bundle)
        except (TypeError, ValueError) as exc:
            msg = f"Invalid ssl_ca_bundle for mail transport: {exc}"
            raise MailConfigurationError(msg) from exc
        return ssl.create_default_context(cafile=validated_path)

    if not ssl_verify:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    return ssl.create_default_context()


def _build_smtp_transport(cfg: Any) -> SMTPTransport:
    """Build ``SMTPTransport`` from a preset config section.

    SSL configuration follows a 4-level cascade (preset > ``mail.ssl`` >
    root ``ssl`` > Python default). See :func:`_resolve_mail_ssl_config`
    for the detailed priority rules and :func:`_build_smtp_ssl_context`
    for the context construction.

    Args:
        cfg: Box/dict with smtp preset fields (host, port, login, password,
            starttls, ssl, timeout, ssl_verify, ssl_ca_bundle).

    Returns:
        Configured ``SMTPTransport`` instance.

    Raises:
        MailConfigurationError: If the ``host`` field is missing or if
            ``ssl_ca_bundle`` is invalid.
        TypeError: If ``ssl_verify`` is not a bool (after cascade).

    """
    from kstlib.mail.transports.smtp import SMTPCredentials, SMTPSecurity, SMTPTransport

    host = cfg.get("host") if hasattr(cfg, "get") else None
    if not host:
        raise MailConfigurationError("SMTP preset requires a 'host' field")

    port = cfg.get("port", 587)
    timeout = cfg.get("timeout")

    login = cfg.get("login")
    password = cfg.get("password")
    credentials = SMTPCredentials(username=login, password=password) if login else None

    ssl_verify, ssl_ca_bundle = _resolve_mail_ssl_config(cfg)
    ssl_context = _build_smtp_ssl_context(ssl_verify, ssl_ca_bundle)

    security = SMTPSecurity(
        use_ssl=bool(cfg.get("ssl", False)),
        use_starttls=bool(cfg.get("starttls", True)),
        ssl_context=ssl_context,
    )

    return SMTPTransport(
        host=str(host),
        port=int(port),
        credentials=credentials,
        security=security,
        timeout=float(timeout) if timeout is not None else None,
    )


def _build_resend_transport(cfg: Any) -> ResendTransport:
    """Build ``ResendTransport`` from a preset config section.

    Args:
        cfg: Box/dict with resend preset fields (api_key, timeout).

    Returns:
        Configured ``ResendTransport`` instance.

    Raises:
        MailConfigurationError: If the ``api_key`` field is missing.

    """
    from kstlib.mail.transports.resend import ResendTransport

    api_key = cfg.get("api_key") if hasattr(cfg, "get") else None
    if not api_key:
        raise MailConfigurationError("Resend preset requires an 'api_key' field")

    timeout = cfg.get("timeout", 30.0)
    return ResendTransport(api_key=str(api_key), timeout=float(timeout))


__all__ = ["MailBuilder", "NotifyResult"]
