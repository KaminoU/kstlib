"""Tests for the mail builder fluent API."""

from __future__ import annotations

import asyncio
from email.message import EmailMessage
from pathlib import Path

import pytest

# pylint: disable=redefined-outer-name
from kstlib.mail import MailBuilder, MailFilesystemGuards, MailValidationError, NotifyCollector
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


class _RecordingTransport(MailTransport):
    """Transport double that stores sent messages for inspection."""

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        """Record the sent message."""
        self.sent.append(message)


def _build_for_notify(transport: MailTransport) -> MailBuilder:
    """Create a notify-ready builder wired to the provided transport."""
    return MailBuilder(transport=transport).sender("bot@example.com").to("admin@example.com").subject("Job")


class TestNotifyModeFiltering:
    """Tests for the new mode/on_success_only filtering of notify."""

    def test_mode_ok_on_success_sends(self) -> None:
        """mode='ok' triggers a mail on success."""
        transport = _RecordingTransport()
        mail = _build_for_notify(transport)

        @mail.notify(mode="ok")
        def fn() -> int:
            return 1

        fn()
        assert len(transport.sent) == 1
        assert transport.sent[0]["Subject"].startswith("[OK]")

    def test_mode_ok_on_exception_skips(self) -> None:
        """mode='ok' suppresses the mail when the function raises."""
        transport = _RecordingTransport()
        mail = _build_for_notify(transport)

        @mail.notify(mode="ok")
        def fn() -> int:
            raise ValueError("nope")

        with pytest.raises(ValueError, match="nope"):
            fn()
        assert transport.sent == []

    def test_mode_ko_on_success_skips(self) -> None:
        """mode='ko' suppresses the mail on success."""
        transport = _RecordingTransport()
        mail = _build_for_notify(transport)

        @mail.notify(mode="ko")
        def fn() -> int:
            return 1

        fn()
        assert transport.sent == []

    def test_mode_ko_on_exception_sends(self) -> None:
        """mode='ko' triggers a mail on exception."""
        transport = _RecordingTransport()
        mail = _build_for_notify(transport)

        @mail.notify(mode="ko")
        def fn() -> int:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            fn()
        assert len(transport.sent) == 1
        assert transport.sent[0]["Subject"].startswith("[FAILED]")

    def test_mode_both_default_behavior(self) -> None:
        """mode='both' matches the legacy default (mail on OK and KO)."""
        transport = _RecordingTransport()
        mail = _build_for_notify(transport)

        @mail.notify(mode="both")
        def ok_fn() -> int:
            return 1

        @mail.notify(mode="both")
        def ko_fn() -> int:
            raise ValueError("x")

        ok_fn()
        with pytest.raises(ValueError):
            ko_fn()
        assert len(transport.sent) == 2

    def test_mode_case_insensitive(self) -> None:
        """mode='OK' is normalised to 'ok'."""
        transport = _RecordingTransport()
        mail = _build_for_notify(transport)

        @mail.notify(mode="OK")
        def fn() -> int:
            return 1

        fn()
        assert len(transport.sent) == 1

    def test_on_success_only_on_success(self) -> None:
        """on_success_only=True triggers a mail on success."""
        transport = _RecordingTransport()
        mail = _build_for_notify(transport)

        @mail.notify(on_success_only=True)
        def fn() -> int:
            return 1

        fn()
        assert len(transport.sent) == 1

    def test_on_success_only_on_exception(self) -> None:
        """on_success_only=True suppresses the mail on exception."""
        transport = _RecordingTransport()
        mail = _build_for_notify(transport)

        @mail.notify(on_success_only=True)
        def fn() -> int:
            raise ValueError("x")

        with pytest.raises(ValueError):
            fn()
        assert transport.sent == []


class TestNotifyValidation:
    """Validation error cases for notify kwargs."""

    def test_mode_and_on_error_only_conflict(self) -> None:
        """Combining mode and on_error_only raises MailValidationError."""
        transport = _RecordingTransport()
        mail = _build_for_notify(transport)
        with pytest.raises(MailValidationError, match="Use mode=.*not both"):
            mail.notify(mode="ok", on_error_only=True)

    def test_mode_and_on_success_only_conflict(self) -> None:
        """Combining mode and on_success_only raises MailValidationError."""
        transport = _RecordingTransport()
        mail = _build_for_notify(transport)
        with pytest.raises(MailValidationError, match="Use mode=.*not both"):
            mail.notify(mode="ko", on_success_only=True)

    def test_on_error_only_and_on_success_only_mutually_exclusive(self) -> None:
        """Setting both on_error_only and on_success_only raises."""
        transport = _RecordingTransport()
        mail = _build_for_notify(transport)
        with pytest.raises(MailValidationError, match="mutually exclusive"):
            mail.notify(on_error_only=True, on_success_only=True)

    def test_mode_invalid_value(self) -> None:
        """An unknown mode value raises MailValidationError."""
        transport = _RecordingTransport()
        mail = _build_for_notify(transport)
        with pytest.raises(MailValidationError, match="mode must be"):
            mail.notify(mode="invalid")

    def test_mode_non_string(self) -> None:
        """Passing a non-string mode raises MailValidationError."""
        transport = _RecordingTransport()
        mail = _build_for_notify(transport)
        with pytest.raises(MailValidationError, match="mode must be"):
            mail.notify(mode=42)  # type: ignore[call-overload]


