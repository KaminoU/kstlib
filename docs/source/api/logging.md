# Logging Manager

Public API for the logging subsystem. `kstlib.logging.LogManager` wraps the standard library logger with Rich
rendering, preset selection, rotation, and async-friendly helpers so you can ship console/file output without
rewriting plumbing.

```{tip}
Pair this reference with {doc}`../features/logging/index` for the feature guide.
```

## Quick overview

- `LogManager` accepts `config` overrides or a `preset` (`dev`, `prod`, `debug`), falling back to the cascade
    described below.
- Console output relies on Rich handlers with custom icons, color themes, and traceback rendering.
- File logging uses timed rotation (`when`, `interval`, `backup_count`) and auto-creates directories when
    needed.
- Async helpers (`ainfo`, `asuccess`, …) dispatch to a thread pool so event loops do not block while
    performing I/O heavy logging.
- Structured context (`logger.info("msg", key=value)`) is flattened into `key=value` segments automatically.

## Configuration cascade

The constructor merges configuration from six sources. Later entries override earlier ones:

1. `FALLBACK_DEFAULTS` from `kstlib.logging.manager`
2. `FALLBACK_PRESETS` (`dev`, `prod`, `debug`)
3. `logger.defaults` in `kstlib.conf.yml`
4. `logger.presets[<name>]` in `kstlib.conf.yml`
5. Remaining keys under `logger` (`output`, `icons`, `rotation`, etc.)
6. The explicit `config` argument

You can pass `preset="prod"` to force a preset without touching the config file, or supply a full dict for
one-off tweaks inside tests.

## Default profile

```yaml
logger:
    defaults:
        output: both  # console | file | both
        theme:
            trace: "medium_purple4 on dark_olive_green1"
            debug: "black on deep_sky_blue1"
            info: "sky_blue1"
            success: "black on sea_green3"
            warning: "bold white on salmon1"
            error: "bold white on deep_pink2"
            critical: "blink bold white on red3"
        icons:
            show: true
            debug: "🔎"
            info: "📄"
            success: "✅"
            warning: "🚨"
            error: "❌"
            critical: "💀"
        console:
            level: DEBUG
            datefmt: "%Y-%m-%d %H:%M:%S"
            format: "::: PID %(process)d / TID %(thread)d ::: %(message)s"
            show_path: true
            tracebacks_show_locals: true
        file:
            level: DEBUG
            datefmt: "%Y-%m-%d %H:%M:%S"
            format: "[%(asctime)s | %(levelname)-8s] ::: PID %(process)d / TID %(thread)d ::: %(message)s"
            log_path: "./"
            log_dir: "logs"
            log_name: "kstlib.log"
            log_dir_auto_create: true
        rotation:
            when: midnight
            interval: 1
            backup_count: 7
```

Presets adjust only the relevant sections (`output`, per-handler levels, icon visibility). Anything left
unspecified inherits from the defaults above.

## Usage patterns

### Basic logging

```{literalinclude} ../../../examples/logging/basic_usage.py
:start-after: "# Example 1: Basic logging levels"
:end-before: "# Example 2: Structured logging"
:language: python
```

### Structured context

```{literalinclude} ../../../examples/logging/basic_usage.py
:start-after: "# Example 2: Structured logging"
:end-before: "# Example 3: Preset usage"
:language: python
```

### Presets

```{literalinclude} ../../../examples/logging/basic_usage.py
:start-after: "# Example 3: Preset usage"
:end-before: "# Example 4: Custom runtime configuration"
:language: python
```

### Async helpers

```{literalinclude} ../../../examples/logging/basic_usage.py
:start-after: "# Example 6: Async logging integration"
:end-before: "if __name__ == \"__main__\":"
:language: python
```

## Module reference

```{eval-rst}
.. automodule:: kstlib.logging
        :members:
        :undoc-members:
        :show-inheritance:
```
