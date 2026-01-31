"""HTTP client for RAPI module.

This module provides the RapiClient class for making REST API calls
with config-driven endpoints, multi-source credentials, and detailed logging.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

import httpx

from kstlib.limits import get_rapi_limits
from kstlib.rapi.config import (
    ApiConfig,
    EndpointConfig,
    HmacConfig,
    RapiConfigManager,
    load_rapi_config,
)
from kstlib.rapi.credentials import CredentialRecord, CredentialResolver
from kstlib.rapi.exceptions import (
    RequestError,
    ResponseTooLargeError,
)
from kstlib.ssl import build_ssl_context

if TYPE_CHECKING:
    from collections.abc import Mapping

from kstlib.logging import TRACE_LEVEL, get_logger

log = get_logger(__name__)


def _log_trace(msg: str, *args: Any) -> None:
    """Log at TRACE level."""
    log.log(TRACE_LEVEL, msg, *args)


@dataclass
class RapiResponse:
    """Response from an API call.

    Attributes:
        status_code: HTTP status code.
        headers: Response headers.
        data: Parsed JSON response (or None if not JSON).
        text: Raw response text.
        elapsed: Request duration in seconds.
        endpoint_ref: Full endpoint reference used.

    Examples:
        >>> response = RapiResponse(status_code=200, data={"ip": "1.2.3.4"})
        >>> response.ok
        True
        >>> response.data["ip"]
        '1.2.3.4'
    """

    status_code: int
    headers: dict[str, str] = field(default_factory=dict)
    data: Any = None
    text: str = ""
    elapsed: float = 0.0
    endpoint_ref: str = ""

    @property
    def ok(self) -> bool:
        """Return True if status code indicates success (2xx)."""
        return 200 <= self.status_code < 300


class RapiClient:
    """Config-driven REST API client.

    Makes HTTP requests to configured API endpoints with automatic
    credential resolution, header merging, and detailed logging.

    Supports loading configuration from:
    - kstlib.conf.yml (default)
    - External ``*.rapi.yml`` files (via from_file)
    - Auto-discovery of ``*.rapi.yml`` in current directory (via discover)

    Args:
        config_manager: Optional RapiConfigManager (loads from config if None).
        credentials_config: Optional credentials configuration.

    Examples:
        >>> client = RapiClient()  # doctest: +SKIP
        >>> response = client.call("httpbin.get_ip")  # doctest: +SKIP
        >>> response.data  # doctest: +SKIP
        {'origin': '...'}

        >>> client = RapiClient.from_file("github.rapi.yml")  # doctest: +SKIP
        >>> client = RapiClient.discover()  # doctest: +SKIP
    """

    def __init__(
        self,
        config_manager: RapiConfigManager | None = None,
        credentials_config: Mapping[str, Any] | None = None,
        *,
        ssl_verify: bool | None = None,
        ssl_ca_bundle: str | None = None,
    ) -> None:
        """Initialize RapiClient.

        Args:
            config_manager: Optional RapiConfigManager instance.
            credentials_config: Optional credentials configuration.
            ssl_verify: Override SSL verification (True/False).
                If None, uses global config from kstlib.conf.yml.
            ssl_ca_bundle: Override CA bundle path.
                If None, uses global config from kstlib.conf.yml.
        """
        self._config_manager = config_manager or load_rapi_config()

        # Merge credentials: inline from config_manager + explicit credentials_config
        merged_credentials: dict[str, Any] = {}
        if hasattr(self._config_manager, "credentials_config"):
            merged_credentials.update(self._config_manager.credentials_config)
        if credentials_config:
            merged_credentials.update(credentials_config)

        self._credential_resolver = CredentialResolver(merged_credentials or None)
        self._limits = get_rapi_limits()

        # Build SSL context (cascade: kwargs > global config > default)
        self._ssl_context = build_ssl_context(
            ssl_verify=ssl_verify,
            ssl_ca_bundle=ssl_ca_bundle,
        )

        log.debug(
            "RapiClient initialized (timeout=%.1fs, max_retries=%d)",
            self._limits.timeout,
            self._limits.max_retries,
        )

    @classmethod
    def from_file(
        cls,
        path: str,
        credentials_config: Mapping[str, Any] | None = None,
    ) -> RapiClient:
        """Create client from a ``*.rapi.yml`` file.

        Loads API configuration from an external YAML file with simplified format.

        Args:
            path: Path to the ``*.rapi.yml`` file.
            credentials_config: Additional credentials (merged with inline).

        Returns:
            Configured RapiClient instance.

        Raises:
            FileNotFoundError: If file does not exist.
            ValueError: If file format is invalid.

        Examples:
            >>> client = RapiClient.from_file("github.rapi.yml")  # doctest: +SKIP
            >>> response = client.call("github.user")  # doctest: +SKIP
        """
        config_manager = RapiConfigManager.from_file(path)
        return cls(config_manager, credentials_config)

    @classmethod
    def discover(
        cls,
        directory: str | None = None,
        pattern: str = "*.rapi.yml",
        credentials_config: Mapping[str, Any] | None = None,
    ) -> RapiClient:
        """Create client by auto-discovering ``*.rapi.yml`` files.

        Searches for files matching the pattern in the specified directory
        (defaults to current working directory) and loads all found configs.

        Args:
            directory: Directory to search in (default: current directory).
            pattern: Glob pattern for files (default: ``*.rapi.yml``).
            credentials_config: Additional credentials (merged with inline).

        Returns:
            Configured RapiClient instance.

        Raises:
            FileNotFoundError: If no matching files found.

        Examples:
            >>> client = RapiClient.discover()  # doctest: +SKIP
            >>> client = RapiClient.discover("./apis/")  # doctest: +SKIP
        """
        config_manager = RapiConfigManager.discover(directory, pattern)
        return cls(config_manager, credentials_config)

    @property
    def config_manager(self) -> RapiConfigManager:
        """Get the configuration manager.

        Returns:
            RapiConfigManager instance.
        """
        return self._config_manager

    def list_apis(self) -> list[str]:
        """List all configured API names.

        Returns:
            List of API names.
        """
        return self._config_manager.list_apis()

    def list_endpoints(self, api_name: str | None = None) -> list[str]:
        """List endpoint references.

        Args:
            api_name: Filter by API name (optional).

        Returns:
            List of full endpoint references (api.endpoint).
        """
        return self._config_manager.list_endpoints(api_name)

    def call(
        self,
        endpoint_ref: str,
        *args: Any,
        body: Any = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> RapiResponse:
        """Make a synchronous API call.

        Args:
            endpoint_ref: Endpoint reference (full: api.endpoint or short: endpoint).
            *args: Positional arguments for path parameters.
            body: Request body (dict for JSON, str for raw).
            headers: Runtime headers (override service/endpoint headers).
            timeout: Request timeout (uses config default if None).
            **kwargs: Keyword arguments for path parameters and query params.

        Returns:
            RapiResponse with parsed data.

        Raises:
            RequestError: If request fails after retries.
            ResponseTooLargeError: If response exceeds max size.

        Examples:
            >>> client = RapiClient()  # doctest: +SKIP
            >>> client.call("httpbin.get_ip")  # doctest: +SKIP
            >>> client.call("httpbin.delayed", 5)  # doctest: +SKIP
            >>> client.call("httpbin.post_data", body={"key": "value"})  # doctest: +SKIP
        """
        log.debug("Calling endpoint: %s", endpoint_ref)

        # Resolve endpoint
        api_config, endpoint_config = self._config_manager.resolve(endpoint_ref)
        _log_trace("Resolved to: %s", endpoint_config.full_ref)

        # Build request
        request = self._build_request(
            api_config,
            endpoint_config,
            args,
            kwargs,
            body,
            headers,
        )

        # Execute with retries
        effective_timeout = timeout if timeout is not None else self._limits.timeout
        return self._execute_with_retry(request, endpoint_config, effective_timeout)

    async def call_async(
        self,
        endpoint_ref: str,
        *args: Any,
        body: Any = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> RapiResponse:
        """Make an asynchronous API call.

        Args:
            endpoint_ref: Endpoint reference (full: api.endpoint or short: endpoint).
            *args: Positional arguments for path parameters.
            body: Request body (dict for JSON, str for raw).
            headers: Runtime headers (override service/endpoint headers).
            timeout: Request timeout (uses config default if None).
            **kwargs: Keyword arguments for path parameters and query params.

        Returns:
            RapiResponse with parsed data.

        Raises:
            RequestError: If request fails after retries.
            ResponseTooLargeError: If response exceeds max size.
        """
        log.debug("Calling endpoint (async): %s", endpoint_ref)

        # Resolve endpoint
        api_config, endpoint_config = self._config_manager.resolve(endpoint_ref)
        _log_trace("Resolved to: %s", endpoint_config.full_ref)

        # Build request
        request = self._build_request(
            api_config,
            endpoint_config,
            args,
            kwargs,
            body,
            headers,
        )

        # Execute with retries
        effective_timeout = timeout if timeout is not None else self._limits.timeout
        return await self._execute_with_retry_async(
            request,
            endpoint_config,
            effective_timeout,
        )

    def _extract_query_params(
        self,
        endpoint_config: EndpointConfig,
        kwargs: dict[str, Any],
    ) -> dict[str, str]:
        """Extract query parameters from kwargs (excluding path params)."""
        import re

        query_params = dict(endpoint_config.query)
        path_params: set[str] = set()

        for match in re.finditer(r"\{([a-zA-Z_][a-zA-Z0-9_]*|\d+)\}", endpoint_config.path):
            param = match.group(1)
            if not param.isdigit():
                path_params.add(param)

        for key, value in kwargs.items():
            if key not in path_params:
                query_params[key] = str(value)

        return query_params

    def _prepare_body(
        self,
        body: Any,
        headers: dict[str, str],
    ) -> bytes | None:
        """Prepare request body and set Content-Type header if needed."""
        if body is None:
            return None

        content: bytes | None = None
        if isinstance(body, dict):
            content = json.dumps(body).encode("utf-8")
            if "Content-Type" not in headers:
                headers["Content-Type"] = "application/json"
        elif isinstance(body, str):
            content = body.encode("utf-8")
        elif isinstance(body, bytes):
            content = body

        if content:
            _log_trace("Request body size: %d bytes", len(content))
            # Log body content (truncate if too large)
            body_preview = content.decode("utf-8", errors="replace")
            if len(body_preview) > 1000:
                _log_trace(">>> Body: %s... [truncated]", body_preview[:1000])
            else:
                _log_trace(">>> Body: %s", body_preview)

        return content

    def _build_request(
        self,
        api_config: ApiConfig,
        endpoint_config: EndpointConfig,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        body: Any,
        runtime_headers: Mapping[str, str] | None,
    ) -> httpx.Request:
        """Build HTTP request from configuration.

        Args:
            api_config: API service configuration.
            endpoint_config: Endpoint configuration.
            args: Positional path parameters.
            kwargs: Keyword parameters (path + query).
            body: Request body.
            runtime_headers: Runtime header overrides.

        Returns:
            Prepared httpx.Request.
        """
        # Build URL with path parameter substitution
        _log_trace("Path template: %s", endpoint_config.path)
        if args:
            _log_trace("Path args (positional): %s", args)
        if kwargs:
            _log_trace("Path/query kwargs: %s", kwargs)
        path = endpoint_config.build_path(*args, **kwargs)
        url = f"{api_config.base_url}{path}"

        # Extract query params from kwargs
        query_params = self._extract_query_params(endpoint_config, kwargs)

        _log_trace("Final URL: %s", url)
        if query_params:
            _log_trace("Query params: %s", query_params)

        # Merge headers (service < endpoint < runtime)
        merged_headers = self._merge_headers(
            api_config.headers,
            endpoint_config.headers,
            dict(runtime_headers) if runtime_headers else {},
        )

        # Prepare body first (needed for HMAC signing if sign_body=True)
        content = self._prepare_body(body, merged_headers)

        # Apply authentication (may modify headers and query_params for HMAC)
        # Skip auth if endpoint explicitly disables it (auth: false)
        if api_config.credentials and endpoint_config.auth:
            self._apply_auth(merged_headers, api_config, query_params, content)

        # Create request
        request = httpx.Request(
            method=endpoint_config.method,
            url=url,
            params=query_params if query_params else None,
            headers=merged_headers,
            content=content,
        )

        self._log_request(request)
        return request

    def _merge_headers(
        self,
        service_headers: dict[str, str],
        endpoint_headers: dict[str, str],
        runtime_headers: dict[str, str],
    ) -> dict[str, str]:
        """Merge headers from three levels.

        Order: service < endpoint < runtime (later overrides earlier).

        Args:
            service_headers: Service-level headers.
            endpoint_headers: Endpoint-level headers.
            runtime_headers: Runtime headers.

        Returns:
            Merged headers dictionary.
        """
        merged = {}
        merged.update(service_headers)
        merged.update(endpoint_headers)
        merged.update(runtime_headers)

        _log_trace(
            "Headers merged: service=%d, endpoint=%d, runtime=%d -> total=%d",
            len(service_headers),
            len(endpoint_headers),
            len(runtime_headers),
            len(merged),
        )

        return merged

    def _apply_auth(
        self,
        headers: dict[str, str],
        api_config: ApiConfig,
        query_params: dict[str, str] | None = None,
        body_content: bytes | None = None,
    ) -> None:
        """Apply authentication to headers and query params.

        Args:
            headers: Headers dict to modify.
            api_config: API config with credentials reference.
            query_params: Query params dict to modify (for HMAC signing).
            body_content: Request body content (for HMAC signing).
        """
        if not api_config.credentials:
            return

        try:
            cred = self._credential_resolver.resolve(api_config.credentials)
        except Exception as e:
            log.warning("Failed to resolve credential '%s': %s", api_config.credentials, e)
            return

        auth_type = api_config.auth_type or "bearer"

        if auth_type == "bearer":
            headers["Authorization"] = f"Bearer {cred.value}"
            _log_trace("Applied Bearer auth")
        elif auth_type == "basic":
            auth_str = f"{cred.value}:{cred.secret}" if cred.secret else f"{cred.value}:"
            encoded = base64.b64encode(auth_str.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
            _log_trace("Applied Basic auth")
        elif auth_type == "api_key":
            headers["X-API-Key"] = cred.value
            _log_trace("Applied API Key auth")
        elif auth_type == "hmac":
            self._apply_hmac_auth(
                headers,
                api_config,
                cred,
                query_params if query_params is not None else {},
                body_content,
            )
        else:
            log.warning("Unknown auth_type: %s", auth_type)

    def _apply_hmac_auth(
        self,
        headers: dict[str, str],
        api_config: ApiConfig,
        cred: CredentialRecord,
        query_params: dict[str, str],
        body_content: bytes | None,
    ) -> None:
        """Apply HMAC authentication.

        Supports various exchange APIs like Binance (SHA256, hex) and
        Kraken (SHA512, base64).

        Args:
            headers: Headers dict to modify.
            api_config: API config with HMAC configuration.
            cred: Resolved credential with API key and secret.
            query_params: Query params dict to modify (timestamp/signature added).
            body_content: Request body content (for signing if sign_body=True).

        Raises:
            ValueError: If secret is not available in credentials.
        """
        if not cred.secret:
            raise ValueError("HMAC auth requires secret_key in credentials")

        hmac_cfg = api_config.hmac_config or HmacConfig()

        # 1. Generate timestamp or nonce
        ts_value = str(int(time.time() * 1000))
        ts_field = hmac_cfg.nonce_field or hmac_cfg.timestamp_field

        # Add timestamp/nonce to query params
        query_params[ts_field] = ts_value

        # 2. Build payload to sign
        if hmac_cfg.sign_body and body_content:
            payload = body_content.decode("utf-8", errors="replace")
        else:
            # Query string with timestamp (same order as httpx will send)
            payload = urlencode(query_params)

        # 3. Generate signature
        hash_func = hashlib.sha512 if hmac_cfg.algorithm == "sha512" else hashlib.sha256

        signature = hmac.new(
            cred.secret.encode("utf-8"),
            payload.encode("utf-8"),
            hash_func,
        )

        if hmac_cfg.signature_format == "base64":
            sig_value = base64.b64encode(signature.digest()).decode("utf-8")
        else:
            sig_value = signature.hexdigest()

        # 4. Add signature to query params
        query_params[hmac_cfg.signature_field] = sig_value

        # 5. Set API key header if configured
        if hmac_cfg.key_header:
            headers[hmac_cfg.key_header] = cred.value

        _log_trace(
            "Applied HMAC auth (algorithm=%s, format=%s)",
            hmac_cfg.algorithm,
            hmac_cfg.signature_format,
        )

    def _log_request(self, request: httpx.Request) -> None:
        """Log request details at TRACE level."""
        _log_trace(">>> %s %s", request.method, request.url)

        # Log headers (redact sensitive ones)
        for name, value in request.headers.items():
            if name.lower() in ("authorization", "x-api-key", "cookie"):
                _log_trace(">>> %s: [REDACTED]", name)
            else:
                _log_trace(">>> %s: %s", name, value)

    def _log_response(self, response: httpx.Response, elapsed: float) -> None:
        """Log response details at TRACE level."""
        _log_trace("<<< %d %s (%.3fs)", response.status_code, response.reason_phrase, elapsed)
        _log_trace("<<< Content-Type: %s", response.headers.get("content-type", "unknown"))
        _log_trace("<<< Content-Length: %s", response.headers.get("content-length", "unknown"))
        # Log response body (truncate if too large)
        try:
            body_text = response.text
            if len(body_text) > 2000:
                _log_trace("<<< Body: %s... [truncated, %d bytes total]", body_text[:2000], len(body_text))
            else:
                _log_trace("<<< Body: %s", body_text)
        except Exception:
            _log_trace("<<< Body: [unable to decode]")

    def _execute_with_retry(
        self,
        request: httpx.Request,
        endpoint_config: EndpointConfig,
        timeout: float,
    ) -> RapiResponse:
        """Execute request with retry logic.

        Args:
            request: Prepared HTTP request.
            endpoint_config: Endpoint configuration.
            timeout: Request timeout in seconds.

        Returns:
            RapiResponse.

        Raises:
            RequestError: If all retries fail.
            ResponseTooLargeError: If response is too large.
        """
        last_error: Exception | None = None
        delay = self._limits.retry_delay

        for attempt in range(self._limits.max_retries + 1):
            if attempt > 0:
                log.debug("Retry %d/%d after %.1fs", attempt, self._limits.max_retries, delay)
                _log_trace("Waiting %.1fs before retry...", delay)
                time.sleep(delay)
                delay *= self._limits.retry_backoff

            _log_trace("Attempt %d/%d", attempt + 1, self._limits.max_retries + 1)

            try:
                start_time = time.monotonic()
                with httpx.Client(timeout=timeout, verify=self._ssl_context) as client:
                    response = client.send(request)
                elapsed = time.monotonic() - start_time

                self._log_response(response, elapsed)

                # Check response size
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > self._limits.max_response_size:
                    raise ResponseTooLargeError(
                        int(content_length),
                        self._limits.max_response_size,
                    )

                # Parse response
                return self._parse_response(response, endpoint_config, elapsed)

            except httpx.TimeoutException as e:
                log.warning("Request timeout (attempt %d): %s", attempt + 1, e)
                last_error = e
            except httpx.NetworkError as e:
                log.warning("Network error (attempt %d): %s", attempt + 1, e)
                last_error = e
            except ResponseTooLargeError:
                raise
            except httpx.HTTPStatusError as e:
                # Don't retry client errors (4xx), only server errors (5xx)
                if 400 <= e.response.status_code < 500:
                    return self._parse_response(e.response, endpoint_config, 0.0)
                log.warning("HTTP error (attempt %d): %s", attempt + 1, e)
                last_error = e

        # All retries exhausted
        raise RequestError(
            f"Request failed after {self._limits.max_retries + 1} attempts: {last_error}",
            retryable=False,
        )

    async def _execute_with_retry_async(
        self,
        request: httpx.Request,
        endpoint_config: EndpointConfig,
        timeout: float,
    ) -> RapiResponse:
        """Execute async request with retry logic.

        Args:
            request: Prepared HTTP request.
            endpoint_config: Endpoint configuration.
            timeout: Request timeout in seconds.

        Returns:
            RapiResponse.

        Raises:
            RequestError: If all retries fail.
            ResponseTooLargeError: If response is too large.
        """
        import asyncio

        last_error: Exception | None = None
        delay = self._limits.retry_delay

        for attempt in range(self._limits.max_retries + 1):
            if attempt > 0:
                log.debug("Retry %d/%d after %.1fs", attempt, self._limits.max_retries, delay)
                _log_trace("Waiting %.1fs before retry...", delay)
                await asyncio.sleep(delay)
                delay *= self._limits.retry_backoff

            _log_trace("Attempt %d/%d", attempt + 1, self._limits.max_retries + 1)

            try:
                start_time = time.monotonic()
                async with httpx.AsyncClient(timeout=timeout, verify=self._ssl_context) as client:
                    response = await client.send(request)
                elapsed = time.monotonic() - start_time

                self._log_response(response, elapsed)

                # Check response size
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > self._limits.max_response_size:
                    raise ResponseTooLargeError(
                        int(content_length),
                        self._limits.max_response_size,
                    )

                # Parse response
                return self._parse_response(response, endpoint_config, elapsed)

            except httpx.TimeoutException as e:
                log.warning("Request timeout (attempt %d): %s", attempt + 1, e)
                last_error = e
            except httpx.NetworkError as e:
                log.warning("Network error (attempt %d): %s", attempt + 1, e)
                last_error = e
            except ResponseTooLargeError:
                raise
            except httpx.HTTPStatusError as e:
                # Don't retry client errors (4xx)
                if 400 <= e.response.status_code < 500:
                    return self._parse_response(e.response, endpoint_config, 0.0)
                log.warning("HTTP error (attempt %d): %s", attempt + 1, e)
                last_error = e

        # All retries exhausted
        raise RequestError(
            f"Request failed after {self._limits.max_retries + 1} attempts: {last_error}",
            retryable=False,
        )

    def _parse_response(
        self,
        response: httpx.Response,
        endpoint_config: EndpointConfig,
        elapsed: float,
    ) -> RapiResponse:
        """Parse HTTP response into RapiResponse.

        Args:
            response: Raw HTTP response.
            endpoint_config: Endpoint configuration.
            elapsed: Request duration in seconds.

        Returns:
            Parsed RapiResponse.
        """
        text = response.text
        data: Any = None

        # Try to parse as JSON
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type or text.startswith(("{", "[")):
            try:
                data = response.json()
            except json.JSONDecodeError:
                log.debug("Response is not valid JSON")

        return RapiResponse(
            status_code=response.status_code,
            headers=dict(response.headers),
            data=data,
            text=text,
            elapsed=elapsed,
            endpoint_ref=endpoint_config.full_ref,
        )


def call(
    endpoint_ref: str,
    *args: Any,
    body: Any = None,
    headers: Mapping[str, str] | None = None,
    **kwargs: Any,
) -> RapiResponse:
    """Convenience function for quick API calls.

    Creates a temporary RapiClient and makes the call.

    Args:
        endpoint_ref: Endpoint reference.
        *args: Positional path parameters.
        body: Request body.
        headers: Runtime headers.
        **kwargs: Keyword parameters.

    Returns:
        RapiResponse.

    Examples:
        >>> from kstlib.rapi import call  # doctest: +SKIP
        >>> response = call("httpbin.get_ip")  # doctest: +SKIP
    """
    client = RapiClient()
    return client.call(endpoint_ref, *args, body=body, headers=headers, **kwargs)


async def call_async(
    endpoint_ref: str,
    *args: Any,
    body: Any = None,
    headers: Mapping[str, str] | None = None,
    **kwargs: Any,
) -> RapiResponse:
    """Convenience function for async API calls.

    Creates a temporary RapiClient and makes the async call.

    Args:
        endpoint_ref: Endpoint reference.
        *args: Positional path parameters.
        body: Request body.
        headers: Runtime headers.
        **kwargs: Keyword parameters.

    Returns:
        RapiResponse.

    Examples:
        >>> from kstlib.rapi import call_async  # doctest: +SKIP
        >>> response = await call_async("httpbin.get_ip")  # doctest: +SKIP
    """
    client = RapiClient()
    return await client.call_async(endpoint_ref, *args, body=body, headers=headers, **kwargs)


__all__ = [
    "RapiClient",
    "RapiResponse",
    "call",
    "call_async",
]
