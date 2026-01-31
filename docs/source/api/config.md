# Configuration Loader

Public API for `kstlib.config`, covering the cascade helpers, loaders, and shortcuts used throughout the rest of
the library. The module is intentionally small: most of the behaviour lives in `kstlib.config.loader`, but this
namespace exposes the functions you are expected to import.

```{tip}
Pair this reference with {doc}`../features/config/index` for the feature guide.
```

## Quick overview

- `load_from_file(path, *, strict_format=False, **overrides)` reads a specific file (YAML/TOML/JSON/INI) and
  resolves any `include:` directives.
- `get_config(*, max_age=None, **overrides)` executes the cascading search and memoizes the result so imports do
  not thrash the filesystem.
- `require_config()` mirrors `get_config()` but raises immediately when no configuration has been loaded yet.
- `clear_config()` flushes the memoized cascade, useful in tests when multiple fixtures run in the same process.

---

## Core Functions

### get_config

```{eval-rst}
.. autofunction:: kstlib.config.get_config
   :noindex:
```

### load_from_file

```{eval-rst}
.. autofunction:: kstlib.config.load_from_file
   :noindex:
```

### require_config

```{eval-rst}
.. autofunction:: kstlib.config.require_config
   :noindex:
```

### clear_config

```{eval-rst}
.. autofunction:: kstlib.config.clear_config
   :noindex:
```

---

## ConfigLoader Class

### ConfigLoader

```{eval-rst}
.. autoclass:: kstlib.config.ConfigLoader
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

---

## SOPS Integration

### SopsDecryptor

```{eval-rst}
.. autoclass:: kstlib.config.SopsDecryptor
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

### get_decryptor

```{eval-rst}
.. autofunction:: kstlib.config.sops.get_decryptor
   :noindex:
```

---

## Exceptions

### ConfigError

```{eval-rst}
.. autoclass:: kstlib.config.ConfigError
   :show-inheritance:
   :noindex:
```

### ConfigFileNotFoundError

```{eval-rst}
.. autoclass:: kstlib.config.ConfigFileNotFoundError
   :show-inheritance:
   :noindex:
```

### ConfigNotLoadedError

```{eval-rst}
.. autoclass:: kstlib.config.ConfigNotLoadedError
   :show-inheritance:
   :noindex:
```
