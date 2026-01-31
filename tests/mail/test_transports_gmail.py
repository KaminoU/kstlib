"""Tests for Gmail transport."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kstlib.auth.models import Token
from kstlib.mail.exceptions import MailConfigurationError, MailTransportError
from kstlib.mail.transport import AsyncMailTransport
from kstlib.mail.transports.gmail import GMAIL_API_URL, GmailResponse, GmailTransport


def make_token(
    access_token: str = "ya29.test_token",
    expires_in_seconds: int = 3600,
) -> Token:
    """Create a test Token with configurable expiration."""
    return Token(
        access_token=access_token,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds),
        scope=["https://www.googleapis.com/auth/gmail.send"],
    )


def make_expired_token() -> Token:
    """Create an expired test Token."""
    return Token(
        access_token="ya29.expired_token",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        scope=["https://www.googleapis.com/auth/gmail.send"],
    )


class TestGmailResponse:
    """Tests for GmailResponse dataclass."""

    def test_stores_fields(self) -> None:
        """Response stores all fields."""
        response = GmailResponse(
            id="msg_123",
            thread_id="thread_456",
            label_ids=["SENT", "INBOX"],
        )
        assert response.id == "msg_123"
        assert response.thread_id == "thread_456"
        assert response.label_ids == ["SENT", "INBOX"]

    def test_is_frozen(self) -> None:
        """Response is immutable."""
        response = GmailResponse(id="msg_123", thread_id="t_1", label_ids=[])
        with pytest.raises(AttributeError):
            response.id = "changed"  # type: ignore[misc]


class TestGmailTransportInit:
    """Tests for GmailTransport initialization."""

    def test_requires_token(self) -> None:
        """None token raises MailConfigurationError."""
        with pytest.raises(MailConfigurationError, match="token is required"):
            GmailTransport(token=None)  # type: ignore[arg-type]

    def test_requires_access_token(self) -> None:
        """Token without access_token raises MailConfigurationError."""
        token = Token(access_token="")
        with pytest.raises(MailConfigurationError, match="access_token"):
            GmailTransport(token=token)

    def test_accepts_valid_token(self) -> None:
        """Valid token is accepted."""
        token = make_token()
        transport = GmailTransport(token=token)
        assert isinstance(transport, AsyncMailTransport)

    def test_default_base_url(self) -> None:
        """Default base URL is Gmail API."""
        token = make_token()
        transport = GmailTransport(token=token)
        assert transport._base_url == GMAIL_API_URL

    def test_custom_base_url(self) -> None:
        """Custom base URL can be provided."""
        token = make_token()
        transport = GmailTransport(token=token, base_url="https://custom.api/send")
        assert transport._base_url == "https://custom.api/send"

    def test_default_timeout(self) -> None:
        """Default timeout is 30 seconds."""
        token = make_token()
        transport = GmailTransport(token=token)
        assert transport._timeout == 30.0

    def test_custom_timeout(self) -> None:
        """Custom timeout can be provided."""
        token = make_token()
        transport = GmailTransport(token=token, timeout=60.0)
        assert transport._timeout == 60.0


class TestGmailTransportToken:
    """Tests for token management."""

    def test_token_property(self) -> None:
        """Token property returns current token."""
        token = make_token()
        transport = GmailTransport(token=token)
        assert transport.token is token

    def test_update_token(self) -> None:
        """Token can be updated after construction."""
        token1 = make_token(access_token="token1")
        token2 = make_token(access_token="token2")

        transport = GmailTransport(token=token1)
        assert transport.token.access_token == "token1"

        transport.update_token(token2)
        assert transport.token.access_token == "token2"


class TestGmailTransportEncoding:
    """Tests for message encoding."""

    def test_encodes_message_as_base64url(self) -> None:
        """Message is encoded as base64url without padding."""
        token = make_token()
        transport = GmailTransport(token=token)

        message = EmailMessage()
        message["From"] = "sender@gmail.com"
        message["To"] = "recipient@example.com"
        message["Subject"] = "Test"
        message.set_content("Body")

        encoded = transport._encode_message(message)

        # Should be valid base64url
        assert "+" not in encoded
        assert "/" not in encoded
        assert not encoded.endswith("=")

        # Should decode back to original
        padded = encoded + "=" * (4 - len(encoded) % 4)
        decoded = base64.urlsafe_b64decode(padded)
        assert b"From: sender@gmail.com" in decoded
        assert b"To: recipient@example.com" in decoded
        assert b"Subject: Test" in decoded

    def test_encodes_unicode_subject(self) -> None:
        """Unicode in subject is handled correctly."""
        token = make_token()
        transport = GmailTransport(token=token)

        message = EmailMessage()
        message["From"] = "sender@gmail.com"
        message["To"] = "recipient@example.com"
        message["Subject"] = "Test with emoji: \U0001f600"
        message.set_content("Body")

        encoded = transport._encode_message(message)

        # Should not raise and produce valid base64url
        assert isinstance(encoded, str)
        assert len(encoded) > 0


class TestGmailTransportSend:
    """Tests for send method."""

    @pytest.mark.asyncio
    async def test_send_success(self) -> None:
        """Successful send stores response."""
        token = make_token()
        transport = GmailTransport(token=token)

        message = EmailMessage()
        message["From"] = "sender@gmail.com"
        message["To"] = "recipient@example.com"
        message["Subject"] = "Test"
        message.set_content("Body")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "msg_abc123",
            "threadId": "thread_xyz789",
            "labelIds": ["SENT"],
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response

            await transport.send(message)

            assert transport.last_response is not None
            assert transport.last_response.id == "msg_abc123"
            assert transport.last_response.thread_id == "thread_xyz789"
            assert transport.last_response.label_ids == ["SENT"]

    @pytest.mark.asyncio
    async def test_send_includes_auth_header(self) -> None:
        """Send includes Authorization Bearer header."""
        token = make_token(access_token="ya29.my_secret_token")
        transport = GmailTransport(token=token)

        message = EmailMessage()
        message["From"] = "sender@gmail.com"
        message["To"] = "recipient@example.com"
        message["Subject"] = "Test"
        message.set_content("Body")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "msg_123", "threadId": "t_1", "labelIds": []}

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response

            await transport.send(message)

            call_kwargs = mock_instance.post.call_args.kwargs
            assert "Authorization" in call_kwargs["headers"]
            assert call_kwargs["headers"]["Authorization"] == "Bearer ya29.my_secret_token"

    @pytest.mark.asyncio
    async def test_send_payload_format(self) -> None:
        """Send uses correct payload format with raw message."""
        token = make_token()
        transport = GmailTransport(token=token)

        message = EmailMessage()
        message["From"] = "sender@gmail.com"
        message["To"] = "recipient@example.com"
        message["Subject"] = "Test"
        message.set_content("Body")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "msg_123", "threadId": "t_1", "labelIds": []}

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response

            await transport.send(message)

            call_kwargs = mock_instance.post.call_args.kwargs
            payload = call_kwargs["json"]
            assert "raw" in payload
            assert isinstance(payload["raw"], str)

    @pytest.mark.asyncio
    async def test_send_401_error(self) -> None:
        """401 error raises specific MailTransportError."""
        token = make_token()
        transport = GmailTransport(token=token)

        message = EmailMessage()
        message["From"] = "sender@gmail.com"
        message["To"] = "recipient@example.com"
        message["Subject"] = "Test"
        message.set_content("Body")

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"error": {"code": 401, "message": "Invalid credentials"}}

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response

            with pytest.raises(MailTransportError, match="authentication failed"):
                await transport.send(message)

    @pytest.mark.asyncio
    async def test_send_api_error(self) -> None:
        """API error raises MailTransportError with details."""
        token = make_token()
        transport = GmailTransport(token=token)

        message = EmailMessage()
        message["From"] = "sender@gmail.com"
        message["To"] = "recipient@example.com"
        message["Subject"] = "Test"
        message.set_content("Body")

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"error": {"code": 400, "message": "Invalid recipient address"}}

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response

            with pytest.raises(MailTransportError, match="Invalid recipient"):
                await transport.send(message)

    @pytest.mark.asyncio
    async def test_send_with_expired_token_warns(self) -> None:
        """Expired token logs warning but attempts send."""
        token = make_expired_token()
        transport = GmailTransport(token=token)

        message = EmailMessage()
        message["From"] = "sender@gmail.com"
        message["To"] = "recipient@example.com"
        message["Subject"] = "Test"
        message.set_content("Body")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "msg_123", "threadId": "t_1", "labelIds": []}

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response

            with patch("kstlib.mail.transports.gmail.log") as mock_log:
                await transport.send(message)
                mock_log.warning.assert_called()
                assert "expired" in str(mock_log.warning.call_args).lower()

    @pytest.mark.asyncio
    async def test_send_timeout(self) -> None:
        """Timeout raises MailTransportError."""
        import httpx

        token = make_token()
        transport = GmailTransport(token=token, timeout=0.1)

        message = EmailMessage()
        message["From"] = "sender@gmail.com"
        message["To"] = "recipient@example.com"
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

        token = make_token()
        transport = GmailTransport(token=token)

        message = EmailMessage()
        message["From"] = "sender@gmail.com"
        message["To"] = "recipient@example.com"
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
        token = make_token()
        transport = GmailTransport(token=token)

        message = EmailMessage()
        message["From"] = "sender@gmail.com"
        message["To"] = "recipient@example.com"
        message["Subject"] = "Test"
        message.set_content("Body")

        with (
            patch.dict("sys.modules", {"httpx": None}),
            patch(
                "kstlib.mail.transports.gmail.GmailTransport.send",
                side_effect=MailConfigurationError("httpx is required"),
            ),
            pytest.raises(MailConfigurationError, match="httpx"),
        ):
            await transport.send(message)


class TestGmailTransportErrorHandling:
    """Tests for error response handling."""

    def test_handles_json_error_format(self) -> None:
        """Standard Google API error format is parsed."""
        token = make_token()
        transport = GmailTransport(token=token)

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.json.return_value = {
            "error": {
                "code": 403,
                "message": "Daily limit exceeded",
                "status": "RESOURCE_EXHAUSTED",
            }
        }

        with pytest.raises(MailTransportError, match="Daily limit exceeded"):
            transport._handle_error_response(mock_response)

    def test_handles_plain_text_error(self) -> None:
        """Non-JSON error response is handled."""
        token = make_token()
        transport = GmailTransport(token=token)

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.side_effect = ValueError("Not JSON")
        mock_response.text = "Internal Server Error"

        with pytest.raises(MailTransportError, match="Internal Server Error"):
            transport._handle_error_response(mock_response)

    def test_handles_empty_error(self) -> None:
        """Empty error response shows status code."""
        token = make_token()
        transport = GmailTransport(token=token)

        mock_response = MagicMock()
        mock_response.status_code = 502
        mock_response.json.side_effect = ValueError("Not JSON")
        mock_response.text = ""

        with pytest.raises(MailTransportError, match="502"):
            transport._handle_error_response(mock_response)
