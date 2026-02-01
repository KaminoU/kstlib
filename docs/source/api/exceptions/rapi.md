# RAPI Exceptions

Exceptions for the REST API client module: credential resolution, endpoint configuration, and HTTP requests.

## Exception hierarchy

```
RapiError (base)
├── CredentialError           # Credential resolution failed
├── EndpointNotFoundError     # Endpoint not in config
├── EndpointAmbiguousError    # Short reference matches multiple endpoints
├── RequestError              # HTTP request failed
├── ResponseTooLargeError     # Response exceeds max size
├── ConfirmationRequiredError # Dangerous endpoint called without confirmation
└── SafeguardMissingError     # Dangerous method without safeguard in config
```

## Common failure modes

- `CredentialError` is raised when credential resolution fails (missing environment variable, file not found, or SOPS decryption error).
- `EndpointNotFoundError` surfaces when the requested endpoint reference doesn't match any configured endpoint.
- `EndpointAmbiguousError` indicates a short reference (e.g., `"users"`) matches endpoints in multiple APIs.
- `RequestError` wraps HTTP failures including timeouts and 5xx errors after retry exhaustion.
- `ResponseTooLargeError` indicates the response body exceeds the configured `max_response_size` limit.
- `ConfirmationRequiredError` is raised at runtime when calling a dangerous endpoint (DELETE, PUT) without the required `confirm` parameter.
- `SafeguardMissingError` is raised at config load time when an endpoint uses a dangerous method but lacks a `safeguard` string.

## Usage patterns

### Handling credential errors

```python
from kstlib.rapi import RapiClient
from kstlib.rapi.exceptions import CredentialError

try:
    client = RapiClient()
    response = client.call("secure_api.endpoint")
except CredentialError as e:
    logger.error(f"Credential resolution failed: {e}")
    logger.error(f"Credential name: {e.credential_name}")
    # Check environment variable or credential file
```

### Handling endpoint resolution

```python
from kstlib.rapi import RapiClient
from kstlib.rapi.exceptions import EndpointNotFoundError, EndpointAmbiguousError

client = RapiClient()

try:
    response = client.call("users")  # Short reference
except EndpointAmbiguousError as e:
    # Multiple APIs have "users" endpoint
    logger.warning(f"Ambiguous: {e.matching_apis}")
    # Use full reference instead
    response = client.call("github.users")
except EndpointNotFoundError as e:
    logger.error(f"Endpoint not found: {e.endpoint_ref}")
    logger.error(f"Searched APIs: {e.searched_apis}")
```

### Request error handling

```python
from kstlib.rapi import RapiClient
from kstlib.rapi.exceptions import RequestError

client = RapiClient()

try:
    response = client.call("httpbin.delay", 60)  # May timeout
except RequestError as e:
    logger.error(f"Request failed: {e}")
    if e.retryable:
        logger.info("Error is retryable, consider retry later")
    if e.status_code:
        logger.info(f"HTTP status: {e.status_code}")
```

### Response size validation

```python
from kstlib.rapi import RapiClient
from kstlib.rapi.exceptions import ResponseTooLargeError

client = RapiClient()

try:
    response = client.call("api.large_endpoint")
except ResponseTooLargeError as e:
    logger.warning(f"Response too large: {e.size} bytes")
    logger.warning(f"Max allowed: {e.max_size} bytes")
    # Consider pagination or streaming
```

### Safeguard confirmation

```python
from kstlib.rapi import RapiClient
from kstlib.rapi.exceptions import ConfirmationRequiredError

client = RapiClient()

try:
    # Dangerous endpoint without confirmation
    client.call("admin.delete-user", user_id="123")
except ConfirmationRequiredError as e:
    logger.warning(f"Confirmation required: {e.expected}")
    # Ask user for confirmation, then retry
    if user_confirms():
        client.call("admin.delete-user", user_id="123", confirm=e.expected)
```

### Safe wrapper pattern

```python
from kstlib.rapi import RapiClient
from kstlib.rapi.exceptions import RapiError

def safe_api_call(endpoint: str, *args, **kwargs) -> dict | None:
    """Make API call with comprehensive error handling."""
    client = RapiClient()
    try:
        response = client.call(endpoint, *args, **kwargs)
        if response.ok:
            return response.data
        logger.warning(f"API returned {response.status_code}")
        return None
    except RapiError as e:
        logger.error(f"API call failed: {e}")
        return None
```

## API reference

```{eval-rst}
.. automodule:: kstlib.rapi.exceptions
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```
