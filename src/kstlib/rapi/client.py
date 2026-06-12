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
import jmespath
from box import Box
from jmespath.exceptions import JMESPathError

from kstlib.auth import AuthExpiredError
from kstlib.limits import get_rapi_limits
from kstlib.rapi.config import (
    _BODY_KEYWORD,
    _MAX_EXTRACT_EXPR_LENGTH,
    _MAX_EXTRACT_KEYS,
    _MAX_FIELD_NAME_LENGTH,
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
    RapiError,
    RequestError,
    ResponseTooLargeError,
)
from kstlib.ssl import build_ssl_context

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

from kstlib.logging import TRACE_LEVEL, get_logger

log = get_logger(__name__)

# Heuristic keywords used to detect HTTP 401 responses that signal
# access token expiration vs other 401 causes (permissions, audience
# mismatch, etc.). Match is case-insensitive against the response body.
_AUTH_EXPIRED_BODY_KEYWORDS: tuple[str, ...] = (
    "expired",
    "invalid_token",
    "token expired",
)

# WWW-Authenticate parameter value that signals token expiration per
# RFC 6750 Section 3 (Bearer error="invalid_token"). Match is
# case-insensitive against the header value.
_AUTH_EXPIRED_HEADER_MARKER: str = "invalid_token"


def _source_for_env_credential(cred_config: Mapping[str, Any]) -> str | None:
    """Derive a sanitized token source label for ``env`` credentials."""
    var = cred_config.get("var") or cred_config.get("var_key") or (cred_config.get("fields") or {}).get("key")
    return f"env:{var}" if var else None


def _source_for_file_credential(cred_config: Mapping[str, Any]) -> str | None:
    """Derive a sanitized token source label for ``file`` credentials."""
    path = cred_config.get("path")
    return str(path) if path else None


def _source_for_sops_credential(cred_config: Mapping[str, Any]) -> str | None:
    """Derive a sanitized token source label for ``sops`` credentials."""
    path = cred_config.get("path")
    return f"sops:{path}" if path else None


def _source_for_provider_credential(cred_config: Mapping[str, Any]) -> str | None:
    """Derive a sanitized token source label for ``provider`` credentials."""
    provider = cred_config.get("provider")
    return f"provider:{provider}" if provider else None


# Dispatch table for AuthExpiredError.token_source labels keyed by
# CredentialRecord.source. Each builder takes the raw credential
# config dict (possibly empty) and returns a sanitized label or
# ``None`` when the configured source is missing the expected key.
_TOKEN_SOURCE_BUILDERS: dict[str, Callable[[Mapping[str, Any]], str | None]] = {
    "env": _source_for_env_credential,
    "file": _source_for_file_credential,
    "sops": _source_for_sops_credential,
    "provider": _source_for_provider_credential,
}


def _hint_for_file_credential(cred_config: Mapping[str, Any]) -> str:
    """Build a re-authentication hint for ``file`` credentials."""
    path = str(cred_config.get("path", ""))
    if path and "credentials.json" in path:
        return "Re-authenticate with: sas-admin --profile $VIYA_HOST -k auth login -u <user>"
    if path:
        return f"Re-authenticate via your credentials file: {path}"
    return "Re-authenticate via your credentials file."


def _hint_for_env_credential(cred_config: Mapping[str, Any]) -> str:
    """Build a re-authentication hint for ``env`` credentials."""
    var = cred_config.get("var") or cred_config.get("var_key") or (cred_config.get("fields") or {}).get("key")
    if var:
        return f"Refresh and re-export env var: ${var}"
    return "Refresh and re-export your env-based credential."


def _hint_for_sops_credential(cred_config: Mapping[str, Any]) -> str:
    """Build a re-authentication hint for ``sops`` credentials."""
    path = cred_config.get("path", "")
    if path:
        return f"Update SOPS-encrypted file: {path}"
    return "Update your SOPS-encrypted credential file."


def _hint_for_provider_credential(cred_config: Mapping[str, Any]) -> str:
    """Build a re-authentication hint for ``provider`` credentials."""
    provider = cred_config.get("provider", "")
    if provider:
        return f"Re-authenticate via your provider: kstlib auth login --provider {provider}"
    return "Re-authenticate via your provider."


