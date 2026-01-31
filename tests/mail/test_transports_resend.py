"""Tests for Resend transport."""

from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kstlib.mail.exceptions import MailConfigurationError, MailTransportError
from kstlib.mail.transport import AsyncMailTransport
from kstlib.mail.transports.resend import RESEND_API_URL, ResendResponse, ResendTransport

if TYPE_CHECKING:
    pass


class TestResendResponse:
    """Tests for ResendResponse dataclass."""

    def test_stores_id(self) -> None:
        """Response stores the email ID."""
        response = ResendResponse(id="email_123")
        assert response.id == "email_123"

    def test_is_frozen(self) -> None:
        """Response is immutable."""
        response = ResendResponse(id="email_123")
        with pytest.raises(AttributeError):
            response.id = "changed"  # type: ignore[misc]


class TestResendTransportInit:
    """Tests for ResendTransport initialization."""

    def test_requires_api_key(self) -> None:
        """Empty API key raises MailConfigurationError."""
        with pytest.raises(MailConfigurationError, match="API key is required"):
            ResendTransport(api_key="")

    def test_accepts_valid_api_key(self) -> None:
        """Valid API key is accepted."""
        transport = ResendTransport(api_key="re_123456789")
        assert isinstance(transport, AsyncMailTransport)

    def test_default_base_url(self) -> None:
        """Default base URL is Resend API."""
        transport = ResendTransport(api_key="re_123")
        assert transport._base_url == RESEND_API_URL

    def test_custom_base_url(self) -> None:
        """Custom base URL can be provided."""
        transport = ResendTransport(api_key="re_123", base_url="https://custom.api/emails")
        assert transport._base_url == "https://custom.api/emails"

    def test_default_timeout(self) -> None:
        """Default timeout is 30 seconds."""
        transport = ResendTransport(api_key="re_123")
        assert transport._timeout == 30.0

    def test_custom_timeout(self) -> None:
        """Custom timeout can be provided."""
        transport = ResendTransport(api_key="re_123", timeout=60.0)
        assert transport._timeout == 60.0


class TestResendTransportPayload:
    """Tests for payload building."""

    def test_basic_payload(self) -> None:
        """Basic email produces correct payload."""
        transport = ResendTransport(api_key="re_123")

        message = EmailMessage()
        message["From"] = "sender@example.com"
        message["To"] = "recipient@example.com"
        message["Subject"] = "Test Subject"
        message.set_content("Plain text body")

        payload = transport._build_payload(message)

        assert payload["from"] == "sender@example.com"
        assert payload["to"] == ["recipient@example.com"]
        assert payload["subject"] == "Test Subject"
        assert payload["text"] == "Plain text body"

    def test_multiple_recipients(self) -> None:
        """Multiple To addresses are parsed correctly."""
        transport = ResendTransport(api_key="re_123")

        message = EmailMessage()
        message["From"] = "sender@example.com"
        message["To"] = "a@example.com, b@example.com, c@example.com"
        message["Subject"] = "Test"
        message.set_content("Body")

        payload = transport._build_payload(message)

        assert payload["to"] == ["a@example.com", "b@example.com", "c@example.com"]

    def test_cc_recipients(self) -> None:
        """CC addresses are included in payload."""
        transport = ResendTransport(api_key="re_123")

        message = EmailMessage()
        message["From"] = "sender@example.com"
        message["To"] = "to@example.com"
        message["Cc"] = "cc1@example.com, cc2@example.com"
        message["Subject"] = "Test"
        message.set_content("Body")

        payload = transport._build_payload(message)

        assert payload["cc"] == ["cc1@example.com", "cc2@example.com"]

    def test_bcc_recipients(self) -> None:
        """BCC addresses are included in payload."""
        transport = ResendTransport(api_key="re_123")

        message = EmailMessage()
        message["From"] = "sender@example.com"
        message["To"] = "to@example.com"
        message["Bcc"] = "bcc@example.com"
        message["Subject"] = "Test"
        message.set_content("Body")

        payload = transport._build_payload(message)

        assert payload["bcc"] == ["bcc@example.com"]

    def test_reply_to(self) -> None:
        """Reply-To is included in payload."""
        transport = ResendTransport(api_key="re_123")

        message = EmailMessage()
        message["From"] = "sender@example.com"
        message["To"] = "to@example.com"
        message["Reply-To"] = "reply@example.com"
        message["Subject"] = "Test"
        message.set_content("Body")

        payload = transport._build_payload(message)

        assert payload["reply_to"] == "reply@example.com"

    def test_html_body(self) -> None:
        """HTML body is extracted correctly."""
        transport = ResendTransport(api_key="re_123")

        message = EmailMessage()
        message["From"] = "sender@example.com"
        message["To"] = "to@example.com"
        message["Subject"] = "Test"
        message.set_content("Plain text")
        message.add_alternative("<h1>HTML</h1>", subtype="html")

        payload = transport._build_payload(message)

        assert payload["text"] == "Plain text"
        assert payload["html"] == "<h1>HTML</h1>"

    def test_html_only_simple_message(self) -> None:
        """Simple HTML-only message (non-multipart) is handled."""
        transport = ResendTransport(api_key="re_123")

        message = EmailMessage()
        message["From"] = "sender@example.com"
        message["To"] = "to@example.com"
        message["Subject"] = "Test"
        message.set_content("<h1>Only HTML</h1>", subtype="html")

        payload = transport._build_payload(message)

        assert "html" in payload
        assert payload["html"] == "<h1>Only HTML</h1>"
        assert "text" not in payload

    def test_missing_from_raises(self) -> None:
        """Missing From address raises MailConfigurationError."""
        transport = ResendTransport(api_key="re_123")

        message = EmailMessage()
        message["To"] = "to@example.com"
        message["Subject"] = "Test"
        message.set_content("Body")

        with pytest.raises(MailConfigurationError, match="From address"):
            transport._build_payload(message)

    def test_missing_to_raises(self) -> None:
        """Missing To address raises MailConfigurationError."""
        transport = ResendTransport(api_key="re_123")

        message = EmailMessage()
        message["From"] = "sender@example.com"
        message["Subject"] = "Test"
        message.set_content("Body")

        with pytest.raises(MailConfigurationError, match="To address"):
            transport._build_payload(message)


