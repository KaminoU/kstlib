# Configuration

Flexible configuration management with multi-format support, cascading search, and type-checked access.

## TL;DR

```python
from kstlib.config import ConfigLoader

# Load with auto-discovery (recommended)
config = ConfigLoader().config

# Access with dot notation
print(config.app.name)
print(config.database.host)
```

```bash
# Export default config to customize
kstlib config export --out kstlib.conf.yml
```

## Key Features

- **Multi-format support**: YAML, TOML, JSON, and INI
- **Cascading search**: Automatic discovery across multiple locations
- **Include system**: Compose configs from multiple files
- **Deep merge**: Intelligent merging of nested configurations
- **Dot notation**: Easy access to nested values via Box
- **Type safety**: Full type hints for IDE support

## Quick Start

```yaml
# kstlib.conf.yml
app:
  name: "My Application"
  debug: true

database:
  host: "localhost"
  port: 5432
```

```python
from kstlib.config import load_from_file

# 1. Load from specific file
config = load_from_file("kstlib.conf.yml")

# 2. Or use auto-discovery
from kstlib.config import ConfigLoader
config = ConfigLoader().config

# 3. Access values with dot notation
print(config.app.name)       # "My Application"
print(config.database.port)  # 5432
```

## How It Works

### Loading Strategies

**Cascading mode** (recommended) searches multiple locations in order:

```python
config = ConfigLoader().config
```

Search order (priority from highest to lowest):
1. Current working directory (`./kstlib.conf.yml`)
2. User's home directory (`~/kstlib.conf.yml`)
3. User's config directory (`~/.config/kstlib.conf.yml`)
4. System-wide config dirs via `platformdirs.site_config_dir`:
   - Linux: `/etc/xdg/kstlib/` plus every entry in `$XDG_CONFIG_DIRS`
   - macOS: `/Library/Application Support/kstlib/`
   - Windows: `%PROGRAMDATA%/kstlib/`
5. Package defaults (lowest priority)

System-wide entries are merged silently. If a file does not exist at a given
location, it is skipped without warning or error. This lets operators drop a
shared `kstlib.conf.yml` in `/etc/xdg/kstlib/` (or the platform equivalent)
while users override individual keys in their home directory.

