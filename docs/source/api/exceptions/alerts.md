# Alerts Exceptions

Exception hierarchy for the alerts subsystem.

## Exception Hierarchy

```
KstlibError
└── AlertError
    ├── AlertConfigurationError
    ├── AlertDeliveryError
    └── AlertThrottledError
```

## Base Exception

```{eval-rst}
.. autoexception:: kstlib.alerts.exceptions.AlertError
   :members:
   :show-inheritance:
```

## Configuration Errors

```{eval-rst}
.. autoexception:: kstlib.alerts.exceptions.AlertConfigurationError
   :members:
   :show-inheritance:
```

Raised when alert configuration is invalid:
- Invalid webhook URL format
- Missing required parameters
- Invalid channel configuration

## Delivery Errors

```{eval-rst}
.. autoexception:: kstlib.alerts.exceptions.AlertDeliveryError
   :members:
   :show-inheritance:
```

Raised when alert delivery fails:
- Network errors
- HTTP errors (4xx, 5xx)
- Timeout errors

The `retryable` attribute indicates if the operation can be retried.

## Throttle Errors

```{eval-rst}
.. autoexception:: kstlib.alerts.exceptions.AlertThrottledError
   :members:
   :show-inheritance:
```

Raised when alert is rate-limited:
- Rate limit exceeded
- Timeout waiting for token

The `retry_after` attribute indicates seconds until next attempt.

## Usage Examples

```python
from kstlib.alerts.exceptions import (
    AlertError,
    AlertConfigurationError,
    AlertDeliveryError,
    AlertThrottledError,
)

try:
    await channel.send(alert)
except AlertThrottledError as e:
    log.warning(f"Throttled, retry after {e.retry_after}s")
except AlertDeliveryError as e:
    if e.retryable:
        await retry_later(alert)
    else:
        log.error(f"Permanent failure: {e}")
except AlertConfigurationError as e:
    log.error(f"Config error: {e}")
except AlertError as e:
    log.error(f"Alert error: {e}")
```
