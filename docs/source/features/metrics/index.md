# Metrics

Performance measurement utilities: timing, memory tracking, call statistics, and step tracking for profiling code execution.

## TL;DR

```python
from kstlib.metrics import metrics, metrics_context, Stopwatch, call_stats

# Decorator: time + memory tracking (config-driven)
@metrics
def process_data(data: list) -> dict:
    return {"count": len(data), "sum": sum(data)}

result = process_data([1, 2, 3])  # Prints: [process_data] | 0.001s | Peak: 64 KB

# Context manager for code blocks
with metrics_context("Load configuration"):
    config = load_config()

# Call statistics (avg/min/max over multiple calls)
@call_stats
def api_call():
    return fetch_data()

for _ in range(10):
    api_call()
print_all_call_stats()  # Shows: [api_call] 10 calls | avg: 0.05s | min: 0.03s | max: 0.08s

# Manual stopwatch with laps
sw = Stopwatch("Pipeline")
sw.start()
# ... step 1 ...
sw.lap("Load data")
# ... step 2 ...
sw.lap("Transform")
sw.stop()
sw.summary()
```

## Key Features

- **Unified Decorator**: `@metrics` for time + memory tracking with Rich output
- **Call Statistics**: Track call count, avg/min/max duration with `@call_stats`
- **Context Manager**: `metrics_context()` for measuring code blocks
- **Stopwatch**: Manual lap timing with summary display
- **Step Tracking**: Numbered steps with `metrics_summary()` for pipelines
- **Rich Markup**: Configurable colors and icons via `kstlib.conf.yml`
- **Thread-safe**: All components are safe for concurrent use

## Quick Start

### Basic timing and memory

```python
from kstlib.metrics import metrics

@metrics
def compute_sum(n: int) -> int:
    """Compute sum of range."""
    return sum(range(n))

result = compute_sum(1_000_000)
# Output: [compute_sum (example.py:4)] | 0.023s | Peak: 128 KB
```

### Time only (disable memory)

```python
@metrics(memory=False)
def quick_operation():
    return [x * 2 for x in range(100)]
```

### Custom title

```python
@metrics("Loading user configuration")
def load_config():
    return {"db": "postgresql://..."}
```

## How It Works

### Metrics Decorator Flow

```text
@metrics
def func():
    ...

          ┌───────────────────┐
    ●───► │ Start tracemalloc │
          └─────────┬─────────┘
                    ▼
          ┌───────────────────┐
          │    Start timer    │
          └─────────┬─────────┘
                    ▼
          ┌───────────────────┐
          │   Execute func()  │
          └─────────┬─────────┘
                    ▼
          ┌───────────────────┐
          │    Stop timer     │
          └─────────┬─────────┘
                    ▼
          ┌───────────────────┐
          │   Read peak mem   │
          └─────────┬─────────┘
                    ▼
          ┌───────────────────┐
          │   Print result    │
          └───────────────────┘
```

### Step Tracking

When using `step=True`, each decorated function is assigned an incrementing step number:

```python
@metrics(step=True)
def step_a():
    pass

@metrics(step=True, title="Process records")
def step_b():
    pass

step_a()  # [STEP 1] step_a | 0.001s
step_b()  # [STEP 2] Process records | 0.002s

metrics_summary()  # Table with all steps and percentages
```

## Configuration

### In kstlib.conf.yml

```yaml
metrics:
  # Enable colored output
  colors: true

  # Default behavior for @metrics decorator
  defaults:
    time: true      # Track execution time
    memory: true    # Track peak memory (tracemalloc)
    step: false     # Enable step numbering

  # Format strings (Rich markup supported)
  step_format: "[STEP {n}] {title}"
  lap_format: "[LAP {n}] {name}"
  title_format: "{function} [dim green]({file}:{line})[/dim green]"

  # Thresholds for color warnings
  thresholds:
    time_warn: 5           # Warn color if >= 5 seconds
    time_crit: 30          # Critical color if >= 30 seconds
    memory_warn: 100000000 # Warn color if >= 100 MB
    memory_crit: 500000000 # Critical color if >= 500 MB

  # Icons (set to "" to disable)
  icons:
    time: ""
    memory: ""
    peak: "Peak:"

  # Color theme (Rich style names)
  theme:
    label: "bold green"
    title: "bold white"
    time_ok: "cyan"
    time_warn: "orange3"
    time_crit: "bold red"
    memory_ok: "rosy_brown"
    memory_warn: "orange3"
    memory_crit: "bold red"
```

### Per-call overrides

```python
# Override config values
@metrics(time=True, memory=False, step=True)
def my_step():
    pass

# Custom title overrides title_format
@metrics("Custom Title")
def my_func():
    pass
```

## Common Patterns

### Pipeline with step tracking

```python
from kstlib.metrics import metrics, metrics_summary, clear_metrics

clear_metrics()  # Reset step counter

@metrics(step=True)
def load_data():
    return fetch_from_api()

@metrics(step=True, title="Transform records")
def transform(data):
    return [process(x) for x in data]

@metrics(step=True)
def save_results(data):
    write_to_db(data)

# Run pipeline
data = load_data()
transformed = transform(data)
save_results(transformed)

# Show summary table
metrics_summary()
```

