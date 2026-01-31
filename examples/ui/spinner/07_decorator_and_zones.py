"""Demonstrate the @with_spinner decorator and SpinnerWithLogZone."""

from __future__ import annotations

import random
import time

from kstlib.ui.spinner import SpinnerWithLogZone, with_spinner

# ==============================================================================
# @with_spinner decorator - captures prints from existing functions
# ==============================================================================


def demo_decorator_basic() -> None:
    """Basic decorator usage with a function that prints."""
    print("\n=== @with_spinner Decorator (Basic) ===\n")

    @with_spinner("Processing data...", log_style="cyan")
    def process_data() -> list[int]:
        """A function that prints during execution."""
        results = []
        for i in range(5):
            print(f"Processing item {i + 1}...")
            time.sleep(0.3)
            results.append(i * 2)
        print("All items processed!")
        return results

    result = process_data()
    print(f"Result: {result}\n")


def demo_decorator_existing_function() -> None:
    """Decorate an existing verbose function."""
    print("\n=== @with_spinner with Existing Verbose Function ===\n")

    # Imagine this is a function from another library that prints a lot
    def verbose_build_process(steps: list[str]) -> bool:
        """Simulates a verbose build process."""
        for step in steps:
            print(f"[BUILD] Starting: {step}")
            time.sleep(random.uniform(0.2, 0.5))
            print(f"[BUILD] Completed: {step}")
        print("[BUILD] All steps finished successfully!")
        return True

    # Wrap it with the decorator
    wrapped_build = with_spinner(
        "Building project...",
        style="BLOCKS",
        log_style="dim",
    )(verbose_build_process)

    steps = ["compile", "link", "test", "package"]
    success = wrapped_build(steps)
    print(f"Build success: {success}\n")


def demo_decorator_no_capture() -> None:
    """Decorator without print capture (just spinner)."""
    print("\n=== @with_spinner without Print Capture ===\n")

    @with_spinner("Working silently...", capture_prints=False, style="DOTS")
    def silent_work() -> str:
        """Function that doesn't print but takes time."""
        time.sleep(2)
        return "done"

    result = silent_work()
    print(f"Result: {result}\n")


# ==============================================================================
# SpinnerWithLogZone - fixed spinner + scrolling log area
# ==============================================================================


def demo_log_zone_basic() -> None:
    """Basic log zone with spinner at top."""
    print("\n=== SpinnerWithLogZone (Basic) ===\n")

    with SpinnerWithLogZone("Processing batch...", log_zone_height=5) as sz:
        for i in range(12):  # More items than zone height
            time.sleep(0.3)
            sz.log(f"Processed item {i + 1:02d}", style="green")
            sz.update(f"Processing batch... ({i + 1}/12)")

    print()


def demo_log_zone_build_simulation() -> None:
    """Simulate a build with fixed spinner and scrolling logs."""
    print("\n=== SpinnerWithLogZone (Build Simulation) ===\n")

    build_steps = [
        ("Fetching dependencies", "cyan"),
        ("Compiling source files", "cyan"),
        ("Running unit tests", "yellow"),
        ("Running integration tests", "yellow"),
        ("Generating documentation", "dim"),
        ("Creating artifacts", "cyan"),
        ("Signing binaries", "magenta"),
        ("Uploading to registry", "cyan"),
        ("Cleaning up temp files", "dim"),
        ("Verifying checksums", "green"),
    ]

    with SpinnerWithLogZone(
        "Building...",
        log_zone_height=6,
        style="BRAILLE",
    ) as sz:
        for step_name, color in build_steps:
            sz.update(f"Building: {step_name}")
            duration = random.uniform(0.3, 0.8)
            time.sleep(duration)
            sz.log(f"{step_name} ({duration:.1f}s)", style=color)

    print()


def demo_log_zone_api_monitor() -> None:
    """Monitor API calls with log zone."""
    print("\n=== SpinnerWithLogZone (API Monitor) ===\n")

    endpoints = [
        ("/api/health", 200),
        ("/api/users", 200),
        ("/api/products", 200),
        ("/api/orders", 201),
        ("/api/payments", 500),
        ("/api/inventory", 200),
        ("/api/reports", 404),
        ("/api/metrics", 200),
        ("/api/logs", 200),
        ("/api/config", 200),
    ]

    with SpinnerWithLogZone(
        "Monitoring API...",
        log_zone_height=5,
        style="ARROW",
    ) as sz:
        for endpoint, status in endpoints:
            time.sleep(random.uniform(0.2, 0.4))

            if status == 200:
                sz.log(f"GET {endpoint} -> {status} OK", style="green")
            elif status == 201:
                sz.log(f"POST {endpoint} -> {status} Created", style="cyan")
            elif status == 404:
                sz.log(f"GET {endpoint} -> {status} Not Found", style="yellow")
            else:
                sz.log(f"GET {endpoint} -> {status} ERROR", style="red")

            sz.update(f"Monitoring API... ({endpoint})")

    print()


def demo_decorator_with_log_zone() -> None:
    """Use @with_spinner decorator with log_zone_height for bounded logs."""
    print("\n=== @with_spinner with log_zone_height ===\n")

    # When log_zone_height is set, the decorator automatically uses
    # SpinnerWithLogZone instead of regular Spinner
    @with_spinner("Building project...", log_zone_height=5, log_style="cyan")
    def build_project() -> bool:
        """Simulates a build process with verbose output."""
        steps = ["fetch", "compile", "link", "test", "package", "sign", "deploy"]
        for step in steps:
            print(f"[BUILD] {step}...")
            time.sleep(random.uniform(0.3, 0.6))
        print("[BUILD] Complete!")
        return True

    success = build_project()
    print(f"Build success: {success}\n")


def demo_log_zone_manual() -> None:
    """Manual SpinnerWithLogZone usage for fine-grained control."""
    print("\n=== SpinnerWithLogZone (Manual Control) ===\n")

    files = [
        "main.py",
        "config.py",
        "utils/helpers.py",
        "utils/validators.py",
        "tests/test_main.py",
        "tests/test_config.py",
        "tests/test_utils.py",
        "docs/index.md",
    ]

    with SpinnerWithLogZone(
        "Analyzing codebase...",
        log_zone_height=4,
        style="DOTS",
    ) as sz:
        total_lines = 0
        for f in files:
            time.sleep(0.2)
            lines = random.randint(50, 500)
            sz.log(f"{f}: {lines} lines", style="dim")
            sz.update(f"Analyzing {f}...")
            total_lines += lines

    print(f"Total lines analyzed: {total_lines}\n")


def main() -> None:
    """Run all decorator and log zone demonstrations."""
    print("=" * 60)
    print("Decorator and Log Zone Examples")
    print("=" * 60)

    # Decorator examples
    demo_decorator_basic()
    demo_decorator_existing_function()
    demo_decorator_no_capture()
    demo_decorator_with_log_zone()  # New: decorator + log_zone_height

    # Log zone examples (manual control)
    demo_log_zone_basic()
    demo_log_zone_build_simulation()
    demo_log_zone_api_monitor()
    demo_log_zone_manual()

    print("\n" + "=" * 60)
    print("Done!")


if __name__ == "__main__":
    main()