class TestResendTransportAttachments:
    """Tests for attachment handling."""

    def test_extracts_attachment(self) -> None:
        """Attachments are extracted and base64 encoded."""
        transport = ResendTransport(api_key="re_123")

        message = EmailMessage()
        message["From"] = "sender@example.com"
        message["To"] = "to@example.com"
        message["Subject"] = "Test"
        message.set_content("Body")
        message.add_attachment(
            b"file content here",
            maintype="application",
            subtype="octet-stream",
            filename="test.bin",
        )

        payload = transport._build_payload(message)

        assert "attachments" in payload
        assert len(payload["attachments"]) == 1
        assert payload["attachments"][0]["filename"] == "test.bin"
        expected_content = base64.b64encode(b"file content here").decode("ascii")
        assert payload["attachments"][0]["content"] == expected_content

    def test_multiple_attachments(self) -> None:
        """Multiple attachments are all extracted."""
        transport = ResendTransport(api_key="re_123")

        message = EmailMessage()
        message["From"] = "sender@example.com"
        message["To"] = "to@example.com"
        message["Subject"] = "Test"
        message.set_content("Body")
        message.add_attachment(b"file1", maintype="application", subtype="octet-stream", filename="a.txt")
        message.add_attachment(b"file2", maintype="application", subtype="octet-stream", filename="b.txt")

        payload = transport._build_payload(message)

        assert len(payload["attachments"]) == 2
        filenames = [a["filename"] for a in payload["attachments"]]
        assert "a.txt" in filenames
        assert "b.txt" in filenames


