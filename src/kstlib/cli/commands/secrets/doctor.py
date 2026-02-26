"""Doctor and init commands for secrets subsystem."""

from __future__ import annotations

import importlib
import os
import shutil
from pathlib import Path
from subprocess import run
from typing import TYPE_CHECKING, Any

import typer

from kstlib.cli.common import (
    CommandResult,
    CommandStatus,
    console,
    exit_error,
    render_result,
)
from kstlib.config.exceptions import ConfigNotLoadedError
from kstlib.config.loader import get_config

from .common import INIT_BACKEND_OPTION, INIT_FORCE_OPTION, INIT_LOCAL_OPTION, CheckEntry, resolve_sops_binary

if TYPE_CHECKING:
    from collections.abc import Sequence


# =============================================================================
# Doctor Checks
# =============================================================================


def _check_sops_binary() -> CheckEntry:
    """Return the SOPS binary availability check result."""
    binary = resolve_sops_binary()
    binary_path = shutil.which(binary)
    if binary_path:
        return {"component": "sops", "status": "available", "details": binary_path}
    return {"component": "sops", "status": "missing", "details": f"Executable '{binary}' not found."}


def _find_effective_sops_config() -> tuple[Path | None, str]:
    """Find the SOPS config file exactly as SOPS does.

    Returns:
        Tuple of (config_path, source) where source is one of:
        - "env" if from SOPS_CONFIG environment variable
        - "local" if found by walking up from cwd (but not in HOME)
        - "home" if from ~/.sops.yaml (whether found by walking or fallback)
        - "none" if not found
    """
    home_dir = Path.home()
    home_config = home_dir / ".sops.yaml"

    # 1. Check SOPS_CONFIG environment variable (highest priority)
    sops_config_env = os.getenv("SOPS_CONFIG")
    if sops_config_env:
        config_path = Path(sops_config_env)
        if config_path.exists():
            return config_path, "env"
        return None, "none"

    # 2. Walk up from cwd to find .sops.yaml (like SOPS does)
    current = Path.cwd()
    while current != current.parent:
        candidate = current / ".sops.yaml"
        if candidate.exists():
            # Distinguish: if found in HOME, label as "home" not "local"
            if candidate.resolve() == home_config.resolve():
                return candidate, "home"
            return candidate, "local"
        current = current.parent

    # 3. Fallback: check ~/.sops.yaml directly
    if home_config.exists():
        return home_config, "home"

    return None, "none"


def _find_sops_config_path() -> Path | None:
    """Find the SOPS config file path (returns None if not found)."""
    config_path, _ = _find_effective_sops_config()
    return config_path


def _extract_age_recipients_from_config(config_path: Path) -> list[str]:
    """Extract age recipients from a .sops.yaml config file."""
    import re

    try:
        content = config_path.read_text(encoding="utf-8")
    except OSError:
        return []

    # Simple regex to find age: keys (handles multi-line with >-)
    recipients: list[str] = []
    # Match "age: age1..." or "age: >-\n  age1...,\n  age1..."
    age_pattern = re.compile(r"\bage:\s*([^\n]+(?:\n\s+[^\n]+)*)", re.MULTILINE)
    for match in age_pattern.finditer(content):
        value = match.group(1).strip()
        # Handle >- multi-line format
        if value.startswith(">"):
            value = value[1:].strip("-").strip()
        # Extract individual age keys
        for key in re.findall(r"(age1[a-z0-9]+)", value):
            if key not in recipients:
                recipients.append(key)
    return recipients


def _detect_sops_backends(config_path: Path) -> list[str]:
    """Detect which encryption backends are configured in .sops.yaml.

    Returns:
        List of backend names: "age", "gpg", "kms", "gcp_kms", "azure_kv"
    """
    import re

    try:
        content = config_path.read_text(encoding="utf-8")
    except OSError:
        return []

    backends: list[str] = []

    # Check for age (age: age1...)
    if re.search(r"\bage:\s*age1", content):
        backends.append("age")

    # Check for GPG/PGP (pgp: or gpg:)
    if re.search(r"\b(pgp|gpg):\s*\S", content):
        backends.append("gpg")

    # Check for AWS KMS (kms: arn:aws:kms:...)
    if re.search(r"\bkms:\s*arn:aws:kms:", content):
        backends.append("kms")

    # Check for GCP KMS (gcp_kms: projects/...)
    if re.search(r"\bgcp_kms:\s*projects/", content):
        backends.append("gcp_kms")

    # Check for Azure Key Vault (azure_keyvault: https://...)
    if re.search(r"\bazure_keyvault:\s*https://", content):
        backends.append("azure_kv")

    return backends


