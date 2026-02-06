"""Tests for AWS SES transport."""

from __future__ import annotations

from email.message import EmailMessage
from unittest.mock import MagicMock, patch

import pytest

from kstlib.mail.exceptions import MailConfigurationError, MailTransportError
from kstlib.mail.transport import AsyncMailTransport
from kstlib.mail.transports.ses import SesResponse, SesTransport


class TestSesResponse:
    """Tests for SesResponse dataclass."""

    def test_stores_message_id(self) -> None:
        """Response stores the SES message ID."""
        response = SesResponse(message_id="ses_abc123")
        assert response.message_id == "ses_abc123"

    def test_is_frozen(self) -> None:
        """Response is immutable."""
        response = SesResponse(message_id="ses_abc123")
        with pytest.raises(AttributeError):
            response.message_id = "changed"  # type: ignore[misc]


class TestSesTransportInit:
    """Tests for SesTransport initialization."""

    def test_default_region(self) -> None:
        """Default region is eu-west-3."""
        transport = SesTransport()
        assert transport._region == "eu-west-3"

    def test_custom_region(self) -> None:
        """Custom region can be provided."""
        transport = SesTransport(region="us-east-1")
        assert transport._region == "us-east-1"

    def test_empty_region_raises(self) -> None:
        """Empty region raises MailConfigurationError."""
        with pytest.raises(MailConfigurationError, match="region is required"):
            SesTransport(region="")

    def test_default_timeout(self) -> None:
        """Default timeout is 30 seconds."""
        transport = SesTransport()
        assert transport._timeout == 30.0

    def test_custom_timeout(self) -> None:
        """Custom timeout can be provided."""
        transport = SesTransport(timeout=60.0)
        assert transport._timeout == 60.0

    def test_negative_timeout_raises(self) -> None:
        """Negative timeout raises MailConfigurationError."""
        with pytest.raises(MailConfigurationError, match="Timeout must be greater than 0"):
            SesTransport(timeout=-1.0)

    def test_zero_timeout_raises(self) -> None:
        """Zero timeout raises MailConfigurationError."""
        with pytest.raises(MailConfigurationError, match="Timeout must be greater than 0"):
            SesTransport(timeout=0)

    def test_partial_credentials_key_only_raises(self) -> None:
        """Providing only access key raises MailConfigurationError."""
        with pytest.raises(MailConfigurationError, match="must be provided together"):
            SesTransport(aws_access_key_id="AKIA_test")

    def test_partial_credentials_secret_only_raises(self) -> None:
        """Providing only secret key raises MailConfigurationError."""
        with pytest.raises(MailConfigurationError, match="must be provided together"):
            SesTransport(aws_secret_access_key="secret_test")

    def test_both_credentials_accepted(self) -> None:
        """Both credentials together are accepted."""
        transport = SesTransport(
            aws_access_key_id="AKIA_test",
            aws_secret_access_key="secret_test",
        )
        assert transport._aws_access_key_id == "AKIA_test"
        assert transport._aws_secret_access_key == "secret_test"

    def test_no_credentials_accepted(self) -> None:
        """No credentials is valid (uses default chain)."""
        transport = SesTransport()
        assert transport._aws_access_key_id is None
        assert transport._aws_secret_access_key is None

    def test_is_async_transport(self) -> None:
        """SesTransport is an AsyncMailTransport."""
        transport = SesTransport()
        assert isinstance(transport, AsyncMailTransport)

    def test_last_response_initially_none(self) -> None:
        """Last response is None before any send."""
        transport = SesTransport()
        assert transport.last_response is None


def _make_message(
    from_addr: str = "sender@example.com",
    to_addr: str = "recipient@example.com",
    subject: str = "Test Subject",
    body: str = "Plain text body",
) -> EmailMessage:
    """Create a basic EmailMessage for testing."""
    message = EmailMessage()
    message["From"] = from_addr
    message["To"] = to_addr
    message["Subject"] = subject
    message.set_content(body)
    return message


