"""Plain-text mail composition using :class:`kstlib.mail.MailBuilder`."""

from __future__ import annotations

from kstlib.mail import MailBuilder


def build_plain_message() -> None:
    """Construct a plain-text message and print the RFC822 payload."""
    message = (
        MailBuilder()
        .sender("sender@example.com")
        .to("user@example.com")
        .subject("Plain Greetings")
        .message(
            "Hello from kstlib!\nThis message uses the plain content type.",
            content_type="plain",
        )
        .build()
    )
    print(message.as_string())


if __name__ == "__main__":  # pragma: no cover - manual example
    build_plain_message()