def _format_config_source(source: str) -> str:
    """Format the config source for display."""
    source_labels = {
        "env": "SOPS_CONFIG env var",
        "local": "local directory (walking up from cwd)",
        "home": "home directory (~/.sops.yaml)",
        "none": "not found",
    }
    return source_labels.get(source, source)


def _check_sops_config() -> CheckEntry:
    """Return the SOPS configuration availability check result.

    Shows exactly which config SOPS will use and where it comes from.
    """
    # Check if SOPS_CONFIG points to missing file
    sops_config_env = os.getenv("SOPS_CONFIG")
    if sops_config_env:
        env_config_path = Path(sops_config_env)
        if not env_config_path.exists():
            return {
                "component": "sops_config",
                "status": "warning",
                "details": f"SOPS_CONFIG points to missing file: {env_config_path}",
            }

    # Find the effective config (exactly as SOPS does)
    effective_config, source = _find_effective_sops_config()

    if effective_config is None:
        return {
            "component": "sops_config",
            "status": "missing",
            "details": (
                "No .sops.yaml found. Run 'kstlib secrets init' or create one manually. "
                "See: https://github.com/getsops/sops#usage"
            ),
        }

    # Extract age recipients to show which keys will be used
    recipients = _extract_age_recipients_from_config(effective_config)
    source_label = _format_config_source(source)

    if recipients:
        # Show full public key(s) - this is the key SOPS will use for encryption
        key_lines = "\n  ".join(recipients)
        extra = "" if len(recipients) <= 3 else f"\n  (+{len(recipients) - 3} more)"
        details = f"[{source_label}] {effective_config}\n  Public key(s) for encryption:\n  {key_lines}{extra}"
    else:
        details = f"[{source_label}] {effective_config} (no age recipients found)"

    return {"component": "sops_config", "status": "available", "details": details}


def _check_age_keygen() -> CheckEntry:
    """Return the age-keygen binary availability check result."""
    age_binary_path = shutil.which("age-keygen")
    if age_binary_path:
        return {"component": "age-keygen", "status": "available", "details": age_binary_path}
    return {
        "component": "age-keygen",
        "status": "warning",
        "details": "Executable 'age-keygen' not found; age recipients will be unavailable.",
    }


def _find_age_key_path() -> Path | None:
    """Find the age key file path (returns None if not found)."""
    age_key_env = os.getenv("SOPS_AGE_KEY_FILE")
    if age_key_env:
        age_key_path = Path(age_key_env)
        if age_key_path.exists():
            return age_key_path
        return None

    # Check platform-specific default locations
    default_paths = [Path.home() / ".config" / "sops" / "age" / "keys.txt"]
    if os.name == "nt":  # Windows
        appdata = os.getenv("APPDATA")
        if appdata:
            default_paths.insert(0, Path(appdata) / "sops" / "age" / "keys.txt")

    for key_path in default_paths:
        if key_path.exists():
            return key_path
    return None


def _read_age_public_key(key_path: Path) -> str | None:
    """Read the public key from an age key file."""
    try:
        content = key_path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in content.splitlines():
        if line.startswith("# public key:"):
            return line.split(":", 1)[1].strip()
    return None


