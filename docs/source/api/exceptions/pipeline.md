# Pipeline Exceptions

Exception hierarchy for the pipeline (workflow execution) subsystem.

## Exception Hierarchy

```
KstlibError
└── PipelineError
    ├── PipelineConfigError (also ValueError)
    ├── PipelineAbortedError
    └── StepError
        ├── StepTimeoutError
        └── StepImportError
```

## Base Exception

```{eval-rst}
.. autoexception:: kstlib.pipeline.exceptions.PipelineError
   :members:
   :show-inheritance:
```

## Configuration Errors

```{eval-rst}
.. autoexception:: kstlib.pipeline.exceptions.PipelineConfigError
   :members:
   :show-inheritance:
```

Raised when pipeline or step configuration is invalid (missing fields,
constraint violations, unknown types).

## Execution Errors

```{eval-rst}
.. autoexception:: kstlib.pipeline.exceptions.PipelineAbortedError
   :members:
   :show-inheritance:
```

```{eval-rst}
.. autoexception:: kstlib.pipeline.exceptions.StepError
   :members:
   :show-inheritance:
```

```{eval-rst}
.. autoexception:: kstlib.pipeline.exceptions.StepTimeoutError
   :members:
   :show-inheritance:
```

```{eval-rst}
.. autoexception:: kstlib.pipeline.exceptions.StepImportError
   :members:
   :show-inheritance:
```

## Usage Examples

```python
from kstlib.pipeline.exceptions import (
    PipelineError,
    PipelineAbortedError,
    PipelineConfigError,
    StepError,
    StepTimeoutError,
    StepImportError,
)

try:
    result = runner.run()
except PipelineAbortedError as e:
    print(f"Pipeline aborted at step '{e.step_name}': {e.reason}")
except StepTimeoutError as e:
    print(f"Step '{e.step_name}' timed out after {e.timeout}s")
except StepImportError as e:
    print(f"Cannot import '{e.target}' for step '{e.step_name}'")
except PipelineConfigError as e:
    print(f"Invalid config: {e}")
except PipelineError as e:
    print(f"Pipeline error: {e}")
```
