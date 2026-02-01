"""Exceptions for the RAPI module.

This module defines the exception hierarchy for REST API operations.
"""

from __future__ import annotations

from typing import Any


class RapiError(Exception):
    """Base exception for all RAPI errors.

    Attributes:
        message: Human-readable error message.
        details: Additional error context as key-value pairs.

    Examples:
        >>> raise RapiError("Something went wrong", details={"endpoint": "test"})
        Traceback (most recent call last):
        ...
        kstlib.rapi.exceptions.RapiError: Something went wrong
    """

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize RapiError.

        Args:
            message: Human-readable error message.
            details: Additional error context.
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}


class CredentialError(RapiError):
    """Raised when credential resolution fails.

    Attributes:
        credential_name: Name of the credential that failed.
        reason: Reason for the failure.

    Examples:
        >>> raise CredentialError("github", "Environment variable not set")
        Traceback (most recent call last):
        ...
        kstlib.rapi.exceptions.CredentialError: Credential 'github' failed: Environment variable not set
    """

    def __init__(self, credential_name: str, reason: str) -> None:
        """Initialize CredentialError.

        Args:
            credential_name: Name of the credential that failed.
            reason: Reason for the failure.
        """
        super().__init__(
            f"Credential '{credential_name}' failed: {reason}",
            details={"credential_name": credential_name, "reason": reason},
        )
        self.credential_name = credential_name
        self.reason = reason


class EndpointNotFoundError(RapiError):
    """Raised when an endpoint cannot be resolved.

    Attributes:
        endpoint_ref: The endpoint reference that was not found.
        searched_apis: List of API names that were searched.

    Examples:
        >>> raise EndpointNotFoundError("unknown.endpoint")
        Traceback (most recent call last):
        ...
        kstlib.rapi.exceptions.EndpointNotFoundError: Endpoint 'unknown.endpoint' not found
    """

    def __init__(
        self,
        endpoint_ref: str,
        searched_apis: list[str] | None = None,
    ) -> None:
        """Initialize EndpointNotFoundError.

        Args:
            endpoint_ref: The endpoint reference that was not found.
            searched_apis: List of API names that were searched.
        """
        super().__init__(
            f"Endpoint '{endpoint_ref}' not found",
            details={"endpoint_ref": endpoint_ref, "searched_apis": searched_apis or []},
        )
        self.endpoint_ref = endpoint_ref
        self.searched_apis = searched_apis or []


class EndpointAmbiguousError(RapiError):
    """Raised when an endpoint name matches multiple APIs.

    Attributes:
        endpoint_name: The ambiguous endpoint name.
        matching_apis: List of API names containing this endpoint.

    Examples:
        >>> raise EndpointAmbiguousError("get_data", ["api1", "api2"])
        Traceback (most recent call last):
        ...
        kstlib.rapi.exceptions.EndpointAmbiguousError: Endpoint 'get_data' is ambiguous, found in: api1, api2
    """

    def __init__(self, endpoint_name: str, matching_apis: list[str]) -> None:
        """Initialize EndpointAmbiguousError.

        Args:
            endpoint_name: The ambiguous endpoint name.
            matching_apis: List of API names containing this endpoint.
        """
        super().__init__(
            f"Endpoint '{endpoint_name}' is ambiguous, found in: {', '.join(matching_apis)}",
            details={"endpoint_name": endpoint_name, "matching_apis": matching_apis},
        )
        self.endpoint_name = endpoint_name
        self.matching_apis = matching_apis


