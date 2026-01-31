# UI Exceptions

Exceptions for the UI module: panels, tables, and spinners.

## Exception hierarchy

```
RuntimeError
├── PanelRenderingError    # Panel preset or payload invalid
├── TableRenderingError    # Table construction failed
└── SpinnerError           # Spinner encountered an error
```

## Common failure modes

- `PanelRenderingError` is raised when the `PanelManager` cannot resolve a preset or when override values are invalid.
- `TableRenderingError` surfaces when table construction fails (invalid column config, incompatible data).
- `SpinnerError` may be raised if the spinner encounters terminal issues or invalid configuration.

## Usage patterns

### Safe panel rendering

```python
from kstlib.ui import PanelManager
from kstlib.ui.exceptions import PanelRenderingError

pm = PanelManager()

try:
    panel = pm.render("info", content="Status OK", title="Health")
except PanelRenderingError as e:
    # Fallback to plain text
    print(f"[INFO] Status OK")
```

### Handling table errors

```python
from kstlib.ui.tables import TableBuilder
from kstlib.ui.exceptions import TableRenderingError

try:
    table = TableBuilder(columns=["Name", "Value"]).add_rows(data).build()
except TableRenderingError as e:
    logger.warning(f"Table render failed: {e}")
```

## API reference

```{eval-rst}
.. automodule:: kstlib.ui.exceptions
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```
