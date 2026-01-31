"""Demonstrate spinner with logs scrolling above it."""

from __future__ import annotations

import random
import time

from kstlib.ui.spinner import Spinner


def demo_logs_above_spinner() -> None:
    """Show logs scrolling while spinner runs at the bottom."""
    print("\n=== Logs Scrolling Above Spinner ===\n")

    with Spinner("Processing batch...", style="DOTS") as spinner:
        for i in range(1, 11):
            # Simulate work
            time.sleep(0.3)

            # Log progress above the spinner
            spinner.log(f"[{i}/10] Processed item batch_{i:03d}", style="dim")

            # Update spinner message
            spinner.update(f"Processing batch... ({i}/10)")

    print()  # Newline after completion


def demo_simulated_build() -> None:
    """Simulate a build process with various log levels."""
    print("\n=== Simulated Build Process ===\n")

    steps = [
        ("Checking dependencies...", "dim"),
        ("Installing packages...", "cyan"),
        ("Compiling source...", "cyan"),
        ("Running linters...", "yellow"),
        ("Executing tests...", "cyan"),
        ("Building artifacts...", "cyan"),
        ("Optimizing output...", "dim"),
        ("Generating docs...", "dim"),
    ]

    with Spinner("Starting build...", style="BRAILLE") as spinner:
        for step_name, style in steps:
            spinner.update(step_name)
            # Simulate step duration
            duration = random.uniform(0.5, 1.5)
            time.sleep(duration)
            spinner.log(f"  {step_name} done ({duration:.1f}s)", style=style)

    print()


def demo_api_calls() -> None:
    """Simulate API calls with responses logging."""
    print("\n=== Simulated API Calls ===\n")

    endpoints = [
        ("/api/users", 200, 0.2),
        ("/api/products", 200, 0.4),
        ("/api/orders", 200, 0.3),
        ("/api/inventory", 404, 0.1),
        ("/api/reports", 200, 0.8),
        ("/api/metrics", 200, 0.2),
        ("/api/health", 200, 0.05),
    ]

    with Spinner("Fetching data...", style="ARROW") as spinner:
        for endpoint, status, delay in endpoints:
            spinner.update(f"GET {endpoint}")
            time.sleep(delay)

            if status == 200:
                spinner.log(f"  GET {endpoint} -> {status} OK", style="green")
            else:
                spinner.log(f"  GET {endpoint} -> {status} Not Found", style="red")

    print()


def demo_file_processing() -> None:
    """Simulate processing files with verbose output."""
    print("\n=== File Processing with Verbose Output ===\n")

    files = [
        "config.yml",
        "main.py",
        "utils/helpers.py",
        "utils/validators.py",
        "tests/test_main.py",
        "tests/test_utils.py",
        "docs/readme.md",
        "docs/api.md",
    ]

    with Spinner("Analyzing codebase...", style="BLOCKS") as spinner:
        for _i, filename in enumerate(files, 1):
            spinner.update(f"Analyzing {filename}...")
            time.sleep(random.uniform(0.2, 0.5))

            lines = random.randint(50, 500)
            spinner.log(f"  {filename}: {lines} lines", style="dim")

    print()


def demo_decorator_style() -> None:
    """Show how to use spinner in a decorator pattern."""
    print("\n=== Decorator-Style Usage ===\n")

    def process_with_spinner(items: list[str]) -> list[str]:
        """Process items with spinner feedback."""
        results = []
        with Spinner("Processing...") as spinner:
            for i, item in enumerate(items, 1):
                time.sleep(0.2)
                result = item.upper()
                results.append(result)
                spinner.log(f"  {item} -> {result}", style="cyan")
                spinner.update(f"Processing... ({i}/{len(items)})")
        return results

    items = ["alpha", "beta", "gamma", "delta", "epsilon"]
    results = process_with_spinner(items)
    print(f"\nResults: {results}")


def main() -> None:
    """Run all log-with-spinner demonstrations."""
    print("=" * 60)
    print("Spinner with Logs Examples")
    print("=" * 60)

    demo_logs_above_spinner()
    demo_simulated_build()
    demo_api_calls()
    demo_file_processing()
    demo_decorator_style()

    print("\n" + "=" * 60)
    print("Done!")


if __name__ == "__main__":
    main()
