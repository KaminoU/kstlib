"""Shared redaction helpers for safe logging.

This module consolidates redaction primitives used across kstlib for
sanitizing diagnostic output before logging. It exposes three helpers:

- ``redact_sensitive`` : best-effort regex redaction for stderr/output
  containing secrets (AWS ARN, AKIA keys, paths, Authorization headers,
  command-line credentials, URL userinfo).
- ``mask_webhook_url`` : mask Slack/Discord/Teams webhook URLs while
  preserving structure (host + first letter of each token).
- ``mask_url`` : mask URL credentials inline (``user:pass@host``) and
  sensitive query parameters (``?token=xxx&api_key=yyy``).

The helpers are pure (no I/O, no side effects) and safe to call from any
log path without recursion risk.

For HTTP body/header redaction at httpx level, see
:class:`kstlib.utils.http_trace.HTTPTraceLogger`.

Examples:
    >>> from kstlib._shared.redaction import redact_sensitive, mask_url
    >>> redact_sensitive("Authorization: Bearer abc123")
    'Authorization: Bearer [REDACTED]'
    >>> mask_url("https://user:secret@host.com/path")
    'https://[REDACTED]@host.com/path'

"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "DEFAULT_URL_SENSITIVE_QUERY_KEYS",
    "mask_url",
    "mask_webhook_url",
    "redact_sensitive",
]


# === Pilier 2 : redact_sensitive (regex stderr/output) ===
# Patterns extracted from secrets/providers/sops.py + extended for cross-module use.

_DEFAULT_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # AWS ARN
    (re.compile(r"arn:aws:[^\s]+", re.IGNORECASE), "[REDACTED_ARN]"),
    # AWS access key id
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED_AWS_KEY]"),
    # Home directories (leak username)
    (re.compile(r"(?:/home/|/Users/)[^\s]+"), "[REDACTED_PATH]"),
    # Authorization header values (Bearer / Basic / etc.)
    (re.compile(r"(Authorization:\s*\S+\s+)\S+", re.IGNORECASE), r"\1[REDACTED]"),
    # CLI flags : --password, --pwd, --api-key, --api_key, --token, --secret
    (
        re.compile(r"(--(?:password|pwd|api[-_]?key|token|secret)[=\s]+)\S+", re.IGNORECASE),
        r"\1[REDACTED]",
    ),
    # URL with userinfo : https://user:pass@host -> https://[REDACTED]@host
    (re.compile(r"(https?://)[^@\s]+:[^@\s]+@"), r"\1[REDACTED]@"),
)


def redact_sensitive(
    message: str,
    *,
    additional_patterns: Iterable[tuple[re.Pattern[str], str]] = (),
) -> str:
    """Best-effort secret redaction for diagnostic output.

    Use on stderr from external tools (SOPS, sas-admin, subprocess) or on
    exception messages from third-party libraries before logging. The
    redaction is regex-based and intentionally conservative: it covers
    common patterns but cannot catch every possible secret format.

    Args:
        message: The diagnostic message to redact.
        additional_patterns: Extra ``(pattern, replacement)`` pairs to
            apply after the defaults. Useful for module-specific tokens.

    Returns:
        The redacted message. Identical to ``message`` if no pattern
        matches.

    Examples:
        >>> redact_sensitive("aws arn:aws:iam::123456789012:user/admin failed")
        'aws [REDACTED_ARN] failed'
        >>> redact_sensitive("--password secret123 was provided")
        '--password [REDACTED] was provided'
        >>> redact_sensitive("https://user:pwd@host/api")
        'https://[REDACTED]@host/api'

    """
    redacted = message
    for pattern, replacement in (*_DEFAULT_SECRET_PATTERNS, *additional_patterns):
        redacted = pattern.sub(replacement, redacted)
    return redacted


# === Pilier 3 : mask_webhook_url (Slack/Discord/Teams tokens) ===
# Extracted from alerts/channels/slack.py + generalized for other webhook providers.

_SLACK_WEBHOOK_HOST = "hooks.slack.com"
_DISCORD_WEBHOOK_HOST = "discord.com"
_TEAMS_WEBHOOK_HOST = "webhook.office.com"


def _mask_slack_webhook(url: str) -> str:
    """Mask a Slack webhook URL preserving host and first letter of each token."""
    parts = url.split("/services/")
    if len(parts) == 2:
        tokens = parts[1].split("/")
        if len(tokens) >= 3:
            return f"https://{_SLACK_WEBHOOK_HOST}/services/{tokens[0][:1]}***/{tokens[1][:1]}***/***"
    return f"https://{_SLACK_WEBHOOK_HOST}/services/***"


def _mask_discord_webhook(url: str) -> str:
    """Mask a Discord webhook URL preserving host."""
    parts = url.split("/api/webhooks/")
    if len(parts) == 2:
        return f"https://{_DISCORD_WEBHOOK_HOST}/api/webhooks/***/***"
    return f"https://{_DISCORD_WEBHOOK_HOST}/api/webhooks/***"


def mask_webhook_url(url: str) -> str:
    """Mask a webhook URL for safe logging.

    Preserves the host and first letter of each token segment so the
    URL remains diagnosable (which webhook, which workspace) without
    leaking the secret. Supports Slack, Discord, and Teams webhook
    formats; falls back to a generic mask for other hosts.

    Args:
        url: The full webhook URL.

    Returns:
        Masked URL safe to log. Empty input returns ``"***"``.

    Examples:
        >>> mask_webhook_url("https://hooks.slack.com/services/T123/B456/xyz")
        'https://hooks.slack.com/services/T***/B***/***'
        >>> mask_webhook_url("https://discord.com/api/webhooks/123/abc")
        'https://discord.com/api/webhooks/***/***'
        >>> mask_webhook_url("")
        '***'

    """
    if not url:
        return "***"
    if _SLACK_WEBHOOK_HOST in url:
        return _mask_slack_webhook(url)
    if _DISCORD_WEBHOOK_HOST in url:
        return _mask_discord_webhook(url)
    if _TEAMS_WEBHOOK_HOST in url:
        return f"https://{_TEAMS_WEBHOOK_HOST}/***"
    return "***"


# === Nouveau v2.5.0 : mask_url (URL with credentials inline / sensitive query) ===

# Sensitive query parameter keys (case-insensitive). Aligned with
# kstlib.utils.http_trace.DEFAULT_SENSITIVE_KEYS where applicable.
DEFAULT_URL_SENSITIVE_QUERY_KEYS: frozenset[str] = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "auth",
        "client_secret",
        "code",
        "code_verifier",
        "key",
        "password",
        "pwd",
        "refresh_token",
        "secret",
        "session",
        "sessionid",
        "sig",
        "signature",
        "token",
    }
)


def mask_url(
    url: str,
    *,
    sensitive_query_keys: frozenset[str] | None = None,
) -> str:
    """Mask URL credentials and sensitive query parameters for safe logging.

    Two transformations are applied:

    1. Userinfo in the netloc is replaced : ``user:pass@host`` becomes
       ``[REDACTED]@host`` so basic auth credentials never appear in logs.
    2. Sensitive query parameters (matched case-insensitively against
       ``sensitive_query_keys``) have their values replaced with
       ``[REDACTED]`` while preserving the key name (useful for tracing
       which params were present).

    Args:
        url: The URL to mask.
        sensitive_query_keys: Frozenset of query keys to redact. Defaults
            to ``DEFAULT_URL_SENSITIVE_QUERY_KEYS``.

    Returns:
        The masked URL. If parsing fails or the URL has no scheme, the
        original input is returned unchanged (best-effort approach).

    Examples:
        >>> mask_url("https://user:pass@host.com/path")
        'https://[REDACTED]@host.com/path'
        >>> mask_url("wss://host?token=secret&plain=ok")
        'wss://host?token=[REDACTED]&plain=ok'
        >>> mask_url("https://host/")
        'https://host/'

    """
    if not url:
        return url

    keys = sensitive_query_keys if sensitive_query_keys is not None else DEFAULT_URL_SENSITIVE_QUERY_KEYS

    try:
        parts = urlsplit(url)
    except ValueError:
        return url

    if not parts.scheme:
        return url

    netloc = parts.netloc
    if "@" in netloc:
        host_port = netloc.rsplit("@", 1)[1]
        netloc = f"[REDACTED]@{host_port}"

    query = parts.query
    if query and "=" in query:
        new_pairs: list[str] = []
        for pair in query.split("&"):
            if "=" not in pair:
                new_pairs.append(pair)
                continue
            key, _, _ = pair.partition("=")
            if key.lower() in keys:
                new_pairs.append(f"{key}=[REDACTED]")
            else:
                new_pairs.append(pair)
        query = "&".join(new_pairs)

    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))