Output:

```text
                  Metrics Summary
+--------------------------------------------------+
|   # | Step               |   Time |  Memory |   %|
|-----+--------------------+--------+---------+----|
|   1 | load_data          | 1.234s | 2.1 MB  | 45%|
|   2 | Transform records  | 0.567s | 512 KB  | 21%|
|   3 | save_results       | 0.890s | 128 KB  | 34%|
+--------------------------------------------------+
  TOTAL: 2.691s | 2.7 MB (100%)
```

### Comparing implementations

```python
from kstlib.metrics import metrics

@metrics("Naive loading (full file)")
def load_naive(path):
    with open(path) as f:
        return f.read().splitlines()

@metrics("Chunked loading (streaming)")
def load_chunked(path, chunk_size=1000):
    lines = []
    with open(path) as f:
        for line in f:
            lines.append(line.strip())
    return lines

# Compare memory usage
data1 = load_naive("large_file.csv")
data2 = load_chunked("large_file.csv")
```

### API call statistics

```python
from kstlib.metrics import call_stats, print_all_call_stats, reset_all_call_stats

@call_stats
def api_fetch(endpoint: str):
    return requests.get(endpoint).json()

# Make many calls
for symbol in ["BTC", "ETH", "SOL"]:
    api_fetch(f"/ticker/{symbol}")

# View statistics
print_all_call_stats()
# [api_fetch] 3 calls | avg: 0.15s | min: 0.12s | max: 0.21s

# Reset for next batch
reset_all_call_stats()
```

### Manual stopwatch for complex flows

```python
from kstlib.metrics import Stopwatch

sw = Stopwatch("Data Pipeline")
sw.start()

# Phase 1
config = load_config()
sw.lap("Load config")

# Phase 2
data = fetch_data(config)
sw.lap("Fetch data")

# Phase 3
results = transform(data)
sw.lap("Transform")

# Phase 4
save(results)
sw.lap("Save")

sw.stop()
sw.summary()
```

Output:

```text
==================================================
Data Pipeline SUMMARY
==================================================
  [1] Load config: 0.051s [ 10.2%]
  [2] Fetch data: 0.312s [ 62.4%]
  [3] Transform: 0.089s [ 17.8%]
  [4] Save: 0.048s [  9.6%]
--------------------------------------------------
  TOTAL: 0.500s
```

### Context manager for inline measurements

```python
from kstlib.metrics import metrics_context

def process_file(path):
    with metrics_context("Read file") as m:
        data = read_file(path)

    print(f"Read took {m.elapsed_seconds:.3f}s")
    print(f"Peak memory: {m.peak_memory_formatted}")

    with metrics_context("Process data", memory=False):
        return transform(data)
```

### Disable output (collect only)

```python
@metrics(print_result=False)
def silent_operation():
    return expensive_computation()

# Access metrics programmatically
records = get_metrics()
for r in records:
    print(f"{r.title}: {r.elapsed_formatted}")
```

## Troubleshooting

### Memory tracking shows 0 bytes

**Cause**: `tracemalloc` was already running or memory was freed before measurement.

**Solution**: The decorator handles tracemalloc automatically. If you see 0 bytes, the operation likely uses no Python heap memory (e.g., C extensions).

### Step numbers not incrementing

**Cause**: `clear_metrics()` was called or `step=False`.

**Solution**: Ensure `step=True` and call `clear_metrics()` only at pipeline start:

```python
clear_metrics()  # Reset counter

@metrics(step=True)  # Must be step=True
def my_step():
    pass
```

### Rich markup not rendering

**Cause**: Terminal doesn't support colors or `colors: false` in config.

**Solution**: Check your terminal supports ANSI colors. In config:

```yaml
metrics:
  colors: true
```

### Stopwatch laps not printing

**Cause**: `print_result=False` passed to `lap()`.

**Solution**: Remove the parameter or set to `True`:

```python
sw.lap("Step name")  # Default: print_result=True
sw.lap("Silent", print_result=False)  # No output
```

## API Reference

Full autodoc: {doc}`../../api/metrics`

| Class/Function | Description |
| - | - |
| `metrics` | Decorator for time + memory tracking |
| `metrics_context` | Context manager for code blocks |
| `call_stats` | Decorator for call count statistics |
| `Stopwatch` | Manual lap timer with summary |
| `MetricsRecord` | Data container for measurements |
| `CallStats` | Statistics for tracked calls |

| Function | Description |
| - | - |
| `get_metrics()` | Get all recorded step metrics |
| `clear_metrics()` | Reset step counter and records |
| `metrics_summary()` | Print summary table of steps |
| `get_call_stats()` | Get stats for a specific function |
| `get_all_call_stats()` | Get all tracked call statistics |
| `print_all_call_stats()` | Print all call statistics |
| `reset_all_call_stats()` | Reset all call statistics |

| Exception | Description |
| - | - |
| `MetricsError` | Base exception for metrics errors |