def _check_age_key() -> CheckEntry:
    """Return the age key file availability check result."""
    age_key_env = os.getenv("SOPS_AGE_KEY_FILE")
    if age_key_env:
        age_key_path = Path(age_key_env)
        if not age_key_path.exists():
            return {
                "component": "age_key",
                "status": "warning",
                "details": f"SOPS_AGE_KEY_FILE points to missing file: {age_key_path}",
            }
        # Read and display public key
        public_key = _read_age_public_key(age_key_path)
        if public_key:
            return {
                "component": "age_key",
                "status": "available",
                "details": f"{age_key_path} (public: {public_key})",
            }
        return {"component": "age_key", "status": "available", "details": str(age_key_path)}

    # Check platform-specific default locations
    default_paths = [Path.home() / ".config" / "sops" / "age" / "keys.txt"]
    if os.name == "nt":  # Windows
        appdata = os.getenv("APPDATA")
        if appdata:
            default_paths.insert(0, Path(appdata) / "sops" / "age" / "keys.txt")

    for key_path in default_paths:
        if key_path.exists():
            # Read and display public key
            public_key = _read_age_public_key(key_path)
            if public_key:
                return {
                    "component": "age_key",
                    "status": "available",
                    "details": f"{key_path} (public: {public_key})",
                }
            return {"component": "age_key", "status": "available", "details": str(key_path)}

    hint = "%APPDATA%\\sops\\age\\keys.txt" if os.name == "nt" else "~/.config/sops/age/keys.txt"
    return {
        "component": "age_key",
        "status": "warning",
        "details": f"No age key detected (set SOPS_AGE_KEY_FILE or create {hint}).",
    }


def _check_age_key_consistency() -> CheckEntry | None:
    """Check if age key in keys.txt matches .sops.yaml recipients."""
    # Find age key file and extract public key
    key_path = _find_age_key_path()
    if not key_path:
        return None  # Will be reported by _check_age_key

    public_key = _read_age_public_key(key_path)
    config_path = _find_sops_config_path()
    if not public_key or not config_path:
        return None  # Missing components reported elsewhere

    recipients = _extract_age_recipients_from_config(config_path)
    if not recipients:
        return {
            "component": "age_consistency",
            "status": "warning",
            "details": f"No age recipients found in {config_path}",
        }

    # Check if current key is in recipients
    if public_key in recipients:
        detail = (
            "Key matches .sops.yaml recipient"
            if len(recipients) == 1
            else f"Key matches .sops.yaml (1 of {len(recipients)} recipients)"
        )
        return {"component": "age_consistency", "status": "available", "details": detail}

    # Key mismatch!
    short_current = f"{public_key[:12]}...{public_key[-6:]}"
    short_configured = ", ".join(f"{r[:12]}...{r[-6:]}" for r in recipients[:2])
    if len(recipients) > 2:
        short_configured += f" (+{len(recipients) - 2} more)"
    return {
        "component": "age_consistency",
        "status": "warning",
        "details": f"KEY MISMATCH! Your key ({short_current}) not in .sops.yaml ({short_configured})",
    }


def _check_keyring() -> CheckEntry:
    """Return the keyring backend availability check result."""
    try:
        keyring_module = importlib.import_module("keyring")
    except ImportError:
        return {
            "component": "keyring",
            "status": "warning",
            "details": "Python 'keyring' package not installed (optional, for credential caching).",
        }
    backend = keyring_module.get_keyring().__class__.__name__
    return {"component": "keyring", "status": "available", "details": backend}


def _check_gpg_binary() -> CheckEntry:
    """Return the GPG binary availability check result."""
    # Try common GPG binary names
    gpg_names = ["gpg", "gpg2"]
    for gpg_name in gpg_names:
        gpg_path = shutil.which(gpg_name)
        if gpg_path:
            # Try to get version
            try:
                result = run([gpg_path, "--version"], capture_output=True, text=True, check=False)
                if result.returncode == 0:
                    # Extract first line (e.g., "gpg (GnuPG) 2.4.0")
                    version_line = result.stdout.split("\n")[0] if result.stdout else gpg_name
                    return {"component": "gpg", "status": "available", "details": f"{gpg_path} ({version_line})"}
            except OSError:
                pass
            return {"component": "gpg", "status": "available", "details": gpg_path}
    return {
        "component": "gpg",
        "status": "warning",
        "details": "GPG not found; GPG-encrypted SOPS files will be unavailable.",
    }


