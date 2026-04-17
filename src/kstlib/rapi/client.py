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
    MultipartConfig,
    RapiConfigManager,
    ServerConfig,
    load_rapi_config,
)
from kstlib.rapi.credentials import CredentialRecord, CredentialResolver
from kstlib.rapi.exceptions import (
    ConfirmationRequiredError,
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
class FilePayload:
    """Carrier for file upload data (multipart mode).

    Use this to upload file content programmatically without a file on disk.

    Attributes:
        filename: Original filename (used in Content-Disposition).
        data: Raw file bytes.
        content_type: MIME type of the file.
        field_name: Form field name for the file part.

    Examples:
        >>> payload = FilePayload(
        ...     filename="report.csv",
        ...     data=b"col1,col2",
        ...     content_type="text/csv",
        ... )
        >>> payload.field_name
        'file'

    """

    filename: str
    data: bytes
    content_type: str
    field_name: str = "file"


def _validate_safeguard(
    endpoint_config: EndpointConfig,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    confirm: str | None,
) -> None:
    """Validate safeguard confirmation for dangerous endpoints.

    Args:
        endpoint_config: Endpoint configuration.
        args: Positional arguments for path/safeguard substitution.
        kwargs: Keyword arguments for path/safeguard substitution.
        confirm: Confirmation string provided by caller.

    Raises:
        ConfirmationRequiredError: If safeguard is required but confirm is missing or wrong.

    """
    if endpoint_config.safeguard is None:
        return

    expected = endpoint_config.build_safeguard(*args, **kwargs)
    if expected is None:
        return

    if confirm is None:
        raise ConfirmationRequiredError(endpoint_config.full_ref, expected=expected)

    if confirm != expected:
        raise ConfirmationRequiredError(endpoint_config.full_ref, expected=expected, actual=confirm)


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
        confirm: str | None = None,
        server: str | None = None,
        **kwargs: Any,
    ) -> RapiResponse:
        """Make a synchronous API call.

        Args:
            endpoint_ref: Endpoint reference (full: api.endpoint or short: endpoint).
            *args: Positional arguments for path parameters.
            body: Request body (dict for JSON, str for raw).
            headers: Runtime headers (override service/endpoint headers).
            timeout: Request timeout (uses config default if None).
            confirm: Confirmation string for dangerous endpoints with safeguard.
            server: Optional named server profile from ``rapi.servers`` to
                use for this call. Overrides any ``server:`` directive set
                at the endpoint or file level in the YAML config. Cascade:
                runtime ``server`` > endpoint ``server:`` > file ``server:``
                > static ``ApiConfig`` (no server).
            **kwargs: Keyword arguments for path parameters and query params.

        Returns:
            RapiResponse with parsed data.

        Raises:
            ConfirmationRequiredError: If safeguard requires confirmation.
            RequestError: If request fails after retries.
            ResponseTooLargeError: If response exceeds max size.
            ServerNotFoundError: If ``server`` (or any cascading directive)
                does not exist in ``rapi.servers``.

        Examples:
            >>> client = RapiClient()  # doctest: +SKIP
            >>> client.call("httpbin.get_ip")  # doctest: +SKIP
            >>> client.call("httpbin.delayed", 5)  # doctest: +SKIP
            >>> client.call("httpbin.post_data", body={"key": "value"})  # doctest: +SKIP
            >>> client.call("admin.delete_user", userId="123", confirm="DELETE USER 123")  # doctest: +SKIP
            >>> client.call("github.repos-list", server="github")  # doctest: +SKIP

        """
        log.debug("Calling endpoint: %s", endpoint_ref)

        # Resolve endpoint
        api_config, endpoint_config = self._config_manager.resolve(endpoint_ref)
        _log_trace("Resolved to: %s", endpoint_config.full_ref)

        # Resolve effective server profile (cascade: runtime > endpoint > file > None)
        effective_server = self._config_manager.resolve_effective_server(
            api_config,
            endpoint_config,
            runtime_server=server,
        )
        if effective_server is not None:
            _log_trace("Effective server profile: %s", effective_server.name)

        # Validate safeguard before proceeding
        _validate_safeguard(endpoint_config, args, kwargs, confirm)

        # Build request
        request = self._build_request(
            api_config,
            endpoint_config,
            args,
            kwargs,
            body,
            headers,
            effective_server=effective_server,
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
        confirm: str | None = None,
        server: str | None = None,
        **kwargs: Any,
    ) -> RapiResponse:
        """Make an asynchronous API call.

        Args:
            endpoint_ref: Endpoint reference (full: api.endpoint or short: endpoint).
            *args: Positional arguments for path parameters.
            body: Request body (dict for JSON, str for raw).
            headers: Runtime headers (override service/endpoint headers).
            timeout: Request timeout (uses config default if None).
            confirm: Confirmation string for dangerous endpoints with safeguard.
            server: Optional named server profile from ``rapi.servers`` to
                use for this call. See :meth:`call` for cascade rules.
            **kwargs: Keyword arguments for path parameters and query params.

        Returns:
            RapiResponse with parsed data.

        Raises:
            ConfirmationRequiredError: If safeguard requires confirmation.
            RequestError: If request fails after retries.
            ResponseTooLargeError: If response exceeds max size.
            ServerNotFoundError: If ``server`` (or any cascading directive)
                does not exist in ``rapi.servers``.

        """
        log.debug("Calling endpoint (async): %s", endpoint_ref)

        # Resolve endpoint
        api_config, endpoint_config = self._config_manager.resolve(endpoint_ref)
        _log_trace("Resolved to: %s", endpoint_config.full_ref)

        # Resolve effective server profile (cascade: runtime > endpoint > file > None)
        effective_server = self._config_manager.resolve_effective_server(
            api_config,
            endpoint_config,
            runtime_server=server,
        )
        if effective_server is not None:
            _log_trace("Effective server profile: %s", effective_server.name)

        # Validate safeguard before proceeding
        _validate_safeguard(endpoint_config, args, kwargs, confirm)

        # Build request
        request = self._build_request(
            api_config,
            endpoint_config,
            args,
            kwargs,
            body,
            headers,
            effective_server=effective_server,
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

        # Start with non-None defaults; None means "available but not sent"
        query_params = {k: v for k, v in endpoint_config.query.items() if v is not None}
        path_params: set[str] = set()

        for match in re.finditer(r"\{([a-zA-Z_][a-zA-Z0-9_]*|\d+)\}", endpoint_config.path):
            param = match.group(1)
            if not param.isdigit():
                path_params.add(param)

        for key, value in kwargs.items():
            if key not in path_params:
                if value is None:
                    query_params.pop(key, None)
                else:
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

    def _prepare_multipart(
        self,
        body: Any,
        endpoint_config: EndpointConfig,
    ) -> list[tuple[str, tuple[str, bytes, str]]]:
        """Prepare multipart file upload from body.

        Args:
            body: Body value (expected: "@filepath" string or FilePayload).
            endpoint_config: Endpoint configuration with optional multipart config.

        Returns:
            httpx files parameter: list of (field_name, (filename, data, content_type)).

        Raises:
            RequestError: If body is not a valid file reference for multipart.

        """
        import mimetypes
        from pathlib import Path

        mp_config = endpoint_config.multipart or MultipartConfig()

        if isinstance(body, FilePayload):
            _log_trace(
                "Multipart upload (FilePayload): field=%s, file=%s, type=%s, size=%d",
                body.field_name,
                body.filename,
                body.content_type,
                len(body.data),
            )
            return [(body.field_name, (body.filename, body.data, body.content_type))]

        if not isinstance(body, str) or not body.startswith("@"):
            raise RequestError(
                f"Multipart endpoint '{endpoint_config.full_ref}' requires a file body "
                f"(@/path/to/file) or FilePayload, got: {type(body).__name__}",
                retryable=False,
            )

        filepath = Path(body[1:])
        if not filepath.exists():
            raise RequestError(
                f"File not found for multipart upload: {filepath}",
                retryable=False,
            )

        file_data = filepath.read_bytes()

        # Validate file size
        limits = get_rapi_limits()
        if len(file_data) > limits.max_upload_size:
            raise RequestError(
                f"File too large for upload: {len(file_data)} bytes (max: {limits.max_upload_size_display})",
                retryable=False,
            )

        filename = filepath.name
        content_type = mp_config.content_type
        if content_type is None:
            guessed, _ = mimetypes.guess_type(filename)
            content_type = guessed or "application/octet-stream"

        field_name = mp_config.field_name

        _log_trace(
            "Multipart upload: field=%s, file=%s, type=%s, size=%d bytes",
            field_name,
            filename,
            content_type,
            len(file_data),
        )

        return [(field_name, (filename, file_data, content_type))]

    def _build_request(
        self,
        api_config: ApiConfig,
        endpoint_config: EndpointConfig,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        body: Any,
        runtime_headers: Mapping[str, str] | None,
        *,
        effective_server: ServerConfig | None = None,
    ) -> httpx.Request:
        """Build HTTP request from configuration.

        Args:
            api_config: API service configuration.
            endpoint_config: Endpoint configuration.
            args: Positional path parameters.
            kwargs: Keyword parameters (path + query).
            body: Request body.
            runtime_headers: Runtime header overrides.
            effective_server: Optional resolved server profile that
                overrides ``api_config.base_url`` and contributes
                ``credentials`` + ``headers`` to the request build.
                When None, the static ApiConfig is used (backward
                compatible behavior).

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

        # Server profile (when present) overrides the static api_config base_url
        base_url = effective_server.base_url if effective_server else api_config.base_url
        url = f"{base_url}{path}"

        # Security: reject null bytes in URL to prevent injection
        if "\x00" in url:
            raise RequestError("Null bytes not allowed in URL", retryable=False)

        # Security: validate URL scheme to prevent SSRF via config injection
        if not url.lower().startswith(("http://", "https://")):
            raise RequestError(f"Invalid URL scheme (only http/https allowed): {url}", retryable=False)

        # Extract query params from kwargs
        query_params = self._extract_query_params(endpoint_config, kwargs)

        _log_trace("Final URL: %s", url)
        if query_params:
            _log_trace("Query params: %s", query_params)

        # Merge headers - cascade: service < server < endpoint < runtime
        merged_headers = self._merge_headers(
            api_config.headers,
            endpoint_config.headers,
            dict(runtime_headers) if runtime_headers else {},
            server_headers=effective_server.headers if effective_server else None,
        )

        # Detect multipart mode from merged Content-Type header
        is_multipart = "multipart/form-data" in merged_headers.get("Content-Type", "").lower()

        if is_multipart:
            _log_trace("Multipart mode detected from Content-Type header")
            # Multipart file upload: use httpx files= parameter
            files_param = self._prepare_multipart(body, endpoint_config)

            # Remove Content-Type: httpx generates it with the boundary
            merged_headers.pop("Content-Type", None)
            merged_headers.pop("content-type", None)

            # Apply auth (no body content for HMAC signing in multipart mode).
            # Auth is applied if either the static ApiConfig or the effective
            # server profile provides credentials, and the endpoint allows it.
            if endpoint_config.auth and ((effective_server and effective_server.credentials) or api_config.credentials):
                self._apply_auth(
                    merged_headers,
                    api_config,
                    query_params,
                    None,
                    effective_server=effective_server,
                )

            request = httpx.Request(
                method=endpoint_config.method,
                url=url,
                params=query_params if query_params else None,
                headers=merged_headers,
                files=files_param,
            )

            # Log multipart request structure at TRACE level
            generated_ct = request.headers.get("content-type", "")
            _log_trace("Multipart Content-Type (generated): %s", generated_ct)
            for field_name, (filename, data, ct) in files_param:
                _log_trace(
                    "Multipart part: field=%s, filename=%s, content_type=%s, size=%d bytes",
                    field_name,
                    filename,
                    ct,
                    len(data),
                )
        else:
            # Normal body processing
            content = self._prepare_body(body, merged_headers)

            # Apply authentication (may modify headers and query_params for HMAC).
            # Skip auth if endpoint explicitly disables it (auth: false).
            # Credentials may come from either the static ApiConfig or the
            # effective server profile.
            if endpoint_config.auth and ((effective_server and effective_server.credentials) or api_config.credentials):
                self._apply_auth(
                    merged_headers,
                    api_config,
                    query_params,
                    content,
                    effective_server=effective_server,
                )

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
        *,
        server_headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Merge headers from up to four levels.

        Cascade order (later overrides earlier):
        ``service < server < endpoint < runtime``

        The ``server`` level is inserted between service and endpoint
        because the server profile describes "what the API server itself
        expects" (e.g. ``Accept: application/vnd.github+json``), while
        the endpoint and runtime levels carry per-call overrides.

        Args:
            service_headers: Service-level headers (lowest priority).
            endpoint_headers: Endpoint-level headers.
            runtime_headers: Runtime headers (highest priority).
            server_headers: Optional headers from the effective server
                profile, layered between service and endpoint headers.

        Returns:
            Merged headers dictionary.

        """
        merged: dict[str, str] = {}
        merged.update(service_headers)
        if server_headers:
            merged.update(server_headers)
        merged.update(endpoint_headers)
        merged.update(runtime_headers)

        _log_trace(
            "Headers merged: service=%d, server=%d, endpoint=%d, runtime=%d -> total=%d",
            len(service_headers),
            len(server_headers or {}),
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
        *,
        effective_server: ServerConfig | None = None,
    ) -> None:
        """Apply authentication to headers and query params.

        When ``effective_server`` is provided and carries inline
        credentials, those are resolved via
        :meth:`CredentialResolver.resolve_inline` and used instead of
        the static ``api_config.credentials`` reference. The auth type
        also follows the server profile when set.

        Args:
            headers: Headers dict to modify.
            api_config: API config with credentials reference (fallback).
            query_params: Query params dict to modify (for HMAC signing).
            body_content: Request body content (for HMAC signing).
            effective_server: Optional resolved server profile providing
                inline credentials and/or auth type override.

        """
        # Resolve credentials: server profile takes precedence over static
        # api_config.credentials, and uses inline dict resolution.
        cred: CredentialRecord | None = None
        if effective_server and effective_server.credentials:
            try:
                cred = self._credential_resolver.resolve_inline(
                    effective_server.credentials,
                    name_hint=f"server.{effective_server.name}",
                )
            except Exception as e:
                log.warning(
                    "Failed to resolve inline credentials for server '%s': %s",
                    effective_server.name,
                    e,
                )
                return
        elif api_config.credentials:
            try:
                cred = self._credential_resolver.resolve(api_config.credentials)
            except Exception as e:
                log.warning("Failed to resolve credential '%s': %s", api_config.credentials, e)
                return
        else:
            return

        # Auth type cascade: server profile > api_config > default "bearer"
        if effective_server and effective_server.auth:
            auth_type = effective_server.auth
        else:
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

    def _check_response_size(self, response: httpx.Response) -> None:
        """Validate response size against configured limits.

        Args:
            response: HTTP response to check.

        Raises:
            ResponseTooLargeError: If response exceeds max size.

        """
        content_length = response.headers.get("content-length")
        if content_length and int(content_length) > self._limits.max_response_size:
            raise ResponseTooLargeError(
                int(content_length),
                self._limits.max_response_size,
            )
        actual_size = len(response.content)
        if actual_size > self._limits.max_response_size:
            raise ResponseTooLargeError(actual_size, self._limits.max_response_size)

    def _handle_retry_error(
        self,
        exc: Exception,
        attempt: int,
        endpoint_config: EndpointConfig,
    ) -> RapiResponse | None:
        """Handle a retryable error, returning a response for 4xx or None to continue.

        Args:
            exc: The caught exception.
            attempt: Current attempt number (1-based).
            endpoint_config: Endpoint configuration for parsing 4xx responses.

        Returns:
            RapiResponse for 4xx client errors, None to continue retrying.

        """
        if isinstance(exc, httpx.TimeoutException):
            log.warning("Request timeout (attempt %d): %s", attempt, exc)
        elif isinstance(exc, httpx.NetworkError):
            log.warning("Network error (attempt %d): %s", attempt, exc)
        elif isinstance(exc, httpx.HTTPStatusError):
            if 400 <= exc.response.status_code < 500:
                return self._parse_response(exc.response, endpoint_config, 0.0)
            log.warning("HTTP error (attempt %d): %s", attempt, exc)
        return None

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
                with httpx.Client(timeout=timeout, verify=self._ssl_context, follow_redirects=False) as client:
                    response = client.send(request)
                elapsed = time.monotonic() - start_time

                self._log_response(response, elapsed)
                self._check_response_size(response)
                return self._parse_response(response, endpoint_config, elapsed)

            except ResponseTooLargeError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as e:
                result = self._handle_retry_error(e, attempt + 1, endpoint_config)
                if result is not None:
                    return result
                last_error = e

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
                async with httpx.AsyncClient(
                    timeout=timeout, verify=self._ssl_context, follow_redirects=False
                ) as client:
                    response = await client.send(request)
                elapsed = time.monotonic() - start_time

                self._log_response(response, elapsed)
                self._check_response_size(response)
                return self._parse_response(response, endpoint_config, elapsed)

            except ResponseTooLargeError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as e:
                result = self._handle_retry_error(e, attempt + 1, endpoint_config)
                if result is not None:
                    return result
                last_error = e

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

        # Try to parse as JSON (only when content-type confirms it)
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type or ("application/vnd." in content_type and "+json" in content_type):
            try:
                data = response.json()
            except json.JSONDecodeError:
                log.debug("Response is not valid JSON despite content-type")

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
    confirm: str | None = None,
    server: str | None = None,
    **kwargs: Any,
) -> RapiResponse:
    """Make a quick synchronous API call using a temporary RapiClient.

    Creates a temporary RapiClient and makes the call.

    Args:
        endpoint_ref: Endpoint reference.
        *args: Positional path parameters.
        body: Request body.
        headers: Runtime headers.
        confirm: Confirmation string for dangerous endpoints with safeguard.
        server: Optional named server profile from ``rapi.servers``
            (see :meth:`RapiClient.call` for cascade rules).
        **kwargs: Keyword parameters.

    Returns:
        RapiResponse.

    Examples:
        >>> from kstlib.rapi import call  # doctest: +SKIP
        >>> response = call("httpbin.get_ip")  # doctest: +SKIP
        >>> response = call("github.repos-list", server="github")  # doctest: +SKIP

    """
    client = RapiClient()
    return client.call(
        endpoint_ref,
        *args,
        body=body,
        headers=headers,
        confirm=confirm,
        server=server,
        **kwargs,
    )


async def call_async(
    endpoint_ref: str,
    *args: Any,
    body: Any = None,
    headers: Mapping[str, str] | None = None,
    confirm: str | None = None,
    server: str | None = None,
    **kwargs: Any,
) -> RapiResponse:
    """Make a quick asynchronous API call using a temporary RapiClient.

    Creates a temporary RapiClient and makes the async call.

    Args:
        endpoint_ref: Endpoint reference.
        *args: Positional path parameters.
        body: Request body.
        headers: Runtime headers.
        confirm: Confirmation string for dangerous endpoints with safeguard.
        server: Optional named server profile from ``rapi.servers``
            (see :meth:`RapiClient.call` for cascade rules).
        **kwargs: Keyword parameters.

    Returns:
        RapiResponse.

    Examples:
        >>> from kstlib.rapi import call_async  # doctest: +SKIP
        >>> response = await call_async("httpbin.get_ip")  # doctest: +SKIP

    """
    client = RapiClient()
    return await client.call_async(
        endpoint_ref,
        *args,
        body=body,
        headers=headers,
        confirm=confirm,
        server=server,
        **kwargs,
    )


__all__ = [
    "RapiClient",
    "RapiResponse",
    "call",
    "call_async",
]
