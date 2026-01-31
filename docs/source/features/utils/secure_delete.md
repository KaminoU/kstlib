# Secure Delete

Securely delete files by overwriting content before removal, preventing data recovery.

## Quick Start

```bash
# CLI
kstlib secrets shred sensitive_file.txt
```

```python
# Python
from kstlib.secure.fs import secure_delete

secure_delete("sensitive_file.txt")
```

## Why Secure Delete?

Normal file deletion (`rm`, `del`) only removes the file's directory entry. The actual data remains on disk until overwritten by new files. Secure deletion overwrites the file content multiple times before unlinking.

## Methods

### Auto (Recommended)

Automatically selects the best method for your platform:

```python
secure_delete("file.txt", method="auto")
```

| Platform | Method Used |
| - | - |
| Linux | `shred` command |
| macOS | `srm` or `rm -P` |
| Windows | Python overwrite |

### Command-based

Use system utilities when available:

```python
secure_delete("file.txt", method="command")
```

- Linux: `shred -vfz -n 3`
- macOS: `srm -sz` or `rm -P`
- Windows: Falls back to Python overwrite

### Python Overwrite

Pure Python implementation for portability:

```python
secure_delete("file.txt", method="overwrite")
```

## Configuration

### In kstlib.conf.yml

```yaml
secrets:
  secure_delete:
    method: auto           # auto | command | overwrite
    passes: 3              # Number of overwrite passes
    zero_last_pass: true   # Final pass with zeros
```

### Per-call options

```python
secure_delete(
    "file.txt",
    method="overwrite",
    passes=7,
    zero_last_pass=True,
)
```

## CLI Usage

```bash
# Basic shred
kstlib secrets shred sensitive.txt

# With verbose output
kstlib secrets shred sensitive.txt --verbose

# Multiple files
kstlib secrets shred file1.txt file2.txt file3.txt
```

## Integration with Encryption

Use `--shred` when encrypting to automatically delete the plaintext:

```bash
kstlib secrets encrypt secrets.yml --out secrets.sops.yml --shred
```

This:
1. Encrypts `secrets.yml` to `secrets.sops.yml`
2. Securely deletes the original `secrets.yml`

## Filesystem Guardrails

For broader path security (templates, attachments), see {doc}`../../api/secure`:

```python
from kstlib.secure import PathGuardrails, STRICT_POLICY

guard = PathGuardrails("/srv/app/data", policy=STRICT_POLICY)
safe_path = guard.resolve_file("user_upload.txt")
```

## Limitations

- **SSD wear leveling**: Modern SSDs may retain data in unmapped sectors. For highly sensitive data, use full-disk encryption.
- **Journaling filesystems**: Some data may exist in journal logs. Consider filesystem-level secure deletion.
- **Network/cloud storage**: Remote storage may have additional copies. Verify provider's deletion policies.

## API Reference

```python
def secure_delete(
    path: str | Path,
    method: str = "auto",
    passes: int = 3,
    zero_last_pass: bool = True,
) -> None:
    """
    Securely delete a file by overwriting before removal.

    Args:
        path: File to delete
        method: "auto", "command", or "overwrite"
        passes: Number of overwrite passes (default: 3)
        zero_last_pass: Write zeros on final pass (default: True)

    Raises:
        FileNotFoundError: If file doesn't exist
        PermissionError: If file cannot be written/deleted
    """
```
