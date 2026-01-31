"""Run all spinner examples sequentially."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


def main() -> None:
    """Execute all spinner example modules."""
    examples_dir = Path(__file__).parent

    # Find all example modules (excluding __init__ and this file)
    example_files = sorted(f for f in examples_dir.glob("*.py") if f.name not in ("__init__.py", "run_all_examples.py"))

    print("=" * 60)
    print("Running All Spinner Examples")
    print("=" * 60)

    for example_file in example_files:
        module_name = f"examples.ui.spinner.{example_file.stem}"
        print(f"\n{'#' * 60}")
        print(f"# {example_file.name}")
        print(f"{'#' * 60}")

        try:
            module = importlib.import_module(module_name)
            if hasattr(module, "main"):
                module.main()
        except Exception as e:
            print(f"Error running {example_file.name}: {e}", file=sys.stderr)

    print("\n" + "=" * 60)
    print("All examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
