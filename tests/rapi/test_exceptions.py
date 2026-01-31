"""Tests for kstlib.rapi.exceptions module."""

from kstlib.rapi.exceptions import (
    CredentialError,
    EndpointAmbiguousError,
    EndpointNotFoundError,
    RapiError,
    RequestError,
    ResponseTooLargeError,
)


class TestRapiError:
    """Tests for RapiError base exception."""

    def test_message_only(self) -> None:
        """Create error with message only."""
        error = RapiError("Something went wrong")
        assert str(error) == "Something went wrong"
        assert error.message == "Something went wrong"
        assert error.details == {}

    def test_with_details(self) -> None:
        """Create error with message and details."""
        error = RapiError("Failed", details={"endpoint": "test", "status": 500})
        assert error.message == "Failed"
        assert error.details == {"endpoint": "test", "status": 500}


class TestCredentialError:
    """Tests for CredentialError exception."""

    def test_basic_creation(self) -> None:
        """Create CredentialError with name and reason."""
        error = CredentialError("github", "Environment variable not set")
        assert "github" in str(error)
        assert "Environment variable not set" in str(error)
        assert error.credential_name == "github"
        assert error.reason == "Environment variable not set"

    def test_inherits_rapi_error(self) -> None:
        """Verify CredentialError inherits from RapiError."""
        error = CredentialError("test", "test reason")
        assert isinstance(error, RapiError)
        assert "credential_name" in error.details
        assert "reason" in error.details


class TestEndpointNotFoundError:
    """Tests for EndpointNotFoundError exception."""

    def test_basic_creation(self) -> None:
        """Create EndpointNotFoundError with reference."""
        error = EndpointNotFoundError("unknown.endpoint")
        assert "unknown.endpoint" in str(error)
        assert error.endpoint_ref == "unknown.endpoint"
        assert error.searched_apis == []

    def test_with_searched_apis(self) -> None:
        """Create EndpointNotFoundError with searched APIs list."""
        error = EndpointNotFoundError("missing", searched_apis=["api1", "api2"])
        assert error.endpoint_ref == "missing"
        assert error.searched_apis == ["api1", "api2"]
        assert error.details["searched_apis"] == ["api1", "api2"]

    def test_inherits_rapi_error(self) -> None:
        """Verify EndpointNotFoundError inherits from RapiError."""
        error = EndpointNotFoundError("test")
        assert isinstance(error, RapiError)


class TestEndpointAmbiguousError:
    """Tests for EndpointAmbiguousError exception."""

    def test_basic_creation(self) -> None:
        """Create EndpointAmbiguousError with name and matching APIs."""
        error = EndpointAmbiguousError("get_data", ["api1", "api2"])
        assert "get_data" in str(error)
        assert "api1" in str(error)
        assert "api2" in str(error)
        assert error.endpoint_name == "get_data"
        assert error.matching_apis == ["api1", "api2"]

    def test_inherits_rapi_error(self) -> None:
        """Verify EndpointAmbiguousError inherits from RapiError."""
        error = EndpointAmbiguousError("test", ["a", "b"])
        assert isinstance(error, RapiError)


class TestRequestError:
    """Tests for RequestError exception."""

    def test_basic_creation(self) -> None:
        """Create RequestError with message only."""
        error = RequestError("Request failed")
        assert str(error) == "Request failed"
        assert error.status_code is None
        assert error.response_body is None
        assert error.retryable is False

    def test_with_status_code(self) -> None:
        """Create RequestError with status code."""
        error = RequestError("Server error", status_code=500, retryable=True)
        assert error.status_code == 500
        assert error.retryable is True

    def test_with_response_body(self) -> None:
        """Create RequestError with response body."""
        error = RequestError(
            "Bad request",
            status_code=400,
            response_body='{"error": "invalid"}',
        )
        assert error.status_code == 400
        assert error.response_body == '{"error": "invalid"}'

    def test_inherits_rapi_error(self) -> None:
        """Verify RequestError inherits from RapiError."""
        error = RequestError("test")
        assert isinstance(error, RapiError)


class TestResponseTooLargeError:
    """Tests for ResponseTooLargeError exception."""

    def test_basic_creation(self) -> None:
        """Create ResponseTooLargeError with sizes."""
        error = ResponseTooLargeError(15_000_000, 10_000_000)
        assert "15000000" in str(error)
        assert "10000000" in str(error)
        assert error.response_size == 15_000_000
        assert error.max_size == 10_000_000

    def test_inherits_rapi_error(self) -> None:
        """Verify ResponseTooLargeError inherits from RapiError."""
        error = ResponseTooLargeError(100, 50)
        assert isinstance(error, RapiError)

    def test_details_populated(self) -> None:
        """Verify details dict is properly populated."""
        error = ResponseTooLargeError(200, 100)
        assert error.details["response_size"] == 200
        assert error.details["max_size"] == 100