def _check_gpg_keys() -> CheckEntry:
    """Return the GPG secret keys availability check result."""
    gpg_path = shutil.which("gpg") or shutil.which("gpg2")
    if not gpg_path:
        return {
            "component": "gpg_keys",
            "status": "warning",
            "details": "GPG not installed; cannot check for secret keys.",
        }

    try:
        result = run(
            [gpg_path, "--list-secret-keys", "--keyid-format=long"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return {
            "component": "gpg_keys",
            "status": "warning",
            "details": "Failed to execute GPG.",
        }

    if result.returncode != 0:
        return {
            "component": "gpg_keys",
            "status": "warning",
            "details": "Failed to list GPG secret keys.",
        }

    # Check if there are any secret keys
    output = result.stdout.strip()
    if not output or "sec" not in output:
        return {
            "component": "gpg_keys",
            "status": "warning",
            "details": "No GPG secret keys found; generate one with 'gpg --gen-key'.",
        }

    # Count keys (lines starting with "sec")
    key_count = sum(1 for line in output.split("\n") if line.strip().startswith("sec"))
    return {
        "component": "gpg_keys",
        "status": "available",
        "details": f"{key_count} secret key(s) available",
    }


def _check_boto3() -> CheckEntry:
    """Return the boto3 availability check result (for KMS)."""
    try:
        boto3_module = importlib.import_module("boto3")
    except ImportError:
        return {
            "component": "boto3",
            "status": "warning",
            "details": "boto3 not installed; KMS provider will be unavailable.",
        }
    version = getattr(boto3_module, "__version__", "unknown")
    return {"component": "boto3", "status": "available", "details": f"v{version}"}


def _check_aws_credentials() -> CheckEntry:
    """Return basic AWS credentials check result (for KMS)."""
    # Check for common credential sources
    cred_sources: list[str] = []

    if os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"):
        cred_sources.append("environment variables")

    if os.getenv("AWS_PROFILE"):
        cred_sources.append(f"profile '{os.getenv('AWS_PROFILE')}'")

    # Check for credentials file
    aws_creds_file = Path.home() / ".aws" / "credentials"
    if aws_creds_file.exists():
        cred_sources.append("~/.aws/credentials")

    # Check for config file
    aws_config_file = Path.home() / ".aws" / "config"
    if aws_config_file.exists():
        cred_sources.append("~/.aws/config")

    if cred_sources:
        return {
            "component": "aws_credentials",
            "status": "available",
            "details": ", ".join(cred_sources),
        }

    return {
        "component": "aws_credentials",
        "status": "warning",
        "details": "No AWS credentials detected; KMS will require explicit configuration.",
    }


def _scan_available_backends() -> list[str]:
    """Scan the system for available encryption backends (binary/package presence only).

    Returns:
        List of backend names detected on the system: "age", "gpg", "kms".
    """
    available: list[str] = []
    if shutil.which("age-keygen"):
        available.append("age")
    if shutil.which("gpg") or shutil.which("gpg2"):
        available.append("gpg")
    try:
        importlib.import_module("boto3")
        available.append("kms")
    except ImportError:
        pass
    return available


def _evaluate_config_state() -> tuple[list[CheckEntry], dict[str, Any] | None]:
    """Return configuration diagnostics entries and resolver snapshot."""
    try:
        config = get_config()
    except ConfigNotLoadedError:
        warning = {
            "component": "config",
            "status": "warning",
            "details": "Global configuration not loaded; resolver will use defaults.",
        }
        return ([warning], None)

    secrets_config = getattr(config, "secrets", None)
    resolver_config = secrets_config.to_dict() if secrets_config is not None else None
    return ([], resolver_config)


def _derive_doctor_status(checks: Sequence[CheckEntry]) -> CommandStatus:
    """Compute the overall doctor status from individual checks."""
    if any(entry.get("status") == "missing" for entry in checks):
        return CommandStatus.ERROR
    if any(entry.get("status") == "warning" for entry in checks):
        return CommandStatus.WARNING
    return CommandStatus.OK


def _build_backend_mismatch_hint(
    configured: list[str],
    available: list[str],
) -> str | None:
    """Build an actionable hint when configured backends are not available.

    Returns:
        A hint string if there is a mismatch, None otherwise.
    """
    unavailable_configured = [b for b in configured if b not in available]
    usable_alternatives = [b for b in available if b in ("age", "gpg")]

    if not unavailable_configured or not usable_alternatives:
        return None

    alt = usable_alternatives[0]
    configured_str = ", ".join(unavailable_configured)
    return (
        f"[yellow]Hint:[/yellow] Configured backend ({configured_str}) is not available, "
        f"but {alt} is. Run: [bold]kstlib secrets init --backend {alt}[/bold]"
    )


def _build_doctor_message(
    checks: Sequence[CheckEntry],
    status: CommandStatus,
    backends: list[str] | None = None,
    available_backends: list[str] | None = None,
) -> str:
    """Build a descriptive message listing issues by severity."""
    # Compute "also available" backends (available but not configured)
    also_available = [b for b in (available_backends or []) if b not in (backends or [])]

    if status is CommandStatus.OK:
        if backends:
            backend_str = ", ".join(backends)
            suffix = f"; also available: {', '.join(also_available)}" if also_available else ""
            return f"Secrets subsystem ready (backend: {backend_str}{suffix})."
        return "Secrets subsystem ready."

    # Collect issues by severity
    missing = [e["component"] for e in checks if e.get("status") == "missing"]
    warnings = [e["component"] for e in checks if e.get("status") == "warning"]

    parts: list[str] = []
    if missing:
        parts.append(f"[red]Missing ({len(missing)})[/red]: {', '.join(missing)}")
    if warnings:
        parts.append(f"[yellow]Warnings ({len(warnings)})[/yellow]: {', '.join(warnings)}")
    if also_available:
        parts.append(f"Available on system: {', '.join(also_available)}")

    # Actionable hint when configured backend is unavailable
    hint = _build_backend_mismatch_hint(backends or [], available_backends or [])
    if hint:
        parts.append(hint)

    return "Secrets subsystem issues:\n" + "\n".join(parts)


def _collect_backend_checks(
    configured: list[str],
    available: list[str],
) -> list[CheckEntry]:
    """Collect check entries for configured (deep) and unconfigured (lightweight) backends."""
    entries: list[CheckEntry] = []

    # Deep checks for configured backends
    if "age" in configured:
        entries.extend([_check_age_keygen(), _check_age_key()])
        consistency_check = _check_age_key_consistency()
        if consistency_check:
            entries.append(consistency_check)
    if "gpg" in configured:
        entries.extend([_check_gpg_binary(), _check_gpg_keys()])
    if "kms" in configured:
        entries.extend([_check_boto3(), _check_aws_credentials()])

    # Lightweight checks for available but not configured backends
    unconfigured = [b for b in available if b not in configured]
    for backend in unconfigured:
        if backend == "age":
            entries.append(_check_age_keygen())
        elif backend == "gpg":
            entries.append(_check_gpg_binary())
        elif backend == "kms":
            entries.append(_check_boto3())

    return entries


def doctor() -> None:
    """Run diagnostics for the secrets subsystem.

    Only checks components relevant to the configured backend(s) in .sops.yaml.
    If no .sops.yaml is found, reports a critical error.
    """
    checks: list[CheckEntry] = [
        # Core SOPS - always required
        _check_sops_binary(),
        _check_sops_config(),
    ]

    # Detect backends from config to conditionally run checks
    config_path = _find_sops_config_path()
    backends = _detect_sops_backends(config_path) if config_path else []

    # If no specific backend detected, assume age (most common for kstlib users)
    if not backends and config_path:
        backends = ["age"]

    # Scan system for available backends (lightweight binary/package detection)
    available = _scan_available_backends()

    # Deep checks for CONFIGURED backends + lightweight for unconfigured
    checks.extend(_collect_backend_checks(backends, available))

    # Keyring is always checked (used for token caching regardless of backend)
    checks.append(_check_keyring())

    config_checks, resolver_config = _evaluate_config_state()
    checks.extend(config_checks)

    status = _derive_doctor_status(checks)
    message = _build_doctor_message(checks, status, backends, available)
    payload: dict[str, Any] = {
        "checks": checks,
        "backends": backends,
        "available_backends": available,
    }
    if resolver_config is not None:
        payload["resolver"] = resolver_config

    result = CommandResult(status=status, message=message, payload=payload)
    render_result(result)
    if result.status is CommandStatus.ERROR:
        raise typer.Exit(code=1)


# =============================================================================
# Init Command Helpers
# =============================================================================


def _get_default_sops_paths(local: bool) -> tuple[Path, Path]:
    """Return (age_key_path, sops_config_path) based on platform and local flag.

    Note: SOPS always looks for .sops.yaml in $HOME (not APPDATA on Windows),
    but age keys are stored in platform-specific locations.
    """
    if local:
        return (Path(".age-key.txt"), Path(".sops.yaml"))

    home = Path.home()
    # SOPS config is ALWAYS in $HOME/.sops.yaml (SOPS does not check APPDATA)
    config_path = home / ".sops.yaml"

    if os.name == "nt":  # Windows
        # Age keys are stored in %APPDATA%\sops\age\keys.txt
        appdata = os.getenv("APPDATA")
        if appdata:
            key_path = Path(appdata) / "sops" / "age" / "keys.txt"
            return (key_path, config_path)

    # Linux/macOS: keys in ~/.config/sops/age/keys.txt
    return (home / ".config" / "sops" / "age" / "keys.txt", config_path)


def _generate_age_key(key_path: Path) -> str | None:
    """Generate an age key and return the public key, or None on failure."""
    age_keygen = shutil.which("age-keygen")
    if not age_keygen:
        return None

    key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    result = run(
        [age_keygen, "-o", str(key_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None

    # Extract public key from stderr (age-keygen outputs it there)
    for line in result.stderr.splitlines():
        if line.startswith("Public key:"):
            return line.split(":", 1)[1].strip()
    # Fallback: read from the file
    if key_path.exists():
        content = key_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            if line.startswith("# public key:"):
                return line.split(":", 1)[1].strip()
    return None


def _create_sops_config(config_path: Path, public_key: str) -> bool:
    """Create a .sops.yaml config file with the given public key."""
    # pylint: disable=no-else-return  # TRY300 requires else block
    config_content = f"""\
# SOPS configuration - generated by kstlib secrets init
creation_rules:
  - path_regex: .*\\.(yml|yaml)$
    encrypted_regex: .*(?:sops|key|password|secret|token|credentials?).*
    age: {public_key}
"""
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        config_path.write_text(config_content, encoding="utf-8")
    except OSError:
        return False
    else:
        return True


def _read_existing_public_key(key_path: Path) -> str | None:
    """Read public key from an existing age key file."""
    try:
        content = key_path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in content.splitlines():
        if line.startswith("# public key:"):
            return line.split(":", 1)[1].strip()
    return None


def _resolve_init_backend(backend: str | None) -> str:
    """Resolve which backend to use for init.

    Priority: explicit choice > age > gpg > error.

    Args:
        backend: Explicit backend choice, or None for auto-detection.

    Returns:
        The resolved backend name ("age" or "gpg").

    Raises:
        SystemExit: If the requested or detected backend is not available.
    """
    valid_backends = ("age", "gpg")
    if backend is not None:
        backend = backend.lower()
        if backend not in valid_backends:
            exit_error(f"Invalid backend '{backend}'. Choose from: {', '.join(valid_backends)}.")
        available = _scan_available_backends()
        if backend not in available:
            exit_error(f"Backend '{backend}' requested but not available. Install it first.")
        return backend

    available = _scan_available_backends()
    resolved = next((p for p in valid_backends if p in available), None)
    if resolved is None:
        exit_error("No encryption backend found. Install age or GPG first (see: kstlib secrets doctor).")
    return resolved


def _get_gpg_fingerprint() -> str:
    """Get the fingerprint of the first GPG secret key.

    Returns:
        The fingerprint string.

    Raises:
        SystemExit: If GPG is not found or no secret keys exist.
    """
    gpg_path = shutil.which("gpg") or shutil.which("gpg2")
    if not gpg_path:
        exit_error("GPG not found. Install GPG first.")

    result = run(
        [gpg_path, "--list-secret-keys", "--with-colons"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        exit_error("Failed to list GPG secret keys.")

    fingerprint = ""
    for line in result.stdout.splitlines():
        if line.startswith("fpr:"):
            fpr = line.split(":")[9]
            if fpr:
                fingerprint = fpr
                break

    if not fingerprint:
        exit_error("No GPG secret keys found. Run 'gpg --gen-key' first.")
    return fingerprint


def _create_sops_config_gpg(config_path: Path, fingerprint: str) -> bool:
    """Create a .sops.yaml config file for GPG backend.

    Args:
        config_path: Path where the config file will be written.
        fingerprint: GPG key fingerprint to use for encryption.

    Returns:
        True if the file was created successfully, False otherwise.
    """
    config_content = f"""\
# SOPS configuration - generated by kstlib secrets init
creation_rules:
  - path_regex: .*\\.(yml|yaml)$
    encrypted_regex: .*(?:sops|key|password|secret|token|credentials?).*
    pgp: {fingerprint}
"""
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        config_path.write_text(config_content, encoding="utf-8")
    except OSError:
        return False
    return True


def _ensure_age_key(key_path: Path, *, force: bool) -> tuple[str, bool]:
    """Ensure age key exists, return (public_key, was_created)."""
    if key_path.exists() and not force:
        public_key = _read_existing_public_key(key_path)
        if not public_key:
            exit_error(f"Age key exists at {key_path} but could not read public key.")
        console.print(f"[dim]Age key already exists:[/dim] {key_path}")
        return public_key, False

    # Delete existing file if force (age-keygen won't overwrite)
    if key_path.exists():
        key_path.unlink()
    public_key = _generate_age_key(key_path)
    if not public_key:
        exit_error(f"Failed to generate age key at {key_path}.")
    return public_key, True


def _ensure_sops_config(config_path: Path, public_key: str, *, force: bool) -> bool:
    """Ensure SOPS config exists, return True if created."""
    if config_path.exists() and not force:
        console.print(f"[dim]SOPS config already exists:[/dim] {config_path}")
        return False

    if not _create_sops_config(config_path, public_key):
        exit_error(f"Failed to create SOPS config at {config_path}.")
    return True


def _init_age(*, local: bool, force: bool) -> None:
    """Run the age backend init flow."""
    key_path, config_path = _get_default_sops_paths(local)
    created_files: list[str] = []

    public_key, key_created = _ensure_age_key(key_path, force=force)
    if key_created:
        created_files.append(str(key_path))

    if _ensure_sops_config(config_path, public_key, force=force):
        created_files.append(str(config_path))

    if created_files:
        summary = "Created (backend: age):\n" + "\n".join(f"  - {f}" for f in created_files)
        summary += f"\n\nPublic key: {public_key}"
        if local:
            summary += "\n\n[dim]Add .age-key.txt to .gitignore![/dim]"
        render_result(CommandResult(status=CommandStatus.OK, message=summary))
    else:
        render_result(
            CommandResult(
                status=CommandStatus.WARNING,
                message="All files already exist. Use --force to overwrite.",
            )
        )


def _init_gpg(*, local: bool, force: bool) -> None:
    """Run the GPG backend init flow."""
    fingerprint = _get_gpg_fingerprint()
    _, config_path = _get_default_sops_paths(local)

    if config_path.exists() and not force:
        console.print(f"[dim]SOPS config already exists:[/dim] {config_path}")
        render_result(
            CommandResult(
                status=CommandStatus.WARNING,
                message="All files already exist. Use --force to overwrite.",
            )
        )
        return

    if not _create_sops_config_gpg(config_path, fingerprint):
        exit_error(f"Failed to create SOPS config at {config_path}.")

    short_fp = f"{fingerprint[:4]}...{fingerprint[-4:]}" if len(fingerprint) > 12 else fingerprint
    summary = f"Created (backend: gpg):\n  - {config_path}\n\nGPG fingerprint: {short_fp}"
    render_result(CommandResult(status=CommandStatus.OK, message=summary))


def init(
    *,
    local: bool = INIT_LOCAL_OPTION,
    force: bool = INIT_FORCE_OPTION,
    backend: str | None = INIT_BACKEND_OPTION,
) -> None:
    """Quick setup: generate key/config for secrets encryption.

    Auto-detects the best available backend (age > gpg) or use --backend
    to choose explicitly. By default, creates files in the user's home
    directory (cross-platform). Use --local for the current directory.
    """
    resolved = _resolve_init_backend(backend)

    if resolved == "age":
        _init_age(local=local, force=force)
    else:
        _init_gpg(local=local, force=force)


__all__ = ["doctor", "init"]
