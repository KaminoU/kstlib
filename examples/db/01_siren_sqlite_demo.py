#!/usr/bin/env python3
"""Demonstrate SQLite :memory: for CSV analytics (SIREN dataset).

This example shows how to use AsyncDatabase with :memory: to perform
SQL analytics on large CSV files - often faster and more memory-efficient
than pandas DataFrames for aggregation queries.

Dataset: Stock Historique des Etablissements SIRENE (data.gouv.fr)
File: StockEtablissementHistorique_utf8.csv (~9 GB, 92M rows)

Usage:
    python examples/db/01_siren_sqlite_demo.py [batch_size] [year_filter]

    batch_size:  Number of rows per INSERT batch (default: 10000)
                 Try different values to see performance impact:
                 - 1000:  More commits, slower
                 - 10000: Good balance (default)
                 - 50000: Fewer commits, more RAM per batch

    year_filter: Filter records by year (default: 2025)
                 - 2025: Only 2025 records (~3M rows)
                 - 2024: Only 2024 records
                 - all:  Load ALL records (~92M rows, needs ~3GB RAM)

Key columns used:
    - dateDebut: establishment creation date (YYYY-MM-DD)
    - denominationUsuelleEtablissement: common business name
    - etatAdministratifEtablissement: A=active, F=closed
    - activitePrincipaleEtablissement: NAF activity code
"""

from __future__ import annotations

import asyncio
import csv
import sys
from collections.abc import Iterator
from pathlib import Path

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from kstlib.db import AsyncDatabase
from kstlib.metrics import Stopwatch
from kstlib.ui.spinner import SpinnerWithLogZone

# Optional: psutil for process memory (pip install psutil)
try:
    import psutil  # type: ignore[import-untyped]

    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


# CSV column indexes (from header)
COL_DATE_DEBUT = 4
COL_ETAT_ADMIN = 5
COL_DENOMINATION = 11
COL_ACTIVITE = 13

# Configurable defaults (from CLI args)
BATCH_SIZE = 10000
YEAR_FILTER = "2025"


def csv_row_generator(
    csv_path: Path,
    batch_size: int = BATCH_SIZE,
    year_filter: str = YEAR_FILTER,
) -> Iterator[tuple[tuple[str, str, str, str], ...]]:
    """Yield filtered rows from CSV as tuples for bulk insert.

    Args:
        csv_path: Path to the CSV file.
        batch_size: Number of rows per batch (affects memory/speed tradeoff).
        year_filter: Year to filter on, or "all" for no filter.

    Yields:
        Tuples of (dateDebut, etatAdmin, denomination, activite).
    """
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        next(reader)  # Skip header

        batch: list[tuple[str, str, str, str]] = []
        filter_all = year_filter.lower() == "all"

        for row in reader:
            date_debut = row[COL_DATE_DEBUT] if len(row) > COL_DATE_DEBUT else ""

            # Apply year filter (or load all if "all")
            if filter_all or date_debut.startswith(year_filter):
                batch.append(
                    (
                        date_debut,
                        row[COL_ETAT_ADMIN] if len(row) > COL_ETAT_ADMIN else "",
                        row[COL_DENOMINATION] if len(row) > COL_DENOMINATION else "",
                        row[COL_ACTIVITE] if len(row) > COL_ACTIVITE else "",
                    )
                )

                if len(batch) >= batch_size:
                    yield tuple(batch)
                    batch = []

        # Yield remaining
        if batch:
            yield tuple(batch)


