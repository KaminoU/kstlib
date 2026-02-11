# Pipeline

Declarative, config-driven pipeline execution for sequential workflows.

`kstlib.pipeline` provides a `PipelineRunner` that executes a sequence of **shell commands**,
**Python modules**, and **callable functions** with support for conditional execution,
error policies, timeout cascade, and dry-run mode.

```{tip}
Pair this reference with {doc}`../features/pipeline/index` for the feature guide.
```

## Quick overview

- `PipelineRunner` is the main facade for pipeline execution
- `StepConfig` and `PipelineConfig` define the pipeline structure
- `StepResult` and `PipelineResult` capture execution results
- `ShellStep`, `PythonStep`, `CallableStep` are the step executors
- Configuration follows standard priority: constructor args > `kstlib.conf.yml` > defaults

## Configuration cascade

The module consults the loaded config for pipeline definitions:

```yaml
pipeline:
  default_timeout: 300
  on_error: fail_fast
  pipelines:
    morning-monitoring:
      steps:
        - name: check_services
          type: shell
          command: systemctl status nginx
          timeout: 30
        - name: send_report
          type: callable
          callable: my.alerts:send_summary
          when: always
```

Load a pipeline from config:

```python
from kstlib.pipeline import PipelineRunner

runner = PipelineRunner.from_config("morning-monitoring")
result = runner.run()
```

## Usage patterns

### Programmatic pipeline

```python
from kstlib.pipeline import (
    PipelineRunner, PipelineConfig, StepConfig, StepType, ErrorPolicy,
)

config = PipelineConfig(
    name="deploy",
    steps=(
        StepConfig(name="build", type=StepType.SHELL, command="make build"),
        StepConfig(name="test", type=StepType.PYTHON, module="pytest"),
        StepConfig(name="notify", type=StepType.CALLABLE, callable="my.alerts:send_ok"),
    ),
    on_error=ErrorPolicy.FAIL_FAST,
    default_timeout=300,
)
runner = PipelineRunner(config)
result = runner.run()
```

### Dry-run simulation

```python
result = runner.run(dry_run=True)
for step in result.results:
    print(f"{step.name}: {step.stdout}")
```

## Module reference

```{eval-rst}
.. automodule:: kstlib.pipeline
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```

## Runner

```{eval-rst}
.. automodule:: kstlib.pipeline.runner
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```

## Models

```{eval-rst}
.. automodule:: kstlib.pipeline.models
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```

## Steps

```{eval-rst}
.. automodule:: kstlib.pipeline.steps.shell
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```

```{eval-rst}
.. automodule:: kstlib.pipeline.steps.python
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```

```{eval-rst}
.. automodule:: kstlib.pipeline.steps.callable
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```

## Protocol

```{eval-rst}
.. automodule:: kstlib.pipeline.base
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```

## Validators

```{eval-rst}
.. automodule:: kstlib.pipeline.validators
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```

## Exceptions

```{eval-rst}
.. automodule:: kstlib.pipeline.exceptions
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```
