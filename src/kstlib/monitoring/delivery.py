"""Delivery backends for monitoring results.

This module provides delivery mechanisms for MonitoringResult outputs:

- **FileDelivery**: Save HTML to local files with rotation
- **MailDelivery**: Send via kstlib.mail transports (wrapper)

Examples:
    Save to file:

    >>> from kstlib.monitoring.delivery import FileDelivery
    >>> delivery = FileDelivery(output_dir="./reports")  # doctest: +SKIP
    >>> result = await delivery.deliver(monitoring_result, "daily")  # doctest: +SKIP
    >>> print(result.path)  # doctest: +SKIP

    Send via email:

    >>> from kstlib.monitoring.delivery import MailDelivery
    >>> delivery = MailDelivery(  # doctest: +SKIP
    ...     transport=gmail_transport,
    ...     sender="bot@example.com",
    ...     recipients=["team@example.com"],
    ... )
    >>> result = await delivery.deliver(monitoring_result, "Daily Report")  # doctest: +SKIP
"""

from __future__ import annotations

import asyncio
import pathlib
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import TYPE_CHECKING, Any

from kstlib.monitoring.exceptions import MonitoringError

if TYPE_CHECKING:
    from kstlib.mail.transport import AsyncMailTransport, MailTransport
    from kstlib.monitoring.service import MonitoringResult

# Deep defense: Security limits
MAX_OUTPUT_DIR_DEPTH = 10  # Maximum directory depth from cwd
MAX_FILENAME_LENGTH = 200  # Maximum filename length
MAX_FILES_PER_DIR = 1000  # Maximum files to keep in output directory
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB max output file size
MAX_RECIPIENTS = 50  # Maximum email recipients
MAX_SUBJECT_LENGTH = 200  # Maximum email subject length

# Filename validation pattern (alphanumeric, dash, underscore, dot)
SAFE_FILENAME_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.]+$")


class DeliveryError(MonitoringError):
    """Base exception for delivery errors."""


class DeliveryConfigError(DeliveryError, ValueError):
    """Invalid delivery configuration."""


class DeliveryIOError(DeliveryError, OSError):
    """I/O error during delivery."""


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    """Result of a delivery operation.

    Attributes:
        success: Whether delivery succeeded.
        timestamp: When delivery was attempted.
        path: Output file path (for file delivery).
        message_id: Email message ID (for mail delivery).
        error: Error message if delivery failed.
        metadata: Additional delivery metadata.
    """

    success: bool
    timestamp: datetime
    path: pathlib.Path | None = None
    message_id: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class DeliveryBackend(ABC):
    """Abstract base class for delivery backends."""

    @abstractmethod
    async def deliver(
        self,
        result: MonitoringResult,
        name: str,
    ) -> DeliveryResult:
        """Deliver a monitoring result.

        Args:
            result: The MonitoringResult to deliver.
            name: Name/subject for this delivery.

        Returns:
            DeliveryResult with success status and metadata.
        """


def _validate_path_safety(path: pathlib.Path, base_dir: pathlib.Path) -> None:
    """Validate path is within allowed directory (deep defense)."""
    try:
        resolved = path.resolve()
        base_resolved = base_dir.resolve()
        resolved.relative_to(base_resolved)
    except ValueError as e:
        raise DeliveryConfigError(f"Path traversal detected: {path}") from e


def _sanitize_filename(name: str, timestamp: datetime) -> str:
    """Create a safe filename from name and timestamp."""
    # Remove unsafe characters
    safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", name)
    # Limit length
    safe_name = safe_name[:50]
    # Add timestamp
    ts = timestamp.strftime("%Y%m%d_%H%M%S")
    return f"{safe_name}_{ts}.html"


@dataclass
class FileDeliveryConfig:
    """Configuration for file delivery.

    Attributes:
        output_dir: Directory to save files.
        filename_template: Template for filenames (supports {name}, {timestamp}).
        create_dirs: Create output directory if missing.
        max_files: Maximum files to keep (oldest deleted, 0=unlimited).
        encoding: File encoding.
    """

    output_dir: str | pathlib.Path
    filename_template: str = "{name}_{timestamp}.html"
    create_dirs: bool = True
    max_files: int = 100
    encoding: str = "utf-8"

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if isinstance(self.output_dir, str):
            object.__setattr__(self, "output_dir", pathlib.Path(self.output_dir))

        # Deep defense: Validate max_files
        if self.max_files < 0:
            raise DeliveryConfigError("max_files cannot be negative")
        if self.max_files > MAX_FILES_PER_DIR:
            raise DeliveryConfigError(f"max_files exceeds limit ({MAX_FILES_PER_DIR})")