async def main() -> None:
    """Run SIREN analytics demo."""
    # Parse CLI args: batch_size [year_filter]
    batch_size = BATCH_SIZE
    year_filter = YEAR_FILTER

    if len(sys.argv) > 1:
        try:
            batch_size = int(sys.argv[1])
        except ValueError:
            print(f"Invalid batch_size: {sys.argv[1]}, using default {BATCH_SIZE}")

    if len(sys.argv) > 2:
        year_filter = sys.argv[2]

    print("=" * 70)
    print("SQLITE :memory: FOR CSV ANALYTICS")
    print("=" * 70)
    print("\nDataset: Stock Historique des Etablissements SIRENE")
    print("Source: data.gouv.fr (INSEE)")
    print(f"Batch size: {batch_size:,} rows")
    if year_filter.lower() == "all":
        print("Year filter: ALL (loading entire dataset ~92M rows)")
    else:
        print(f"Year filter: {year_filter}")

    csv_path = Path("./tmp/StockEtablissementHistorique_utf8.csv")

    if not csv_path.exists():
        print(f"\n[SKIP] File not found: {csv_path}")
        print("       Download from: https://www.data.gouv.fr/fr/datasets/")
        print("       base-sirene-des-entreprises-et-de-leurs-etablissements-siren-siret/")
        return

    file_size_gb = csv_path.stat().st_size / (1024**3)
    print(f"File size: {file_size_gb:.2f} GB")

    sw = Stopwatch("SIREN Analytics")
    sw.start()

    # =========================================================================
    # PHASE 1: Create in-memory database with schema
    # =========================================================================
    print("\n" + "-" * 70)
    print("PHASE 1: Create SQLite :memory: database")
    print("-" * 70)

    async with AsyncDatabase(":memory:") as db:
        await db.execute("""
            CREATE TABLE etablissements (
                date_debut TEXT,
                etat_admin TEXT,
                denomination TEXT,
                activite TEXT
            )
        """)

        # Create index on date for faster queries
        await db.execute("""
            CREATE INDEX idx_date ON etablissements(date_debut)
        """)

        sw.lap("Schema created")
        print("  Schema created with index on date_debut")

        # =====================================================================
        # PHASE 2: Bulk insert 2025 records
        # =====================================================================
        filter_label = "ALL" if year_filter.lower() == "all" else year_filter
        print("\n" + "-" * 70)
        print(f"PHASE 2: Load {filter_label} records (streaming CSV)")
        print("-" * 70)

        total_inserted = 0

        # Use spinner with log zone for progress display
        with SpinnerWithLogZone(
            f"Loading {filter_label} records...",
            log_zone_height=5,
            style="DOTS",
        ) as spinner:
            # Progress every 5 batches (or minimum 50k rows)
            progress_interval = max(batch_size * 5, 50000)
            last_progress = 0

            for batch in csv_row_generator(csv_path, batch_size, year_filter):
                await db.executemany(
                    "INSERT INTO etablissements VALUES (?, ?, ?, ?)",
                    batch,
                )
                total_inserted += len(batch)

                # Update spinner message with current count
                spinner.update(f"Loading {filter_label} records... {total_inserted:,}")

                # Log progress at intervals
                if total_inserted - last_progress >= progress_interval:
                    spinner.log(f"Inserted: {total_inserted:,} rows", style="cyan")
                    last_progress = total_inserted

        sw.lap("Data loaded")
        print(f"\n  Total {filter_label} records: {total_inserted:,}")

        # =====================================================================
        # PHASE 3: Run analytics queries
        # =====================================================================
        print("\n" + "-" * 70)
        print("PHASE 3: Analytics queries")
        print("-" * 70)

        # Query 1: Count by month
        print(f"\n  [Query 1] Establishments created per month ({filter_label}):")
        if year_filter.lower() == "all":
            query1 = """
                SELECT
                    substr(date_debut, 1, 7) AS month,
                    COUNT(*) AS count
                FROM etablissements
                WHERE date_debut != ''
                GROUP BY month
                ORDER BY month DESC
                LIMIT 24
            """
        else:
            query1 = f"""
                SELECT
                    substr(date_debut, 1, 7) AS month,
                    COUNT(*) AS count
                FROM etablissements
                WHERE date_debut LIKE '{year_filter}%'
                GROUP BY month
                ORDER BY month
            """
        rows = await db.fetch_all(query1)
        sw.lap("Query 1: Monthly counts")

        print("\n    Month     | Count")
        print("    " + "-" * 25)
        for month, count in rows:
            print(f"    {month}   | {count:,}")

        # Query 2: Top 10 activity codes
        print("\n  [Query 2] Top 10 activity codes (NAF):")
        rows = await db.fetch_all("""
            SELECT
                activite,
                COUNT(*) AS count
            FROM etablissements
            WHERE activite != ''
            GROUP BY activite
            ORDER BY count DESC
            LIMIT 10
        """)
        sw.lap("Query 2: Top activities")

        print("\n    NAF Code | Count")
        print("    " + "-" * 25)
        for activite, count in rows:
            print(f"    {activite:<8} | {count:,}")

        # Query 3: Active vs Closed ratio
        print("\n  [Query 3] Status distribution (A=Active, F=Closed):")
        rows = await db.fetch_all("""
            SELECT
                etat_admin,
                COUNT(*) AS count,
                ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM etablissements), 2) AS pct
            FROM etablissements
            GROUP BY etat_admin
            ORDER BY count DESC
        """)
        sw.lap("Query 3: Status distribution")

        print("\n    Status | Count      | Percentage")
        print("    " + "-" * 35)
        for etat, count, pct in rows:
            status_label = "Active" if etat == "A" else "Closed" if etat == "F" else etat
            print(f"    {status_label:<6} | {count:>10,} | {pct}%")

        # Query 4: Sample denominations
        print(f"\n  [Query 4] Sample of business names ({filter_label}):")
        rows = await db.fetch_all("""
            SELECT DISTINCT denomination
            FROM etablissements
            WHERE denomination != ''
              AND denomination NOT LIKE '%TEST%'
            LIMIT 10
        """)
        sw.lap("Query 4: Sample names")

        print("\n    Business Names (sample):")
        for (name,) in rows:
            # Truncate long names
            display = name[:50] + "..." if len(name) > 50 else name
            print(f"    - {display}")

        # =====================================================================
        # PHASE 4: Memory introspection
        # =====================================================================
        print("\n" + "-" * 70)
        print("PHASE 4: Memory introspection")
        print("-" * 70)

        # SQLite database size (pages * page_size)
        page_count = await db.fetch_value("PRAGMA page_count")
        page_size = await db.fetch_value("PRAGMA page_size")
        db_size_mb = (page_count * page_size) / (1024 * 1024)

        print("\n  SQLite Database (PRAGMA):")
        print(f"    Page size:    {page_size:,} bytes")
        print(f"    Page count:   {page_count:,}")
        print(f"    DB size:      {db_size_mb:.1f} MB (data on disk equivalent)")

        # Process memory via psutil (if available)
        if HAS_PSUTIL:
            process = psutil.Process()
            mem_info = process.memory_info()
            print("\n  Process Memory (psutil):")
            print(f"    RSS (resident): {mem_info.rss / (1024**2):.1f} MB")
            print(f"    VMS (virtual):  {mem_info.vms / (1024**2):.1f} MB")
            print("\n  Note: RSS includes Python runtime (~30-50 MB baseline)")
            print(f"        SQLite :memory: DB is ~{db_size_mb:.0f} MB of the RSS")
        else:
            print("\n  [TIP] Install psutil for process memory stats:")
            print("        pip install psutil")

        sw.lap("Memory introspection")

    sw.stop()

    # =========================================================================
    # SUMMARY
    # =========================================================================
    print("\n" + "=" * 70)
    print("PERFORMANCE SUMMARY")
    print("=" * 70)
    sw.summary()

    print("\n" + "-" * 70)
    print("KEY TAKEAWAYS")
    print("-" * 70)
    print(f"""
  1. SQLite :memory: processes 92M row CSV efficiently
  2. Streaming insert (batch={batch_size:,}) keeps Python RAM low
  3. SQL queries are readable and fast (indexes help)
  4. No pandas dependency needed for aggregations
  5. Data vanishes on close (perfect for temp analytics)

  Memory breakdown:
  - Python: minimal (only batch buffer + iterator)
  - SQLite: ~DB size in RAM (managed by C library, not Python GC)
  - Total: fraction of what pandas would use

  Try different configurations:
    python examples/db/01_siren_sqlite_demo.py 10000 2025   # Default
    python examples/db/01_siren_sqlite_demo.py 10000 2024   # Year 2024
    python examples/db/01_siren_sqlite_demo.py 50000 all    # ALL records (~92M)
    """)


if __name__ == "__main__":
    asyncio.run(main())
