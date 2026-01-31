# Monitoring Exceptions

The monitoring module raises specialized exceptions for render failures, collector errors,
configuration issues, and delivery problems.

## Exception Hierarchy

```
KstlibError
└── MonitoringError (base)
    ├── CollectorError
    ├── RenderError
    ├── MonitoringConfigError
    │   ├── MonitoringConfigFileNotFoundError
    │   ├── MonitoringConfigFormatError
    │   └── MonitoringConfigCollectorError
    └── DeliveryError
        ├── DeliveryConfigError
        └── DeliveryIOError
```

## Common Failure Modes

- **CollectorError**: A collector function raised an exception during data collection
- **RenderError**: Template rendering failed (invalid Jinja2 syntax, missing variables)
- **MonitoringConfigError**: Configuration file is missing, malformed, or invalid
- **DeliveryError**: Failed to save file or send email

## Usage Patterns

### Basic Error Handling

```python
from kstlib.monitoring import (
    Monitoring,
    MonitoringError,
    CollectorError,
    RenderError,
)

mon = Monitoring(template="{{ data | render }}")

@mon.collector
def data():
    return fetch_metrics()  # May raise

try:
    result = mon.run_sync()
except CollectorError as e:
    print(f"Collector '{e.collector_name}' failed: {e.cause}")
except RenderError as e:
    print(f"Template error: {e}")
except MonitoringError as e:
    print(f"Monitoring error: {e}")
```

### Handling Partial Failures

With `fail_fast=False`, collectors that fail are recorded but don't stop execution:

```python
mon = Monitoring(
    template="{{ a }} {{ b }}",
    fail_fast=False,  # Continue on errors
)

@mon.collector
def a():
    return "OK"

@mon.collector
def b():
    raise ValueError("Service unavailable")

result = mon.run_sync()
print(result.success)  # False (has errors)
print(result.errors)   # {"b": ValueError("Service unavailable")}
print(result.html)     # Partial render (a is present)
```

### Config Loading Errors

```python
from kstlib.monitoring import (
    load_monitoring_config,
    MonitoringConfigFileNotFoundError,
    MonitoringConfigFormatError,
    MonitoringConfigCollectorError,
)

try:
    config = load_monitoring_config("dashboard.monitor.yml")
    service = config.to_service()
except MonitoringConfigFileNotFoundError as e:
    print(f"Config not found: {e}")
except MonitoringConfigFormatError as e:
    print(f"Invalid YAML: {e}")
except MonitoringConfigCollectorError as e:
    print(f"Collector error: {e}")
```

### Delivery Errors

```python
from kstlib.monitoring import (
    Monitoring,
    FileDelivery,
    DeliveryError,
    DeliveryConfigError,
    DeliveryIOError,
)

mon = Monitoring(
    template="<p>{{ msg }}</p>",
    delivery=FileDelivery(output_dir="/nonexistent/path"),
)

@mon.collector
def msg():
    return "Hello"

try:
    mon.run_sync()
except DeliveryConfigError as e:
    print(f"Invalid config: {e}")
except DeliveryIOError as e:
    print(f"I/O error: {e}")
except DeliveryError as e:
    print(f"Delivery failed: {e}")
```

### Defensive Pattern with Logging

```python
import logging
from kstlib.monitoring import (
    Monitoring,
    MonitoringError,
    CollectorError,
    DeliveryError,
)

log = logging.getLogger(__name__)

def run_monitoring():
    mon = Monitoring.from_config()

    @mon.collector
    def metrics():
        return collect_metrics()

    try:
        result = mon.run_sync()
        if not result.success:
            for name, error in result.errors.items():
                log.warning("Collector %s failed: %s", name, error)
        return result
    except CollectorError as e:
        log.error("Critical collector failure: %s", e)
        raise
    except DeliveryError as e:
        log.error("Delivery failed: %s", e)
        # Don't raise - report was generated, just not delivered
        return None
    except MonitoringError as e:
        log.exception("Unexpected monitoring error")
        raise
```

## Exception Reference

### MonitoringError

Base exception for all monitoring errors.

```{eval-rst}
.. autoclass:: kstlib.monitoring.exceptions.MonitoringError
    :noindex:
    :show-inheritance:
```

### CollectorError

Raised when a collector callable fails during execution.

**Attributes:**
- `collector_name`: Name of the failed collector
- `cause`: The underlying exception

```{eval-rst}
.. autoclass:: kstlib.monitoring.exceptions.CollectorError
    :noindex:
    :members:
    :show-inheritance:
```

### RenderError

Raised when HTML rendering fails (template errors, data issues).

```{eval-rst}
.. autoclass:: kstlib.monitoring.exceptions.RenderError
    :noindex:
    :show-inheritance:
```

### MonitoringConfigError

Base exception for configuration errors.

```{eval-rst}
.. autoclass:: kstlib.monitoring.exceptions.MonitoringConfigError
    :noindex:
    :show-inheritance:
```

### MonitoringConfigFileNotFoundError

Config file does not exist.

```{eval-rst}
.. autoclass:: kstlib.monitoring.config.MonitoringConfigFileNotFoundError
    :noindex:
    :show-inheritance:
```

### MonitoringConfigFormatError

Config file has invalid YAML or missing required fields.

```{eval-rst}
.. autoclass:: kstlib.monitoring.config.MonitoringConfigFormatError
    :noindex:
    :show-inheritance:
```

### MonitoringConfigCollectorError

Error loading a collector from config (bad module path, missing function).

```{eval-rst}
.. autoclass:: kstlib.monitoring.config.MonitoringConfigCollectorError
    :noindex:
    :show-inheritance:
```

### DeliveryError

Base exception for delivery failures.

```{eval-rst}
.. autoclass:: kstlib.monitoring.delivery.DeliveryError
    :noindex:
    :show-inheritance:
```

### DeliveryConfigError

Invalid delivery configuration (bad path, too many recipients).

```{eval-rst}
.. autoclass:: kstlib.monitoring.delivery.DeliveryConfigError
    :noindex:
    :show-inheritance:
```

### DeliveryIOError

I/O error during file delivery (permission denied, disk full).

```{eval-rst}
.. autoclass:: kstlib.monitoring.delivery.DeliveryIOError
    :noindex:
    :show-inheritance:
```