class FileDelivery(DeliveryBackend):
    """Deliver monitoring results to local files.

    Saves HTML output to files with automatic rotation and cleanup.

    Args:
        output_dir: Directory to save files (str or Path).
        filename_template: Template for filenames.
        create_dirs: Create output directory if missing.
        max_files: Maximum files to keep (oldest deleted when exceeded).
        encoding: File encoding.

    Examples:
        >>> delivery = FileDelivery(output_dir="./reports")  # doctest: +SKIP
        >>> result = await delivery.deliver(monitoring_result, "daily")  # doctest: +SKIP
        >>> print(f"Saved to: {result.path}")  # doctest: +SKIP

        With rotation (keep last 7 files):

        >>> delivery = FileDelivery(  # doctest: +SKIP
        ...     output_dir="./reports",
        ...     max_files=7,
        ... )
    """

    def __init__(
        self,
        output_dir: str | pathlib.Path,
        *,
        filename_template: str = "{name}_{timestamp}.html",
        create_dirs: bool = True,
        max_files: int = 100,
        encoding: str = "utf-8",
    ) -> None:
        """Initialize file delivery backend."""
        self._config = FileDeliveryConfig(
            output_dir=pathlib.Path(output_dir),
            filename_template=filename_template,
            create_dirs=create_dirs,
            max_files=max_files,
            encoding=encoding,
        )
        self._last_result: DeliveryResult | None = None

    @property
    def config(self) -> FileDeliveryConfig:
        """Return the delivery configuration."""
        return self._config

    @property
    def last_result(self) -> DeliveryResult | None:
        """Return the last delivery result."""
        return self._last_result

    def _generate_filename(self, name: str, timestamp: datetime) -> str:
        """Generate filename from template."""
        ts_str = timestamp.strftime("%Y%m%d_%H%M%S")
        # Sanitize name
        safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", name)[:50]
        filename = self._config.filename_template.format(
            name=safe_name,
            timestamp=ts_str,
        )
        # Deep defense: Validate final filename
        if len(filename) > MAX_FILENAME_LENGTH:
            raise DeliveryConfigError(f"Generated filename too long ({len(filename)} > {MAX_FILENAME_LENGTH})")
        return filename

    def _cleanup_old_files(self, output_dir: pathlib.Path) -> int:
        """Remove oldest files if max_files exceeded. Returns count deleted."""
        if self._config.max_files == 0:
            return 0

        html_files = sorted(
            output_dir.glob("*.html"),
            key=lambda p: p.stat().st_mtime,
        )
        to_delete = len(html_files) - self._config.max_files
        deleted = 0

        if to_delete > 0:
            for old_file in html_files[:to_delete]:
                try:
                    old_file.unlink()
                    deleted += 1
                except OSError:
                    pass  # Best effort cleanup

        return deleted

    def _validate_output_dir(self, output_dir: pathlib.Path) -> None:
        """Validate output directory depth and existence (deep defense)."""
        try:
            cwd = pathlib.Path.cwd().resolve()
            rel_path = output_dir.relative_to(cwd)
            if len(rel_path.parts) > MAX_OUTPUT_DIR_DEPTH:
                raise DeliveryConfigError(f"Output directory too deep ({len(rel_path.parts)} > {MAX_OUTPUT_DIR_DEPTH})")
        except ValueError:
            # Path not relative to cwd, check absolute depth
            if len(output_dir.parts) > MAX_OUTPUT_DIR_DEPTH + 5:
                raise DeliveryConfigError("Output directory path too deep") from None

        # Create directory if needed
        if self._config.create_dirs:
            output_dir.mkdir(parents=True, exist_ok=True)

        if not output_dir.is_dir():
            raise DeliveryConfigError(f"Output directory does not exist: {output_dir}")

    async def deliver(
        self,
        result: MonitoringResult,
        name: str,
    ) -> DeliveryResult:
        """Save monitoring result HTML to a file.

        Args:
            result: The MonitoringResult to save.
            name: Name for this report (used in filename).

        Returns:
            DeliveryResult with file path on success.

        Raises:
            DeliveryIOError: If file cannot be written.
            DeliveryConfigError: If configuration is invalid.
        """
        timestamp = datetime.now(timezone.utc)
        delivery_result: DeliveryResult | None = None

        try:
            output_dir = pathlib.Path(self._config.output_dir).resolve()

            # Deep defense: Validate directory
            self._validate_output_dir(output_dir)

            # Generate filename
            filename = self._generate_filename(name, timestamp)
            output_path = output_dir / filename

            # Deep defense: Validate path safety
            _validate_path_safety(output_path, output_dir)

            # Deep defense: Check content size
            html_bytes = result.html.encode(self._config.encoding)
            if len(html_bytes) > MAX_FILE_SIZE:
                raise DeliveryConfigError(f"Output too large ({len(html_bytes)} > {MAX_FILE_SIZE} bytes)")

            # Write file (run in executor for async compatibility)
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                lambda: output_path.write_bytes(html_bytes),
            )

            # Cleanup old files
            deleted = await loop.run_in_executor(
                None,
                lambda: self._cleanup_old_files(output_dir),
            )

            delivery_result = DeliveryResult(
                success=True,
                timestamp=timestamp,
                path=output_path,
                metadata={
                    "size_bytes": len(html_bytes),
                    "files_deleted": deleted,
                    "encoding": self._config.encoding,
                },
            )

        except DeliveryError as e:
            delivery_result = DeliveryResult(
                success=False,
                timestamp=timestamp,
                error=str(e),
            )
            raise
        except OSError as e:
            delivery_result = DeliveryResult(
                success=False,
                timestamp=timestamp,
                error=f"I/O error: {e}",
            )
            raise DeliveryIOError(f"Failed to write file: {e}") from e
        except Exception as e:
            delivery_result = DeliveryResult(
                success=False,
                timestamp=timestamp,
                error=str(e),
            )
            raise DeliveryError(f"Unexpected error during delivery: {e}") from e
        finally:
            if delivery_result is not None:
                self._last_result = delivery_result

        return delivery_result