class TestNotifyCollectorCapture:
    """Filtered capture into a NotifyCollector."""

    def test_collector_mode_ok_captures_only_success(self) -> None:
        """mode='ok' captures the success but ignores the failure."""
        transport = _RecordingTransport()
        mail = _build_for_notify(transport)
        collector = NotifyCollector()

        @mail.notify(collector=collector, mode="ok")
        def ok_fn() -> int:
            return 1

        @mail.notify(collector=collector, mode="ok")
        def ko_fn() -> int:
            raise ValueError("x")

        ok_fn()
        with pytest.raises(ValueError):
            ko_fn()
        assert collector.total_count == 1
        assert collector.results[0].function_name == "ok_fn"
        assert collector.results[0].success is True

    def test_collector_mode_ko_captures_only_failure(self) -> None:
        """mode='ko' captures the failure but ignores the success."""
        transport = _RecordingTransport()
        mail = _build_for_notify(transport)
        collector = NotifyCollector()

        @mail.notify(collector=collector, mode="ko")
        def ok_fn() -> int:
            return 1

        @mail.notify(collector=collector, mode="ko")
        def ko_fn() -> int:
            raise RuntimeError("boom")

        ok_fn()
        with pytest.raises(RuntimeError):
            ko_fn()
        assert collector.total_count == 1
        assert collector.results[0].function_name == "ko_fn"
        assert collector.results[0].success is False

    def test_collector_default_mode_captures_everything(self) -> None:
        """Default (both) mode captures every result."""
        transport = _RecordingTransport()
        mail = _build_for_notify(transport)
        collector = NotifyCollector()

        @mail.notify(collector=collector)
        def ok_fn() -> int:
            return 1

        @mail.notify(collector=collector)
        def ko_fn() -> int:
            raise ValueError("x")

        ok_fn()
        with pytest.raises(ValueError):
            ko_fn()
        assert collector.total_count == 2

    def test_double_decorator_pattern_one_entry_per_execution(self) -> None:
        """mlok mode=ok + mlko mode=ko + same collector yields one entry per call."""
        transport = _RecordingTransport()
        collector = NotifyCollector()
        mlok = _build_for_notify(transport).subject("OK group")
        mlko = _build_for_notify(transport).subject("KO group")

        @mlok.notify(collector=collector, mode="ok")
        @mlko.notify(collector=collector, mode="ko")
        def check() -> int:
            return 1

        @mlok.notify(collector=collector, mode="ok")
        @mlko.notify(collector=collector, mode="ko")
        def check_fail() -> int:
            raise RuntimeError("boom")

        check()
        with pytest.raises(RuntimeError):
            check_fail()

        assert collector.total_count == 2
        names = [r.function_name for r in collector.results]
        assert names.count("check") == 1
        assert names.count("check_fail") == 1


class TestNotifyAsyncExtended:
    """Async parity for mode + collector."""

    @pytest.mark.asyncio
    async def test_async_mode_ok(self) -> None:
        """Async wrapper honors mode='ok'."""
        transport = _RecordingTransport()
        mail = _build_for_notify(transport)

        @mail.notify(mode="ok")
        async def ok_fn() -> int:
            await asyncio.sleep(0.001)
            return 1

        @mail.notify(mode="ok")
        async def ko_fn() -> int:
            await asyncio.sleep(0.001)
            raise ValueError("x")

        await ok_fn()
        with pytest.raises(ValueError):
            await ko_fn()
        assert len(transport.sent) == 1
        assert transport.sent[0]["Subject"].startswith("[OK]")

    @pytest.mark.asyncio
    async def test_async_mode_ko(self) -> None:
        """Async wrapper honors mode='ko'."""
        transport = _RecordingTransport()
        mail = _build_for_notify(transport)

        @mail.notify(mode="ko")
        async def ok_fn() -> int:
            await asyncio.sleep(0.001)
            return 1

        @mail.notify(mode="ko")
        async def ko_fn() -> int:
            await asyncio.sleep(0.001)
            raise RuntimeError("boom")

        await ok_fn()
        with pytest.raises(RuntimeError):
            await ko_fn()
        assert len(transport.sent) == 1
        assert transport.sent[0]["Subject"].startswith("[FAILED]")

    @pytest.mark.asyncio
    async def test_async_collector_capture(self) -> None:
        """Async wrapper records into the collector following the active mode."""
        transport = _RecordingTransport()
        mail = _build_for_notify(transport)
        collector = NotifyCollector()

        @mail.notify(collector=collector, mode="ok")
        async def ok_fn() -> int:
            await asyncio.sleep(0.001)
            return 7

        @mail.notify(collector=collector, mode="ok")
        async def ko_fn() -> int:
            await asyncio.sleep(0.001)
            raise ValueError("x")

        await ok_fn()
        with pytest.raises(ValueError):
            await ko_fn()
        assert collector.total_count == 1
        assert collector.results[0].function_name == "ok_fn"


