#!/usr/bin/env python3
"""Demonstrate the unified @metrics decorator for timing and profiling.

This example shows the config-driven metrics decorator available in kstlib.metrics.

Usage:
    python examples/metrics/01_decorators_demo.py
"""

from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from kstlib.metrics import (
    Stopwatch,
    call_stats,
    clear_metrics,
    metrics,
    metrics_context,
    metrics_summary,
    print_all_call_stats,
    reset_all_call_stats,
)


def demo_unified_decorator() -> None:
    """Demonstrate the unified @metrics decorator."""
    print("\n" + "=" * 60)
    print("1. UNIFIED @metrics DECORATOR")
    print("=" * 60)

    # Default behavior: time + memory from config
    @metrics
    def compute_sum() -> int:
        """Compute a large sum."""
        return sum(range(1_000_000))

    # Time only (disable memory tracking)
    @metrics(memory=False)
    def quick_compute() -> int:
        """Quick computation without memory tracking."""
        return sum(range(100_000))

    # Custom title
    @metrics("Loading configuration")
    def load_config() -> dict[str, str]:
        """Load configuration."""
        time.sleep(0.05)
        return {"db": "postgresql://..."}

    print("\n--- Default (time + memory) ---")
    _ = compute_sum()

    print("\n--- Time only (memory=False) ---")
    _ = quick_compute()

    print("\n--- Custom title ---")
    _ = load_config()


def demo_context_manager() -> None:
    """Demonstrate context manager usage."""
    print("\n" + "=" * 60)
    print("2. CONTEXT MANAGER")
    print("=" * 60)

    print("\n--- metrics_context() ---")
    with metrics_context("Allocate list"):
        data = [0] * 100_000
        del data

    print("\n--- With custom options ---")
    with metrics_context("Quick computation", memory=False):
        _ = sum(range(1_000_000))


def demo_step_tracking() -> None:
    """Demonstrate step tracking for pipelines."""
    print("\n" + "=" * 60)
    print("3. STEP TRACKING")
    print("=" * 60)

    clear_metrics()

    @metrics(step=True)
    def load_data() -> dict[str, str]:
        """Load configuration."""
        time.sleep(0.05)
        return {"db": "postgresql://..."}

    @metrics(step=True, title="Fetch data from source")
    def fetch_data() -> list[int]:
        """Fetch data from external source."""
        time.sleep(0.1)
        return list(range(1000))

    @metrics(step=True, title="Transform records")
    def transform(data: list[int]) -> list[int]:
        """Transform the data."""
        time.sleep(0.08)
        return [x * 2 for x in data]

    @metrics(step=True)
    def save_results(data: list[int]) -> None:
        """Save results to database."""
        time.sleep(0.03)

    print("\nRunning pipeline...\n")

    _ = load_data()
    raw_data = fetch_data()
    transformed = transform(raw_data)
    save_results(transformed)

    print("\n--- Steps Summary (table) ---")
    metrics_summary(style="table")

    print("\n--- Steps Summary (simple) ---")
    clear_metrics()

    # Run again for simple summary
    @metrics(step=True)
    def step_a() -> None:
        time.sleep(0.05)

    @metrics(step=True, title="Step B")
    def step_b() -> None:
        time.sleep(0.1)

    step_a()
    step_b()
    metrics_summary(style="simple")


def demo_call_stats() -> None:
    """Demonstrate call statistics tracking."""
    print("\n" + "=" * 60)
    print("4. CALL STATISTICS")
    print("=" * 60)

    reset_all_call_stats()

    @call_stats
    def api_call() -> None:
        """Simulate API call with variable latency."""
        time.sleep(0.01 + 0.01 * (hash(time.time()) % 5) / 10)

    print("\nMaking 5 API calls...")
    for _ in range(5):
        api_call()

    print("\n--- Call statistics ---")
    print_all_call_stats()


