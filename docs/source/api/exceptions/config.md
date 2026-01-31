# Config Exceptions

Configuration failures surface through a dedicated hierarchy rooted at `KstlibError`. Importing from
`kstlib.config.exceptions` keeps the error handling consistent across loaders, exporters, and the CLI.

## Exception Hierarchy

```
KstlibError
└── ConfigError
    ├── ConfigFileNotFoundError    # Config file not found
    ├── ConfigFormatError          # Invalid YAML/JSON format
    ├── ConfigCircularIncludeError # Recursive include detected
    ├── ConfigIncludeDepthError    # Include depth exceeded (max 10)
    └── ConfigNotLoadedError       # Config not initialized
```

## Quick overview

- `KstlibError` groups every library-specific exception so callers can guard large sections of code
	with a single `except`.
- `ConfigError` narrows that scope to configuration-specific faults; downstream modules inherit from
	it when they depend on config state.
- `ConfigFileNotFoundError` extends `FileNotFoundError` to include the missing path in the message.
- `ConfigFormatError` captures parsing issues (unsupported extension, invalid YAML/JSON, strict mode
	violations).
- `ConfigCircularIncludeError` prevents recursive `include` directives.
- `ConfigIncludeDepthError` prevents deeply nested includes (max depth: 10) to protect against resource
	exhaustion attacks or misconfiguration.
- `ConfigNotLoadedError` is raised by helpers such as `require_config()` when the global configuration
	has not been initialised yet.

## Usage patterns

### Guarding config loads

```python
from kstlib.config import load_config
from kstlib.config.exceptions import ConfigFileNotFoundError, ConfigFormatError

try:
    config = load_config("kstlib.conf.yml")
except ConfigFileNotFoundError:
    raise SystemExit("Config missing; run kstlib config init")
except ConfigFormatError as error:
    raise SystemExit(f"Config invalid: {error}")
```

### Ensuring configuration is present

```python
from kstlib.config import require_config
from kstlib.config.exceptions import ConfigNotLoadedError

try:
    config = require_config()
except ConfigNotLoadedError:
    config = load_default_profile()
```

## Module reference

```{eval-rst}
.. automodule:: kstlib.config.exceptions
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```