# Dispatch table for AuthExpiredError.suggested_action hints keyed
# by CredentialRecord.source. Each builder takes the raw credential
# config dict (possibly empty) and returns a sanitized hint string
# (never includes secret material, only source labels such as path
# / env var / provider name).
_AUTH_RENEW_HINT_BUILDERS: dict[str, Callable[[Mapping[str, Any]], str]] = {
    "file": _hint_for_file_credential,
    "env": _hint_for_env_credential,
    "sops": _hint_for_sops_credential,
    "provider": _hint_for_provider_credential,
}


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


# Heuristic field-extraction keys (collection shapes: HAL, SAS Viya, ...) back
# the ``.id`` / ``.ids`` / ``.count`` accessors when no per-endpoint ``extract:``
# directive (stored into ``RapiResponse.extracted``) applies. The default values
# live solely in the embedded ``kstlib.conf.yml`` (``rapi.extraction``); there is
# no in-code copy. ``get_config`` always layers that embedded section in, so a
# standard run resolves the documented defaults; users override the lists there
# (cascade: extracted > config). Each configured list is hardened on resolution
# (size, element length, and JMESPath validity for ``ids_paths``); an invalid
# override is rejected with a ``[SECURITY]`` warning and that list degrades to
# empty instead of crashing the client at init.


@dataclass(frozen=True, slots=True)
class _ExtractionKeys:
    """Resolved heuristic key lists for response field extraction."""

    id_keys: tuple[str, ...]
    ids_paths: tuple[str, ...]
    count_keys: tuple[str, ...]


def _load_rapi_extraction_config() -> Any:
    """Return the ``rapi.extraction`` config section, or an empty mapping.

    Falls back to an empty mapping when no kstlib configuration is loaded, so
    response extraction works standalone without any ``kstlib.conf.yml``
    present. Mirrors the cascade loader used by ``kstlib.secure.passwords``.
    """
    from kstlib.config import get_config
    from kstlib.config.exceptions import ConfigNotLoadedError

    try:
        cfg: Any = get_config()
    except ConfigNotLoadedError:
        return {}
    except Exception:  # any loader failure falls back to safe defaults
        log.debug("Could not load kstlib config; using default rapi extraction keys")
        return {}
    rapi_section: Any = cfg.get("rapi", {}) if hasattr(cfg, "get") else {}
    extraction: Any = rapi_section.get("extraction", {}) if hasattr(rapi_section, "get") else {}
    return extraction if hasattr(extraction, "get") else {}


def _extraction_item_violation(item: Any, *, max_len: int, compile_jmespath: bool) -> str | None:
    """Return a sanitized violation reason for one list element, or None if valid.

    The reason names the nature of the violation only, never the offending
    value, so it is safe to log.

    Args:
        item: Raw element to validate (expected to be a string).
        max_len: Maximum accepted length for the element.
        compile_jmespath: Whether the element must compile as a JMESPath expression.

    Returns:
        A short reason string when invalid, or None when the element is valid.
    """
    if not isinstance(item, str):
        return f"non-string entry (got {type(item).__name__})"
    if len(item) > max_len:
        return f"entry too long ({len(item)} > {max_len})"
    if compile_jmespath:
        try:
            jmespath.compile(item)
        except JMESPathError:
            return "invalid JMESPath expression"
    return None


def _extraction_list_violation(value: Any, *, max_len: int, compile_jmespath: bool) -> str | None:
    """Return a sanitized violation reason for an override list, or None if valid.

    Hardening for an external config input (defense in depth): rejects values
    that are not a non-empty list, oversized lists, non-string or overlong
    elements, and (when *compile_jmespath* is set) invalid JMESPath expressions.
    The returned reason names the nature of the violation only, never the
    offending value, so it is safe to log.

    Args:
        value: Raw configured list to validate.
        max_len: Maximum accepted length for a single element.
        compile_jmespath: Whether each element must compile as a JMESPath expression.

    Returns:
        A short reason string when invalid, or None when the list is valid.
    """
    if not isinstance(value, (list, tuple)):
        return f"not a list (got {type(value).__name__})"
    if not value:
        return "empty list"
    if len(value) > _MAX_EXTRACT_KEYS:
        return f"too many entries ({len(value)} > {_MAX_EXTRACT_KEYS})"
    for item in value:
        reason = _extraction_item_violation(item, max_len=max_len, compile_jmespath=compile_jmespath)
        if reason is not None:
            return reason
    return None


