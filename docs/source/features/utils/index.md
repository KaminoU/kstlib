# Utilities

Helper functions and decorators used across kstlib modules.

## TL;DR

```python
from kstlib.utils import lazy_factory
from kstlib.secure import secure_delete

# Defer heavy imports until first use
@lazy_factory("cryptography.fernet", "Fernet")
def get_fernet(**kwargs):
    ...

fernet = get_fernet(key=my_key)  # Import happens here

# Securely delete sensitive files
secure_delete("secrets.txt")
```

## Key Features

- **Lazy loading**: `@lazy_factory` defers imports until first call
- **Secure deletion**: Multiple overwrite passes before unlinking
- **Dictionary helpers**: Deep merge with override semantics
- **Formatters**: Human-readable bytes, counts, durations
- **Validators**: Email parsing and normalization

## Quick Start

```python
# 1. Lazy loading for slow imports
from kstlib.utils import lazy_factory

@lazy_factory("pandas", "DataFrame")
def get_dataframe(**kwargs):
    ...

df = get_dataframe(data=my_data)  # pandas imported here

# 2. Secure file deletion
from kstlib.secure import secure_delete

secure_delete("sensitive_data.txt")  # Overwrite then delete

# 3. Deep merge dictionaries
from kstlib.utils import deep_merge

base = {"a": 1, "nested": {"x": 10}}
override = {"nested": {"y": 20}}
result = deep_merge(base, override)
# {"a": 1, "nested": {"x": 10, "y": 20}}
```

## How It Works

### Lazy Factory

The `@lazy_factory` decorator defers module imports until the decorated function is first called:

```python
from kstlib.utils import lazy_factory

@lazy_factory("heavy_module", "HeavyClass")
def get_heavy_instance(**kwargs):
    ...

# heavy_module is NOT imported yet
instance = get_heavy_instance(param=value)
# NOW heavy_module is imported
```

This improves startup time when heavy dependencies are only needed in certain code paths.

### Secure Delete

Secure deletion overwrites file contents before unlinking to prevent recovery:

```python
from kstlib.secure import secure_delete, SecureDeleteMethod

# Default (auto-detects best method)
secure_delete("file.txt")

# Specific method
secure_delete("file.txt", method=SecureDeleteMethod.DOD)  # DoD 5220.22-M
secure_delete("file.txt", method=SecureDeleteMethod.GUTMANN)  # 35 passes
```

See {doc}`secure_delete` for detailed options.

## Configuration

### Secure delete in kstlib.conf.yml

```yaml
secrets:
  secure_delete:
    method: auto       # auto | command | overwrite
    passes: 3          # Number of overwrite passes
    zero_last_pass: true  # Final pass with zeros
```

## Common Patterns

### Lazy import for optional dependencies

```python
from kstlib.utils import lazy_factory

@lazy_factory("keyring", "get_password")
def get_keyring_password(**kwargs):
    ...

# Use only if keyring is available
try:
    password = get_keyring_password(service="myapp", username="user")
except ImportError:
    password = os.getenv("MYAPP_PASSWORD")
```

### Secure cleanup after encryption

```python
from kstlib.secure import secure_delete

# Create plaintext file
with open("secrets.yml", "w") as f:
    f.write("api_key: sk_xxx")

# Encrypt (external tool)
encrypt_file("secrets.yml", "secrets.sops.yml")

# Securely delete original
secure_delete("secrets.yml")
```

### Deep merge configuration

```python
from kstlib.utils import deep_merge

defaults = {
    "logging": {"level": "INFO", "format": "simple"},
    "cache": {"ttl": 300},
}

user_config = {
    "logging": {"level": "DEBUG"},
}

final = deep_merge(defaults, user_config)
# {"logging": {"level": "DEBUG", "format": "simple"}, "cache": {"ttl": 300}}
```

## Troubleshooting

### ImportError from lazy_factory

The module or class doesn't exist:

```python
# Wrong: typo in module name
@lazy_factory("cyptography", "Fernet")  # "cyptography" should be "cryptography"

# Wrong: class doesn't exist in module
@lazy_factory("cryptography", "Ferret")  # "Ferret" should be "Fernet"
```

### Secure delete not working on Windows

Windows may lock files. Ensure:

1. File is not open in another process
2. You have write permissions
3. File is not read-only

### Deep merge replacing instead of merging

Lists are replaced, not merged:

```python
base = {"items": [1, 2, 3]}
override = {"items": [4, 5]}
result = deep_merge(base, override)
# {"items": [4, 5]}  # List replaced, not [1, 2, 3, 4, 5]
```

## Learn More

```{toctree}
:maxdepth: 1

lazy
secure_delete
```

## API Reference

Full autodoc: {doc}`../../api/utils`

| Function | Description |
| - | - |
| `lazy_factory(module, cls)` | Decorator for deferred imports |
| `secure_delete(path, ...)` | Securely delete files with overwrite |
| `deep_merge(base, override)` | Recursively merge dictionaries |
| `format_bytes(size)` | Human-readable byte sizes |
| `format_duration(seconds)` | Duration as "Xh Ym Zs" |
