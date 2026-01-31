"""Test fixtures for database module."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture
def temp_db_path() -> Generator[Path, None, None]:
    """Create a temporary database file path."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    yield path
    # Cleanup
    if path.exists():
        path.unlink()
    # Also cleanup WAL and SHM files
    for ext in (".db-wal", ".db-shm"):
        wal_path = path.with_suffix(ext)
        if wal_path.exists():
            wal_path.unlink()
