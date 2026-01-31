# Spinners

Animated CLI feedback for long-running operations. Multiple styles, animation types, and full customization support.

## Quick Start

```python
from kstlib.ui.spinner import Spinner

# Context manager (recommended)
with Spinner("Processing..."):
    do_long_operation()

# Manual control
spinner = Spinner("Loading...")
spinner.start()
try:
    do_work()
finally:
    spinner.stop()
```

## Spinner Styles

Nine built-in animation styles:

| Style | Characters | Best For |
|-------|------------|----------|
| `BRAILLE` | `⣾⣽⣻⢿⡿⣟⣯⣷` | Default, smooth |
| `DOTS` | `⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏` | Unicode terminals |
| `LINE` | `\|/-\\` | Classic, minimal |
| `ARROW` | `←↖↑↗→↘↓↙` | Directional |
| `BLOCKS` | `▁▂▃▄▅▆▇█` | Progress feel |
| `CIRCLE` | `◐◓◑◒` | Subtle |
| `SQUARE` | `◰◳◲◱` | Geometric |
| `MOON` | `🌑🌒🌓🌔🌕🌖🌗🌘` | Fun, visible |
| `CLOCK` | `🕐🕑🕒...🕛` | Time-based tasks |

```python
from kstlib.ui.spinner import Spinner, SpinnerStyle

with Spinner("Loading...", style=SpinnerStyle.MOON):
    time.sleep(2)

# Or use string name
with Spinner("Loading...", style="clock"):
    time.sleep(2)
```

## Animation Types

Three animation modes beyond classic spin:

### Spin (default)

Classic rotating character animation.

```python
with Spinner("Processing...", animation_type="spin"):
    time.sleep(2)
```

### Bounce

A marker bouncing inside brackets `[=    ]`.

```python
with Spinner("Syncing...", animation_type="bounce", spinner_style="yellow"):
    time.sleep(3)
```

### Color Wave

Rainbow colors flowing through the text itself.

```python
with Spinner("Analyzing data...", animation_type="color_wave"):
    time.sleep(3)
```

## Presets

Quick configuration via built-in presets:

```python
from kstlib.ui.spinner import Spinner

# Available: minimal, fancy, blocks, bounce, color_wave
spinner = Spinner.from_preset("fancy", "Processing...")
with spinner:
    time.sleep(2)
```

### Preset with overrides

```python
spinner = Spinner.from_preset(
    "fancy",
    "Custom message...",
    style="MOON",      # Override style
    interval=0.15,     # Override speed
)
```

## Customization

### Position

```python
# Spinner before text (default)
with Spinner("Loading...", position="before"):
    ...

# Spinner after text
with Spinner("Loading...", position="after"):
    ...
```

### Styling

```python
with Spinner(
    "Processing...",
    spinner_style="bold magenta",
    text_style="italic white",
):
    ...
```

### Success/Failure markers

```python
spinner = Spinner(
    "Connecting...",
    done_character="[OK]",
    done_style="bold green",
    fail_character="[FAIL]",
    fail_style="bold red",
)
spinner.start()
try:
    connect()
    spinner.stop(success=True)
except Exception:
    spinner.stop(success=False)
```

### Animation speed

```python
# Slow (0.2s between frames)
with Spinner("Slow...", interval=0.2):
    ...

# Fast (0.03s between frames)
with Spinner("Fast...", interval=0.03):
    ...
```

## Message Updates

Update the spinner message while running:

```python
with Spinner("Initializing...") as spinner:
    time.sleep(1)
    spinner.update("Loading modules...")
    time.sleep(1)
    spinner.update("Almost done...")
    time.sleep(1)
```

## Logging Above Spinner

Print messages above the spinner while it continues running. Perfect for showing progress logs, API responses, or verbose output:

```python
with Spinner("Processing batch...") as spinner:
    for i, item in enumerate(items, 1):
        process(item)
        spinner.log(f"Processed {item}", style="dim")
        spinner.update(f"Processing... ({i}/{len(items)})")
```

