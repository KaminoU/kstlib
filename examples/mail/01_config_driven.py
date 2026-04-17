"""Config-driven mail sending via :class:`kstlib.mail.MailBuilder`.

Requires a ``kstlib.conf.yml`` with a ``mail.presets`` section. See the
sample configuration block below for supported fields.

Example ``kstlib.conf.yml``::

    mail:
      default: corporate
      presets:
        corporate:
          transport: smtp
          host: smtp.example.com
          port: 587
          login: user@example.com
          password: "secret"
          starttls: true
        transactional:
          transport: resend
          api_key: re_xxxxxxxxxxxxx
          timeout: 30

With the config above, ``MailBuilder()`` resolves the ``corporate`` preset
automatically. Override with ``MailBuilder(preset="transactional")``.
"""

from __future__ import annotations

from kstlib.mail import MailBuilder


def send_via_default_preset() -> None:
    """Build and send a mail using the preset referenced by ``mail.default``."""
    mail = (
        MailBuilder()
        .sender("noreply@example.com")
        .to("recipient@example.com")
        .subject("Hello from kstlib")
        .message("This email was sent via a config-driven transport.")
    )
    result = mail.send()
    print(f"Sent: {result['Subject']}")


def send_via_named_preset() -> None:
    """Build and send a mail using an explicit preset name."""
    mail = (
        MailBuilder(preset="transactional")
        .sender("noreply@example.com")
        .to("recipient@example.com")
        .subject("Transactional notice")
        .message("<p>Sent via Resend.</p>", content_type="html")
    )
    result = mail.send()
    print(f"Sent via Resend: {result['Subject']}")


if __name__ == "__main__":  # pragma: no cover - manual example
    send_via_default_preset()
