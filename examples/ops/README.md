# Ops Examples - Persistent Sessions

Demonstrates `kstlib.ops` for running bots in persistent sessions (tmux or container).

## The Demo Bot

`astro_bot.py` is a simple bot that displays a greeting every minute with a `kstlib.ui.Spinner`:

```
⣾ [000] Hello! I'm Astro. Today is Sunday 26 January 2026, it's 14:30.
⣽ [001] Hello! I'm Astro. Today is Sunday 26 January 2026, it's 14:31.
...
⣻ [999] Hello! I'm Astro. Today is Sunday 26 January 2026, it's 07:09.
⢿ [000] Hello! I'm Astro. Today is Sunday 26 January 2026, it's 07:10.  # Wraps to 0
```

The spinner animates while waiting, and the counter is cyclic (0-999) so you can see how long the bot has been running.

## Use Case

The point is **persistence**: start the bot, detach, come back later (even via SSH from another machine) and the bot is still running. You can see its output history.

## Option 1: tmux (Local Development)

Best for development on your local machine or a server you SSH into.

### Requirements

```bash
# Linux
apt install tmux

# macOS
brew install tmux

# Windows: Use WSL2
```

### Usage

```bash
# Start the bot
python run_tmux.py

# Or via CLI
kstlib ops start astro --backend tmux --command "python astro_bot.py"
```

### Commands

```bash
# Attach to see output
kstlib ops attach astro
# Or: tmux attach -t astro

# Detach (bot keeps running)
# Press: Ctrl+B D

# View recent logs without attaching
kstlib ops logs astro --lines 20

# Check status
kstlib ops status astro

# Stop the bot
kstlib ops stop astro
```

## Option 2: Container (Production)

Best for production deployments with podman or docker.

### Requirements

- [Podman](https://podman.io/getting-started/installation) (recommended, rootless)
- Or [Docker](https://docs.docker.com/get-docker/)

### Build the Image

```bash
cd examples/ops

# Podman (recommended)
podman build -t astro-bot .

# Or Docker
docker build -t astro-bot .
```

### Usage

```bash
# Start the bot
python run_container.py

# Or via CLI
kstlib ops start astro --backend container --image astro-bot
```

### Commands

```bash
# Attach to see output
kstlib ops attach astro

# Detach (bot keeps running)
# Press: Ctrl+P Ctrl+Q

# View logs
kstlib ops logs astro --lines 50

# Check status (with container ID)
kstlib ops status astro --json

# Stop and remove container
kstlib ops stop astro
```

## SSH Workflow Example

This is the real power of persistent sessions:

```bash
# On your dev machine
ssh myserver
cd /opt/bots
python run_tmux.py  # Start Astro
# Ctrl+B D to detach
exit  # Leave SSH

# ... hours later, from anywhere ...

ssh myserver
kstlib ops attach astro  # See Astro still running!
# [142] Hello! I'm Astro. Today is Sunday 26 January 2026, it's 16:52.
```

## Config-Driven Sessions

Define sessions in `kstlib.conf.yml` and manage them by name only.
The config becomes the single source of truth.

```yaml
ops:
  default_backend: tmux
  container_runtime: null  # auto-detect (podman or docker)

  sessions:
    astro:
      backend: tmux
      command: "python -m astro.bot"
      working_dir: "/opt/bots/astro"

    orion:
      backend: container
      image: "orion-bot:latest"
      volumes:
        - "./data:/app/data"
```

Config-defined sessions are **always visible** in `kstlib ops list`, even before
they are started (state: `defined`, dimmed). Once started, the state switches to
`running` (green). After stopping, it returns to `defined`.

```bash
kstlib ops list           # Shows astro and orion as "defined"
kstlib ops start astro    # Loads config automatically
kstlib ops list           # astro is now "running", orion still "defined"
kstlib ops stop astro
kstlib ops list           # Back to both "defined"
```

From Python:

```python
from kstlib.ops import SessionManager

session = SessionManager.from_config("astro")
session.start()
```

CLI arguments override config values when needed:

```bash
kstlib ops start orion --image orion-bot:v2  # Override image from config
```

See `config_driven/` subdirectory for complete tmux and container examples.