class TestSendSummary:
    """Tests for MailBuilder.send_summary."""

    def _seed_collector(self) -> NotifyCollector:
        """Return a collector with one OK and one KO entry."""
        transport = _RecordingTransport()
        mail = _build_for_notify(transport)
        collector = NotifyCollector()

        @mail.notify(collector=collector)
        def ok_fn() -> int:
            return 1

        @mail.notify(collector=collector)
        def ko_fn() -> int:
            raise ValueError("boom")

        ok_fn()
        with pytest.raises(ValueError):
            ko_fn()
        return collector

    def test_send_summary_html(self) -> None:
        """format='html' delivers an HTML body with the rendered table."""
        transport = _RecordingTransport()
        mail = _build_for_notify(transport).subject("Recap")
        collector = self._seed_collector()

        msg = mail.send_summary(collector, format="html")
        # Discard the seeding sends recorded on a different transport
        # we only assert on the latest send via this builder.
        assert len(transport.sent) == 1
        sent = transport.sent[0]
        assert sent is msg
        html_part = sent.get_body("html")
        assert html_part is not None
        body = html_part.get_content()
        assert "ok_fn" in body
        assert "ko_fn" in body
        assert "<table" in body

    def test_send_summary_plain(self) -> None:
        """format='plain' delivers a text body via plain rendering."""
        transport = _RecordingTransport()
        mail = _build_for_notify(transport).subject("Recap")
        collector = self._seed_collector()

        mail.send_summary(collector, format="plain")
        assert len(transport.sent) == 1
        plain_part = transport.sent[0].get_body("plain")
        assert plain_part is not None
        body = plain_part.get_content()
        assert "[OK] ok_fn" in body
        assert "[FAILED] ko_fn" in body

    def test_send_summary_monitor_table(self) -> None:
        """format='monitor_table' delivers HTML built from MonitorTable."""
        transport = _RecordingTransport()
        mail = _build_for_notify(transport).subject("Recap")
        collector = self._seed_collector()

        mail.send_summary(collector, format="monitor_table")
        assert len(transport.sent) == 1
        html_part = transport.sent[0].get_body("html")
        assert html_part is not None
        body = html_part.get_content()
        assert "<table" in body
        assert "ok_fn" in body
        assert "ko_fn" in body

    def test_send_summary_subject_override(self) -> None:
        """An explicit subject overrides the builder default."""
        transport = _RecordingTransport()
        mail = _build_for_notify(transport).subject("Default")
        collector = self._seed_collector()

        mail.send_summary(collector, subject="Custom recap")
        assert transport.sent[0]["Subject"] == "Custom recap"

    def test_send_summary_does_not_mutate_builder(self) -> None:
        """send_summary leaves the original builder state intact."""
        transport = _RecordingTransport()
        mail = _build_for_notify(transport).subject("Original").message("<p>orig</p>", content_type="html")
        collector = self._seed_collector()

        mail.send_summary(collector, subject="Recap", format="html")
        # Subsequent send should reuse the original subject/body.
        mail.send()
        assert len(transport.sent) == 2
        assert transport.sent[0]["Subject"] == "Recap"
        assert transport.sent[1]["Subject"] == "Original"
        html_part = transport.sent[1].get_body("html")
        assert html_part is not None
        assert "orig" in html_part.get_content()

    def test_send_summary_invalid_format(self) -> None:
        """An unsupported format raises MailValidationError."""
        transport = _RecordingTransport()
        mail = _build_for_notify(transport).subject("Recap")
        collector = NotifyCollector()
        with pytest.raises(MailValidationError, match="format must be"):
            mail.send_summary(collector, format="xml")  # type: ignore[arg-type]