def demo_stopwatch() -> None:
    """Demonstrate manual stopwatch."""
    print("\n" + "=" * 60)
    print("5. STOPWATCH")
    print("=" * 60)

    sw = Stopwatch("Data Pipeline")
    sw.start()

    # Phase 1
    time.sleep(0.05)
    sw.lap("Load config")

    # Phase 2
    time.sleep(0.1)
    sw.lap("Fetch data")

    # Phase 3
    time.sleep(0.08)
    sw.lap("Transform")

    # Phase 4
    time.sleep(0.03)
    sw.lap("Save")

    sw.stop()

    print("\n--- Stopwatch Summary ---")
    sw.summary()


def demo_file_loading() -> None:
    """Demonstrate naive vs chunked file loading comparison.

    Uses the SIRENE historical establishments stock from data.gouv.fr
    (StockEtablissementHistorique_utf8.csv - January 8, 2026 snapshot).

    This demo shows:
    - Naive loading: reads entire file into memory (bad for large files)
    - Chunked loading: yields chunks of 7000 lines (memory efficient)

    Both compute the same sha256 checksum to prove identical data was read.

    Benchmark results (9 GB CSV file, 92M lines, Windows 11, 32 GB RAM):
    -----------------------------------------------------------------------
    | Method          | Time   | Peak Memory | Lines      | SHA256 Match |
    |-----------------|--------|-------------|------------|--------------|
    | Naive (full)    | 6m 27s | 40.1 GB *   | 92,227,503 | (reference)  |
    | Chunked (7000)  | 1m 29s | 1.2 MB      | 92,227,503 | YES          |
    -----------------------------------------------------------------------

    * Peak Memory is memory ALLOCATED by Python (tracemalloc), not physical
      RAM. When allocation exceeds available RAM, the OS uses swap (virtual
      memory on disk), which explains why naive is 4x slower despite doing
      the same work - it's constantly swapping to disk!

    Key takeaways:
    - Chunked uses 33,000x LESS memory (1.2 MB vs 40 GB)
    - Chunked is 4x FASTER (no swap thrashing)
    - Both produce identical SHA256 checksums
    - The @metrics decorator reveals this difference instantly
    """
    print("\n" + "=" * 60)
    print("6. FILE LOADING COMPARISON")
    print("=" * 60)
    print("\nDataset: Stock Historique des Etablissements SIRENE")
    print("Source: data.gouv.fr (snapshot 8 janvier 2026)")

    csv_path = Path("./tmp/StockEtablissementHistorique_utf8.csv")

    if not csv_path.exists():
        print(f"\n[SKIP] File not found: {csv_path}")
        print("       Download from: https://www.data.gouv.fr/fr/datasets/")
        print("       base-sirene-des-entreprises-et-de-leurs-etablissements-siren-siret/")
        return

    file_size_mb = csv_path.stat().st_size / (1024 * 1024)
    print(f"File size: {file_size_mb:.1f} MB")

    # Results storage for comparison
    results: dict[str, dict[str, int | float | str]] = {}

    # =========================================================================
    # METHOD 1: Naive loading (entire file in memory)
    # =========================================================================
    print("\n" + "-" * 60)
    print("METHOD 1: Naive loading (entire file in memory)")
    print("-" * 60)
    print(">>> WARNING: This loads the ENTIRE file into RAM!")

    @metrics("Naive: Read entire file")
    def load_naive() -> tuple[int, str]:
        """Load entire file into memory and compute stats."""
        # Read raw bytes for accurate hash
        with open(csv_path, "rb") as f:
            raw_content = f.read()

        # Count lines (decode for counting)
        content = raw_content.decode("utf-8")
        lines = content.splitlines()
        line_count = len(lines)

        # Compute sha256 on raw bytes (not re-encoded text)
        sha256_hash = hashlib.sha256(raw_content).hexdigest()

        return line_count, sha256_hash

    naive_lines: int | None = None
    naive_sha256: str | None = None
    naive_crashed = False

    try:
        naive_lines, naive_sha256 = load_naive()
        results["naive"] = {
            "lines": naive_lines,
            "sha256": naive_sha256,
        }
        print(f"\n  Lines read: {naive_lines:,}")
        print(f"  SHA256: {naive_sha256[:16]}...{naive_sha256[-16:]}")
    except MemoryError:
        naive_crashed = True
        print("\n  >>> MEMORY ERROR! System ran out of RAM!")
        print("  >>> This is EXACTLY why naive loading is dangerous!")
        print("  >>> The file is too large to fit in memory.")

    # =========================================================================
    # METHOD 2: Chunked loading with generator (memory efficient)
    # =========================================================================
    print("\n" + "-" * 60)
    print("METHOD 2: Chunked loading (7000 lines per chunk)")
    print("-" * 60)
    print(">>> Memory efficient: only one chunk in memory at a time")

    @metrics("Chunked: Read by 7000-line chunks")
    def load_chunked() -> tuple[int, str]:
        """Load file in chunks and compute stats (hash-compatible with naive)."""
        hasher = hashlib.sha256()
        line_count = 0
        chunk_size = 7000
        current_chunk: list[bytes] = []

        # Read raw bytes line by line for accurate hash
        with open(csv_path, "rb") as f:
            for raw_line in f:
                hasher.update(raw_line)
                line_count += 1
                current_chunk.append(raw_line)

                # Yield chunk when full (for memory demo purposes)
                if len(current_chunk) >= chunk_size:
                    current_chunk = []

        sha256_hash = hasher.hexdigest()
        return line_count, sha256_hash

    chunked_lines, chunked_sha256 = load_chunked()
    results["chunked"] = {
        "lines": chunked_lines,
        "sha256": chunked_sha256,
    }

    print(f"\n  Lines read: {chunked_lines:,}")
    print(f"  SHA256: {chunked_sha256[:16]}...{chunked_sha256[-16:]}")

    # =========================================================================
    # COMPARISON SUMMARY
    # =========================================================================
    print("\n" + "=" * 60)
    print("COMPARISON SUMMARY")
    print("=" * 60)

    print("\n  Method          | Lines      | SHA256 Match | Status")
    print("  " + "-" * 60)

    if naive_crashed:
        print("  Naive (full)    |        N/A | N/A          | CRASHED (MemoryError)")
        print(f"  Chunked (7000)  | {chunked_lines:>10,} | (reference)  | SUCCESS")
        print("\n  >>> NAIVE METHOD CRASHED - Out of memory!")
        print("  >>> CHUNKED METHOD SUCCEEDED - Processed entire file!")
        print("\n  This perfectly demonstrates why chunked loading is essential")
        print("  for large files. The naive method tried to load 9GB into RAM")
        print("  while chunked only needs memory for 7000 lines at a time.")
    else:
        print(f"  Naive (full)    | {naive_lines:>10,} | (reference)  | SUCCESS")
        match_status = "YES" if naive_sha256 == chunked_sha256 else "NO"
        print(f"  Chunked (7000)  | {chunked_lines:>10,} | {match_status:12} | SUCCESS")

        if naive_sha256 == chunked_sha256:
            print("\n  >>> IDENTICAL DATA READ - Same SHA256 checksum!")
            print("  >>> But chunked method uses MUCH LESS memory!")
        else:
            print("\n  >>> WARNING: SHA256 mismatch!")
            print(f"      Naive:   {naive_sha256}")
            print(f"      Chunked: {chunked_sha256}")

    print("\n  Key insight: The @metrics decorator reveals memory usage.")
    print("  Chunked loading is the ONLY viable option for large files.")


def main() -> None:
    """Run all demos."""
    print("=" * 60)
    print("KSTLIB.METRICS DEMO")
    print("=" * 60)

    demo_unified_decorator()
    demo_context_manager()
    demo_step_tracking()
    demo_call_stats()
    demo_stopwatch()
    demo_file_loading()

    print("\n" + "=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
