# Monitoring API

Complete API reference for the monitoring module.

```{tip}
Pair this reference with {doc}`../features/monitoring/index` for the feature guide.
```

## Quick Overview

- **Monitoring**: Simplified API with `@collector` decorators
- **MonitoringService**: Lower-level orchestrator for collect/render pipeline
- **Render Types**: StatusCell, MonitorTable, MonitorKV, MonitorList, MonitorMetric, MonitorImage
- **Delivery**: FileDelivery (local files), MailDelivery (email via kstlib.mail)
- **Config**: Load from `kstlib.conf.yml` or `*.monitor.yml` files

## Simplified API

### Monitoring

```{eval-rst}
.. autoclass:: kstlib.monitoring.monitoring.Monitoring
    :members:
    :show-inheritance:
```

## Orchestration

### MonitoringService

```{eval-rst}
.. autoclass:: kstlib.monitoring.service.MonitoringService
    :members:
    :show-inheritance:
```

### MonitoringResult

```{eval-rst}
.. autoclass:: kstlib.monitoring.service.MonitoringResult
    :members:
    :show-inheritance:
    :noindex:
```

## Render Types

### Base Protocol

```{eval-rst}
.. autoclass:: kstlib.monitoring.types.Renderable
    :members:
    :show-inheritance:
```

### StatusLevel

```{eval-rst}
.. autoclass:: kstlib.monitoring.types.StatusLevel
    :members:
    :show-inheritance:
    :noindex:
```

### StatusCell

```{eval-rst}
.. autoclass:: kstlib.monitoring.cell.StatusCell
    :members:
    :show-inheritance:
    :noindex:
```

### MonitorTable

```{eval-rst}
.. autoclass:: kstlib.monitoring.table.MonitorTable
    :members:
    :show-inheritance:
    :noindex:
```

### MonitorKV

```{eval-rst}
.. autoclass:: kstlib.monitoring.kv.MonitorKV
    :members:
    :show-inheritance:
    :noindex:
```

### MonitorList

```{eval-rst}
.. autoclass:: kstlib.monitoring.list.MonitorList
    :members:
    :show-inheritance:
    :noindex:
```

### MonitorMetric

```{eval-rst}
.. autoclass:: kstlib.monitoring.metric.MonitorMetric
    :members:
    :show-inheritance:
    :noindex:
```

### MonitorImage

```{eval-rst}
.. autoclass:: kstlib.monitoring.image.MonitorImage
    :members:
    :show-inheritance:
    :noindex:
```

## Jinja2 Renderer

### render_template

```{eval-rst}
.. autofunction:: kstlib.monitoring.renderer.render_template
```

### render_html

```{eval-rst}
.. autofunction:: kstlib.monitoring.renderer.render_html
```

### create_environment

```{eval-rst}
.. autofunction:: kstlib.monitoring.renderer.create_environment
```

### get_css_classes

```{eval-rst}
.. autofunction:: kstlib.monitoring._styles.get_css_classes
```

## Configuration

### MonitoringConfig

```{eval-rst}
.. autoclass:: kstlib.monitoring.config.MonitoringConfig
    :members:
    :show-inheritance:
    :noindex:
```

### CollectorConfig

```{eval-rst}
.. autoclass:: kstlib.monitoring.config.CollectorConfig
    :members:
    :show-inheritance:
    :noindex:
```

### load_monitoring_config

```{eval-rst}
.. autofunction:: kstlib.monitoring.config.load_monitoring_config
```

### discover_monitoring_configs

```{eval-rst}
.. autofunction:: kstlib.monitoring.config.discover_monitoring_configs
```

### create_services_from_directory

```{eval-rst}
.. autofunction:: kstlib.monitoring.config.create_services_from_directory
```

## Delivery Backends

### DeliveryBackend

```{eval-rst}
.. autoclass:: kstlib.monitoring.delivery.DeliveryBackend
    :members:
    :show-inheritance:
```

### DeliveryResult

```{eval-rst}
.. autoclass:: kstlib.monitoring.delivery.DeliveryResult
    :members:
    :show-inheritance:
    :noindex:
```

### FileDelivery

```{eval-rst}
.. autoclass:: kstlib.monitoring.delivery.FileDelivery
    :members:
    :show-inheritance:
```

### FileDeliveryConfig

```{eval-rst}
.. autoclass:: kstlib.monitoring.delivery.FileDeliveryConfig
    :members:
    :show-inheritance:
    :noindex:
```

### MailDelivery

```{eval-rst}
.. autoclass:: kstlib.monitoring.delivery.MailDelivery
    :members:
    :show-inheritance:
```

### MailDeliveryConfig

```{eval-rst}
.. autoclass:: kstlib.monitoring.delivery.MailDeliveryConfig
    :members:
    :show-inheritance:
    :noindex:
```

## Exceptions

See {doc}`exceptions/monitoring` for detailed exception handling patterns.

```{eval-rst}
.. automodule:: kstlib.monitoring.exceptions
    :members:
    :show-inheritance:
    :noindex:
```

### Config Exceptions

```{eval-rst}
.. autoclass:: kstlib.monitoring.config.MonitoringConfigFileNotFoundError
    :noindex:
    :show-inheritance:

.. autoclass:: kstlib.monitoring.config.MonitoringConfigFormatError
    :noindex:
    :show-inheritance:

.. autoclass:: kstlib.monitoring.config.MonitoringConfigCollectorError
    :noindex:
    :show-inheritance:
```

### Delivery Exceptions

```{eval-rst}
.. autoclass:: kstlib.monitoring.delivery.DeliveryError
    :noindex:
    :show-inheritance:

.. autoclass:: kstlib.monitoring.delivery.DeliveryConfigError
    :noindex:
    :show-inheritance:

.. autoclass:: kstlib.monitoring.delivery.DeliveryIOError
    :noindex:
    :show-inheritance:
```

## Module Exports

The following are available directly from `kstlib.monitoring`:

```python
from kstlib.monitoring import (
    # Simplified API
    Monitoring,

    # Orchestration
    MonitoringService,
    MonitoringResult,

    # Render types
    StatusCell,
    MonitorTable,
    MonitorKV,
    MonitorList,
    MonitorMetric,
    MonitorImage,

    # Enums & Protocol
    StatusLevel,
    Renderable,
    CellValue,

    # Renderer
    render_template,
    render_html,
    create_environment,
    get_css_classes,

    # Config
    MonitoringConfig,
    CollectorConfig,
    load_monitoring_config,
    discover_monitoring_configs,
    create_services_from_directory,

    # Delivery
    DeliveryBackend,
    DeliveryResult,
    FileDelivery,
    FileDeliveryConfig,
    MailDelivery,
    MailDeliveryConfig,

    # Exceptions
    MonitoringError,
    CollectorError,
    RenderError,
    MonitoringConfigError,
    MonitoringConfigFileNotFoundError,
    MonitoringConfigFormatError,
    MonitoringConfigCollectorError,
    DeliveryError,
    DeliveryConfigError,
    DeliveryIOError,
)
```
