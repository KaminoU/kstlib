# Utilities

Public API for `kstlib.utils`, a collection of utility helpers shared across kstlib modules. These functions
handle common tasks like dictionary merging, value formatting, lazy initialization, secure file deletion,
and email validation.

```{tip}
These utilities are building blocks used internally by other kstlib modules but are also available for
direct use in your applications.
```

## Quick overview

**Dictionary helpers:**
- `deep_merge(base, override)` - Recursively merge dictionaries with override semantics

**Formatting:**
- `format_bytes(size)` - Human-readable byte sizes (e.g., "1.5 GB")
- `format_count(n)` - Human-readable counts with SI suffixes
- `format_duration(seconds)` - Duration as "Xh Ym Zs"
- `format_time_delta(delta)` - Format timedelta objects
- `format_timestamp(epoch, fmt, tz)` - Config-driven epoch to datetime string
- `parse_size_string(s)` - Parse "10MB" to bytes

**Lazy initialization:**
- `lazy_factory(factory)` - Decorator for lazy singleton initialization

**Secure deletion:**
- `secure_delete(path)` - Securely delete files with configurable overwrite methods
- `SecureDeleteMethod` - Enum of deletion strategies (zeros, random, DoD, Gutmann)
- `SecureDeleteReport` - Result object with deletion details

**Text processing:**
- `replace_placeholders(template, values)` - Simple `{key}` placeholder substitution

**Validators:**
- `parse_email_address(s)` - Parse email string to `EmailAddress` object
- `normalize_address_list(addresses)` - Normalize list of email addresses
- `EmailAddress` - Named tuple for parsed email components
- `ValidationError` - Raised on invalid input

---

## Dictionary Helpers

### deep_merge

```{eval-rst}
.. autofunction:: kstlib.utils.deep_merge
   :noindex:
```

---

## Formatting Functions

### format_bytes

```{eval-rst}
.. autofunction:: kstlib.utils.format_bytes
   :noindex:
```

### format_count

```{eval-rst}
.. autofunction:: kstlib.utils.format_count
   :noindex:
```

### format_duration

```{eval-rst}
.. autofunction:: kstlib.utils.format_duration
   :noindex:
```

### format_time_delta

```{eval-rst}
.. autofunction:: kstlib.utils.format_time_delta
   :noindex:
```

### format_timestamp

```{eval-rst}
.. autofunction:: kstlib.utils.format_timestamp
   :noindex:
```

### parse_size_string

```{eval-rst}
.. autofunction:: kstlib.utils.parse_size_string
   :noindex:
```

---

## Lazy Initialization

### lazy_factory

```{eval-rst}
.. autofunction:: kstlib.utils.lazy_factory
   :noindex:
```

---

## Secure Deletion

### secure_delete

```{eval-rst}
.. autofunction:: kstlib.utils.secure_delete
   :noindex:
```

### SecureDeleteMethod

```{eval-rst}
.. autoclass:: kstlib.utils.SecureDeleteMethod
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

### SecureDeleteReport

```{eval-rst}
.. autoclass:: kstlib.utils.SecureDeleteReport
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

---

## Text Processing

### replace_placeholders

```{eval-rst}
.. autofunction:: kstlib.utils.replace_placeholders
   :noindex:
```

---

## Validators

### parse_email_address

```{eval-rst}
.. autofunction:: kstlib.utils.parse_email_address
   :noindex:
```

### normalize_address_list

```{eval-rst}
.. autofunction:: kstlib.utils.normalize_address_list
   :noindex:
```

### EmailAddress

```{eval-rst}
.. autoclass:: kstlib.utils.EmailAddress
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

### ValidationError

```{eval-rst}
.. autoclass:: kstlib.utils.ValidationError
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```

---

## HTTP Tracing

### HTTPTraceLogger

```{eval-rst}
.. autoclass:: kstlib.utils.HTTPTraceLogger
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:
```
