"""HTML monitoring render types for dashboards and email reports.

This module provides five render types that produce HTML output suitable
for both browser dashboards (CSS classes) and email reports (inline CSS).

Render types:

- **StatusCell**: Colored ``<span>`` badge for UP/DOWN/DEGRADED indicators.
- **MonitorTable**: Striped ``<table>`` with typed headers and row validation.
- **MonitorKV**: Two-column ``<dl>`` grid for key-value stat panels.
- **MonitorList**: ``<ul>``/``<ol>`` for event logs and alert lists.
- **MonitorMetric**: Hero-number ``<div>`` for KPI display (P&L, uptime).
- **MonitorImage**: Base64 ``<img>`` for embedded logos and icons.

All render types implement ``render(*, inline_css: bool = False) -> str``:

- ``inline_css=False``: CSS class references (``.status-ok``, ``.monitor-table``).
- ``inline_css=True``: Inline ``style`` attributes for email compatibility.

Examples:
    Basic status badge:

    >>> from kstlib.monitoring import StatusCell, StatusLevel
    >>> cell = StatusCell("UP", StatusLevel.OK)
    >>> cell.render()
    '<span class="status-ok">UP</span>'

    Table with status cells:

    >>> from kstlib.monitoring import MonitorTable
    >>> t = MonitorTable(headers=["Service", "Status"])
    >>> t.add_row(["API", StatusCell("OK", StatusLevel.OK)])
    >>> "<table" in t.render()
    True
"""

from __future__ import annotations

from kstlib.monitoring._styles import get_css_classes
from kstlib.monitoring.cell import StatusCell
from kstlib.monitoring.config import (
    CollectorConfig,
    MonitoringConfig,
    MonitoringConfigCollectorError,
    MonitoringConfigFileNotFoundError,
    MonitoringConfigFormatError,
    create_services_from_directory,
    discover_monitoring_configs,
    load_monitoring_config,
)
from kstlib.monitoring.delivery import (
    DeliveryBackend,
    DeliveryConfigError,
    DeliveryError,
    DeliveryIOError,
    DeliveryResult,
    FileDelivery,
    FileDeliveryConfig,
    MailDelivery,
    MailDeliveryConfig,
)
from kstlib.monitoring.exceptions import (
    CollectorError,
    MonitoringConfigError,
    MonitoringError,
    RenderError,
)
from kstlib.monitoring.image import MonitorImage
from kstlib.monitoring.kv import MonitorKV
from kstlib.monitoring.list import MonitorList
from kstlib.monitoring.metric import MonitorMetric
from kstlib.monitoring.monitoring import Monitoring
from kstlib.monitoring.renderer import create_environment, render_html, render_template
from kstlib.monitoring.service import MonitoringResult, MonitoringService
from kstlib.monitoring.table import MonitorTable
from kstlib.monitoring.types import CellValue, Renderable, StatusLevel

__all__ = [
    "CellValue",
    "CollectorConfig",
    "CollectorError",
    "DeliveryBackend",
    "DeliveryConfigError",
    "DeliveryError",
    "DeliveryIOError",
    "DeliveryResult",
    "FileDelivery",
    "FileDeliveryConfig",
    "MailDelivery",
    "MailDeliveryConfig",
    "MonitorImage",
    "MonitorKV",
    "MonitorList",
    "MonitorMetric",
    "MonitorTable",
    "Monitoring",
    "MonitoringConfig",
    "MonitoringConfigCollectorError",
    "MonitoringConfigError",
    "MonitoringConfigFileNotFoundError",
    "MonitoringConfigFormatError",
    "MonitoringError",
    "MonitoringResult",
    "MonitoringService",
    "RenderError",
    "Renderable",
    "StatusCell",
    "StatusLevel",
    "create_environment",
    "create_services_from_directory",
    "discover_monitoring_configs",
    "get_css_classes",
    "load_monitoring_config",
    "render_html",
    "render_template",
]