Example output:
```
  Processed item_001
  Processed item_002
  Processed item_003
⣾ Processing... (3/10)
```

The `log()` method:
- Clears the spinner line temporarily
- Prints your message with optional Rich styling
- Spinner redraws automatically on the next frame

```python
# With styles
spinner.log("Success!", style="green")
spinner.log("Warning: slow response", style="yellow")
spinner.log("Error: connection failed", style="bold red")
```

## Decorator for Existing Functions

Wrap any function with `@with_spinner` to add a spinner that captures its print output:

```python
from kstlib.ui.spinner import with_spinner

@with_spinner("Loading data...", log_style="cyan")
def load_data():
    print("Reading file...")    # Appears above spinner
    data = read_large_file()
    print("Processing...")      # Appears above spinner
    return process(data)

result = load_data()  # Spinner runs while function executes
```

You can also wrap existing functions dynamically:

```python
# Wrap a verbose library function
wrapped_fn = with_spinner("Building...", log_style="dim")(verbose_build)
wrapped_fn()
```

Options:
- `capture_prints=True` - Redirect stdout to spinner.log() (default)
- `capture_prints=False` - Just show spinner, don't capture prints
- `log_style` - Rich style for captured output
- `log_zone_height` - Use bounded log zone (see below)

### Decorator with Log Zone

Add `log_zone_height` to get a fixed spinner with bounded scrolling logs:

```python
@with_spinner("Building...", log_zone_height=5, log_style="cyan")
def build_project():
    print("Fetching deps...")   # Logs scroll in 5-line zone
    print("Compiling...")       # Old logs pushed out when full
    print("Testing...")
    return True
```

## Fixed Spinner with Log Zone (Manual)

`SpinnerWithLogZone` keeps the spinner fixed at the top while logs scroll below in a bounded area:

```python
from kstlib.ui.spinner import SpinnerWithLogZone

with SpinnerWithLogZone("Building...", log_zone_height=5) as sz:
    for step in build_steps:
        execute(step)
        sz.log(f"Completed: {step}", style="green")
        sz.update(f"Building: {step}...")
```

Visual layout:
```
⣾ Building: compile...          <- Fixed spinner line
  Completed: fetch deps         <- Log zone (scrolls)
  Completed: install
  Completed: compile
  Completed: test
  Completed: package
```

When more logs arrive than `log_zone_height`, old logs are automatically pushed out (FIFO).

## Configuration

### In kstlib.conf.yml

```yaml
ui:
  spinners:
    defaults:
      style: BRAILLE
      position: before
      animation_type: spin
      interval: 0.08
      spinner_style: cyan
      done_character: "✓"
      done_style: green
      fail_character: "✗"
      fail_style: red
    presets:
      custom_preset:
        style: MOON
        spinner_style: bold yellow
        interval: 0.12
```

Then use your custom preset:

```python
spinner = Spinner.from_preset("custom_preset", "Loading...")
```

## API Reference

| Class/Function | Description |
|----------------|-------------|
| `Spinner` | Main spinner class |
| `SpinnerWithLogZone` | Fixed spinner + scrolling log zone |
| `with_spinner` | Decorator that captures prints |
| `SpinnerStyle` | Animation character sets |
| `SpinnerPosition` | `BEFORE` or `AFTER` text |
| `SpinnerAnimationType` | `SPIN`, `BOUNCE`, `COLOR_WAVE` |

-> Full autodoc: {doc}`../../api/ui/index`

## Examples

See runnable examples in `examples/ui/spinner/`:

- `01_basic_usage.py` - Context manager and manual control
- `02_all_styles.py` - Gallery of all 9 styles
- `03_animation_types.py` - Spin, bounce, color wave
- `04_presets.py` - Using and overriding presets
- `05_customization.py` - Full customization options
- `06_with_logs.py` - Logs scrolling above spinner
- `07_decorator_and_zones.py` - @with_spinner decorator + SpinnerWithLogZone

Run all with:

```bash
python examples/ui/spinner/run_all_examples.py
```
