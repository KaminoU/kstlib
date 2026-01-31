# Contributing to kstlib

Thank you for your interest in contributing to kstlib! 🎉

## 🤝 Code of Conduct

Be respectful, inclusive, and professional. We're all here to learn and improve kstlib together.

## 🚀 Getting Started

### Prerequisites

- Python 3.10+
- Git
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Familiarity with pytest, Ruff, and mypy

### Fork and Clone

1. Fork the repository on GitHub
2. Clone your fork locally:

   ```bash
   git clone https://github.com/KaminoU/kstlib.git
   cd kstlib
   ```

## 🛠️ Development Setup

### 1. Install uv (recommended)

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
irm https://astral.sh/uv/install.ps1 | iex
```

### 2. Create a virtual environment

```bash
# Using uv (recommended - faster)
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Or using venv
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Or using conda
conda create -n kstlib_dev python=3.10
conda activate kstlib_dev
```

### 3. Install in development mode

#### Recommended: PEP 751 lockfile installation (supply chain verified)

```bash
# Install from pylock.toml with SHA256-verified dependencies
uv pip sync pylock.toml
uv pip install -e . --no-deps
```

This is the same installation method used by CI and tox tests. It provides:

- **Hash verification**: Every package is SHA256-verified against the lockfile
- **Exact versions**: Identical dependency tree as CI (no version drift)
- **Reproducibility**: Same behavior on every machine, every time
- **PEP 751 standard**: Interoperable format, future pip native support

#### Alternative: Dynamic resolution (no guarantees)

```bash
pip install -e .[dev]
```

This resolves dependencies at install time. Acceptable for quick local experiments, but offers no supply chain verification. If tests pass locally but fail in CI, dependency version drift is a likely cause.

### 4. Verify setup

```bash
# Run tests
pytest

# Check linting
ruff check .

# Check formatting
ruff format --check .

# Check types
mypy src/
```

### 5. Install pre-commit hooks

```bash
pre-commit install
```

Pre-commit hooks run automatically on each `git commit` to check:

- Lockfile is up to date (`uv lock --check`)
- Code formatting (`ruff format --check`)
- Linting (`ruff check`)

You can also run them manually:

```bash
# Run all hooks on all files
pre-commit run --all-files

# Run full tox suite (manual stage)
pre-commit run tox --hook-stage manual
```

## ✏️ Making Changes

### 1. Create a branch

```bash
git checkout main
git pull origin main
git checkout -b feature/your-feature-name
```

**Branch naming conventions:**

- `feature/` - New features
- `fix/` - Bug fixes
- `docs/` - Documentation updates
- `refactor/` - Code refactoring
- `test/` - Test additions/updates

### 2. Make your changes

- Follow the [Code Style](#-code-style) guidelines
- Add tests for new features
- Update documentation as needed
- Keep commits atomic and well-described

### 3. Commit your changes

```bash
git add .
git commit -m "feat: add awesome feature

- Implement feature X
- Add tests for feature X
- Update documentation"
```

**Commit message format:**

```text
<type>: <short description>

<detailed description>
<list of changes>
```

**Types:** `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

## 🔐 Security Notes

### Supply Chain

- **Always use lockfile installation** (`uv pip sync pylock.toml`) when running
  tests or deploying. This ensures SHA256-verified, reproducible builds.
- We use **PEP 751** standard format (`pylock.toml`) for future pip interoperability.
- If you add or update dependencies, regenerate the lockfile:

  ```bash
  uv lock && uv export --format pylock.toml --all-extras -o pylock.toml
  ```

- Never commit a lockfile without verifying tests pass with `tox` (full matrix).

### Code Security

- Leave the JSON serializer as the default for ``FileCacheStrategy``. Discuss any
  change to ``pickle``/``auto`` defaults with maintainers before submitting a PR.
- Reuse the provided email validators and placeholder helpers; do not bypass the
  sanitisation they provide when composing messages or formatting logs.
- When touching the SOPS provider, keep stderr redaction intact and add tests to
  cover the expected ``[REDACTED]`` markers in ``tests/secrets/test_providers.py``.
- New code that handles secrets must include tests and docs describing the
  threat model, and must pass ``ruff``, ``mypy --strict src`` and
  ``pytest --cov`` before review.

