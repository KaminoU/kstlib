"""Tests for the mail builder fluent API."""

from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path

import pytest

# pylint: disable=redefined-outer-name
from kstlib.mail import MailBuilder, MailFilesystemGuards, MailValidationError
from kstlib.mail.exceptions import MailConfigurationError, MailTransportError
from kstlib.mail.transport import MailTransport


class FakeTransport(MailTransport):
    """In-memory transport used for assertions in tests."""

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        """Store the message in the sent list."""
        self.sent.append(message)


class ErrorTransport(MailTransport):
    """Transport double that raises ``MailTransportError`` on send."""

    def send(self, message: EmailMessage) -> None:
        """Raise MailTransportError unconditionally."""
        raise MailTransportError("boom")


@pytest.fixture
def mail_guards(tmp_path: Path) -> MailFilesystemGuards:
    """Provide relaxed guardrails rooted in the temporary workspace."""

    return MailFilesystemGuards.relaxed_for_testing(tmp_path)


class TestMailBuilder:
    """Behavioural coverage for ``MailBuilder``."""

    @staticmethod
    def _make_builder(guards: MailFilesystemGuards) -> MailBuilder:
        """Return a builder wired to the provided filesystem guardrails."""

        return MailBuilder(filesystem=guards)

    def test_builds_plain_message(self, mail_guards: MailFilesystemGuards) -> None:
        """Ensure plain body renders without HTML part."""
        builder = self._make_builder(mail_guards)
        builder.sender("sender@example.com").to("receiver@example.com").subject("Greetings").message(
            "Hello", content_type="plain"
        )

        message = builder.build()
        assert message["From"] == "sender@example.com"
        assert message["To"] == "receiver@example.com"
        assert message["Subject"] == "Greetings"
        plain_part = message.get_body("plain")
        assert plain_part is not None
        assert plain_part.get_content().strip() == "Hello"
        assert message.get_body("html") is None

    def test_builds_html_message_with_template_and_placeholders(self, mail_guards: MailFilesystemGuards) -> None:
        """Render HTML templates with placeholder substitution."""
        template_path = mail_guards.templates_root / "template.html"
        template_path.parent.mkdir(parents=True, exist_ok=True)
        template_path.write_text("<h1>{{ title }}</h1>", encoding="utf-8")

        builder = self._make_builder(mail_guards)
        builder.sender("sender@example.com").to("user@example.com").message(
            template=template_path,
            placeholders={"title": "Newsletter"},
        )

        message = builder.build()
        html_part = message.get_body("html")
        assert html_part is not None
        assert "<h1>Newsletter</h1>" in html_part.get_content()

    def test_includes_inline_resources(self, mail_guards: MailFilesystemGuards) -> None:
        """Embed inline resources with the expected CID."""
        image_path = mail_guards.inline_root / "logo.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"fake-image-bytes")

        builder = self._make_builder(mail_guards)
        builder.sender("sender@example.com").to("user@example.com").message(
            '<img src="cid:logo" />',
            content_type="html",
        ).attach_inline("logo", image_path)

        message = builder.build()
        html_part = message.get_body("html")
        assert html_part is not None

        inline_parts = [
            part for part in message.walk() if part.get_content_maintype() != "multipart" and part["Content-ID"]
        ]

        assert len(inline_parts) == 1
        assert inline_parts[0]["Content-ID"] == "<logo>"

    def test_attaches_binary_files(self, mail_guards: MailFilesystemGuards) -> None:
        """Attach binary files as message attachments."""
        file_path = mail_guards.attachments_root / "data.txt"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("payload", encoding="utf-8")

        builder = self._make_builder(mail_guards)
        builder.sender("sender@example.com").to("user@example.com").message(
            "Hi",
            content_type="plain",
        ).attach(file_path)

        message = builder.build()
        attachments = list(message.iter_attachments())
        assert len(attachments) == 1
        assert attachments[0].get_filename() == "data.txt"

    def test_detect_mime_falls_back_to_octet_stream(self, mail_guards: MailFilesystemGuards) -> None:
        """Attachments without an extension fall back to application/octet-stream."""
        file_path = mail_guards.attachments_root / "blob"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b"binary")

        builder = self._make_builder(mail_guards)
        builder.sender("sender@example.com").to("user@example.com").message(
            "Body",
            content_type="plain",
        ).attach(file_path)

        message = builder.build()
        attachment = next(message.iter_attachments())
        assert attachment.get_content_type() == "application/octet-stream"

    def test_send_uses_transport_backend(self) -> None:
        """Use the configured transport when sending."""
        transport = FakeTransport()
        builder = MailBuilder(transport=transport)
        builder.sender("sender@example.com").to("user@example.com").message(
            "Body",
            content_type="plain",
        )

        message = builder.send()
        assert transport.sent == [message]

    def test_transport_helper_attaches_backend(self) -> None:
        """The fluent ``transport()`` helper should override the backend."""
        transport = FakeTransport()
        builder = MailBuilder()
        builder.transport(transport).sender("sender@example.com").to("user@example.com").message(
            "Body",
            content_type="plain",
        )

        message = builder.send()
        assert transport.sent == [message]

    def test_send_propagates_mail_transport_errors(self) -> None:
        """Existing ``MailTransportError`` exceptions should bubble up unchanged."""
        builder = MailBuilder(transport=ErrorTransport())
        builder.sender("sender@example.com").to("user@example.com").message("Body", content_type="plain")

        with pytest.raises(MailTransportError):
            builder.send()

    def test_missing_sender_raises(self) -> None:
        """Reject builds without specifying a sender."""
        builder = MailBuilder()
        builder.to("user@example.com").message("Test", content_type="plain")

        with pytest.raises(MailValidationError):
            builder.build()

    def test_missing_recipients_raise(self) -> None:
        """Reject builds without any recipients."""
        builder = MailBuilder()
        builder.sender("sender@example.com").message("Test", content_type="plain")

        with pytest.raises(MailValidationError):
            builder.build()

    def test_missing_body_raises(self) -> None:
        """Reject builds missing message content."""
        builder = MailBuilder()
        builder.sender("sender@example.com").to("user@example.com")

        with pytest.raises(MailValidationError):
            builder.build()

    def test_reply_to_cc_bcc_headers(self) -> None:
        """Ensure secondary headers are propagated into the message."""
        builder = MailBuilder()
        builder.sender("sender@example.com").reply_to("reply@example.com").to("user@example.com").cc(
            "cc@example.com"
        ).bcc("bcc@example.com").subject("Subject").message("Body", content_type="plain")

        message = builder.build()
        assert message["Reply-To"] == "reply@example.com"
        assert message["Cc"] == "cc@example.com"
        assert message["Bcc"] == "bcc@example.com"

    def test_invalid_email_raises(self) -> None:
        """Validate email addresses on assignment."""
        builder = MailBuilder()
        with pytest.raises(MailValidationError):
            builder.sender("bad-email")

    def test_invalid_recipient_raises(self) -> None:
        """Recipient parsing should surface ``MailValidationError`` values."""
        builder = MailBuilder()
        builder.sender("sender@example.com")

        with pytest.raises(MailValidationError):
            builder.to("bad-email")

    def test_attach_requires_existing_files(self, mail_guards: MailFilesystemGuards) -> None:
        """Fail when attachments point to missing files."""
        missing = mail_guards.attachments_root / "missing.txt"
        builder = self._make_builder(mail_guards)
        builder.sender("sender@example.com").to("user@example.com").message("Body", content_type="plain")

        with pytest.raises(MailValidationError):
            builder.attach(missing)

    def test_attachment_outside_guardrail_is_rejected(self, tmp_path: Path, mail_guards: MailFilesystemGuards) -> None:
        """Reject attachments outside the configured guardrail root."""

        rogue_path = tmp_path.parent / "rogue.txt"
        rogue_path.write_text("payload", encoding="utf-8")

        builder = self._make_builder(mail_guards)
        builder.sender("sender@example.com").to("user@example.com").message("Body", content_type="plain")

        with pytest.raises(MailValidationError):
            builder.attach(rogue_path)

    def test_attach_without_arguments_raises(self) -> None:
        """Calling attach without files should fail fast."""
        builder = MailBuilder()
        builder.sender("sender@example.com").to("user@example.com").message("Body", content_type="plain")

        with pytest.raises(MailValidationError):
            builder.attach()

    def test_attach_inline_requires_html_body(self, mail_guards: MailFilesystemGuards) -> None:
        """Inline attachments require an HTML body."""
        image_path = mail_guards.inline_root / "img.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"data")

        builder = self._make_builder(mail_guards)
        builder.sender("sender@example.com").to("user@example.com").message("plain", content_type="plain")

        with pytest.raises(MailValidationError):
            builder.attach_inline("cid", image_path).build()

    def test_attach_inline_requires_cid(self, mail_guards: MailFilesystemGuards) -> None:
        """Inline attachments must include a non-empty CID."""
        image_path = mail_guards.inline_root / "img.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"data")

        builder = self._make_builder(mail_guards)
        builder.sender("sender@example.com").to("user@example.com").message("<p>Body</p>", content_type="html")

        with pytest.raises(MailValidationError):
            builder.attach_inline("", image_path)

    def test_attach_inline_requires_existing_file(self, mail_guards: MailFilesystemGuards) -> None:
        """Inline attachments must point to an existing path."""
        missing = mail_guards.inline_root / "missing.png"

        builder = self._make_builder(mail_guards)
        builder.sender("sender@example.com").to("user@example.com").message("<p>Body</p>", content_type="html")

        with pytest.raises(MailValidationError):
            builder.attach_inline("cid", missing)

    def test_template_file_missing_raises(self, mail_guards: MailFilesystemGuards) -> None:
        """Template rendering should fail when the file is absent."""
        missing_template = mail_guards.templates_root / "missing.html"
        builder = self._make_builder(mail_guards)
        builder.sender("sender@example.com").to("user@example.com")

        with pytest.raises(MailValidationError):
            builder.message(template=missing_template)

    def test_message_requires_content(self) -> None:
        """``message()`` must be provided with raw content or a template."""
        builder = MailBuilder()
        builder.sender("sender@example.com").to("user@example.com")

        with pytest.raises(MailValidationError):
            builder.message()

    def test_placeholders_allow_kwargs_override(self) -> None:
        """Additional keyword placeholders should override the base mapping."""
        builder = MailBuilder()
        builder.sender("sender@example.com").to("user@example.com").message(
            "<p>{{ name }}</p>",
            content_type="html",
            placeholders={"name": "Original"},
            name="Override",
        )

        html_part = builder.build().get_body("html")
        assert html_part is not None
        assert "Override" in html_part.get_content()

    def test_send_without_transport_raises(self) -> None:
        """Send should fail when no transport is configured."""
        builder = MailBuilder()
        builder.sender("sender@example.com").to("user@example.com").message("Body", content_type="plain")

        with pytest.raises(MailConfigurationError):
            builder.send()

    def test_max_attachments_exceeded_raises(self, mail_guards: MailFilesystemGuards) -> None:
        """Reject when attachment count exceeds configured limit."""
        from kstlib.limits import MailLimits

        # Create limits with max 2 attachments
        limits = MailLimits(max_attachment_size=1024 * 1024, max_attachments=2)

        # Create 3 files
        for i in range(3):
            f = mail_guards.attachments_root / f"file{i}.txt"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(f"content{i}", encoding="utf-8")

        builder = MailBuilder(filesystem=mail_guards, limits=limits)
        builder.sender("sender@example.com").to("user@example.com").message("Body", content_type="plain")

        # Attach first two files - should succeed
        builder.attach(
            mail_guards.attachments_root / "file0.txt",
            mail_guards.attachments_root / "file1.txt",
        )

        # Third attachment should fail
        with pytest.raises(MailValidationError, match="Maximum of 2 attachments exceeded"):
            builder.attach(mail_guards.attachments_root / "file2.txt")

    def test_attachment_size_exceeded_raises(self, mail_guards: MailFilesystemGuards) -> None:
        """Reject attachments that exceed the size limit."""
        from kstlib.limits import MailLimits

        # Create limits with max 10 bytes per attachment
        limits = MailLimits(max_attachment_size=10, max_attachments=10)

        # Create a file larger than 10 bytes
        large_file = mail_guards.attachments_root / "large.txt"
        large_file.parent.mkdir(parents=True, exist_ok=True)
        large_file.write_text("This content is definitely larger than 10 bytes", encoding="utf-8")

        builder = MailBuilder(filesystem=mail_guards, limits=limits)
        builder.sender("sender@example.com").to("user@example.com").message("Body", content_type="plain")

        with pytest.raises(MailValidationError, match="exceeds size limit"):
            builder.attach(large_file)

    def test_inline_resource_size_exceeded_raises(self, mail_guards: MailFilesystemGuards) -> None:
        """Reject inline resources that exceed the size limit."""
        from kstlib.limits import MailLimits

        # Create limits with max 10 bytes per attachment/inline
        limits = MailLimits(max_attachment_size=10, max_attachments=10)

        # Create an inline image larger than 10 bytes
        large_image = mail_guards.inline_root / "large.png"
        large_image.parent.mkdir(parents=True, exist_ok=True)
        large_image.write_bytes(b"This is fake image data that exceeds 10 bytes")

        builder = MailBuilder(filesystem=mail_guards, limits=limits)
        builder.sender("sender@example.com").to("user@example.com").message(
            '<img src="cid:logo" />', content_type="html"
        )

        with pytest.raises(MailValidationError, match="exceeds size limit"):
            builder.attach_inline("logo", large_image)
