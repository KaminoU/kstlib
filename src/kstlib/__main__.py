"""Entry point for kstlib CLI application.

This module serves as the entry point when kstlib is invoked as a module
(python -m kstlib) or through the installed console script.
"""

from kstlib.cli import app


def main() -> None:
    """Run the kstlib CLI application."""
    app()


if __name__ == "__main__":
    main()