class TestResendTransportSend:
    """Tests for send method."""

    @pytest.mark.asyncio
    async def test_send_success(self) -> None:
        """Successful send stores response."""
        transport = ResendTransport(api_key="re_123")

        message = EmailMessage()
        message["From"] = "sender@example.com"
        message["To"] = "to@example.com"
        message["Subject"] = "Test"
        message.set_content("Body")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "email_abc123"}

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response

            await transport.send(message)

            assert transport.last_response is not None
            assert transport.last_response.id == "email_abc123"

    @pytest.mark.asyncio
    async def test_send_includes_auth_header(self) -> None:
        """Send includes Authorization header."""
        transport = ResendTransport(api_key="re_my_secret_key")

        message = EmailMessage()
        message["From"] = "sender@example.com"
        message["To"] = "to@example.com"
        message["Subject"] = "Test"
        message.set_content("Body")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "email_123"}

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response

            await transport.send(message)

            call_kwargs = mock_instance.post.call_args.kwargs
            assert "Authorization" in call_kwargs["headers"]
            assert call_kwargs["headers"]["Authorization"] == "Bearer re_my_secret_key"

    @pytest.mark.asyncio
    async def test_send_api_error(self) -> None:
        """API error raises MailTransportError."""
        transport = ResendTransport(api_key="re_123")

        message = EmailMessage()
        message["From"] = "sender@example.com"
        message["To"] = "to@example.com"
        message["Subject"] = "Test"
        message.set_content("Body")

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"message": "Invalid API key"}

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response

            with pytest.raises(MailTransportError, match="Invalid API key"):
                await transport.send(message)

    @pytest.mark.asyncio
    async def test_send_timeout(self) -> None:
        """Timeout raises MailTransportError."""
        import httpx

        transport = ResendTransport(api_key="re_123", timeout=0.1)

        message = EmailMessage()
        message["From"] = "sender@example.com"
        message["To"] = "to@example.com"
        message["Subject"] = "Test"
        message.set_content("Body")

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.side_effect = httpx.TimeoutException("timeout")

            with pytest.raises(MailTransportError, match="timeout"):
                await transport.send(message)

    @pytest.mark.asyncio
    async def test_send_network_error(self) -> None:
        """Network error raises MailTransportError."""
        import httpx

        transport = ResendTransport(api_key="re_123")

        message = EmailMessage()
        message["From"] = "sender@example.com"
        message["To"] = "to@example.com"
        message["Subject"] = "Test"
        message.set_content("Body")

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.side_effect = httpx.ConnectError("connection failed")

            with pytest.raises(MailTransportError, match="request failed"):
                await transport.send(message)

    @pytest.mark.asyncio
    async def test_httpx_not_installed(self) -> None:
        """Missing httpx raises MailConfigurationError."""
        transport = ResendTransport(api_key="re_123")

        message = EmailMessage()
        message["From"] = "sender@example.com"
        message["To"] = "to@example.com"
        message["Subject"] = "Test"
        message.set_content("Body")

        # Force ImportError by patching the import inside send
        with (
            patch.dict("sys.modules", {"httpx": None}),
            patch(
                "kstlib.mail.transports.resend.ResendTransport.send",
                side_effect=MailConfigurationError("httpx is required"),
            ),
            pytest.raises(MailConfigurationError, match="httpx"),
        ):
            await transport.send(message)


class TestResendTransportTraceLogging:
    """Tests for TRACE-level logging in ResendTransport."""

    @pytest.mark.asyncio
    async def test_send_with_trace_logging_enabled(self) -> None:
        """TRACE logging is emitted when enabled."""
        import logging

        from kstlib.logging import TRACE_LEVEL

        transport = ResendTransport(api_key="re_123")

        message = EmailMessage()
        message["From"] = "sender@example.com"
        message["To"] = "to@example.com"
        message["Subject"] = "Test"
        message.set_content("Body")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "email_traced"}

        # Enable TRACE logging on the resend logger
        logger = logging.getLogger("kstlib.mail.transports.resend")
        original_level = logger.level
        logger.setLevel(TRACE_LEVEL)

        try:
            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_client.return_value.__aenter__.return_value = mock_instance
                mock_instance.post.return_value = mock_response

                await transport.send(message)

                assert transport.last_response is not None
                assert transport.last_response.id == "email_traced"
        finally:
            logger.setLevel(original_level)

    @pytest.mark.asyncio
    async def test_send_timeout_with_trace_logging(self) -> None:
        """TRACE logging for timeout errors when enabled."""
        import logging

        import httpx

        from kstlib.logging import TRACE_LEVEL

        transport = ResendTransport(api_key="re_123", timeout=0.1)

        message = EmailMessage()
        message["From"] = "sender@example.com"
        message["To"] = "to@example.com"
        message["Subject"] = "Test"
        message.set_content("Body")

        logger = logging.getLogger("kstlib.mail.transports.resend")
        original_level = logger.level
        logger.setLevel(TRACE_LEVEL)

        try:
            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_client.return_value.__aenter__.return_value = mock_instance
                mock_instance.post.side_effect = httpx.TimeoutException("timeout")

                with pytest.raises(MailTransportError, match="timeout"):
                    await transport.send(message)
        finally:
            logger.setLevel(original_level)

    @pytest.mark.asyncio
    async def test_send_request_error_with_trace_logging(self) -> None:
        """TRACE logging for request errors when enabled."""
        import logging

        import httpx

        from kstlib.logging import TRACE_LEVEL

        transport = ResendTransport(api_key="re_123")

        message = EmailMessage()
        message["From"] = "sender@example.com"
        message["To"] = "to@example.com"
        message["Subject"] = "Test"
        message.set_content("Body")

        logger = logging.getLogger("kstlib.mail.transports.resend")
        original_level = logger.level
        logger.setLevel(TRACE_LEVEL)

        try:
            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_client.return_value.__aenter__.return_value = mock_instance
                mock_instance.post.side_effect = httpx.ConnectError("connection failed")

                with pytest.raises(MailTransportError, match="request failed"):
                    await transport.send(message)
        finally:
            logger.setLevel(original_level)
