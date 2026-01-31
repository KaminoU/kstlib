# Config-Driven Sessions

Demonstrates **config-driven** session management where `kstlib.conf.yml` is the
single source of truth for session definitions.

## What is Config-Driven?

Instead of hardcoding backend, image, command, and options in Python scripts or CLI
arguments, you define everything in `kstlib.conf.yml`:

```yaml
ops:
  default_backend: tmux
  container_runtime: null  # auto-detect (docker or podman)

  sessions:
    astro-dev:
      backend: tmux
      command: "python -m astro.bot"
      env:
        BOT_MODE: "dev"

    astro-prod:
      backend: container
      image: "astro-bot"
      env:
        BOT_MODE: "prod"
```

Then start, stop, and monitor sessions by **name only**:

```bash
kstlib ops start astro-dev    # backend + command loaded from config
kstlib ops status astro-dev
kstlib ops stop astro-dev
```

## Session Lifecycle

Config-driven sessions follow this lifecycle:

```
  kstlib.conf.yml        kstlib ops start       kstlib ops stop
  ┌──────────┐           ┌──────────┐           ┌──────────┐
  │ DEFINED  │  ──────►  │ RUNNING  │  ──────►  │ DEFINED  │
  │ (config) │           │ (active) │           │ (config) │
  └──────────┘           └──────────┘           └──────────┘
       │                      │                      │
       ▼                      ▼                      ▼
  Visible in             Visible in             Back to
  "ops list"             "ops list"             "ops list"
  (dimmed)               (green)                (dimmed)
```

Key point: sessions defined in config are **always visible** in `kstlib ops list`,
even before they are started. The state shows as `defined` (dimmed) until started.

## Runtime Auto-Detect

Set `container_runtime: null` (or omit it) to let kstlib auto-detect:

1. Checks for `podman` in PATH
2. Falls back to `docker` in PATH
3. Raises `ContainerRuntimeNotFoundError` if neither found

This means your config works on any machine with either runtime installed.

## CLI Overrides

Config values serve as defaults. CLI arguments override them:

```bash
# Start with config defaults
kstlib ops start astro-prod

# Override the image from CLI
kstlib ops start astro-prod --image astro-bot:v2

# Override the backend
kstlib ops start astro-dev --backend container --image astro-bot
```

## Examples

### tmux/ - Local Development

```bash
cd examples/ops/config_driven/tmux
python run.py              # Start from config
python run.py --status     # Check status
python run.py --stop       # Stop

# Or use CLI directly
kstlib ops list            # Shows astro-dev as "defined"
kstlib ops start astro-dev # Start from config
kstlib ops attach astro-dev
kstlib ops stop astro-dev
```

### container/ - Production

```bash
# Build the image first
cd examples/ops
docker build -t astro-bot .
# or: podman build -t astro-bot .

# Run config-driven
cd config_driven/container
python run.py              # Start from config
python run.py --status
python run.py --stop

# Or use CLI
kstlib ops list            # Shows astro-prod as "defined"
kstlib ops start astro-prod
kstlib ops logs astro-prod --lines 50
kstlib ops stop astro-prod
```

## Deep Defense

All values from `kstlib.conf.yml` are validated before use:

- Session names: alphanumeric + hyphens only
- Commands: no shell injection characters
- Image names: valid container image format
- Volumes/ports: valid mount/port format
- Environment variables: valid key=value pairs
- Session count: capped at 50 per config file

Invalid config entries are skipped with a warning logged, never executed.

## See Also

- [Ops Feature Guide](../../../docs/source/features/ops/index.md)
- [Ops API Reference](../../../docs/source/api/ops.md)
- [Parent README](../README.md) for direct (non-config) examples