class TestSesTransportSend:
    """Tests for send method."""

    @pytest.mark.asyncio
    async def test_send_success(self) -> None:
        """Successful send stores response with message ID."""
        transport = SesTransport(region="eu-west-3")
        message = _make_message()

        mock_client = MagicMock()
        mock_client.send_raw_email.return_value = {"MessageId": "ses_abc123"}

        with patch.object(transport, "_create_client", return_value=mock_client):
            await transport.send(message)

        assert transport.last_response is not None
        assert transport.last_response.message_id == "ses_abc123"

    @pytest.mark.asyncio
    async def test_send_passes_raw_mime(self) -> None:
        """Send passes raw MIME bytes to SES."""
        transport = SesTransport(region="eu-west-3")
        message = _make_message()
        expected_bytes = message.as_bytes()

        mock_client = MagicMock()
        mock_client.send_raw_email.return_value = {"MessageId": "ses_raw"}

        with patch.object(transport, "_create_client", return_value=mock_client):
            await transport.send(message)

        call_kwargs = mock_client.send_raw_email.call_args.kwargs
        assert call_kwargs["RawMessage"]["Data"] == expected_bytes

    @pytest.mark.asyncio
    async def test_send_html_multipart(self) -> None:
        """HTML multipart message is sent as raw MIME."""
        transport = SesTransport(region="eu-west-3")
        message = _make_message()
        message.add_alternative("<h1>HTML content</h1>", subtype="html")

        mock_client = MagicMock()
        mock_client.send_raw_email.return_value = {"MessageId": "ses_html"}

        with patch.object(transport, "_create_client", return_value=mock_client):
            await transport.send(message)

        assert transport.last_response is not None
        assert transport.last_response.message_id == "ses_html"
        # Verify raw bytes contain the HTML
        call_kwargs = mock_client.send_raw_email.call_args.kwargs
        raw_data = call_kwargs["RawMessage"]["Data"]
        assert b"HTML content" in raw_data

    @pytest.mark.asyncio
    async def test_send_with_attachments(self) -> None:
        """Attachments are preserved in raw MIME."""
        transport = SesTransport(region="eu-west-3")
        message = _make_message()
        message.add_attachment(
            b"file content here",
            maintype="application",
            subtype="octet-stream",
            filename="test.bin",
        )

        mock_client = MagicMock()
        mock_client.send_raw_email.return_value = {"MessageId": "ses_attach"}

        with patch.object(transport, "_create_client", return_value=mock_client):
            await transport.send(message)

        assert transport.last_response is not None
        call_kwargs = mock_client.send_raw_email.call_args.kwargs
        raw_data = call_kwargs["RawMessage"]["Data"]
        assert b"test.bin" in raw_data

    @pytest.mark.asyncio
    async def test_send_stores_last_response(self) -> None:
        """Last response is updated after each send."""
        transport = SesTransport(region="eu-west-3")

        mock_client = MagicMock()
        mock_client.send_raw_email.side_effect = [
            {"MessageId": "first_id"},
            {"MessageId": "second_id"},
        ]

        with patch.object(transport, "_create_client", return_value=mock_client):
            await transport.send(_make_message())
            assert transport.last_response is not None
            assert transport.last_response.message_id == "first_id"

            await transport.send(_make_message())
            assert transport.last_response.message_id == "second_id"

    @pytest.mark.asyncio
    async def test_send_client_error(self) -> None:
        """ClientError raises MailTransportError."""
        from botocore.exceptions import ClientError

        transport = SesTransport(region="eu-west-3")

        mock_client = MagicMock()
        mock_client.send_raw_email.side_effect = ClientError(
            error_response={"Error": {"Code": "MessageRejected", "Message": "Email address not verified"}},
            operation_name="SendRawEmail",
        )

        with patch.object(transport, "_create_client", return_value=mock_client):
            with pytest.raises(MailTransportError, match="Email address not verified"):
                await transport.send(_make_message())

    @pytest.mark.asyncio
    async def test_send_no_credentials(self) -> None:
        """NoCredentialsError raises MailConfigurationError."""
        from botocore.exceptions import NoCredentialsError

        transport = SesTransport(region="eu-west-3")

        mock_client = MagicMock()
        mock_client.send_raw_email.side_effect = NoCredentialsError()

        with patch.object(transport, "_create_client", return_value=mock_client):
            with pytest.raises(MailConfigurationError, match="credentials not found"):
                await transport.send(_make_message())

    @pytest.mark.asyncio
    async def test_send_endpoint_connection_error(self) -> None:
        """EndpointConnectionError raises MailTransportError."""
        from botocore.exceptions import EndpointConnectionError

        transport = SesTransport(region="eu-west-3")

        mock_client = MagicMock()
        mock_client.send_raw_email.side_effect = EndpointConnectionError(
            endpoint_url="https://ses.eu-west-3.amazonaws.com"
        )

        with patch.object(transport, "_create_client", return_value=mock_client):
            with pytest.raises(MailTransportError, match="endpoint connection failed"):
                await transport.send(_make_message())


