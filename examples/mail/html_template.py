"""Render an HTML mail from a reusable template file."""

from __future__ import annotations

from pathlib import Path

from kstlib.mail import MailBuilder

TEMPLATE_PATH = Path(__file__).with_name("templates").joinpath("newsletter.html")


def build_html_message() -> None:
    """Populate the HTML template with placeholders and dump the MIME payload."""
    message = (
        MailBuilder()
        .sender("sender@example.com")
        .to("subscriber@example.com")
        .subject("Monthly Update")
        .message(
            template=TEMPLATE_PATH,
            placeholders={
                "subject": "kstlib Monthly Update",
                "headline": "A brand new mail builder",
                "body_text": "This edition demonstrates HTML templating with placeholders.",
                "signature": "The kstlib Team",
            },
        )
        .build()
    )
    print(message.as_string())


if __name__ == "__main__":  # pragma: no cover - manual example
    build_html_message()