class RequestError(RapiError):
    """Raised when an HTTP request fails.

    Attributes:
        status_code: HTTP status code (if available).
        response_body: Response body (if available).
        retryable: Whether the error is potentially retryable.

    Examples:
        >>> raise RequestError("Server error", status_code=500, retryable=True)
        Traceback (most recent call last):
        ...
        kstlib.rapi.exceptions.RequestError: Server error
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_body: str | None = None,
        retryable: bool = False,
    ) -> None:
        """Initialize RequestError.

        Args:
            message: Human-readable error message.
            status_code: HTTP status code (if available).
            response_body: Response body (if available).
            retryable: Whether the error is potentially retryable.
        """
        super().__init__(
            message,
            details={
                "status_code": status_code,
                "response_body": response_body,
                "retryable": retryable,
            },
        )
        self.status_code = status_code
        self.response_body = response_body
        self.retryable = retryable


class ResponseTooLargeError(RapiError):
    """Raised when response exceeds max_response_size limit.

    Attributes:
        response_size: Actual response size in bytes.
        max_size: Maximum allowed size in bytes.

    Examples:
        >>> raise ResponseTooLargeError(15_000_000, 10_000_000)
        Traceback (most recent call last):
        ...
        kstlib.rapi.exceptions.ResponseTooLargeError: Response size 15000000 exceeds limit 10000000
    """

    def __init__(self, response_size: int, max_size: int) -> None:
        """Initialize ResponseTooLargeError.

        Args:
            response_size: Actual response size in bytes.
            max_size: Maximum allowed size in bytes.
        """
        super().__init__(
            f"Response size {response_size} exceeds limit {max_size}",
            details={"response_size": response_size, "max_size": max_size},
        )
        self.response_size = response_size
        self.max_size = max_size


class ConfirmationRequiredError(RapiError):
    """Raised when a dangerous endpoint requires confirmation.

    This exception is raised at runtime when calling an endpoint
    that has a safeguard configured but the confirm parameter is
    missing or incorrect.

    Attributes:
        endpoint_ref: Full endpoint reference (api.endpoint).
        expected: Expected confirmation string.
        actual: Actual confirmation string provided (None if missing).

    Examples:
        >>> raise ConfirmationRequiredError("api.delete", expected="DELETE X")
        Traceback (most recent call last):
        ...
        kstlib.rapi.exceptions.ConfirmationRequiredError: ... requires confirmation...
    """

    def __init__(
        self,
        endpoint_ref: str,
        *,
        expected: str,
        actual: str | None = None,
    ) -> None:
        """Initialize ConfirmationRequiredError.

        Args:
            endpoint_ref: Full endpoint reference (api.endpoint).
            expected: Expected confirmation string.
            actual: Actual confirmation string provided (None if missing).
        """
        if actual is None:
            message = f"Endpoint '{endpoint_ref}' requires confirmation. Pass confirm=\"{expected}\" to proceed."
        else:
            message = f'Confirmation mismatch for \'{endpoint_ref}\'. Expected: "{expected}", got: "{actual}"'
        super().__init__(
            message,
            details={
                "endpoint_ref": endpoint_ref,
                "expected": expected,
                "actual": actual,
            },
        )
        self.endpoint_ref = endpoint_ref
        self.expected = expected
        self.actual = actual


class SafeguardMissingError(RapiError):
    """Raised when endpoint requires safeguard but none is configured.

    This exception is raised at config load time when an endpoint uses
    a method that requires a safeguard (e.g., DELETE, PUT) but no
    safeguard string is provided in the endpoint configuration.

    Attributes:
        endpoint_ref: Full endpoint reference (api.endpoint).
        method: HTTP method that requires the safeguard.

    Examples:
        >>> raise SafeguardMissingError("api.delete", "DELETE")
        Traceback (most recent call last):
        ...
        kstlib.rapi.exceptions.SafeguardMissingError: ... requires a safeguard...
    """

    def __init__(self, endpoint_ref: str, method: str) -> None:
        """Initialize SafeguardMissingError.

        Args:
            endpoint_ref: Full endpoint reference (api.endpoint).
            method: HTTP method that requires the safeguard.
        """
        message = (
            f"Endpoint '{endpoint_ref}' uses method {method} which requires a safeguard. "
            f"Add 'safeguard: \"...\"' to the endpoint or remove {method} from "
            f"rapi.safeguard.required_methods in kstlib.conf.yml."
        )
        super().__init__(
            message,
            details={"endpoint_ref": endpoint_ref, "method": method},
        )
        self.endpoint_ref = endpoint_ref
        self.method = method


class EndpointCollisionError(RapiError):
    """Raised when endpoints collide in strict mode.

    This exception is raised at config load time when the same endpoint
    reference is defined in multiple files and strict mode is enabled.

    Attributes:
        endpoint_ref: Full endpoint reference (api.endpoint).
        source_files: List of files defining this endpoint.

    Examples:
        >>> raise EndpointCollisionError("api.create", ["a.rapi.yml", "b.rapi.yml"])
        Traceback (most recent call last):
        ...
        kstlib.rapi.exceptions.EndpointCollisionError: Endpoint 'api.create' defined in multiple files...
    """

    def __init__(self, endpoint_ref: str, source_files: list[str]) -> None:
        """Initialize EndpointCollisionError.

        Args:
            endpoint_ref: Full endpoint reference (api.endpoint).
            source_files: List of files defining this endpoint.
        """
        message = (
            f"Endpoint '{endpoint_ref}' defined in multiple files: {', '.join(source_files)}. "
            f"Set rapi.strict: false to allow overwriting (last file wins)."
        )
        super().__init__(
            message,
            details={"endpoint_ref": endpoint_ref, "source_files": source_files},
        )
        self.endpoint_ref = endpoint_ref
        self.source_files = source_files


class EnvVarError(RapiError):
    """Raised when environment variable substitution fails.

    This exception is raised at config load time when a required
    environment variable is not set and no default value is provided.

    Attributes:
        var_name: Name of the missing environment variable.
        source: Source file or context where the variable was referenced.

    Examples:
        >>> raise EnvVarError("VIYA_HOST")
        Traceback (most recent call last):
        ...
        kstlib.rapi.exceptions.EnvVarError: Environment variable 'VIYA_HOST' is not set...
    """

    def __init__(self, var_name: str, source: str | None = None) -> None:
        """Initialize EnvVarError.

        Args:
            var_name: Name of the missing environment variable.
            source: Source file or context where the variable was referenced.
        """
        if source:
            message = f"Environment variable '{var_name}' is not set (required by {source}). Use ${{VAR:-default}} for optional variables."
        else:
            message = f"Environment variable '{var_name}' is not set. Use ${{VAR:-default}} for optional variables."
        super().__init__(
            message,
            details={"var_name": var_name, "source": source},
        )
        self.var_name = var_name
        self.source = source


__all__ = [
    "ConfirmationRequiredError",
    "CredentialError",
    "EndpointAmbiguousError",
    "EndpointCollisionError",
    "EndpointNotFoundError",
    "EnvVarError",
    "RapiError",
    "RequestError",
    "ResponseTooLargeError",
    "SafeguardMissingError",
]
