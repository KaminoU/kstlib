"""Clean-install gate: import every public module of the INSTALLED kstlib package.

This script is run by the ``cleaninstall-*`` tox environments against a virtual
environment that contains only the built wheel and its DECLARED dependencies:
no extras, no test tooling, no editable install.

Why it exists: a development environment cannot detect a phantom runtime
dependency, because its own tooling installs the missing package as a side
effect. Only an environment built like a consumer's can. The multi-version test
matrix is blind to this whole class of defect by construction, and adding one
more Python version to it would not change that.

Two properties make the gate hold over time:

* The module list is DISCOVERED, never hardcoded, so a module added later is
  covered on the day it is created. Discovery reads the installed distribution,
  which also means a module missing from the wheel is reported here rather than
  by a consumer.
* Discovery is RECURSIVE, because a subpackage may defer part of its own
  surface: importing it is not enough to reach the modules behind its lazy
  attribute loader.

Exit code is 0 when every public module imports and every export resolves,
1 otherwise.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
import traceback
from types import ModuleType

# Floor on the number of discovered modules. Discovery that silently returned an
# empty list would make this script exit 0 without importing anything, which
# reads exactly like a success. The floor sits well under the real count so a
# legitimate removal does not trip it, but a broken discovery does.
MIN_EXPECTED_MODULES = 50

Failure = tuple[str, str]


def walk_public_modules(root: ModuleType) -> tuple[list[ModuleType], list[Failure]]:
    """Recursively import every public module below a root package.

    Names starting with an underscore are skipped at any depth, which covers
    private modules and ``__main__`` (importing the latter is not part of the
    surface a consumer exercises). A package that fails to import is reported
    and not descended into, so its own failure is never masked by its children.

    Args:
        root: Imported root package to walk.

    Returns:
        Tuple of (successfully imported modules, failures). Each failure is a
        ``(module name, formatted traceback)`` pair.
    """
    imported: list[ModuleType] = []
    failures: list[Failure] = []
    pending: list[ModuleType] = [root]

    while pending:
        package = pending.pop(0)
        for info in pkgutil.iter_modules(package.__path__):
            if info.name.startswith("_"):
                continue
            name = f"{package.__name__}.{info.name}"
            try:
                module = importlib.import_module(name)
            except Exception:  # noqa: BLE001 - any import failure is a finding
                failures.append((name, traceback.format_exc()))
                continue
            imported.append(module)
            if info.ispkg:
                pending.append(module)

    return imported, failures


def resolve_exports(modules: list[ModuleType]) -> tuple[int, list[Failure]]:
    """Resolve every name listed in each module's ``__all__``.

    The root package and some subpackages use PEP 562 lazy loading, so importing
    them loads nothing on its own. Attribute access is what triggers the
    underlying import, and is therefore the only way to cover those symbols.

    Args:
        modules: Imported modules whose ``__all__`` is resolved.

    Returns:
        Tuple of (number of names resolved, failures). Each failure is a
        ``(qualified name, formatted traceback)`` pair.
    """
    resolved = 0
    failures: list[Failure] = []

    for module in modules:
        for name in sorted(getattr(module, "__all__", ())):
            resolved += 1
            try:
                getattr(module, name)
            except Exception:  # noqa: BLE001 - any resolution failure is a finding
                failures.append((f"{module.__name__}.{name}", traceback.format_exc()))

    return resolved, failures


def main() -> int:
    """Run the clean-install import gate.

    Returns:
        0 when every public module imports and every export resolves, 1 otherwise.
    """
    import kstlib

    print(f"python  : {sys.version}")
    print(f"kstlib  : {kstlib.__version__}")
    print(f"location: {kstlib.__file__}")

    imported, failures = walk_public_modules(kstlib)
    resolved, export_failures = resolve_exports([kstlib, *imported])
    failures += export_failures

    checks = len(imported) + resolved
    print(f"walked {len(imported)} public modules, resolved {resolved} exports")

    if len(imported) < MIN_EXPECTED_MODULES:
        print(
            f"\nDISCOVERY FAILED: walked {len(imported)} modules, expected at least "
            f"{MIN_EXPECTED_MODULES}. The gate did not actually run."
        )
        return 1

    if failures:
        print(f"\n{'=' * 70}")
        print(f"CLEAN INSTALL GATE FAILED: {len(failures)} of {checks} checks")
        print(f"{'=' * 70}")
        for name, formatted in failures:
            print(f"\n--- FAILED: {name} ---")
            print(formatted)
        return 1

    print(f"\nOK: {checks} checks passed on a clean install")
    return 0


if __name__ == "__main__":
    sys.exit(main())
