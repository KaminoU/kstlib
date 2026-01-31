# Spinner

Animated CLI spinners for visual feedback during long-running operations. The `Spinner` class provides
configurable animations with Rich styling, context manager support, and decorator patterns.

```{tip}
Use spinners to indicate progress when exact completion time is unknown. For determinate progress,
consider Rich's built-in progress bars instead.
```

## Quick overview

- Multiple animation styles: `BRAILLE`, `DOTS`, `LINE`, `ARROW`, `BLOCKS`, `CIRCLE`, `MOON`, `CLOCK`
- Configurable via presets (`minimal`, `fancy`, `blocks`, `bounce`, `color_wave`)
- Context manager and decorator support
- Thread-safe animation loop
- Success/failure indicators on completion

## Usage patterns

### Basic context manager

```python
from kstlib.ui import Spinner

with Spinner("Loading data...") as spinner:
    # Long operation here
    data = fetch_data()
    spinner.update("Processing...")
    process(data)
# Spinner shows success checkmark on exit
```

### As a decorator

```python
from kstlib.ui import Spinner

@Spinner.wrap("Fetching results")
def fetch_results():
    # Long operation
    return api.get_results()

results = fetch_results()  # Spinner runs during execution
```

### With presets

```python
from kstlib.ui import Spinner

# Use a preset style
with Spinner("Working...", preset="fancy"):
    do_work()

# Or specify style directly
with Spinner("Computing...", style="MOON", interval=0.1):
    compute()
```

### Manual control

```python
from kstlib.ui import Spinner

spinner = Spinner("Starting...")
spinner.start()
try:
    for item in items:
        spinner.update(f"Processing {item}...")
        process(item)
    spinner.succeed("All done!")
except Exception as e:
    spinner.fail(f"Error: {e}")
finally:
    spinner.stop()
```

## Module reference

```{eval-rst}
.. automodule:: kstlib.ui.spinner
    :members:
    :undoc-members:
    :show-inheritance:
```