@dataclass
class MailDeliveryConfig:
    """Configuration for mail delivery.

    Attributes:
        sender: Sender email address.
        recipients: List of recipient addresses.
        cc: List of CC addresses.
        bcc: List of BCC addresses.
        subject_template: Subject template (supports {name}).
        include_plain_text: Include plain text version.
    """

    sender: str
    recipients: list[str]
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    subject_template: str = "Monitoring Report: {name}"
    include_plain_text: bool = True

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if not self.sender:
            raise DeliveryConfigError("Sender address is required")
        if not self.recipients:
            raise DeliveryConfigError("At least one recipient is required")

        # Deep defense: Limit recipients
        total_recipients = len(self.recipients) + len(self.cc) + len(self.bcc)
        if total_recipients > MAX_RECIPIENTS:
            raise DeliveryConfigError(f"Too many recipients ({total_recipients} > {MAX_RECIPIENTS})")


class MailDelivery(DeliveryBackend):
    """Deliver monitoring results via email.

    Wraps kstlib.mail transports for monitoring delivery.

    Args:
        transport: Mail transport (sync or async).
        sender: Sender email address.
        recipients: List of recipient addresses.
        cc: Optional CC addresses.
        bcc: Optional BCC addresses.
        subject_template: Subject template with {name} placeholder.
        include_plain_text: Include plain text version of HTML.

    Examples:
        >>> from kstlib.mail.transports.gmail import GmailTransport
        >>> transport = GmailTransport(...)  # doctest: +SKIP
        >>> delivery = MailDelivery(  # doctest: +SKIP
        ...     transport=transport,
        ...     sender="bot@example.com",
        ...     recipients=["team@example.com"],
        ... )
        >>> result = await delivery.deliver(monitoring_result, "Daily Report")  # doctest: +SKIP
    """

    def __init__(
        self,
        transport: MailTransport | AsyncMailTransport,
        config: MailDeliveryConfig,
    ) -> None:
        """Initialize mail delivery backend.

        Args:
            transport: Mail transport (sync or async).
            config: Mail delivery configuration.
        """
        self._transport = transport
        self._config = config
        self._last_result: DeliveryResult | None = None

    @classmethod
    def create(
        cls,
        transport: MailTransport | AsyncMailTransport,
        sender: str,
        recipients: list[str],
        **kwargs: Any,
    ) -> MailDelivery:
        """Create a MailDelivery with configuration.

        Convenience factory method that creates the config internally.

        Args:
            transport: Mail transport (sync or async).
            sender: Sender email address.
            recipients: List of recipient addresses.
            **kwargs: Additional config options (cc, bcc, subject_template, etc.).

        Returns:
            Configured MailDelivery instance.
        """
        config = MailDeliveryConfig(
            sender=sender,
            recipients=list(recipients),
            cc=list(kwargs.get("cc", [])) if kwargs.get("cc") else [],
            bcc=list(kwargs.get("bcc", [])) if kwargs.get("bcc") else [],
            subject_template=kwargs.get("subject_template", "Monitoring Report: {name}"),
            include_plain_text=kwargs.get("include_plain_text", True),
        )
        return cls(transport, config)

    @property
    def config(self) -> MailDeliveryConfig:
        """Return the delivery configuration."""
        return self._config

    @property
    def last_result(self) -> DeliveryResult | None:
        """Return the last delivery result."""
        return self._last_result

    def _build_message(self, html: str, subject: str) -> EmailMessage:
        """Build EmailMessage from HTML content."""
        msg = EmailMessage()
        msg["From"] = self._config.sender
        msg["To"] = ", ".join(self._config.recipients)
        if self._config.cc:
            msg["Cc"] = ", ".join(self._config.cc)
        if self._config.bcc:
            msg["Bcc"] = ", ".join(self._config.bcc)

        # Deep defense: Validate subject length
        if len(subject) > MAX_SUBJECT_LENGTH:
            subject = subject[: MAX_SUBJECT_LENGTH - 3] + "..."

        msg["Subject"] = subject

        if self._config.include_plain_text:
            # Create multipart message with plain and HTML
            # Simple HTML to text conversion (strip tags)
            plain_text = re.sub(r"<[^>]+>", "", html)
            plain_text = re.sub(r"\s+", " ", plain_text).strip()

            msg.set_content(plain_text)
            msg.add_alternative(html, subtype="html")
        else:
            msg.set_content(html, subtype="html")

        return msg

    async def deliver(
        self,
        result: MonitoringResult,
        name: str,
    ) -> DeliveryResult:
        """Send monitoring result via email.

        Args:
            result: The MonitoringResult to send.
            name: Name for this report (used in subject).

        Returns:
            DeliveryResult with message ID on success.

        Raises:
            DeliveryError: If email cannot be sent.
        """
        import inspect

        timestamp = datetime.now(timezone.utc)

        try:
            # Generate subject
            subject = self._config.subject_template.format(name=name)

            # Build message
            message = self._build_message(result.html, subject)

            # Send via transport
            if hasattr(self._transport, "send") and inspect.iscoroutinefunction(self._transport.send):
                await self._transport.send(message)
            else:
                # Sync transport - run in executor
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._transport.send, message)

            # Try to get message ID from transport response
            message_id = None
            if hasattr(self._transport, "last_response"):
                resp = self._transport.last_response
                if resp and hasattr(resp, "id"):
                    message_id = resp.id

            delivery_result = DeliveryResult(
                success=True,
                timestamp=timestamp,
                message_id=message_id,
                metadata={
                    "recipients": len(self._config.recipients),
                    "subject": subject,
                },
            )

        except Exception as e:
            delivery_result = DeliveryResult(
                success=False,
                timestamp=timestamp,
                error=str(e),
            )
            raise DeliveryError(f"Failed to send email: {e}") from e
        finally:
            self._last_result = delivery_result

        return delivery_result


__all__ = [
    "DeliveryBackend",
    "DeliveryConfigError",
    "DeliveryError",
    "DeliveryIOError",
    "DeliveryResult",
    "FileDelivery",
    "FileDeliveryConfig",
    "MailDelivery",
    "MailDeliveryConfig",
]
