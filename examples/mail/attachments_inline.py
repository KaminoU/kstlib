"""Demonstrate attachments and inline resources with :class:`MailBuilder`."""

from __future__ import annotations

from base64 import b64decode
from pathlib import Path
from tempfile import TemporaryDirectory

from kstlib.mail import MailBuilder, MailFilesystemGuards

_LOGO_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9dOAoAAAAASUVORK5CYII="


def build_message_with_attachments() -> None:
    """Create a message that includes an attachment and an inline PNG resource."""
    with TemporaryDirectory() as tmp_dir:
        workdir = Path(tmp_dir)
        guards = MailFilesystemGuards.relaxed_for_testing(workdir)

        report_path = guards.attachments_root / "daily-report.txt"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("Daily metrics: 42 conversions", encoding="utf-8")

        logo_path = guards.inline_root / "logo.png"
        logo_path.parent.mkdir(parents=True, exist_ok=True)
        logo_path.write_bytes(b64decode(_LOGO_BASE64))

        message = (
            MailBuilder(filesystem=guards)
            .sender("sender@example.com")
            .to("ops@example.com")
            .subject("Daily metrics report")
            .message(
                '<p>Please find the report attached.</p><img src="cid:company-logo" alt="logo" />',
                content_type="html",
            )
            .attach(report_path)
            .attach_inline("company-logo", logo_path)
            .build()
        )

        print(message.as_string())


if __name__ == "__main__":  # pragma: no cover - manual example
    build_message_with_attachments()
