# Metrics Utilities

Public API for performance measurement: timing, memory tracking, call statistics, and step tracking. These
utilities help profile code execution and identify bottlenecks.

```{tip}
Pair this reference with {doc}`../features/metrics/index` for the feature guide.
```

## Quick overview

- `@metrics` decorator provides unified time + memory tracking with Rich output
- `@call_stats` tracks call count, avg/min/max duration across multiple invocations
- `metrics_context` context manager measures code blocks inline
- `Stopwatch` provides manual lap timing with summary display
- Step tracking with `step=True` assigns incrementing numbers for pipeline visualization
- Configuration follows the standard priority chain: decorator args > `kstlib.conf.yml` > defaults

## Configuration cascade

The module consults the loaded config for default values. A minimal config block:

```yaml
metrics:
  colors: true
  defaults:
    time: true
    memory: true
    step: false
  thresholds:
    time_warn: 5
    time_crit: 30
```

Override any of these per call:

```python
from kstlib.metrics import metrics

@metrics(memory=False, step=True)
def my_step():
    pass
```

## Usage patterns

### Basic decorator usage

```python
from kstlib.metrics import metrics

@metrics
def process_data(items: list) -> int:
    return sum(items)

result = process_data([1, 2, 3])
# Output: [process_data (script.py:3)] | 0.001s | Peak: 64 KB
```

### Step tracking for pipelines

```python
from kstlib.metrics import metrics, metrics_summary, clear_metrics

clear_metrics()

@metrics(step=True)
def load():
    pass

@metrics(step=True, title="Transform")
def transform():
    pass

load()
transform()
metrics_summary()
```

### Call statistics

```python
from kstlib.metrics import call_stats, print_all_call_stats

@call_stats
def api_call():
    return fetch()

for _ in range(10):
    api_call()

print_all_call_stats()
```

### Context manager

```python
from kstlib.metrics import metrics_context

with metrics_context("Data loading") as m:
    data = load_data()

print(f"Took {m.elapsed_seconds:.3f}s, peak {m.peak_memory_formatted}")
```

### Manual stopwatch

```python
from kstlib.metrics import Stopwatch

sw = Stopwatch("Pipeline")
sw.start()
# ... work ...
sw.lap("Step 1")
# ... work ...
sw.lap("Step 2")
sw.stop()
sw.summary()
```

## Module reference

```{eval-rst}
.. automodule:: kstlib.metrics
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```

## Exceptions

```{eval-rst}
.. automodule:: kstlib.metrics.exceptions
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```
