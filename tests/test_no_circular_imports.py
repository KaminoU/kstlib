"""Verify that public kstlib entry points can be imported in a fresh Python process.

Circular imports only manifest when a module is the FIRST kstlib symbol
loaded in an otherwise-empty ``sys.modules``. Pytest's own init (conftest,
fixtures, plugin collection) pre-loads enough modules that cycles can
hide undetected in normal tests. These tests force a fresh Python
subprocess for each entry point so ``sys.modules`` starts empty.

Regression test added for fix-circular-import-mail (2026-04-24).
"""

from __future__ import annotations

import subprocess
import sys

import pytest

_SUBPROCESS_TIMEOUT_SECONDS = 30

_TOP_LEVEL_ENTRY_POINTS: list[str] = [
    "kstlib",
    "kstlib.alerts",
    "kstlib.auth",
    "kstlib.cache",
    "kstlib.cli",
    "kstlib.config",
    "kstlib.db",
    "kstlib.helpers",
    "kstlib.limits",
    "kstlib.logging",
    "kstlib.mail",
    "kstlib.metrics",
    "kstlib.monitoring",
    "kstlib.ops",
    "kstlib.pipeline",
    "kstlib.rapi",
    "kstlib.resilience",
    "kstlib.secrets",
    "kstlib.secure",
    "kstlib.ssl",
    "kstlib.transform",
    "kstlib.ui",
    "kstlib.utils",
    "kstlib.websocket",
]


@pytest.mark.parametrize("import_target", _TOP_LEVEL_ENTRY_POINTS)
def test_no_circular_import_fresh_python(import_target: str) -> None:
    """`import <target>` must succeed in a fresh Python process with empty sys.modules.

    Args:
        import_target: Fully qualified module name to import in a subprocess.

    """
    result = subprocess.run(
        [sys.executable, "-c", f"import {import_target}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=_SUBPROCESS_TIMEOUT_SECONDS,
    )
    assert result.returncode == 0, (
        f"Circular or failing import triggered by `import {import_target}`:\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )


_PUBLIC_SYMBOL_ENTRY_POINTS: list[tuple[str, str]] = [
    ("kstlib.mail", "MailBuilder"),
    ("kstlib.config", "get_config"),
    ("kstlib.config", "reload_config"),
    ("kstlib.config", "load_config"),
    ("kstlib.rapi", "RapiClient"),
    ("kstlib.limits", "HARD_MAX_CONFIG_FILE_SIZE"),
    ("kstlib.limits", "DEFAULT_MAX_SOPS_CACHE_ENTRIES"),
]

#: Submodules whose init historically participated in circular import
#: cycles with ``kstlib.limits``. Importing them fresh must succeed.
_CYCLE_GUARD_SUBMODULES: list[str] = [
    "kstlib.config.sops",
]


@pytest.mark.parametrize("import_target", _CYCLE_GUARD_SUBMODULES)
def test_no_circular_import_cycle_guard_submodule(import_target: str) -> None:
    """`import <submodule>` must succeed fresh, even for historical cycle actors.

    Guards against regressions of the specific cycle fixed in 2.3.1,
    where ``kstlib.config.sops`` re-entered a still-initialising
    ``kstlib.limits`` during ``kstlib.config.__init__`` cascade.

    Args:
        import_target: Fully qualified submodule name to import fresh.

    """
    result = subprocess.run(
        [sys.executable, "-c", f"import {import_target}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=_SUBPROCESS_TIMEOUT_SECONDS,
    )
    assert result.returncode == 0, (
        f"Circular or failing import triggered by `import {import_target}`:\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )


@pytest.mark.parametrize(("module", "symbol"), _PUBLIC_SYMBOL_ENTRY_POINTS)
def test_no_circular_import_from_public_symbol(module: str, symbol: str) -> None:
    """`from <module> import <symbol>` must succeed in a fresh Python process.

    Args:
        module: Fully qualified kstlib module from which to import the symbol.
        symbol: Public name to import from ``module``.

    """
    result = subprocess.run(
        [sys.executable, "-c", f"from {module} import {symbol}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=_SUBPROCESS_TIMEOUT_SECONDS,
    )
    assert result.returncode == 0, (
        f"Circular or failing import triggered by `from {module} import {symbol}`:\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
