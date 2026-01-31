"""Secrets subsystem public exports.

The secrets package exposes factories and models that orchestrate credential
resolution across multiple providers such as kwargs, configuration files,
keyring backends, and SOPS encrypted payloads.
"""

from kstlib.secrets.exceptions import (
    SecretDecryptionError,
    SecretError,
    SecretNotFoundError,
)
from kstlib.secrets.models import SecretRecord, SecretRequest, SecretSource
from kstlib.secrets.resolver import SecretResolver, get_secret_resolver, resolve_secret
from kstlib.secrets.sensitive import CachePurgeProtocol, sensitive

__all__ = [
    "CachePurgeProtocol",
    "SecretDecryptionError",
    "SecretError",
    "SecretNotFoundError",
    "SecretRecord",
    "SecretRequest",
    "SecretResolver",
    "SecretSource",
    "get_secret_resolver",
    "resolve_secret",
    "sensitive",
]