def _resolve_key_list(section: Any, key: str, *, max_len: int, compile_jmespath: bool) -> tuple[str, ...]:
    """Resolve and harden one extraction key list from the config section.

    Reads ``section[key]`` and returns it as a validated tuple. A missing list
    yields an empty tuple silently. A present but invalid list (failing the
    size, length, or JMESPath checks) is rejected with a ``[SECURITY]`` warning
    naming the list and the violation (never the offending value) and also
    yields an empty tuple, so a typo in a global override degrades the heuristic
    instead of crashing the client at init.

    Args:
        section: The ``rapi.extraction`` config mapping (or an empty mapping).
        key: Which list to resolve (``id_keys``, ``ids_paths``, ``count_keys``).
        max_len: Maximum accepted length for a single element.
        compile_jmespath: Whether each element must compile as a JMESPath expression.

    Returns:
        The validated list as a tuple, or an empty tuple when absent or invalid.
    """
    value: Any = section.get(key) if hasattr(section, "get") else None
    if value is None:
        _log_trace("extraction %s absent from config", key)
        return ()
    reason = _extraction_list_violation(value, max_len=max_len, compile_jmespath=compile_jmespath)
    if reason is not None:
        log.warning(
            "[SECURITY] rapi.extraction.%s rejected (%s); heuristic disabled for this list",
            key,
            reason,
        )
        return ()
    resolved = tuple(value)
    _log_trace("extraction %s resolved from config (%d keys)", key, len(resolved))
    return resolved


def _resolve_extraction_keys() -> _ExtractionKeys:
    """Resolve the heuristic key lists from the embedded/user ``rapi.extraction``.

    The default values live in the embedded ``kstlib.conf.yml``; ``get_config``
    always layers that base in, so a standard run resolves the documented
    defaults, a valid user override is honored, an invalid one is hardened away
    (empty + ``[SECURITY]`` warning), and a total config-load failure degrades
    every list to empty.
    """
    section = _load_rapi_extraction_config()
    return _ExtractionKeys(
        id_keys=_resolve_key_list(section, "id_keys", max_len=_MAX_FIELD_NAME_LENGTH, compile_jmespath=False),
        ids_paths=_resolve_key_list(section, "ids_paths", max_len=_MAX_EXTRACT_EXPR_LENGTH, compile_jmespath=True),
        count_keys=_resolve_key_list(section, "count_keys", max_len=_MAX_FIELD_NAME_LENGTH, compile_jmespath=False),
    )


