# Quality & CI

Code quality is enforced through automated tooling and CI pipelines.

## Linting

[Ruff](https://docs.astral.sh/ruff/) handles both linting and formatting:

```bash
# Check for issues
ruff check src/

# Auto-fix issues
ruff check src/ --fix

# Format code
ruff format src/ tests/
```

Configuration in `pyproject.toml`:

```toml
[tool.ruff]
line-length = 100
target-version = "py310"

[tool.ruff.lint]
select = ["ALL"]
ignore = ["D203", "D213", "COM812"]  # And other rules
```

## Type Checking

[Mypy](https://mypy.readthedocs.io/) with strict mode:

```bash
# Run type checking
mypy src/

# Via tox
tox -e mypy
```

Configuration in `pyproject.toml`:

```toml
[tool.mypy]
strict = true
warn_return_any = true
warn_unused_ignores = true
```

## Testing

See {doc}`testing` for comprehensive testing documentation including:

- Test structure by module
- Running tests with tox/pytest
- Coverage requirements (95% minimum)
- SOPS e2e tests with fixtures
- Windows compatibility notes

## CI Pipelines

GitHub Actions runs on every push/PR:

| Job | Description |
| - | - |
| `lock-check` | Verify uv.lock and pylock.toml are in sync |
| `lint` | Ruff check + format + mypy |
| `test` | pytest on Python 3.10-3.14 |
| `docs` | Sphinx build with warnings as errors |

### Running Locally

```bash
# All checks
tox

# Specific environment
tox -e lint
tox -e mypy
tox -e py310
tox -e docs
```

## Pre-commit Hooks

Automatic checks before each commit:

```bash
# Install hooks
pre-commit install

# Run manually
pre-commit run --all-files
```

Hooks configured:

- `ruff` - Linting
- `ruff-format` - Formatting
- `lockfile-check` - Verify lock files are current
- `tox-marker-check` - Ensures full tox suite was run

### Tox Marker System

To prevent commits without proper validation, a marker file (`.github/.tox-passed`)
is checked by pre-commit:

1. Run `make tox` or `make tox-clean` to execute the full test suite
2. **Only if ALL checks pass** → marker is created
3. **Any failure** → no marker, commit blocked
4. Pre-commit verifies the marker exists before allowing commit

This guarantees that every commit has passed the full quality gate. No shortcuts!

## Sphinx / Furo gotchas

The kstlib documentation uses [Furo](https://pradyunsg.me/furo/) for its
HTML rendering. A handful of recurring traps are worth flagging so the
next contributor does not rediscover them by surprise.

### No manual `{contents}` directive

Furo auto-generates a sidebar table of contents on the right of every
page (the "ON THIS PAGE" panel). Adding a manual `{contents}` /
`[TOC]` directive at the top of a Markdown page produces a red error
admonition in the rendered HTML and a duplicated TOC. Just write the
prose; Furo picks up the `##` / `###` headings on its own.

### Card background is theme-managed

`sphinx-design` cards (the `grid-item-card` directives on
`features/index.md`, the dropdowns on `index.md`) take their colors
from a mix of `--color-card-*` (Furo) and `--sd-color-card-*`
(sphinx-design). Both must be overridden in `_static/custom.css` to
align the cards on the rest of the kstlib palette - overriding only
one leaves a stale gray panel on hover or in some directive flavors.
See the "sphinx-design Cards" section of `_static/custom.css` for the
current overrides.

### Build the docs locally before pushing

`tox -e docs` is the source of truth. The HTML output lands in
`docs/build/html/`. Open `index.html` directly in a browser to verify
both light and dark modes (Furo exposes the toggle in the top bar).
Furo issues most styling regressions silently, so a clean log does not
imply a clean visual result.
