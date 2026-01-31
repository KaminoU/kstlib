"""Shared pytest fixtures for kstlib test suite."""

from __future__ import annotations

# Disable Rich colors and force wide terminal BEFORE any imports
# Rich checks these at import time
import os

os.environ["NO_COLOR"] = "1"
os.environ["TERM"] = "dumb"
os.environ["FORCE_COLOR"] = "0"
os.environ["COLUMNS"] = "200"  # Prevent text wrapping in CLI output

import pathlib
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

# Import private internals for testing purposes
import kstlib.config.loader as _cfg_loader

# pylint: disable=redefined-outer-name


@pytest.fixture(scope="session")
def fixtures_root() -> Path:
    """Return the root directory containing persistent test fixtures."""

    return pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def get_fixture_path(fixtures_root: Path) -> Callable[[str], Path]:
    """Build a path helper bound to the shared fixtures directory."""

    def _get(subdir: str) -> Path:
        """Return the absolute path for a given fixture subdirectory."""

        return fixtures_root / subdir

    return _get


@pytest.fixture
def copy_fixture(
    get_fixture_path: Callable[[str], Path],
    tmp_path: Path,
) -> Callable[[str, str, str | None], Path]:
    """Copy a fixture file into the pytest temp directory."""

    def _copy(subdir: str, fixture_name: str, dest_name: str | None = None) -> Path:
        """Copy the requested fixture file and return the destination path."""

        src = get_fixture_path(subdir) / fixture_name
        dst = tmp_path / (dest_name or fixture_name)
        shutil.copyfile(src, dst)
        return dst

    return _copy


# ============================================================================
# CONFIG MODULE PRIVATE INTERNALS - For testing purposes only
# ============================================================================


@pytest.fixture
def cfg_loader() -> Any:
    """Expose config.loader module for testing private methods.

    This fixture provides access to internal implementation details
    that are not part of the public API. Used for unit testing only.

    Returns:
        Module object containing private config loader internals.
    """
    return _cfg_loader


# ============================================================================
# PERF MODULE FIXTURES - For testing chunked readers and metrics
# ============================================================================


@pytest.fixture
def temp_file(tmp_path: Path) -> Path:
    """Create a temporary file for testing."""
    file_path = tmp_path / "test.txt"
    file_path.write_text("line1\nline2\nline3\nline4\nline5\n")
    return file_path


@pytest.fixture
def temp_csv(tmp_path: Path) -> Path:
    """Create a temporary CSV file for testing."""
    file_path = tmp_path / "test.csv"
    lines = ["id,name,value"]
    for i in range(100):
        lines.append(f"{i},item_{i},{i * 10}")
    file_path.write_text("\n".join(lines) + "\n")
    return file_path


@pytest.fixture
def temp_binary(tmp_path: Path) -> Path:
    """Create a temporary binary file for testing."""
    file_path = tmp_path / "test.bin"
    file_path.write_bytes(b"hello world " * 1000)
    return file_path


@pytest.fixture
def large_temp_file(tmp_path: Path) -> Path:
    """Create a larger temporary file for parallel tests."""
    file_path = tmp_path / "large.txt"
    lines = [f"line {i}: some content here" for i in range(10000)]
    file_path.write_text("\n".join(lines) + "\n")
    return file_path
