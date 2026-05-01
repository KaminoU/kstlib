"""Private helpers shared between subprocess-based step executors.

Currently exposes :func:`_sanitize_command`, a best-effort regex-based
redaction for command lines logged by ShellStep and PythonStep. The
function is intentionally private to the ``kstlib.pipeline.steps``
sub-package because it does not aim to cover every possible secret
pattern: users running pipelines with shell commands are responsible
for not embedding credentials directly in command-line arguments
(prefer ``env:`` mappings, see Sphinx user-responsibility guide).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

# Patterns covering common credential exposure shapes in shell / argv lines.
# Compiled once at module load so the redaction stays cheap on the hot path.
_SENSITIVE_CMD_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # -H "Authorization: <scheme> <token>" or -H 'Authorization: ...'
    (
        re.compile(r"(-H\s+['\"]?Authorization:\s*\S+\s+)\S+['\"]?", re.IGNORECASE),
        r"\1[REDACTED]",
    ),
    # --password, --pwd, --api-key, --api_key, --apikey, --token, --secret
    # Either with `=value` or `space value` form.
    (
        re.compile(
            r"(--(?:password|pwd|api[-_]?key|apikey|token|secret)[=\s]+)\S+",
            re.IGNORECASE,
        ),
        r"\1[REDACTED]",
    ),
    # sshpass -p <password>
    (
        re.compile(r"(sshpass\s+-p\s+)['\"]?\S+?['\"]?(\s|$)"),
        r"\1[REDACTED]\2",
    ),
    # URL with userinfo : scheme://user:pass@host
    (
        re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://)[^@\s/]+:[^@\s/]+@"),
        r"\1[REDACTED]@",
    ),
    # PGPASSWORD=value, MYSQL_PWD=value, and similar inline env-var prefixes.
    # Matches uppercase letters, digits, underscores ending in PASSWORD/PWD/SECRET/TOKEN.
    (
        re.compile(
            r"(\b[A-Z][A-Z0-9_]*?(?:PASSWORD|PWD|SECRET|TOKEN|API_KEY)=)\S+",
        ),
        r"\1[REDACTED]",
    ),
)


def _sanitize_command(cmd: str | Sequence[str]) -> str:
    """Return a best-effort sanitized representation of a command line.

    Apply known regex patterns to mask credentials embedded in
    ``Authorization`` headers, ``--password`` / ``--api-key`` flags,
    ``sshpass -p`` invocations, URL userinfo, and inline environment
    variable prefixes (``PGPASSWORD=...``).

    Args:
        cmd: Either a shell command string (``shell=True`` execution)
            or an argv sequence (``shell=False`` execution).

    Returns:
        A single string suitable for log output. The original ``cmd`` is
        not modified.

    Note:
        Regex-based redaction is best-effort only. Users embedding
        secrets in arbitrary CLI shapes are responsible for not relying
        on this redaction. The Sphinx user-responsibility guide
        documents safer alternatives (``env:`` mappings).

    """
    cmd_str = cmd if isinstance(cmd, str) else " ".join(str(part) for part in cmd)
    for pattern, replacement in _SENSITIVE_CMD_PATTERNS:
        cmd_str = pattern.sub(replacement, cmd_str)
    return cmd_str
