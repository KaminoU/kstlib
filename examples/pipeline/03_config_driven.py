"""Config-driven pipeline example.

Demonstrates loading a pipeline from kstlib.conf.yml using
PipelineRunner.from_config().

Usage:
    cd examples/pipeline
    python 03_config_driven.py
"""

from __future__ import annotations

from kstlib.config import load_config
from kstlib.pipeline import PipelineAbortedError, PipelineRunner


def main() -> None:
    """Run a config-driven pipeline."""
    # Load config from current directory
    load_config()

    # Load and run the pipeline defined in kstlib.conf.yml
    runner = PipelineRunner.from_config("example-pipeline")

    print(f"Pipeline: {runner.config.name}")
    print(f"Steps: {len(runner.config.steps)}")
    print(f"Error policy: {runner.config.on_error.value}")
    print(f"Default timeout: {runner.config.default_timeout}s")
    print()

    try:
        result = runner.run()
        print(f"\nCompleted in {result.duration:.3f}s")
        print(f"Success: {result.success}")
        for step in result.results:
            print(f"  [{step.status.value:>7}] {step.name}")
            if step.stdout and step.stdout.strip():
                for line in step.stdout.strip().splitlines():
                    print(f"            {line}")
            if step.return_value is not None:
                print(f"            -> {step.return_value}")
    except PipelineAbortedError as e:
        print(f"\nAborted at step '{e.step_name}': {e.reason}")


if __name__ == "__main__":
    main()
