# Alerts Subsystem

Multi-channel alerting with throttling, level filtering, and config-driven defaults.

```{tip}
Pair this reference with {doc}`../features/alerts/index` for the feature guide.
```

## Quick Overview

- `AlertManager` orchestrates delivery to multiple channels with per-channel level filtering
- `AlertThrottle` provides rate limiting via token bucket algorithm
- `AlertMessage` and `AlertLevel` define alert content and severity
- `SlackChannel` and `EmailChannel` are the built-in delivery backends
- All settings support config-driven defaults with hard limit enforcement

## Core Components

### AlertManager

```{eval-rst}
.. autoclass:: kstlib.alerts.AlertManager
   :members:
   :undoc-members:
   :show-inheritance:
```

### AlertThrottle

```{eval-rst}
.. autoclass:: kstlib.alerts.throttle.AlertThrottle
   :members:
   :undoc-members:
   :show-inheritance:
```

## Models

```{eval-rst}
.. autoclass:: kstlib.alerts.models.AlertMessage
   :show-inheritance:
   :noindex:

.. autoclass:: kstlib.alerts.models.AlertLevel
   :show-inheritance:
   :noindex:

.. autoclass:: kstlib.alerts.models.AlertResult
   :show-inheritance:
   :noindex:
```

## Channels

### SlackChannel

```{eval-rst}
.. autoclass:: kstlib.alerts.channels.SlackChannel
   :members:
   :undoc-members:
   :show-inheritance:
```

### EmailChannel

```{eval-rst}
.. autoclass:: kstlib.alerts.channels.EmailChannel
   :members:
   :undoc-members:
   :show-inheritance:
```

### Base Classes

```{eval-rst}
.. autoclass:: kstlib.alerts.channels.base.AlertChannel
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: kstlib.alerts.channels.base.AsyncAlertChannel
   :members:
   :undoc-members:
   :show-inheritance:
```

## Configuration Limits

```{eval-rst}
.. autoclass:: kstlib.limits.AlertsLimits
   :show-inheritance:
   :noindex:

.. autofunction:: kstlib.limits.get_alerts_limits
   :noindex:
```