## 🧪 Testing

### Run all tests

```bash
pytest
```

### Run with coverage

```bash
pytest --cov=src --cov-report=term --cov-report=html
```

### Run specific tests

```bash
# Test a specific file
pytest tests/config/test_loader.py

# Test a specific function
pytest tests/config/test_loader.py::test_load_config_basic

# Run only fast tests
pytest -m "not slow"
```

### Test guidelines

- Aim for **95%+ coverage**
- Test edge cases and error conditions
- Use descriptive test names: `test_<what>_<condition>_<expected>`
- Use pytest fixtures for setup/teardown
- Mock external dependencies

### Test across Python versions with tox

Before submitting your PR, ensure tests pass on **all supported Python versions** (3.10-3.14):

```bash
# Install tox with uv support (10-100x faster than pip)
pip install tox tox-uv

# Run tests on all Python versions
tox

# Run only linting checks
tox -e lint

# Run on specific Python version
tox -e py311
```

**Note:** tox is configured to use `uv` for dependency installation, making test environment creation significantly faster. CI will automatically test on Python 3.10, 3.11, 3.12, 3.13, and 3.14 across Windows, macOS, and Linux.

## 📤 Submitting Changes

### 1. Push your branch

```bash
git push origin feature/your-feature-name
```

### 2. Create a Pull Request

- Go to GitHub and create a PR from your branch to `main`
- Fill out the PR template completely
- Link related issues with `Closes #123` or `Fixes #456`
- Wait for CI checks to pass
- Request review from maintainers

### 3. Address review feedback

- Make requested changes
- Push updates to your branch
- Respond to review comments
- Keep the PR up-to-date with `main` branch

## 🎨 Code Style

### Python Style

We use **Ruff** for linting and formatting:

```bash
# Format code
ruff format .

# Check linting
ruff check .

# Auto-fix issues
ruff check --fix .
```

### Type Hints

All public functions **must** have type hints:

```python
def load_config(file_path: str, strict: bool = False) -> Box:
    """Load configuration from file."""
    ...
```

### Docstrings

Use **Google style** docstrings:

```python
def example_function(param1: str, param2: int = 0) -> bool:
    """Short description.

    Longer description if needed.

    Args:
        param1: Description of param1
        param2: Description of param2 (default: 0)

    Returns:
        Description of return value

    Raises:
        ValueError: Description of when this is raised

    Examples:
        Basic usage::

            result = example_function("test", 42)
            assert result is True
    """
    ...
```

### Code Conventions

- **Line length:** 100 characters max
- **Imports:** Always use absolute imports (`from kstlib...`). Ruff will keep them sorted and grouped automatically.
- **Naming:**
  - `snake_case` for functions and variables
  - `PascalCase` for classes
  - `UPPER_SNAKE_CASE` for constants
  - `_prefix` for private/internal

## 🐛 Reporting Bugs

Use the [Bug Report template](https://github.com/KaminoU/kstlib/issues/new?template=bug_report.md) and include:

- OS and Python version
- kstlib version
- Steps to reproduce
- Expected vs actual behavior
- Error messages/logs

## 💡 Suggesting Features

Use the [Feature Request template](https://github.com/KaminoU/kstlib/issues/new?template=feature_request.md) and include:

- Use case description
- Proposed solution
- Alternative solutions considered
- Examples/mockups

## 📚 Documentation

- Update docstrings for code changes
- Update Sphinx docs in `docs/source/` if needed
- Add examples in `examples/` for new features
- Update `CHANGELOG.md` with your changes

## ❓ Questions?

- Open a [Discussion](https://github.com/KaminoU/kstlib/discussions)
- Ask in issues with the `question` label

## 🎯 Development Workflow Summary

1. Fork and clone the repository
2. Create a branch from `main`
3. Make changes following code style
4. Add tests (95%+ coverage)
5. Run `ruff format .`, `ruff check .`, `mypy src/`, `pytest`
6. Commit with descriptive messages
7. Push and create PR to `main`
8. Address review feedback
9. Merge when approved! 🎉

---

**Thank you for contributing to kstlib!** 🚀
