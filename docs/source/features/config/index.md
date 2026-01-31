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

Search order:
1. Current working directory
2. `$XDG_CONFIG_HOME/kstlib/` (Linux/macOS) or `%APPDATA%/kstlib/` (Windows)
3. Package defaults

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
