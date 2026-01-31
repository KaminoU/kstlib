# Makefile Commands

The project includes a Makefile with convenience wrappers for common development tasks.

## Quick Reference

```bash
make help  # Show all available commands
```

## Development

### Testing

```bash
make tox        # Run full tox suite + create commit marker
make tox-clean  # Clean caches + recreate tox environments
```

The `tox` target creates a `.github/.tox-passed` marker file on success, enabling fast pre-commit checks.

### Lock Files

```bash
make lock       # Regenerate uv.lock and pylock.toml
make lock-check # Verify lock files are in sync
```

The project maintains two lock file formats:

| File | Format | Used by |
|------|--------|---------|
| `uv.lock` | uv native | `uv sync`, `uv pip install` |
| `pylock.toml` | PEP 751 standard | `uv`, future `pip` versions |

```{note}
`pylock.toml` follows [PEP 751](https://peps.python.org/pep-0751/), the new standard for lock files.
As of early 2026, `pip` does not yet support this format natively. Use `uv` for lock file installation,
or use `make dist-bundle` which also exports a `requirements-lock.txt` for pip compatibility.
```

## Build & Distribution

### Wheel Package

```bash
make dist  # Build wheel package in dist/
```

Creates a standard Python wheel: `dist/kstlib-X.Y.Z-py3-none-any.whl`

**Installation**:
```bash
pip install dist/kstlib-1.0.0-py3-none-any.whl
```

```{note}
The wheel format `py3-none-any` means: Python 3, no ABI dependency (pure Python), any platform.
```

### Offline Bundle

```bash
make dist-bundle  # Build wheel + all dependencies
```

Creates two artifacts in `dist/`:

| File | Description |
|------|-------------|
| `kstlib-X.Y.Z-bundle.zip` | Self-contained zip with all dependency wheels |
| `requirements-lock.txt` | Locked versions in pip-compatible format |

**Which one to use?**

| Scenario | Use |
|----------|-----|
| Same architecture, air-gapped | `bundle.zip` |
| Different architecture (e.g., build on Windows, deploy on Raspberry Pi) | `requirements-lock.txt` |
| Unsure | `requirements-lock.txt` (always works) |

#### Using the bundle (same architecture)

```bash
# 1. Extract the bundle
unzip kstlib-1.0.0-bundle.zip -d wheels/

# 2. Install without network access
pip install --no-index --find-links=wheels/ kstlib
```

```{warning}
**Architecture limitation**: The bundle contains wheels for the **build machine's architecture**.
A bundle created on Windows x64 will not work on ARM (Raspberry Pi) for packages with native
extensions (e.g., `cryptography`, `pydantic-core`).
```

#### Using requirements-lock.txt (cross-platform)

```bash
# Copy requirements-lock.txt to target, then:
pip install -r requirements-lock.txt
```

Pip downloads architecture-appropriate wheels from PyPI. This works on any platform.

## Secrets Management

Thin wrappers around the `kstlib secrets` CLI.

```bash
make secrets-doctor                    # Check SOPS setup
make secrets-encrypt SOURCE=file.yml   # Encrypt file
make secrets-decrypt SOURCE=file.sops.yml  # Decrypt file
make secrets-shred TARGET=file.yml     # Secure delete
```

### Variables

| Variable | Description |
|----------|-------------|
| `SOURCE` | Input file path (required for encrypt/decrypt) |
| `TARGET` | Target file path (required for shred) |
| `OUT` | Output file path (optional) |
| `CONFIG` | Path to .sops.yaml config |
| `BINARY` | Path to SOPS binary (default: `sops`) |
| `FORCE` | Overwrite existing files |
| `QUIET` | Suppress output |

### Example

```bash
make secrets-encrypt SOURCE=secrets.yml OUT=secrets.sops.yml CONFIG=~/.sops.yaml
```
