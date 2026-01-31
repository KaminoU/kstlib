"""Unit tests for auth module data models."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from kstlib.auth.models import (
    AuthFlow,
    PreflightReport,
    PreflightResult,
    PreflightStatus,
    Token,
    TokenType,
)


class TestToken:
    """Tests for Token dataclass."""

    def test_token_creation(self):
        """Test basic token creation."""
        token = Token(
            access_token="abc123",
            token_type=TokenType.BEARER,
            scope=["openid"],
        )
        assert token.access_token == "abc123"
        assert token.token_type == TokenType.BEARER
        assert token.scope == ["openid"]
        assert token.refresh_token is None
        assert token.id_token is None

    def test_token_is_expired_with_future_expiry(self):
        """Test token is not expired when expires_at is in the future."""
        token = Token(
            access_token="abc",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        assert token.is_expired is False

    def test_token_is_expired_with_past_expiry(self):
        """Test token is expired when expires_at is in the past."""
        token = Token(
            access_token="abc",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        assert token.is_expired is True

    def test_token_is_expired_without_expiry_recent(self):
        """Test token without expiry is not expired if recently issued."""
        token = Token(
            access_token="abc",
            expires_at=None,
            issued_at=datetime.now(timezone.utc),
        )
        assert token.is_expired is False

    def test_token_is_expired_without_expiry_old(self):
        """Test token without expiry is expired if issued long ago."""
        token = Token(
            access_token="abc",
            expires_at=None,
            issued_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        assert token.is_expired is True

    def test_token_is_refreshable(self):
        """Test token is refreshable when refresh_token is present."""
        token = Token(access_token="abc", refresh_token="xyz")
        assert token.is_refreshable is True

        token_no_refresh = Token(access_token="abc")
        assert token_no_refresh.is_refreshable is False

    def test_token_expires_in(self):
        """Test expires_in property."""
        token = Token(
            access_token="abc",
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=3600),
        )
        # Allow some tolerance for test execution time
        assert 3590 < token.expires_in < 3610

        token_no_expiry = Token(access_token="abc")
        assert token_no_expiry.expires_in is None

    def test_token_should_refresh(self):
        """Test should_refresh property."""
        # Token expiring in 30 seconds - should refresh
        token_soon = Token(
            access_token="abc",
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        )
        assert token_soon.should_refresh is True

        # Token expiring in 2 hours - should not refresh
        token_later = Token(
            access_token="abc",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
        )
        assert token_later.should_refresh is False

    def test_token_should_refresh_without_expires_at(self):
        """Test should_refresh falls back to is_expired when expires_at is None."""
        # Token without expires_at but recently issued - should not refresh
        token_recent = Token(
            access_token="abc",
            expires_at=None,
            issued_at=datetime.now(timezone.utc),
        )
        assert token_recent.should_refresh is False

        # Token without expires_at and old - should refresh
        token_old = Token(
            access_token="abc",
            expires_at=None,
            issued_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        assert token_old.should_refresh is True

    def test_token_from_response(self):
        """Test Token.from_response() parsing."""
        response = {
            "access_token": "access123",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "refresh456",
            "scope": "openid profile email",
            "id_token": "id789",
            "custom_field": "extra",
        }
        token = Token.from_response(response)

        assert token.access_token == "access123"
        assert token.refresh_token == "refresh456"
        assert token.scope == ["openid", "profile", "email"]
        assert token.id_token == "id789"
        assert token.metadata == {"custom_field": "extra"}
        assert token.expires_at is not None

    def test_token_from_response_list_scope(self):
        """Test Token.from_response() with scope as list."""
        response = {
            "access_token": "abc",
            "scope": ["openid", "profile"],
        }
        token = Token.from_response(response)
        assert token.scope == ["openid", "profile"]

    def test_token_from_response_with_expires_at_timestamp(self):
        """Test Token.from_response() with absolute expires_at timestamp."""
        # Some servers return absolute timestamp instead of expires_in
        future_timestamp = (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()
        response = {
            "access_token": "abc",
            "expires_at": int(future_timestamp),
        }
        token = Token.from_response(response)
        assert token.expires_at is not None
        assert not token.is_expired

    def test_token_serialization_roundtrip(self, sample_token):
        """Test token serialization and deserialization."""
        data = sample_token.to_dict()
        restored = Token.from_dict(data)

        assert restored.access_token == sample_token.access_token
        assert restored.refresh_token == sample_token.refresh_token
        assert restored.scope == sample_token.scope
        assert restored.id_token == sample_token.id_token


class TestAuthFlow:
    """Tests for AuthFlow enum."""

    def test_auth_flow_values(self):
        """Test AuthFlow enum values."""
        assert AuthFlow.AUTHORIZATION_CODE.value == "authorization_code"
        assert AuthFlow.AUTHORIZATION_CODE_PKCE.value == "authorization_code_pkce"
        assert AuthFlow.CLIENT_CREDENTIALS.value == "client_credentials"
        assert AuthFlow.DEVICE_CODE.value == "device_code"

    def test_auth_flow_is_string_enum(self):
        """Test AuthFlow can be used as string."""
        assert str(AuthFlow.AUTHORIZATION_CODE) == "AuthFlow.AUTHORIZATION_CODE"
        assert AuthFlow.AUTHORIZATION_CODE == "authorization_code"


class TestPreflightResult:
    """Tests for PreflightResult dataclass."""

    def test_preflight_result_success(self):
        """Test successful preflight result."""
        result = PreflightResult(
            step="discovery",
            status=PreflightStatus.SUCCESS,
            message="Discovery successful",
            duration_ms=150,
        )
        assert result.success is True
        assert result.failed is False

    def test_preflight_result_failure(self):
        """Test failed preflight result."""
        result = PreflightResult(
            step="token_endpoint",
            status=PreflightStatus.FAILURE,
            message="Connection refused",
        )
        assert result.success is False
        assert result.failed is True

    def test_preflight_result_warning_is_success(self):
        """Test warning status counts as success."""
        result = PreflightResult(
            step="scopes",
            status=PreflightStatus.WARNING,
            message="Some scopes may not be supported",
        )
        assert result.success is True
        assert result.failed is False


class TestPreflightReport:
    """Tests for PreflightReport dataclass."""

    def test_preflight_report_all_success(self):
        """Test report with all successful steps."""
        report = PreflightReport(provider_name="test")
        report.results = [
            PreflightResult("step1", PreflightStatus.SUCCESS, "OK"),
            PreflightResult("step2", PreflightStatus.SUCCESS, "OK"),
        ]
        assert report.success is True
        assert report.failed_steps == []

    def test_preflight_report_with_failure(self):
        """Test report with a failed step."""
        report = PreflightReport(provider_name="test")
        report.results = [
            PreflightResult("step1", PreflightStatus.SUCCESS, "OK"),
            PreflightResult("step2", PreflightStatus.FAILURE, "Failed"),
        ]
        assert report.success is False
        assert len(report.failed_steps) == 1
        assert report.failed_steps[0].step == "step2"

    def test_preflight_report_total_duration(self):
        """Test total duration calculation."""
        report = PreflightReport(provider_name="test")
        report.results = [
            PreflightResult("step1", PreflightStatus.SUCCESS, "OK", duration_ms=100),
            PreflightResult("step2", PreflightStatus.SUCCESS, "OK", duration_ms=200),
        ]
        assert report.total_duration_ms == 300

    def test_preflight_report_warnings(self):
        """Test warnings collection."""
        report = PreflightReport(provider_name="test")
        report.results = [
            PreflightResult("step1", PreflightStatus.SUCCESS, "OK"),
            PreflightResult("step2", PreflightStatus.WARNING, "Warning"),
        ]
        assert len(report.warnings) == 1
        assert report.warnings[0].step == "step2"
