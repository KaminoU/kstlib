"""Tests for kstlib.monitoring.delivery module."""

from __future__ import annotations

import pathlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from kstlib.monitoring import (
    DeliveryConfigError,
    DeliveryError,
    DeliveryIOError,
    DeliveryResult,
    FileDelivery,
    FileDeliveryConfig,
    MailDelivery,
    MailDeliveryConfig,
    MonitoringResult,
)


@pytest.fixture
def sample_result() -> MonitoringResult:
    """Create a sample MonitoringResult for testing."""
    return MonitoringResult(
        html="<h1>Test Report</h1><p>Content here</p>",
        data={"test": "value"},
        collected_at=datetime.now(timezone.utc),
        rendered_at=datetime.now(timezone.utc),
        errors=[],
    )


@pytest.fixture
def temp_output_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a temporary output directory."""
    output_dir = tmp_path / "reports"
    output_dir.mkdir()
    return output_dir


class TestDeliveryResult:
    """Tests for DeliveryResult dataclass."""

    def test_successful_result(self, tmp_path: pathlib.Path) -> None:
        """Successful result has success=True."""
        result = DeliveryResult(
            success=True,
            timestamp=datetime.now(timezone.utc),
            path=tmp_path / "test.html",
        )
        assert result.success is True
        assert result.path is not None
        assert result.error is None

    def test_failed_result(self) -> None:
        """Failed result has success=False and error message."""
        result = DeliveryResult(
            success=False,
            timestamp=datetime.now(timezone.utc),
            error="Connection failed",
        )
        assert result.success is False
        assert result.error == "Connection failed"

    def test_result_with_metadata(self) -> None:
        """Result can include metadata."""
        result = DeliveryResult(
            success=True,
            timestamp=datetime.now(timezone.utc),
            metadata={"size_bytes": 1024, "files_deleted": 2},
        )
        assert result.metadata["size_bytes"] == 1024


class TestFileDeliveryConfig:
    """Tests for FileDeliveryConfig."""

    def test_default_config(self, temp_output_dir: pathlib.Path) -> None:
        """Default config has sensible values."""
        config = FileDeliveryConfig(output_dir=temp_output_dir)
        assert config.output_dir == temp_output_dir
        assert config.max_files == 100
        assert config.encoding == "utf-8"

    def test_string_path_converted(self, temp_output_dir: pathlib.Path) -> None:
        """String path is converted to Path object."""
        config = FileDeliveryConfig(output_dir=str(temp_output_dir))
        assert isinstance(config.output_dir, pathlib.Path)

    def test_negative_max_files_raises(self, temp_output_dir: pathlib.Path) -> None:
        """Negative max_files raises error."""
        with pytest.raises(DeliveryConfigError) as exc_info:
            FileDeliveryConfig(output_dir=temp_output_dir, max_files=-1)
        assert "negative" in str(exc_info.value).lower()

    def test_max_files_limit_exceeded(self, temp_output_dir: pathlib.Path) -> None:
        """max_files exceeding limit raises error."""
        with pytest.raises(DeliveryConfigError) as exc_info:
            FileDeliveryConfig(output_dir=temp_output_dir, max_files=5000)
        assert "limit" in str(exc_info.value).lower()


class TestFileDelivery:
    """Tests for FileDelivery backend."""

    def test_init_with_path(self, temp_output_dir: pathlib.Path) -> None:
        """Initialize with Path object."""
        delivery = FileDelivery(output_dir=temp_output_dir)
        assert delivery.config.output_dir == temp_output_dir

    def test_init_with_string(self, temp_output_dir: pathlib.Path) -> None:
        """Initialize with string path."""
        delivery = FileDelivery(output_dir=str(temp_output_dir))
        assert isinstance(delivery.config.output_dir, pathlib.Path)

    @pytest.mark.asyncio
    async def test_deliver_creates_file(self, temp_output_dir: pathlib.Path, sample_result: MonitoringResult) -> None:
        """deliver() creates HTML file."""
        delivery = FileDelivery(output_dir=temp_output_dir)
        result = await delivery.deliver(sample_result, "test-report")

        assert result.success is True
        assert result.path is not None
        assert result.path.exists()
        assert result.path.suffix == ".html"
        assert "Test Report" in result.path.read_text()

    @pytest.mark.asyncio
    async def test_deliver_returns_metadata(
        self, temp_output_dir: pathlib.Path, sample_result: MonitoringResult
    ) -> None:
        """deliver() returns metadata in result."""
        delivery = FileDelivery(output_dir=temp_output_dir)
        result = await delivery.deliver(sample_result, "test")

        assert "size_bytes" in result.metadata
        assert result.metadata["size_bytes"] > 0

    @pytest.mark.asyncio
    async def test_deliver_creates_directory(self, tmp_path: pathlib.Path, sample_result: MonitoringResult) -> None:
        """deliver() creates output directory if missing."""
        output_dir = tmp_path / "new" / "nested" / "dir"
        delivery = FileDelivery(output_dir=output_dir, create_dirs=True)
        result = await delivery.deliver(sample_result, "test")

        assert result.success is True
        assert output_dir.is_dir()

    @pytest.mark.asyncio
    async def test_deliver_without_create_dirs_fails(
        self, tmp_path: pathlib.Path, sample_result: MonitoringResult
    ) -> None:
        """deliver() fails if directory missing and create_dirs=False."""
        output_dir = tmp_path / "nonexistent"
        delivery = FileDelivery(output_dir=output_dir, create_dirs=False)

        with pytest.raises(DeliveryConfigError):
            await delivery.deliver(sample_result, "test")

    @pytest.mark.asyncio
    async def test_file_rotation(self, temp_output_dir: pathlib.Path, sample_result: MonitoringResult) -> None:
        """Old files are deleted when max_files exceeded."""
        delivery = FileDelivery(output_dir=temp_output_dir, max_files=3)

        # Create 5 files
        for i in range(5):
            await delivery.deliver(sample_result, f"report-{i}")

        # Should have at most 3 files
        html_files = list(temp_output_dir.glob("*.html"))
        assert len(html_files) <= 3

    @pytest.mark.asyncio
    async def test_last_result_property(self, temp_output_dir: pathlib.Path, sample_result: MonitoringResult) -> None:
        """last_result property returns last delivery result."""
        delivery = FileDelivery(output_dir=temp_output_dir)
        initial = delivery.last_result
        assert initial is None

        result = await delivery.deliver(sample_result, "test")
        after = delivery.last_result
        # last_result should be set to the returned result
        assert after is result and result.success is True

    @pytest.mark.asyncio
    async def test_filename_sanitization(self, temp_output_dir: pathlib.Path, sample_result: MonitoringResult) -> None:
        """Unsafe characters in name are sanitized."""
        delivery = FileDelivery(output_dir=temp_output_dir)
        result = await delivery.deliver(sample_result, "test/with\\bad:chars")

        assert result.success is True
        assert result.path is not None
        # Filename should not contain unsafe chars
        assert "/" not in result.path.name
        assert "\\" not in result.path.name
        assert ":" not in result.path.name


class TestFileDeliveryDeepDefense:
    """Deep defense security tests for FileDelivery."""

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, temp_output_dir: pathlib.Path, sample_result: MonitoringResult) -> None:
        """Path traversal attempts are blocked."""
        delivery = FileDelivery(
            output_dir=temp_output_dir,
            filename_template="../../../etc/{name}_{timestamp}.html",
        )
        # The path validation should catch this
        with pytest.raises((DeliveryConfigError, DeliveryError)):
            await delivery.deliver(sample_result, "passwd")

    @pytest.mark.asyncio
    async def test_large_content_rejected(self, temp_output_dir: pathlib.Path) -> None:
        """Content exceeding max size is rejected."""
        large_html = "<p>" + "x" * (60 * 1024 * 1024) + "</p>"  # > 50MB
        large_result = MonitoringResult(
            html=large_html,
            data={},
            collected_at=datetime.now(timezone.utc),
            rendered_at=datetime.now(timezone.utc),
            errors=[],
        )
        delivery = FileDelivery(output_dir=temp_output_dir)

        with pytest.raises(DeliveryConfigError) as exc_info:
            await delivery.deliver(large_result, "large")
        assert "large" in str(exc_info.value).lower()

    def test_max_files_per_dir_limit(self, temp_output_dir: pathlib.Path) -> None:
        """max_files cannot exceed safety limit."""
        with pytest.raises(DeliveryConfigError):
            FileDelivery(output_dir=temp_output_dir, max_files=2000)


class TestMailDeliveryConfig:
    """Tests for MailDeliveryConfig."""

    def test_valid_config(self) -> None:
        """Valid config is accepted."""
        config = MailDeliveryConfig(
            sender="bot@example.com",
            recipients=["team@example.com"],
        )
        assert config.sender == "bot@example.com"
        assert config.recipients == ["team@example.com"]

    def test_empty_sender_raises(self) -> None:
        """Empty sender raises error."""
        with pytest.raises(DeliveryConfigError) as exc_info:
            MailDeliveryConfig(sender="", recipients=["test@example.com"])
        assert "sender" in str(exc_info.value).lower()

    def test_empty_recipients_raises(self) -> None:
        """Empty recipients raises error."""
        with pytest.raises(DeliveryConfigError) as exc_info:
            MailDeliveryConfig(sender="bot@example.com", recipients=[])
        assert "recipient" in str(exc_info.value).lower()

    def test_too_many_recipients_raises(self) -> None:
        """Too many recipients raises error."""
        recipients = [f"user{i}@example.com" for i in range(60)]
        with pytest.raises(DeliveryConfigError) as exc_info:
            MailDeliveryConfig(sender="bot@example.com", recipients=recipients)
        assert "recipients" in str(exc_info.value).lower()


class TestMailDelivery:
    """Tests for MailDelivery backend."""

    def test_init_with_async_transport(self) -> None:
        """Initialize with async transport."""
        transport = AsyncMock()
        delivery = MailDelivery.create(
            transport=transport,
            sender="bot@example.com",
            recipients=["team@example.com"],
        )
        assert delivery.config.sender == "bot@example.com"

    @pytest.mark.asyncio
    async def test_deliver_calls_transport(self, sample_result: MonitoringResult) -> None:
        """deliver() calls transport.send()."""
        transport = AsyncMock()
        transport.send = AsyncMock()
        delivery = MailDelivery.create(
            transport=transport,
            sender="bot@example.com",
            recipients=["team@example.com"],
        )

        result = await delivery.deliver(sample_result, "Test Report")

        assert result.success is True
        transport.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_deliver_builds_correct_message(self, sample_result: MonitoringResult) -> None:
        """deliver() builds message with correct headers."""
        transport = AsyncMock()
        transport.send = AsyncMock()
        delivery = MailDelivery.create(
            transport=transport,
            sender="bot@example.com",
            recipients=["team@example.com"],
            cc=["cc@example.com"],
            subject_template="Report: {name}",
        )

        await delivery.deliver(sample_result, "Daily")

        # Check the message that was sent
        call_args = transport.send.call_args
        message = call_args[0][0]
        assert message["From"] == "bot@example.com"
        assert "team@example.com" in message["To"]
        assert "cc@example.com" in message["Cc"]
        assert message["Subject"] == "Report: Daily"

    @pytest.mark.asyncio
    async def test_deliver_with_sync_transport(self, sample_result: MonitoringResult) -> None:
        """deliver() works with sync transport."""
        transport = MagicMock()
        transport.send = MagicMock()
        delivery = MailDelivery.create(
            transport=transport,
            sender="bot@example.com",
            recipients=["team@example.com"],
        )

        result = await delivery.deliver(sample_result, "Test")

        assert result.success is True
        transport.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_deliver_failure_raises(self, sample_result: MonitoringResult) -> None:
        """deliver() raises DeliveryError on transport failure."""
        transport = AsyncMock()
        transport.send = AsyncMock(side_effect=Exception("Network error"))
        delivery = MailDelivery.create(
            transport=transport,
            sender="bot@example.com",
            recipients=["team@example.com"],
        )

        with pytest.raises(DeliveryError) as exc_info:
            await delivery.deliver(sample_result, "Test")
        assert "Network error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_last_result_on_failure(self, sample_result: MonitoringResult) -> None:
        """last_result is set even on failure."""
        transport = AsyncMock()
        transport.send = AsyncMock(side_effect=Exception("Error"))
        delivery = MailDelivery.create(
            transport=transport,
            sender="bot@example.com",
            recipients=["team@example.com"],
        )

        with pytest.raises(DeliveryError):
            await delivery.deliver(sample_result, "Test")

        assert delivery.last_result is not None
        assert delivery.last_result.success is False


class TestMailDeliveryDeepDefense:
    """Deep defense security tests for MailDelivery."""

    def test_subject_length_truncated(self) -> None:
        """Long subjects are truncated."""
        transport = MagicMock()
        delivery = MailDelivery.create(
            transport=transport,
            sender="bot@example.com",
            recipients=["team@example.com"],
            subject_template="x" * 300,  # Very long subject
        )
        # Should not raise - subject will be truncated
        message = delivery._build_message("<p>test</p>", "y" * 300)
        assert len(message["Subject"]) <= 203  # 200 + "..."

    def test_recipients_limit_enforced(self) -> None:
        """Too many total recipients (to+cc+bcc) is rejected."""
        recipients = [f"to{i}@example.com" for i in range(20)]
        cc = [f"cc{i}@example.com" for i in range(20)]
        bcc = [f"bcc{i}@example.com" for i in range(20)]

        with pytest.raises(DeliveryConfigError) as exc_info:
            MailDelivery.create(
                transport=MagicMock(),
                sender="bot@example.com",
                recipients=recipients,
                cc=cc,
                bcc=bcc,
            )
        assert "recipients" in str(exc_info.value).lower()

    def test_bcc_header_included(self) -> None:
        """BCC addresses are included in message."""
        transport = MagicMock()
        delivery = MailDelivery.create(
            transport=transport,
            sender="bot@example.com",
            recipients=["team@example.com"],
            bcc=["hidden@example.com"],
        )
        message = delivery._build_message("<p>test</p>", "Test Subject")
        assert "hidden@example.com" in message["Bcc"]

    def test_html_only_message(self) -> None:
        """Message without plain text includes HTML only."""
        transport = MagicMock()
        delivery = MailDelivery.create(
            transport=transport,
            sender="bot@example.com",
            recipients=["team@example.com"],
            include_plain_text=False,
        )
        message = delivery._build_message("<h1>HTML</h1>", "Test")
        # HTML-only message should have html content type
        assert message.get_content_type() == "text/html"


class TestFileDeliveryEdgeCases:
    """Edge case tests for FileDelivery."""

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        __import__("sys").platform == "win32",
        reason="Permission tests unreliable on Windows",
    )
    async def test_deliver_handles_os_error(self, tmp_path: pathlib.Path, sample_result: MonitoringResult) -> None:
        """deliver() handles OSError gracefully."""
        import os
        import stat

        # Create a read-only directory
        output_dir = tmp_path / "readonly"
        output_dir.mkdir()

        delivery = FileDelivery(output_dir=output_dir)

        original_mode = output_dir.stat().st_mode
        try:
            # Remove write permission
            os.chmod(output_dir, stat.S_IRUSR | stat.S_IXUSR)

            with pytest.raises((DeliveryIOError, PermissionError, OSError)):
                await delivery.deliver(sample_result, "test")
        finally:
            # Restore permissions
            os.chmod(output_dir, original_mode)

    @pytest.mark.asyncio
    async def test_filename_too_long(self, temp_output_dir: pathlib.Path, sample_result: MonitoringResult) -> None:
        """Filename exceeding max length raises error."""
        delivery = FileDelivery(
            output_dir=temp_output_dir,
            filename_template="{name}_{timestamp}_" + "x" * 250 + ".html",
        )

        with pytest.raises(DeliveryConfigError, match="too long"):
            await delivery.deliver(sample_result, "test")

    @pytest.mark.asyncio
    async def test_deep_output_dir_path(self, tmp_path: pathlib.Path, sample_result: MonitoringResult) -> None:
        """Output directory with absolute deep path is validated."""
        # Create deeply nested path
        deep_path = tmp_path
        for i in range(20):
            deep_path = deep_path / f"level{i}"

        delivery = FileDelivery(output_dir=deep_path, create_dirs=True)

        with pytest.raises(DeliveryConfigError, match="too deep"):
            await delivery.deliver(sample_result, "test")

    @pytest.mark.asyncio
    async def test_max_files_zero_skips_cleanup(
        self, temp_output_dir: pathlib.Path, sample_result: MonitoringResult
    ) -> None:
        """max_files=0 skips file rotation entirely."""
        delivery = FileDelivery(output_dir=temp_output_dir, max_files=0)

        # Create multiple files
        for i in range(5):
            await delivery.deliver(sample_result, f"report-{i}")

        # All files should remain (no rotation)
        html_files = list(temp_output_dir.glob("*.html"))
        assert len(html_files) == 5

    @pytest.mark.asyncio
    async def test_cleanup_handles_unlink_error(
        self, temp_output_dir: pathlib.Path, sample_result: MonitoringResult
    ) -> None:
        """File cleanup handles OSError gracefully during unlink."""
        from unittest.mock import patch

        delivery = FileDelivery(output_dir=temp_output_dir, max_files=2)

        # Create 3 files
        for i in range(3):
            await delivery.deliver(sample_result, f"report-{i}")

        # Now create a 4th file with unlink mocked to fail
        original_unlink = pathlib.Path.unlink

        def failing_unlink(self: pathlib.Path, *args: object, **kwargs: object) -> None:
            raise OSError("Permission denied")

        with patch.object(pathlib.Path, "unlink", failing_unlink):
            # Should not raise - best effort cleanup
            result = await delivery.deliver(sample_result, "report-final")
            assert result.success is True

    @pytest.mark.asyncio
    async def test_deliver_general_exception(
        self, temp_output_dir: pathlib.Path, sample_result: MonitoringResult
    ) -> None:
        """deliver() handles unexpected exceptions."""
        from unittest.mock import patch

        from kstlib.monitoring.delivery import DeliveryError

        delivery = FileDelivery(output_dir=temp_output_dir)

        # Mock _generate_filename to raise an unexpected exception
        with patch.object(delivery, "_generate_filename", side_effect=RuntimeError("Unexpected error")):
            with pytest.raises(DeliveryError, match="Unexpected error"):
                await delivery.deliver(sample_result, "test")

            # last_result should be set even on failure
            assert delivery.last_result is not None
            assert delivery.last_result.success is False

    @pytest.mark.asyncio
    async def test_deliver_oserror_during_write(
        self, temp_output_dir: pathlib.Path, sample_result: MonitoringResult
    ) -> None:
        """deliver() handles OSError during file write."""
        from unittest.mock import patch

        delivery = FileDelivery(output_dir=temp_output_dir)

        # Mock write_bytes to raise OSError
        with patch.object(pathlib.Path, "write_bytes", side_effect=OSError("Disk full")):
            with pytest.raises(DeliveryIOError, match="Failed to write file"):
                await delivery.deliver(sample_result, "test")

            # last_result should be set even on failure
            assert delivery.last_result is not None
            assert delivery.last_result.success is False
            assert "I/O error" in (delivery.last_result.error or "")


class TestSanitizeFilename:
    """Tests for _sanitize_filename function."""

    def test_sanitize_filename_removes_unsafe_chars(self) -> None:
        """Unsafe characters are replaced with underscores."""
        from datetime import datetime, timezone

        from kstlib.monitoring.delivery import _sanitize_filename

        ts = datetime(2024, 1, 26, 12, 30, 45, tzinfo=timezone.utc)
        result = _sanitize_filename("test/name:with*bad<chars>", ts)

        assert "/" not in result
        assert ":" not in result
        assert "*" not in result
        assert "<" not in result
        assert ">" not in result
        assert result.endswith("_20240126_123045.html")

    def test_sanitize_filename_truncates_long_name(self) -> None:
        """Long names are truncated to 50 characters."""
        from datetime import datetime, timezone

        from kstlib.monitoring.delivery import _sanitize_filename

        ts = datetime(2024, 1, 26, 12, 30, 45, tzinfo=timezone.utc)
        long_name = "a" * 100
        result = _sanitize_filename(long_name, ts)

        # Should be: 50 chars for name + _ + 15 chars timestamp + .html
        assert result == "a" * 50 + "_20240126_123045.html"