def _first_present(obj: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    """Return the stringified value of the first present key in *obj*, or None."""
    for key in keys:
        value = obj.get(key)
        if value is not None:
            return str(value)
    return None


def _extracted_get(extracted: Mapping[str, Any], key: str) -> Any:
    """Read a key from an ``extract:`` result mapping, or None when absent.

    Typed against ``Mapping`` so the read goes through the annotated
    ``Mapping.get`` rather than python-box's unannotated ``Box.get``.
    """
    return extracted.get(key)


def _eval_extract(extract: dict[str, str] | None, data: Any, text: str) -> Box:
    """Evaluate an endpoint ``extract:`` map into a result Box.

    Each value is a JMESPath expression evaluated against the parsed body,
    except the reserved ``$body`` keyword which yields the raw response text.
    An expression that fails at evaluation stores None (never raises); the
    warning names the key only, never the extracted value or the body.
    """
    if not extract:
        return Box()
    result: dict[str, Any] = {}
    for key, expr in extract.items():
        if expr == _BODY_KEYWORD:
            _log_trace("extract %r resolved from $body keyword (type=str, len=%d)", key, len(text))
            result[key] = text
        elif data is None:
            _log_trace("extract %r: body not JSON, storing None", key)
            result[key] = None
        else:
            try:
                value = jmespath.search(expr, data)
            except JMESPathError:
                log.warning("extract: key %r expression failed to evaluate; storing None", key)
                result[key] = None
            else:
                _log_trace(
                    "extract %r resolved from JMESPath %r (type=%s, present=%s)",
                    key,
                    expr,
                    type(value).__name__,
                    value is not None,
                )
                result[key] = value
    return Box(result)


@dataclass
class RapiResponse:
    """Response from an API call.

    Beyond the raw ``status_code`` / ``headers`` / ``data`` / ``text`` fields,
    the response exposes convenience accessors that pull common identifiers out
    of HAL / SAS Viya style payloads (``.id``, ``.ids``, ``.count``,
    ``.next_url``, ``.has_next``), a JMESPath escape hatch (``.get``), and a
    strict JSON accessor (``.json``). The heuristic key lists are overridable
    via the ``rapi.extraction`` config section.

    Attributes:
        status_code: HTTP status code.
        headers: Response headers.
        data: Parsed JSON response (or None if not JSON).
        text: Raw response text.
        elapsed: Request duration in seconds.
        endpoint_ref: Full endpoint reference used.
        extracted: Values produced by an endpoint ``extract:`` directive
            (empty unless the endpoint defines one). Takes priority over the
            heuristic accessors.
        extraction_keys: Resolved heuristic key lists (internal; defaults to
            the built-in HAL/Viya keys, overridable via ``rapi.extraction``).

    Examples:
        >>> response = RapiResponse(status_code=200, data={"ip": "1.2.3.4"})
        >>> response.ok
        True
        >>> response.data["ip"]
        '1.2.3.4'
        >>> RapiResponse(status_code=200, data={"id": "abc-123"}).id
        'abc-123'
        >>> RapiResponse(status_code=200, data={"items": [{"id": "a"}, {"id": "b"}]}).ids
        ['a', 'b']
        >>> RapiResponse(status_code=204, data=None).ids
        []

    """

    status_code: int
    headers: dict[str, str] = field(default_factory=dict)
    data: Any = None
    text: str = ""
    elapsed: float = 0.0
    endpoint_ref: str = ""
    extracted: Box = field(default_factory=Box)
    extraction_keys: _ExtractionKeys = field(default_factory=_resolve_extraction_keys, repr=False)

    @property
    def ok(self) -> bool:
        """Return True if status code indicates success (2xx)."""
        return 200 <= self.status_code < 300

    @property
    def id(self) -> str | None:
        """Return the resource id, or None when it cannot be resolved.

        Resolution order: the ``extract:`` value stored under ``id``, then the
        configured ``id_keys`` on the root object, then the id of the first
        item for a list payload (with a warning). Returns None for a non-JSON
        body.
        """
        extracted_id = _extracted_get(self.extracted, "id")
        if extracted_id is not None:
            _log_trace("resolved .id from extract: directive")
            return str(extracted_id)
        if isinstance(self.data, dict):
            value = _first_present(self.data, self.extraction_keys.id_keys)
            if value is None:
                _log_trace(".id: no id_keys field matched on dict response")
            elif log.isEnabledFor(TRACE_LEVEL):
                matched = next((k for k in self.extraction_keys.id_keys if self.data.get(k) is not None), None)
                _log_trace("resolved .id from field %r", matched)
            return value
        if isinstance(self.data, list) and self.data:
            first = self.data[0]
            if isinstance(first, dict):
                value = _first_present(first, self.extraction_keys.id_keys)
                if value is not None:
                    log.warning(
                        "Multiple results on '%s', returning id of the first item",
                        self.endpoint_ref or "<response>",
                    )
                    if log.isEnabledFor(TRACE_LEVEL):
                        matched = next((k for k in self.extraction_keys.id_keys if first.get(k) is not None), None)
                        _log_trace("resolved .id from first list item field %r", matched)
                return value
            return None
        if self.data is None:
            log.warning(".id requested on a non-JSON response from '%s'", self.endpoint_ref or "<response>")
        return None

    @property
    def ids(self) -> list[str]:
        """Return all resource ids as a list of strings (empty when none).

        Resolution order: the ``extract:`` value stored under ``ids``, then the
        first configured ``ids_paths`` JMESPath that yields a non-empty list.
        Always returns a ``list[str]`` (never None), including [] for a non-JSON
        or empty body.
        """
        extracted_ids = _extracted_get(self.extracted, "ids")
        if isinstance(extracted_ids, list):
            _log_trace("resolved .ids from extract: directive (%d items)", len(extracted_ids))
            return [str(item) for item in extracted_ids]
        for path in self.extraction_keys.ids_paths:
            found = self._search(path)
            if isinstance(found, list) and found:
                _log_trace("resolved .ids from %r (%d items)", path, len(found))
                return [str(item) for item in found if item is not None]
        _log_trace(".ids: no ids_paths matched")
        return []

    @property
    def count(self) -> int | None:
        """Return the collection count, or None when not present.

        Resolution order: the ``extract:`` value stored under ``count``, then
        the configured ``count_keys`` on the root object. Booleans are not
        accepted as counts.
        """
        extracted_count = _extracted_get(self.extracted, "count")
        if isinstance(extracted_count, int) and not isinstance(extracted_count, bool):
            _log_trace("resolved .count from extract: directive -> %d", extracted_count)
            return extracted_count
        if isinstance(self.data, dict):
            for key in self.extraction_keys.count_keys:
                value = self.data.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    _log_trace("resolved .count from field %r -> %d", key, value)
                    return value
        _log_trace(".count: no count_keys field matched")
        return None

    @property
    def next_url(self) -> str | None:
        """Return the next-page URL, or None when there is none.

        Resolution order: the ``extract:`` value stored under ``next_url``,
        then the ``links[?rel=='next'].href`` JMESPath (HAL/Viya pagination).
        """
        extracted_next = _extracted_get(self.extracted, "next_url")
        if isinstance(extracted_next, str):
            _log_trace("resolved .next_url from extract: directive")
            return extracted_next
        found = self._search("links[?rel=='next'].href | [0]")
        if isinstance(found, str):
            _log_trace("resolved .next_url from JMESPath links[?rel=='next'].href")
            return found
        return None

    @property
    def has_next(self) -> bool:
        """Return True when the response advertises a next-page link."""
        return self.next_url is not None

    def get(self, expr: str) -> Any:
        """Evaluate a JMESPath expression against the parsed JSON body.

        Args:
            expr: JMESPath expression to evaluate.

        Returns:
            The matched value, or None when the expression matches nothing, the
            body is not JSON, or the expression is invalid (never raises).
        """
        return self._search(expr)

    def json(self) -> dict[str, Any] | list[Any]:
        """Return the parsed JSON body (dict or list).

        Returns:
            The parsed JSON object or array.

        Raises:
            RapiError: If the response body is not a JSON object or array.
        """
        if isinstance(self.data, dict):
            return self.data
        if isinstance(self.data, list):
            return self.data
        raise RapiError(
            f"Response body is not JSON for endpoint '{self.endpoint_ref or '<response>'}'",
            details={"status_code": self.status_code, "endpoint_ref": self.endpoint_ref},
        )

    def _search(self, expr: str) -> Any:
        """Run a JMESPath search against the body, swallowing errors."""
        if self.data is None:
            return None
        try:
            return jmespath.search(expr, self.data)
        except JMESPathError:
            log.warning("Invalid JMESPath expression: %s", expr)
            return None


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

        # Resolve heuristic extraction keys once from the embedded/user config
        # (rapi.extraction). Stamped onto every RapiResponse so the .id / .ids /
        # .count accessors stay pure (no config I/O on attribute access).
        self._extraction_keys = _resolve_extraction_keys()

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
            AuthExpiredError: If the response signals access token
                expiration (HTTP 401 with body keyword or
                ``WWW-Authenticate`` ``invalid_token`` marker).
                Terminal, not retried.
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
        return self._execute_with_retry(
            request,
            endpoint_config,
            effective_timeout,
            api_config=api_config,
            effective_server=effective_server,
        )

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
            AuthExpiredError: If the response signals access token
                expiration (HTTP 401 with body keyword or
                ``WWW-Authenticate`` ``invalid_token`` marker).
                Terminal, not retried.
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
            api_config=api_config,
            effective_server=effective_server,
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
        *,
        api_config: ApiConfig,
        effective_server: ServerConfig | None = None,
    ) -> RapiResponse:
        """Execute request with retry logic.

        Args:
            request: Prepared HTTP request.
            endpoint_config: Endpoint configuration.
            timeout: Request timeout in seconds.
            api_config: Resolved API configuration, forwarded to
                :meth:`_check_auth_expired` for credential-context
                lookup on HTTP 401 detection.
            effective_server: Optional resolved server profile,
                forwarded to :meth:`_check_auth_expired`.

        Returns:
            RapiResponse.

        Raises:
            AuthExpiredError: If the response signals access token
                expiration (HTTP 401 with expiration markers).
                Terminal, not retried.
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
                parsed = self._parse_response(response, endpoint_config, elapsed)
                self._check_auth_expired(parsed, api_config, effective_server)
                return parsed

            except ResponseTooLargeError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as e:
                result = self._handle_retry_error(e, attempt + 1, endpoint_config)
                if result is not None:
                    self._check_auth_expired(result, api_config, effective_server)
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
        *,
        api_config: ApiConfig,
        effective_server: ServerConfig | None = None,
    ) -> RapiResponse:
        """Execute async request with retry logic.

        Args:
            request: Prepared HTTP request.
            endpoint_config: Endpoint configuration.
            timeout: Request timeout in seconds.
            api_config: Resolved API configuration, forwarded to
                :meth:`_check_auth_expired` for credential-context
                lookup on HTTP 401 detection.
            effective_server: Optional resolved server profile,
                forwarded to :meth:`_check_auth_expired`.

        Returns:
            RapiResponse.

        Raises:
            AuthExpiredError: If the response signals access token
                expiration (HTTP 401 with expiration markers).
                Terminal, not retried.
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
                parsed = self._parse_response(response, endpoint_config, elapsed)
                self._check_auth_expired(parsed, api_config, effective_server)
                return parsed

            except ResponseTooLargeError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as e:
                result = self._handle_retry_error(e, attempt + 1, endpoint_config)
                if result is not None:
                    self._check_auth_expired(result, api_config, effective_server)
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
            extracted=_eval_extract(endpoint_config.extract, data, text),
            extraction_keys=self._extraction_keys,
        )

    def _check_auth_expired(
        self,
        response: RapiResponse,
        api_config: ApiConfig,
        effective_server: ServerConfig | None,
    ) -> None:
        """Detect HTTP 401 indicating access token expiration and raise.

        Inspects an already-parsed response and, when the heuristic
        matches, raises :class:`AuthExpiredError` with a contextual
        hint derived from the credentials currently active for this
        request. Non-401 responses and 401 responses without
        expiration markers are left untouched (backward compat
        preserved : the caller receives a ``RapiResponse(ok=False)``
        for non-expiration 401s).

        Heuristic (any match triggers detection) :

        - response body (case-insensitive) contains one of the
          keywords listed in ``_AUTH_EXPIRED_BODY_KEYWORDS``
        - response ``WWW-Authenticate`` header (case-insensitive)
          contains ``invalid_token`` (RFC 6750 Bearer
          error="invalid_token")

        Args:
            response: Parsed ``RapiResponse`` to inspect.
            api_config: Resolved API configuration used to send the
                request.
            effective_server: Optional resolved server profile
                providing the effective credentials for this call.
                ``None`` when falling back to the static
                ``api_config``.

        Raises:
            AuthExpiredError: If the response signals access token
                expiration via body keywords or ``WWW-Authenticate``
                header. The exception carries a sanitized
                ``token_source`` label and a contextual
                ``suggested_action`` hint.

        """
        if response.status_code != 401:
            return

        body_lower = (response.text or "").lower()
        has_body_keyword = any(kw in body_lower for kw in _AUTH_EXPIRED_BODY_KEYWORDS)

        www_auth_value = response.headers.get("www-authenticate") or response.headers.get(
            "WWW-Authenticate",
            "",
        )
        has_header_marker = _AUTH_EXPIRED_HEADER_MARKER in www_auth_value.lower()

        if not (has_body_keyword or has_header_marker):
            # Backward compat: 401 without expiration markers returns
            # a RapiResponse(ok=False) as before, not AuthExpiredError.
            return

        cred, credential_name = self._resolve_active_credential(api_config, effective_server)
        token_source = self._derive_token_source(cred, credential_name, api_config, effective_server)
        suggested_action = self._auth_renew_hint(cred, credential_name, api_config, effective_server)

        # SECURITY (rules/code-rules.md Section 10) : tagged WARNING
        # before raise, sanitized payload only (status code, content
        # type, credential source label). NEVER log token value,
        # response body, or Authorization header.
        log.warning(
            "[SECURITY] AuthExpired detected on endpoint %s (status=%d, content-type=%s, cred.source=%s)",
            response.endpoint_ref,
            response.status_code,
            response.headers.get("content-type", "unknown"),
            cred.source if cred else "unknown",
        )

        # User-facing ERROR (visible to apps consuming kstlib as a
        # library) with the actionable re-authentication hint. The
        # [SECURITY] WARNING above stays for audit/observability;
        # this log targets human operators who need a clear next
        # step. Sanitization rules apply equally: hint references
        # source labels only (file path / env var name / SOPS path
        # / provider name), never the token value.
        log.error(
            "Access token expired on endpoint '%s'. %s",
            response.endpoint_ref,
            suggested_action or "Please re-authenticate via your usual channel.",
        )

        raise AuthExpiredError(
            f"Access token expired or invalidated (HTTP 401) on endpoint '{response.endpoint_ref}'.",
            token_source=token_source,
            suggested_action=suggested_action,
        )

    def _resolve_active_credential(
        self,
        api_config: ApiConfig,
        effective_server: ServerConfig | None,
    ) -> tuple[CredentialRecord | None, str | None]:
        """Re-derive the credential active for the current request.

        Used by :meth:`_check_auth_expired` to source a contextual
        hint without mutating the request flow. Resolution errors
        are swallowed so 401 detection always raises a meaningful
        ``AuthExpiredError`` rather than being masked by a stale
        credential resolution failure.

        Returns:
            Tuple ``(cred, credential_name)`` where ``cred`` is the
            resolved record (or ``None`` on failure) and
            ``credential_name`` is the registered name (or a
            ``server.<profile>`` hint for inline server
            credentials).

        """
        try:
            if effective_server and effective_server.credentials:
                cred = self._credential_resolver.resolve_inline(
                    effective_server.credentials,
                    name_hint=f"server.{effective_server.name}",
                )
                return cred, f"server.{effective_server.name}"
            if api_config.credentials:
                cred = self._credential_resolver.resolve(api_config.credentials)
                return cred, api_config.credentials
        except Exception:
            # Credential resolution may fail between send time and
            # 401 detection (env var unset, file removed, etc.). Fall
            # back to a generic hint rather than mask the expiration.
            log.debug("Credential re-resolution failed during AuthExpired detection", exc_info=True)
        return None, None

    def _credential_config(
        self,
        credential_name: str | None,
        effective_server: ServerConfig | None,
    ) -> Mapping[str, Any] | None:
        """Return the raw credential configuration dict for hint derivation.

        Args:
            credential_name: Registered name of the credential, or
                ``server.<profile>`` when the credential is declared
                inline on a server profile.
            effective_server: Optional resolved server profile.

        Returns:
            The credential config dict, or ``None`` when no source
            is available (caller falls back to a generic hint).

        """
        if effective_server and effective_server.credentials:
            return effective_server.credentials
        if credential_name:
            cfg = self._credential_resolver._config.get(credential_name)  # noqa: SLF001
            if isinstance(cfg, dict):
                return cfg
        return None

    def _derive_token_source(
        self,
        cred: CredentialRecord | None,
        credential_name: str | None,
        api_config: ApiConfig,
        effective_server: ServerConfig | None,
    ) -> str | None:
        """Build a sanitized label identifying where the access token came from.

        Used as the ``token_source`` attribute of
        :class:`AuthExpiredError`. Returns ``None`` when no
        credential context is available so callers do not surface a
        misleading default.

        Examples of generated labels :

        - ``"~/.sas/credentials.json"`` (file-based, SAS Viya)
        - ``"env:KSTLIB_TOKEN"`` (environment variable)
        - ``"sops:secrets/viya.sops.json"`` (SOPS-encrypted)
        - ``"provider:corporate"`` (kstlib.auth OIDC provider)

        """
        del api_config  # reserved for future per-API token source resolution
        if cred is None:
            return None

        cred_config = self._credential_config(credential_name, effective_server)
        fallback = f"{cred.source}:{credential_name}" if credential_name else None

        if cred_config is None:
            return fallback

        builder = _TOKEN_SOURCE_BUILDERS.get(cred.source)
        if builder is None:
            return fallback
        return builder(cred_config) or fallback

    def _auth_renew_hint(
        self,
        cred: CredentialRecord | None,
        credential_name: str | None,
        api_config: ApiConfig,
        effective_server: ServerConfig | None,
    ) -> str:
        """Build a contextual re-authentication hint for the user.

        Used as the ``suggested_action`` attribute of
        :class:`AuthExpiredError`. The hint is best-effort and
        NEVER includes secret material : it only references
        credential sources (file path, env var name, SOPS file
        path, provider name).

        """
        del api_config  # reserved for future per-API hint customization
        if cred is None:
            return "Re-authenticate via your usual channel."

        cred_config = self._credential_config(credential_name, effective_server) or {}
        builder = _AUTH_RENEW_HINT_BUILDERS.get(cred.source)
        if builder is None:
            return "Re-authenticate via your usual channel."
        return builder(cred_config)


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