See [System-Wide Configuration](#system-wide-configuration) below for the
full per-OS defaults and the rules that apply when `XDG_CONFIG_DIRS` lists
several directories.

**Direct mode** loads from a specific file:

```python
config = load_from_file("path/to/config.yml")
```

**Environment variable** mode loads from a path in an env var:

```python
# Uses CONFIG_PATH env var by default
config = ConfigLoader(auto_source="env").config

# Or specify a different env var name
config = ConfigLoader(auto_source="env", auto_env_var="MYAPP_CONFIG_FILE").config
```

### System-Wide Configuration

System-wide configuration lets operators ship shared defaults (corporate
endpoints, logging targets, TLS settings, audit rules, ...) from a location
that every user of a machine inherits automatically. Users keep their own
`~/.config/kstlib.conf.yml` and the cascade merges the two without any
manual wiring.

Under the hood, kstlib delegates path discovery to
[`platformdirs.site_config_dir`](https://platformdirs.readthedocs.io), so the
behavior matches every other well-behaved XDG-aware tool.

#### Default paths per OS

| Platform | Default system config path |
| - | - |
| Linux / BSD | `/etc/xdg/kstlib/kstlib.conf.yml` |
| macOS | `/Library/Application Support/kstlib/kstlib.conf.yml` |
| Windows | `%PROGRAMDATA%\kstlib\kstlib.conf.yml` (typically `C:\ProgramData\kstlib\kstlib.conf.yml`) |

```{note}
On Windows and macOS, writing to these paths usually requires administrator
or root privileges. That is intentional: system-wide config is meant to be
provisioned by an operator or a configuration management tool (Ansible,
Puppet, Chef, Intune, ...), not hand-edited by end users.
```

#### Linux: `XDG_CONFIG_DIRS` semantics

On Linux and other XDG-compliant Unices, kstlib honors the standard
[XDG Base Directory Specification](https://specifications.freedesktop.org/basedir-spec/basedir-spec-latest.html).
The `XDG_CONFIG_DIRS` environment variable takes a **colon-separated** list
of directories, ordered from **highest to lowest** priority:

```bash
# /etc/corp/kstlib wins over /etc/xdg/kstlib for common keys
export XDG_CONFIG_DIRS=/etc/corp:/etc/xdg
```

If `XDG_CONFIG_DIRS` is unset, kstlib falls back to the single default
`/etc/xdg/kstlib/`.

Each directory in the list is probed for `kstlib.conf.yml`. kstlib then
deep-merges every file it finds, so keys defined in the higher-priority
directory override identical keys in the lower-priority ones, while
non-conflicting keys are unioned.

```{tip}
You can inspect what kstlib will probe on your machine:

    python -c "import platformdirs; print(platformdirs.site_config_dir('kstlib', appauthor=False, multipath=True))"
```

#### Full cascade at a glance

From lowest to highest priority (later entries override earlier ones):

```text
1. Package defaults (shipped inside kstlib)
2. System config dirs:
     - $XDG_CONFIG_DIRS entries (Linux, if set)      <- lowest system priority
     - /etc/xdg/kstlib (Linux default, if XDG unset)
     - /Library/Application Support/kstlib (macOS)
     - %PROGRAMDATA%\kstlib (Windows)                <- highest system priority
3. ~/.config/kstlib.conf.yml
4. ~/kstlib.conf.yml
5. ./kstlib.conf.yml (cwd)                           <- highest overall
6. Runtime kwargs (supersede every file source)
```

Missing files at any level are skipped silently. This is the whole point:
deployments can pre-provision a system file, and machines that do not have
one simply fall through to the next layer.

#### Example: corporate baseline + user overrides

```yaml
# /etc/xdg/kstlib/kstlib.conf.yml (shipped by IT)
logger:
  defaults:
    output: file
    rotation: daily
alerts:
  channels:
    slack:
      webhook_url: https://hooks.slack.com/services/OPS/CORP/XXXXX
```

```yaml
# ~/.config/kstlib.conf.yml (written by the developer)
logger:
  defaults:
    level: DEBUG  # Adds to the corporate baseline
```

The effective configuration for this user is:

```yaml
logger:
  defaults:
    output: file       # from system
    rotation: daily    # from system
    level: DEBUG       # from user (added)
alerts:
  channels:
    slack:
      webhook_url: https://hooks.slack.com/services/OPS/CORP/XXXXX  # from system
```

The developer cannot accidentally lose the corporate Slack webhook or the
file-rotation policy, but they can still opt into DEBUG locally.

#### Opting out

System-wide config is always active in cascading mode, but you can bypass
it entirely by using direct mode:

```python
from kstlib.config import load_from_file

# Only this file is loaded - no cascade, no system dirs
config = load_from_file("/opt/myapp/isolated.yml")
```

Or by scoping the loader to an explicit file:

```python
from kstlib.config import ConfigLoader

loader = ConfigLoader(auto_source="file", auto_path="./test.yml")
```

### Include System

Compose configurations from multiple files:

```yaml
# main.yml
include:
  - database.toml
  - features.json

app:
  name: "My App"
```

**Deep merge behavior**:
- Nested dictionaries are recursively merged
- Lists are replaced (not merged)
- Later values override earlier ones

```{warning}
**Override priority matters!** Values are merged left-to-right with later sources
overwriting earlier ones:

`package defaults` → `user config file` → `includes` → `kwargs`

This means a value in your config file will override package defaults, and
`kwargs` passed at runtime will override everything else.

**Example**: If package defaults set `app.debug: false` and your config file has
`app.debug: true`, the final value is `true`. If you then pass `debug=False` as
a kwarg, it becomes `False` again.
```

### Supported Formats

| Format | Extensions | Notes |
| - | - | - |
| YAML | `.yml`, `.yaml` | Recommended, supports comments |
| TOML | `.toml` | Good for hierarchical data |
| JSON | `.json` | Strict, no comments |
| INI | `.ini` | Legacy support |

### Caching

Config is cached after first load:

```python
from kstlib.config import get_config, clear_config

config = get_config()        # Cached config (fast)
config = get_config(max_age=0)  # Force reload
clear_config()               # Clear cache entirely
```

## Configuration

### CLI Export

Bootstrap configuration files from package defaults:

```bash
# Export full default config
kstlib config export --out kstlib.conf.yml

# Export specific section
kstlib config export --section secrets --out secrets.yml

# Preview to stdout
kstlib config export --stdout
```

### Environment-Based Structure

Recommended project layout:

```text
myapp/
├── config/
│   ├── base.yml          # Defaults (committed)
│   ├── development.yml   # Dev overrides
│   ├── production.yml    # Prod overrides
│   └── secrets.yml       # Local secrets (gitignored)
└── src/
```

```yaml
# config/base.yml
app:
  name: "My Application"
  debug: false
  log_level: INFO

database:
  pool_size: 10
  timeout: 30
```

```yaml
# config/development.yml
include: base.yml

app:
  debug: true
  log_level: DEBUG

database:
  host: localhost
```

### Strict Format Mode

Enforce format consistency (all includes must match parent format):

```python
config = load_from_file("config.yml", strict_format=True)
```

### Default Configuration

The package ships with sensible defaults. Export to customize:

```bash
kstlib config export --out kstlib.conf.yml
```

```{note}
**Partial override only**: You do not need to copy the entire default configuration.
The system deep-merges your config with package defaults, so you only specify what
you want to change:

```yaml
# Minimal user config - only override what you need
logger:
  defaults:
    output: file  # Everything else uses package defaults

cache:
  default_strategy: lru
```

This keeps your config clean and maintainable. For larger projects, you can also
split your config into multiple files using the `include:` directive.


```{dropdown} View default configuration
:icon: file-code

```{literalinclude} ../../../../src/kstlib/kstlib.conf.yml
:language: yaml
:linenos:
```

## Common Patterns

### Development vs Production

```python
import os
from kstlib.config import load_from_file

env = os.getenv("APP_ENV", "development")
config = load_from_file(f"config/{env}.yml")
```

### Override from environment

```python
# Load base config, then override specific values
config = ConfigLoader().config

# Override at runtime (config is a Box, so this works)
if os.getenv("DEBUG"):
    config.app.debug = True
```

### Testing with isolated config

```python
from pathlib import Path
from kstlib.config import clear_config, load_from_file

def test_custom_config(tmp_path: Path):
    config_file = tmp_path / "test.yml"
    config_file.write_text("""
    app:
      debug: true
    """)

    clear_config()  # Isolate from other tests
    config = load_from_file(config_file)

    assert config.app.debug is True
```

### Advanced: AutoDiscoveryConfig

Bundle discovery settings into a reusable object:

```python
from pathlib import Path
from kstlib.config import ConfigLoader
from kstlib.config.loader import AutoDiscoveryConfig

auto = AutoDiscoveryConfig(
    enabled=True,
    source="file",
    filename="kstlib.conf.yml",
    env_var="APP_CONFIG",
    path=Path("/srv/kstlib/prod.yml"),
)

loader = ConfigLoader(auto=auto)
config = loader.config
```

## Troubleshooting

### ConfigFileNotFoundError

File doesn't exist at the specified path:

```python
from kstlib.config import load_from_file
from kstlib.exceptions import ConfigFileNotFoundError

try:
    config = load_from_file("config.yml")
except ConfigFileNotFoundError:
    # Fall back to defaults or create config
    config = bootstrap_defaults()
```

### ConfigFormatError

Invalid syntax or parse error in config file:

```python
from kstlib.exceptions import ConfigFormatError

try:
    config = load_from_file("config.yml")
except ConfigFormatError as exc:
    raise SystemExit(f"Invalid configuration: {exc}")
```

### ConfigCircularIncludeError

Include loop detected (A includes B, B includes A):

```yaml
# This will fail
# a.yml includes b.yml, b.yml includes a.yml
```

Fix: Review your include chain and remove the circular dependency.

### Config not updating after file change

Config is cached by default. Force reload:

```python
from kstlib.config import clear_config, get_config

clear_config()
config = get_config()  # Fresh load
```

### Environment variable not found

When using `auto_source="env"`, ensure the variable is set:

```bash
export CONFIG_PATH=/path/to/config.yml
```

```python
# This fails if CONFIG_PATH is not set
config = ConfigLoader(auto_source="env").config
```

## API Reference

Full autodoc: {doc}`../../api/config`

| Function | Description |
| - | - |
| `ConfigLoader()` | Main loader class with auto-discovery |
| `load_from_file(path)` | Load from specific file |
| `get_config()` | Get cached config (singleton) |
| `clear_config()` | Clear the config cache |