class TestSesTransportCredentials:
    """Tests for credential handling in client creation."""

    def test_explicit_credentials_passed_to_client(self) -> None:
        """Explicit credentials are forwarded to boto3.client."""
        transport = SesTransport(
            region="us-east-1",
            aws_access_key_id="AKIA_test",
            aws_secret_access_key="secret_test",
        )

        mock_boto3 = MagicMock()
        mock_config_cls = MagicMock()
        transport._create_client(mock_boto3, mock_config_cls)

        call_kwargs = mock_boto3.client.call_args.kwargs
        assert call_kwargs["aws_access_key_id"] == "AKIA_test"
        assert call_kwargs["aws_secret_access_key"] == "secret_test"
        assert call_kwargs["region_name"] == "us-east-1"

    def test_no_credentials_uses_default_chain(self) -> None:
        """Without explicit credentials, boto3 uses its default chain."""
        transport = SesTransport(region="eu-west-3")

        mock_boto3 = MagicMock()
        mock_config_cls = MagicMock()
        transport._create_client(mock_boto3, mock_config_cls)

        call_kwargs = mock_boto3.client.call_args.kwargs
        assert "aws_access_key_id" not in call_kwargs
        assert "aws_secret_access_key" not in call_kwargs
        assert call_kwargs["region_name"] == "eu-west-3"


class TestSesTransportTraceLogging:
    """Tests for TRACE-level logging in SesTransport."""

    @pytest.mark.asyncio
    async def test_send_with_trace_logging_enabled(self) -> None:
        """TRACE logging is emitted when enabled."""
        import logging

        from kstlib.logging import TRACE_LEVEL

        transport = SesTransport(region="eu-west-3")
        message = _make_message()

        mock_client = MagicMock()
        mock_client.send_raw_email.return_value = {"MessageId": "ses_traced"}

        logger = logging.getLogger("kstlib.mail.transports.ses")
        original_level = logger.level
        logger.setLevel(TRACE_LEVEL)

        try:
            with patch.object(transport, "_create_client", return_value=mock_client):
                await transport.send(message)

            assert transport.last_response is not None
            assert transport.last_response.message_id == "ses_traced"
        finally:
            logger.setLevel(original_level)

    @pytest.mark.asyncio
    async def test_send_error_with_trace_logging(self) -> None:
        """TRACE logging for errors when enabled."""
        import logging

        from botocore.exceptions import ClientError

        from kstlib.logging import TRACE_LEVEL

        transport = SesTransport(region="eu-west-3")

        mock_client = MagicMock()
        mock_client.send_raw_email.side_effect = ClientError(
            error_response={"Error": {"Code": "Throttling", "Message": "Rate exceeded"}},
            operation_name="SendRawEmail",
        )

        logger = logging.getLogger("kstlib.mail.transports.ses")
        original_level = logger.level
        logger.setLevel(TRACE_LEVEL)

        try:
            with patch.object(transport, "_create_client", return_value=mock_client):
                with pytest.raises(MailTransportError, match="Rate exceeded"):
                    await transport.send(_make_message())
        finally:
            logger.setLevel(original_level)


class TestBoto3NotInstalled:
    """Tests for missing boto3 dependency."""

    @pytest.mark.asyncio
    async def test_boto3_not_installed_raises(self) -> None:
        """Missing boto3 raises MailConfigurationError."""
        transport = SesTransport(region="eu-west-3")

        with (
            patch.dict(
                "sys.modules", {"boto3": None, "botocore": None, "botocore.config": None, "botocore.exceptions": None}
            ),
            patch(
                "kstlib.mail.transports.ses.SesTransport.send",
                side_effect=MailConfigurationError("boto3 is required for SesTransport"),
            ),
            pytest.raises(MailConfigurationError, match="boto3 is required"),
        ):
            await transport.send(_make_message())
