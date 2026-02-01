"""Tests for kstlib.rapi.exceptions module."""

from kstlib.rapi.exceptions import (
    ConfirmationRequiredError,
    CredentialError,
    EndpointAmbiguousError,
    EndpointNotFoundError,
    EnvVarError,
    RapiError,
    RequestError,
    ResponseTooLargeError,
    SafeguardMissingError,
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


class TestConfirmationRequiredError:
    """Tests for ConfirmationRequiredError exception."""

    def test_missing_confirmation(self) -> None:
        """Create error when confirmation is missing."""
        error = ConfirmationRequiredError("admin.delete_user", expected="DELETE USER 123")
        assert "admin.delete_user" in str(error)
        assert "requires confirmation" in str(error)
        assert 'confirm="DELETE USER 123"' in str(error)
        assert error.endpoint_ref == "admin.delete_user"
        assert error.expected == "DELETE USER 123"
        assert error.actual is None

    def test_mismatch_confirmation(self) -> None:
        """Create error when confirmation does not match."""
        error = ConfirmationRequiredError(
            "admin.delete_user",
            expected="DELETE USER 123",
            actual="wrong",
        )
        assert "admin.delete_user" in str(error)
        assert "mismatch" in str(error).lower()
        assert '"DELETE USER 123"' in str(error)
        assert '"wrong"' in str(error)
        assert error.expected == "DELETE USER 123"
        assert error.actual == "wrong"

    def test_inherits_rapi_error(self) -> None:
        """Verify ConfirmationRequiredError inherits from RapiError."""
        error = ConfirmationRequiredError("test.ep", expected="CONFIRM")
        assert isinstance(error, RapiError)
        assert "endpoint_ref" in error.details
        assert "expected" in error.details
        assert "actual" in error.details

    def test_details_populated(self) -> None:
        """Verify details dict is properly populated."""
        error = ConfirmationRequiredError("api.endpoint", expected="EXPECTED", actual="ACTUAL")
        assert error.details["endpoint_ref"] == "api.endpoint"
        assert error.details["expected"] == "EXPECTED"
        assert error.details["actual"] == "ACTUAL"


class TestSafeguardMissingError:
    """Tests for SafeguardMissingError exception."""

    def test_basic_creation(self) -> None:
        """Create SafeguardMissingError with endpoint and method."""
        error = SafeguardMissingError("admin.delete_user", "DELETE")
        assert "admin.delete_user" in str(error)
        assert "DELETE" in str(error)
        assert "safeguard" in str(error).lower()
        assert error.endpoint_ref == "admin.delete_user"
        assert error.method == "DELETE"

    def test_message_suggests_fix(self) -> None:
        """Error message suggests how to fix the issue."""
        error = SafeguardMissingError("api.ep", "PUT")
        msg = str(error)
        assert 'safeguard: "..."' in msg
        assert "required_methods" in msg

    def test_inherits_rapi_error(self) -> None:
        """Verify SafeguardMissingError inherits from RapiError."""
        error = SafeguardMissingError("test.ep", "DELETE")
        assert isinstance(error, RapiError)
        assert "endpoint_ref" in error.details
        assert "method" in error.details

    def test_details_populated(self) -> None:
        """Verify details dict is properly populated."""
        error = SafeguardMissingError("api.endpoint", "DELETE")
        assert error.details["endpoint_ref"] == "api.endpoint"
        assert error.details["method"] == "DELETE"


class TestEnvVarError:
    """Tests for EnvVarError exception."""

    def test_basic_creation(self) -> None:
        """Create EnvVarError with variable name only."""
        error = EnvVarError("VIYA_HOST")
        assert "VIYA_HOST" in str(error)
        assert "not set" in str(error)
        assert "${VAR:-default}" in str(error)
        assert error.var_name == "VIYA_HOST"
        assert error.source is None

    def test_with_source(self) -> None:
        """Create EnvVarError with source file context."""
        error = EnvVarError("API_KEY", source="config.rapi.yml")
        assert "API_KEY" in str(error)
        assert "config.rapi.yml" in str(error)
        assert error.var_name == "API_KEY"
        assert error.source == "config.rapi.yml"

    def test_inherits_rapi_error(self) -> None:
        """Verify EnvVarError inherits from RapiError."""
        error = EnvVarError("TEST_VAR")
        assert isinstance(error, RapiError)
        assert "var_name" in error.details
        assert "source" in error.details

    def test_details_populated(self) -> None:
        """Verify details dict is properly populated."""
        error = EnvVarError("MY_VAR", source="test.yml")
        assert error.details["var_name"] == "MY_VAR"
        assert error.details["source"] == "test.yml"
