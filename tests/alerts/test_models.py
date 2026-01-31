"""Tests for kstlib.alerts.models module."""

import pytest

from kstlib.alerts.models import AlertLevel, AlertMessage, AlertResult


class TestAlertLevel:
    """Tests for AlertLevel enum."""

    def test_info_value(self) -> None:
        """AlertLevel.INFO should have value 10."""
        assert int(AlertLevel.INFO) == 10

    def test_warning_value(self) -> None:
        """AlertLevel.WARNING should have value 20."""
        assert int(AlertLevel.WARNING) == 20

    def test_critical_value(self) -> None:
        """AlertLevel.CRITICAL should have value 30."""
        assert int(AlertLevel.CRITICAL) == 30

    def test_ordering(self) -> None:
        """Alert levels should be ordered by severity."""
        assert AlertLevel.INFO < AlertLevel.WARNING
        assert AlertLevel.WARNING < AlertLevel.CRITICAL
        assert AlertLevel.INFO < AlertLevel.CRITICAL

    def test_name(self) -> None:
        """Alert levels should have correct names."""
        assert AlertLevel.INFO.name == "INFO"
        assert AlertLevel.WARNING.name == "WARNING"
        assert AlertLevel.CRITICAL.name == "CRITICAL"

    def test_is_int_enum(self) -> None:
        """AlertLevel should be usable as int."""
        assert int(AlertLevel.INFO) == 10
        assert int(AlertLevel.WARNING) == 20
        assert int(AlertLevel.CRITICAL) == 30


class TestAlertMessage:
    """Tests for AlertMessage dataclass."""

    def test_basic_creation(self) -> None:
        """AlertMessage should be created with title and body."""
        msg = AlertMessage(title="Test", body="Test body")
        assert msg.title == "Test"
        assert msg.body == "Test body"

    def test_default_level(self) -> None:
        """AlertMessage should default to INFO level."""
        msg = AlertMessage(title="Test", body="Body")
        assert msg.level == AlertLevel.INFO

    def test_custom_level(self) -> None:
        """AlertMessage should accept custom level."""
        msg = AlertMessage(
            title="Critical",
            body="Something broke",
            level=AlertLevel.CRITICAL,
        )
        assert msg.level == AlertLevel.CRITICAL

    def test_frozen(self) -> None:
        """AlertMessage should be immutable."""
        msg = AlertMessage(title="Test", body="Body")
        with pytest.raises(AttributeError):
            msg.title = "Changed"  # type: ignore[misc]

    def test_slots(self) -> None:
        """AlertMessage should use slots."""
        # Verify __slots__ is defined (dataclass with slots=True)
        assert hasattr(AlertMessage, "__slots__")

    def test_equality(self) -> None:
        """AlertMessage with same values should be equal."""
        msg1 = AlertMessage(title="Test", body="Body", level=AlertLevel.INFO)
        msg2 = AlertMessage(title="Test", body="Body", level=AlertLevel.INFO)
        assert msg1 == msg2

    def test_inequality(self) -> None:
        """AlertMessage with different values should not be equal."""
        msg1 = AlertMessage(title="Test1", body="Body")
        msg2 = AlertMessage(title="Test2", body="Body")
        assert msg1 != msg2

    def test_hash(self) -> None:
        """AlertMessage should be hashable."""
        msg = AlertMessage(title="Test", body="Body")
        assert hash(msg) is not None
        # Same message should have same hash
        msg2 = AlertMessage(title="Test", body="Body")
        assert hash(msg) == hash(msg2)


class TestAlertResult:
    """Tests for AlertResult dataclass."""

    def test_success_result(self) -> None:
        """AlertResult should store success status."""
        result = AlertResult(channel="slack", success=True)
        assert result.channel == "slack"
        assert result.success is True

    def test_failure_result(self) -> None:
        """AlertResult should store failure status."""
        result = AlertResult(channel="email", success=False)
        assert result.success is False

    def test_message_id(self) -> None:
        """AlertResult should accept message_id."""
        result = AlertResult(channel="slack", success=True, message_id="msg123")
        assert result.message_id == "msg123"

    def test_error_message(self) -> None:
        """AlertResult should accept error message."""
        result = AlertResult(
            channel="email",
            success=False,
            error="SMTP timeout",
        )
        assert result.error == "SMTP timeout"

    def test_defaults(self) -> None:
        """AlertResult optional fields should default to None."""
        result = AlertResult(channel="slack", success=True)
        assert result.message_id is None
        assert result.error is None

    def test_frozen(self) -> None:
        """AlertResult should be immutable."""
        result = AlertResult(channel="slack", success=True)
        with pytest.raises(AttributeError):
            result.success = False  # type: ignore[misc]

    def test_slots(self) -> None:
        """AlertResult should use slots."""
        # Verify __slots__ is defined (dataclass with slots=True)
        assert hasattr(AlertResult, "__slots__")

    def test_equality(self) -> None:
        """AlertResult with same values should be equal."""
        r1 = AlertResult(channel="slack", success=True, message_id="123")
        r2 = AlertResult(channel="slack", success=True, message_id="123")
        assert r1 == r2

    def test_hash(self) -> None:
        """AlertResult should be hashable."""
        result = AlertResult(channel="slack", success=True)
        assert hash(result) is not None
