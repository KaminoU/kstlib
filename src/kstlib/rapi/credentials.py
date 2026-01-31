"""Credential resolver for RAPI module.

This module provides multi-source credential resolution for REST API calls.
Supports environment variables, files (JSON/YAML), SOPS-encrypted files,
and kstlib.auth providers.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from kstlib.rapi.exceptions import CredentialError

if TYPE_CHECKING:
    from collections.abc import Mapping

log = logging.getLogger(__name__)

# Pattern for jq-like path extraction: .foo.bar[0].baz or .foo["key-with-dash"]
# Supports: .key, [0], ["quoted-key"], ['quoted-key']
_JQ_PATH_PATTERN = re.compile(r'\.?([a-zA-Z_][a-zA-Z0-9_]*|\[\d+\]|\["[^"]+"\]|\[\'[^\']+\'\])')

# Deep defense limits for fields mapping
_MAX_FIELDS = 20  # Max number of fields in a mapping
_MAX_FIELD_NAME_LENGTH = 64  # Max characters for field name
_MAX_FIELD_VALUE_SIZE = 10 * 1024  # 10KB max per field value
_FIELD_NAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


@dataclass(frozen=True, slots=True)
class CredentialRecord:
    """Resolved credential with metadata.

    Attributes:
        value: Primary credential value (token, API key).
        secret: Secondary credential value (API secret for signing).
        source: Source type that provided this credential.
        expires_at: Expiration timestamp (if known).
        extras: Additional credential fields (passphrase, etc.).

    Examples:
        >>> record = CredentialRecord(value="token123", source="env")
        >>> record.value
        'token123'
        >>> record = CredentialRecord(
        ...     value="key", secret="secret", source="sops",
        ...     extras={"passphrase": "pass123"}
        ... )
        >>> record.extras.get("passphrase")
        'pass123'
    """

    value: str
    secret: str | None = None
    source: str = "unknown"
    expires_at: float | None = None
    extras: dict[str, str] = field(default_factory=dict)


def _validate_field_name(name: str, credential_name: str) -> None:
    """Validate a field name for security.

    Args:
        name: Field name to validate.
        credential_name: Credential name for error messages.

    Raises:
        CredentialError: If field name is invalid.
    """
    if not name:
        raise CredentialError(credential_name, "Empty field name in fields mapping")

    if len(name) > _MAX_FIELD_NAME_LENGTH:
        raise CredentialError(
            credential_name,
            f"Field name '{name[:20]}...' exceeds max length ({_MAX_FIELD_NAME_LENGTH})",
        )

    if not _FIELD_NAME_PATTERN.match(name):
        raise CredentialError(
            credential_name,
            f"Invalid field name '{name}': must be alphanumeric with underscores",
        )


def _validate_field_value(value: str, field_name: str, credential_name: str) -> None:
    """Validate a field value for security.

    Args:
        value: Field value to validate.
        field_name: Field name for error messages.
        credential_name: Credential name for error messages.

    Raises:
        CredentialError: If field value is invalid.
    """
    if len(value) > _MAX_FIELD_VALUE_SIZE:
        raise CredentialError(
            credential_name,
            f"Field '{field_name}' value exceeds max size ({_MAX_FIELD_VALUE_SIZE} bytes)",
        )


def _validate_fields_mapping(
    fields: Mapping[str, str],
    credential_name: str,
) -> None:
    """Validate entire fields mapping for security.

    Args:
        fields: Fields mapping to validate.
        credential_name: Credential name for error messages.

    Raises:
        CredentialError: If mapping is invalid.
    """
    if len(fields) > _MAX_FIELDS:
        raise CredentialError(
            credential_name,
            f"Too many fields in mapping ({len(fields)} > {_MAX_FIELDS})",
        )

    if "key" not in fields:
        raise CredentialError(
            credential_name,
            "Missing required 'key' in fields mapping",
        )

    for name, source_field in fields.items():
        _validate_field_name(name, credential_name)
        _validate_field_name(source_field, credential_name)


class CredentialResolver:
    """Resolve credentials from multiple sources.

    Supported credential types:
    - env: Environment variable
    - file: JSON/YAML file with jq-like path extraction
    - sops: SOPS-encrypted file
    - provider: kstlib.auth provider (OAuth2/OIDC)

    Args:
        credentials_config: Credentials section from config.

    Examples:
        >>> resolver = CredentialResolver({"github": {"type": "env", "var": "GITHUB_TOKEN"}})
        >>> record = resolver.resolve("github")  # doctest: +SKIP
    """

    def __init__(self, credentials_config: Mapping[str, Any] | None = None) -> None:
        """Initialize CredentialResolver.

        Args:
            credentials_config: Credentials section from config.
        """
        self._config = credentials_config or {}
        self._cache: dict[str, CredentialRecord] = {}

    def resolve(self, credential_name: str) -> CredentialRecord:
        """Resolve a credential by name.

        Args:
            credential_name: Name of the credential in config.

        Returns:
            CredentialRecord with resolved value(s).

        Raises:
            CredentialError: If credential cannot be resolved.
        """
        log.debug("Resolving credential: %s", credential_name)

        if credential_name in self._cache:
            log.debug("Credential '%s' found in cache", credential_name)
            return self._cache[credential_name]

        if credential_name not in self._config:
            raise CredentialError(credential_name, "Not found in credentials config")

        cred_config = self._config[credential_name]
        cred_type = cred_config.get("type", "env")

        log.debug("Credential '%s' type: %s", credential_name, cred_type)

        if cred_type == "env":
            record = self._resolve_env(credential_name, cred_config)
        elif cred_type == "file":
            record = self._resolve_file(credential_name, cred_config)
        elif cred_type == "sops":
            record = self._resolve_sops(credential_name, cred_config)
        elif cred_type == "provider":
            record = self._resolve_provider(credential_name, cred_config)
        else:
            raise CredentialError(credential_name, f"Unknown credential type: {cred_type}")

        self._cache[credential_name] = record
        log.debug("Credential '%s' resolved from %s", credential_name, record.source)
        return record

    def _resolve_env(
        self,
        credential_name: str,
        cred_config: Mapping[str, Any],
    ) -> CredentialRecord:
        """Resolve credential from environment variable.

        Config format (new - generic fields mapping):
            type: env
            fields:
              key: "API_KEY"        # Required, maps to value
              secret: "API_SECRET"  # Optional, maps to secret
              passphrase: "API_PASS"  # Optional, maps to extras

        Config format (legacy - still supported):
            type: env
            var: "GITHUB_TOKEN"
            # Or for key+secret pair:
            var_key: "API_KEY"
            var_secret: "API_SECRET"
        """
        # New format: fields mapping
        fields = cred_config.get("fields")
        if fields:
            return self._resolve_env_fields(credential_name, fields)

        # Legacy format: var or var_key/var_secret
        var_name = cred_config.get("var")
        var_key = cred_config.get("var_key")
        var_secret = cred_config.get("var_secret")

        if var_name:
            value = os.environ.get(var_name)
            if not value:
                raise CredentialError(
                    credential_name,
                    f"Environment variable '{var_name}' not set",
                )
            _validate_field_value(value, "var", credential_name)
            return CredentialRecord(value=value, source="env")

        if var_key:
            key_value = os.environ.get(var_key)
            if not key_value:
                raise CredentialError(
                    credential_name,
                    f"Environment variable '{var_key}' not set",
                )
            _validate_field_value(key_value, "var_key", credential_name)
            secret_value = None
            if var_secret:
                secret_value = os.environ.get(var_secret)
                if not secret_value:
                    raise CredentialError(
                        credential_name,
                        f"Environment variable '{var_secret}' not set",
                    )
                _validate_field_value(secret_value, "var_secret", credential_name)
            return CredentialRecord(value=key_value, secret=secret_value, source="env")

        raise CredentialError(credential_name, "Missing 'var', 'var_key', or 'fields' in env config")

    def _resolve_env_fields(
        self,
        credential_name: str,
        fields: Mapping[str, str],
    ) -> CredentialRecord:
        """Resolve credentials from environment using fields mapping.

        Args:
            credential_name: Credential name for error messages.
            fields: Mapping of logical names to env var names.
                    key -> value, secret -> secret, others -> extras

        Returns:
            CredentialRecord with resolved values.
        """
        _validate_fields_mapping(fields, credential_name)

        # Resolve key (required)
        key_env_var = fields["key"]
        key_value = os.environ.get(key_env_var)
        if not key_value:
            raise CredentialError(
                credential_name,
                f"Environment variable '{key_env_var}' not set (fields.key)",
            )
        _validate_field_value(key_value, "key", credential_name)

        # Resolve secret (optional)
        secret_value: str | None = None
        if "secret" in fields:
            secret_env_var = fields["secret"]
            secret_value = os.environ.get(secret_env_var)
            if not secret_value:
                raise CredentialError(
                    credential_name,
                    f"Environment variable '{secret_env_var}' not set (fields.secret)",
                )
            _validate_field_value(secret_value, "secret", credential_name)

        # Resolve extras (all other fields)
        extras: dict[str, str] = {}
        for field_name, env_var in fields.items():
            if field_name in ("key", "secret"):
                continue
            env_value = os.environ.get(env_var)
            if not env_value:
                raise CredentialError(
                    credential_name,
                    f"Environment variable '{env_var}' not set (fields.{field_name})",
                )
            _validate_field_value(env_value, field_name, credential_name)
            extras[field_name] = env_value

        return CredentialRecord(
            value=key_value,
            secret=secret_value,
            source="env",
            extras=extras,
        )

    def _load_file_data(self, credential_name: str, file_path: str) -> Any:
        """Load and parse JSON/YAML file data."""
        path = Path(file_path).expanduser()
        if not path.exists():
            raise CredentialError(credential_name, f"File not found: {path}")

        try:
            content = path.read_text(encoding="utf-8")
            if path.suffix in (".yaml", ".yml"):
                import yaml

                return yaml.safe_load(content)
            return json.loads(content)
        except Exception as e:
            raise CredentialError(credential_name, f"Failed to read file: {e}") from e

    def _extract_key_secret(
        self,
        credential_name: str,
        data: Any,
        key_field: str,
        secret_field: str | None,
    ) -> CredentialRecord:
        """Extract key and optional secret from data."""
        key_value = self.extract_value(data, f".{key_field}")
        if key_value is None:
            raise CredentialError(credential_name, f"Field '{key_field}' not found in file")

        secret_value = None
        if secret_field:
            secret_value = self.extract_value(data, f".{secret_field}")
            if secret_value is None:
                raise CredentialError(credential_name, f"Field '{secret_field}' not found in file")
            secret_value = str(secret_value)

        return CredentialRecord(value=str(key_value), secret=secret_value, source="file")

    def _extract_expires_at(
        self,
        data: Any,
        cred_config: Mapping[str, Any],
    ) -> float | None:
        """Extract expires_at timestamp from data if configured.

        Args:
            data: Parsed file data.
            cred_config: Credential configuration.

        Returns:
            Timestamp as float, or None if not configured/found.
        """
        expires_at_path = cred_config.get("expires_at_path")
        if not expires_at_path:
            return None

        expires_at = self.extract_value(data, expires_at_path)
        if expires_at is None:
            return None

        return self._parse_expires_at(expires_at)

    @staticmethod
    def _parse_expires_at(expires_at: Any) -> float | None:
        """Parse expires_at value to timestamp.

        Args:
            expires_at: Raw expires_at value (int, float, or ISO string).

        Returns:
            Timestamp as float, or None if unparseable.
        """
        if isinstance(expires_at, int | float):
            return float(expires_at)

        if isinstance(expires_at, str):
            # Try ISO format first
            try:
                from datetime import datetime

                dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                return dt.timestamp()
            except ValueError:
                # Try as numeric string
                try:
                    return float(expires_at)
                except ValueError:
                    pass
        return None

    def _resolve_fields_from_data(
        self,
        credential_name: str,
        data: Any,
        fields: Mapping[str, str],
        source: str,
        expires_at: float | None = None,
    ) -> CredentialRecord:
        """Resolve credentials from data using fields mapping.

        Args:
            credential_name: Credential name for error messages.
            data: Parsed data (dict from file/SOPS).
            fields: Mapping of logical names to field names in data.
            source: Source identifier (file, sops).
            expires_at: Optional expiration timestamp.

        Returns:
            CredentialRecord with resolved values.
        """
        _validate_fields_mapping(fields, credential_name)

        # Resolve key (required)
        key_field = fields["key"]
        key_value = self.extract_value(data, f".{key_field}")
        if key_value is None:
            raise CredentialError(
                credential_name,
                f"Field '{key_field}' not found in {source} (fields.key)",
            )
        key_str = str(key_value)
        _validate_field_value(key_str, "key", credential_name)

        # Resolve secret (optional)
        secret_value: str | None = None
        if "secret" in fields:
            secret_field = fields["secret"]
            secret_raw = self.extract_value(data, f".{secret_field}")
            if secret_raw is None:
                raise CredentialError(
                    credential_name,
                    f"Field '{secret_field}' not found in {source} (fields.secret)",
                )
            secret_value = str(secret_raw)
            _validate_field_value(secret_value, "secret", credential_name)

        # Resolve extras (all other fields)
        extras: dict[str, str] = {}
        for field_name, data_field in fields.items():
            if field_name in ("key", "secret"):
                continue
            field_value = self.extract_value(data, f".{data_field}")
            if field_value is None:
                raise CredentialError(
                    credential_name,
                    f"Field '{data_field}' not found in {source} (fields.{field_name})",
                )
            extra_str = str(field_value)
            _validate_field_value(extra_str, field_name, credential_name)
            extras[field_name] = extra_str

        return CredentialRecord(
            value=key_str,
            secret=secret_value,
            source=source,
            expires_at=expires_at,
            extras=extras,
        )

    def _resolve_file(
        self,
        credential_name: str,
        cred_config: Mapping[str, Any],
    ) -> CredentialRecord:
        """Resolve credential from JSON/YAML file with jq-like extraction.

        Config format (new - generic fields mapping):
            type: file
            path: "~/.config/credentials.json"
            fields:
              key: "api_key"        # Required, maps to value
              secret: "api_secret"  # Optional, maps to secret
              passphrase: "pass"    # Optional, maps to extras

        Config format (legacy - still supported):
            type: file
            path: "~/.config/credentials.json"
            token_path: ".access_token"  # jq-like path
            expires_at_path: ".expires_at"  # Optional, for OAuth2 tokens
            # Or for key+secret:
            key_field: "api_key"
            secret_field: "api_secret"
        """
        file_path = cred_config.get("path")
        if not file_path:
            raise CredentialError(credential_name, "Missing 'path' in file config")

        data = self._load_file_data(credential_name, file_path)

        # Extract expiration if configured
        expires_at = self._extract_expires_at(data, cred_config)

        # New format: fields mapping
        fields = cred_config.get("fields")
        if fields:
            return self._resolve_fields_from_data(credential_name, data, fields, "file", expires_at)

        # Legacy format: token_path or key_field
        token_path = cred_config.get("token_path")
        if token_path:
            value = self.extract_value(data, token_path)
            if value is None:
                raise CredentialError(credential_name, f"Path '{token_path}' not found in file")
            value_str = str(value)
            _validate_field_value(value_str, "token", credential_name)
            return CredentialRecord(value=value_str, source="file", expires_at=expires_at)

        key_field = cred_config.get("key_field")
        if key_field:
            record = self._extract_key_secret(
                credential_name,
                data,
                key_field,
                cred_config.get("secret_field"),
            )
            # Add expires_at if available
            if expires_at:
                return CredentialRecord(
                    value=record.value,
                    secret=record.secret,
                    source=record.source,
                    expires_at=expires_at,
                )
            return record

        raise CredentialError(
            credential_name,
            "Missing 'token_path', 'key_field', or 'fields' in file config",
        )

    def _resolve_sops(
        self,
        credential_name: str,
        cred_config: Mapping[str, Any],
    ) -> CredentialRecord:
        """Resolve credential from SOPS-encrypted file.

        Config format (new - generic fields mapping):
            type: sops
            path: "secrets/api.sops.json"
            fields:
              key: "api_key"        # Required, maps to value
              secret: "api_secret"  # Optional, maps to secret
              passphrase: "pass"    # Optional, maps to extras

        Config format (legacy - still supported):
            type: sops
            path: "secrets/api.sops.json"
            key_field: "api_key"
            secret_field: "api_secret"
        """
        file_path = cred_config.get("path")
        if not file_path:
            raise CredentialError(credential_name, "Missing 'path' in sops config")

        # Build a secrets config with SOPS provider for the specific file
        sops_config: dict[str, Any] = {
            "providers": [{"name": "sops", "settings": {"path": file_path}}],
        }

        # New format: fields mapping
        fields = cred_config.get("fields")
        if fields:
            return self._resolve_sops_fields(credential_name, fields, sops_config)

        # Legacy format: token_path or key_field
        return self._resolve_sops_legacy(credential_name, cred_config, sops_config)

    def _resolve_sops_legacy(
        self,
        credential_name: str,
        cred_config: Mapping[str, Any],
        sops_config: dict[str, Any],
    ) -> CredentialRecord:
        """Resolve SOPS credentials using legacy format (key_field/secret_field)."""
        key_field = cred_config.get("key_field")
        secret_field = cred_config.get("secret_field")
        token_path = cred_config.get("token_path")

        if token_path:
            return self._resolve_sops_token_path(credential_name, token_path, sops_config)

        if key_field:
            return self._resolve_sops_key_secret(credential_name, key_field, secret_field, sops_config)

        raise CredentialError(
            credential_name,
            "Missing 'token_path', 'key_field', or 'fields' in sops config",
        )

    def _resolve_sops_token_path(
        self,
        credential_name: str,
        token_path: str,
        sops_config: dict[str, Any],
    ) -> CredentialRecord:
        """Resolve single SOPS token using token_path."""
        from kstlib.secrets import resolve_secret

        key_path = token_path.lstrip(".")
        try:
            record = resolve_secret(key_path, config=sops_config)
            _validate_field_value(record.value, "token", credential_name)
            return CredentialRecord(value=record.value, source="sops")
        except CredentialError:
            raise
        except Exception as e:
            raise CredentialError(
                credential_name,
                f"Failed to resolve SOPS secret: {e}",
            ) from e

    def _resolve_sops_key_secret(
        self,
        credential_name: str,
        key_field: str,
        secret_field: str | None,
        sops_config: dict[str, Any],
    ) -> CredentialRecord:
        """Resolve SOPS key and optional secret using legacy format."""
        from kstlib.secrets import resolve_secret

        try:
            record_key = resolve_secret(key_field, config=sops_config)
            key_value = record_key.value
            _validate_field_value(key_value, "key", credential_name)
        except CredentialError:
            raise
        except Exception as e:
            raise CredentialError(
                credential_name,
                f"Failed to resolve SOPS key field: {e}",
            ) from e

        secret_value = None
        if secret_field:
            try:
                record_secret = resolve_secret(secret_field, config=sops_config)
                secret_value = record_secret.value
                _validate_field_value(secret_value, "secret", credential_name)
            except CredentialError:
                raise
            except Exception as e:
                raise CredentialError(
                    credential_name,
                    f"Failed to resolve SOPS secret field: {e}",
                ) from e

        return CredentialRecord(value=key_value, secret=secret_value, source="sops")

    def _resolve_sops_fields(
        self,
        credential_name: str,
        fields: Mapping[str, str],
        sops_config: dict[str, Any],
    ) -> CredentialRecord:
        """Resolve credentials from SOPS using fields mapping.

        Args:
            credential_name: Credential name for error messages.
            fields: Mapping of logical names to field names in SOPS file.
            sops_config: SOPS provider configuration.

        Returns:
            CredentialRecord with resolved values.
        """
        from kstlib.secrets import resolve_secret

        _validate_fields_mapping(fields, credential_name)

        # Resolve key (required)
        key_field = fields["key"]
        try:
            record_key = resolve_secret(key_field, config=sops_config)
            key_value = record_key.value
            _validate_field_value(key_value, "key", credential_name)
        except CredentialError:
            raise
        except Exception as e:
            raise CredentialError(
                credential_name,
                f"Failed to resolve SOPS field '{key_field}' (fields.key): {e}",
            ) from e

        # Resolve secret (optional)
        secret_value: str | None = None
        if "secret" in fields:
            secret_field = fields["secret"]
            try:
                record_secret = resolve_secret(secret_field, config=sops_config)
                secret_value = record_secret.value
                _validate_field_value(secret_value, "secret", credential_name)
            except CredentialError:
                raise
            except Exception as e:
                raise CredentialError(
                    credential_name,
                    f"Failed to resolve SOPS field '{secret_field}' (fields.secret): {e}",
                ) from e

        # Resolve extras (all other fields)
        extras: dict[str, str] = {}
        for field_name, sops_field in fields.items():
            if field_name in ("key", "secret"):
                continue
            try:
                record_extra = resolve_secret(sops_field, config=sops_config)
                extra_value = record_extra.value
                _validate_field_value(extra_value, field_name, credential_name)
                extras[field_name] = extra_value
            except CredentialError:
                raise
            except Exception as e:
                raise CredentialError(
                    credential_name,
                    f"Failed to resolve SOPS field '{sops_field}' (fields.{field_name}): {e}",
                ) from e

        return CredentialRecord(
            value=key_value,
            secret=secret_value,
            source="sops",
            extras=extras,
        )

    def _resolve_provider(
        self,
        credential_name: str,
        cred_config: Mapping[str, Any],
    ) -> CredentialRecord:
        """Resolve credential from kstlib.auth provider.

        Config format:
            type: provider
            provider: "corporate"  # kstlib.auth provider name
        """
        provider_name = cred_config.get("provider")
        if not provider_name:
            raise CredentialError(credential_name, "Missing 'provider' in provider config")

        try:
            from kstlib.auth import OIDCProvider, get_token_storage_from_config

            storage = get_token_storage_from_config(provider_name=provider_name)
            token = storage.load(provider_name)

            if not token or not token.access_token:
                raise CredentialError(
                    credential_name,
                    f"No valid token found for provider '{provider_name}'. Run 'kstlib auth login' first.",
                )

            # Check if token is expired
            if token.is_expired:
                # Try to refresh using the provider
                if token.is_refreshable:
                    log.debug("Access token expired, attempting refresh")
                    provider = OIDCProvider.from_config(provider_name)
                    token = provider.refresh(token)
                    storage.save(provider_name, token)
                else:
                    raise CredentialError(
                        credential_name,
                        f"Token for provider '{provider_name}' is expired. Run 'kstlib auth login' to refresh.",
                    )

            # Convert datetime to float timestamp for CredentialRecord
            expires_at_ts: float | None = None
            if token.expires_at is not None:
                expires_at_ts = token.expires_at.timestamp()

            return CredentialRecord(
                value=token.access_token,
                source="provider",
                expires_at=expires_at_ts,
            )
        except ImportError as e:
            raise CredentialError(
                credential_name,
                f"kstlib.auth module not available: {e}",
            ) from e
        except Exception as e:
            if isinstance(e, CredentialError):
                raise
            raise CredentialError(
                credential_name,
                f"Failed to get token from provider: {e}",
            ) from e

    @staticmethod
    def extract_value(data: Any, path: str) -> Any:
        """Extract value using jq-like path syntax.

        Supports:
        - .foo.bar - nested object access
        - .foo[0] - array index access
        - .foo["key-with-dash"] - bracket notation for special keys
        - .foo['key-with-dash'] - single quotes also supported
        - .foo.bar[0].baz - combined access

        Args:
            data: Data structure to extract from.
            path: jq-like path (e.g., ".foo.bar[0]" or '.foo["access-token"]').

        Returns:
            Extracted value or None if not found.

        Examples:
            >>> CredentialResolver.extract_value({"foo": {"bar": [1, 2, 3]}}, ".foo.bar[1]")
            2
            >>> CredentialResolver.extract_value({"a": "b"}, ".missing")
            >>> CredentialResolver.extract_value([1, 2, 3], ".[0]")
            1
            >>> CredentialResolver.extract_value({"a-b": "value"}, '.["a-b"]')
            'value'
        """
        if not path or path == ".":
            return data

        current = data
        matches = _JQ_PATH_PATTERN.findall(path)

        for part in matches:
            if current is None:
                return None

            if part.startswith("[") and part.endswith("]"):
                inner = part[1:-1]
                # Check for quoted string key: ["key"] or ['key']
                if (inner.startswith('"') and inner.endswith('"')) or (inner.startswith("'") and inner.endswith("'")):
                    # Extract key from quotes
                    key = inner[1:-1]
                    if isinstance(current, dict):
                        current = current.get(key)
                    else:
                        return None
                else:
                    # Array index
                    try:
                        index = int(inner)
                        if isinstance(current, list | tuple) and 0 <= index < len(current):
                            current = current[index]
                        else:
                            return None
                    except (ValueError, IndexError):
                        return None
            elif isinstance(current, dict):
                current = current.get(part)
            else:
                return None

        return current

    def clear_cache(self) -> None:
        """Clear the credential cache."""
        self._cache.clear()
        log.debug("Credential cache cleared")


__all__ = ["CredentialRecord", "CredentialResolver"]