class TestMessageJinja2Templates:
    """Jinja2 rendering of MailBuilder.message templates."""

    def test_simple_substitution_string_template(self) -> None:
        """Backward compat: {{ var }} substitution still works on inline content."""
        builder = MailBuilder()
        builder.sender("sender@example.com").to("user@example.com").message(
            "<p>{{ name }}</p>",
            content_type="html",
            placeholders={"name": "Ada"},
        )
        html_part = builder.build().get_body("html")
        assert html_part is not None
        assert "<p>Ada</p>" in html_part.get_content()

    def test_for_loop_in_template(self, mail_guards: MailFilesystemGuards) -> None:
        """Templates support {% for %} loops over list values."""
        template_path = mail_guards.templates_root / "loop.html"
        template_path.parent.mkdir(parents=True, exist_ok=True)
        template_path.write_text(
            "<ul>{% for item in items %}<li>{{ item }}</li>{% endfor %}</ul>",
            encoding="utf-8",
        )
        builder = MailBuilder(filesystem=mail_guards)
        builder.sender("sender@example.com").to("user@example.com").message(
            template=template_path,
            placeholders={"items": ["a", "b", "c"]},
        )
        html_part = builder.build().get_body("html")
        assert html_part is not None
        body = html_part.get_content()
        assert "<li>a</li>" in body
        assert "<li>b</li>" in body
        assert "<li>c</li>" in body

    def test_if_else_in_template(self, mail_guards: MailFilesystemGuards) -> None:
        """Templates support {% if %}/{% else %} conditionals."""
        template_path = mail_guards.templates_root / "cond.html"
        template_path.parent.mkdir(parents=True, exist_ok=True)
        template_path.write_text(
            "<p>{% if ok %}YES{% else %}NO{% endif %}</p>",
            encoding="utf-8",
        )
        builder = MailBuilder(filesystem=mail_guards)
        builder.sender("sender@example.com").to("user@example.com").message(
            template=template_path,
            placeholders={"ok": True},
        )
        html_part = builder.build().get_body("html")
        assert html_part is not None
        assert "<p>YES</p>" in html_part.get_content()

    def test_filter_in_template(self) -> None:
        """Templates support Jinja2 built-in filters like upper."""
        builder = MailBuilder()
        builder.sender("sender@example.com").to("user@example.com").message(
            "<p>{{ x | upper }}</p>",
            content_type="html",
            placeholders={"x": "hello"},
        )
        html_part = builder.build().get_body("html")
        assert html_part is not None
        assert "<p>HELLO</p>" in html_part.get_content()

    def test_missing_key_renders_empty(self) -> None:
        """ChainableUndefined: missing keys render as empty string (new semantic)."""
        builder = MailBuilder()
        builder.sender("sender@example.com").to("user@example.com").message(
            "<p>before {{ missing }} after</p>",
            content_type="html",
            placeholders={"present": "x"},
        )
        html_part = builder.build().get_body("html")
        assert html_part is not None
        assert "<p>before  after</p>" in html_part.get_content()

    def test_non_scalar_renders_via_str(self) -> None:
        """Non-scalar values render via Python str() (new semantic vs '[object]')."""
        builder = MailBuilder()
        builder.sender("sender@example.com").to("user@example.com").message(
            "<p>{{ items }}</p>",
            content_type="html",
            placeholders={"items": [1, 2, 3]},
        )
        html_part = builder.build().get_body("html")
        assert html_part is not None
        assert "<p>[1, 2, 3]</p>" in html_part.get_content()

    def test_collector_to_context_loop_in_template(self) -> None:
        """A NotifyCollector.to_context() feeds a Jinja2 loop on results."""
        transport = _RecordingTransport()
        mail = _build_for_notify(transport)
        collector = NotifyCollector()

        @mail.notify(collector=collector)
        def ok_fn() -> int:
            return 1

        @mail.notify(collector=collector)
        def ko_fn() -> int:
            raise ValueError("boom")

        ok_fn()
        with pytest.raises(ValueError):
            ko_fn()

        template = (
            "Total: {{ total_count }}; "
            "{% for r in results %}"
            "{{ r.function_name }}={% if r.success %}OK{% else %}KO{% endif %};"
            "{% endfor %}"
        )
        recap = MailBuilder(transport=transport).sender("a@x.com").to("b@x.com").subject("Recap")
        recap.message(content=template, content_type="plain", placeholders=collector.to_context()).send()

        plain_part = transport.sent[-1].get_body("plain")
        assert plain_part is not None
        body = plain_part.get_content()
        assert "Total: 2;" in body
        assert "ok_fn=OK;" in body
        assert "ko_fn=KO;" in body
