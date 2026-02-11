"""Multi-step pipeline with conditions.

Demonstrates conditional steps (on_success, on_failure) and
callable steps alongside shell steps.

Usage:
    python examples/pipeline/02_multi_step.py
"""

from __future__ import annotations

import sys

from kstlib.pipeline import (
    ErrorPolicy,
    PipelineConfig,
    PipelineRunner,
    StepCondition,
    StepConfig,
    StepType,
)


def main() -> None:
    """Run a multi-step pipeline with conditions."""
    # Build a pipeline that demonstrates:
    # 1. A step that succeeds
    # 2. A step that fails (simulated)
    # 3. An on_success step (skipped because step 2 failed)
    # 4. An on_failure step (runs because step 2 failed)
    # 5. An always step (runs regardless)

    config = PipelineConfig(
        name="multi-step-demo",
        steps=(
            StepConfig(
                name="setup",
                type=StepType.SHELL,
                command="echo Setting up environment...",
            ),
            StepConfig(
                name="check-health",
                type=StepType.SHELL,
                command=f'{sys.executable} -c "import sys; sys.exit(1)"',
            ),
            StepConfig(
                name="deploy",
                type=StepType.SHELL,
                command="echo Deploying... (should be skipped)",
                when=StepCondition.ON_SUCCESS,
            ),
            StepConfig(
                name="alert-failure",
                type=StepType.CALLABLE,
                callable="platform:system",
                when=StepCondition.ON_FAILURE,
            ),
            StepConfig(
                name="log-result",
                type=StepType.SHELL,
                command="echo Pipeline completed (always runs)",
                when=StepCondition.ALWAYS,
            ),
        ),
        on_error=ErrorPolicy.CONTINUE,
    )

    runner = PipelineRunner(config)
    result = runner.run()

    print(f"\nPipeline '{result.name}' completed in {result.duration:.3f}s")
    print(f"Success: {result.success}")
    print(f"Failed steps: {len(result.failed_steps)}")
    print(f"Skipped steps: {len(result.skipped_steps)}")
    print()
    for step in result.results:
        status = step.status.value.upper()
        print(f"  [{status:>7}] {step.name} ({step.duration:.3f}s)")
        if step.stdout and step.stdout.strip():
            for line in step.stdout.strip().splitlines():
                print(f"            {line}")
        if step.return_value is not None:
            print(f"            -> {step.return_value}")
        if step.error:
            print(f"            ! {step.error}")


if __name__ == "__main__":
    main()
