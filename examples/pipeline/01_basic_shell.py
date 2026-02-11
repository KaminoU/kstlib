"""Basic shell pipeline example.

Demonstrates a simple pipeline with shell commands.

Usage:
    python examples/pipeline/01_basic_shell.py
"""

from __future__ import annotations

from kstlib.pipeline import (
    PipelineConfig,
    PipelineRunner,
    StepConfig,
    StepType,
)


def main() -> None:
    """Run a basic shell pipeline."""
    config = PipelineConfig(
        name="basic-shell",
        steps=(
            StepConfig(
                name="greet",
                type=StepType.SHELL,
                command="echo Hello from pipeline!",
            ),
            StepConfig(
                name="date",
                type=StepType.SHELL,
                command='python -c "import datetime; print(datetime.datetime.now())"',
            ),
            StepConfig(
                name="platform",
                type=StepType.SHELL,
                command='python -c "import platform; print(platform.platform())"',
            ),
        ),
    )

    runner = PipelineRunner(config)
    result = runner.run()

    print(f"\nPipeline '{result.name}' completed in {result.duration:.3f}s")
    print(f"Success: {result.success}")
    print()
    for step in result.results:
        print(f"  [{step.status.value.upper():>7}] {step.name} ({step.duration:.3f}s)")
        if step.stdout.strip():
            for line in step.stdout.strip().splitlines():
                print(f"           {line}")


if __name__ == "__main__":
    main()
