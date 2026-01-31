# Metrics Exceptions

The metrics module handles application telemetry and performance tracking.
The exception hierarchy is intentionally minimal, with a single base class for all metrics-related errors.

## Exception hierarchy

```
MetricsError (base)
```

## Common failure modes

- `MetricsError` is raised when metrics collection, aggregation, or export encounters an unrecoverable state.
- Typical causes: invalid metric names, backend connectivity issues, or malformed metric data.

## Usage patterns

### Guarding metrics operations

```python
from kstlib.metrics.exceptions import MetricsError

try:
    metrics.record("order_latency", latency_ms)
except MetricsError as error:
    LOGGER.warning("Metrics recording failed: %s", error)
    # Continue execution - metrics should not block business logic
```

### Defensive metrics wrapper

```python
from kstlib.metrics.exceptions import MetricsError

def safe_record(name: str, value: float) -> None:
    """Record a metric without raising on failure."""
    try:
        metrics.record(name, value)
    except MetricsError:
        pass  # Metrics failure should not crash the app
```

## Module reference

```{eval-rst}
.. automodule:: kstlib.metrics.exceptions
    :members:
    :undoc-members:
    :show-inheritance:
```
